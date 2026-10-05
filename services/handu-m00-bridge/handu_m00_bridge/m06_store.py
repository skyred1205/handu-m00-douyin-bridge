from __future__ import annotations

from typing import Any

import asyncpg


class M06StoreError(RuntimeError):
    pass


def normalize_asyncpg_dsn(value: str) -> str:
    if value.startswith("postgresql+asyncpg://"):
        return "postgresql://" + value[len("postgresql+asyncpg://") :]
    return value


class M06Store:
    def __init__(self, dsn: str) -> None:
        self.dsn = normalize_asyncpg_dsn(dsn)

    async def _connect(self) -> asyncpg.Connection:
        return await asyncpg.connect(self.dsn)

    async def ensure_schema(self) -> None:
        conn = await self._connect()
        try:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS handu_m06_exports (
                    fingerprint TEXT PRIMARY KEY,
                    text_sha256 TEXT NOT NULL,
                    voice_id TEXT NOT NULL,
                    speed DOUBLE PRECISION NOT NULL,
                    state TEXT NOT NULL,
                    project_export_id TEXT,
                    audio_url TEXT,
                    srt_url TEXT,
                    voice_sha256 TEXT,
                    voice_bytes BIGINT,
                    srt_sha256 TEXT,
                    srt_bytes BIGINT,
                    duration_ms BIGINT,
                    error TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE TABLE IF NOT EXISTS handu_m06_jobs (
                    job_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL REFERENCES handu_m06_exports(fingerprint),
                    confirmed_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
        finally:
            await conn.close()

    async def claim(
        self,
        job_id: str,
        fingerprint: str,
        text_sha256: str,
        voice_id: str,
        speed: float,
    ) -> tuple[dict[str, Any], bool]:
        await self.ensure_schema()
        conn = await self._connect()
        try:
            async with conn.transaction():
                existing_job = await conn.fetchrow(
                    "SELECT fingerprint FROM handu_m06_jobs WHERE job_id=$1 FOR UPDATE",
                    job_id,
                )
                if existing_job and existing_job["fingerprint"] != fingerprint:
                    raise M06StoreError("M06_JOB_FINGERPRINT_CONFLICT")

                inserted = await conn.fetchrow(
                    """
                    INSERT INTO handu_m06_exports(
                        fingerprint, text_sha256, voice_id, speed, state
                    ) VALUES($1,$2,$3,$4,'creation_pending')
                    ON CONFLICT (fingerprint) DO NOTHING
                    RETURNING fingerprint
                    """,
                    fingerprint,
                    text_sha256,
                    voice_id,
                    speed,
                )
                await conn.execute(
                    """
                    INSERT INTO handu_m06_jobs(job_id, fingerprint)
                    VALUES($1,$2)
                    ON CONFLICT (job_id) DO NOTHING
                    """,
                    job_id,
                    fingerprint,
                )
                row = await conn.fetchrow(
                    """
                    SELECT e.*, j.job_id, j.confirmed_at
                    FROM handu_m06_jobs j
                    JOIN handu_m06_exports e USING(fingerprint)
                    WHERE j.job_id=$1
                    """,
                    job_id,
                )
                if row is None:
                    raise M06StoreError("M06_STATE_NOT_FOUND")
                return dict(row), inserted is not None
        finally:
            await conn.close()

    async def get_for_job(self, job_id: str) -> dict[str, Any] | None:
        await self.ensure_schema()
        conn = await self._connect()
        try:
            row = await conn.fetchrow(
                """
                SELECT e.*, j.job_id, j.confirmed_at
                FROM handu_m06_jobs j
                JOIN handu_m06_exports e USING(fingerprint)
                WHERE j.job_id=$1
                """,
                job_id,
            )
            return dict(row) if row else None
        finally:
            await conn.close()

    async def set_export_id(self, fingerprint: str, project_export_id: str) -> None:
        conn = await self._connect()
        try:
            await conn.execute(
                """
                UPDATE handu_m06_exports
                SET project_export_id=$2, updated_at=now()
                WHERE fingerprint=$1
                """,
                fingerprint,
                project_export_id,
            )
        finally:
            await conn.close()

    async def mark_uncertain(self, fingerprint: str, error: str) -> None:
        conn = await self._connect()
        try:
            await conn.execute(
                """
                UPDATE handu_m06_exports
                SET state='uncertain', error=$2, updated_at=now()
                WHERE fingerprint=$1
                """,
                fingerprint,
                error[:1000],
            )
        finally:
            await conn.close()

    async def mark_failed(self, fingerprint: str, error: str) -> None:
        conn = await self._connect()
        try:
            await conn.execute(
                """
                UPDATE handu_m06_exports
                SET state='failed', error=$2, updated_at=now()
                WHERE fingerprint=$1
                """,
                fingerprint,
                error[:1000],
            )
        finally:
            await conn.close()

    async def mark_completed(
        self,
        fingerprint: str,
        *,
        project_export_id: str,
        audio_url: str,
        srt_url: str,
        voice_sha256: str,
        voice_bytes: int,
        srt_sha256: str,
        srt_bytes: int,
        duration_ms: int,
    ) -> None:
        conn = await self._connect()
        try:
            await conn.execute(
                """
                UPDATE handu_m06_exports
                SET state='completed',
                    project_export_id=$2,
                    audio_url=$3,
                    srt_url=$4,
                    voice_sha256=$5,
                    voice_bytes=$6,
                    srt_sha256=$7,
                    srt_bytes=$8,
                    duration_ms=$9,
                    error=NULL,
                    updated_at=now()
                WHERE fingerprint=$1
                """,
                fingerprint,
                project_export_id,
                audio_url,
                srt_url,
                voice_sha256,
                voice_bytes,
                srt_sha256,
                srt_bytes,
                duration_ms,
            )
        finally:
            await conn.close()

    async def confirm(self, job_id: str) -> None:
        conn = await self._connect()
        try:
            result = await conn.execute(
                "UPDATE handu_m06_jobs SET confirmed_at=now() WHERE job_id=$1",
                job_id,
            )
            if result.endswith("0"):
                raise M06StoreError("M06_JOB_NOT_FOUND")
        finally:
            await conn.close()
