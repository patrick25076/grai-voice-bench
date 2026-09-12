"""Raw material for generated callers, per domain and language.

Everything here is content, not logic. `generate.py` samples from it with a
seeded RNG. Kept separate so a new vertical is a data change, and so the
open-source release can ship `clinic` while `order` stays private if we want.

Two domains today:

* ``clinic`` — dental front desk, scheduling and questions. Mock tools. This is
  the pack that goes public, because nothing in it is a real customer.
* ``order`` — supplier order intake, shaped like Nora's job. Never talks to the
  real CRM.

A note on the constraints: each one is a thing that is TRUE about the caller,
never an instruction about what to do on the call. The `Constraint` constructor
rejects the second kind.

Everything spoken is written in the SECOND person, because the caller model
reads it as "what is true about you". Third-person content produced prompts that
said "you: they can't get away before five", which is both wrong and confusing
for the persona.
"""

from __future__ import annotations

from .world import Constraint, Disclosure

# --------------------------------------------------------------------------
# People
# --------------------------------------------------------------------------

#: Surnames chosen because they are hard over a phone line: near-homophones,
#: silent letters, or spellings a listener will guess wrong. Entity capture is
#: the top measured S2S failure, so the names should attack it.
NAMES_EN: tuple[tuple[str, str, str | None], ...] = (
    ("Alex", "Thwaite", "T-H-W-A-I-T-E"),
    ("Priya", "Raghunathan", "R-A-G-H-U-N-A-T-H-A-N"),
    ("Tom", "Keogh", "K-E-O-G-H, it's pronounced 'kyo'"),
    ("Sarah", "Mainwaring", "M-A-I-N-W-A-R-I-N-G, said 'mannering'"),
    ("Dan", "Featherstonehaugh", "F-E-A-T-H-E-R-S-T-O-N-E-H-A-U-G-H, said 'fanshaw'"),
    ("Nia", "Llewellyn", "double-L twice, L-L-E-W-E-L-L-Y-N"),
    ("Marcus", "Oyelaran", "O-Y-E-L-A-R-A-N"),
    ("Beth", "Cholmondeley", "C-H-O-L-M-O-N-D-E-L-E-Y, said 'chumley'"),
    ("Ines", "Szabó", "S-Z-A-B-O with an accent on the O"),
    ("Rory", "MacIlwraith", "M-A-C-I-L-W-R-A-I-T-H"),
)

NAMES_RO: tuple[tuple[str, str, str | None], ...] = (
    ("Andrei", "Mihăilescu", "M-I-H-Ă-I-L-E-S-C-U"),
    ("Ioana", "Gheorghiu", "G-H-E-O-R-G-H-I-U"),
    ("Cătălin", "Ștefănescu", "cu Ș și Ă, Ș-T-E-F-Ă-N-E-S-C-U"),
    ("Raluca", "Dumitrașcu", "D-U-M-I-T-R-A-Ș-C-U"),
    ("Bogdan", "Anghelescu", "A-N-G-H-E-L-E-S-C-U"),
    ("Elena", "Vîlcu", "V-Î-L-C-U, cu î din i"),
)

PHONES_EN = ("07700 900123", "07700 900456", "07911 123456", "020 7946 0812", "07458 291044")
PHONES_RO = ("0722 314 558", "0745 902 117", "0733 481 260", "0264 590 118")

# --------------------------------------------------------------------------
# Clinic: dental front desk
# --------------------------------------------------------------------------

CLINIC_NEEDS_EN: tuple[tuple[str, dict, str], ...] = (
    ("checkup", {"service": "check-up"}, "you want a routine check-up, it has been a while"),
    ("cleaning", {"service": "hygienist"}, "you want a clean, the hygienist one"),
    ("pain", {"service": "urgent", "urgency": "high"}, "a tooth has been hurting you"),
    ("child", {"service": "check-up", "for": "child"}, "you want an appointment for your son"),
    ("crown_refit", {"service": "treatment"}, "a crown of yours feels loose"),
    ("whitening_q", {"service": "enquiry"}, "you have a question about whitening, and might book"),
    ("reschedule", {"service": "reschedule"}, "you want to move an appointment you already have"),
)

CLINIC_HARD_EN: tuple[tuple[str, dict, str, Disclosure], ...] = (
    (
        "no_weekday",
        {"weekday": "tuesday"},
        "Tuesdays are impossible for you, that is your day in the office",
        Disclosure.ON_CONFLICT,
    ),
    (
        "after_time",
        {"not_before": "17:00"},
        "you cannot get away from work before five",
        Disclosure.ON_CONFLICT,
    ),
    (
        "before_time",
        {"not_after": "11:00"},
        "you need it early, you have the school run at eleven",
        Disclosure.ON_ASK,
    ),
    (
        "away_range",
        {"unavailable_from": "the 18th", "unavailable_to": "the 25th"},
        "you are away from the 18th to the 25th",
        Disclosure.ON_CONFLICT,
    ),
    (
        "named_clinician",
        {"must_be": "the dentist seen last time"},
        "it has to be the same dentist as last time, she knows your history",
        Disclosure.IF_PRESSED,
    ),
    (
        "needs_double",
        {"min_minutes": 60},
        "you need a long appointment, last time there was not enough time",
        Disclosure.ON_ASK,
    ),
)

CLINIC_SOFT_EN: tuple[tuple[str, dict, str, Disclosure], ...] = (
    ("prefer_morning", {"prefer": "morning"}, "mornings suit you better", Disclosure.VOLUNTEERED),
    (
        "prefer_soon",
        {"prefer": "asap"},
        "sooner is better if anything is free",
        Disclosure.VOLUNTEERED,
    ),
    ("parking", {"prefer": "parking"}, "you would like to know about parking", Disclosure.ON_ASK),
    ("cost_aware", {"prefer": "price"}, "you want a rough idea of the cost", Disclosure.ON_ASK),
)

CLINIC_DISTRACTORS_EN: tuple[str, ...] = (
    "your sister is also a patient there",
    "a colleague at work recommended them to you",
    "you had a bad experience at a different practice years ago",
    "you are nervous about the drill, and you mention it more than once",
    "you are getting married in the spring",
    "you thought the practice was on another street and wonder if it moved",
    "you are convinced your last visit was in March when it was actually May",
)
# Distractors must not describe WHERE the caller is: CallerBehavior.noise already
# sets that, and a caller who is both "in the car" and "in a workshop" reads as
# broken rather than as realistic.

CLINIC_OPENINGS_EN: tuple[str, ...] = (
    "open by asking whether this is even the right number",
    "open mid-thought, as though continuing a conversation",
    "open with the problem rather than with what you want",
    "open by apologising for calling at a bad time",
    "open by asking a completely different question first",
    "open by giving your name before saying why you called",
    "open by asking whether you could just be seen today",
)

# --------------------------------------------------------------------------
# Order intake: supplier phone orders, Nora-shaped
# --------------------------------------------------------------------------

ORDER_NEEDS_EN: tuple[tuple[str, dict, str], ...] = (
    ("restock", {"product": "dry ice", "unit": "kg"}, "you want your usual order, topped up"),
    ("new_order", {"product": "dry ice", "unit": "kg"}, "you need a delivery for a job next week"),
    ("change_order", {"action": "amend"}, "you want to change an order you placed already"),
    ("urgent_order", {"urgency": "high"}, "it is urgent, you have run short"),
    ("price_then_order", {"action": "quote_first"}, "you want a price, and then probably to order"),
    ("cancel_part", {"action": "reduce"}, "you want to cut back a delivery that is too big"),
)

ORDER_HARD_EN: tuple[tuple[str, dict, str, Disclosure], ...] = (
    (
        "dock_closes",
        {"delivery_not_after": "15:00"},
        "your loading bay shuts at three, nothing can arrive after that",
        Disclosure.ON_CONFLICT,
    ),
    (
        "min_quantity",
        {"min_qty": 200, "unit": "kg"},
        "under two hundred kilos is not worth the trip for you",
        Disclosure.ON_ASK,
    ),
    (
        "before_production",
        {"delivery_not_after": "07:00"},
        "it has to be there before your production starts at seven",
        Disclosure.ON_CONFLICT,
    ),
    (
        "no_friday",
        {"weekday_excluded": "friday"},
        "nobody is on your site Friday afternoon to take a delivery in",
        Disclosure.ON_CONFLICT,
    ),
    (
        "site_change",
        {"deliver_to": "the second site, not the registered address"},
        "this one goes to your other site, not the address on the account",
        Disclosure.IF_PRESSED,
    ),
    (
        "po_required",
        {"requires": "purchase order number on the paperwork"},
        "your finance team rejects anything without a PO number on it",
        Disclosure.IF_PRESSED,
    ),
)

ORDER_SOFT_EN: tuple[tuple[str, dict, str, Disclosure], ...] = (
    (
        "same_driver",
        {"prefer": "usual driver"},
        "you like the usual driver, he knows the gate code",
        Disclosure.VOLUNTEERED,
    ),
    (
        "call_ahead",
        {"prefer": "call on approach"},
        "a call twenty minutes out would help you",
        Disclosure.ON_ASK,
    ),
    (
        "invoice_email",
        {"prefer": "invoice by email"},
        "the invoice should go to your accounts team, not to you",
        Disclosure.ON_ASK,
    ),
)

ORDER_DISTRACTORS_EN: tuple[str, ...] = (
    "your last delivery came on broken pallets, and you mention it",
    "the colleague who usually makes this call is off sick",
    "a competitor quoted you cheaper, though you do not push it",
    "you ask about a completely different product they do not sell",
    "you refer to an invoice number that is actually from a different order",
    "you are certain you spoke to someone called Mihai last time",
)

ORDER_OPENINGS_EN: tuple[str, ...] = (
    "open with 'it's me again', assuming you are recognised",
    "open by reading out an account number nobody asked for",
    "open by asking whether a delivery has already gone out",
    "open mid-sentence, after talking to someone else in the room",
    "open with the quantity before saying what the product is",
    "open by asking for a person by name who may not work there",
)

# Romanian order pack. Gate zero (2026-09-11) confirmed gpt-live-1 speaks
# Romanian, so the Nora arm can run in its real language.
ORDER_NEEDS_RO: tuple[tuple[str, dict, str], ...] = (
    (
        "restock",
        {"product": "gheață carbonică", "unit": "kg"},
        "vreți comanda obișnuită, completată",
    ),
    (
        "new_order",
        {"product": "gheață carbonică", "unit": "kg"},
        "aveți nevoie de o livrare pentru o lucrare",
    ),
    ("change_order", {"action": "amend"}, "vreți să modificați o comandă deja plasată"),
    ("urgent_order", {"urgency": "high"}, "este urgent, ați rămas fără stoc"),
)

ORDER_HARD_RO: tuple[tuple[str, dict, str, Disclosure], ...] = (
    (
        "dock_closes",
        {"delivery_not_after": "15:00"},
        "rampa dumneavoastră se închide la trei, nu poate ajunge nimic după",
        Disclosure.ON_CONFLICT,
    ),
    (
        "before_production",
        {"delivery_not_after": "07:00"},
        "trebuie să ajungă înainte să înceapă producția la șapte",
        Disclosure.ON_CONFLICT,
    ),
    (
        "min_quantity",
        {"min_qty": 200, "unit": "kg"},
        "sub două sute de kilograme nu merită drumul pentru dumneavoastră",
        Disclosure.ON_ASK,
    ),
    (
        "site_change",
        {"deliver_to": "al doilea punct de lucru"},
        "comanda asta merge la celălalt punct de lucru al dumneavoastră, nu la adresa din contract",
        Disclosure.IF_PRESSED,
    ),
)

ORDER_SOFT_RO: tuple[tuple[str, dict, str, Disclosure], ...] = (
    (
        "call_ahead",
        {"prefer": "sună înainte"},
        "v-ar ajuta un telefon cu douăzeci de minute înainte",
        Disclosure.ON_ASK,
    ),
    (
        "invoice_email",
        {"prefer": "factura pe email"},
        "factura trebuie să meargă la contabilitate, nu la dumneavoastră",
        Disclosure.ON_ASK,
    ),
)

ORDER_DISTRACTORS_RO: tuple[str, ...] = (
    "ultima livrare a venit pe paleți rupți și pomeniți asta",
    "colegul care sună de obicei este în concediu medical",
    "întrebați despre un produs pe care furnizorul nu îl are",
    "sunteți convins că data trecută ați vorbit cu cineva pe nume Mihai",
    "un concurent v-a dat un preț mai bun, deși nu insistați pe asta",
)

ORDER_OPENINGS_RO: tuple[str, ...] = (
    "începeți cu „eu sunt iar”, presupunând că sunteți recunoscut",
    "începeți citind un număr de contract pe care nu l-a cerut nimeni",
    "începeți întrebând dacă a plecat deja o livrare",
    "începeți cu cantitatea, înainte să spuneți despre ce produs e vorba",
)


def _as_constraints(rows: tuple[tuple[str, dict, str, Disclosure], ...]) -> tuple[Constraint, ...]:
    return tuple(
        Constraint(kind=kind, params=params, spoken=spoken, disclosure=disc)
        for kind, params, spoken, disc in rows
    )


#: domain -> language -> content bundle
PACKS: dict[str, dict[str, dict]] = {
    "clinic": {
        "en": {
            "names": NAMES_EN,
            "phones": PHONES_EN,
            "needs": CLINIC_NEEDS_EN,
            "hard": _as_constraints(CLINIC_HARD_EN),
            "soft": _as_constraints(CLINIC_SOFT_EN),
            "distractors": CLINIC_DISTRACTORS_EN,
            "openings": CLINIC_OPENINGS_EN,
            "business": "a dental practice",
        }
    },
    "order": {
        "en": {
            "names": NAMES_EN,
            "phones": PHONES_EN,
            "needs": ORDER_NEEDS_EN,
            "hard": _as_constraints(ORDER_HARD_EN),
            "soft": _as_constraints(ORDER_SOFT_EN),
            "distractors": ORDER_DISTRACTORS_EN,
            "openings": ORDER_OPENINGS_EN,
            "business": "a supplier that takes orders by phone",
        },
        "ro": {
            "names": NAMES_RO,
            "phones": PHONES_RO,
            "needs": ORDER_NEEDS_RO,
            "hard": _as_constraints(ORDER_HARD_RO),
            "soft": _as_constraints(ORDER_SOFT_RO),
            "distractors": ORDER_DISTRACTORS_RO,
            "openings": ORDER_OPENINGS_RO,
            "business": "un furnizor care preia comenzi la telefon",
        },
    },
}
