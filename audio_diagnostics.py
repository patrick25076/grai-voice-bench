"""Describe raw recording levels without changing audio or claiming perceptual quality."""

import argparse
import array
import json
import math
import statistics
import sys
import wave
from pathlib import Path


def levels(path):
    with wave.open(str(path), "rb") as recording:
        rate, channels, width = (
            recording.getframerate(),
            recording.getnchannels(),
            recording.getsampwidth(),
        )
        if width != 2:
            raise ValueError("PCM16 required")
        samples = array.array("h", recording.readframes(recording.getnframes()))
    if sys.byteorder != "little":
        samples.byteswap()
    rows = []
    frame_size = rate // 50
    for channel in range(channels):
        mono = samples[channel::channels]
        rms = [
            math.sqrt(sum(x * x for x in mono[i : i + frame_size]) / frame_size)
            for i in range(0, len(mono) - frame_size + 1, frame_size)
        ]
        active = [v for v in rms if v >= 300]
        median = statistics.median(active) if active else None
        rows.append(
            {
                "channel": channel,
                "active_frame_median_dbfs": 20 * math.log10(median / 32768) if median else None,
                "peak_dbfs": 20 * math.log10(max(map(abs, mono)) / 32768) if any(mono) else None,
                "clipped_samples": sum(abs(v) >= 32760 for v in mono),
                "energy_active_seconds": len(active) * 0.02,
            }
        )
    return {
        "sample_rate": rate,
        "duration_s": len(samples) / channels / rate,
        "channels": rows,
        "method": "20 ms RMS; active frames >=300 PCM16 units; raw audio unchanged",
        "limitation": "Active RMS is not LUFS, a whisper detector, or a speaking-speed measure.",
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--pattern", default="*/*.wav", help="Recording glob relative to root")
    a = p.parse_args()
    result = {
        str(path.relative_to(a.root)): levels(path) for path in sorted(a.root.glob(a.pattern))
    }
    a.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
