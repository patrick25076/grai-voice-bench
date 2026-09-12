# Study proposal: voice agents completing and revising phone orders

The research question is: **How reliably does each configured voice system turn
a changing spoken request into the correct business state, and what time and
cost does that require?** Naturalness is a separate outcome.

This is a protocol proposal for the new lifecycle suite, not results or a claim
of preregistration for the old pilot. Calibrate caller reliability and call limits
on development cases, then freeze the protocol and a dated manifest before the
evaluation batch. Keep the original pilot and any calibration runs separately.

## What the current evidence establishes

The [September 12 pilot](PILOT.md) contains two comparable phone calls: one per
target, same task, caller model, seed, phone number, host, language and two-minute
limit. GPT-Live failed to save before the cutoff. Gemini saved the wrong surname.
Both fail saved-state checks. Conversation success remains unreviewed.

That setup controls several confounders. It does not establish a ranking: one
caller model, one case, one run per target, fixed target order, incomplete cost
reconciliation, unreviewed audio and a disclosed post-pilot grader amendment.
The 82 earlier regression tests verified code; they were not 82 AI phone calls.
The new scripted lifecycle demos likewise validate software, not model quality.

## Unit of comparison

Compare `gemini-3.1-flash-live-preview` against `gpt-live-1` **plus the declared
`gpt-5.6-terra` reasoning backend**. Report all model IDs, voices, API/SDK versions,
settings and timestamps. Record resolved model snapshots where available; aliases
can change. Do not describe GPT-Live's backend as free or optional in this tested
configuration.

Use one business specification and equivalent permissions. Render it into each
provider's intended prompt structure. GPT-Live separates voice behavior from
backend procedures. Google's current documentation describes synchronous tool
calling for Gemini 3.1 Flash Live. Preserve these native capabilities and measure
their consequences rather than implementing a different product secretly for
one target. Sources: [GPT-Live evaluation guide](https://developers.openai.com/cookbook/examples/audio/voice_agent_evaluation),
[Gemini Live tools](https://ai.google.dev/gemini-api/docs/live-api/tools).

Allow equal development time and tuning budgets on development cases; freeze
prompts before held-out evaluation. Match the task information, not literal prompt
bytes when the architectures require different prompt locations.

## Matched design

Within each pair, hold fixed: scenario and fixture, caller model and prompt,
language and persona, tool schemas, injected failures and delays, transport,
number, host/region, codec/audio processing, call limit and grading version.
Run pairs serially on the dedicated route. Alternate and randomize which target
runs first to reduce time-of-day and warm-up bias. Declare warm-up policy.

Use two caller strata: Gemini calls both targets, then GPT-Live calls both targets
in separate matched pairs. Comparing Gemini→GPT with GPT→Gemini alone changes
the caller and target simultaneously. Seeded agendas do not make generated speech
identical. Report caller-by-target results before combining strata; add a held-out
human or fixed-recording subset when possible.

The starter plan is **8 cases × 5 repetitions × 2 targets × 2 caller models =
160 calls per language**. This is a feasibility-sized experiment, not a power
guarantee. Five runs per case/caller condition give wide uncertainty. Use effect
sizes and interval widths to decide the size of a later confirmatory study.

```sh
uv run python -m voicelab.simulations plan --language ro --repetitions 5 \
  --output runs/proposed-study.json
```

This generates balanced paired assignments and hashes of fixture, caller prompt,
business specification, schemas and simulation source. It makes no calls. It is
not a budget authorization or an invoice estimate. Finish recording deployment
configuration and approve a batch allowance before executing it. The earlier
EUR 25 session allowance does not authorize this whole study.

Run English as a separate language condition. Add slow tools, audio noise and
timed interruption as separately specified conditions, not randomly mixed factors
in the baseline. If changing a model or prompt, change one tested factor at a time.

## Measurements and adjudication

| Outcome | Evidence and rule |
| --- | --- |
| Complete task success | Correct final state AND mandatory lifecycle/policy checks AND verified caller adherence, consent and truthful spoken outcome |
| Entity correctness | Names, quantities, dates, address and unchanged fields; declared normalization only |
| Action correctness | Correct order reference, correct create/update/cancel sequence, no duplicate or unauthorized action |
| Recovery | State after tool failure, retries, duplicate prevention, and whether the caller receives a truthful explanation |
| Time to completion | From the declared task start until its final verified outcome is communicated; report unresolved/cutoff calls separately |
| First audible response | End of eligible caller speech to first audible response; acknowledgements are labeled |
| Substantive response | End of the request to an answer that advances it, separate from a filler acknowledgement |
| Tool waiting | Tool durations plus caller-experienced silence while work is pending |
| Interruption handling | Controlled caller onset to agent yield, plus whether the corrected request reaches state |
| Cost | Target voice, reasoning backend, carrier/SIP/media and hosting; caller/judge costs shown separately |
| Naturalness | Blind listener rubric for intelligibility, pacing and conversational quality |

The sandbox can establish writes and stock changes. An agent-supplied confirmation
flag cannot establish spoken consent. A text judge cannot establish audio overlap.
Use deterministic checks for state and actions, aligned recordings for timing,
and independent conversational review for caller adherence and spoken claims.

LLM judges can triage semantic issues. Hide provider labels, use an explicit rubric,
check agreement with humans, and retain disagreements. Do not let an LLM's general
positive impression override a failed required state assertion. Review all critical
failures and a random sample of successes; inspect possible grader failures.

Carrier dual-channel audio supplies one clock for audible timings. Validate channel
orientation, annotate semantic boundaries on a sample and assess segmentation
error. Current RMS gaps are diagnostics until validated. Report response rates
alongside latency so ignoring difficult questions cannot make a system look fast.
Declare how silence, overlap, unanswered requests and closing farewells are scored.

## Analysis and reporting

Retain every attempt with a stable ID, including timeouts, invalid callers,
transport failures and missing evidence. Distinguish system failures from
infrastructure and grader problems. Show both attempted-run reliability and
task success among evaluable runs, with exclusion reasons and counts. Never
silently drop a failed run or retry until a model passes.

Report each case, language and caller stratum with denominators. Report paired
success differences with uncertainty intervals; preserve pair membership when
resampling. Account for repeated turns within calls instead of treating them
as independent experiments. Show latency distributions with explicit units of
aggregation, and cost per attempted call and per successful task. Keep missing
prices unknown. Do not choose a winner from a small mean difference or combine
unrelated dimensions into an unexplained single score.

Release versioned fixtures, tools, protocol, prompts/settings, grader source,
paired run manifest and anonymized per-call evidence. Include representative
failures, uncertainty, known measurement bugs, and all post-hoc changes. Publish
consented redacted recordings or clear evidence limitations. Raw production data
and account identifiers remain outside the repository.

## Contribution to the community

AI caller evaluation already exists. OpenAI provides controlled audio, recorded
audio and multi-turn caller harnesses; LiveKit provides agent testing utilities.
Our useful contribution is a portable set of business environments and assertions,
cross-provider comparisons on real phone paths, and inspectable failure evidence.
Sources: [OpenAI's harness guidance](https://developers.openai.com/cookbook/examples/audio/voice_agent_evaluation),
[LiveKit testing](https://docs.livekit.io/agents/start/testing/).

Build reusable pieces: caller agendas, tool adapters, isolated business state,
fault injection, evidence collection and graders. Let teams contribute a synthetic
version of a real production failure and rerun it when their model, prompt or tools
change. Broader observability can reuse the same event vocabulary in production,
but the current framework does not certify enterprise readiness.
