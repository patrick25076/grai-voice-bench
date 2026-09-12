"""Create a local listening report from private carrier recordings.

Energy segments are a timing proxy. Channel mapping must be checked by ear.
No provider or absolute-machine path is exposed in the blinded cards.
"""

from __future__ import annotations

import argparse
import array
import html
import json
import math
import random
import statistics
import sys
import wave
from pathlib import Path


def analyze(path: Path, caller_channel: int) -> dict:
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 2 or wav.getsampwidth() != 2:
            raise ValueError("Expected two-channel PCM16 recording")
        rate = wav.getframerate()
        samples = array.array("h", wav.readframes(wav.getnframes()))
        if sys.byteorder != "little":
            samples.byteswap()
    width = rate // 50
    energies = []
    for channel in range(2):
        mono = samples[channel::2]
        energies.append(
            [
                math.sqrt(sum(x * x for x in mono[i : i + width]) / width)
                for i in range(0, len(mono) - width + 1, width)
            ]
        )

    def segments(frames):
        runs = []
        for i, energy in enumerate(frames):
            if energy < 300:
                continue
            at = i * 20
            if runs and at - runs[-1][1] < 400:
                runs[-1][1] = at + 20
            else:
                runs.append([at, at + 20])
        return runs

    caller = segments(energies[caller_channel])
    agent = segments(energies[1 - caller_channel])
    gaps = []
    unanswered = 0
    for i, (_, end) in enumerate(caller):
        limit = caller[i + 1][0] if i + 1 < len(caller) else math.inf
        if any(start < end < stop for start, stop in agent):
            continue
        response = next((start for start, _ in agent if end <= start < limit), None)
        if response is None:
            unanswered += 1
        else:
            gaps.append(response - end)
    return {
        "duration_s": len(samples) / 2 / rate,
        "caller_channel": caller_channel,
        "audio_proxy_gap_ms": gaps,
        "median_audio_proxy_gap_ms": statistics.median(gaps) if gaps else None,
        "caller_segments_without_following_response": unanswered,
        "overlap_ms": sum(a >= 300 and b >= 300 for a, b in zip(*energies, strict=True)) * 20,
        "agent_energy_active_ms": sum(x >= 300 for x in energies[1 - caller_channel]) * 20,
        "method": "PCM RMS >=300, 20ms frames, 400ms merge; not semantic turn detection",
        "requires_channel_and_turn_review": True,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--caller-channel", type=int, choices=[0, 1], required=True)
    args = parser.parse_args()
    files = sorted(args.root.glob("*/RE*.wav"))
    random.Random(260912).shuffle(files)
    cards = []
    results = []
    for index, path in enumerate(files, 1):
        analysis = analyze(path, args.caller_channel)
        run = json.loads((path.parent / "run.json").read_text(encoding="utf-8"))
        results.append({"sample": index, "run": path.parent.name, "analysis": analysis})
        source = html.escape(path.relative_to(args.root).as_posix())
        cards.append(f'''<article><h2>Sample {index}</h2>
          <audio controls preload="metadata" src="{source}"></audio>
          <p>{analysis["duration_s"]:.1f}s · median energy-based response gap:
          {analysis["median_audio_proxy_gap_ms"]} ms · overlap: {analysis["overlap_ms"]} ms</p>
          <label>Caller followed its assigned facts
          <select data-sample="{index}" data-field="caller_fidelity">
          <option>unreviewed</option><option>yes</option><option>no</option></select></label>
          <label>Spoken claim matches saved state
          <select data-sample="{index}" data-field="spoken_truth">
          <option>unreviewed</option><option>yes</option><option>no</option></select></label>
          <label>Caller confirmed the action
          <select data-sample="{index}" data-field="confirmation">
          <option>unreviewed</option><option>yes</option><option>no</option></select></label>
          <label>Listening quality (1-5) <select data-sample="{index}" data-field="quality">
          <option>unreviewed</option><option>1</option><option>2</option><option>3</option>
          <option>4</option><option>5</option>
          </select></label>
          <details><summary>Reveal configuration after listening</summary>
          <pre>{html.escape(json.dumps(run["setup"], indent=2))}</pre></details></article>''')
    page = """<!doctype html><meta charset="utf-8"><title>GRAI Labs · Voice Bench</title>
    <style>body{font:17px system-ui;max-width:900px;margin:40px auto;
    background:#10161b;color:#eee;padding:20px}
    article{background:#1c262d;padding:24px;margin:24px 0;border-radius:12px}audio{width:100%}
    label{display:block;margin:16px 0}select,button{padding:8px;margin-left:10px}
    details{margin-top:24px}
    p{line-height:1.6;color:#bccdd9}</style><h1>GRAI Labs · Voice Bench pilot</h1>
    <p>Listen before revealing the provider. Verify the caller channel by ear before interpreting
    timing. Energy gaps are a proxy; review the turns and state evidence. Costs remain pending
    until model, backend, telephony and hosting charges have been reconciled.</p>"""
    page += "".join(cards) or "<p>No carrier recordings have been collected yet.</p>"
    page += """<button onclick="save()">Download review JSON</button><script>
    function save(){let rows=[...document.querySelectorAll('select')].map(e=>({
    sample:e.dataset.sample,field:e.dataset.field,value:e.value}));
    let a=document.createElement('a');a.href=URL.createObjectURL(
    new Blob([JSON.stringify(rows,null,2)],{type:'application/json'}));
    a.download='listening-review.json';
    a.click();URL.revokeObjectURL(a.href)}</script>"""
    args.root.mkdir(parents=True, exist_ok=True)
    (args.root / "listen.html").write_text(page, encoding="utf-8")
    (args.root / "audio-analysis.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(args.root / "listen.html")


if __name__ == "__main__":
    main()
