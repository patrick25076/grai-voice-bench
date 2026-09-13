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
from grade_errata import apply_errata


def read(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def known_total(values):
    known = [v for v in values if v is not None]
    return {
        "known_sum_usd": sum(known) if known else None,
        "known_n": len(known),
        "total_n": len(values),
    }


def secondary_asr_cost(row):
    usage = row.get("transcription", {}).get("usage", {})
    if usage.get("type") == "duration" and isinstance(usage.get("seconds"), (int, float)):
        return usage["seconds"] / 60 * 0.0045
    return row["list_price_estimate_usd"]


def distribution(values):
    known = [value for value in values if value is not None]
    return {
        "n": len(known),
        "total_n": len(values),
        "median": statistics.median(known) if known else None,
        "min": min(known) if known else None,
        "max": max(known) if known else None,
    }


def measurement_summary(rows):
    def acoustic(row):
        return row.get("audio_diagnostics", {}).get("acoustic_diagnostics", {})

    def target_level(row):
        channels = row.get("audio_diagnostics", {}).get("audio_levels", {}).get("channels", [])
        return next(
            (c.get("active_frame_median_dbfs") for c in channels if c["channel"] == 1), None
        )

    return {
        "call_median_energy_gap_ms": distribution(
            [acoustic(row).get("median_audio_proxy_gap_ms") for row in rows]
        ),
        "target_active_frame_median_dbfs": distribution([target_level(row) for row in rows]),
        "overlap_ms": distribution([acoustic(row).get("overlap_ms") for row in rows]),
        "measurement_unit": "one statistic per call; calls have equal weight",
        "scope": (
            "Exploratory PCM energy measurements, not validated turn latency, LUFS or speech speed."
        ),
    }


def reviewed_content_hash(target, caller, asr, secondary=None):
    content = {
        "target_transcript": target["transcript"],
        "caller_transcript": caller["transcript"],
        "benchmark": target["benchmark"],
        "asr": asr,
    }
    if secondary is not None:
        content["secondary_asr"] = secondary
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def measurement_tables(groups):
    def number(value, digits=2):
        return "unknown" if value is None else f"{value:.{digits}f}"

    lines = [
        "",
        "## Known cost components (USD)",
        "",
        "These are component estimates and posted carrier charges, not a complete invoice. "
        "Target and simulator costs are separate. Unknown modality and unbilled services are "
        "not zero. Compare costs with outcomes and duration: early failures and silent hangup "
        "tails affect these totals. This is not cost per verified successful task. The approved "
        "EUR budget is a spending limit, not an exchange-rate conversion.",
        "ASR includes original Whisper plus supplemental gpt-transcribe. Supplemental estimates "
        "use reported API duration when available; raw envelopes retain the original "
        "input-duration estimate.",
        "",
        "| Language | Target | Calls | Target model | Caller model | Carrier + recording | ASR |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for g in groups:
        cells = [g["language"], g["provider"], str(g["recordings"])]
        for k in ("target", "caller", "carrier", "asr"):
            part = g[k + "_known_components"] if k != "target" else g["target_known_components"]
            cells.append(
                number(part["known_sum_usd"], 4) + f" ({part['known_n']}/{part['total_n']})"
            )
        lines.append("| " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Exploratory audio measurements",
        "",
        "Each call has equal weight: the gap column is the median of per-call median energy "
        "gaps, not a pooled turn statistic. PCM16 RMS threshold 300, 20 ms frames and a 400 ms "
        "segment merge were used. Overlapping responses are excluded from gaps; acknowledgments "
        "can count as responses. These are not validated semantic response times. Active-frame "
        "dBFS is not LUFS or a measure of whispering/speaking speed. Silent hangup tails remain "
        "in recording duration and costs. A fixed energy threshold can miss quieter speech "
        "and shift detected boundaries differently across voices. Original recordings are "
        "unchanged.",
        "",
        "| Language | Target | Gap observations | Median call gap (ms) | Median target active dBFS "
        "| Median recording duration (s) |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for g in groups:
        m = g["audio_measurements"]
        gap = m["call_median_energy_gap_ms"]
        lines.append(
            "| "
            + " | ".join(
                [
                    g["language"],
                    g["provider"],
                    f"{gap['n']}/{gap['total_n']}",
                    number(gap["median"], 0),
                    number(m["target_active_frame_median_dbfs"]["median"]),
                    number(g["recording_duration_median_s"]),
                ]
            )
            + " |"
        )
    lines += [
        "",
        "## Transcript-assisted checks",
        "",
        "These provisional checks compare native text, independent ASR and sandbox evidence. "
        "They are assistant assessments, not Patrick's scores or verified human listening. "
        "Disputed audible details remain unclear. Readback/consent can fail even when a model "
        "sets confirmed=true and the sandbox accepts its write.",
        "",
        "| Language | Target | Gate | Pass | Fail | Unclear | Not applicable | Pending |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for g in groups:
        for gate, counts in g["transcript_gates"].items():
            lines.append(
                "| "
                + " | ".join(
                    [
                        g["language"],
                        g["provider"],
                        gate,
                        *[
                            str(counts[k])
                            for k in ("pass", "fail", "unclear", "not_applicable", "pending")
                        ],
                    ]
                )
                + " |"
            )
    return lines


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
                "state_pass_with_erratum": sum(
                    r.get("grader_errata", {}).get("grade", {}).get("state_pass") is True
                    for r in group
                ),
                "erratum_applied_calls": sum(
                    bool(r.get("grader_errata", {}).get("applied")) for r in group
                ),
                "policy_pass": sum(r.get("grade", {}).get("policy_pass") is True for r in group),
                "policy_fail": sum(r.get("grade", {}).get("policy_pass") is False for r in group),
                "state_and_policy_pass": sum(
                    r.get("grade", {}).get("state_pass") is True
                    and r.get("grade", {}).get("policy_pass") is True
                    for r in group
                ),
                "transcript_gates": {
                    gate: {
                        value: sum(
                            r.get("assessment", {}).get(gate, "pending") == value for r in group
                        )
                        for value in ("pass", "fail", "unclear", "not_applicable", "pending")
                    }
                    for gate in ("caller_fidelity", "spoken_truth", "spoken_consent")
                },
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
                "caller_known_components": known_total(
                    [r["cost"]["caller"]["known_component_estimate_usd"] for r in recorded]
                ),
                "carrier_known_components": known_total(
                    [r["cost"]["carrier_known_usd"] for r in recorded]
                ),
                "asr_known_components": known_total(
                    [r["cost"]["asr_list_price_estimate_usd"] for r in recorded]
                ),
                "audio_measurements": measurement_summary(group),
                "recording_duration_median_s": statistics.median(durations) if durations else None,
                "human_validated_complete_task_rate": None,
                "human_validated_latency_ms": None,
                "personal_score": None,
            }
        )
    return result


def stratified_summary(rows, keys):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[k] for k in keys)].append(row)
    return [
        {**summary, **dict(zip(keys, identity, strict=True))}
        for identity, group in sorted(groups.items())
        for summary in group_summary(group)
    ]


def paired_outcomes(rows):
    pairs = defaultdict(dict)
    for row in rows:
        if row["provider"] in pairs[row["pair_id"]]:
            raise ValueError("Duplicate target arm in a matched pair")
        pairs[row["pair_id"]][row["provider"]] = row
    result = []
    for identity, arms in sorted(pairs.items()):
        sample = next(iter(arms.values()))
        states = {
            p: arms.get(p, {}).get("grade", {}).get("state_pass") for p in ("gemini", "gptlive")
        }
        if any(value is None for value in states.values()):
            pattern = "incomplete_evidence"
        elif all(states.values()):
            pattern = "both_pass"
        elif not any(states.values()):
            pattern = "both_fail"
        else:
            pattern = next(p for p, value in states.items() if value) + "_only_pass"
        result.append(
            {
                "pair_id": identity,
                **{k: sample[k] for k in ("language", "scenario", "caller_provider")},
                "raw_state_pattern": pattern,
                "both_caller_transcript_reviews_pass": len(arms) == 2
                and all(
                    a.get("assessment", {}).get("caller_fidelity") == "pass" for a in arms.values()
                ),
                "states": states,
            }
        )
    return result


def export(manifest, root, output, draft=False):
    if output.exists():
        raise ValueError("Choose a fresh output directory")
    plan = read(manifest)
    canonical = hashlib.sha256(
        json.dumps(plan, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    if canonical != read(manifest.with_suffix(".sha256.json"))["sha256"]:
        raise ValueError("Frozen manifest hash mismatch")
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
        secondary = [read(folder / f"analysis/asr-secondary-{i}.json") for i in (0, 1)]
        secondary_complete = all(secondary)
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
            and secondary_complete
        )
        if not draft and not complete:
            raise ValueError(
                f"{trial['trial_id']}: incomplete evidence/review; use --draft explicitly"
            )
        if not draft:
            from study import check_evidence

            check_evidence(folder, plan["observed_profiles"])
            for key in ("provider", "caller_provider", "scenario", "language", "seed"):
                if run["setup"].get(key) != trial[key]:
                    raise ValueError(f"{trial['trial_id']}: assignment mismatch for {key}")
            expected_sources = {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in [folder / "agent-evidence.json", folder / "caller-evidence.json", *wavs]
            }
            if audit.get("source_sha256") != expected_sources:
                raise ValueError(f"{trial['trial_id']}: audit source changed; rerun offline audit")
            asr = [read(folder / f"analysis/asr-channel-{i}.json")["transcription"] for i in (0, 1)]
            if review.get("reviewed_content_sha256") != reviewed_content_hash(
                target, caller, asr, [r["transcription"] for r in secondary]
            ):
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
            attempted_at_utc=stamp.get("started_at"),
            collected_at_utc=stamp.get("completed_at"),
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
        row["supplemental_asr"] = [r for r in secondary if r]
        row["sandbox"] = target.get("benchmark", {}).get("sandbox")
        row["tool_executions"] = target.get("benchmark", {}).get("tool_executions", [])
        row["caller_agenda"] = caller.get("benchmark", {}).get("caller_prompt")
        row["grader_errata"] = apply_errata(target.get("benchmark", {}))
        row["audio_diagnostics"] = {k: v for k, v in audit.items() if k not in {"source_sha256"}}
        carrier = summary.get(trial["trial_id"], {})
        row["cost"] = {
            "target": estimate_usage(target.get("session_usage", {})),
            "caller": estimate_usage(caller.get("session_usage", {})),
            "carrier_known_usd": carrier.get("known_carrier_cost_usd"),
            "carrier_pending_prices": carrier.get("pending_carrier_prices"),
            "primary_asr_list_price_estimate_usd": transcript.get("asr_list_price_estimate_usd"),
            "secondary_asr_list_price_estimate_usd": sum(
                secondary_asr_cost(r) for r in secondary if r
            )
            if secondary_complete
            else None,
            "asr_list_price_estimate_usd": (
                transcript["asr_list_price_estimate_usd"]
                + sum(secondary_asr_cost(r) for r in secondary if r)
                if transcript.get("asr_list_price_estimate_usd") is not None
                else None
            ),
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
        "analysis_software": "https://github.com/patrick25076/grai-voice-bench/tree/study60-v1",
        "exact_analysis_source_archive": (
            "https://github.com/patrick25076/grai-voice-bench/releases/download/"
            "study60-v1/grai-voice-bench-study60-v1-source.zip"
        ),
        "analysis_source_sha256": {
            name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in (
                "publish_study.py",
                "grade_errata.py",
                "offline_analysis.py",
                "usage_audit.py",
                "secondary_asr.py",
                "audio_diagnostics.py",
                "report.py",
                "costs.py",
            )
        },
        "exact_frozen_source_archive": (
            "https://github.com/patrick25076/grai-voice-bench/releases/download/"
            "v0.4.0/frozen-source-v0.4.0.zip"
        ),
        "exact_frozen_source_archive_sha256": (
            "7ec62a4821f5b881409e35e08ce6dfe652d50678a15fef737ae271804a10255c"
        ),
        "observed_period_utc": {
            "first_attempt": min(
                (r["attempted_at_utc"] for r in rows if r["attempted_at_utc"]), default=None
            ),
            "last_evidence_collection": max(
                (r["collected_at_utc"] for r in rows if r["collected_at_utc"]), default=None
            ),
        },
        "frozen_manifest_canonical_sha256": read(manifest.with_suffix(".sha256.json"))["sha256"],
        "scheduled": plan["total_calls"],
        "recordings": sum(bool(r["audio"]) for r in rows),
        "secondary_transcribed_calls": sum(len(r["supplemental_asr"]) == 2 for r in rows),
        "groups": groups,
        "caller_strata": stratified_summary(rows, ("language", "caller_provider")),
        "case_strata": stratified_summary(rows, ("language", "scenario")),
        "paired_outcomes": paired_outcomes(rows),
        "trials": rows,
        "cost_totals": {
            key: known_total([r["cost"][key] for r in rows])
            for key in ("carrier_known_usd", "asr_list_price_estimate_usd")
        },
        "limitations": [
            "Configured systems: Gemini 3.1 Flash Live / Puck versus GPT-Live-1 / marin plus "
            "GPT-5.6-Terra. Not equal-compute isolated base models.",
            "Calibration checked routing, caller agendas, native tool exposure and working "
            "examples before freezing. It does not establish that either prompt is optimal "
            "or that a failure is independent of prompt and adapter design.",
            "60 selected calls, 50 English and 10 Romanian; eight workflows and three seeded "
            "personas, not 60 independent scenario families. No universal ranking or significance "
            "claim.",
            "30 matched pairs share caller provider, agenda, tools and fixture, but generated "
            "speech varies. Show caller deviations and acoustic uncertainty; raw state pass is "
            "not clean causal attribution.",
            "Seeds reproduce fixtures and persona selection, not generated speech. Recorded "
            "model IDs and source hashes do not freeze provider-side model updates; this is "
            "evidence of the observed configurations and dates.",
            "Caller behavior is affected by the target's responses. The subset with passing "
            "caller reviews is a post-hoc diagnostic subset, not an unbiased causal comparison.",
            "Deterministic state and guardrail checks are separate from transcript-assisted "
            "assessment, human audio verification and Patrick's personal preference.",
            "The Codex assistant's transcript-assisted assessments were made with model labels "
            "visible. They are provisional and are not an independent or blinded review panel.",
            "The state grade includes exact lifecycle and message-count rules. An unnecessary "
            "no-op update can fail its required sequence even when the final cancellation is "
            "correct. Address normalization can also reject semantically equivalent wording "
            "such as adding the Romanian word for number. Read each failed check and the "
            "accompanying assessment; these rules were not relaxed after seeing results.",
            "Whisper and provider transcripts can hallucinate, omit speech or disagree. Original "
            "dual-channel audio is retained at unchanged level and speed.",
            "After major Whisper omissions/repetition were observed, all 60 recordings received "
            "a supplemental gpt-transcribe pass on both channels without an expected-text prompt. "
            "This post-start analysis addition preserves the original ASR and grades. Agreement "
            "between transcribers is supporting machine evidence, not human audio verification.",
            "Whisper and gpt-transcribe are both OpenAI transcription systems; their errors may "
            "be correlated. They were not given the expected order facts or benchmark answers.",
            "RMS gaps are exploratory acoustic diagnostics, not validated response latency. "
            "The fixed energy threshold can miss quieter speech. Receipt timestamps are not "
            "audible boundaries. Duration is not speaking speed.",
            "Known USD cost components are dated estimates/posted carrier charges. Missing token "
            "modality, final invoices, media/SIP, hosting, storage, taxes and FX remain "
            "unresolved; EUR reservations are not spend.",
            "Seven development calls are excluded. Evaluation code and assignments were frozen "
            "before the first scored call.",
            "Patrick's personal scores and human-validated complete-task/latency measurements "
            "remain pending unless explicitly supplied in a later report.",
            "The frozen lexical hangup fallback misses bye/bye-bye when the caller omits its "
            "finish_call tool. Preserve these silent tails and charges, but do not call them "
            "slow target task completion.",
            "The strict stock-followup grader distinguishes an empty optional order reference "
            "from an absent one; the single-message rule also rejects a separate contact note. "
            "Per-call assessments disclose these grading limitations rather than treating every "
            "strict failure as failure of the customer's business goal.",
            "A declared post-start erratum treats an empty optional stock-request order reference "
            "as absent. It is applied equally to both targets and preserves original scores; it "
            "does not relax quantity, message count, stock, order ownership or policy checks.",
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
        "[Listen and inspect the calls](https://patrick25076.github.io/grai-voice-bench/) "
        "or [download the versioned dataset](https://github.com/patrick25076/"
        "grai-voice-bench/releases/tag/study60-v1).",
        "",
        "Evaluation software: [v0.4.0](https://github.com/patrick25076/grai-voice-bench/tree/v0.4.0).",
        f"Analysis software: [study60-v1]({report['analysis_software']}); "
        f"[exact analysis source bytes]({report['exact_analysis_source_archive']}). "
        "Per-file analysis hashes are recorded in data.json.",
        f"Exact source bytes: [frozen archive]({report['exact_frozen_source_archive']}) "
        f"(SHA-256 `{report['exact_frozen_source_archive_sha256']}`).",
        f"Observed UTC period: {report['observed_period_utc']['first_attempt']} to "
        f"{report['observed_period_utc']['last_evidence_collection']} (last evidence collection).",
        "Canonical frozen manifest SHA-256: `" + report["frozen_manifest_canonical_sha256"] + "`.",
        "",
        "## Recorded sandbox outcomes",
        "",
        "These are raw deterministic outcomes across all attempts, including caller problems. "
        "They include strict action-sequence/cardinality rules, not only final record contents. "
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
    lines += [
        "",
        "## Declared grading erratum",
        "",
        "An empty optional stock-request order reference and an absent one both identify no "
        "order. The frozen grader distinguished them. The correction below was declared "
        "after evaluation began, applies to both targets, and changes only that equivalence. "
        "Original scores above and all original traces remain preserved.",
        "",
        "| Language | Target | Original state passes | Passes with erratum | Affected calls |",
        "|---|---|---:|---:|---:|",
    ]
    for group in groups:
        lines.append(
            "| "
            + " | ".join(
                str(group[k])
                for k in (
                    "language",
                    "provider",
                    "state_pass",
                    "state_pass_with_erratum",
                    "erratum_applied_calls",
                )
            )
            + " |"
        )
    lines += [
        "",
        "## Outcomes by caller provider",
        "",
        "| Language | Caller | Target | State pass | State fail | State unknown |",
        "|---|---|---|---:|---:|---:|",
    ]
    for group in report["caller_strata"]:
        lines.append(
            "| "
            + " | ".join(
                str(group[k])
                for k in (
                    "language",
                    "caller_provider",
                    "provider",
                    "state_pass",
                    "state_fail",
                    "state_unknown",
                )
            )
            + " |"
        )
    lines += [
        "",
        "## Outcomes by workflow",
        "",
        "| Language | Case | Target | State pass | State fail | State unknown |",
        "|---|---|---|---:|---:|---:|",
    ]
    for group in report["case_strata"]:
        lines.append(
            "| "
            + " | ".join(
                str(group[k])
                for k in (
                    "language",
                    "scenario",
                    "provider",
                    "state_pass",
                    "state_fail",
                    "state_unknown",
                )
            )
            + " |"
        )
    lines += [
        "",
        "## Matched raw state outcomes",
        "",
        "All pairs remain in data.json, including caller deviations and unresolved audio.",
        "",
        "| Language | Cohort | Both pass | Both fail | Gemini only pass "
        "| GPT only pass | Incomplete |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    patterns = (
        "both_pass",
        "both_fail",
        "gemini_only_pass",
        "gptlive_only_pass",
        "incomplete_evidence",
    )
    for language in ("en", "ro"):
        for cohort in ("all", "both caller transcript reviews pass"):
            pairs = [
                p
                for p in report["paired_outcomes"]
                if p["language"] == language
                and (cohort == "all" or p["both_caller_transcript_reviews_pass"])
            ]
            counts = [sum(p["raw_state_pattern"] == pattern for p in pairs) for pattern in patterns]
            lines.append("| " + " | ".join([language, cohort, *map(str, counts)]) + " |")
    lines += measurement_tables(groups)
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
                        "attempted_at_utc",
                        "collected_at_utc",
                        "audio_sha256",
                    )
                },
                "state_pass": row["grade"].get("state_pass"),
                "state_pass_with_erratum": row["grader_errata"]["grade"].get("state_pass"),
                "grader_errata": ";".join(row["grader_errata"]["applied"]),
                "policy_pass": row["grade"].get("policy_pass"),
                "caller_transcript_review": row["assessment"].get("caller_fidelity"),
                "spoken_truth_transcript_review": row["assessment"].get("spoken_truth"),
                "spoken_consent_transcript_review": row["assessment"].get("spoken_consent"),
                "human_audio_verified": False,
                "recording_duration_s": row["audio_diagnostics"]
                .get("audio_levels", {})
                .get("duration_s"),
                "median_audio_proxy_gap_ms": row["audio_diagnostics"]
                .get("acoustic_diagnostics", {})
                .get("median_audio_proxy_gap_ms"),
                "target_active_frame_median_dbfs": next(
                    (
                        c.get("active_frame_median_dbfs")
                        for c in row["audio_diagnostics"]
                        .get("audio_levels", {})
                        .get("channels", [])
                        if c["channel"] == 1
                    ),
                    None,
                ),
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
