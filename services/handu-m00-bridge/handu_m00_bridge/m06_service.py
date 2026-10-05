from __future__ import annotations

import asyncio
import json

from .lucylab_client import LucyLabClient, LucyLabError, LucyLabExportFailed, LucyLabSubmissionUncertain
from .m06_assets import materialize
from .m06_config import M06RuntimeError, fingerprint, manifest_path, settings, validate_job_id
from .m06_manifest import write_manifest
from .m06_store import M06Store, M06StoreError

_locks: dict[str, asyncio.Lock] = {}


async def synthesize(
    job_id: str,
    text: str,
    voice_id: str | None = None,
    speed: float = 1.0,
) -> dict:
    validate_job_id(job_id)
    endpoint, request_headers, dsn, default_voice = settings()

    text = text.strip()
    if not text:
        raise M06RuntimeError("EMPTY_TEXT")

    selected_voice = (voice_id or default_voice).strip()
    if not selected_voice:
        raise M06RuntimeError("EMPTY_VOICE_ID")

    speed = float(speed)
    if not 0.5 <= speed <= 2.0:
        raise M06RuntimeError("INVALID_SPEED")

    fp, text_sha256 = fingerprint(text, selected_voice, speed)
    lock = _locks.setdefault(fp, asyncio.Lock())

    async with lock:
        store = M06Store(dsn)
        try:
            record, created_new = await store.claim(
                job_id,
                fp,
                text_sha256,
                selected_voice,
                speed,
            )
        except M06StoreError as exc:
            raise M06RuntimeError(str(exc)) from exc

        state = str(record.get("state") or "")
        if state == "uncertain":
            raise M06RuntimeError("TTS_CREATION_UNCERTAIN")
        if state == "failed":
            raise M06RuntimeError(
                f"M06_PREVIOUS_EXPORT_FAILED: {record.get('error') or 'unknown'}"
            )

        client = LucyLabClient(
            endpoint,
            request_headers,
            poll_interval_ms=int(
                __import__("os").environ.get("LUCYLAB_POLL_INTERVAL_MS", "2000")
            ),
            poll_timeout_ms=int(
                __import__("os").environ.get("LUCYLAB_POLL_TIMEOUT_MS", "120000")
            ),
        )
        try:
            if state == "creation_pending" and not record.get("project_export_id"):
                if not created_new:
                    await store.mark_uncertain(
                        fp,
                        "creation_pending row has no recoverable project_export_id",
                    )
                    raise M06RuntimeError("TTS_CREATION_UNCERTAIN")

                try:
                    export_id = await client.submit(
                        text,
                        selected_voice,
                        speed,
                        f"handu-m06-submit-{fp[:16]}",
                    )
                except LucyLabSubmissionUncertain as exc:
                    await store.mark_uncertain(fp, str(exc))
                    raise M06RuntimeError("TTS_CREATION_UNCERTAIN") from exc
                except LucyLabError as exc:
                    await store.mark_failed(fp, str(exc))
                    raise M06RuntimeError(f"LUCYLAB_SUBMIT_FAILED: {exc}") from exc

                await store.set_export_id(fp, export_id)
                record = await store.get_for_job(job_id)
                if record is None:
                    raise M06RuntimeError("M06_STATE_MISSING_AFTER_SUBMISSION")

            try:
                record = await materialize(job_id, record, client, store)
            except LucyLabExportFailed as exc:
                await store.mark_failed(fp, str(exc))
                raise M06RuntimeError(f"LUCYLAB_EXPORT_FAILED: {exc}") from exc
            except LucyLabError as exc:
                raise M06RuntimeError(
                    f"LUCYLAB_EXPORT_PENDING_OR_UNAVAILABLE: {exc}"
                ) from exc
        finally:
            await client.aclose()

        return write_manifest(record)


async def get_manifest(job_id: str) -> dict:
    validate_job_id(job_id)
    path = manifest_path(job_id)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    _, _, dsn, _ = settings()
    record = await M06Store(dsn).get_for_job(job_id)
    if record is None:
        raise M06RuntimeError("M06_JOB_NOT_FOUND")
    return write_manifest(record)


async def confirm(job_id: str, voice_sha256: str, duration_ms: int) -> dict:
    validate_job_id(job_id)
    _, _, dsn, _ = settings()
    store = M06Store(dsn)
    record = await store.get_for_job(job_id)

    if record is None or record.get("state") != "completed":
        raise M06RuntimeError("M06_NOT_READY_FOR_CONFIRMATION")
    if str(record.get("voice_sha256") or "") != voice_sha256.strip().lower():
        raise M06RuntimeError("M06_CONFIRM_SHA_MISMATCH")
    if int(record.get("duration_ms") or -1) != int(duration_ms):
        raise M06RuntimeError("M06_CONFIRM_DURATION_MISMATCH")

    await store.confirm(job_id)
    refreshed = await store.get_for_job(job_id)
    if refreshed is None:
        raise M06RuntimeError("M06_STATE_MISSING_AFTER_CONFIRMATION")
    return write_manifest(refreshed)
