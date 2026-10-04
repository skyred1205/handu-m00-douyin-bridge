from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

DTK_HOST = "127.0.0.1"
DTK_PORT = 8001
DTK_BASE_URL = f"http://{DTK_HOST}:{DTK_PORT}"
DOWNLOADER_BIND = "127.0.0.1:9100"
DOWNLOADER_URL = "http://127.0.0.1:9100"
RUNTIME_KEY_NAME = "handu-m00-runtime"


class GatewayError(RuntimeError):
    pass


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise GatewayError(f"required environment variable {name} is missing")
    return value


def base_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "DTK_BIND_HOST": DTK_HOST,
            "DTK_BIND_PORT": str(DTK_PORT),
            "DTK_MEDIA_DIR": "/var/lib/dtk/media",
            "DTK_DOWNLOADER_BIND": DOWNLOADER_BIND,
            "DTK_DOWNLOADER_ROOT": "/var/lib/dtk/media",
            "DTK_DOWNLOADER_URL": DOWNLOADER_URL,
            "HANDU_M00_CACHE_DIR": "/var/lib/handu/m00-cache",
        }
    )
    return env


def run_checked(args: list[str], *, env: dict[str, str], stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        input=stdin,
        text=True,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        tail = "\n".join(result.stdout.splitlines()[-12:])
        raise GatewayError(f"{' '.join(args)} failed with exit {result.returncode}:\n{tail}")
    return result


def try_create_admin(env: dict[str, str], username: str, password: str) -> None:
    result = subprocess.run(
        ["dtk", "user", "create", username, "--role", "admin", "--stdin"],
        input=password + "\n",
        text=True,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=90,
        check=False,
    )
    if result.returncode == 0:
        print("gateway bootstrap: administrator created", flush=True)
        return
    # Existing installations legitimately refuse a duplicate. Login below is
    # the authoritative check that the configured bootstrap credentials still work.
    print("gateway bootstrap: administrator create skipped; verifying login", flush=True)


def wait_http(url: str, *, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=3.0)
            if response.status_code < 500:
                return
            last = f"HTTP {response.status_code}"
        except Exception as exc:
            last = type(exc).__name__
        time.sleep(1.0)
    raise GatewayError(f"service did not become ready at {url}: {last}")


def envelope_data(response: httpx.Response) -> Any:
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or "data" not in body:
        raise GatewayError(f"unexpected DTK response from {response.request.url}")
    return body["data"]


def issue_runtime_key(username: str, password: str) -> str:
    with httpx.Client(base_url=DTK_BASE_URL, timeout=15.0) as client:
        login = client.post("/api/v1/auth/login", json={"username": username, "password": password})
        envelope_data(login)

        listed = envelope_data(client.get("/api/v1/admin/api-keys"))
        if isinstance(listed, list):
            for item in listed:
                if not isinstance(item, dict):
                    continue
                if item.get("name") != RUNTIME_KEY_NAME or item.get("status") != "active":
                    continue
                key_id = item.get("id")
                if isinstance(key_id, str) and key_id:
                    envelope_data(client.delete(f"/api/v1/admin/api-keys/{key_id}"))

        created = envelope_data(
            client.post(
                "/api/v1/admin/api-keys",
                json={
                    "name": RUNTIME_KEY_NAME,
                    "scopes": ["douyin:read", "media:read", "media:write"],
                    "rate_limit": 600,
                    "expires_at": None,
                },
            )
        )
        if not isinstance(created, dict) or not isinstance(created.get("key"), str):
            raise GatewayError("DTK did not return the one-time runtime API key")
        return created["key"]


def spawn(args: list[str], *, env: dict[str, str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(args, env=env)


def terminate(children: list[subprocess.Popen[bytes]]) -> None:
    for child in children:
        if child.poll() is None:
            child.terminate()
    deadline = time.monotonic() + 20
    for child in children:
        if child.poll() is not None:
            continue
        remaining = max(0.1, deadline - time.monotonic())
        try:
            child.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            child.kill()


def main() -> int:
    username = required("HANDU_DTK_ADMIN_USERNAME")
    password = required("HANDU_DTK_ADMIN_PASSWORD")
    required("HANDU_M00_BRIDGE_TOKEN")
    required("DTK_SECRET_KEY")
    required("DTK_DATABASE_URL")
    required("DTK_REDIS_URL")
    env = base_env()

    Path("/var/lib/dtk/media").mkdir(parents=True, exist_ok=True)
    Path("/var/lib/handu/m00-cache").mkdir(parents=True, exist_ok=True)

    print("gateway bootstrap: migrating database", flush=True)
    run_checked(["dtk", "migrate"], env=env)
    try_create_admin(env, username, password)

    children: list[subprocess.Popen[bytes]] = []
    stopping = False

    def stop_handler(_signum: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True
        terminate(children)

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)

    try:
        children.append(spawn(["/usr/local/bin/downloader"], env=env))
        children.append(spawn(["dtk-entrypoint", "api"], env=env))
        wait_http(f"{DTK_BASE_URL}/readyz")
        print("gateway bootstrap: DTK API ready", flush=True)

        api_key = issue_runtime_key(username, password)
        print("gateway bootstrap: scoped runtime key issued", flush=True)

        children.append(spawn(["dtk-entrypoint", "worker"], env=env))

        bridge_env = dict(env)
        bridge_env["DTK_BASE_URL"] = DTK_BASE_URL
        bridge_env["DTK_API_KEY"] = api_key
        port = required("PORT")
        children.append(
            spawn(
                [
                    "uvicorn",
                    "handu_m00_bridge.server:app",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    port,
                    "--proxy-headers",
                    "--forwarded-allow-ips=*",
                ],
                env=bridge_env,
            )
        )
        wait_http(f"http://127.0.0.1:{port}/health", timeout=60)
        print("gateway ready: HANDU M00 MCP bridge healthy", flush=True)

        while not stopping:
            for child in children:
                code = child.poll()
                if code is not None:
                    raise GatewayError(f"child process exited unexpectedly with code {code}: {child.args}")
            time.sleep(1.0)
        return 0
    finally:
        terminate(children)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GatewayError as exc:
        print(f"gateway error: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
