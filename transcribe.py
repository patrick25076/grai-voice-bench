"""Independent per-channel ASR evidence; timestamps are estimates, not ground truth."""

from __future__ import annotations

import argparse
import array
import asyncio
import hashlib
import json
import math
import sys
import wave
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI


async def transcribe(run_dir, env_path, language):
    load_dotenv(env_path)
    recordings = list(run_dir.glob("*.wav"))
    if len(recordings) != 1:
        raise ValueError("Exactly one original carrier WAV required")
    source = recordings[0]
    analysis = run_dir / "analysis"
    analysis.mkdir(exist_ok=True)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    with wave.open(str(source), "rb") as wav:
        channels, rate, width = wav.getnchannels(), wav.getframerate(), wav.getsampwidth()
        frames = wav.getnframes()
        if channels != 2 or width != 2:
            raise ValueError("Dual-channel PCM16 required")
        samples = array.array("h", wav.readframes(frames))
    if sys.byteorder != "little":
        samples.byteswap()

    async with AsyncOpenAI(max_retries=0, timeout=120) as client:

        async def channel(index):
            output = analysis / f"asr-channel-{index}.json"
            if output.exists():
                previous = json.loads(output.read_text(encoding="utf-8"))
                if previous["source_sha256"] != source_hash:
                    raise ValueError("Recording changed after transcription")
                return previous
            request = analysis / f"asr-channel-{index}.request.json"
            mono = analysis / f"channel-{index}.wav"
            values = samples[index::channels]
            # Common trailing-silence trim for ASR only. Keep the original WAV
            # untouched and keep time zero, so timestamps retain the carrier clock.
            frame_size = max(1, rate // 50)
            active_end = 0
            for offset in range(0, len(values), frame_size):
                window = values[offset : offset + frame_size]
                if math.sqrt(sum(v * v for v in window) / len(window)) >= 100:
                    active_end = offset + len(window)
            asr_samples = min(len(values), max(rate, active_end + rate // 2))
            values = values[:asr_samples]
            if sys.byteorder != "little":
                values.byteswap()
            with wave.open(str(mono), "wb") as wav:
                wav.setparams((1, 2, rate, 0, "NONE", "not compressed"))
                wav.writeframes(values.tobytes())
            envelope = {
                "source_sha256": source_hash,
                "channel": index,
                "model": "whisper-1",
                "language_hint": language,
                "duration_s": asr_samples / rate,
                "original_duration_s": frames / rate,
                "asr_preprocessing": "Trailing silence trimmed using 20 ms RMS >=100 PCM16 units plus 0.5 s; original recording unchanged; no start trim or gain change",
                "requested_at": datetime.now(UTC).isoformat(),
                "list_price_estimate_usd": asr_samples / rate / 60 * 0.006,
                "price_source": "https://developers.openai.com/api/docs/pricing",
                "price_checked": "2026-09-13",
                "limitation": "ASR may mishear names or numbers; word timestamps need acoustic validation",
            }
            with request.open("x", encoding="utf-8") as stream:
                json.dump(envelope, stream, indent=2)
            with mono.open("rb") as audio:
                result = await client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio,
                    language=language,
                    response_format="verbose_json",
                    timestamp_granularities=["word", "segment"],
                )
            envelope["transcription"] = result.model_dump(mode="json")
            output.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
            return envelope

        return await asyncio.gather(channel(0), channel(1))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--language", choices=("en", "ro"), required=True)
    args = parser.parse_args()
    for row in asyncio.run(transcribe(args.run_dir, args.env, args.language)):
        print(
            json.dumps(
                {"channel": row["channel"], "text": row["transcription"]["text"]},
                ensure_ascii=False,
            )
        )
