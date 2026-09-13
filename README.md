# GRAI Voice Bench

Test whether a speech-to-speech agent completes a real phone task, what the
caller hears while it works, and what each part costs. This release compares
`gemini-3.1-flash-live-preview` with `gpt-live-1` plus a declared Responses
backend. These are system configurations, including their provider runtimes.

**The 60-call study is collected and assessed:** 50 English and 10 Romanian
calls, with 30 calls per answering system. [Listen and inspect the evidence](https://patrick25076.github.io/grai-voice-bench/),
[read the results](STUDY-RESULTS.md), or [download the versioned dataset](https://github.com/patrick25076/grai-voice-bench/releases/tag/study60-v1).
Every call includes original audio, sandbox actions and before/after state,
deterministic grades and provisional transcript-assisted assessments.

Start with the [failure audit](FAILURE-AUDIT.md) to understand S027's correct order
after a blocked attempt and S033's skipped, available lookup tool. The viewer now
includes captured native tool declarations and prompts, plus direct sample links.
The addendum preserves all original recordings and scores. See the
[framework direction and existing alternatives](FRAMEWORK-DIRECTION.md) for what
is implemented and what remains planned, including browser and Telnyx transports.

This remains an experimental phone-testing framework. Personal listening scores,
human-validated response latency and full invoices are pending. Caller deviations,
strict grader limitations and one declared scoring correction are visible; raw
state scores are not a model leaderboard. The earlier [two-call pilot](PILOT.md)
is separate. New calls require your own model, LiveKit and Twilio accounts.

The [60-call study protocol](STUDY-60.md) adds 50 English and 10 Romanian calls,
native tool-schema checks, recorded provider configuration/usage, a frozen batch
runner and a local listening page with durable personal ratings. Its assignments
and runtime hashes were published before evaluation in
[v0.4.0](https://github.com/patrick25076/grai-voice-bench/releases/tag/v0.4.0).
The completed evidence release is `study60-v1`; its original and supplemental
transcripts are machine evidence, with human listening verification still pending.

The new [simulation component](SIMULATIONS.md) adds eight order-lifecycle cases:
create, amend, change address, cancel, escalate an older order, handle a shortage,
recover an uncertain save, and avoid ordering without consent. Tools execute in
fresh in-memory business environments with before/after evidence. These additions
were tested offline and exercised by the completed phone study.

September 13 calibration found and corrected a caller-agenda ambiguity and a
recovery-grader restriction before evaluation. It also verified native tool
exposure, a common call-ending rule, and incoming-trunk cost collection. The
development recordings remain separate from the 60-call study. See
[the protocol](STUDY-60.md) for exact controls and known transcription limitations.

```sh
uv sync --locked
uv run python -m voicelab.simulations demo --output runs/simulation-demo
```

Open `runs/simulation-demo/index.html` to inspect the sandbox and its grader.
This demo uses scripted tool traces, not AI calls. See the [study proposal](STUDY.md)
for the paired Gemini/GPT design and proposed call matrix.

## Six cases

These are the original pilot cases. The new study uses the eight lifecycle
cases in [SIMULATIONS.md](SIMULATIONS.md).

| Case               | What it tests                                       |
| ------------------ | --------------------------------------------------- |
| after-work         | Find and book an appointment after 17:00            |
| spell-my-name      | Preserve a spelled surname and a morning constraint |
| not-tuesday        | Respond when a hidden scheduling conflict emerges   |
| loading-dock       | Record an order that arrives before the dock closes |
| exact-quantity     | Capture 200 kg without losing the quantity          |
| check-before-order | Answer a stock question before recording an order   |

Clinic cases are English; order cases support English and Romanian. All
business records are fictional and in memory. Seeds reproduce setup, not
model speech. The reference calendar is Monday, 14 September 2026.

## Architecture and reuse

`worker.py` selects either provider using one LiveKit `AgentSession` transport.
`benchmark_support.py` adapts one tool registry into SDK function tools. Both
providers receive fresh identical mock state. GPT-Live receives a short voice
prompt and a separate procedural backend prompt. The caller has no business
tools or grader access.

`phone.py` connects the caller over SIP, then Twilio dials the target telephone
number. The target returns through the dedicated inbound SIP trunk. The Dial
recording has two channels on one carrier clock. This is a real PSTN leg, not
the in-process audio loop. Both arms must use the same target number, host,
caller provider, seed, case, language, and duration within a matched comparison.

## Run

Use Python 3.12 or 3.13 and `uv sync --locked`. Copy `.env.example` to `.env`
and fill your own credentials. Set `BENCH_CONTROL_TOKEN` to a long random value
shared by the runner and worker. The included phone runner targets Twilio IE1
(Dublin); its API token must belong to that region. Model access is also required
for the exact model IDs in `worker.py` and `.env.example`.

Run the checks without credentials or calls:

```sh
uv run python test_benchmark_support.py
uv run python test_runner.py
uv run python test_simulations.py
```

Create a dedicated LiveKit inbound SIP trunk
and a dispatch rule that selects the worker by `VOICELAB_AGENT_NAME`. Route an
owned test number to that trunk. Start the worker with `uv run worker.py start`
or deploy the Dockerfile. A self-hosted worker also works.

For Twilio **Elastic SIP Trunking**, configure the inbound LiveKit trunk with
Twilio's signaling-IP allowlist. Twilio origination does not support digest
authentication, although Programmable Voice SIP calls support it. The included
`lk/configure_twilio_inbound.py` applies the documented IP list only to an
explicitly supplied dedicated trunk and saves a private rollback first.

```sh
uv run python phone.py --target YOUR_TEST_NUMBER --caller-id YOUR_OWNED_CALLER_ID \
  --sip-host YOUR_LIVEKIT_SIP_HOST --trunk YOUR_DEDICATED_TRUNK \
  --rule YOUR_DEDICATED_RULE --agent grai-bench \
  --provider gemini --caller-provider gemini --scenario loading-dock \
  --language ro --seed 41 --seconds 120 --output runs/pair01-gemini \
  --ledger runs/budget.json --cap-eur 20 --reserve-eur 3
```

Repeat with `--provider gptlive` and a fresh output directory. Randomize arm
order across subsequent pairs. Use a second caller provider as a separate
stratum; do not swap the caller only when you swap the target.

The runner temporarily changes only the supplied dedicated trunk and rule,
stores private rollback snapshots, restores their previous state, and caps
call duration. It reserves a conservative amount before each call. This ledger
is a local spending allowance, not a provider-enforced billing cap. Leave a
hosting reserve and reconcile all provider charges before another batch.

Run calls serially and use one ledger for the entire batch. Its local lock is
held through routing restoration; it does not coordinate separate machines or
different ledgers. A process kill can leave a lock and modified routing. Inspect
the carrier and restore the saved trunk/rule snapshots before removing a stale
lock. Any `cleanup_errors` in `run.json` also require routing inspection.

Keep the worker running until its shutdown callbacks write `scorecards/*.json`.
For manual calls with no scenario metadata, benchmark mode defaults to the
Romanian mock order assistant. No orders are persisted to a real business.

## Evidence and claims

Each run retains carrier call IDs, routing configuration, recordings and
available carrier prices. The worker emits `BENCH_RESULT` JSON with the
declared models, tools, outcomes, usage events, errors and SDK event timings.
Missing usage or prices remain null. Count both caller and target models,
GPT-Live's Responses backend, all carrier legs (outbound SIP, PSTN and the
inbound target trunk), recordings, SIP/media and hosting.
Do not report the caller's cost as the target's cost.

Download the worker scorecards into `runs/worker-scorecards/`, then run
`uv run python collect.py runs` to join them to call IDs and estimate known
model-cost components from the dated rate table. Run
`uv run python report.py runs --caller-channel 0` for the local listening page.
Check channel orientation by ear. These files are private review artifacts;
public evidence needs a separate export with account identifiers removed.
Use `uv run python reconcile.py runs --env .env.twilio` to refresh
carrier prices after settlement. This reads the calls already saved in `runs`.

The database grader checks writes, captured entities and hard constraints.
`overall_pass` remains null until a reviewer checks caller fidelity, the spoken
claim, and the caller's confirmation against the recording. Keep failed and
timed-out calls in the denominator. Report caller failures separately.

Audio response gaps use energy segmentation with a disclosed 400 ms merge
threshold. They are proxies, not validated semantic turn boundaries. SDK
"speaking" events are a different metric. Physical noise, reliable timed
barge-in, blind listening scores and broad statistical conclusions require
additional work. Prompting a model to sound as if it is in a noisy room does
not test noise robustness.

Use `uv run python offline_analysis.py runs/study60` to replay recorded sandbox
transitions and compare native provider usage to SDK counters. This makes no
model or phone calls and uses the exact recorded worker source. It detects
changed state, results and grades; it cannot verify spoken consent. See
[evidence export and review](EVIDENCE.md) for the static viewer, CSV and hashes.

Small pilot samples support engineering observations, not a model leaderboard.
Publish raw anonymized evidence and per-call results before aggregate claims.
Never publish `.env*`, rollback snapshots, account IDs or personal phone data.

## Source contracts

- [GPT-Live WebSockets](https://developers.openai.com/api/docs/guides/voice-websockets?api=live)
- [GPT-Live delegation and tools](https://developers.openai.com/api/docs/guides/live-delegation)
- [Gemini Live API](https://ai.google.dev/gemini-api/docs/live)
- [Twilio call resource](https://www.twilio.com/docs/voice/api/call-resource)
- [Twilio Dial and dual-channel recordings](https://www.twilio.com/docs/voice/twiml/dial)
- [LiveKit inbound trunk authentication](https://docs.livekit.io/telephony/accepting-calls/inbound-trunk/)
- [Twilio signaling IP addresses](https://www.twilio.com/docs/sip-trunking/ip-addresses)

MIT licensed. This staged package is the release boundary; it excludes the
rest of the GRAI monorepo and production tenant configurations.

See [CONTRIBUTING.md](CONTRIBUTING.md) for useful contributions and
[LAUNCH-DRAFTS.md](LAUNCH-DRAFTS.md) for draft GRAI Labs posts.
