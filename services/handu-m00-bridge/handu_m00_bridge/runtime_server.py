from __future__ import annotations

import json
import os
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ResourceLink, TextContent
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from . import m06_service
from .m06_config import DEFAULT_LUCYLAB_VOICE_ID, M06RuntimeError, srt_path, voice_path
from .server import (
    BearerTokenMiddleware,
    download_douyin_video as run_m00_download,
    get_m00_manifest as run_m00_manifest,
    read_m00_source as run_m00_source,
)

mcp = MCPServer("HANDU Runtime Bridge")


@mcp.tool()
async def download_douyin_video(url: str):
    """Run the verified Railway M00 Douyin intake."""
    return await run_m00_download(url)


@mcp.tool()
def get_m00_manifest(job_id: str) -> dict[str, Any]:
    """Return the verified M00 manifest."""
    return run_m00_manifest(job_id)


@mcp.resource("handu-m00://{job_id}/source.mp4", mime_type="video/mp4")
def read_m00_source(job_id: str) -> bytes:
    """Read the verified M00 source MP4."""
    return run_m00_source(job_id)


@mcp.tool()
async def synthesize_lucylab_voice(
    job_id: str,
    text: str,
    voice_id: str = DEFAULT_LUCYLAB_VOICE_ID,
    speed: float = 1.0,
) -> list[TextContent | ResourceLink]:
    """Create or safely reuse one exact-script LucyLab M06 export."""
    try:
        manifest = await m06_service.synthesize(job_id, text, voice_id, speed)
    except M06RuntimeError as exc:
        return [TextContent(type="text", text=f"M06 failed: {exc}")]

    return [
        TextContent(type="text", text=json.dumps(manifest, ensure_ascii=False)),
        ResourceLink(
            name="voice.wav",
            uri=f"handu-m06://{job_id}/voice.wav",
            description="Canonical LucyLab M06 WAV for HANDU",
            mime_type="audio/wav",
            size=int(manifest.get("voice_bytes") or 0),
        ),
        ResourceLink(
            name="subtitles.original.srt",
            uri=f"handu-m06://{job_id}/subtitles.original.srt",
            description="LucyLab timing SRT for HANDU M06",
            mime_type="application/x-subrip",
            size=int(manifest.get("srt_bytes") or 0),
        ),
    ]


@mcp.tool()
async def get_m06_manifest(job_id: str) -> dict[str, Any]:
    """Return M06 state without creating another paid export."""
    return await m06_service.get_manifest(job_id)


@mcp.tool()
async def confirm_m06(job_id: str, voice_sha256: str, duration_ms: int) -> dict[str, Any]:
    """Confirm locally verified M06 evidence before M07."""
    return await m06_service.confirm(job_id, voice_sha256, duration_ms)


@mcp.resource("handu-m06://{job_id}/voice.wav", mime_type="audio/wav")
def read_m06_voice(job_id: str) -> bytes:
    path = voice_path(job_id)
    if not path.exists():
        raise FileNotFoundError(f"Unknown M06 voice: {job_id}")
    return path.read_bytes()


@mcp.resource("handu-m06://{job_id}/subtitles.original.srt", mime_type="application/x-subrip")
def read_m06_srt(job_id: str) -> bytes:
    path = srt_path(job_id)
    if not path.exists():
        raise FileNotFoundError(f"Unknown M06 SRT: {job_id}")
    return path.read_bytes()


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> Response:
    m00_configured = all(
        os.environ.get(key, "").strip()
        for key in ("DTK_BASE_URL", "DTK_API_KEY", "HANDU_M00_BRIDGE_TOKEN")
    )
    m06_configured = bool(
        os.environ.get("LUCYLAB_REQUEST_HEADERS_JSON", "").strip()
        and os.environ.get("DTK_DATABASE_URL", "").strip()
    )
    return JSONResponse(
        {
            "status": "ok" if m00_configured else "misconfigured",
            "service": "handu-runtime-bridge",
            "capabilities": {"m00": bool(m00_configured), "m06": m06_configured},
        },
        status_code=200 if m00_configured else 503,
    )


security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
app = BearerTokenMiddleware(
    mcp.streamable_http_app(stateless_http=True, transport_security=security)
)
