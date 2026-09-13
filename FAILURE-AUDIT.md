# What failed, and what the benchmark can actually establish

Published 2026-09-13 as a diagnostic addendum to `study60-v1`. No new model calls
were made, no recordings were replaced, and no original grades were changed.

The [viewer](https://patrick25076.github.io/grai-voice-bench/) now separates
state checks from blocked tool attempts. Its [audit data](https://patrick25076.github.io/grai-voice-bench/audit.json)
contains selected, captured target prompts and native tool declarations for every
call. The original [versioned dataset](https://github.com/patrick25076/grai-voice-bench/releases/tag/study60-v1)
remains the reference for the experiment. A successful-sounding conversation is
not sufficient evidence of a saved action, and a red check is not sufficient
evidence of a model failure.

## S033: lookup was supplied, but not called

[Open S033](https://patrick25076.github.io/grai-voice-bench/#S033).

The captured Gemini connection configuration includes this function:

```json
{
  "name": "lookup_order",
  "description": "Read only this caller's orders. Older orders require human changes."
}
```

It takes no arguments. In this sandbox, the caller is already associated with
authorized records. Calling `lookup_order()` would have returned `PREVIOUS-001`;
the customer did not need to recite an order ID. This is a synthetic authorization
fixture, not a production identity-verification implementation.

The procedure also says to look up older orders and leave a team request. Gemini
instead called `take_message` before lookup, omitted the order reference, and
received `not_authorized` with an instruction to look up the authorized order.
It never called lookup and saved no message. It then described itself as unable
to see older orders. That description contradicts the supplied tool contract.

Gemini successfully called the same lookup tool in S003 and S048. Its matched
GPT-Live trial, S034, called lookup and saved the requested follow-up. These
observations argue against a missing Gemini tool declaration. They do not prove
the prompt was optimal or that the difference was caused by model weights alone.

There is a separate caller problem in S033: it claimed to have already supplied
a phone number and ended without resolving its agenda. Both failures remain
visible. The caller error did not remove the no-argument lookup tool.

The restriction on **editing older orders was our business policy**. Both systems
could read older orders, but had to ask a human to change them. If a deployment
should permit editing older orders, its tools, permissions and expected outcome
need a different scenario. This study did not test automatic changes to old orders.

## S027: the order succeeded after a blocked attempt

[Open S027](https://patrick25076.github.io/grai-voice-bench/#S027).

1. Gemini tried `record_order` with `confirmed=false`. The sandbox rejected it
   with `confirmation_required`; no order or stock changed.
2. The agent read the details back and the caller agreed.
3. It retried with `confirmed=true` and saved one correct order, `NEW-001`.

The original **state grade is PASS**. The attempted-action grade is FAIL because
the frozen rule remembers the earlier blocked attempt. The transcript-assisted
consent and truth assessments pass, with human audio verification still pending.

The appropriate description is **correct saved order after a blocked attempt**.
It is misleading to call this a failed order, an unauthorized committed order,
or evidence that the sandbox failed to protect the write. Six Gemini calls passed
their original state checks while retaining a blocked-attempt flag. The seventh
flagged Gemini call was S033, whose final state also failed.

## Other examples show why a single failure label is insufficient

| Sample                                                                  | Observed outcome                                                                                                              | Interpretation                                                                                                                                   |
| ----------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| [S030](https://patrick25076.github.io/grai-voice-bench/#S030), Gemini   | Created and cancelled the right order; a requested spelling correction produced an extra update to an already-correct surname | Cancellation succeeded. The strict create-then-cancel sequence rejected the intermediate update. Separate consent issues remain.                 |
| [S039](https://patrick25076.github.io/grai-voice-bench/#S039), GPT-Live | Created and amended the order using the shortened phone number actually supplied by the AI caller                             | The fixture's phone check failed. This is not clean evidence that GPT extracted the spoken number incorrectly.                                   |
| [S048](https://patrick25076.github.io/grai-voice-bench/#S048), Gemini   | Looked up the right order, claimed to have taken a message, never called `take_message`                                       | A substantive tool/claim mismatch. Caller phone errors also occurred, but do not explain the absent message after successful lookup.             |
| [S054](https://patrick25076.github.io/grai-voice-bench/#S054), Gemini   | Correct order persisted, but its response was deliberately lost; no lookup or same-key retry followed                         | Saved state and verified recovery differ. The recovery failed; the underlying order was not lost.                                                |
| S009 and S046, GPT-Live                                                 | Follow-up had an empty optional reference rather than an absent field                                                         | The already-declared scoring erratum corrects that equivalence for both systems. It is a grader correction, not newly successful model behavior. |

These explanations come from the recorded tool state and existing provisional
transcript assessments. This addendum does not promote them to human listening.

## What the tool audit verifies

All **60/60** captured target configurations contain the expected seven tools,
matching their registry's common parameter contract. All **30/30** matched pairs
share that contract. Successful lookup calls are visible in Gemini S003/S048 and
GPT-Live S004/S013/S034/S047.

The audit compares names, descriptions, required fields, types, enums and numeric
constraints. It retains the raw provider declarations and their prompts. Google
uses uppercase type names and omits a parameters object for a no-argument tool;
Google's [Live API examples](https://ai.google.dev/gemini-api/docs/live-api/tools)
also use parameterless function declarations.

There is a disclosed schema difference: the pinned Google SDK omits
`additionalProperties:false`, which is present in the shared/OpenAI schemas.
The common-contract comparison excludes that field and `propertyOrdering`.
Therefore **common-contract match does not mean identical provider validation**.
No absent lookup declaration was found, but this audit is not a proof that every
possible adapter behavior is equivalent.

These hooks capture the configuration at the SDK's connection-building boundary.
They are stronger evidence than inspecting a Python tool list alone, but are not
a provider acknowledgement of each function. The exporter anchors the addendum
to the original `data.json` hash; the viewer refuses to apply a mismatched audit.

Reproduce the inspection locally, without making a call:

```sh
uv run python explain.py --data exports/study60/data.json \
  --runs runs/study60 --output exports/audit/audit.json
```

This requires the private per-trial `agent-evidence.json` files from your own run.
The output intentionally selects tool declarations and prompts, not account or
routing envelopes. Review your own prompt contents before publishing them.

## Fair comparison, with limits

Gemini's original state checks passed 24/30. GPT-Live passed 18/30, or 20/30 after
the declared grading correction. Attempt checks passed 23/30 and 30/30 respectively.
Neither set of counts establishes human-validated business success or a winner.
Only six English pairs had passing caller reviews on both arms, and both targets
passed the original state checks in all six. That post-hoc subset is affected by
how targets influence their callers and must not be used as an unbiased ranking.

The target prompt did not contain the customer's future agenda, exact address,
phone number or grader answers. Both targets received the shared business
procedure. The **simulated customer** knew its own facts and planned requests;
its prompt often led it to give everything up front. That is useful for exercising
tools, but weak coverage of natural information gathering. Fixtures repeated
the same synthetic facts and varied only a small set of personas and workflows.

Seven calibration calls established working examples and caught setup problems.
They did not establish prompt robustness. A future controlled diagnostic should
hold model, fixture, transport and audio stimulus fixed, compare the original
prompt with an explicit lookup instruction, and label those new calls separately.
If the clarified version succeeds, that indicates prompt sensitivity; it still
does not make the original failure disappear. No such new model experiment was
conducted in this addendum.

## What was the latency?

| Language |   Gemini | GPT-Live |
| -------- | -------: | -------: |
| English  | 2,010 ms | 1,800 ms |
| Romanian | 2,300 ms | 1,820 ms |

These are **medians of per-call median PCM energy gaps**, not validated
end-of-utterance-to-first-speech latencies. The threshold can miss quiet speech;
acknowledgments count; overlapping replies are excluded. They do not establish
that GPT-Live is faster. Silent hangup tails affect duration and cost, not
necessarily task-completion speed. Original audio level and speed are preserved.

A proper latency report needs separate measures for caller-end to first audible
response, caller-end to substantive answer, tool-result to spoken result,
interruption-to-yield, and last required action to audible completion. Each needs
a defined clock, event pairing, unavailable/overlap handling, and audited audio
boundaries. Values computed from different definitions must not share a ranking.
