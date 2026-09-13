"""Explain existing evidence and inspect captured tool exposure without new calls.

This is a diagnostic addendum, never a replacement grader. Private evidence
envelopes are read locally; only explicitly selected prompts and declarations
are exported. Review that selected content before publishing your own study.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

VERSION = "study60-audit-v1"
EMPTY_PARAMETERS = {"type": "object", "properties": {}}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def normalize_schema(value):
    """Compare common fields, explicitly excluding two transport differences.

    additionalProperties is a real constraint difference, not proof of full
    schema equivalence. Raw schemas are retained and this exclusion is reported.
    """
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in {"additionalProperties", "propertyOrdering"}:
                continue
            if key == "required" and item == []:
                continue
            if key == "type" and isinstance(item, str):
                result[key] = item.lower()
            elif key in {"required", "enum"} and isinstance(item, list):
                result[key] = sorted(item)
            else:
                result[key] = normalize_schema(item)
        return result
    if isinstance(value, list):
        return [normalize_schema(item) for item in value]
    return value


def selected_tool(tool):
    # Preserve raw parameter spelling/omission, never copy the session envelope.
    return {
        key: tool[key]
        for key in ("name", "description", "parameters", "parameters_json_schema")
        if key in tool
    }


def tool_map(tools):
    result = {}
    for tool in tools:
        name = tool["name"]
        if name in result:
            raise ValueError(f"Duplicate tool declaration: {name}")
        params = tool.get("parameters", tool.get("parameters_json_schema"))
        result[name] = {
            "description": tool.get("description", ""),
            "parameters": normalize_schema(params if params is not None else EMPTY_PARAMETERS),
        }
    return result


def captured_configs(extra):
    provider = extra["provider"]
    configs = []
    for session in extra.get("provider_audit", {}).get("sessions", []):
        for event in session.get("events", []):
            if event["kind"] != "requested_config":
                continue
            raw = event["data"]
            if provider == "gemini":
                tools = [
                    tool
                    for group in raw.get("tools", [])
                    for tool in group.get("function_declarations", [])
                ]
                instructions = "\n".join(
                    part.get("text", "")
                    for part in raw.get("system_instruction", {}).get("parts", [])
                )
                backend = None
            elif provider == "gptlive":
                live = raw["session"]
                delegate = live["delegation"]["responses"]
                tools = delegate.get("tools", [])
                instructions = live.get("instructions", "")
                backend = delegate.get("instructions", "")
            else:
                raise ValueError(f"Unsupported captured configuration: {provider}")
            configs.append(
                {
                    "provider": provider,
                    "model": extra.get("model"),
                    "backend_model": extra.get("backend_model"),
                    "instruction": instructions,
                    "backend_instruction": backend,
                    "requested_tools": [selected_tool(tool) for tool in tools],
                    "capture_scope": (
                        "SDK-built requested configuration, not a provider acknowledgement "
                        "of each tool"
                    ),
                }
            )
    return configs


def explain_trial(trial):
    grade = trial["grade"]
    corrected = trial.get("grader_errata", {}).get("grade", grade)
    events = (trial.get("sandbox") or {}).get("events", [])
    codes = set(grade.get("policy_violations", []))
    blocks = [
        {
            "event": event["sequence"] + 1,
            "tool": event["tool"],
            "code": event["result"].get("code"),
            "state_unchanged": event["before"] == event["after"],
        }
        for event in events
        if event["result"].get("ok") is False and event["result"].get("code") in codes
    ]
    if grade.get("state_pass") is True:
        headline = "State checks passed"
        if grade.get("policy_pass") is False:
            headline += "; blocked tool attempt recorded"
    elif corrected.get("state_pass") is True:
        headline = "State checks pass with the declared grading correction"
    elif grade.get("state_pass") is False:
        headline = "Strict state checks failed; inspect the cause"
    else:
        headline = "State result is unavailable"
    return {
        "sample_id": trial["sample_id"],
        "trial_id": trial["trial_id"],
        "pair_id": trial["pair_id"],
        "provider": trial["provider"],
        "scenario": trial["scenario"],
        "headline": headline,
        "failed_original_checks": [
            key for key, value in grade.get("checks", {}).items() if value is False
        ],
        "blocked_attempts": blocks,
        "caller_review": trial.get("assessment", {}).get("caller_fidelity", "pending"),
        "existing_assessment": trial.get("assessment", {}).get("attribution"),
        "causal_model_fault": None,
        "overall_task_success": None,
        "interpretation": (
            "State, attempted actions, caller behavior and spoken consent are separate. "
            "No overall success or model-only cause is inferred."
        ),
    }


def build(data, runs):
    rows, configurations = [], {}
    pairs = defaultdict(list)
    for trial in data["trials"]:
        trial_id = trial["trial_id"]
        # Do not allow a dataset to read files outside the supplied runs root.
        folder = (runs / trial_id).resolve()
        if folder.parent != runs.resolve():
            raise ValueError("Trial ID must identify a direct child of the runs directory")
        evidence_path = folder / "agent-evidence.json"
        extra = json.loads(evidence_path.read_text(encoding="utf-8"))["lane_extra"]
        if extra["provider"] != trial["provider"]:
            raise ValueError(f"Provider mismatch: {trial_id}")
        if extra["benchmark"]["grade"] != trial["grade"]:
            raise ValueError(f"Evidence grade mismatch: {trial_id}")
        if (
            extra["runtime_source_sha256"]
            != trial["configuration"]["target"]["runtime_source_sha256"]
        ):
            raise ValueError(f"Runtime fingerprint mismatch: {trial_id}")
        expected = tool_map(extra["tool_declarations"])
        configs = captured_configs(extra)
        ids, comparisons = [], []
        for config in configs:
            key = digest(config)
            configurations[key] = config
            ids.append(key)
            actual = tool_map(config["requested_tools"])
            comparisons.append(
                {
                    "missing_tools": sorted(expected.keys() - actual.keys()),
                    "unexpected_tools": sorted(actual.keys() - expected.keys()),
                    "changed_common_contracts": sorted(
                        name
                        for name in expected.keys() & actual.keys()
                        if expected[name] != actual[name]
                    ),
                }
            )
        matches = bool(comparisons) and all(not any(c.values()) for c in comparisons)
        row = explain_trial(trial)
        row.update(
            {
                "evidence_file_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
                "expected_tool_names": sorted(expected),
                "configuration_ids": ids,
                "captured_config_count": len(configs),
                "tool_contract_comparisons": comparisons,
                "common_tool_contract_matches_registry": matches if configs else None,
                "successful_lookup_calls": sum(
                    event["name"] == "lookup_order" and event["result"].get("ok") is True
                    for event in trial.get("tool_executions", [])
                ),
            }
        )
        rows.append(row)
        pairs[trial["pair_id"]].append((row, expected))
    paired = []
    for pair_id, members in sorted(pairs.items()):
        paired.append(
            {
                "pair_id": pair_id,
                "two_different_targets": len(members) == 2
                and len({r["provider"] for r, _ in members}) == 2,
                "same_registry_contract": len(members) == 2 and members[0][1] == members[1][1],
                "captured_common_contract_matches_both": len(members) == 2
                and all(r["common_tool_contract_matches_registry"] is True for r, _ in members),
            }
        )
    return {
        "version": VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "kind": "post-publication_diagnostic_addendum_original_scores_unchanged",
        "source_study": data["study_id"],
        "scope": (
            "Existing captured configurations and recorded results only; "
            "no new model or telephone calls."
        ),
        "schema_comparison_limits": [
            "Names, descriptions, property types, required fields, enums and numeric "
            "constraints are compared.",
            "Google upper-case types and omitted empty parameter objects are normalized; "
            "raw declarations remain below.",
            "additionalProperties and propertyOrdering are excluded from common-contract "
            "comparison. Google SDK omits additionalProperties:false present in the "
            "shared/OpenAI schemas; full provider constraint equivalence is not established.",
            "Capture occurs where the pinned SDK builds its requested configuration, "
            "not inside the provider. Successful invocation in another call is supporting "
            "evidence, not proof of optimal prompting.",
            "State grades, transcripts and review labels retain the original study's "
            "limitations. A passing capture audit cannot isolate model weights from "
            "prompts, adapters or caller behavior.",
        ],
        "summary": {
            "trials": len(rows),
            "captured_contract_match": sum(
                r["common_tool_contract_matches_registry"] is True for r in rows
            ),
            "pairs": len(paired),
            "matched_pair_contracts": sum(
                p["same_registry_contract"] and p["captured_common_contract_matches_both"]
                for p in paired
            ),
            "successful_lookup_samples": {
                provider: [
                    r["sample_id"]
                    for r in rows
                    if r["provider"] == provider and r["successful_lookup_calls"]
                ]
                for provider in sorted({r["provider"] for r in rows})
            },
            "headlines": dict(Counter(r["headline"] for r in rows)),
        },
        "configurations": configurations,
        "paired_contracts": paired,
        "trials": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.data.read_bytes()
    result = build(json.loads(raw), args.runs)
    result["source_data_sha256"] = hashlib.sha256(raw).hexdigest()
    result["analysis_source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result["summary"]))


if __name__ == "__main__":
    main()
