"""Compare captured native usage to SDK counters without claiming invoice totals.

This is an offline capture audit. Google event sums reproduce the adapter's
per-response accounting, not an independent interpretation of provider billing.
OpenAI voice counters use one final snapshot per session; backend responses are
deduplicated by response ID. Raw provider events never get summed indiscriminately.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def audit(extra):
    sessions = extra.get("provider_audit", {}).get("sessions", [])
    raw = defaultdict(lambda: defaultdict(float))
    concerns = []
    response_ids = set()
    native_count = 0
    if extra.get("provider") == "gptlive":
        responses = {}
        for session in sessions:
            events = [e["data"] for e in session.get("events", [])]
            closed = [e for e in events if e.get("type") == "session.closed"]
            if len(closed) != 1 or not number(closed[-1].get("usage", {}).get("seconds")):
                concerns.append("Missing or ambiguous final voice usage snapshot")
            else:
                raw["gpt-live-1"]["session_duration"] += closed[-1]["usage"]["seconds"]
            for event in events:
                nested = event.get("event", {})
                response = nested.get("response", {})
                if nested.get("type") not in {
                    "response.completed",
                    "response.failed",
                    "response.incomplete",
                    "response.cancelled",
                } or not response.get("usage"):
                    continue
                identity = response.get("id")
                if not identity:
                    concerns.append("Backend usage without response ID")
                    continue
                if identity in responses and responses[identity] != response:
                    concerns.append("Conflicting terminal response snapshots")
                responses[identity] = response
        for identity, response in responses.items():
            response_ids.add(identity)
            usage = response["usage"]
            details = usage.get("input_tokens_details", {})
            values = {
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "input_cached_tokens": details.get("cached_tokens"),
                "input_cache_creation_tokens": details.get("cache_write_tokens"),
            }
            for key, value in values.items():
                if not number(value):
                    concerns.append("Backend usage missing " + key)
                else:
                    raw[response.get("model", "unknown")][key] += value
        native_count = len(responses)
    elif extra.get("provider") == "gemini":
        model = extra["model"]
        for session in sessions:
            for event in session.get("events", []):
                if event.get("kind") != "usage_metadata":
                    continue
                native_count += 1
                data = event["data"]
                for source, dest in (
                    ("prompt_token_count", "input_tokens"),
                    ("response_token_count", "output_tokens"),
                ):
                    if number(data.get(source)):
                        raw[model][dest] += data[source]
                    else:
                        concerns.append("Google event missing " + source)
                for source, dest in (
                    ("prompt_tokens_details", "input"),
                    ("response_tokens_details", "output"),
                ):
                    for modality in ("audio", "text"):
                        raw[model][f"{dest}_{modality}_tokens"] += sum(
                            item["token_count"]
                            for item in data.get(source, [])
                            if item.get("modality", "").lower() == modality
                            and number(item.get("token_count"))
                        )
        if not native_count:
            concerns.append("No native Google usage captured")
    else:
        concerns.append("Unsupported provider")
    sdk = defaultdict(lambda: defaultdict(float))
    for row in extra.get("session_usage", {}).get("model_usage", []):
        for key, value in row.items():
            if number(value):
                sdk[row["model"]][key] += value
    differences = []
    for model, counters in raw.items():
        for key, native in counters.items():
            observed = sdk.get(model, {}).get(key)
            if observed is None or not math.isclose(native, observed, abs_tol=1e-6):
                differences.append(
                    {"model": model, "counter": key, "native": native, "sdk": observed}
                )
    for model in sdk:
        if model not in raw:
            concerns.append("SDK model has no matching native usage: " + model)
    return {
        "provider": extra.get("provider"),
        "native_usage_event_count": native_count,
        "unique_backend_responses": len(response_ids),
        "native_counter_totals": dict(raw),
        "sdk_differences": differences,
        "capture_concerns": sorted(set(concerns)),
        "capture_counters_match": bool(raw) and not concerns and not differences,
        "invoice_verified": False,
        "limitation": (
            "Matching counters only verifies capture. Missing modality, provider billing rules, "
            "services and taxes remain unresolved."
        ),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("evidence", type=Path)
    args = p.parse_args()
    data = json.loads(args.evidence.read_text(encoding="utf-8"))
    print(json.dumps(audit(data["lane_extra"]), indent=2))
