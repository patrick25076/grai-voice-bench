"""Versioned, solvable v1 cases. Seeds reproduce inputs, never model audio."""

import re
from dataclasses import replace

from .generate import GeneratedCall, build_rubric, generate, render_caller_prompt
from .world import CallerBehavior, Constraint, Disclosure, Identity, Need

CASES = (
    "after-work",
    "spell-my-name",
    "not-tuesday",
    "loading-dock",
    "exact-quantity",
    "check-before-order",
)


def scenario(name: str, seed: int = 41, language: str = "en") -> GeneratedCall:
    if name not in CASES:
        raise ValueError(f"Unknown scenario {name!r}; choose {CASES}")
    domain = "clinic" if name in CASES[:3] else "order"
    if domain == "clinic" and language != "en":
        raise ValueError("v1 clinic pack currently supports English only")
    base = generate(seed, domain, language)
    ro = language == "ro"
    constraints = {
        "after-work": (
            "after_time",
            {"not_before": "17:00"},
            "you cannot leave work before five",
            Disclosure.ON_ASK,
        ),
        "spell-my-name": (
            "before_time",
            {"not_after": "11:00"},
            "you need a morning appointment before eleven",
            Disclosure.ON_ASK,
        ),
        "not-tuesday": (
            "no_weekday",
            {"weekday": "tuesday"},
            "Tuesdays are impossible because you are in the office",
            Disclosure.ON_CONFLICT,
        ),
        "loading-dock": (
            "dock_closes",
            {"delivery_not_after": "15:00"},
            "rampa se închide la trei" if ro else "your loading dock closes at three",
            Disclosure.ON_CONFLICT,
        ),
        "exact-quantity": (
            "min_quantity",
            {"min_qty": 200},
            "aveți nevoie de exact 200 kg" if ro else "you need exactly 200 kg",
            Disclosure.ON_ASK,
        ),
        "check-before-order": (
            "dock_closes",
            {"delivery_not_after": "15:00"},
            "rampa se închide la trei" if ro else "your loading dock closes at three",
            Disclosure.ON_ASK,
        ),
    }
    product = "gheață carbonică" if ro else "dry ice"
    need = (
        Need("checkup", {"service": "check-up"}, "you need a routine dental check-up")
        if domain == "clinic"
        else Need(
            "new_order",
            {
                "product": product,
                "quantity_kg": 200,
                "delivery_date": "2026-09-15",
            },
            "aveți nevoie de 200 kg de gheață carbonică marți, 15 septembrie"
            if ro
            else "you need 200 kg of dry ice on Tuesday, September 15",
        )
    )
    world = replace(
        base.world,
        identity=Identity("Alex", "Smythe", "S-M-Y-T-H-E", "07700 900123"),
        need=need,
        hard_constraint=Constraint(*constraints[name]),
        soft_preferences=(),
        distractors=(),
        opening="întrebați dacă pot ajuta cu o comandă" if ro else "ask whether they can help",
    )
    # Behavioral prompts do not simulate physical background noise. Acoustic
    # noise and timed barge-in need a separate, measured audio intervention.
    behavior = CallerBehavior(
        interruption=0,
        self_corrects=False,
        changes_mind=False,
        answer_drift=0,
        filler=0.2,
        pace="normal",
        noise="quiet",
        abrupt_ending=False,
    )
    prompt = render_caller_prompt(world, behavior)
    prompt += "\nReference date: Monday, 14 September 2026. All personal details are fictional."
    prompt += "\nKeep these facts stable; do not invent a different need or change the quantity."
    if domain == "order":
        address = "Strada Exemplului 10" if ro else "10 Example Street"
        world = replace(
            world,
            need=replace(
                world.need,
                params={
                    **world.need.params,
                    "delivery_address": address,
                },
            ),
        )
        prompt += f"\nYour delivery address is {address}. Supply it when asked."
        prompt += "\nIf asked for a delivery time, 14:00 works for you."
        prompt += " Any proposed time must still satisfy your stated delivery constraint."
    if name == "check-before-order":
        prompt += "\nAsk whether the full quantity is in stock before you discuss placing an order."
    return GeneratedCall(world, behavior, build_rubric(world), prompt)


def grade_state(call: GeneratedCall, backend) -> dict:
    """Objective database evidence only. Audio truth and consent require review."""
    from datetime import datetime

    from .tools import Slot, _satisfies

    world = call.world
    records = backend.bookings if world.domain == "clinic" else backend.orders
    checks = {"exactly_one_write": len(records) == 1}
    raw_fields = {}
    if len(records) == 1:
        saved = records[0]
        checks["surname"] = (
            str(saved.get("family_name", "")).casefold() == world.identity.family_name.casefold()
        )
        checks["phone"] = "".join(filter(str.isdigit, str(saved.get("phone", "")))) == "".join(
            filter(str.isdigit, world.identity.phone)
        )
        for key, value in world.need.params.items():
            raw_fields[key] = saved.get(key) == value
            if key == "delivery_address":
                checks[key] = normalize_address(str(saved.get(key, ""))) == normalize_address(value)
            else:
                checks[key] = raw_fields[key]
        if world.domain == "clinic":
            slot = Slot(
                datetime.fromisoformat(saved["date"] + "T" + saved["time"]),
                saved["clinician"],
                saved["minutes"],
            )
            checks["hard_constraint"] = _satisfies(slot, world)
        elif world.hard_constraint.kind == "min_quantity":
            checks["hard_constraint"] = (
                saved["quantity_kg"] >= world.hard_constraint.params["min_qty"]
            )
        else:
            try:
                actual = datetime.strptime(saved["delivery_time"], "%H:%M").time()
                limit = datetime.strptime(
                    world.hard_constraint.params["delivery_not_after"], "%H:%M"
                ).time()
                checks["hard_constraint"] = actual <= limit
            except (ValueError, TypeError, KeyError):
                checks["hard_constraint"] = False
    return {
        "state_pass": all(checks.values()),
        "checks": checks,
        "raw_field_checks": raw_fields,
        "caller_fidelity": "needs_audio_review",
        "spoken_truth": "needs_audio_review",
        "confirmation": "needs_audio_review",
        "overall_pass": None,
    }


def normalize_address(value: str) -> str:
    """Only known textual abbreviations; not geographic or semantic matching."""
    words = re.findall(r"\w+", value.casefold())
    mapping = {"str": "strada", "nr": "", "number": ""}
    return " ".join(mapping.get(word, word) for word in words if mapping.get(word, word))
