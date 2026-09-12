"""The caller's hidden world — what a test caller knows, wants, and will not say.

The old tester (`clinic.eval.scenarios`) put the caller's persona and the
grader's expectations in one object and handed the caller the happy path:

    "You want any weekday morning next week. ... Accept the first suitable slot.
     Once it's confirmed, thank them and end the call."

A caller told to accept cannot fail the agent, a goal stated that precisely has
nothing to elicit, and a fixed string makes every run the same call. This module
replaces that with three objects and a visibility rule for each.

======================  ==========================================  ============
Object                  Contains                                    Who sees it
======================  ==========================================  ============
``CallerWorld``         identity, need, ONE hard constraint,        caller model,
                        soft preferences, distractors, disclosure   grader
``CallerBehavior``      how awkward they are, sampled per seed      caller model
``Rubric``              what a correct outcome must satisfy         grader only
======================  ==========================================  ============

**The agent under test sees none of it.** It has to find out by asking.

The rule that makes this a test rather than a walkthrough: an outcome that
violates ``CallerWorld.hard_constraint`` is a FAIL *even if the caller accepted
it on the call*. Real callers agree to things that do not work for them and then
do not show up. Grading on caller satisfaction scores the agent's charm; grading
on the constraint scores whether it did the job.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class Disclosure(enum.Enum):
    """When a fact leaves the caller's mouth.

    ``ON_CONFLICT`` is the one that produces realistic calls. Real people do not
    recite their constraints up front; they remember them the moment you offer
    something that breaks one. An agent that never proposes anything never
    learns the constraint exists, which is exactly the behaviour worth measuring.
    """

    VOLUNTEERED = "volunteered"  # said in the opening, unprompted
    ON_ASK = "on_ask"  # said if the agent asks a question that covers it
    ON_CONFLICT = "on_conflict"  # surfaces only when the agent proposes a violation
    IF_PRESSED = "if_pressed"  # only after the agent asks twice, or asks directly


@dataclass(frozen=True)
class Identity:
    given_name: str
    family_name: str
    #: Surnames that are a pain to hear on an 8 kHz line are the point, not an
    #: accident. Entity capture is the top measured S2S failure mode.
    spelling_hint: str | None
    phone: str
    company: str | None = None

    @property
    def full_name(self) -> str:
        return f"{self.given_name} {self.family_name}"


@dataclass(frozen=True)
class Constraint:
    """Something a correct outcome must not violate.

    ``kind`` and ``params`` are structured so the grader can check them
    mechanically. ``spoken`` is how this caller would put it out loud, and is the
    only form the caller model is allowed to see phrased as speech.
    """

    kind: str
    params: dict[str, Any]
    spoken: str
    disclosure: Disclosure

    def __post_init__(self) -> None:
        banned = ("accept", "agree to", "confirm and end", "say yes")
        low = self.spoken.lower()
        if any(b in low for b in banned):
            raise ValueError(
                "constraint.spoken tells the caller how to behave, not what is true: "
                f"{self.spoken!r}"
            )


@dataclass(frozen=True)
class Need:
    """What the caller actually wants, in the domain's own terms.

    ``summary`` is deliberately vague, the way a real opening line is. The
    precise version lives in ``params`` for the grader, and the caller only
    reveals that much under questioning.
    """

    kind: str
    params: dict[str, Any]
    summary: str


#: Behaviour directives per language. Kept beside the dataclass rather than in
#: `packs` because these describe the caller's manner, which is domain-free.
BEHAVIOUR_PHRASES: dict[str, dict[str, str]] = {
    "en": {
        "fast": "You talk quickly and run sentences together.",
        "slow": "You speak slowly, with pauses while you think.",
        "filler_high": "You use filler words, restart sentences, and trail off mid-thought.",
        "filler_low": "You occasionally hesitate or restart a sentence.",
        "interrupt_high": "You interrupt when you think you already know what they will say.",
        "interrupt_low": "You sometimes start talking before they have quite finished.",
        "drift": (
            "You sometimes answer a slightly different question than the one you were asked, "
            "or add something unrelated before answering."
        ),
        "self_correct": (
            "Early in the call you get one of your own details slightly wrong. "
            "You correct it later, unprompted, when you notice."
        ),
        "changes_mind": (
            "Partway through, you reconsider what you want and say so. "
            "You do not explain why unless asked."
        ),
        "abrupt": "When you are done you end the call quickly, without a long goodbye.",
    },
    "ro": {
        "fast": "Vorbiți repede și legați propozițiile între ele.",
        "slow": "Vorbiți rar, cu pauze în care vă gândiți.",
        "filler_high": "Folosiți cuvinte de umplutură, reluați propoziții și vă pierdeți ideea.",
        "filler_low": "Din când în când ezitați sau reluați o propoziție.",
        "interrupt_high": "Întrerupeți când credeți că știți deja ce urmează să spună.",
        "interrupt_low": "Uneori începeți să vorbiți înainte să termine ei.",
        "drift": (
            "Uneori răspundeți la o întrebare puțin diferită de cea pusă, "
            "sau adăugați ceva fără legătură înainte de a răspunde."
        ),
        "self_correct": (
            "La începutul apelului greșiți ușor unul dintre detaliile dumneavoastră. "
            "Îl corectați mai târziu, din proprie inițiativă, când observați."
        ),
        "changes_mind": (
            "Pe parcurs vă răzgândiți în privința a ceea ce vreți și spuneți asta. "
            "Nu explicați de ce decât dacă sunteți întrebat."
        ),
        "abrupt": "Când ați terminat închideți repede, fără un rămas-bun lung.",
    },
}


@dataclass(frozen=True)
class CallerBehavior:
    """How difficult this caller is to serve. Sampled from the seed."""

    #: 0.0 never interrupts, 1.0 talks over the agent constantly
    interruption: float
    #: gives a detail wrong first, corrects it later in the call
    self_corrects: bool
    #: changes their mind about the need partway through
    changes_mind: bool
    #: answers a slightly different question than the one asked
    answer_drift: float
    #: "erm", "like", restarts, trailing off
    filler: float
    #: slow, normal, fast
    pace: str
    #: background environment, feeds the impairment stack later
    noise: str
    #: says goodbye abruptly instead of winding down
    abrupt_ending: bool

    def directives(self, language: str = "en") -> list[str]:
        """Behaviour as instructions to the caller model, in the call's language.

        Never includes anything about the agent's task. These shape HOW the
        caller speaks, never WHAT outcome they should reach.
        """
        phrases = BEHAVIOUR_PHRASES.get(language, BEHAVIOUR_PHRASES["en"])
        out: list[str] = []
        if self.pace == "fast":
            out.append(phrases["fast"])
        elif self.pace == "slow":
            out.append(phrases["slow"])
        if self.filler > 0.6:
            out.append(phrases["filler_high"])
        elif self.filler > 0.3:
            out.append(phrases["filler_low"])
        if self.interruption > 0.6:
            out.append(phrases["interrupt_high"])
        elif self.interruption > 0.3:
            out.append(phrases["interrupt_low"])
        if self.answer_drift > 0.5:
            out.append(phrases["drift"])
        if self.self_corrects:
            out.append(phrases["self_correct"])
        if self.changes_mind:
            out.append(phrases["changes_mind"])
        if self.abrupt_ending:
            out.append(phrases["abrupt"])
        return out


@dataclass(frozen=True)
class CallerWorld:
    """The hidden ground truth for one generated call."""

    seed: int
    domain: str
    language: str
    identity: Identity
    need: Need
    hard_constraint: Constraint
    soft_preferences: tuple[Constraint, ...] = ()
    #: True but irrelevant. Real callers volunteer these and agents get derailed.
    distractors: tuple[str, ...] = ()
    #: Roughly how the caller opens. Openings are usually bad.
    opening: str = ""

    def spoken_facts(self) -> list[tuple[str, Disclosure]]:
        """Every fact the caller could say, with when they would say it."""
        facts = [(self.hard_constraint.spoken, self.hard_constraint.disclosure)]
        facts.extend((c.spoken, c.disclosure) for c in self.soft_preferences)
        return facts


@dataclass(frozen=True)
class Rubric:
    """What a correct outcome looks like. The caller model never sees this.

    Built from the world rather than written alongside it, so it cannot drift
    into describing a path. B2 implements the checks; this is the contract.
    """

    world_seed: int
    #: The outcome must not violate this. Violation is a FAIL regardless of
    #: whether the caller sounded happy.
    hard_constraint: Constraint
    #: Values that must appear correctly in whatever the agent recorded.
    must_capture: dict[str, Any] = field(default_factory=dict)
    #: The agent must not claim these happened unless a tool call proves it.
    claims_needing_proof: tuple[str, ...] = ()
    #: Soft preferences: honoured is better, ignored is not a failure.
    nice_to_have: tuple[Constraint, ...] = ()

    @classmethod
    def from_world(cls, world: CallerWorld, *, must_capture: dict[str, Any]) -> Rubric:
        return cls(
            world_seed=world.seed,
            hard_constraint=world.hard_constraint,
            must_capture=must_capture,
            nice_to_have=world.soft_preferences,
        )
