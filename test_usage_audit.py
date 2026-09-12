import unittest

from usage_audit import audit


class AuditTest(unittest.TestCase):
    def test_cumulative_voice_updates_are_not_added(self):
        events = [
            {"data": {"type": "session.usage.updated", "usage": {"seconds": n}}} for n in (1, 2, 3)
        ]
        events.append({"data": {"type": "session.closed", "usage": {"seconds": 4}}})
        result = audit(
            {
                "provider": "gptlive",
                "provider_audit": {"sessions": [{"events": events}]},
                "session_usage": {"model_usage": [{"model": "gpt-live-1", "session_duration": 4}]},
            }
        )
        self.assertEqual(result["native_counter_totals"]["gpt-live-1"]["session_duration"], 4)
        self.assertTrue(result["capture_counters_match"])

    def test_duplicate_backend_response_counted_once(self):
        event = {
            "data": {
                "type": "response.event",
                "event": {
                    "type": "response.completed",
                    "response": {
                        "id": "response-1",
                        "model": "test",
                        "usage": {
                            "input_tokens": 10,
                            "output_tokens": 2,
                            "input_tokens_details": {"cached_tokens": 3, "cache_write_tokens": 4},
                        },
                    },
                },
            }
        }
        result = audit(
            {"provider": "gptlive", "provider_audit": {"sessions": [{"events": [event, event]}]}}
        )
        self.assertEqual(result["native_counter_totals"]["test"]["input_tokens"], 10)
        self.assertEqual(result["unique_backend_responses"], 1)
        self.assertFalse(result["capture_counters_match"])

    def test_omitted_google_usage_is_visible(self):
        native = {
            "kind": "usage_metadata",
            "data": {
                "prompt_token_count": 20,
                "response_token_count": 5,
                "prompt_tokens_details": [{"modality": "AUDIO", "token_count": 17}],
                "response_tokens_details": [{"modality": "AUDIO", "token_count": 5}],
            },
        }
        result = audit(
            {
                "provider": "gemini",
                "model": "test",
                "provider_audit": {"sessions": [{"events": [native]}]},
                "session_usage": {"model_usage": [{"model": "test", "input_tokens": 10}]},
            }
        )
        self.assertFalse(result["capture_counters_match"])
        self.assertTrue(any(d["counter"] == "input_tokens" for d in result["sdk_differences"]))


if __name__ == "__main__":
    unittest.main()
