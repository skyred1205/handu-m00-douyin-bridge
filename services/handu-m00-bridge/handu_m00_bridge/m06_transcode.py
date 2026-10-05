from __future__ import annotations

import io

import av

from .m06_config import M06RuntimeError


def provider_audio_to_wav(payload: bytes) -> bytes:
    source_buffer = io.BytesIO(payload)
    output_buffer = io.BytesIO()

    source = av.open(source_buffer, mode="r")
    try:
        output = av.open(output_buffer, mode="w", format="wav")
        try:
            stream = output.add_stream("pcm_s16le", rate=48000)
            stream.layout = "mono"
            resampler = av.AudioResampler(format="s16", layout="mono", rate=48000)

            decoded = False
            for frame in source.decode(audio=0):
                decoded = True
                for converted in resampler.resample(frame):
                    for packet in stream.encode(converted):
                        output.mux(packet)

            for converted in resampler.resample(None):
                for packet in stream.encode(converted):
                    output.mux(packet)
            for packet in stream.encode(None):
                output.mux(packet)

            if not decoded:
                raise M06RuntimeError("PROVIDER_AUDIO_HAS_NO_AUDIO_STREAM")
        finally:
            output.close()
    finally:
        source.close()

    result = output_buffer.getvalue()
    if len(result) <= 44:
        raise M06RuntimeError("WAV_CANONICALIZATION_FAILED")
    return result
