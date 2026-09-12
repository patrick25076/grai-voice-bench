"""The mock backends both arms call, built on the real `voicelab.tools` registry.

For the comparison to be about the models, every arm must get **identical** tools
over **identical** state. So there is one :class:`~voicelab.tools.ToolRegistry`
per domain, rendered to Gemini by the registry's own ``to_gemini()`` and to the
Responses API by :func:`to_openai` here, rather than two hand-written schemas
that could drift apart.

An earlier version of this module defined its own ``ToolDef`` and its own
dispatch loop. That was a duplicate of `voicelab.tools`, which already has the
timeout budget, the never-raise contract and the Gemini renderer, and which is
what the production bridge uses. Sharing it means the benchmark exercises the
same tool path the real agent does, which is worth more than the convenience.

Three properties this module still owns:

1. **Deterministic.** State is built from the call's seed, and "today" is a fixed
   date (`BENCH_TODAY`), never `date.today()`. A benchmark whose results depend
   on the day you ran it is not a benchmark. (The clinic seeder in `apps/clinic`
   learned this the hard way: a per-day RNG made a test fail or pass depending on
   the calendar, and it blocked every merge for a while.)
2. **Winnable.** Generated availability always contains at least two options that
   satisfy the caller's hidden hard constraint. If none existed, every run would
   fail and the score would measure the scenario rather than the agent. See
   :func:`_guarantee_a_valid_option`.
3. **Recorded.** Every call lands in a :class:`ToolLog`. Nothing here talks to a
   real CRM, a real calendar, or the Ice Trust database.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from voicelab.tools import ToolDef, ToolRegistry, ToolResult

from .world import CallerWorld

#: Fixed reference date for every benchmark run. Chosen as a Monday so weekday
#: arithmetic in the scenarios is easy to reason about. Never use date.today().
BENCH_TODAY = date(2026, 9, 14)

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def to_openai(registry: ToolRegistry) -> list[dict[str, Any]]:
    """Render a registry as Responses-API function tools.

    The registry ships `to_gemini()` because that is what the bridge needs. Arm B
    delegates to a Responses backend, which wants the same declarations in a
    different envelope. One source, two renderers, no hand-maintained copy.
    """
    out: list[dict[str, Any]] = []
    for tool in registry:
        entry: dict[str, Any] = {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
        }
        if tool.parameters:
            entry["parameters"] = dict(tool.parameters)
        out.append(entry)
    return out


@dataclass
class ToolLog:
    """Everything the agent did, in order. The grader's primary evidence."""

    entries: list[dict] = field(default_factory=list)

    def record(self, name: str, args: dict, result: dict, elapsed_ms: float = 0.0) -> None:
        self.entries.append(
            {
                "name": name,
                "args": dict(args),
                "result": result,
                "elapsed_ms": round(elapsed_ms, 1),
            }
        )

    def record_result(self, res: ToolResult, args: dict) -> None:
        self.record(res.name, args, res.result, res.elapsed_ms)

    def calls(self, name: str) -> list[dict]:
        return [e for e in self.entries if e["name"] == name]

    def succeeded(self, name: str) -> list[dict]:
        return [e for e in self.calls(name) if e["result"].get("ok") is True]

    def as_json(self) -> str:
        return json.dumps(self.entries, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------
# Slot generation
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Slot:
    when: datetime
    clinician: str
    minutes: int

    @property
    def weekday(self) -> str:
        return WEEKDAYS[self.when.weekday()]

    def as_dict(self) -> dict:
        return {
            "date": self.when.date().isoformat(),
            "time": self.when.strftime("%H:%M"),
            "weekday": self.weekday,
            "clinician": self.clinician,
            "minutes": self.minutes,
        }


CLINICIANS = ("Dr Mira Ellis", "Dr Sam Rowan", "Dr Alex Vale")

#: The clinician the caller "saw last time", for the named_clinician constraint.
#: Fixed rather than sampled so the constraint is checkable without extra state.
PREVIOUS_CLINICIAN = CLINICIANS[0]


def _business_days(start: date, count: int) -> list[date]:
    out: list[date] = []
    day = start
    while len(out) < count:
        day += timedelta(days=1)
        if day.weekday() < 5:  # the practice is closed at weekends
            out.append(day)
    return out


def _generate_slots(rng: random.Random) -> list[Slot]:
    """A fortnight of partly-booked appointment slots."""
    slots: list[Slot] = []
    for day in _business_days(BENCH_TODAY, 10):
        for hour in (8, 9, 10, 11, 14, 15, 16, 17, 18):
            if rng.random() < 0.45:  # already taken
                continue
            slots.append(
                Slot(
                    when=datetime.combine(day, time(hour, rng.choice((0, 30)))),
                    clinician=rng.choice(CLINICIANS),
                    minutes=rng.choice((30, 30, 60)),
                )
            )
    return slots


def _satisfies(slot: Slot, world: CallerWorld) -> bool:
    """Would booking this slot honour the caller's hidden hard constraint?"""
    c = world.hard_constraint
    p = c.params
    if c.kind == "no_weekday":
        return slot.weekday != p["weekday"]
    if c.kind == "after_time":
        return slot.when.strftime("%H:%M") >= p["not_before"]
    if c.kind == "before_time":
        return slot.when.strftime("%H:%M") <= p["not_after"]
    if c.kind == "away_range":
        # The pack states the range in spoken form ("the 18th"); parse the day.
        lo = int("".join(ch for ch in p["unavailable_from"] if ch.isdigit()))
        hi = int("".join(ch for ch in p["unavailable_to"] if ch.isdigit()))
        return not (lo <= slot.when.day <= hi)
    if c.kind == "named_clinician":
        return slot.clinician == PREVIOUS_CLINICIAN
    if c.kind == "needs_double":
        return slot.minutes >= p["min_minutes"]
    return True


def _guarantee_a_valid_option(
    slots: list[Slot], world: CallerWorld, rng: random.Random
) -> list[Slot]:
    """Make sure at least two bookable slots honour the hard constraint.

    Without this a run can be unwinnable, and an unwinnable run scores the
    scenario rather than the agent. Two rather than one so an agent that offers
    a valid slot the caller happens to decline still has somewhere to go.
    """
    valid = [s for s in slots if _satisfies(s, world)]
    if len(valid) >= 2:
        return slots
    out = list(slots)
    for day in _business_days(BENCH_TODAY, 10):
        for hour in (8, 9, 10, 17, 18):
            candidate = Slot(
                when=datetime.combine(day, time(hour, 0)),
                clinician=PREVIOUS_CLINICIAN,
                minutes=60,
            )
            if _satisfies(candidate, world) and candidate not in out:
                out.append(candidate)
                valid.append(candidate)
                if len(valid) >= 2:
                    rng.shuffle(out)
                    return out
    return out


# --------------------------------------------------------------------------
# Clinic backend
# --------------------------------------------------------------------------


class MockClinic:
    """A dental front desk's calendar. Deterministic, in memory, disposable."""

    domain = "clinic"

    def __init__(self, world: CallerWorld) -> None:
        rng = random.Random(world.seed ^ 0xC11C)
        self.log = ToolLog()
        self.slots = _guarantee_a_valid_option(_generate_slots(rng), world, rng)
        self.bookings: list[dict] = []

    # -- handlers ---------------------------------------------------------

    async def check_availability(self, args: dict) -> dict:
        day = str(args.get("date", ""))
        part = args.get("part_of_day")
        matches = [s for s in self.slots if s.when.date().isoformat() == day]
        if part == "morning":
            matches = [s for s in matches if s.when.hour < 12]
        elif part == "afternoon":
            matches = [s for s in matches if s.when.hour >= 12]
        result = {"ok": True, "slots": [s.as_dict() for s in matches[:6]]}
        self.log.record("check_availability", args, result)
        return result

    async def find_availability(self, args: dict) -> dict:
        try:
            lo = date.fromisoformat(str(args["from_date"]))
            hi = date.fromisoformat(str(args["to_date"]))
        except (KeyError, ValueError) as exc:
            result = {"ok": False, "error": f"bad date range: {exc}"}
            self.log.record("find_availability", args, result)
            return result
        matches = [s for s in self.slots if lo <= s.when.date() <= hi]
        part = args.get("part_of_day")
        if part == "morning":
            matches = [s for s in matches if s.when.hour < 12]
        elif part == "afternoon":
            matches = [s for s in matches if s.when.hour >= 12]
        if clinician := args.get("clinician"):
            matches = [s for s in matches if str(clinician).lower() in s.clinician.lower()]
        if minutes := args.get("minutes"):
            matches = [s for s in matches if s.minutes >= int(minutes)]
        result = {"ok": True, "slots": [s.as_dict() for s in matches[:8]]}
        self.log.record("find_availability", args, result)
        return result

    async def book_appointment(self, args: dict) -> dict:
        day, at = str(args.get("date", "")), str(args.get("time", ""))
        match = next(
            (
                s
                for s in self.slots
                if s.when.date().isoformat() == day and s.when.strftime("%H:%M") == at
                and (not args.get("clinician") or args["clinician"] == s.clinician)
                and int(args.get("minutes") or s.minutes) <= s.minutes
            ),
            None,
        )
        if match is None:
            # Booking a slot that was never offered is a hallucination, and the
            # backend says no rather than quietly inventing it.
            result: dict = {
                "ok": False,
                "error": "that slot is not in the diary",
                "code": "slot_not_available",
            }
        else:
            if not args.get("family_name") or not args.get("phone"):
                result = {"ok": False, "error": "surname and phone are required"}
                self.log.record("book_appointment", args, result)
                return result
            booking = {
                "family_name": args.get("family_name"),
                "phone": args.get("phone"),
                "date": day,
                "time": at,
                "service": args.get("service"),
                "clinician": match.clinician,
                "minutes": match.minutes,
                "weekday": match.weekday,
            }
            self.bookings.append(booking)
            self.slots = [s for s in self.slots if s is not match]
            result = {"ok": True, "reference": f"BK{len(self.bookings):04d}", **booking}
        self.log.record("book_appointment", args, result)
        return result

    async def practice_info(self, args: dict) -> dict:
        answers = {
            "parking": "Free parking at the rear of the building, entrance on the side street.",
            "price": "We do not quote prices by phone; you get a written estimate at the visit.",
            "hours": "Monday to Friday, 08:00 to 18:30. Closed at weekends.",
            "address": "10 Example Square, Demo City (fictional address).",
        }
        topic = str(args.get("topic", "")).lower()
        answer = answers.get(topic)
        result = (
            {"ok": True, "topic": topic, "answer": answer}
            if answer
            else {"ok": False, "error": f"no information held about {topic!r}"}
        )
        self.log.record("practice_info", args, result)
        return result

    def registry(self) -> ToolRegistry:
        return ToolRegistry(
            [
                ToolDef(
                    name="check_availability",
                    description="Appointment slots free on ONE specific date.",
                    handler=self.check_availability,
                    parameters={
                        "type": "object",
                        "properties": {
                            "date": {"type": "string", "description": "ISO date, e.g. 2026-09-17"},
                            "part_of_day": {"type": "string", "enum": ["morning", "afternoon"]},
                        },
                        "required": ["date"],
                    },
                ),
                ToolDef(
                    name="find_availability",
                    description=(
                        "Slots across a DATE RANGE, optionally filtered by clinician or by "
                        "minimum appointment length. Use this for a flexible caller instead "
                        "of calling check_availability once per day."
                    ),
                    handler=self.find_availability,
                    parameters={
                        "type": "object",
                        "properties": {
                            "from_date": {"type": "string"},
                            "to_date": {"type": "string"},
                            "part_of_day": {"type": "string", "enum": ["morning", "afternoon"]},
                            "clinician": {"type": "string"},
                            "minutes": {"type": "integer", "description": "minimum length needed"},
                        },
                        "required": ["from_date", "to_date"],
                    },
                ),
                ToolDef(
                    name="book_appointment",
                    description=(
                        "Book a slot that check_availability or find_availability returned. "
                        "Fails if the slot was not offered."
                    ),
                    handler=self.book_appointment,
                    parameters={
                        "type": "object",
                        "properties": {
                            "family_name": {"type": "string"},
                            "phone": {"type": "string"},
                            "date": {"type": "string"},
                            "time": {"type": "string", "description": "HH:MM, 24 hour"},
                            "service": {"type": "string"},
                            "clinician": {"type": "string"},
                            "minutes": {"type": "integer"},
                        },
                        "required": ["family_name", "phone", "date", "time", "service"],
                    },
                ),
                ToolDef(
                    name="practice_info",
                    description="Answer a factual question: parking, price, hours, address.",
                    handler=self.practice_info,
                    parameters={
                        "type": "object",
                        "properties": {
                            "topic": {
                                "type": "string",
                                "enum": ["parking", "price", "hours", "address"],
                            }
                        },
                        "required": ["topic"],
                    },
                ),
            ]
        )


# --------------------------------------------------------------------------
# Supplier backend (Nora-shaped)
# --------------------------------------------------------------------------

SECOND_SITE = "Unit 4, Drumul Industrial 22"
REGISTERED_ADDRESS = "Strada Fabricii 9"


class MockSupplier:
    """Phone order intake. Same shape as Nora's job, none of Nora's data."""

    domain = "order"

    def __init__(self, world: CallerWorld) -> None:
        rng = random.Random(world.seed ^ 0x0DDE)
        self.log = ToolLog()
        self.orders: list[dict] = []
        self.price_per_kg = round(rng.uniform(3.2, 4.8), 2)
        self.stock_kg = rng.choice((150, 400, 800, 1200))

    async def get_price(self, args: dict) -> dict:
        qty = int(args.get("quantity_kg") or 0)
        result = {
            "ok": True,
            "product": args.get("product"),
            "quantity_kg": qty,
            "price_per_kg": self.price_per_kg,
            "total": round(self.price_per_kg * qty, 2),
            "currency": "RON",
        }
        self.log.record("get_price", args, result)
        return result

    async def check_stock(self, args: dict) -> dict:
        qty = int(args.get("quantity_kg") or 0)
        result = {
            "ok": True,
            "available": qty <= self.stock_kg,
            "on_hand_kg": self.stock_kg,
            "delivery_date": args.get("delivery_date"),
        }
        self.log.record("check_stock", args, result)
        return result

    async def place_order(self, args: dict) -> dict:
        qty = int(args.get("quantity_kg") or 0)
        if qty <= 0:
            result: dict = {"ok": False, "error": "quantity must be positive"}
        elif qty > self.stock_kg:
            result = {
                "ok": False,
                "error": f"only {self.stock_kg} kg on hand",
                "code": "insufficient_stock",
            }
        else:
            try:
                weekday = WEEKDAYS[date.fromisoformat(str(args["delivery_date"])).weekday()]
            except (KeyError, ValueError) as exc:
                result = {"ok": False, "error": f"bad delivery_date: {exc}"}
                self.log.record("place_order", args, result)
                return result
            order = {
                "family_name": args.get("family_name"),
                "phone": args.get("phone"),
                "product": args.get("product"),
                "quantity_kg": qty,
                "delivery_date": args.get("delivery_date"),
                "delivery_time": args.get("delivery_time"),
                "delivery_address": args.get("delivery_address") or REGISTERED_ADDRESS,
                "po_number": args.get("po_number"),
                "weekday": weekday,
            }
            self.orders.append(order)
            self.stock_kg -= qty
            result = {"ok": True, "reference": f"ORD{len(self.orders):04d}", **order}
        self.log.record("place_order", args, result)
        return result

    def registry(self) -> ToolRegistry:
        return ToolRegistry(
            [
                ToolDef(
                    name="get_price",
                    description="Price for a quantity of a product. Does not reserve anything.",
                    handler=self.get_price,
                    parameters={
                        "type": "object",
                        "properties": {
                            "product": {"type": "string"},
                            "quantity_kg": {"type": "integer"},
                        },
                        "required": ["product", "quantity_kg"],
                    },
                ),
                ToolDef(
                    name="check_stock",
                    description="Whether a quantity can be supplied for a delivery date.",
                    handler=self.check_stock,
                    parameters={
                        "type": "object",
                        "properties": {
                            "product": {"type": "string"},
                            "quantity_kg": {"type": "integer"},
                            "delivery_date": {"type": "string"},
                        },
                        "required": ["product", "quantity_kg", "delivery_date"],
                    },
                ),
                ToolDef(
                    name="place_order",
                    description=(
                        "Record a confirmed order. Only call this once every value is known "
                        "and confirmed with the caller."
                    ),
                    handler=self.place_order,
                    parameters={
                        "type": "object",
                        "properties": {
                            "family_name": {"type": "string"},
                            "phone": {"type": "string"},
                            "product": {"type": "string"},
                            "quantity_kg": {"type": "integer"},
                            "delivery_date": {"type": "string"},
                            "delivery_time": {"type": "string", "description": "HH:MM, 24 hour"},
                            "delivery_address": {"type": "string"},
                            "po_number": {"type": "string"},
                        },
                        "required": [
                            "family_name",
                            "phone",
                            "product",
                            "quantity_kg",
                            "delivery_date",
                            "delivery_time",
                        ],
                    },
                ),
            ]
        )


Backend = MockClinic | MockSupplier


def build_backend(world: CallerWorld) -> Backend:
    return MockClinic(world) if world.domain == "clinic" else MockSupplier(world)
