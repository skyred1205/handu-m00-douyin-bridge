from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

DEFAULT_LUCYLAB_ENDPOINT = "https://api.lucylab.io/json-rpc"
DEFAULT_LUCYLAB_VOICE_ID = "cLZiqtzLcKYqwYrWJemAJK"
JOB_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}$")


class M06RuntimeError(RuntimeError):
    pass


def cache_root() -> Path:
    root = Path(os.environ.get("HANDU_M06_CACHE_DIR", "/tmp/handu-m06-cache"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def validate_job_id(job_id: str) -> None:
    if not JOB_ID_RE.fullmatch(job_id):
        raise M06RuntimeError("INVALID_JOB_ID")


def settings() -> tuple[str, dict[str, str], str, str]:
    endpoint = os.environ.get("LUCYLAB_ENDPOINT", DEFAULT_LUCYLAB_ENDPOINT).strip()
    headers_raw = os.environ.get("LUCYLAB_REQUEST_HEADERS_JSON", "").strip()
    dsn = os.environ.get("DTK_DATABASE_URL", "").strip()
    default_voice = os.environ.get("LUCYLAB_VOICE_ID", DEFAULT_LUCYLAB_VOICE_ID).strip()
    if not headers_raw:
        raise M06RuntimeError("M06_NOT_CONFIGURED")

    clean_headers: dict[str, str] = {}
    try:
        parsed = json.loads(headers_raw)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, dict):
        clean_headers = {str(k): str(v) for k, v in parsed.items() if str(k).strip()}
    elif isinstance(parsed, str) and parsed.strip():
        raw = parsed.strip()
        clean_headers = {"Authorization": raw if raw.lower().startswith("bearer ") else f"Bearer {raw}"}
    elif parsed is None:
        raw = headers_raw.strip()
        clean_headers = {"Authorization": raw if raw.lower().startswith("bearer ") else f"Bearer {raw}"}

    clean_headers.setdefault("Content-Type", "application/json")
    if not endpoint or not dsn or not default_voice or not clean_headers.get("Authorization"):
        raise M06RuntimeError("M06_HEADER_CONFIG_INVALID")
    return endpoint, clean_headers, dsn, default_voice


def fingerprint(text: str, voice_id: str, speed: float) -> tuple[str, str]:
    text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    canonical = json.dumps(
        {"text_sha256": text_sha256, "voice_id": voice_id, "speed": f"{speed:.3f}"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest(), text_sha256


def job_dir(job_id: str) -> Path:
    return cache_root() / job_id


def manifest_path(job_id: str) -> Path:
    return job_dir(job_id) / "manifest.json"


def voice_path(job_id: str) -> Path:
    return job_dir(job_id) / "voice.wav"


def srt_path(job_id: str) -> Path:
    return job_dir(job_id) / "subtitles.original.srt"
