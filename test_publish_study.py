import unittest

from publish_study import (
    distribution,
    known_total,
    measurement_summary,
    paired_outcomes,
    reviewed_content_hash,
    secondary_asr_cost,
)


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
    def test_supplemental_cost_uses_reported_duration(self):
        row = {
            "list_price_estimate_usd": 99,
            "transcription": {"usage": {"type": "duration", "seconds": 120}},
        }
        self.assertAlmostEqual(secondary_asr_cost(row), 0.009)

    def test_supplemental_transcript_change_invalidates_review(self):
        target = {"transcript": [], "benchmark": {}}
        caller = {"transcript": []}
        self.assertNotEqual(
            reviewed_content_hash(target, caller, [], [{"text": "yes"}]),
            reviewed_content_hash(target, caller, [], [{"text": "no"}]),
        )

    def test_zero_gap_is_valid_but_missing_gap_is_not_zero(self):
        self.assertEqual(
            distribution([0, None, 1000]),
            {"n": 2, "total_n": 3, "median": 500, "min": 0, "max": 1000},
        )

    def test_calls_have_equal_weight_and_target_channel_is_explicit(self):
        rows = [
            {
                "audio_diagnostics": {
                    "acoustic_diagnostics": {
                        "median_audio_proxy_gap_ms": gap,
                        "audio_proxy_gap_ms": raw,
                    },
                    "audio_levels": {
                        "channels": [
                            {"channel": 0, "active_frame_median_dbfs": -10},
                            {"channel": 1, "active_frame_median_dbfs": -25},
                        ]
                    },
                }
            }
            for gap, raw in [(100, [100] * 30), (900, [900])]
        ]
        result = measurement_summary(rows)
        self.assertEqual(result["call_median_energy_gap_ms"]["median"], 500)
        self.assertEqual(result["target_active_frame_median_dbfs"]["median"], -25)

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
