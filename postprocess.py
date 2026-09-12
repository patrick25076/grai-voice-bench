"""Transcribe completed study recordings while calls continue; never place calls."""

import argparse
import asyncio
import json
from pathlib import Path

from audio_diagnostics import levels
from transcribe import transcribe


async def watch(manifest, runs, env):
    plan = json.loads(manifest.read_text(encoding="utf-8"))
    finished = set()
    while len(finished) < len(plan["trials"]):
        for trial in plan["trials"]:
            identity = trial["trial_id"]
            if identity in finished:
                continue
            folder = runs / trial["output_name"]
            stamp = runs / "attempts" / f"{identity}.json"
            if not stamp.exists():
                continue
            state = json.loads(stamp.read_text(encoding="utf-8"))
            if state.get("status") != "evidence_collected":
                continue
            rows = await transcribe(folder, env, trial["language"])
            wavs = list(folder.glob("*.wav"))
            analysis = folder / "analysis"
            (analysis / "audio-levels.json").write_text(
                json.dumps(levels(wavs[0]), indent=2), encoding="utf-8"
            )
            text = {
                "trial_id": identity,
                "method": "independent ASR; inspect against native transcript and audio, including possible hallucinated silent-tail text",
                "caller": rows[0]["transcription"]["text"],
                "target": rows[1]["transcription"]["text"],
                "asr_list_price_estimate_usd": sum(row["list_price_estimate_usd"] for row in rows),
            }
            (analysis / "transcript-summary.json").write_text(
                json.dumps(text, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            finished.add(identity)
            print(
                json.dumps(
                    {
                        "transcribed": identity,
                        "completed": len(finished),
                        "total": len(plan["trials"]),
                    }
                ),
                flush=True,
            )
        if len(finished) < len(plan["trials"]):
            await asyncio.sleep(10)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--runs", type=Path, required=True)
    p.add_argument("--env", type=Path, required=True)
    args = p.parse_args()
    asyncio.run(watch(args.manifest, args.runs, args.env))
