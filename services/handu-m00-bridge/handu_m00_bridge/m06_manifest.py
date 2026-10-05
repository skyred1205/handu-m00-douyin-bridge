from __future__ import annotations

import json
from typing import Any

from .m06_config import manifest_path


def record_manifest(record: dict[str, Any]) -> dict[str, Any]:
    confirmed = record.get("confirmed_at") is not None
    state = str(record.get("state") or "")
    if confirmed:
        status = "M06_PASS"
    elif state == "completed":
        status = "M06_READY_NEEDS_LOCAL_VERIFY"
    else:
        status = state
    return {
        "job_id": record["job_id"],
        "module": "M06",
        "status": status,
        "fingerprint": record["fingerprint"],
        "text_sha256": record["text_sha256"],
        "voice_id": record["voice_id"],
        "speed": float(record["speed"]),
        "project_export_id": record.get("project_export_id"),
        "voice_filename": "voice.wav",
        "voice_mime_type": "audio/wav",
        "voice_bytes": record.get("voice_bytes"),
        "voice_sha256": record.get("voice_sha256"),
        "srt_filename": "subtitles.original.srt",
        "srt_mime_type": "application/x-subrip",
        "srt_bytes": record.get("srt_bytes"),
        "srt_sha256": record.get("srt_sha256"),
        "duration_ms": record.get("duration_ms"),
        "provider": "LucyLab",
        "confirmed": confirmed,
    }


def write_manifest(record: dict[str, Any]) -> dict[str, Any]:
    manifest = record_manifest(record)
    path = manifest_path(record["job_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
