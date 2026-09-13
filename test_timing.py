import unittest

from timing import backend_timing, distribution, response_opportunities, speech_intervals


class TimingTests(unittest.TestCase):
    def test_silence_hold_is_not_added_to_speech_endpoint(self):
        result = speech_intervals([0.9] * 10 + [0.1] * 20, 960)
        self.assertEqual(result, [[0, 320]])

    def test_end_of_file_silence_does_not_become_speech(self):
        self.assertEqual(speech_intervals([0.9] * 10 + [0.1] * 3, 416), [[0, 320]])

    def test_short_click_and_empty_audio_do_not_become_speech(self):
        self.assertEqual(speech_intervals([0.9] + [0.1] * 20, 672), [])
        self.assertEqual(speech_intervals([], 0), [])

    def test_overlap_is_not_a_slow_following_answer_or_zero_latency(self):
        rows = response_opportunities([[0, 1000], [3000, 4000]], [[800, 1500], [4200, 5000]])
        self.assertEqual(rows[0]["kind"], "overlap_at_caller_end")
        self.assertIsNone(rows[0]["gap_ms"])
        self.assertEqual(rows[1]["gap_ms"], 200)

    def test_no_response_not_assigned_to_later_caller_chunk(self):
        rows = response_opportunities([[0, 1000], [1500, 2000]], [[2200, 3000]])
        self.assertEqual(rows[0]["kind"], "no_paired_response")
        self.assertEqual(rows[1]["gap_ms"], 200)

    def test_backend_continuations_duplicates_and_incomplete_are_separate(self):
        def event(kind, ident, elapsed):
            return {"elapsed_ms": elapsed, "data": {"type": "response.event", "event": {
                "type": kind, "response": {"id": ident, "model": "backend"}}}}
        audit = {"sessions": [{"events": [event("response.created", "a", 100),
            event("response.completed", "a", 600), event("response.completed", "a", 650),
            event("response.created", "b", 700)]}]}
        result = backend_timing(audit)
        self.assertEqual(result["completed_ms"], {"n": 1, "p50": 500, "p95": 500})
        self.assertEqual(len(result["responses"]), 2)
        self.assertEqual(result["responses"][1]["status"], "unclosed")

    def test_missing_latency_is_null(self):
        self.assertEqual(distribution([]), {"n": 0, "p50": None, "p95": None})


if __name__ == "__main__":
    unittest.main()
