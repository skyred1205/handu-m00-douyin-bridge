import httpx
import pytest

from handu_m00_bridge.dtk_client import DtkClient


@pytest.mark.asyncio
async def test_download_flow(monkeypatch):
    calls = []
    state = {"download_poll": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/v1/parse":
            return httpx.Response(200, json={"data": {"platform": "douyin", "content_id": "1234567890123456789", "kind": "video"}})
        if request.url.path == "/api/v1/downloads" and request.method == "POST":
            return httpx.Response(202, json={"data": {"download_id": "d1", "state": "queued"}})
        if request.url.path == "/api/v1/downloads/d1":
            state["download_poll"] += 1
            if state["download_poll"] == 1:
                return httpx.Response(200, json={"data": {"state": "running", "files": []}})
            return httpx.Response(200, json={"data": {"state": "done", "files": [{"name": "video.mp4", "state": "done"}]}})
        if request.url.path == "/api/v1/downloads/d1/files/video.mp4":
            return httpx.Response(200, content=b"video-bytes", headers={"content-type": "video/mp4"})
        return httpx.Response(404, json={"error": {"code": "NOT_FOUND", "message": "no"}})

    client = DtkClient("https://dtk.example", "secret")
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        base_url="https://dtk.example",
        transport=httpx.MockTransport(handler),
        headers={"X-API-Key": "secret"},
    )
    monkeypatch.setattr("handu_m00_bridge.dtk_client.asyncio.sleep", lambda *_: _noop())
    result = await client.download_video("https://v.douyin.com/test")
    await client.aclose()
    assert result.payload == b"video-bytes"
    assert result.filename == "video.mp4"
    assert result.content_id == "1234567890123456789"
    assert calls[0] == ("POST", "/api/v1/parse")


async def _noop():
    return None
