"""Supplement every study recording with gpt-transcribe; preserve primary ASR.

Post-start review addition after severe Whisper omissions/repetition were found.
Same unaltered channel inputs for both target arms, no expected transcript prompt.
This is additional machine evidence, not human listening or replacement trials.
"""

import argparse
import asyncio
import hashlib
import json
import wave
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


async def transcribe_call(folder, client):
    analysis = folder / "analysis"
    original = list(folder.glob("*.wav"))
    if len(original) != 1:
        raise ValueError("One original two-channel recording required")
    source_hash = hashlib.sha256(original[0].read_bytes()).hexdigest()

    async def channel(index):
        primary = read(analysis / f"asr-channel-{index}.json")
        if primary["source_sha256"] != source_hash:
            raise ValueError("Primary transcription recording hash changed")
        mono = analysis / f"channel-{index}.wav"
        mono_hash = hashlib.sha256(mono.read_bytes()).hexdigest()
        with wave.open(str(mono), "rb") as wav:
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                raise ValueError("Expected existing mono PCM16 transcription input")
            duration = wav.getnframes() / wav.getframerate()
        if abs(duration - primary["duration_s"]) > 0.001:
            raise ValueError("Primary transcription input duration changed")
        output = analysis / f"asr-secondary-{index}.json"
        if output.exists():
            row = read(output)
            if row["source_sha256"] != source_hash or row["input_sha256"] != mono_hash:
                raise ValueError("Previously transcribed audio changed")
            return row
        row = {
            "channel": index,
            "model": "gpt-transcribe",
            "source_sha256": source_hash,
            "input_sha256": mono_hash,
            "duration_s": duration,
            "requested_at": datetime.now(UTC).isoformat(),
            "selection": "All 60 study recordings, both channels, both target arms",
            "request_prompt": None,
            "language_hint": None,
            "asr_preprocessing": primary["asr_preprocessing"],
            "list_price_estimate_usd": duration / 60 * 0.0045,
            "price_source": "https://developers.openai.com/api/docs/pricing",
            "price_checked": "2026-09-13",
            "limitation": "Supplemental machine transcription; not human-verified audio or timing.",
        }
        marker = analysis / f"asr-secondary-{index}.request.json"
        with marker.open("x", encoding="utf-8") as stream:
            json.dump(row, stream, indent=2)
        with mono.open("rb") as audio:
            result = await client.audio.transcriptions.create(model="gpt-transcribe", file=audio)
        row["transcription"] = result.model_dump(mode="json")
        with output.open("x", encoding="utf-8") as stream:
            json.dump(row, stream, ensure_ascii=False, indent=2)
        return row

    return await asyncio.gather(channel(0), channel(1))


async def watch(manifest, runs, env):
    load_dotenv(env)
    plan = read(manifest)
    finished = set()
    async with AsyncOpenAI(max_retries=0, timeout=120) as client:
        while len(finished) < len(plan["trials"]):
            for trial in plan["trials"]:
                identity = trial["trial_id"]
                folder = runs / trial["output_name"]
                if (
                    identity in finished
                    or not (folder / "analysis/transcript-summary.json").exists()
                ):
                    continue
                rows = await transcribe_call(folder, client)
                finished.add(identity)
                print(
                    json.dumps(
                        {
                            "secondary_transcribed": identity,
                            "completed": len(finished),
                            "total": len(plan["trials"]),
                            "estimated_usd": sum(r["list_price_estimate_usd"] for r in rows),
                        }
                    ),
                    flush=True,
                )
            if len(finished) < len(plan["trials"]):
                await asyncio.sleep(10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--env", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(watch(args.manifest, args.runs, args.env))
