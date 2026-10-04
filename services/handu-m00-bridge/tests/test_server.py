import hashlib
import json

import pytest

from handu_m00_bridge import server
from handu_m00_bridge.dtk_client import DownloadedVideo


class FakeDtkClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        assert base_url == "http://dtk.test"
        assert api_key == "dtk-test-key"

    async def download_video(self, url: str) -> DownloadedVideo:
        assert url == "https://v.douyin.com/test"
        return DownloadedVideo(
            platform="douyin",
            content_id="1234567890123456789",
            download_id="download-1",
            filename="video.mp4",
            mime_type="video/mp4",
            payload=b"fake-mp4-bytes",
        )

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_mcp_tool_returns_manifest_and_binary_resource(monkeypatch, tmp_path):
    monkeypatch.setenv("DTK_BASE_URL", "http://dtk.test")
    monkeypatch.setenv("DTK_API_KEY", "dtk-test-key")
    monkeypatch.setenv("HANDU_M00_BRIDGE_TOKEN", "bridge-test-token")
    monkeypatch.setattr(server, "CACHE_ROOT", tmp_path)
    monkeypatch.setattr(server, "DtkClient", FakeDtkClient)

    blocks = await server.download_douyin_video("https://v.douyin.com/test")
    assert len(blocks) == 2

    manifest = json.loads(blocks[0].text)
    expected_sha = hashlib.sha256(b"fake-mp4-bytes").hexdigest()
    assert manifest["content_id"] == "1234567890123456789"
    assert manifest["sha256"] == expected_sha
    assert manifest["bytes"] == len(b"fake-mp4-bytes")

    link = blocks[1]
    assert link.name == "source.mp4"
    assert str(link.uri) == f"handu-m00://{manifest['job_id']}/source.mp4"
    assert link.mime_type == "video/mp4"
    assert link.size == len(b"fake-mp4-bytes")

    source = server.read_m00_source(manifest["job_id"])
    assert source == b"fake-mp4-bytes"
