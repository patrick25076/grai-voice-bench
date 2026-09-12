"""Produce a dated evidence inventory, preserving unknowns and personal-score separation."""

import argparse
import hashlib
import json
import statistics
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from costs import estimate_usage
from review import RUBRIC, read


def complete_task_result(state, policy, gates):
    # An invalid or unreviewed simulated caller cannot establish target quality.
    if gates[0] != "pass" or state is None or policy is None:
        return None
    if state is False or policy is False or "fail" in gates[1:]:
        return False
    return True if gates == ["pass"] * 3 else None


def compile_results(manifest, root):
    plan = read(manifest)
    votes = read(root / "review/votes.json", {"samples": {}})["samples"]
    rows = []
    for index, trial in enumerate(plan["trials"], 1):
        folder = root / trial["output_name"]
        run = read(folder / "run.json", {})
        target = read(folder / "agent-evidence.json", {}).get("lane_extra", {})
        caller = read(folder / "caller-evidence.json", {}).get("lane_extra", {})
        grade = target.get("benchmark", {}).get("grade", {})
        history = votes.get(f"S{index:03d}", {}).get("history", [])
        wavs = list(folder.glob("*.wav"))
        audio_hash = hashlib.sha256(wavs[0].read_bytes()).hexdigest() if len(wavs) == 1 else None
        valid_history = [v for v in history if audio_hash and v.get("audio_sha256") == audio_hash]
        first = valid_history[0] if valid_history else None
        audio_review = valid_history[-1].get("audio_review", {}) if valid_history else {}
        gates = [
            audio_review.get(k, "unreviewed")
            for k in ("caller_fidelity", "spoken_truth", "spoken_consent")
        ]
        state_pass, policy_pass = grade.get("state_pass"), grade.get("policy_pass")
        complete = complete_task_result(state_pass, policy_pass, gates)
        rows.append(
            {
                **{
                    k: trial[k]
                    for k in (
                        "trial_id",
                        "pair_id",
                        "provider",
                        "caller_provider",
                        "language",
                        "scenario",
                    )
                },
                "attempted": (root / "attempts" / f"{trial['trial_id']}.json").exists()
                or bool(run),
                "carrier_status": run.get("status"),
                "recording_sha256": audio_hash,
                "state_pass": state_pass,
                "policy_pass": policy_pass,
                "complete_task_pass": complete,
                "audio_review": audio_review,
                "target_known_cost": estimate_usage(target.get("session_usage", {})),
                "caller_known_cost": estimate_usage(caller.get("session_usage", {})),
                "personal_first_rating": first,
                "personal_rating_revisions": len(valid_history),
                "excluded_rating_revisions_with_wrong_audio_hash": len(history)
                - len(valid_history),
                "validated_latency_ms": None,
                "latency_status": "requires verified, paired acoustic boundary annotations",
            }
        )
    groups = defaultdict(list)
    for row in rows:
        groups[(row["language"], row["caller_provider"], row["provider"])].append(row)
    summaries = []
    for (language, caller, target), group in sorted(groups.items()):
        personal = {}
        for metric in RUBRIC:
            values = [
                r["personal_first_rating"]["ratings"][metric]
                for r in group
                if r["personal_first_rating"]
                and not r["personal_first_rating"]["labels_previously_revealed"]
                and r["personal_first_rating"]["ratings"][metric] is not None
            ]
            personal[metric] = {
                "n": len(values),
                "mean": statistics.mean(values) if values else None,
            }
        summaries.append(
            {
                "language": language,
                "caller_provider": caller,
                "provider": target,
                "scheduled": len(group),
                "attempted": sum(r["attempted"] for r in group),
                "recordings": sum(bool(r["recording_sha256"]) for r in group),
                "state_pass": sum(r["state_pass"] is True for r in group),
                "state_fail": sum(r["state_pass"] is False for r in group),
                "state_unknown": sum(r["state_pass"] is None for r in group),
                "complete_task_pass": sum(r["complete_task_pass"] is True for r in group),
                "complete_task_fail": sum(r["complete_task_pass"] is False for r in group),
                "complete_task_unknown": sum(r["complete_task_pass"] is None for r in group),
                "personal_first_label_hidden_scores": personal,
            }
        )
    return {
        "study_id": plan["study_id"],
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "draft_evidence_inventory_not_a_validated_leaderboard",
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "invoice_total_usd": None,
        "validated_latency_ms": None,
        "limitations": [
            "Selected exploratory scenarios; no universal ranking or significance claim",
            "Costs are incomplete dated SDK components, not invoices or all-in totals",
            "Personal ratings are Patrick's opinions, not independent consensus",
            "Audio gates are human annotations and need evidence review",
            "No validated latency aggregation is implemented in this draft inventory",
        ],
        "groups": summaries,
        "trials": rows,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--runs", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(compile_results(args.manifest, args.runs), stream, ensure_ascii=False, indent=2)
