"""Direct WAV serialization obeys the same finite cache-size contract."""

from __future__ import annotations

import io
import wave

import numpy as np
import pytest

from pdf2audiobook.audio import wav_bytes
from pdf2audiobook.errors import AudioError


def test_broadcast_view_above_wav_limit_is_rejected_before_materialization() -> None:
    # A zero-stride view represents >128 MiB of PCM with just one stored float.
    # If the size guard is absent, this fixture would allocate huge PCM arrays.
    samples = np.broadcast_to(
        np.zeros(1, dtype=np.float32),
        ((128 * 1024 * 1024 - 44) // 2 + 1,),
    )
    assert samples.nbytes > 128 * 1024 * 1024
    with pytest.raises(AudioError, match="safe WAV cache limit"):
        wav_bytes(samples, 24000)


def test_small_direct_wav_is_still_valid_mono_pcm() -> None:
    data = wav_bytes(np.array([0.0, 0.5, -0.5], dtype=np.float32), 24000)
    with wave.open(io.BytesIO(data), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getframerate() == 24000
        assert handle.getsampwidth() == 2
        assert handle.getnframes() == 3
        assert len(handle.readframes(3)) == 6
