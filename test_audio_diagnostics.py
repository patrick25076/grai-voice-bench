"""Known acoustic boundaries check the proxy's arithmetic, not real speech VAD."""

import array
import tempfile
import unittest
import wave
from pathlib import Path

from audio_diagnostics import levels
from report import analyze


def recording(path, intervals, duration=7):
    rate = 8000
    samples = array.array("h")
    for frame in range(duration * rate):
        at = frame / rate
        samples.extend(1000 if any(a <= at < b for a, b in spans) else 0 for spans in intervals)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(samples.tobytes())


class AcousticTests(unittest.TestCase):
    def test_known_gaps_use_one_recording_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.wav"
            recording(path, [[(1, 2), (5, 6)], [(3, 4), (6.2, 6.8)]])
            result = analyze(path, 0)
            self.assertEqual(result["audio_proxy_gap_ms"], [1000, 200])
            self.assertEqual(result["median_audio_proxy_gap_ms"], 600)
            self.assertEqual(result["overlap_ms"], 0)

    def test_silence_produces_unknown_gap_not_zero_latency(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "silent.wav"
            recording(path, [[], []])
            self.assertIsNone(analyze(path, 0)["median_audio_proxy_gap_ms"])
            self.assertTrue(
                all(c["active_frame_median_dbfs"] is None for c in levels(path)["channels"])
            )

    def test_overlap_is_not_a_positive_response_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "overlap.wav"
            recording(path, [[(1, 3)], [(2, 4)]])
            result = analyze(path, 0)
            self.assertEqual(result["audio_proxy_gap_ms"], [])
            self.assertEqual(result["overlap_ms"], 1000)


if __name__ == "__main__":
    unittest.main()
