from __future__ import annotations

import wave
from pathlib import Path

from .m06_config import M06RuntimeError


def wav_duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as wav:
        frames = wav.getnframes()
        rate = wav.getframerate()
        if rate <= 0:
            raise M06RuntimeError("INVALID_WAV_SAMPLE_RATE")
        return int(round(frames * 1000 / rate))
