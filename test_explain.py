"""Regression checks for honest failure attribution and native schema audits."""

import copy
import unittest

from explain import captured_configs, explain_trial, tool_map


class ExplanationChecks(unittest.TestCase):
    def trial(self):
        return {
            "sample_id": "S001",
            "trial_id": "P01-1",
            "pair_id": "P01",
            "provider": "gemini",
            "scenario": "sim-create-order",
            "grade": {
                "state_pass": True,
                "policy_pass": False,
                "checks": {"phone": True},
                "policy_violations": ["confirmation_required"],
            },
            "sandbox": {
                "events": [
                    {
                        "sequence": 0,
                        "tool": "record_order",
                        "result": {"ok": False, "code": "confirmation_required"},
                        "before": {"orders": []},
                        "after": {"orders": []},
                    }
                ]
            },
            "assessment": {"caller_fidelity": "fail"},
        }

    def test_blocked_then_recovered_is_not_a_failed_final_state(self):
        trial = self.trial()
        before = copy.deepcopy(trial)
        result = explain_trial(trial)
        self.assertIn("State checks passed", result["headline"])
        self.assertTrue(result["blocked_attempts"][0]["state_unchanged"])
        self.assertIsNone(result["overall_task_success"])
        self.assertIsNone(result["causal_model_fault"])
        self.assertEqual(trial, before)

    def test_declared_correction_preserves_original_failed_checks(self):
        trial = self.trial()
        trial["grade"].update(state_pass=False, checks={"followup_request_correct": False})
        trial["grader_errata"] = {"grade": {"state_pass": True}}
        result = explain_trial(trial)
        self.assertIn("declared grading correction", result["headline"])
        self.assertEqual(result["failed_original_checks"], ["followup_request_correct"])

    def test_absent_parameter_block_is_a_valid_no_argument_tool(self):
        google = [{"name": "lookup_order", "description": "Read orders"}]
        openai = [
            {
                "name": "lookup_order",
                "description": "Read orders",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
            }
        ]
        self.assertEqual(tool_map(google), tool_map(openai))
        self.assertNotEqual(tool_map([]), tool_map(openai))

    def test_changed_required_fields_and_constraints_are_detected(self):
        base = [
            {
                "name": "save",
                "parameters": {
                    "type": "object",
                    "properties": {"quantity": {"type": "integer", "minimum": 1}},
                    "required": ["quantity"],
                },
            }
        ]
        for change in ("required", "minimum", "type"):
            changed = copy.deepcopy(base)
            params = changed[0]["parameters"]
            if change == "required":
                params["required"] = []
            else:
                params["properties"]["quantity"][change] = 2 if change == "minimum" else "string"
            self.assertNotEqual(tool_map(base), tool_map(changed))

    def test_duplicate_tool_names_are_not_silently_collapsed(self):
        with self.assertRaises(ValueError):
            tool_map([{"name": "lookup"}, {"name": "lookup"}])

    def test_capture_exports_no_account_or_unselected_session_fields(self):
        extra = {
            "provider": "gemini",
            "account_id": "private",
            "provider_audit": {
                "sessions": [
                    {
                        "events": [
                            {
                                "kind": "requested_config",
                                "data": {
                                    "api_key": "private",
                                    "session_resumption": {"handle": "private"},
                                    "system_instruction": {
                                        "parts": [{"text": "public instruction"}]
                                    },
                                    "tools": [
                                        {
                                            "function_declarations": [
                                                {"name": "lookup", "private_key": "private"}
                                            ]
                                        }
                                    ],
                                },
                            }
                        ]
                    }
                ]
            },
        }
        out = captured_configs(extra)
        self.assertEqual(out[0]["requested_tools"], [{"name": "lookup"}])
        self.assertNotIn("private", repr(out))


if __name__ == "__main__":
    unittest.main()
