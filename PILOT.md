# First phone pilot: 12 September 2026

GRAI Labs ran one matched pair of Romanian ordering calls through a real PSTN
leg. Gemini saved an order with an incorrect surname. GPT-Live reached the
readback but did not save an order before the two-minute limit. Neither call
passed the complete saved-state checks. Overall conversational success is
unscored pending listening review.

This is an engineering pilot with two comparable calls. It cannot establish
which model is better, faster, cheaper overall, or ready for enterprise use.

## Setup

| Variable | Configuration |
| --- | --- |
| Case | `loading-dock`, Romanian, seed 41 |
| Need | 200 kg of dry ice on 15 September 2026, before a 15:00 dock closure |
| Fictional customer | Alex Smythe, Strada Exemplului 10 |
| Gemini target | `gemini-3.1-flash-live-preview`, Puck voice |
| GPT-Live target | `gpt-live-1`, Marin voice, `gpt-5.6-terra` Responses backend |
| Caller in both calls | `gemini-3.1-flash-live-preview` |
| Runtime in both calls | LiveKit Agents 1.8.1, one self-hosted worker on OVH |
| Phone path | Twilio IE1, same Romanian test number, LiveKit Germany 2 |
| Tools | Same synthetic stock, pricing and order backend, fresh per call |
| Limit | 120 seconds after the target answers |
| Execution order | GPT-Live first, Gemini second; no counterbalancing in this pilot |
| Recording | Two-channel carrier WAV on one clock |

Seeds fix the fixture and caller prompt. They do not fix generated speech.
The Gemini caller spoke differently in the two conversations. Provider prompt
formats also differ: GPT-Live splits voice behavior from backend procedures.
These are comparisons of configured systems, not isolated model inference.

## Observed saved state

| Observation | GPT-Live configuration | Gemini configuration |
| --- | --- | --- |
| Tool calls | `check_stock`, `get_price` | `get_price`, `check_stock`, `place_order` |
| Saved orders | 0 | 1 |
| Quantity and date | No saved order | Correct: 200 kg, 15 September |
| Delivery time | No saved order | 14:00, meets the dock constraint |
| Surname | No saved order | Saved `Smith`; fixture is `Smythe` |
| State pass | False | False |
| Overall pass | Unreviewed | Unreviewed |

The GPT-Live transcript reaches a readback and request for confirmation near
the cutoff. Absence of a write is a time-limited task failure; it does not
establish that the agent falsely claimed an order was saved. The caller's own
Gemini transcript contains `Smythe`, while the target saved `Smith`. Listening
review must still check what was actually spoken and whether the caller
confirmed any incorrect readback.

**Post-pilot grader correction:** the original Gemini scorecard also failed the
address field because it used literal equality. `str. Exemplului, nr. 10` is a
formatting variant of the fixture's `Strada Exemplului 10`. The released grader
normalizes the documented abbreviations and punctuation, retaining a separate
raw equality check and distinguishing house number 10 from 11. This correction
does not change the state-pass result: the surname still fails. Original private
scorecards remain unchanged; the correction was made after observing this case.

## Cost components, USD

| Observed component | GPT-Live call | Gemini call |
| --- | ---: | ---: |
| Target model estimate, including GPT backend | $0.119045 | $0.056562 |
| Caller model estimate | $0.057032 | $0.029903 |
| Retrieved carrier call and recording charges | $0.044500 | $0.044500 |

These are **partial components, not all-in totals**. Gemini usage snapshots
contain tokens without captured modality. LiveKit SIP/media, the inbound
Elastic SIP trunk leg, allocated hosting, and final model invoice reconciliation
are absent. Caller cost belongs to the test harness, separate from target cost.
The dated formulas and uncertainty flags are in `costs.py`, based on
[OpenAI pricing](https://developers.openai.com/api/docs/pricing) and
[Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-3.1-flash-live-preview),
checked 12 September 2026. Unknown prices must not be treated as free.

## Audio timing remains provisional

The analysis uses PCM energy, 20 ms frames, RMS threshold 300 and a 400 ms
segment-merge threshold. With caller channel assumed to be channel 0, it finds
five response-gap pairs for GPT-Live (median 1,720 ms) and four for Gemini
(median 3,450 ms). These are unvalidated segmentation outputs, **not semantic
turn latency or evidence that one model is faster**. Channel orientation,
utterance boundaries, overlap, and missed responses need listening review.
SDK speaking events and watchdog alerts are separate diagnostics.

## Diagnostics retained outside the comparison

Eight local attempts were reserved in the session ledger. One stopped before
making a remote call; three failed to connect the target; one was a completed
30-second connectivity smoke test; one was a completed 120-second exploratory
Gemini call with missing scorecards; two form the matched pair above.

The failed target connections exposed a trunk-authentication mismatch: Twilio
Elastic SIP origination does not support digest authentication. The dedicated
LiveKit trunk was changed to Twilio's documented signaling-IP allowlist, after
which real calls completed. A separate SDK usage-serialization error prevented
the exploratory Gemini scorecards from being written. It was fixed before the
matched pair. The fixture's delivery address was also made explicit before both
matched calls. These diagnostic attempts are excluded for declared protocol and
instrumentation reasons, not counted as model task-success observations.

## Evidence and next experiment

Private artifacts retain recordings, transcripts, tool arguments/results,
usage snapshots, prompt hashes, call IDs, routing rollback snapshots and the
spending ledger. This public release contains code, synthetic fixtures and this
sanitized report. It does not include the raw audio or private scorecards, so
the pilot observations are not independently auditable from the repository
alone. The framework supports reproducing new calls with your own accounts.

Before publishing a model comparison: review channel orientation and both
conversations; classify caller adherence and spoken confirmation; repeat each
case with balanced target order; reconcile every cost component; and publish
consented, anonymized per-call evidence. Physical noise and controlled barge-in
need audio interventions. A persona prompt does not establish either capability.
