"""Freeze and execute an auditable paired study; no automatic replacements.

The operator supplies explicit account routing and an approved budget. A frozen
manifest records code/config hashes and successful development-call evidence.
An interrupted or invalid trial stops the batch and remains an attempt.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from voicelab.simulations.study60 import fingerprint, make_plan


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def exclusive_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def code_fingerprint():
    from provider_audit import runtime_fingerprint

    lane = Path(__file__).resolve().parent
    result = runtime_fingerprint()
    result.update(
        {
            name: hashlib.sha256((lane / name).read_bytes()).hexdigest()
            for name in ("phone.py", "costs.py", "study.py")
        }
    )
    return result


def check_evidence(run_dir, profiles=None):
    from benchmark_support import BenchmarkContext
    from provider_audit import runtime_fingerprint

    run = read(run_dir / "run.json")
    if run["status"] != "completed" or run.get("cleanup_errors"):
        raise ValueError(f"{run_dir.name}: call incomplete or routing cleanup failed")
    if len(list(run_dir.glob("*.wav"))) != 1:
        raise ValueError(f"{run_dir.name}: one dual-channel recording required")
    import wave

    with wave.open(str(next(run_dir.glob("*.wav"))), "rb") as wav:
        if wav.getnchannels() != 2 or wav.getnframes() == 0:
            raise ValueError("Missing dual-channel audio")
    roles = []
    for role in ("agent", "caller"):
        card = read(run_dir / f"{role}-evidence.json")
        extra = card["lane_extra"]
        if extra.get("runtime_source_sha256") != runtime_fingerprint():
            raise ValueError("Worker code differs from the current tested source")
        configs = [
            event
            for session in extra.get("provider_audit", {}).get("sessions", [])
            for event in session["events"]
            if event["kind"] == "requested_config"
        ]
        if not configs or not extra.get("output_audio_formats") or not card.get("audio_out_bytes"):
            raise ValueError(f"{run_dir.name}/{role}: missing native config or audio evidence")
        if extra.get("role") != role or extra.get("run_id") != run["setup"]["run_id"]:
            raise ValueError("Evidence identity mismatch")
        expected = run["setup"]["provider" if role == "agent" else "caller_provider"]
        if extra["provider"] != expected:
            raise ValueError("Observed provider differs from assignment")
        setup = run["setup"]
        context = BenchmarkContext(
            setup["scenario"], setup["seed"], setup["language"], setup["tool_delay_ms"]
        )
        prompts = context.prompts()
        instruction = (
            context.call.caller_prompt
            if role == "caller"
            else prompts[1 if expected == "gptlive" else 0]
        )
        if hashlib.sha256(instruction.encode()).hexdigest() != extra["instruction_sha256"]:
            raise ValueError("Observed prompt differs from the assigned fixture")
        if expected == "gptlive":
            backend = context.call.caller_prompt if role == "caller" else prompts[2]
            if hashlib.sha256(backend.encode()).hexdigest() != extra["backend_instruction_sha256"]:
                raise ValueError("Observed backend prompt differs from fixture")
        profile = {
            k: extra.get(k)
            for k in (
                "model",
                "voice",
                "backend_model",
                "turn_detection",
                "auto_gain_control",
                "room_input_rate",
            )
        }
        if profiles is not None:
            previous = profiles.setdefault(expected, profile)
            if profile != previous:
                raise ValueError("Observed runtime settings changed within the study")
        names = {t["name"] for t in extra.get("tool_declarations", [])}
        wanted = {
            "get_price",
            "check_stock",
            "lookup_order",
            "record_order",
            "update_order",
            "cancel_order",
            "take_message",
        }
        if names != (wanted if role == "agent" else {"finish_call"}):
            raise ValueError("Incorrect tool exposure")
        native_names = set()
        for event in configs:
            native = event["data"]
            if expected == "gptlive":
                declarations = (
                    native.get("session", {})
                    .get("delegation", {})
                    .get("responses", {})
                    .get("tools", [])
                )
            else:
                declarations = [
                    tool
                    for group in native.get("tools", [])
                    for tool in group.get("function_declarations", [])
                ]
            native_names.update(t["name"] for t in declarations)
        if native_names != names:
            raise ValueError("Native provider configuration does not expose the expected tools")
        roles.append((role, extra["provider"]))
    return roles


def freeze(args):
    config = read(args.config)
    for key in (
        "target",
        "caller_id",
        "sip_host",
        "trunk",
        "rule",
        "agent",
        "worker_host",
        "worker_dir",
        "env",
        "carrier_env",
        "cap_eur",
        "reserve_eur",
    ):
        if key not in config:
            raise ValueError("Missing configuration field: " + key)
    cap, reserve = config["cap_eur"], config["reserve_eur"]
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in (cap, reserve)):
        raise ValueError("Budget must be finite and positive")
    if 60 * reserve > cap:
        raise ValueError("Reservations exceed the supplied approved batch cap")
    coverage = set()
    proof = {}
    profiles = {}
    for path in args.preflight:
        coverage.update(check_evidence(path, profiles))
        proof[path.name] = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in path.iterdir()
            if p.suffix in {".json", ".wav"}
        }
    if coverage != {(r, p) for r in ("agent", "caller") for p in ("gemini", "gptlive")}:
        raise ValueError("Development calls must exercise both providers as target and caller")
    plan = make_plan()
    plan.update(
        status="frozen_before_evaluation",
        frozen_at=datetime.now(UTC).isoformat(),
        approved_batch_cap_eur=cap,
        reservation_per_call_eur=reserve,
        runtime_config_sha256=fingerprint(config),
        source_sha256=code_fingerprint(),
        observed_profiles=profiles,
        preflight_evidence_sha256=proof,
    )
    exclusive_json(args.output, plan)
    exclusive_json(args.output.with_suffix(".sha256.json"), {"sha256": fingerprint(plan)})
    print(f"Frozen 60-call manifest: {args.output}")


async def execute(args):
    from collect import main as collect
    from phone import run, session_lock
    from reconcile import main as reconcile
    from review import build

    plan, config = read(args.manifest), read(args.config)
    if plan["status"] != "frozen_before_evaluation" or plan.get("total_calls") != 60:
        raise ValueError("Freeze the 60-call plan first")
    if fingerprint(plan) != read(args.manifest.with_suffix(".sha256.json"))["sha256"]:
        raise ValueError("Manifest changed after freeze")
    if (
        fingerprint(config) != plan["runtime_config_sha256"]
        or code_fingerprint() != plan["source_sha256"]
    ):
        raise ValueError("Code or configuration changed after freeze; do not mix versions")
    args.runs.mkdir(parents=True, exist_ok=True)
    # One route transaction at a time. A stale lock is evidence of an interruption;
    # inspect carrier/route state before manually clearing it.
    with session_lock(args.runs / "study-execution.json"):
        for trial in plan["trials"]:
            output = args.runs / trial["output_name"]
            stamp = args.runs / "attempts" / f"{trial['trial_id']}.json"
            if stamp.exists():
                if read(stamp).get("status") != "evidence_collected":
                    raise ValueError(
                        f"Inspect interrupted attempt {trial['trial_id']}; it will not be redialed"
                    )
                check_evidence(output, plan["observed_profiles"])
                continue
            fields = {
                k: config[k]
                for k in (
                    "target",
                    "caller_id",
                    "sip_host",
                    "trunk",
                    "rule",
                    "agent",
                    "cap_eur",
                    "reserve_eur",
                )
            }
            fields.update(
                {
                    k: trial[k]
                    for k in (
                        "provider",
                        "caller_provider",
                        "scenario",
                        "language",
                        "seed",
                        "seconds",
                        "tool_delay_ms",
                    )
                }
            )
            fields.update(
                env=Path(config["env"]),
                carrier_env=Path(config["carrier_env"]),
                output=output,
                ledger=args.runs / "budget.json",
            )
            exclusive_json(
                stamp,
                {
                    "trial": trial,
                    "status": "attempt_started",
                    "started_at": datetime.now(UTC).isoformat(),
                },
            )
            await run(SimpleNamespace(**fields))
            # SCP performs no remote shell command interpolation. Restrict the
            # deployment path before constructing the remote-source argument.
            import re

            if not re.fullmatch(r"[A-Za-z0-9_.-]+", config["worker_host"]) or not re.fullmatch(
                r"/[A-Za-z0-9_./-]+", config["worker_dir"]
            ):
                raise ValueError("Unsupported worker host/path")
            cards = args.runs / "worker-scorecards"
            cards.mkdir(exist_ok=True)
            for settle_attempt in range(8):
                subprocess.run(
                    [
                        "scp",
                        "-q",
                        f"{config['worker_host']}:{config['worker_dir']}/scorecards/*.json",
                        str(cards),
                    ],
                    check=True,
                )
                collect(args.runs)
                try:
                    check_evidence(output, plan["observed_profiles"])
                    break
                except FileNotFoundError:
                    if settle_attempt == 7:
                        raise
                    # Provider shutdown can finish after the carrier hangup.
                    # Wait for the same call's artifacts; never redial it.
                    await asyncio.sleep(5)
            reconcile(args.runs, Path(config["carrier_env"]), only_run=output)
            collect(args.runs)
            from review import write

            attempt = read(stamp)
            attempt.update(status="evidence_collected", completed_at=datetime.now(UTC).isoformat())
            write(stamp, attempt)
            build(args.manifest, args.runs, args.runs / "review")
            print(
                json.dumps({"trial": trial["trial_id"], "status": "evidence_collected"}), flush=True
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("freeze")
    f.add_argument("--config", type=Path, required=True)
    f.add_argument("--preflight", type=Path, nargs="+", required=True)
    f.add_argument("--output", type=Path, required=True)
    e = sub.add_parser("execute")
    e.add_argument("--config", type=Path, required=True)
    e.add_argument("--manifest", type=Path, required=True)
    e.add_argument("--runs", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args)
    else:
        asyncio.run(execute(args))
