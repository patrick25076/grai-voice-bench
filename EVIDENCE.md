# Inspect, review and export evidence

The phone runner records evidence; it does not establish a model leaderboard.
Use the exact worker source version recorded in each call when replaying tools.

For the completed study's setup and failure questions, read [FAILURE-AUDIT.md](FAILURE-AUDIT.md).
`explain.py` inspects captured native declarations and generates a diagnostic
addendum anchored to the input data hash. It does not regrade calls or infer a
model-only cause. Its common-contract comparison explicitly excludes the
documented `additionalProperties`/`propertyOrdering` transport differences.

```sh
uv run python offline_analysis.py runs/study60
uv run python usage_audit.py runs/study60/P01-1/agent-evidence.json
```

`offline_analysis.py` replays every captured sandbox event and compares the
before/after state, tool result, final state and deterministic grade. It also
checks native usage against the SDK snapshot and writes original-level acoustic
diagnostics to `analysis/offline-audit.json`. The audit never places calls,
changes real business records, fills personal ratings or validates audio by
inference. A matching replay means the trace is internally reproducible, not
that the model behaved correctly.

For GPT-Live, voice time comes from one final usage snapshot per session; backend
response usage is deduplicated by response ID. For Gemini, native per-response
usage is compared to the adapter counters. This checks capture, not independent
invoice semantics. Missing modality categories and services remain unknown.

Review each call against its assigned agenda, target/caller native transcripts,
independent per-channel ASR and saved state. Keep an `assessment.json` beside the
recording. The study's assistant review uses `caller_fidelity`, `spoken_truth`
and `spoken_consent` values `pass`, `fail`, `unclear` or `not_applicable`, plus
`reviewer`, `reviewed_at`, `method`, `notes`, `attribution`, and
`human_audio_verified: false`. Do not call transcript review human listening.

The assessment's `reviewed_content_sha256` is generated with
`publish_study.reviewed_content_hash(target_extra, caller_extra, asr_transcriptions,
secondary_transcriptions)` when supplemental ASR is included.
The ASR argument contains channel 0 then channel 1's `transcription` objects.
This anchors the assessment to the content reviewed; changed transcripts or
tool state require review again. Patrick's personal ratings stay in the separate
local review application's `votes.json` and are not invented by an assistant.

Use these gates consistently and retain the explanation, not only the label:

- **Caller fidelity:** did the caller preserve the supplied business facts and
  follow the required sequence? A wrong callback number, invented address, early
  amendment, or hangup before the required result can invalidate that scenario.
  A target refusal can affect caller behavior; this gate is not independent of
  the target under test.
- **Spoken truth:** do the agent's audible claims match the available tools and
  their results? A saved follow-up is not a changed order or a verified outbound
  notification. Leave ambiguous names, digits, currency and cut-off speech
  unclear when the available transcript sources do not resolve them.
- **Spoken consent:** was the required readback and agreement obtained before
  each committed create, amendment or cancellation? The model's own
  `confirmed: true` argument is not evidence of a caller's permission. No
  committed write can be marked not applicable while a blocked attempted write
  remains visible in the separate policy result.

The deterministic state grade also checks exact action sequence and message
count. A redundant update before a correct cancellation or a second contact
note after a correct follow-up can fail those strict rules. Inspect the failed
assertion and final business state before describing a customer-facing failure.
Do not turn a post-hoc subset of compliant callers into an unbiased model ranking.

```sh
uv run python publish_study.py --manifest runs/manifest-frozen.json \
  --runs runs/study60 --output exports/draft-1 --draft
uv run python -m http.server 8784 --bind 127.0.0.1 --directory exports/draft-1
```

The static viewer includes recordings, caller agendas, transcripts, tool-event
state transitions, assessments, costs and diagnostics. It shows model names;
use the separate local review application for personal scores before revealing
labels. `trials.csv` provides flat outcomes and cost components, `data.json`
contains the evidence selections, and `SHA256SUMS.json` hashes the exported files.

Omit `--draft` only after every scheduled call has a recording, both role files,
ASR, a current matching replay audit and a current assessment. The exporter uses
an explicit field allowlist and neutral WAV filenames. It never copies raw
provider events, account routing, credentials or private voting files. Inspect
the synthetic transcripts and recording provenance before publication.

The 60-call report is a specific experiment. Provider configuration, caller
behavior, strict grader choices and acoustic uncertainty constrain what it can
establish. State success, blocked attempts, spoken truth, human-verified latency,
known cost components and personal opinion must stay separate.

## Declared scoring correction

`grade_errata.py` applies `empty-stock-order-reference-v1`, identified from the
ninth evaluation call. An empty optional `order_id` on a stock follow-up and an
absent reference both identify no order. The frozen grader incorrectly treated
them differently. The correction was introduced after evaluation started and
is applied to both models; original grades and transcripts are never overwritten.
It does not relax quantity, message count, stock, ownership or policy assertions.
The report shows both versions. This is a declared correction, not a new call,
prompt change, hidden exclusion or claim of fully prespecified revised scoring.

The separate rule requiring one follow-up message remains unchanged. A second
contact-detail message can therefore fail that strict rule even when the main
amendment request exists; the per-call assessment explains what happened.

## Exact frozen source

For byte-level replay, use the `frozen-source-v0.4.0.zip` asset attached to
[v0.4.0](https://github.com/patrick25076/grai-voice-bench/releases/tag/v0.4.0).
Git checkouts can normalize line endings. The archive preserves the original
bytes and all 17 frozen runtime/runner hashes. It was packaged during evaluation
without changing those files; its historical README describes the pre-study
state. Later assessment tools and reports are separate from the frozen runtime.

## Supplemental transcription for all 60 calls

After primary Whisper ASR omitted much of a Romanian call and repeated unrelated
text, the review added `gpt-transcribe` for both channels of every study recording.
This was a post-start analysis change, applied to all target arms rather than only
selected outcomes. Original Whisper results and raw recordings are retained.

```sh
uv run python secondary_asr.py --manifest runs/manifest-frozen.json \
  --runs runs/study60 --env .env
```

It reuses the exact primary per-channel audio files without gain or speed changes,
provides no expected transcript or order facts, stores source/input hashes, and
uses exclusive request markers to prevent accidental paid retries. Supplemental
ASR remains machine evidence, not a human listening judgment. Assessments must
explicitly include the new evidence before their content hashes are refreshed.
The completed study export requires both supplemental channels for every call.
Whisper and gpt-transcribe are both OpenAI systems, so their transcription errors
may be correlated even when the two outputs agree.

The report retains input-duration estimates in raw ASR envelopes and uses the
supplemental API's reported duration when available for its cost estimate.
The dated list price is $0.0045 per minute, checked 2026-09-13 in the
[official pricing documentation](https://developers.openai.com/api/docs/pricing).
ASR totals include both passes. These estimates are not final invoices.
