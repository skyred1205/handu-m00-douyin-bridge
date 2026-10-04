from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx


class DtkError(RuntimeError):
    pass


@dataclass(frozen=True)
class DownloadedVideo:
    platform: str
    content_id: str
    download_id: str
    filename: str
    mime_type: str
    payload: bytes


class DtkClient:
    def __init__(self, base_url: str, api_key: str, *, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout),
            headers={"X-API-Key": api_key},
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _json(self, method: str, path: str, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        response = await self._client.request(method, path, **kwargs)
        try:
            body = response.json()
        except ValueError as exc:
            raise DtkError(f"DTK returned non-JSON HTTP {response.status_code} for {path}") from exc
        if response.status_code >= 400:
            err = body.get("error") if isinstance(body, dict) else None
            message = err.get("message") if isinstance(err, dict) else None
            code = err.get("code") if isinstance(err, dict) else None
            raise DtkError(f"DTK {code or response.status_code}: {message or 'request failed'}")
        if not isinstance(body, dict):
            raise DtkError(f"DTK returned an invalid envelope for {path}")
        return response.status_code, body

    @staticmethod
    def _data(envelope: dict[str, Any]) -> dict[str, Any]:
        data = envelope.get("data")
        if not isinstance(data, dict):
            raise DtkError("DTK response did not contain an object data payload")
        return data

    async def _poll_task(self, task_id: str, *, deadline_seconds: float = 90.0) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + deadline_seconds
        while True:
            _, envelope = await self._json("GET", f"/api/v1/tasks/{task_id}")
            task = self._data(envelope)
            state = str(task.get("state") or "")
            if state == "done":
                result = task.get("data")
                if not isinstance(result, dict):
                    raise DtkError("DTK task completed without an object result")
                return result
            if state == "failed":
                error = task.get("error")
                raise DtkError(f"DTK task failed: {error}")
            if loop.time() >= deadline:
                raise DtkError(f"DTK task {task_id} did not finish within {deadline_seconds:.0f}s")
            await asyncio.sleep(1.0)

    async def parse_url(self, url: str) -> dict[str, Any]:
        status, envelope = await self._json(
            "POST",
            "/api/v1/parse",
            params={"wait": 30},
            json={"url": url, "include_raw": False},
        )
        data = self._data(envelope)
        if status == 202 or (data.get("task_id") and not data.get("content_id")):
            task_id = str(data.get("task_id") or "")
            if not task_id:
                raise DtkError("DTK parse returned pending without task_id")
            data = await self._poll_task(task_id)
        platform = data.get("platform")
        content_id = data.get("content_id")
        kind = data.get("kind")
        if platform != "douyin":
            raise DtkError(f"Expected a Douyin post, got platform={platform!r}")
        if kind != "video":
            raise DtkError(f"Expected a Douyin video post, got kind={kind!r}")
        if not isinstance(content_id, str) or not content_id:
            raise DtkError("DTK parse did not return content_id")
        return data

    async def start_download(self, platform: str, content_id: str) -> str:
        _, envelope = await self._json(
            "POST",
            "/api/v1/downloads",
            json={"platform": platform, "content_id": content_id, "skip_existing": True},
        )
        data = self._data(envelope)
        download_id = data.get("download_id")
        if not isinstance(download_id, str) or not download_id:
            raise DtkError("DTK download response did not return download_id")
        return download_id

    async def _wait_download_row(self, download_id: str, *, deadline_seconds: float = 180.0) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + deadline_seconds
        while True:
            _, envelope = await self._json("GET", f"/api/v1/downloads/{download_id}")
            row = self._data(envelope)
            state = str(row.get("state") or "")
            files = row.get("files") if isinstance(row.get("files"), list) else []
            completed_video = next(
                (
                    item
                    for item in files
                    if isinstance(item, dict)
                    and item.get("state") == "done"
                    and str(item.get("name") or "").lower().endswith((".mp4", ".mov", ".webm", ".m4v"))
                ),
                None,
            )
            if state == "done" or (state == "partial" and completed_video is not None):
                if completed_video is None:
                    raise DtkError("DTK download settled without a completed video file")
                return row
            if state in {"failed", "cancelled"}:
                raise DtkError(f"DTK download {download_id} settled as {state}")
            if loop.time() >= deadline:
                raise DtkError(f"DTK download {download_id} did not finish within {deadline_seconds:.0f}s")
            await asyncio.sleep(1.0)

    async def download_video(self, url: str) -> DownloadedVideo:
        parsed = await self.parse_url(url)
        platform = str(parsed["platform"])
        content_id = str(parsed["content_id"])
        download_id = await self.start_download(platform, content_id)
        row = await self._wait_download_row(download_id)
        files = row.get("files") if isinstance(row.get("files"), list) else []
        video = next(
            item
            for item in files
            if isinstance(item, dict)
            and item.get("state") == "done"
            and str(item.get("name") or "").lower().endswith((".mp4", ".mov", ".webm", ".m4v"))
        )
        filename = str(video.get("name"))
        response = await self._client.get(f"/api/v1/downloads/{download_id}/files/{filename}")
        if response.status_code >= 400:
            raise DtkError(f"DTK could not return stored media: HTTP {response.status_code}")
        mime_type = response.headers.get("content-type", "video/mp4").split(";", 1)[0]
        return DownloadedVideo(
            platform=platform,
            content_id=content_id,
            download_id=download_id,
            filename=filename,
            mime_type=mime_type,
            payload=response.content,
        )
