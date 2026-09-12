"""Export a synthetic study using an explicit public-data allowlist.

Never copy raw provider audit events, account routing, environment files or votes.
The caller and target transcripts must belong to the authorized synthetic study.
Use --draft for inspection; a final export requires every scheduled recording,
role evidence, transcription, replay audit and assistant assessment.
"""

import argparse
import csv
import hashlib
import json
import shutil
import statistics
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from costs import estimate_usage


def read(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def known_total(values):
    known = [v for v in values if v is not None]
    return {
        "known_sum_usd": sum(known) if known else None,
        "known_n": len(known),
        "total_n": len(values),
    }


def reviewed_content_hash(target, caller, asr):
    content = {
        "target_transcript": target["transcript"],
        "caller_transcript": caller["transcript"],
        "benchmark": target["benchmark"],
        "asr": asr,
    }
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def group_summary(rows):
    result = []
    groups = defaultdict(list)
    for row in rows:
        groups[(row["language"], row["provider"])].append(row)
    for (language, provider), group in sorted(groups.items()):
        recorded = [r for r in group if r.get("audio")]
        costs = [r["cost"]["target"]["known_component_estimate_usd"] for r in recorded]
        durations = [
            r["audio_diagnostics"]["audio_levels"]["duration_s"]
            for r in recorded
            if r.get("audio_diagnostics")
        ]
        result.append(
            {
                "language": language,
                "provider": provider,
                "scheduled": len(group),
                "recordings": len(recorded),
                "state_pass": sum(r.get("grade", {}).get("state_pass") is True for r in group),
                "state_fail": sum(r.get("grade", {}).get("state_pass") is False for r in group),
                "state_unknown": sum(r.get("grade", {}).get("state_pass") is None for r in group),
                "policy_pass": sum(r.get("grade", {}).get("policy_pass") is True for r in group),
                "policy_fail": sum(r.get("grade", {}).get("policy_pass") is False for r in group),
                "caller_review_pass": sum(
                    r.get("assessment", {}).get("caller_fidelity") == "pass" for r in group
                ),
                "caller_review_fail": sum(
                    r.get("assessment", {}).get("caller_fidelity") == "fail" for r in group
                ),
                "caller_review_unclear_or_pending": sum(
                    r.get("assessment", {}).get("caller_fidelity") not in {"pass", "fail"}
                    for r in group
                ),
                "target_known_components": known_total(costs),
                "recording_duration_median_s": statistics.median(durations) if durations else None,
                "human_validated_complete_task_rate": None,
                "human_validated_latency_ms": None,
                "personal_score": None,
            }
        )
    return result


def export(manifest, root, output, draft=False):
    if output.exists():
        raise ValueError("Choose a fresh output directory")
    plan = read(manifest)
    summary = {r["run_id"]: r for r in read(root / "summary.json", [])}
    rows, to_copy = [], []
    for index, trial in enumerate(plan["trials"], 1):
        folder = root / trial["output_name"]
        stamp = read(root / "attempts" / f"{trial['trial_id']}.json", {})
        run = read(folder / "run.json", {})
        cards = {role: read(folder / f"{role}-evidence.json", {}) for role in ("agent", "caller")}
        target = cards["agent"].get("lane_extra", {})
        caller = cards["caller"].get("lane_extra", {})
        transcript = read(folder / "analysis/transcript-summary.json", {})
        review = read(folder / "assessment.json", {})
        audit = read(folder / "analysis/offline-audit.json", {})
        wavs = list(folder.glob("*.wav"))
        complete = (
            stamp.get("status") == "evidence_collected"
            and target
            and caller
            and transcript
            and review
            and audit
            and len(wavs) == 1
        )
        if not draft and not complete:
            raise ValueError(
                f"{trial['trial_id']}: incomplete evidence/review; use --draft explicitly"
            )
        if not draft:
            expected_sources = {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in [folder / "agent-evidence.json", folder / "caller-evidence.json", *wavs]
            }
            if audit.get("source_sha256") != expected_sources:
                raise ValueError(f"{trial['trial_id']}: audit source changed; rerun offline audit")
            asr = [read(folder / f"analysis/asr-channel-{i}.json")["transcription"] for i in (0, 1)]
            if review.get("reviewed_content_sha256") != reviewed_content_hash(target, caller, asr):
                raise ValueError(f"{trial['trial_id']}: review source changed; inspect again")
        if audit and not audit["sandbox_replay"]["exact_state_results_and_grade_match"]:
            raise ValueError("Resolve failed replay audit before export")
        sid = f"S{index:03d}"
        row = {
            k: trial[k]
            for k in (
                "trial_id",
                "pair_id",
                "provider",
                "caller_provider",
                "scenario",
                "language",
                "seed",
                "arm_order",
            )
        }
        row.update(
            sample_id=sid,
            audio=None,
            audio_sha256=None,
            attempted=bool(stamp),
            carrier_status=run.get("status"),
            grade=target.get("benchmark", {}).get("grade", {}),
            assessment=review,
        )
        if len(wavs) == 1 and target and caller:
            row["audio"] = f"audio/{sid}.wav"
            row["audio_sha256"] = hashlib.sha256(wavs[0].read_bytes()).hexdigest()
            to_copy.append((wavs[0], row["audio"]))
        # Public JSON uses explicit selections. Raw session events contain account
        # identifiers and must never be copied into a community dataset.
        row["configuration"] = {
            role: {
                k: extra.get(k)
                for k in (
                    "model",
                    "voice",
                    "backend_model",
                    "turn_detection",
                    "auto_gain_control",
                    "room_input_rate",
                    "instruction_sha256",
                    "backend_instruction_sha256",
                    "runtime_source_sha256",
                    "output_audio_formats",
                )
            }
            for role, extra in (("target", target), ("caller", caller))
        }
        row["native_transcripts"] = {
            role: [
                {k: item.get(k) for k in ("role", "text", "received_at_unix")}
                for item in extra.get("transcript", [])
            ]
            for role, extra in (("target", target), ("caller", caller))
        }
        row["independent_asr"] = transcript
        row["sandbox"] = target.get("benchmark", {}).get("sandbox")
        row["tool_executions"] = target.get("benchmark", {}).get("tool_executions", [])
        row["caller_agenda"] = caller.get("benchmark", {}).get("caller_prompt")
        row["audio_diagnostics"] = {k: v for k, v in audit.items() if k not in {"source_sha256"}}
        carrier = summary.get(trial["trial_id"], {})
        row["cost"] = {
            "target": estimate_usage(target.get("session_usage", {})),
            "caller": estimate_usage(caller.get("session_usage", {})),
            "carrier_known_usd": carrier.get("known_carrier_cost_usd"),
            "carrier_pending_prices": carrier.get("pending_carrier_prices"),
            "asr_list_price_estimate_usd": transcript.get("asr_list_price_estimate_usd"),
            "unreconciled_components": carrier.get("unreconciled_costs", []),
            "invoice_total_usd": None,
        }
        # Preserve raw-source hashes without publishing account-bearing filenames.
        row["assessment"] = {k: v for k, v in review.items() if k != "source_sha256"}
        rows.append(row)
    groups = group_summary(rows)
    report = {
        "study_id": plan["study_id"],
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "draft_in_progress"
        if draft
        else "completed_exploratory_evidence_with_listening_pending",
        "evaluation_software": "https://github.com/patrick25076/grai-voice-bench/tree/v0.4.0",
        "frozen_manifest_canonical_sha256": read(manifest.with_suffix(".sha256.json"))["sha256"],
        "scheduled": plan["total_calls"],
        "recordings": sum(bool(r["audio"]) for r in rows),
        "groups": groups,
        "trials": rows,
        "cost_totals": {
            key: known_total([r["cost"][key] for r in rows])
            for key in ("carrier_known_usd", "asr_list_price_estimate_usd")
        },
        "limitations": [
            "Configured systems: Gemini 3.1 Flash Live / Puck versus GPT-Live-1 / marin plus "
            "GPT-5.6-Terra. Not equal-compute isolated base models.",
            "60 selected calls, 50 English and 10 Romanian; eight workflows and three seeded "
            "personas, not 60 independent scenario families. No universal ranking or significance "
            "claim.",
            "30 matched pairs share caller provider, agenda, tools and fixture, but generated "
            "speech varies. Show caller deviations and acoustic uncertainty; raw state pass is "
            "not clean causal attribution.",
            "Deterministic state and guardrail checks are separate from transcript-assisted "
            "assessment, human audio verification and Patrick's personal preference.",
            "Whisper and provider transcripts can hallucinate, omit speech or disagree. Original "
            "dual-channel audio is retained at unchanged level and speed.",
            "RMS gaps are exploratory acoustic diagnostics, not validated response latency. "
            "Receipt timestamps are not audible boundaries. Duration is not speaking speed.",
            "Known USD cost components are dated estimates/posted carrier charges. Missing token "
            "modality, final invoices, media/SIP, hosting, storage, taxes and FX remain "
            "unresolved; EUR reservations are not spend.",
            "Seven development calls are excluded. Evaluation code and assignments were frozen "
            "before the first scored call.",
            "The frozen shared procedure contains an encoding defect in a Romanian product alias; "
            "the explicit enum is dry ice. No causal irrelevance is assumed. Do not silently "
            "repair the frozen experiment.",
            "Patrick's personal scores and human-validated complete-task/latency measurements "
            "remain pending unless explicitly supplied in a later report.",
        ],
    }
    output.mkdir(parents=True)
    (output / "audio").mkdir()
    for source, relative in to_copy:
        shutil.copyfile(source, output / relative)
    (output / "data.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    shutil.copyfile(Path(__file__).with_name("study_report.html"), output / "index.html")
    lines = [
        "# GRAI Labs: 60-call telephone study",
        "",
        f"Status: {report['status']}. {report['recordings']}/{report['scheduled']} recordings.",
        "",
        "Evaluation software: [v0.4.0](https://github.com/patrick25076/grai-voice-bench/tree/v0.4.0).",
        "Canonical frozen manifest SHA-256: `" + report["frozen_manifest_canonical_sha256"] + "`.",
        "",
        "## Recorded sandbox outcomes",
        "",
        "These are raw deterministic outcomes across all attempts, including caller problems. "
        "They are not human-validated success rates.",
        "",
        "| Language | Target | Recordings | State pass | State fail | Policy pass | Policy fail "
        "| Caller review pass |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for group in groups:
        lines.append(
            "| "
            + " | ".join(
                str(group[k])
                for k in (
                    "language",
                    "provider",
                    "recordings",
                    "state_pass",
                    "state_fail",
                    "policy_pass",
                    "policy_fail",
                    "caller_review_pass",
                )
            )
            + " |"
        )
    lines += ["", "## Interpretation limits", ""] + ["- " + s for s in report["limitations"]]
    lines += [
        "",
        "See data.json for each recording, assignment, transcript, state transition, assessment "
        "and cost component. Listen before making a model claim.",
        "",
    ]
    (output / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    flat_rows = []
    for row in rows:
        flat_rows.append(
            {
                **{
                    k: row[k]
                    for k in (
                        "sample_id",
                        "trial_id",
                        "pair_id",
                        "language",
                        "provider",
                        "caller_provider",
                        "scenario",
                        "attempted",
                        "carrier_status",
                        "audio_sha256",
                    )
                },
                "state_pass": row["grade"].get("state_pass"),
                "policy_pass": row["grade"].get("policy_pass"),
                "caller_transcript_review": row["assessment"].get("caller_fidelity"),
                "spoken_truth_transcript_review": row["assessment"].get("spoken_truth"),
                "spoken_consent_transcript_review": row["assessment"].get("spoken_consent"),
                "human_audio_verified": False,
                "recording_duration_s": row["audio_diagnostics"]
                .get("audio_levels", {})
                .get("duration_s"),
                "target_known_model_components_usd": row["cost"]["target"][
                    "known_component_estimate_usd"
                ],
                "caller_known_model_components_usd": row["cost"]["caller"][
                    "known_component_estimate_usd"
                ],
                "carrier_known_usd": row["cost"]["carrier_known_usd"],
                "asr_estimate_usd": row["cost"]["asr_list_price_estimate_usd"],
                "validated_latency_ms": None,
                "invoice_total_usd": None,
                "personal_score": None,
            }
        )
    with (output / "trials.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(flat_rows[0]))
        writer.writeheader()
        writer.writerows(flat_rows)
    hashes = {
        p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(output.rglob("*"))
        if p.is_file()
    }
    (output / "SHA256SUMS.json").write_text(json.dumps(hashes, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "recordings": report["recordings"], "draft": draft}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--runs", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--draft", action="store_true")
    a = p.parse_args()
    export(a.manifest, a.runs, a.output, a.draft)
