"""Offline checks for study accounting, native tool conversion and review integrity."""

import copy
import unittest
from collections import Counter, defaultdict
from unittest.mock import AsyncMock, patch

from livekit.agents import llm
from livekit.plugins.google.utils import create_tools_config
from livekit.plugins.openai.realtime.gpt_live_model import _build_delegation_tools
from voicelab.simulations.cases import CASES, SimulationCase
from voicelab.simulations.study60 import make_plan

from benchmark_support import BenchmarkContext
from costs import estimate_usage
from provider_audit import attach_audit
from results import complete_task_result
from review import GATES, RUBRIC, validate_vote


def normalized(schema):
    if isinstance(schema, dict):
        return {
            k: normalized(v)
            for k, v in schema.items()
            if k not in {"additionalProperties", "propertyOrdering"}
        }
    if isinstance(schema, list):
        return [normalized(v) for v in schema]
    if isinstance(schema, str) and schema in {
        "OBJECT",
        "STRING",
        "NUMBER",
        "INTEGER",
        "BOOLEAN",
        "ARRAY",
    }:
        return schema.lower()
    return schema


class StudyChecks(unittest.TestCase):
    def test_caller_only_receives_the_assigned_second_address(self):
        for name in CASES:
            for language in ("en", "ro"):
                case = SimulationCase(name, language=language)
                self.assertEqual(
                    case.second_address in case.call.caller_prompt, name == "sim-change-address"
                )
                if name in {"sim-amend-quantity", "sim-change-address", "sim-cancel-order"}:
                    self.assertIn("no order exists yet", case.call.caller_prompt)

    def test_invalid_caller_cannot_establish_target_quality(self):
        self.assertIsNone(complete_task_result(False, True, ["fail", "pass", "pass"]))
        self.assertIsNone(complete_task_result(True, True, ["unreviewed"] * 3))
        self.assertIs(complete_task_result(False, True, ["pass"] * 3), False)
        self.assertIs(complete_task_result(True, True, ["pass"] * 3), True)

    def test_exact_counts_and_matched_conditions(self):
        plan = make_plan()
        trials = plan["trials"]
        self.assertEqual(Counter(t["language"] for t in trials), {"en": 50, "ro": 10})
        self.assertEqual(Counter(t["provider"] for t in trials), {"gemini": 30, "gptlive": 30})
        self.assertEqual(
            Counter(t["caller_provider"] for t in trials), {"gemini": 30, "gptlive": 30}
        )
        pairs = defaultdict(list)
        for trial in trials:
            pairs[trial["pair_id"]].append(trial)
        self.assertEqual(len(pairs), 30)
        for a, b in pairs.values():
            for key in (
                "scenario",
                "seed",
                "language",
                "caller_provider",
                "seconds",
                "tool_delay_ms",
                "fixture_sha256",
                "caller_prompt_sha256",
                "job_spec_sha256",
                "tool_schema_sha256",
            ):
                self.assertEqual(a[key], b[key])
            self.assertNotEqual(a["provider"], b["provider"])
        self.assertEqual(
            Counter(p[0]["provider"] for p in pairs.values()), {"gemini": 15, "gptlive": 15}
        )

    def test_real_sdk_native_schemas_preserve_parameters(self):
        context = BenchmarkContext("sim-amend-quantity", 41, "en")
        wrapped = context.tools()
        openai = {t["name"]: t for t in _build_delegation_tools(wrapped)}
        google, _ = create_tools_config(llm.ToolContext(wrapped), use_parameters_json_schema=False)
        gemini = {
            t.name: t.model_dump(mode="json", exclude_none=True)
            for group in google
            for t in group.function_declarations
        }
        self.assertEqual(set(openai), set(context.registry.names()))
        self.assertEqual(set(gemini), set(openai))
        for name in openai:
            google_parameters = gemini[name].get("parameters") or gemini[name].get(
                "parameters_json_schema"
            )
            if google_parameters is None and not openai[name]["parameters"].get("properties"):
                google_parameters = {"type": "object", "properties": {}, "required": []}
            self.assertEqual(normalized(openai[name]["parameters"]), normalized(google_parameters))
            self.assertEqual(openai[name]["description"], gemini[name]["description"])
        self.assertEqual(_build_delegation_tools([]), [])
        self.assertEqual(create_tools_config(llm.ToolContext([]))[0], [])

    def test_missing_usage_is_not_zero_for_known_models(self):
        for model in ("gpt-live-1", "gpt-5.6-terra", "gemini-3.1-flash-live-preview"):
            cost = estimate_usage({"model_usage": [{"model": model}]})
            self.assertIsNone(cost["known_component_estimate_usd"])
            self.assertFalse(cost["usage_complete"])
        cost = estimate_usage(
            {"model_usage": [{"model": "gpt-live-1", "session_duration": float("nan")}]}
        )
        self.assertIsNone(cost["known_component_estimate_usd"])

    def test_subjective_rating_does_not_assert_task_success(self):
        vote = {
            "sample_id": "S001",
            "ratings": dict.fromkeys(RUBRIC, 5),
            "audio_review": dict.fromkeys(GATES, "unreviewed"),
        }
        stored = validate_vote(vote, {"S001"})
        self.assertNotIn("overall_pass", stored)
        self.assertEqual(stored["audio_review"]["spoken_consent"], "unreviewed")
        for invalid in (True, 6, -1, "5"):
            broken = copy.deepcopy(vote)
            broken["ratings"]["personal_overall"] = invalid
            with self.assertRaises(ValueError):
                validate_vote(broken, {"S001"})


class AuditChecks(unittest.IsolatedAsyncioTestCase):
    async def test_pinned_native_config_hooks_without_network(self):
        from livekit.plugins.google.realtime.realtime_api import RealtimeModel, RealtimeSession
        from livekit.plugins.openai.realtime.gpt_live_model import GPTLiveModel, GPTLiveSession

        for provider, model_class, session_class, method in (
            ("gemini", RealtimeModel, RealtimeSession, "_build_connect_config"),
            ("gptlive", GPTLiveModel, GPTLiveSession, "_session_start_event"),
        ):
            with patch.object(session_class, "_main_task", new=AsyncMock(return_value=None)):
                model = model_class(api_key="offline-test-placeholder")
                evidence = {}
                attach_audit(model, provider, evidence)
                session = model.session()
                getattr(session, method)()
                events = evidence["provider_audit"]["sessions"][0]["events"]
                self.assertEqual(events[0]["kind"], "requested_config")
                self.assertIsInstance(events[0]["data"], dict)
                await model.aclose()


if __name__ == "__main__":
    unittest.main()
