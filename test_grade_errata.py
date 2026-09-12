import unittest

from grade_errata import apply_errata


def fixture(reference, quantity=200, scenario="sim-stock-shortage"):
    return {
        "scenario": scenario,
        "sandbox": {
            "final_state": {
                "messages": [
                    {
                        "request_type": "stock_request",
                        "quantity_kg": quantity,
                        "order_id": reference,
                    }
                ]
            }
        },
        "grade": {
            "checks": {"followup_request_correct": False, "stock_checked": True},
            "state_pass": False,
            "policy_pass": False,
        },
    }


class ErrataTests(unittest.TestCase):
    def test_empty_reference_equivalence_preserves_original_and_policy(self):
        original = fixture("")
        corrected = apply_errata(original)
        self.assertTrue(corrected["grade"]["state_pass"])
        self.assertFalse(corrected["grade"]["policy_pass"])
        self.assertFalse(original["grade"]["state_pass"])
        self.assertEqual(len(corrected["applied"]), 1)

    def test_real_reference_wrong_quantity_and_other_case_are_not_relaxed(self):
        for original in (
            fixture("OTHER-001"),
            fixture("", 100),
            fixture("", scenario="sim-existing-order"),
        ):
            self.assertFalse(apply_errata(original)["grade"]["state_pass"])
            self.assertEqual(apply_errata(original)["applied"], [])


if __name__ == "__main__":
    unittest.main()
