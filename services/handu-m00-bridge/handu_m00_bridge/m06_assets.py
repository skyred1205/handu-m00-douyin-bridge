from __future__ import annotations

import hashlib

from .lucylab_client import LucyLabClient
from .m06_audio import wav_duration_ms
from .m06_config import M06RuntimeError, job_dir, srt_path, voice_path
from .m06_store import M06Store
from .m06_transcode import provider_audio_to_wav


async def materialize(job_id: str, record: dict, client: LucyLabClient, store: M06Store) -> dict:
    voice = voice_path(job_id)
    srt = srt_path(job_id)
    if (
        record.get("state") == "completed"
        and voice.exists()
        and srt.exists()
        and voice.stat().st_size > 44
        and srt.stat().st_size > 0
    ):
        return record

    export_id = str(record.get("project_export_id") or "")
    if not export_id:
        raise M06RuntimeError("TTS_CREATION_UNCERTAIN")

    exported = await client.poll_until_done(export_id)
    provider_audio = await client.download(exported.audio_url)
    subtitles = await client.download(exported.srt_url)
    if not subtitles.strip():
        raise M06RuntimeError("EMPTY_SRT")

    wav_bytes = provider_audio_to_wav(provider_audio)
    directory = job_dir(job_id)
    directory.mkdir(parents=True, exist_ok=True)
    voice.write_bytes(wav_bytes)
    srt.write_bytes(subtitles)

    await store.mark_completed(
        record["fingerprint"],
        project_export_id=exported.project_export_id,
        audio_url=exported.audio_url,
        srt_url=exported.srt_url,
        voice_sha256=hashlib.sha256(wav_bytes).hexdigest(),
        voice_bytes=len(wav_bytes),
        srt_sha256=hashlib.sha256(subtitles).hexdigest(),
        srt_bytes=len(subtitles),
        duration_ms=wav_duration_ms(voice),
    )
    refreshed = await store.get_for_job(job_id)
    if refreshed is None:
        raise M06RuntimeError("M06_STATE_MISSING_AFTER_COMPLETION")
    return refreshed
