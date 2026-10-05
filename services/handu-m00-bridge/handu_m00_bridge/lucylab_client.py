from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx


class LucyLabError(RuntimeError):
    pass


class LucyLabSubmissionUncertain(LucyLabError):
    pass


class LucyLabExportFailed(LucyLabError):
    pass


@dataclass(slots=True)
class LucyLabExport:
    project_export_id: str
    audio_url: str
    srt_url: str


def _validate_asset_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "cdn.lucylab.io" or host.endswith(".lucylab.io")):
        raise LucyLabError("LucyLab returned an untrusted asset URL")
    return url


class LucyLabClient:
    def __init__(
        self,
        endpoint: str,
        request_headers: dict[str, str],
        *,
        poll_interval_ms: int = 2000,
        poll_timeout_ms: int = 120000,
    ) -> None:
        self.endpoint = endpoint
        self.poll_interval_ms = poll_interval_ms
        self.poll_timeout_ms = poll_timeout_ms
        self.client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=False,
            headers=request_headers,
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    async def _rpc(self, method: str, payload: dict, request_id: str) -> dict:
        try:
            response = await self.client.post(
                self.endpoint,
                json={"jsonrpc": "2.0", "method": method, "input": payload, "id": request_id},
            )
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise LucyLabSubmissionUncertain(
                f"LucyLab {method} transport outcome is uncertain: {type(exc).__name__}"
            ) from exc

        if response.status_code >= 500:
            raise LucyLabSubmissionUncertain(
                f"LucyLab {method} returned HTTP {response.status_code}; creation outcome is uncertain"
            )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise LucyLabError(f"LucyLab {method} returned a non-object response")
        error = body.get("error")
        if isinstance(error, dict):
            raise LucyLabError(str(error.get("message") or f"LucyLab {method} failed"))
        result = body.get("result")
        if not isinstance(result, dict):
            raise LucyLabError(f"LucyLab {method} response missing result")
        return result

    async def submit(self, text: str, voice_id: str, speed: float, request_id: str) -> str:
        result = await self._rpc(
            "ttsLongText",
            {"text": text, "userVoiceId": voice_id, "speed": speed},
            request_id,
        )
        export_id = result.get("projectExportId") or result.get("exportId")
        if not isinstance(export_id, str) or not export_id.strip():
            raise LucyLabError("LucyLab ttsLongText response missing projectExportId")
        return export_id.strip()

    async def get_status(self, project_export_id: str, request_id: str) -> dict:
        try:
            return await self._rpc(
                "getExportStatus",
                {"projectExportId": project_export_id},
                request_id,
            )
        except LucyLabSubmissionUncertain as exc:
            raise LucyLabError(str(exc)) from exc

    async def poll_until_done(self, project_export_id: str) -> LucyLabExport:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.poll_timeout_ms / 1000.0
        last_error = ""
        while loop.time() < deadline:
            try:
                status = await self.get_status(project_export_id, f"handu-m06-poll-{project_export_id}")
            except LucyLabError as exc:
                last_error = str(exc)
                await asyncio.sleep(max(0.25, self.poll_interval_ms / 1000.0))
                continue

            state = str(status.get("state") or "").lower()
            if state == "completed":
                audio_url = status.get("url")
                srt_url = status.get("srtUrl") or status.get("srt_url")
                if not isinstance(audio_url, str) or not audio_url:
                    raise LucyLabError("LucyLab export completed without audio URL")
                if not isinstance(srt_url, str) or not srt_url:
                    raise LucyLabError("LucyLab export completed without SRT URL")
                return LucyLabExport(
                    project_export_id,
                    _validate_asset_url(audio_url),
                    _validate_asset_url(srt_url),
                )
            if state == "failed":
                raise LucyLabExportFailed(str(status.get("error") or "LucyLab export failed"))
            await asyncio.sleep(max(0.25, self.poll_interval_ms / 1000.0))

        suffix = f": {last_error}" if last_error else ""
        raise LucyLabError(f"LucyLab export polling timed out{suffix}")

    async def download(self, url: str) -> bytes:
        trusted = _validate_asset_url(url)
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = await self.client.get(trusted, timeout=120.0)
                response.raise_for_status()
                if not response.content:
                    raise LucyLabError("LucyLab asset download returned empty content")
                return response.content
            except (httpx.HTTPError, LucyLabError) as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(float(attempt + 1))
        raise LucyLabError(f"LucyLab asset download failed: {last_error}")
