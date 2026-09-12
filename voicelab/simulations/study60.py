"""The fixed 50-English / 10-Romanian study requested on 2026-09-12."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict
from datetime import UTC, datetime

from . import VERSION
from .cases import CASES, SimulationCase


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def make_plan(seed=20260913):
    names = tuple(CASES)
    pairs = []
    for repetition in range(3):
        for index, name in enumerate(names):
            pairs.append(
                ("en", name, repetition, "gemini" if (index + repetition) % 2 == 0 else "gptlive")
            )
    pairs.append(("en", "sim-amend-quantity", 3, "gemini"))
    ro_cases = (
        "sim-create-order",
        "sim-amend-quantity",
        "sim-change-address",
        "sim-cancel-order",
        "sim-retry-after-timeout",
    )
    for index, name in enumerate(ro_cases):
        pairs.append(("ro", name, 0, "gptlive" if index % 2 == 0 else "gemini"))
    rng = random.Random(seed)
    rng.shuffle(pairs)
    # Balanced first-target order overall, near-balanced within each language.
    first_bags = {"en": ["gemini"] * 13 + ["gptlive"] * 12, "ro": ["gemini"] * 2 + ["gptlive"] * 3}
    for bag in first_bags.values():
        rng.shuffle(bag)
    trials = []
    for number, (language, name, repetition, caller) in enumerate(pairs, 1):
        fixture_seed = seed + repetition
        case = SimulationCase(name, fixture_seed, language)
        pair_id = f"P{number:02d}"
        first = first_bags[language].pop()
        for order, target in enumerate((first, "gptlive" if first == "gemini" else "gemini"), 1):
            trials.append(
                {
                    "trial_id": f"{pair_id}-{order}",
                    "pair_id": pair_id,
                    "arm_order": order,
                    "provider": target,
                    "caller_provider": caller,
                    "language": language,
                    "scenario": name,
                    "seed": fixture_seed,
                    "seconds": 180,
                    "tool_delay_ms": 0,
                    "output_name": f"{pair_id}-{order}",
                    "fixture_sha256": fingerprint(case.sandbox.initial_state),
                    "caller_prompt_sha256": fingerprint(case.call.caller_prompt),
                    "job_spec_sha256": fingerprint(asdict(case.job)),
                    "tool_schema_sha256": fingerprint(
                        [t.declaration() for t in case.sandbox.registry()]
                    ),
                }
            )
    return {
        "study_id": "grai-phone-60-v1",
        "suite_version": VERSION,
        "status": "prepared_not_frozen",
        "generated_at": datetime.now(UTC).isoformat(),
        "plan_seed": seed,
        "total_calls": 60,
        "language_counts": {"en": 50, "ro": 10},
        "target_counts": {"gemini": 30, "gptlive": 30},
        "max_call_seconds": 180,
        "caller_counts": {"gemini": 30, "gptlive": 30},
        "models": {
            "gemini": "gemini-3.1-flash-live-preview",
            "gptlive": "gpt-live-1",
            "gptlive_backend": "gpt-5.6-terra",
        },
        "personal_reviewer": (
            "Patrick, GRAI Labs builder; subjective preference, not an independent panel"
        ),
        "estimated_batch_cost": None,
        "approved_batch_cap_eur": None,
        "trials": trials,
    }


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(make_plan(), stream, ensure_ascii=False, indent=2)
    print("Prepared exactly 60 calls: 50 English and 10 Romanian; 30 per target.")
