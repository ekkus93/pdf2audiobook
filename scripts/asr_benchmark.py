"""Benchmark the three ASR families on generated chapter audio (audio verification, AV0.03).

Three steps, each its own process so memory can be measured per model:

    uv run python scripts/asr_benchmark.py make CHAPTER_TXT... --out DIR
    uv run --with openai-whisper==20250625 --with vosk==0.3.45 \\
        python scripts/asr_benchmark.py run DIR --model whisper|wav2vec2|vosk \\
        --device cpu|cuda --models-dir MODELS
    uv run python scripts/asr_benchmark.py score DIR

`make` synthesizes test cases with the project's Kitten pipeline: each case speaks a text
(sometimes deliberately altered) while its reference stays the original, so planted
insertions, omissions and substitutions are known exactly. `run` writes timed word
transcripts; `score` normalizes, aligns and reports error rates, the differences each
model finds on clean audio, and which planted edits one model or a 2-of-3 vote catches.
The models are pinned as in docs/PDF2AUDIOBOOK_AUDIO_VERIFICATION_SPEC.md §12 and must
already be in MODELS (whisper/medium.en.pt, hf/..., vosk/vosk-model-en-us-0.22-lgraph).
"""

from __future__ import annotations

import argparse
import json
import re
import resource
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np

WAV2VEC2 = "facebook/wav2vec2-base-960h"
WAV2VEC2_REVISION = "22aad52d435eb6dbaf354bdad9b0da84ce7d6156"
VOSK_MODEL = "vosk-model-en-us-0.22-lgraph"
RATE = 16_000

# --- make -------------------------------------------------------------------------------

INSERT = "and the old ferry bell rang twice across the water"
NUMBERS = (
    "In 1987 the harbour gauge recorded 1,250 millimetres of rain over 365 days. "
    "By 2004 the figure had fallen to 3.5 metres of tide on 12 March, and 40 boats stayed home."
)


def _sentences(text: str) -> list[str]:
    return [part for part in re.split(r"(?<=[.!?])\s+", " ".join(text.split())) if part]


def _passage(path: Path, limit: int = 120) -> str:
    """The chapter's first sentences, up to about `limit` words."""
    words = 0
    kept = []
    for sentence in _sentences(path.read_text(encoding="utf-8")):
        kept.append(sentence)
        words += len(sentence.split())
        if words >= limit:
            break
    return " ".join(kept)


def _cases(passages: list[str]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for index, text in enumerate(passages):
        base = f"p{index}"
        voices = ["Jasper", "Luna"] if index < 2 else ["Jasper"]
        for voice in voices:
            cases.append(
                {
                    "id": f"{base}-clean-{voice.lower()}",
                    "reference": text,
                    "spoken": text,
                    "voice": voice,
                }
            )
        sentences = _sentences(text)
        middle = len(sentences) // 2
        words = sentences[middle].split()
        cut = max(2, len(words) // 2)
        inserted = " ".join(words[:cut] + [INSERT] + words[cut:])
        spoken = " ".join(sentences[:middle] + [inserted] + sentences[middle + 1 :])
        cases.append(
            {"id": f"{base}-insertion", "reference": text, "spoken": spoken, "voice": "Jasper"}
        )
        if len(sentences) > 2:
            spoken = " ".join(sentences[:middle] + sentences[middle + 1 :])
            cases.append(
                {"id": f"{base}-omission", "reference": text, "spoken": spoken, "voice": "Jasper"}
            )
        long_words = [w for w in words if len(re.sub(r"\W", "", w)) >= 5]
        if long_words:
            target = long_words[0]
            spoken_sentence = sentences[middle].replace(
                target, "kitchen" + target[len(target.rstrip(",.;:")) :], 1
            )
            spoken = " ".join(sentences[:middle] + [spoken_sentence] + sentences[middle + 1 :])
            cases.append(
                {
                    "id": f"{base}-substitution",
                    "reference": text,
                    "spoken": spoken,
                    "voice": "Jasper",
                }
            )
        if index == 0:
            cases.append(
                {
                    "id": f"{base}-noisy10",
                    "reference": text,
                    "spoken": text,
                    "voice": "Jasper",
                    "snr_db": 10,
                }
            )
            cases.append(
                {
                    "id": f"{base}-noisy0",
                    "reference": text,
                    "spoken": text,
                    "voice": "Jasper",
                    "snr_db": 0,
                }
            )
    cases.append({"id": "numbers", "reference": NUMBERS, "spoken": NUMBERS, "voice": "Jasper"})
    for voice in ["Kiki", "Leo"]:
        cases.append(
            {
                "id": f"p0-clean-{voice.lower()}",
                "reference": passages[0],
                "spoken": passages[0],
                "voice": voice,
            }
        )
    cases.append(
        {
            "id": "short-title",
            "reference": "Chapter 2: The Storm",
            "spoken": "Chapter 2: The Storm",
            "voice": "Jasper",
        }
    )
    return cases


def _write_wav(samples: np.ndarray, rate: int, path: Path) -> None:
    data = np.clip(samples, -1.0, 1.0)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes((data * 32767).astype("<i2").tobytes())


def make(args: argparse.Namespace) -> None:
    from pdf2audiobook.audio import synthesize_chunks
    from pdf2audiobook.config import load_settings
    from pdf2audiobook.pipeline import create_tts_provider

    settings, _ = load_settings(no_config=True)
    provider = create_tts_provider(settings)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cases = _cases([_passage(Path(path)) for path in args.chapters])
    for case in cases:
        with tempfile.TemporaryDirectory() as cache:
            samples = synthesize_chunks(
                case["spoken"],
                provider,
                model=settings.tts.kitten.model,
                voice=case["voice"],
                speed=1.0,
                pause_ms=settings.tts.pause_ms,
                cache=Path(cache),
                use_cache=False,
                pronunciations=settings.tts.pronunciations,
            )
        assert isinstance(samples, np.ndarray)
        raw = out / f"{case['id']}.raw.wav"
        _write_wav(samples, provider.sample_rate, raw)
        command = ["ffmpeg", "-v", "error", "-y", "-i", str(raw)]
        if "snr_db" in case:
            # Pink noise mixed at the requested signal-to-noise ratio (approximate: by RMS).
            rms = float(np.sqrt(np.mean(np.square(samples)))) or 1e-4
            amplitude = rms / (10 ** (case["snr_db"] / 20))
            command += [
                "-f",
                "lavfi",
                "-i",
                f"anoisesrc=color=pink:amplitude={amplitude:.5f}:sample_rate={provider.sample_rate}",
                "-filter_complex",
                "[0][1]amix=inputs=2:duration=first:normalize=0",
            ]
        command += ["-ac", "1", "-ar", str(RATE), str(out / f"{case['id']}.wav")]
        subprocess.run(command, check=True)
        raw.unlink()
        case["seconds"] = round(len(samples) / provider.sample_rate, 2)
        print(f"made {case['id']}: {case['seconds']} s", flush=True)
    (out / "cases.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")


# --- run --------------------------------------------------------------------------------


def _read(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as source:
        assert source.getframerate() == RATE and source.getnchannels() == 1
        frames = source.readframes(source.getnframes())
    return np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0


def _whisper(models: Path, device: str):
    import torch
    import whisper

    torch.set_num_threads(4)
    model = whisper.load_model(str(models / "whisper" / "medium.en.pt"), device=device)

    def transcribe(path: Path) -> list[dict[str, Any]]:
        result = model.transcribe(
            str(path),
            language="en",
            word_timestamps=True,
            fp16=device == "cuda",
            condition_on_previous_text=False,
            temperature=0.0,
        )
        return [
            {
                "word": word["word"].strip(),
                "start": round(word["start"], 2),
                "end": round(word["end"], 2),
            }
            for segment in result["segments"]
            for word in segment.get("words", [])
        ]

    return transcribe


def _wav2vec2(models: Path, device: str):
    import torch
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

    torch.set_num_threads(4)
    # The files fetched for the pinned revision (only those the model needs).
    path = str(
        models / "hf" / "models--facebook--wav2vec2-base-960h" / "snapshots" / WAV2VEC2_REVISION
    )
    processor = Wav2Vec2Processor.from_pretrained(path)
    model = Wav2Vec2ForCTC.from_pretrained(path).to(device).eval()
    ratio = model.config.inputs_to_logits_ratio / RATE
    window = 30 * RATE

    def transcribe(path: Path) -> list[dict[str, Any]]:
        audio = _read(path)
        words: list[dict[str, Any]] = []
        # Fixed windows bound memory; a word cut at a boundary may be split or lost.
        for offset in range(0, len(audio), window):
            piece = audio[offset : offset + window]
            inputs = processor(piece, sampling_rate=RATE, return_tensors="pt").input_values.to(
                device
            )
            with torch.inference_mode():
                logits = model(inputs).logits
            ids = torch.argmax(logits, dim=-1)[0].cpu()
            decoded = processor.decode(ids, output_word_offsets=True)
            for item in decoded.word_offsets:
                words.append(
                    {
                        "word": item["word"],
                        "start": round(offset / RATE + item["start_offset"] * ratio, 2),
                        "end": round(offset / RATE + item["end_offset"] * ratio, 2),
                    }
                )
        return words

    return transcribe


def _vosk(models: Path, device: str):
    from vosk import KaldiRecognizer, Model, SetLogLevel

    SetLogLevel(-1)
    model = Model(str(models / "vosk" / VOSK_MODEL))

    def transcribe(path: Path) -> list[dict[str, Any]]:
        recognizer = KaldiRecognizer(model, RATE)
        recognizer.SetWords(True)
        words: list[dict[str, Any]] = []

        def take(result: str) -> None:
            for item in json.loads(result).get("result", []):
                words.append(
                    {
                        "word": item["word"],
                        "start": round(item["start"], 2),
                        "end": round(item["end"], 2),
                    }
                )

        with wave.open(str(path), "rb") as source:
            while data := source.readframes(4000):
                if recognizer.AcceptWaveform(data):
                    take(recognizer.Result())
        take(recognizer.FinalResult())
        return words

    return transcribe


def run(args: argparse.Namespace) -> None:
    folder = Path(args.dir)
    cases = json.loads((folder / "cases.json").read_text(encoding="utf-8"))
    started = time.perf_counter()
    transcribe = {"whisper": _whisper, "wav2vec2": _wav2vec2, "vosk": _vosk}[args.model](
        Path(args.models_dir), args.device
    )
    load_seconds = time.perf_counter() - started
    results: dict[str, Any] = {}
    audio_seconds = compute_seconds = 0.0
    for case in cases:
        began = time.perf_counter()
        words = transcribe(folder / f"{case['id']}.wav")
        spent = time.perf_counter() - began
        results[case["id"]] = {"words": words, "seconds": round(spent, 2)}
        audio_seconds += case["seconds"]
        compute_seconds += spent
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    summary = {
        "model": args.model,
        "device": args.device,
        "load_seconds": round(load_seconds, 1),
        "audio_seconds": round(audio_seconds, 1),
        "compute_seconds": round(compute_seconds, 1),
        "real_time_factor": round(compute_seconds / audio_seconds, 3),
        "peak_rss_mb": round(peak_mb),
    }
    if args.device == "cuda":
        import torch

        summary["peak_gpu_mb"] = round(torch.cuda.max_memory_allocated() / 2**20)
    (folder / f"run-{args.model}-{args.device}.json").write_text(
        json.dumps({"summary": summary, "cases": results}, indent=1), encoding="utf-8"
    )
    print(json.dumps(summary))


# --- score ------------------------------------------------------------------------------


def score(args: argparse.Namespace) -> None:
    """Score with the production comparison core across minimum-size and slack settings."""
    from pdf2audiobook.verification import compare
    from pdf2audiobook.verification.contracts import Word

    folder = Path(args.dir)
    cases = json.loads((folder / "cases.json").read_text(encoding="utf-8"))
    runs = {
        path.stem.removeprefix("run-"): json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(folder.glob("run-*.json"))
    }
    devices = sorted({name.rsplit("-", 1)[1] for name in runs})
    report: dict[str, Any] = {"runs": {n: d["summary"] for n, d in runs.items()}, "settings": {}}
    for device in devices:
        print(f"\n== {device}")
        for name, data in runs.items():
            if name.endswith(device):
                print("  ", data["summary"])
        models = [m for m in ("whisper", "wav2vec2", "vosk") if f"{m}-{device}" in runs]
        for min_words in (2, 3):
            for slack in (1, 2, 3):
                compare.MIN_WORDS, compare.SLACK_WORDS = 1, slack
                totals = {
                    "planted": 0,
                    "caught": 0,
                    "false_flags": 0,
                    "disagreements": 0,
                    "clean_flagged": 0,
                }
                missed = []
                for case in cases:
                    reference = compare.tokenize_text(case["reference"])
                    planted = compare.differences(
                        "whisper", reference, compare.tokenize_text(case["spoken"])
                    )
                    compare.MIN_WORDS = min_words
                    found = {}
                    for model in models:
                        words = runs[f"{model}-{device}"]["cases"][case["id"]]["words"]
                        heard = compare.tokenize(
                            Word(w["word"], w["start"], w["end"]) for w in words
                        )
                        found[model] = compare.differences(model, reference, heard)
                    flags = compare.vote(reference, found)
                    compare.MIN_WORDS = 1
                    confirmed = [f for f in flags if f.confirmed]
                    totals["planted"] += len(planted)
                    hits = [p for p in planted if any(compare._near(f, p) for f in confirmed)]
                    totals["caught"] += len(hits)
                    missed += [case["id"] for p in planted if p not in hits]
                    false = [f for f in confirmed if not any(compare._near(f, p) for p in planted)]
                    totals["false_flags"] += len(false)
                    totals["disagreements"] += len(flags) - len(confirmed)
                    totals["clean_flagged"] += bool(not planted and confirmed)
                key = f"{device} min_words={min_words} slack={slack}"
                report["settings"][key] = {**totals, "missed": missed}
                print(
                    f"   min_words={min_words} slack={slack}: caught {totals['caught']}/{totals['planted']}, "
                    f"false 2-of-3 flags {totals['false_flags']} (clean cases flagged {totals['clean_flagged']}), "
                    f"one-model differences {totals['disagreements']}; missed {missed}"
                )
    (folder / "score.json").write_text(json.dumps(report, indent=1), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    making = commands.add_parser("make")
    making.add_argument("chapters", nargs="+")
    making.add_argument("--out", required=True)
    running = commands.add_parser("run")
    running.add_argument("dir")
    running.add_argument("--model", required=True, choices=["whisper", "wav2vec2", "vosk"])
    running.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    running.add_argument("--models-dir", required=True)
    scoring = commands.add_parser("score")
    scoring.add_argument("dir")
    args = parser.parse_args()
    {"make": make, "run": run, "score": score}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
