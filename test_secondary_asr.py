import hashlib
import json
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from secondary_asr import transcribe_call


class SecondaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        analysis = self.folder / "analysis"
        analysis.mkdir()
        self.source = self.folder / "recording.wav"
        with wave.open(str(self.source), "wb") as wav:
            wav.setparams((2, 2, 8000, 0, "NONE", "not compressed"))
            wav.writeframes(b"\x00" * 320)
        digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        for index in (0, 1):
            with wave.open(str(analysis / f"channel-{index}.wav"), "wb") as wav:
                wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
                wav.writeframes(b"\x00" * 160)
            (analysis / f"asr-channel-{index}.json").write_text(
                json.dumps(
                    {
                        "source_sha256": digest,
                        "duration_s": 0.01,
                        "asr_preprocessing": "test fixture",
                    }
                ),
                encoding="utf-8",
            )
        result = SimpleNamespace(model_dump=lambda **_: {"text": "fixture", "usage": {}})
        self.create = AsyncMock(return_value=result)
        self.client = SimpleNamespace(
            audio=SimpleNamespace(transcriptions=SimpleNamespace(create=self.create))
        )

    async def test_restart_reuses_results_without_duplicate_paid_requests(self):
        first = await transcribe_call(self.folder, self.client)
        again = await transcribe_call(self.folder, self.client)
        self.assertEqual(first, again)
        self.assertEqual(self.create.await_count, 2)

    async def test_changed_recording_is_rejected_before_model_request(self):
        self.source.write_bytes(self.source.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "recording hash changed"):
            await transcribe_call(self.folder, self.client)
        self.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
