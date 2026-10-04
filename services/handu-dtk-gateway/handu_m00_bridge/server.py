from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ResourceLink, TextContent
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .dtk_client import DtkClient, DtkError

CACHE_ROOT = Path(os.environ.get("HANDU_M00_CACHE_DIR", "/tmp/handu-m00-cache"))
CACHE_ROOT.mkdir(parents=True, exist_ok=True)

mcp = MCPServer("HANDU M00 Douyin Bridge")


def _settings() -> tuple[str, str, str]:
    base_url = os.environ.get("DTK_BASE_URL", "").strip()
    api_key = os.environ.get("DTK_API_KEY", "").strip()
    bridge_token = os.environ.get("HANDU_M00_BRIDGE_TOKEN", "").strip()
    if not base_url or not api_key or not bridge_token:
        raise RuntimeError("DTK_BASE_URL, DTK_API_KEY and HANDU_M00_BRIDGE_TOKEN are required")
    return base_url, api_key, bridge_token


def _job_id(source_url: str, content_id: str) -> str:
    digest = hashlib.sha256(f"{source_url}\0{content_id}".encode()).hexdigest()[:20]
    return f"handu-m00-{digest}"


def _manifest_path(job_id: str) -> Path:
    return CACHE_ROOT / job_id / "manifest.json"


def _source_path(job_id: str) -> Path:
    return CACHE_ROOT / job_id / "source.mp4"


@mcp.tool()
async def download_douyin_video(url: str) -> list[TextContent | ResourceLink]:
    """Resolve a Douyin share URL, download the watermark-free MP4, and return source.mp4 for HANDU M00."""
    base_url, api_key, _ = _settings()
    client = DtkClient(base_url, api_key)
    try:
        downloaded = await client.download_video(url)
    except DtkError as exc:
        return [TextContent(type="text", text=f"M00 failed: {exc}")]
    finally:
        await client.aclose()

    if not downloaded.filename.lower().endswith(".mp4"):
        return [TextContent(type="text", text=f"M00 failed: DTK returned unsupported video container {downloaded.filename}")]
    if not downloaded.payload:
        return [TextContent(type="text", text="M00 failed: downloaded source is empty")]

    job_id = _job_id(url, downloaded.content_id)
    job_dir = CACHE_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    source = _source_path(job_id)
    source.write_bytes(downloaded.payload)
    sha256 = hashlib.sha256(downloaded.payload).hexdigest()
    manifest = {
        "job_id": job_id,
        "source_url": url,
        "platform": downloaded.platform,
        "content_id": downloaded.content_id,
        "download_id": downloaded.download_id,
        "filename": "source.mp4",
        "mime_type": "video/mp4",
        "bytes": len(downloaded.payload),
        "sha256": sha256,
        "backend": "Evil0ctal/Douyin_TikTok_Download_API",
    }
    _manifest_path(job_id).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    uri = f"handu-m00://{job_id}/source.mp4"
    return [
        TextContent(type="text", text=json.dumps(manifest, ensure_ascii=False)),
        ResourceLink(
            name="source.mp4",
            uri=uri,
            description="Watermark-free Douyin source video for HANDU M00",
            mime_type="video/mp4",
            size=len(downloaded.payload),
        ),
    ]


@mcp.tool()
def get_m00_manifest(job_id: str) -> dict[str, Any]:
    """Return the cached HANDU M00 intake manifest for a job."""
    path = _manifest_path(job_id)
    if not path.exists():
        raise FileNotFoundError(f"Unknown M00 job: {job_id}")
    return json.loads(path.read_text(encoding="utf-8"))


@mcp.resource("handu-m00://{job_id}/source.mp4", mime_type="video/mp4")
def read_m00_source(job_id: str) -> bytes:
    """Read the cached source MP4 for a completed M00 job."""
    path = _source_path(job_id)
    if not path.exists():
        raise FileNotFoundError(f"Unknown M00 source: {job_id}")
    return path.read_bytes()


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> Response:
    configured = all(
        os.environ.get(key, "").strip()
        for key in ("DTK_BASE_URL", "DTK_API_KEY", "HANDU_M00_BRIDGE_TOKEN")
    )
    return JSONResponse(
        {"status": "ok" if configured else "misconfigured", "service": "handu-m00-bridge"},
        status_code=200 if configured else 503,
    )


class BearerTokenMiddleware:
    """Small ASGI bearer gate. Health remains public; every other HTTP route requires the bridge token."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("path") == "/health":
            await self.inner(scope, receive, send)
            return
        expected = os.environ.get("HANDU_M00_BRIDGE_TOKEN", "").strip()
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        supplied = headers.get(b"authorization", b"").decode("latin-1")
        if not expected:
            status, body = 503, b"bridge token is not configured"
        elif not secrets.compare_digest(supplied, f"Bearer {expected}"):
            status, body = 401, b"unauthorized"
        else:
            await self.inner(scope, receive, send)
            return
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"text/plain; charset=utf-8"), (b"www-authenticate", b"Bearer")],
            }
        )
        await send({"type": "http.response.body", "body": body})


security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
app = BearerTokenMiddleware(mcp.streamable_http_app(stateless_http=True, transport_security=security))