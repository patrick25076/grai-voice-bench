"""Seeded generation of test callers, and the prompt the caller model receives.

One seed produces one call, reproducibly. A different seed produces a genuinely
different one: different person, different need, different hidden constraint,
different amount of awkwardness, and a different moment at which the constraint
surfaces.

Run it to look at what comes out::

    uv run python -m voicelab.bench.generate --domain clinic --seeds 3
    uv run python -m voicelab.bench.generate --domain order --language ro --seeds 2
    uv run python -m voicelab.bench.generate --domain clinic --seed 41 --prompt-only

The generated prompt is checked by :func:`assert_no_leakage` before it is
returned. That check is the whole point of this module: the old tester leaked
the answer into the question, and a guard is harder to forget than a convention.
"""

from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass

from .packs import PACKS
from .world import CallerBehavior, CallerWorld, Constraint, Disclosure, Identity, Need, Rubric

#: Phrases that mean the caller has been told how the call should end, or what
#: to agree to. Any of these in a caller prompt makes the run worthless: the
#: caller stops being a test and becomes a co-operator. Drawn from the failure
#: in `clinic.eval.scenarios`, which contained three of them at once.
LEAKAGE_MARKERS: tuple[str, ...] = (
    "accept the first",
    "accept any",
    "once it's confirmed",
    "once confirmed",
    "thank them and end",
    "end the call once",
    "when the appointment is confirmed",
    "your goal is to book",
    "make sure they book",
    "you should book",
    "you should accept",
    "expected outcome",
    "the agent should",
    "the receptionist should",
    "if they do it correctly",
)


class PromptLeak(AssertionError):
    """Raised when a caller prompt tells the caller how the call should end."""


def assert_no_leakage(prompt: str) -> None:
    lowered = prompt.lower()
    hits = [m for m in LEAKAGE_MARKERS if m in lowered]
    if hits:
        raise PromptLeak(
            "caller prompt resolves the agent's job, which defeats the test. "
            f"Offending phrases: {hits}"
        )


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------


def generate_behavior(rng: random.Random) -> CallerBehavior:
    """Sample how awkward this caller is.

    Skewed deliberately: most real callers are mildly awkward and a few are very.
    A uniform sample would make every generated call equally strange, which is
    its own kind of unrealistic.
    """
    return CallerBehavior(
        interruption=round(rng.betavariate(2, 5), 2),
        self_corrects=rng.random() < 0.35,
        changes_mind=rng.random() < 0.25,
        answer_drift=round(rng.betavariate(2, 4), 2),
        filler=round(rng.betavariate(3, 4), 2),
        pace=rng.choices(("slow", "normal", "fast"), weights=(0.2, 0.55, 0.25))[0],
        noise=rng.choices(
            ("quiet", "office", "street", "car", "workshop"),
            weights=(0.35, 0.25, 0.15, 0.15, 0.10),
        )[0],
        abrupt_ending=rng.random() < 0.3,
    )


def generate_world(seed: int, domain: str, language: str) -> CallerWorld:
    try:
        pack = PACKS[domain][language]
    except KeyError as exc:
        available = {d: sorted(langs) for d, langs in PACKS.items()}
        raise KeyError(
            f"no pack for domain={domain!r} language={language!r}; have {available}"
        ) from exc

    rng = random.Random(seed)

    given, family, spelling = rng.choice(pack["names"])
    identity = Identity(
        given_name=given,
        family_name=family,
        # Half the time they do not offer the spelling. Making the agent ask is
        # the interesting case.
        spelling_hint=spelling if rng.random() < 0.5 else None,
        phone=rng.choice(pack["phones"]),
        company=None,
    )

    need_kind, need_params, need_summary = rng.choice(pack["needs"])
    need = Need(kind=need_kind, params=dict(need_params), summary=need_summary)

    hard: Constraint = rng.choice(pack["hard"])
    soft = tuple(rng.sample(pack["soft"], k=rng.randint(0, min(2, len(pack["soft"])))))
    distractors = tuple(
        rng.sample(pack["distractors"], k=rng.randint(0, min(2, len(pack["distractors"]))))
    )

    return CallerWorld(
        seed=seed,
        domain=domain,
        language=language,
        identity=identity,
        need=need,
        hard_constraint=hard,
        soft_preferences=soft,
        distractors=distractors,
        opening=rng.choice(pack["openings"]),
    )


def build_rubric(world: CallerWorld) -> Rubric:
    """What the grader will check. Never shown to the caller."""
    must_capture: dict[str, object] = {
        "family_name": world.identity.family_name,
        "phone": world.identity.phone,
    }
    must_capture.update({f"need.{k}": v for k, v in world.need.params.items()})
    return Rubric.from_world(world, must_capture=must_capture)


# --------------------------------------------------------------------------
# The caller prompt
# --------------------------------------------------------------------------

LANGUAGE_NAMES = {"en": "English", "ro": "Romanian", "nl": "Dutch", "fr": "French", "de": "German"}

#: What the language is called IN that language. "Vorbiți numai în Romanian" is
#: the kind of seam that makes a persona wobble.
LANGUAGE_ENDONYMS = {
    "en": "English",
    "ro": "română",
    "nl": "Nederlands",
    "fr": "français",
    "de": "Deutsch",
}

#: Prompt scaffolding per language. A caller prompt that is half English and half
#: the target language invites exactly the language drift the grader flags, so
#: the frame is translated too, not just the facts.
TEMPLATES: dict[str, dict[str, object]] = {
    "en": {
        "header": (
            "You are {name}. You are phoning {business}.\n"
            "You are the CALLER. They have just picked up."
        ),
        "who": "WHO YOU ARE",
        "name_is": "- Your name is {name}.",
        "spell_yes": "- If they need your surname spelled: {hint}.",
        "spell_no": "- You do not spell your surname unless they ask. You assume they got it.",
        "phone": "- Your number is {phone}. You give it only if they ask for it.",
        "why": "WHY YOU CALLED",
        "opening": "- You {opening}.",
        "truth": "WHAT IS TRUE ABOUT YOUR SITUATION",
        "distractor": "- Also true, though it does not really matter: {fact}.",
        "speak": "HOW YOU SPEAK",
        "easy": "- You are clear and easy to deal with.",
        "noisy": "- You are calling from somewhere noisy: {place}.",
        "rules_head": "HOW THIS CALL GOES",
        "rules": [
            "- Speak only {lang}.",
            "- Stay in character. Never say or hint that you are a test, a bot, or an AI.",
            "- Short spoken sentences, one point at a time. This is a phone call, not an email.",
            "- You do not know what they are going to offer you, and you have not decided in",
            "  advance how this ends. Respond to what they actually say.",
            "- You are under no obligation to agree to anything. If what they offer does not",
            "  work for you, say so plainly, the way a real person would.",
            "- If they have not solved your problem, do not pretend they have.",
            "- When you genuinely have nothing left to say, stop talking.",
        ],
        "disclosure": {
            Disclosure.VOLUNTEERED: "You mention this early, without being asked.",
            Disclosure.ON_ASK: "You mention this only if they ask something that touches on it.",
            Disclosure.ON_CONFLICT: (
                "This does not cross your mind until they suggest something that clashes with "
                "it. When they do, you push back."
            ),
            Disclosure.IF_PRESSED: (
                "You assume they already know this, so you do not raise it. It only comes out "
                "if they ask you directly, or ask a second time."
            ),
        },
        "places": {
            "office": "an office",
            "street": "the street",
            "car": "a car",
            "workshop": "a workshop",
        },
    },
    "ro": {
        "header": "Sunteți {name}. Sunați la {business}.\nDumneavoastră SUNAȚI. Tocmai au răspuns.",
        "who": "CINE SUNTEȚI",
        "name_is": "- Vă numiți {name}.",
        "spell_yes": "- Dacă au nevoie să vă silabisiți numele: {hint}.",
        "spell_no": "- Nu vă silabisiți numele decât dacă vi se cere. Presupuneți că au înțeles.",
        "phone": "- Numărul dumneavoastră este {phone}. Îl dați doar dacă vi-l cer.",
        "why": "DE CE AȚI SUNAT",
        "opening": "- {opening}.",
        "truth": "CE ESTE ADEVĂRAT DESPRE SITUAȚIA DUMNEAVOASTRĂ",
        "distractor": "- De asemenea adevărat, deși nu prea contează: {fact}.",
        "speak": "CUM VORBIȚI",
        "easy": "- Sunteți clar și ușor de servit.",
        "noisy": "- Sunați dintr-un loc zgomotos: {place}.",
        "rules_head": "CUM DECURGE APELUL",
        "rules": [
            "- Vorbiți numai în {lang}.",
            "- Rămâneți în personaj. Nu spuneți și nu sugerați niciodată",
            "  că sunteți un test sau un AI.",
            "- Propoziții scurte, un singur lucru pe rând. Este un apel telefonic, nu un e-mail.",
            "- Nu știți ce vă vor oferi și nu ați decis dinainte cum se termină apelul.",
            "  Reacționați la ce spun ei de fapt.",
            "- Nu sunteți obligat să acceptați nimic. Dacă ce vă oferă nu vă convine,",
            "  spuneți direct, așa cum ar face un om real.",
            "- Dacă nu v-au rezolvat problema, nu vă prefaceți că da.",
            "- Când chiar nu mai aveți nimic de spus, încetați să vorbiți.",
        ],
        "disclosure": {
            Disclosure.VOLUNTEERED: "Menționați asta devreme, fără să vi se ceară.",
            Disclosure.ON_ASK: "Menționați asta doar dacă întreabă ceva legat de subiect.",
            Disclosure.ON_CONFLICT: (
                "Nu vă gândiți la asta până când nu vă propun ceva care intră în conflict. "
                "Când o fac, obiectați."
            ),
            Disclosure.IF_PRESSED: (
                "Presupuneți că ei știu deja, deci nu aduceți vorba. Iese la iveală doar dacă "
                "vă întreabă direct sau insistă."
            ),
        },
        "places": {
            "office": "un birou",
            "street": "stradă",
            "car": "mașină",
            "workshop": "o hală",
        },
    },
}


def render_caller_prompt(world: CallerWorld, behavior: CallerBehavior) -> str:
    pack = PACKS[world.domain][world.language]
    t = TEMPLATES.get(world.language, TEMPLATES["en"])
    lang = LANGUAGE_ENDONYMS.get(world.language, LANGUAGE_NAMES.get(world.language, world.language))
    i = world.identity
    disclosure_rules: dict = t["disclosure"]  # type: ignore[assignment]

    lines = [
        str(t["header"]).format(name=i.full_name, business=pack["business"]),
        "",
        str(t["who"]),
        str(t["name_is"]).format(name=i.full_name),
    ]
    lines.append(
        str(t["spell_yes"]).format(hint=i.spelling_hint) if i.spelling_hint else str(t["spell_no"])
    )
    lines += [
        str(t["phone"]).format(phone=i.phone),
        "",
        str(t["why"]),
        f"- {world.need.summary}.",
        str(t["opening"]).format(opening=world.opening),
        "",
        str(t["truth"]),
        f"- {world.hard_constraint.spoken}.",
        f"  {disclosure_rules[world.hard_constraint.disclosure]}",
    ]
    for soft in world.soft_preferences:
        lines.append(f"- {soft.spoken}.")
        lines.append(f"  {disclosure_rules[soft.disclosure]}")
    lines.extend(str(t["distractor"]).format(fact=d) for d in world.distractors)

    lines += ["", str(t["speak"])]
    directives = behavior.directives(world.language)
    if directives:
        lines.extend(f"- {d}" for d in directives)
    else:
        lines.append(str(t["easy"]))
    if behavior.noise != "quiet":
        places: dict = t["places"]  # type: ignore[assignment]
        lines.append(str(t["noisy"]).format(place=places.get(behavior.noise, behavior.noise)))

    lines += ["", str(t["rules_head"])]
    lines.extend(str(r).format(lang=lang) for r in t["rules"])  # type: ignore[union-attr]

    prompt = "\n".join(lines)
    assert_no_leakage(prompt)
    return prompt


@dataclass
class GeneratedCall:
    world: CallerWorld
    behavior: CallerBehavior
    rubric: Rubric
    caller_prompt: str


def generate(seed: int, domain: str = "clinic", language: str = "en") -> GeneratedCall:
    world = generate_world(seed, domain, language)
    behavior = generate_behavior(random.Random(seed ^ 0x5EED))
    return GeneratedCall(
        world=world,
        behavior=behavior,
        rubric=build_rubric(world),
        caller_prompt=render_caller_prompt(world, behavior),
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def render_report(call: GeneratedCall) -> str:
    w, b, r = call.world, call.behavior, call.rubric
    out = [
        "=" * 78,
        f"SEED {w.seed}   domain={w.domain}   language={w.language}",
        "=" * 78,
        "",
        "HIDDEN TRUTH (grader sees this, the agent never does)",
        f"  caller        {w.identity.full_name}   {w.identity.phone}",
        f"  spells name   {w.identity.spelling_hint or '(only if asked)'}",
        f"  need          {w.need.kind}  {w.need.params}",
        f"  HARD          [{w.hard_constraint.kind}] {w.hard_constraint.spoken}",
        f"                surfaces: {w.hard_constraint.disclosure.value}",
    ]
    for s in w.soft_preferences:
        out.append(f"  soft          [{s.kind}] {s.spoken}  ({s.disclosure.value})")
    for d in w.distractors:
        out.append(f"  noise         {d}")
    out += [
        "",
        "BEHAVIOUR",
        f"  pace={b.pace}  filler={b.filler}  interrupt={b.interruption}  drift={b.answer_drift}",
        f"  self_corrects={b.self_corrects}  changes_mind={b.changes_mind}  "
        f"abrupt_end={b.abrupt_ending}  noise={b.noise}",
        "",
        "GRADER WILL REQUIRE",
        f"  must not violate: {r.hard_constraint.kind} {r.hard_constraint.params}",
        f"  must capture:     {r.must_capture}",
        "",
        "CALLER PROMPT (this is all the caller model gets)",
        "-" * 78,
        call.caller_prompt,
        "-" * 78,
        "",
    ]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--domain", default="clinic", choices=sorted(PACKS))
    p.add_argument("--language", default="en")
    p.add_argument("--seed", type=int, default=None, help="one specific seed")
    p.add_argument("--seeds", type=int, default=3, help="how many consecutive seeds to show")
    p.add_argument("--start", type=int, default=1, help="first seed when using --seeds")
    p.add_argument("--prompt-only", action="store_true", help="print just the caller prompt")
    args = p.parse_args(argv)

    seeds = (
        [args.seed] if args.seed is not None else list(range(args.start, args.start + args.seeds))
    )
    for s in seeds:
        try:
            call = generate(s, args.domain, args.language)
        except KeyError as exc:
            print(exc, file=sys.stderr)
            return 2
        print(call.caller_prompt if args.prompt_only else render_report(call))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
