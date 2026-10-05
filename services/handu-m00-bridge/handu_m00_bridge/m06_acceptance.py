from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import time
import wave

import asyncpg
import httpx

TEST_JOB_ID = "m06-live-test-20261005-01"
TEST_TEXT = "Xin chào, đây là bài kiểm tra giọng Chi Mai cho hệ thống HANDU trên Railway."
VOICE_ID = "cLZiqtzLcKYqwYrWJemAJK"
SPEED = 1.0


def decode_mcp_response(response: httpx.Response, expected_id: int | None = None):
    response.raise_for_status()
    body = response.text
    if not body.strip():
        return None
    if "application/json" in response.headers.get("content-type", ""):
        return response.json()
    messages = []
    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload:
            messages.append(json.loads(payload))
    if expected_id is not None:
        for message in messages:
            if message.get("id") == expected_id:
                return message
    return messages[0] if messages else None


async def rpc(client: httpx.AsyncClient, endpoint: str, token: str, request_id: int, method: str, params: dict, protocol: str | None = None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if protocol:
        headers["MCP-Protocol-Version"] = protocol
    response = await client.post(
        endpoint,
        headers=headers,
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
        timeout=180.0,
    )
    message = decode_mcp_response(response, request_id)
    if not message:
        raise RuntimeError(f"empty MCP response for {method}")
    if message.get("error"):
        raise RuntimeError(f"MCP {method} error: {message['error']}")
    return message["result"]


async def notify(client: httpx.AsyncClient, endpoint: str, token: str, method: str, params: dict, protocol: str):
    response = await client.post(
        endpoint,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": protocol,
        },
        json={"jsonrpc": "2.0", "method": method, "params": params},
        timeout=30.0,
    )
    if response.status_code not in (200, 202):
        raise RuntimeError(f"notification {method} failed HTTP {response.status_code}")


def tool_manifest(result: dict) -> dict:
    for item in result.get("content", []):
        if item.get("type") == "text" and isinstance(item.get("text"), str):
            text = item["text"]
            if text.startswith("M06 failed:"):
                raise RuntimeError(text)
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                continue
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    raise RuntimeError("M06 tool response did not contain a manifest")


async def read_resource(client: httpx.AsyncClient, endpoint: str, token: str, uri: str, request_id: int, protocol: str) -> bytes:
    result = await rpc(client, endpoint, token, request_id, "resources/read", {"uri": uri}, protocol)
    contents = result.get("contents") or []
    if not contents or not contents[0].get("blob"):
        raise RuntimeError(f"missing binary blob for {uri}")
    return base64.b64decode(contents[0]["blob"])


def wav_duration_ms(payload: bytes) -> int:
    with wave.open(io.BytesIO(payload), "rb") as wav:
        if wav.getnframes() <= 0 or wav.getframerate() <= 0:
            raise RuntimeError("invalid WAV metadata")
        return round(wav.getnframes() * 1000 / wav.getframerate())


async def database_count(fingerprint: str) -> int:
    dsn = os.environ["DTK_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
    conn = await asyncpg.connect(dsn)
    try:
        value = await conn.fetchval(
            "SELECT count(*) FROM handu_m06_exports WHERE fingerprint=$1",
            fingerprint,
        )
        return int(value or 0)
    finally:
        await conn.close()


async def run_acceptance(port: int) -> dict:
    token = os.environ["HANDU_M00_BRIDGE_TOKEN"]
    endpoint = f"http://127.0.0.1:{port}/mcp"
    health_url = f"http://127.0.0.1:{port}/health"

    async with httpx.AsyncClient() as client:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                health = await client.get(health_url, timeout=2.0)
                if health.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.5)
        else:
            raise RuntimeError("M06 server did not become healthy")

        init = await rpc(
            client,
            endpoint,
            token,
            1,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "handu-m06-acceptance", "version": "1.0.0"},
            },
        )
        protocol = init["protocolVersion"]
        await notify(client, endpoint, token, "notifications/initialized", {}, protocol)

        listed = await rpc(client, endpoint, token, 2, "tools/list", {}, protocol)
        tool_names = [tool["name"] for tool in listed.get("tools", [])]
        required = {"synthesize_lucylab_voice", "get_m06_manifest", "confirm_m06"}
        if not required.issubset(set(tool_names)):
            raise RuntimeError(f"missing MCP tools: {sorted(required - set(tool_names))}")

        first_result = await rpc(
            client,
            endpoint,
            token,
            3,
            "tools/call",
            {
                "name": "synthesize_lucylab_voice",
                "arguments": {
                    "job_id": TEST_JOB_ID,
                    "text": TEST_TEXT,
                    "voice_id": VOICE_ID,
                    "speed": SPEED,
                },
            },
            protocol,
        )
        first = tool_manifest(first_result)

        voice_uri = f"handu-m06://{TEST_JOB_ID}/voice.wav"
        srt_uri = f"handu-m06://{TEST_JOB_ID}/subtitles.original.srt"
        voice = await read_resource(client, endpoint, token, voice_uri, 4, protocol)
        srt = await read_resource(client, endpoint, token, srt_uri, 5, protocol)
        srt_text = srt.decode("utf-8", errors="strict").strip()

        voice_sha = hashlib.sha256(voice).hexdigest()
        local_duration = wav_duration_ms(voice)
        checks = {
            "voice_nonempty": len(voice) > 44,
            "srt_nonempty": bool(srt_text),
            "srt_has_timestamps": "-->" in srt_text,
            "sha_match": voice_sha == first.get("voice_sha256"),
            "bytes_match": len(voice) == int(first.get("voice_bytes") or -1),
            "duration_delta_ms": abs(local_duration - int(first.get("duration_ms") or -999999)),
        }
        if not all(
            [
                checks["voice_nonempty"],
                checks["srt_nonempty"],
                checks["srt_has_timestamps"],
                checks["sha_match"],
                checks["bytes_match"],
                checks["duration_delta_ms"] <= 10,
            ]
        ):
            raise RuntimeError(f"local verification failed: {checks}")

        confirm_result = await rpc(
            client,
            endpoint,
            token,
            6,
            "tools/call",
            {
                "name": "confirm_m06",
                "arguments": {
                    "job_id": TEST_JOB_ID,
                    "voice_sha256": voice_sha,
                    "duration_ms": int(first["duration_ms"]),
                },
            },
            protocol,
        )
        confirmed = tool_manifest(confirm_result)
        if confirmed.get("status") != "M06_PASS":
            raise RuntimeError(f"confirm_m06 status is not M06_PASS: {confirmed.get('status')}")

        second_result = await rpc(
            client,
            endpoint,
            token,
            7,
            "tools/call",
            {
                "name": "synthesize_lucylab_voice",
                "arguments": {
                    "job_id": TEST_JOB_ID,
                    "text": TEST_TEXT,
                    "voice_id": VOICE_ID,
                    "speed": SPEED,
                },
            },
            protocol,
        )
        second = tool_manifest(second_result)

        fingerprint_rows = await database_count(first["fingerprint"])
        idempotency = {
            "same_fingerprint": first.get("fingerprint") == second.get("fingerprint"),
            "same_project_export_id": first.get("project_export_id") == second.get("project_export_id"),
            "same_voice_sha256": first.get("voice_sha256") == second.get("voice_sha256"),
            "fingerprint_rows": fingerprint_rows,
        }
        if not all(
            [
                idempotency["same_fingerprint"],
                idempotency["same_project_export_id"],
                idempotency["same_voice_sha256"],
                fingerprint_rows == 1,
            ]
        ):
            raise RuntimeError(f"idempotency verification failed: {idempotency}")

        return {
            "pass": True,
            "job_id": TEST_JOB_ID,
            "voice_id": VOICE_ID,
            "project_export_id": first.get("project_export_id"),
            "fingerprint": first.get("fingerprint"),
            "voice_bytes": len(voice),
            "voice_sha256": voice_sha,
            "duration_ms": int(first["duration_ms"]),
            "srt_bytes": len(srt),
            "confirm_status": confirmed.get("status"),
            "checks": checks,
            "idempotency": idempotency,
            "protocol_version": protocol,
            "tool_count": len(tool_names),
        }


def main() -> int:
    port = int(os.environ.get("PORT", "8080"))
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "handu_m00_bridge.m06_server:app",
            "--host",
            "0.0.0.0",
            "--port",
            str(port),
            "--proxy-headers",
        ]
    )
    try:
        result = asyncio.run(run_acceptance(port))
        print("M06_LIVE_ACCEPTANCE " + json.dumps(result, ensure_ascii=False), flush=True)
        return server.wait()
    except Exception as exc:
        print(f"M06_LIVE_ACCEPTANCE_ERROR {type(exc).__name__}: {exc}", flush=True)
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
