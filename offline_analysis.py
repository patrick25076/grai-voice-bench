"""Recheck recorded sandbox transitions, usage capture and acoustic diagnostics.

No model calls, phone calls, production writes or subjective ratings. Run using
the same source version as the recorded worker. Acoustic metrics remain proxies.
"""

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from voicelab.simulations.cases import SimulationCase

from audio_diagnostics import levels
from provider_audit import runtime_fingerprint
from report import analyze
from usage_audit import audit


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


async def check_sandbox(benchmark):
    case = SimulationCase(benchmark["scenario"], benchmark["seed"], benchmark["language"])
    sandbox = benchmark["sandbox"]
    differences = []
    if case.sandbox.snapshot() != sandbox["initial_state"]:
        differences.append("initial_state")
    for event in sandbox["events"]:
        if case.sandbox.snapshot() != event["before"]:
            differences.append(f"event_{event['sequence']}_before")
        result = await case.sandbox.execute(event["tool"], event["arguments"])
        if result != event["result"]:
            differences.append(f"event_{event['sequence']}_result")
        if case.sandbox.snapshot() != event["after"]:
            differences.append(f"event_{event['sequence']}_after")
    if case.sandbox.snapshot() != sandbox["final_state"]:
        differences.append("final_state")
    if case.grade() != benchmark["grade"]:
        differences.append("grade")
    return {
        "events_replayed": len(sandbox["events"]),
        "exact_state_results_and_grade_match": not differences,
        "differences": differences,
        "scope": (
            "Deterministic replay verifies captured tool transitions and grader output, "
            "not caller speech or consent."
        ),
    }


async def analyze_call(folder):
    paths = [folder / f"{role}-evidence.json" for role in ("agent", "caller")]
    wavs = list(folder.glob("*.wav"))
    if not all(p.exists() for p in paths) or len(wavs) != 1:
        raise ValueError("Two role evidence files and one original recording required")
    sources = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths + wavs}
    dest = folder / "analysis/offline-audit.json"
    if dest.exists() and read(dest).get("source_sha256") == sources:
        return read(dest)
    roles = {
        role: read(path)["lane_extra"]
        for role, path in zip(("agent", "caller"), paths, strict=True)
    }
    if any(extra.get("runtime_source_sha256") != runtime_fingerprint() for extra in roles.values()):
        raise ValueError("Use the exact recorded worker source for replay")
    benchmark = roles["agent"]["benchmark"]
    tools = benchmark.get("tool_executions", [])
    result = {
        "trial_id": folder.name,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_sha256": sources,
        "sandbox_replay": await check_sandbox(benchmark),
        "usage_capture": {role: audit(extra) for role, extra in roles.items()},
        "audio_levels": levels(wavs[0]),
        "acoustic_diagnostics": analyze(wavs[0], caller_channel=0),
        "tool_execution_count": len(tools),
        "tool_registry_failures": sum(t.get("ok") is False for t in tools),
        "business_error_codes": [
            t["result"].get("code", "unspecified")
            for t in tools
            if t.get("result", {}).get("ok") is False
        ],
        "validated_latency_ms": None,
        "human_audio_review": "pending",
        "personal_rating": None,
    }
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


async def main(root):
    folders = [root] if (root / "run.json").exists() else sorted(root.glob("P*-*"))
    for folder in folders:
        if (
            not (folder / "agent-evidence.json").exists()
            or not (folder / "caller-evidence.json").exists()
        ):
            continue
        result = await analyze_call(folder)
        print(
            json.dumps(
                {
                    "trial": folder.name,
                    "replay_match": result["sandbox_replay"]["exact_state_results_and_grade_match"],
                    "usage_match": {
                        role: value["capture_counters_match"]
                        for role, value in result["usage_capture"].items()
                    },
                }
            )
        )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    asyncio.run(main(p.parse_args().root))
