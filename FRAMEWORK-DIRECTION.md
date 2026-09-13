# GRAI voice evaluations: what is useful and what to build

Research and implementation direction, 2026-09-13. This is a proposal; capabilities
marked planned are not shipped. The current study is an exploratory configured-
system comparison, not proof of model superiority. Read the [failure audit](FAILURE-AUDIT.md).

## Honest assessment

An AI caller, mock tools, scenarios, recordings and a dashboard are useful, but
the category is already established. More adapters or more scenario names alone
will not make GRAI distinctive. The current repository is an early, reusable
experiment toolkit, with considerable setup and a narrow business domain. It is
not yet a polished evaluation service for arbitrary voice agents.

The strongest product promise to validate is:

> Turn a failed voice interaction into an inspectable, repeatable business test,
> with evidence showing what the agent heard, attempted, changed and claimed.

This is a focus and execution opportunity, not a claim of being first. It becomes
valuable if a developer can add an existing agent, reproduce an issue, understand
its cause and prevent a regression with little integration work.

## Comparison with Speko

Speko's [S2S board](https://benchmarks.speko.ai/s2s) already exercises six concierge
scenarios involving changes, constraints and tools. It separately reports action,
completion, capability and first sound. We should not claim that tool testing,
multi-turn scenarios or response timing are additions Speko has never considered.

Its [public data](https://benchmarks.speko.ai/data.json) records the GPT-Live row
with a Luna backend; our study used Terra. Its first-sound note specifies a
provider-direct US-east4 run, n=5. Its main S2S board describes clean audio,
six scenarios and n=3. Our evidence used 30 pairs over a Twilio/LiveKit/PSTN route,
eight order workflows, and a different timing definition. The scores and latency
numbers cannot be compared as if they measured the same experiment.

Our contribution to discuss with Speko is a reusable state-transition/fault test
pack and inspectable phone evidence that can accompany model-selection results.
The inspected board/data do not establish whether Speko's unpublished runner
already supports the same facilities; ask about that before making exclusivity
claims. Agree on a shared protocol before proposing a numerical replication.

## Existing work to learn from

| Project                                                                          | Relevant existing work                                                                                                                                                                                                                                | Implication for GRAI                                                                                                             |
| -------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| [ServiceNow EVA](https://github.com/ServiceNow/eva)                              | Open-source spoken bot-to-bot evaluation, task/experience metrics, 213 scenarios and perturbations; its [tool/database documentation](https://github.com/ServiceNow/eva/blob/main/docs/airline_database_tool_schema.md) includes mutable reservations | Stateful tools and spoken simulation are not novel. Reuse compatible fixtures or contribute integrations where possible.         |
| [LiveKit simulations](https://docs.livekit.io/agents/start/testing/simulations/) | Text/audio simulations, mock tool integration, final-state grading, CI and result export; hosted on LiveKit Cloud                                                                                                                                     | A LiveKit-only simulation wrapper would have weak differentiation. Offer useful portable artifacts and checks across runtimes.   |
| [Pipecat](https://docs.pipecat.ai/pipecat/telephony/overview)                    | Existing Twilio/Telnyx telephony transports; its [benchmarks](https://www.pipecat.ai/benchmarks) cover voice components and dialogue/tool behavior                                                                                                    | Reuse media transports. Carrier adapters should record deployment details and measurements, not reinvent audio streaming.        |
| [voice-lab](https://github.com/saharmor/voice-lab)                               | Open-source voice-agent evaluation across models, prompts and personas                                                                                                                                                                                | Even a small community framework has prior art. Make onboarding and debugging demonstrably better.                               |
| [Hamming](https://hamming.ai/)                                                   | Commercial testing and production monitoring; advertises turning failures into regression tests                                                                                                                                                       | That workflow is also established. Local, portable, inspectable implementation would be our delivery choice, not a new category. |

These are documentation-level comparisons, not hands-on rankings of those
products or audits of their published benchmark correctness.

## Current versus planned

| Capability         | Current public implementation                                                                     | Needed next                                                                                           |
| ------------------ | ------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| Scenario execution | Eight fixed order workflows; live AI callers; scripted offline replay                             | User-defined scenario packs, progressive fact disclosure, controlled branches and caller validation   |
| Model adapters     | Gemini Live and GPT-Live via the pinned LiveKit plugins; shared tool registry                     | Stable model-adapter contract plus direct-audio diagnostic route                                      |
| Telephone route    | Working Twilio IE1 + LiveKit SIP/PSTN runner                                                      | Separate configurable transport interface and documented Telnyx integration                           |
| Browser            | Evidence and local personal-rating UIs                                                            | A browser/WebRTC **simulation transport**; playback pages are not this capability                     |
| Sandbox            | In-memory orders, isolated state, permissions, idempotency, injected lost result, state snapshots | Pluggable business services, explicit read/prepare/commit semantics and consent evidence              |
| Assessment         | Frozen state/history checks, provisional transcript review, human-rating storage                  | Separate outcome/process/recovery/test-validity verdicts; reviewed equivalence rules and adjudication |
| Observability      | Per-call audio, transcripts, tools, state and costs; native declaration audit                     | Common event timeline, clock provenance, exportable spans and comparison across revisions             |
| Latency            | Exploratory PCM gap diagnostics                                                                   | Audited first sound, substantive answer, tool-response speech and interruption/yield timings          |

## Architecture to work toward

Keep business tests independent of media transport and model provider:

```text
Scenario + caller agenda + fixture + business policy
                        |
                 Simulation runner
          /             |              \
  direct audio      browser/WebRTC      phone/SIP
                                        /    \
                                     Twilio Telnyx
                        |
              Existing agent/model adapter
                        |
              Instrumented mock tools
                        |
           State changes + audio + event trace
                        |
       Deterministic checks / audio review / report
```

A model adapter handles session setup, tool declarations, audio events, tool
results and usage. A transport handles connection, codec, audio delivery,
recording and carrier billing. The sandbox handles business state and faults.
Mixing these responsibilities would make it difficult to tell whether a change
in outcome came from a prompt, a provider or the phone route.

## Proposed next release, in order

1. **Make every verdict explainable.** Ship captured-schema inspection, blocked-
   attempt versus final-result distinctions, and links directly to each sample.
   This addendum implements that first step for the existing dataset. Keep
   immutable original evidence and version every later scoring change.
2. **Make one external developer's agent work.** Add a minimal adapter contract,
   one documented bring-your-own-agent example and a neutral result schema.
   Demonstrate it against the current LiveKit target and one Pipecat target.
   Use the same scenario pack and assertions for both.
3. **Fix caller realism and validity.** The opening request should not contain
   all private facts. Disclose address/phone when asked; introduce a correction
   only after the relevant save. Separate a scripted audio-stimulus mode for
   controlled timing from an adaptive persona mode for exploratory dialogue.
   Judge the caller against the agenda and preserve invalid attempts explicitly.
4. **Add transport comparisons.** Browser/direct audio first for fast debugging;
   Twilio and Telnyx phone routes for deployment checks. Declare region, codec,
   audio pacing and every media hop. Use recorded reference audio for matched
   acoustic probes and report transport results separately from model claims.
5. **Add substantive fault/consent tests.** Interrupted confirmation, a correction
   while a write is in flight, response lost after commit, duplicate delivery of
   a request, stock changing after a quote, a delayed lookup, and wrong-customer
   records. Verify no duplicate side effects and truthful recovery. A model's
   `confirmed=true` is not an independent consent record.
6. **Turn traces into regression fixtures.** Export an original failing run as a
   minimized scenario and replayable tool trace. Run original/clarified prompt,
   original/fixed adapter or transport variants in separately labeled experiments.
   Do not claim causal attribution from one replay that changes several variables.

A useful first acceptance test is: a developer changes their agent's prompt;
the same order-amendment scenario now creates a duplicate; CI fails and the report
shows the two writes, their keys, audio context and final state. The developer
can run that one case locally without buying a hosted evaluation subscription.

## How to find out whether developers actually want it

Start with three external teams that have an agent with business tools. Ask them
to reproduce one known failure, add one custom case and run it in CI. Record time
to first usable result, setup steps, bugs they could explain and fixes the tests
caught. A pleasant sample page or more scenario count is not evidence of adoption.

For a Speko collaboration, propose exchanging two existing-order/recovery cases
and one latency stimulus with the same model backend, prompt, clock and tool
contract. Let both runners execute them and inspect the differences together.
Prepare a short methodology note before drawing a cross-benchmark conclusion.
No message has been sent to Speko or anyone else as part of this work.
