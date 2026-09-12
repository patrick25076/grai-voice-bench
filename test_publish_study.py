import unittest

from publish_study import known_total, paired_outcomes, reviewed_content_hash


def arm(provider, state, caller="pass"):
    return {
        "pair_id": "P01",
        "provider": provider,
        "language": "en",
        "scenario": "sim-create-order",
        "caller_provider": "gemini",
        "grade": {"state_pass": state},
        "assessment": {"caller_fidelity": caller},
    }


class ReportTests(unittest.TestCase):
    def test_missing_cost_is_not_a_zero_cost_observation(self):
        self.assertEqual(
            known_total([None, 0.2]), {"known_sum_usd": 0.2, "known_n": 1, "total_n": 2}
        )
        self.assertIsNone(known_total([None])["known_sum_usd"])

    def test_unknown_pair_is_not_a_model_loss(self):
        result = paired_outcomes([arm("gemini", True), arm("gptlive", None)])[0]
        self.assertEqual(result["raw_state_pattern"], "incomplete_evidence")

    def test_caller_exclusion_does_not_erase_raw_pair(self):
        result = paired_outcomes([arm("gemini", True, "fail"), arm("gptlive", False)])[0]
        self.assertEqual(result["raw_state_pattern"], "gemini_only_pass")
        self.assertFalse(result["both_caller_transcript_reviews_pass"])

    def test_review_hash_tracks_content_not_later_billing(self):
        target = {"transcript": [], "benchmark": {}, "session_usage": 1}
        caller = {"transcript": []}
        before = reviewed_content_hash(target, caller, [])
        target["session_usage"] = 2
        self.assertEqual(before, reviewed_content_hash(target, caller, []))
        caller["transcript"].append({"text": "Changed request"})
        self.assertNotEqual(before, reviewed_content_hash(target, caller, []))


if __name__ == "__main__":
    unittest.main()
