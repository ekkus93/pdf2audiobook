"""Long chapter encoding must not inherit the short TTS cache WAV limit."""

import gc
import shutil
import tracemalloc
import wave

import numpy as np
import pytest

from pdf2audiobook import audio as audio_module
from pdf2audiobook.audio import encode_mp3, synthesize_chunks, wav_bytes
from pdf2audiobook.audio import encoding as audio_encoding
from pdf2audiobook.audio import synthesis as audio_synthesis
from pdf2audiobook.audio import wav as audio_wav
from pdf2audiobook.errors import AudioError


class _StreamingProvider:
    sample_rate = 24000

    def generate(self, text, *, voice, speed):
        return np.full(24000, 0.05, dtype=np.float32)


def test_synthesis_can_stream_chunks_directly_to_wav(tmp_path):
    chapter = "\n\n".join(f"Sentence number {index} ends here." for index in range(8))
    output = tmp_path / "streamed.wav"
    result = synthesize_chunks(
        chapter,
        _StreamingProvider(),
        model="synthetic",
        voice="default",
        speed=1.0,
        pause_ms=0,
        cache=tmp_path / "cache",
        use_cache=False,
        output_wav=output,
    )
    assert result == output
    with wave.open(str(output), "rb") as reader:
        assert reader.getnchannels() == 1
        assert reader.getframerate() == 24000
        assert reader.getnframes() >= 8 * 24000


def test_streaming_peak_memory_does_not_grow_with_chapter_length(tmp_path):
    # Exclude one-time interpreter/NumPy initialization from the size comparison.
    warmup_text = "\n\n".join(f"Sentence number {index} ends here." for index in range(40))
    synthesize_chunks(
        warmup_text,
        _StreamingProvider(),
        model="synthetic",
        voice="default",
        speed=1.0,
        pause_ms=0,
        cache=tmp_path / "cache-warmup",
        use_cache=False,
        output_wav=tmp_path / "streamed-warmup.wav",
    )
    peaks = []
    for chunk_count in (10, 40):
        chapter = "\n\n".join(f"Sentence number {index} ends here." for index in range(chunk_count))
        tracemalloc.start()
        synthesize_chunks(
            chapter,
            _StreamingProvider(),
            model="synthetic",
            voice="default",
            speed=1.0,
            pause_ms=0,
            cache=tmp_path / f"cache-{chunk_count}",
            use_cache=False,
            output_wav=tmp_path / f"streamed-{chunk_count}.wav",
        )
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peaks.append(peak)
    # One float32 chunk is 96 KiB. Chapter growth should add less than that.
    assert peaks[1] - peaks[0] < 24_000 * 4


def test_chapter_wav_streaming_exceeds_chunk_cache_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(audio_synthesis, "_MAX_CACHED_WAV_BYTES", 512)
    samples = np.full(1200, 0.1, dtype=np.float32)
    with pytest.raises(AudioError, match="cache limit"):
        wav_bytes(samples, 24000)
    path = tmp_path / "long-chapter.wav"
    audio_module._write_chapter_wav(samples, 24000, path)
    assert path.stat().st_size > 512
    with wave.open(str(path), "rb") as reader:
        assert reader.getnframes() == 1200
        assert reader.getframerate() == 24000
        assert reader.getnchannels() == 1


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed")
def test_mp3_chapter_encode_is_not_limited_by_wav_chunk_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(audio_synthesis, "_MAX_CACHED_WAV_BYTES", 512)
    result = encode_mp3(
        np.full(24000, 0.05, dtype=np.float32),
        24000,
        tmp_path / "long-chapter.mp3",
        bitrate="128k",
        target_rate=24000,
        title="Synthetic Chapter",
        artist=None,
        album="Synthetic Book",
        track=1,
    )
    assert result.is_file()
    assert result.stat().st_size > 0


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_chapter_wav_streaming_rejects_nonfinite_samples(tmp_path, bad):
    samples = np.array([0.1, bad, 0.2], dtype=np.float32)
    with pytest.raises(AudioError, match="empty/nonfinite"):
        audio_module._write_chapter_wav(samples, 24000, tmp_path / "invalid.wav")


def test_streaming_wav_checks_riff_limit_before_writing(monkeypatch):
    class NearLimitWriter:
        bytes_written = 0xFFFFFFFF - 37

        def writeframesraw(self, _data):
            raise AssertionError("oversized PCM must not be written")

    with pytest.raises(AudioError, match="RIFF size limit"):
        audio_wav._write_pcm_chunk(NearLimitWriter(), np.ones(1, dtype=np.float32))


def test_oserror_while_writing_chapter_wav_leaves_no_temporary_wav(monkeypatch, tmp_path):
    monkeypatch.setattr(audio_module.shutil, "which", lambda _name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        audio_encoding.wave,
        "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("private path detail")),
    )

    with pytest.raises(AudioError, match="Could not write chapter PCM WAV"):
        encode_mp3(
            np.ones(10, dtype=np.float32),
            24000,
            tmp_path / "chapter.mp3",
            bitrate="128k",
            target_rate=24000,
            title="Chapter",
            artist=None,
            album="Book",
            track=1,
        )

    assert not (tmp_path / "chapter.mp3").exists()
    assert list(tmp_path.iterdir()) == []


def test_chapter_size_limit_leaves_no_temporary_wav(monkeypatch, tmp_path):
    class HugeSamples:
        ndim = 1
        size = (0xFFFFFFFF - 36) // 2 + 1

    monkeypatch.setattr(audio_module.shutil, "which", lambda _name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(audio_encoding.np, "asarray", lambda *_args, **_kwargs: HugeSamples())

    with pytest.raises(AudioError, match="RIFF size limit"):
        encode_mp3(
            object(),
            24000,
            tmp_path / "chapter.mp3",
            bitrate="128k",
            target_rate=24000,
            title="Chapter",
            artist=None,
            album="Book",
            track=1,
        )

    assert not (tmp_path / "chapter.mp3").exists()
    assert list(tmp_path.iterdir()) == []


# --- Writer refusals (test coverage round 2, U7) -------------------------------


@pytest.fixture
def _earlier_garbage_collected():
    """Collect garbage left by earlier tests (with warnings ignored), so a warning
    raised by the collection inside a test below comes from that test alone."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        gc.collect()


@pytest.mark.usefixtures("_earlier_garbage_collected")
@pytest.mark.filterwarnings(
    "error::pytest.PytestUnraisableExceptionWarning", "error::ResourceWarning"
)
@pytest.mark.parametrize("blocker", ["file-as-folder", "folder-as-file"])
def test_chapter_wav_that_cannot_be_created_is_a_fixed_error(tmp_path, blocker):
    """U7.a: a file where the folder should be, or a folder where the WAV should be."""
    if blocker == "file-as-folder":
        (tmp_path / "work").write_text("not a folder", encoding="utf-8")
        target = tmp_path / "work" / "chapter.wav"
    else:
        target = tmp_path / "chapter.wav"
        target.mkdir()

    with pytest.raises(AudioError) as error:
        audio_wav._open_streaming_wav(target, 24000)
    message = str(error.value)
    del error
    gc.collect()  # any half-built writer or open handle is released inside this test

    assert message == "Could not create temporary chapter WAV"
    assert str(tmp_path) not in message


@pytest.mark.usefixtures("_earlier_garbage_collected")
@pytest.mark.filterwarnings(
    "error::pytest.PytestUnraisableExceptionWarning", "error::ResourceWarning"
)
def test_writer_that_cannot_be_configured_is_closed_cleanly(tmp_path):
    """U7.a: a rate wave refuses is a fixed error, with no file handle left open."""
    with pytest.raises(AudioError) as error:
        audio_wav._open_streaming_wav(tmp_path / "chapter.wav", 0)
    message = str(error.value)
    del error
    gc.collect()

    assert message == "Could not create temporary chapter WAV"


@pytest.mark.usefixtures("_earlier_garbage_collected")
@pytest.mark.filterwarnings(
    "error::pytest.PytestUnraisableExceptionWarning", "error::ResourceWarning"
)
def test_closing_the_writer_closes_its_file(tmp_path):
    """U7.a: the writer owns the handle it opened and closes it with the WAV."""
    writer = audio_wav._open_streaming_wav(tmp_path / "chapter.wav", 24000)
    stream = writer.stream
    writer.close()

    assert stream.closed
    assert _frames(tmp_path / "chapter.wav") == (0, 24000, 1, 2)


def _frames(path):
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes(), wav.getframerate(), wav.getnchannels(), wav.getsampwidth()


@pytest.mark.parametrize(
    ("samples", "message"),
    [
        (["not", "audio"], "TTS returned invalid audio sample data"),
        (object(), "TTS returned invalid audio sample data"),
        (np.zeros((2, 4), dtype=np.float32), "TTS returned invalid mono audio samples"),
        (np.zeros(0, dtype=np.float32), "TTS returned invalid mono audio samples"),
        (np.array([0.1, np.nan], dtype=np.float32), "TTS returned invalid mono audio samples"),
        (np.array([0.1, np.inf], dtype=np.float32), "TTS returned invalid mono audio samples"),
    ],
    ids=["strings", "object", "two-dimensional", "empty", "nan", "infinite"],
)
def test_invalid_sample_chunk_is_refused_without_writing(tmp_path, samples, message):
    """U7.b: a bad chunk is refused before any frame is written."""
    target = tmp_path / "chapter.wav"
    writer = audio_wav._open_streaming_wav(target, 24000)
    try:
        with pytest.raises(AudioError) as error:
            audio_wav._write_pcm_chunk(writer, samples)
        assert writer.bytes_written == 0
    finally:
        writer.close()

    assert str(error.value) == message
    assert _frames(target) == (0, 24000, 1, 2)


def test_valid_chunk_control_case_is_written(tmp_path):
    """U7.b control: a finite mono chunk is written as 16-bit PCM."""
    target = tmp_path / "chapter.wav"
    writer = audio_wav._open_streaming_wav(target, 24000)
    try:
        audio_wav._write_pcm_chunk(writer, np.array([0.0, 0.5, -0.5], dtype=np.float32))
        assert writer.bytes_written == 6
    finally:
        writer.close()

    assert _frames(target) == (3, 24000, 1, 2)


_RIFF_LIMIT = 0xFFFFFFFF - 36


@pytest.mark.parametrize(("count", "allowed"), [(1, True), (2, False)])
def test_silence_past_the_riff_limit_is_refused_without_writing(tmp_path, count, allowed):
    """U7.c: silence that would pass the RIFF size limit is refused before writing."""
    writer = audio_wav._open_streaming_wav(tmp_path / "chapter.wav", 24000)
    try:
        writer.bytes_written = _RIFF_LIMIT - 2  # pretend the chapter is almost full
        if allowed:
            audio_wav._write_silence(writer, count)
            assert writer.bytes_written == _RIFF_LIMIT
        else:
            with pytest.raises(AudioError, match="^Chapter audio exceeds the WAV RIFF size limit$"):
                audio_wav._write_silence(writer, count)
            assert writer.bytes_written == _RIFF_LIMIT - 2
    finally:
        writer.close()
