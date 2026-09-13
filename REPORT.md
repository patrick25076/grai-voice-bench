# GRAI Labs: 60-call telephone study

Status: completed_exploratory_evidence_with_listening_pending. 60/60 recordings.

[Listen and inspect the calls](https://patrick25076.github.io/grai-voice-bench/) or [download the versioned dataset](https://github.com/patrick25076/grai-voice-bench/releases/tag/study60-v1).

Evaluation software: [v0.4.0](https://github.com/patrick25076/grai-voice-bench/tree/v0.4.0).
Analysis software: [study60-v1](https://github.com/patrick25076/grai-voice-bench/tree/study60-v1); [exact analysis source bytes](https://github.com/patrick25076/grai-voice-bench/releases/download/study60-v1/grai-voice-bench-study60-v1-source.zip). Per-file analysis hashes are recorded in data.json.
Exact source bytes: [frozen archive](https://github.com/patrick25076/grai-voice-bench/releases/download/v0.4.0/frozen-source-v0.4.0.zip) (SHA-256 `7ec62a4821f5b881409e35e08ce6dfe652d50678a15fef737ae271804a10255c`).
Observed UTC period: 2026-09-12T21:52:55.060048+00:00 to 2026-09-13T00:50:16.504872+00:00 (last evidence collection).
Canonical frozen manifest SHA-256: `96345df49ee889c25c982a68e7d6ef73498bbb5f515415a2507a1c39f4467572`.

## Recorded sandbox outcomes

These are raw deterministic outcomes across all attempts, including caller problems. They include strict action-sequence/cardinality rules, not only final record contents. They are not human-validated success rates.

| Language | Target | Recordings | State pass | State fail | Policy pass | Policy fail | Caller review pass |
|---|---|---:|---:|---:|---:|---:|---:|
| en | gemini | 25 | 21 | 4 | 18 | 7 | 13 |
| en | gptlive | 25 | 16 | 9 | 25 | 0 | 10 |
| ro | gemini | 5 | 3 | 2 | 5 | 0 | 0 |
| ro | gptlive | 5 | 2 | 3 | 5 | 0 | 1 |

## Declared grading erratum

An empty optional stock-request order reference and an absent one both identify no order. The frozen grader distinguished them. The correction below was declared after evaluation began, applies to both targets, and changes only that equivalence. Original scores above and all original traces remain preserved.

| Language | Target | Original state passes | Passes with erratum | Affected calls |
|---|---|---:|---:|---:|
| en | gemini | 21 | 21 | 0 |
| en | gptlive | 16 | 18 | 2 |
| ro | gemini | 3 | 3 | 0 |
| ro | gptlive | 2 | 2 | 0 |

## Outcomes by caller provider

| Language | Caller | Target | State pass | State fail | State unknown |
|---|---|---|---:|---:|---:|
| en | gemini | gemini | 10 | 3 | 0 |
| en | gemini | gptlive | 8 | 5 | 0 |
| en | gptlive | gemini | 11 | 1 | 0 |
| en | gptlive | gptlive | 8 | 4 | 0 |
| ro | gemini | gemini | 1 | 1 | 0 |
| ro | gemini | gptlive | 1 | 1 | 0 |
| ro | gptlive | gemini | 2 | 1 | 0 |
| ro | gptlive | gptlive | 1 | 2 | 0 |

## Outcomes by workflow

| Language | Case | Target | State pass | State fail | State unknown |
|---|---|---|---:|---:|---:|
| en | sim-amend-quantity | gemini | 4 | 0 | 0 |
| en | sim-amend-quantity | gptlive | 2 | 2 | 0 |
| en | sim-cancel-order | gemini | 3 | 0 | 0 |
| en | sim-cancel-order | gptlive | 2 | 1 | 0 |
| en | sim-change-address | gemini | 3 | 0 | 0 |
| en | sim-change-address | gptlive | 2 | 1 | 0 |
| en | sim-create-order | gemini | 3 | 0 | 0 |
| en | sim-create-order | gptlive | 3 | 0 | 0 |
| en | sim-existing-order | gemini | 1 | 2 | 0 |
| en | sim-existing-order | gptlive | 2 | 1 | 0 |
| en | sim-no-consent | gemini | 3 | 0 | 0 |
| en | sim-no-consent | gptlive | 3 | 0 | 0 |
| en | sim-retry-after-timeout | gemini | 2 | 1 | 0 |
| en | sim-retry-after-timeout | gptlive | 2 | 1 | 0 |
| en | sim-stock-shortage | gemini | 2 | 1 | 0 |
| en | sim-stock-shortage | gptlive | 0 | 3 | 0 |
| ro | sim-amend-quantity | gemini | 1 | 0 | 0 |
| ro | sim-amend-quantity | gptlive | 0 | 1 | 0 |
| ro | sim-cancel-order | gemini | 0 | 1 | 0 |
| ro | sim-cancel-order | gptlive | 1 | 0 | 0 |
| ro | sim-change-address | gemini | 1 | 0 | 0 |
| ro | sim-change-address | gptlive | 1 | 0 | 0 |
| ro | sim-create-order | gemini | 1 | 0 | 0 |
| ro | sim-create-order | gptlive | 0 | 1 | 0 |
| ro | sim-retry-after-timeout | gemini | 0 | 1 | 0 |
| ro | sim-retry-after-timeout | gptlive | 0 | 1 | 0 |

## Matched raw state outcomes

All pairs remain in data.json, including caller deviations and unresolved audio.

| Language | Cohort | Both pass | Both fail | Gemini only pass | GPT only pass | Incomplete |
|---|---|---:|---:|---:|---:|---:|
| en | all | 13 | 1 | 8 | 3 | 0 |
| en | both caller transcript reviews pass | 6 | 0 | 0 | 0 | 0 |
| ro | all | 1 | 1 | 2 | 1 | 0 |
| ro | both caller transcript reviews pass | 0 | 0 | 0 | 0 | 0 |

## Known cost components (USD)

These are component estimates and posted carrier charges, not a complete invoice. Target and simulator costs are separate. Unknown modality and unbilled services are not zero. Compare costs with outcomes and duration: early failures and silent hangup tails affect these totals. This is not cost per verified successful task. The approved EUR budget is a spending limit, not an exchange-rate conversion.
ASR includes original Whisper plus supplemental gpt-transcribe. Supplemental estimates use reported API duration when available; raw envelopes retain the original input-duration estimate.

| Language | Target | Calls | Target model | Caller model | Carrier + recording | ASR |
|---|---|---:|---:|---:|---:|---:|
| en | gemini | 25 | 1.1720 (25/25) | 1.4811 (25/25) | 1.3792 (25/25) | 0.7321 (25/25) |
| en | gptlive | 25 | 3.1911 (25/25) | 2.3304 (25/25) | 1.7486 (25/25) | 0.9631 (25/25) |
| ro | gemini | 5 | 0.3030 (5/5) | 0.4547 (5/5) | 0.3473 (5/5) | 0.1925 (5/5) |
| ro | gptlive | 5 | 0.8134 (5/5) | 0.5972 (5/5) | 0.3959 (5/5) | 0.2823 (5/5) |

## Exploratory audio measurements

Each call has equal weight: the gap column is the median of per-call median energy gaps, not a pooled turn statistic. PCM16 RMS threshold 300, 20 ms frames and a 400 ms segment merge were used. Overlapping responses are excluded from gaps; acknowledgments can count as responses. These are not validated semantic response times. Active-frame dBFS is not LUFS or a measure of whispering/speaking speed. Silent hangup tails remain in recording duration and costs. A fixed energy threshold can miss quieter speech and shift detected boundaries differently across voices. Original recordings are unchanged.

| Language | Target | Gap observations | Median call gap (ms) | Median target active dBFS | Median recording duration (s) |
|---|---|---:|---:|---:|---:|
| en | gemini | 25/25 | 2010 | -17.71 | 91.98 |
| en | gptlive | 25/25 | 1800 | -22.74 | 147.50 |
| ro | gemini | 5/5 | 2300 | -18.18 | 134.16 |
| ro | gptlive | 5/5 | 1820 | -19.34 | 179.84 |

## Transcript-assisted checks

These provisional checks compare native text, independent ASR and sandbox evidence. They are assistant assessments, not Patrick's scores or verified human listening. Disputed audible details remain unclear. Readback/consent can fail even when a model sets confirmed=true and the sandbox accepts its write.

| Language | Target | Gate | Pass | Fail | Unclear | Not applicable | Pending |
|---|---|---|---:|---:|---:|---:|---:|
| en | gemini | caller_fidelity | 13 | 10 | 2 | 0 | 0 |
| en | gemini | spoken_truth | 17 | 3 | 5 | 0 | 0 |
| en | gemini | spoken_consent | 13 | 6 | 0 | 6 | 0 |
| en | gptlive | caller_fidelity | 10 | 8 | 7 | 0 | 0 |
| en | gptlive | spoken_truth | 9 | 0 | 16 | 0 | 0 |
| en | gptlive | spoken_consent | 19 | 1 | 1 | 4 | 0 |
| ro | gemini | caller_fidelity | 0 | 5 | 0 | 0 | 0 |
| ro | gemini | spoken_truth | 3 | 0 | 2 | 0 | 0 |
| ro | gemini | spoken_consent | 1 | 4 | 0 | 0 | 0 |
| ro | gptlive | caller_fidelity | 1 | 3 | 1 | 0 | 0 |
| ro | gptlive | spoken_truth | 1 | 0 | 4 | 0 | 0 |
| ro | gptlive | spoken_consent | 3 | 1 | 0 | 1 | 0 |

## Interpretation limits

- Configured systems: Gemini 3.1 Flash Live / Puck versus GPT-Live-1 / marin plus GPT-5.6-Terra. Not equal-compute isolated base models.
- Calibration checked routing, caller agendas, native tool exposure and working examples before freezing. It does not establish that either prompt is optimal or that a failure is independent of prompt and adapter design.
- 60 selected calls, 50 English and 10 Romanian; eight workflows and three seeded personas, not 60 independent scenario families. No universal ranking or significance claim.
- 30 matched pairs share caller provider, agenda, tools and fixture, but generated speech varies. Show caller deviations and acoustic uncertainty; raw state pass is not clean causal attribution.
- Seeds reproduce fixtures and persona selection, not generated speech. Recorded model IDs and source hashes do not freeze provider-side model updates; this is evidence of the observed configurations and dates.
- Caller behavior is affected by the target's responses. The subset with passing caller reviews is a post-hoc diagnostic subset, not an unbiased causal comparison.
- Deterministic state and guardrail checks are separate from transcript-assisted assessment, human audio verification and Patrick's personal preference.
- The Codex assistant's transcript-assisted assessments were made with model labels visible. They are provisional and are not an independent or blinded review panel.
- The state grade includes exact lifecycle and message-count rules. An unnecessary no-op update can fail its required sequence even when the final cancellation is correct. Address normalization can also reject semantically equivalent wording such as adding the Romanian word for number. Read each failed check and the accompanying assessment; these rules were not relaxed after seeing results.
- Whisper and provider transcripts can hallucinate, omit speech or disagree. Original dual-channel audio is retained at unchanged level and speed.
- After major Whisper omissions/repetition were observed, all 60 recordings received a supplemental gpt-transcribe pass on both channels without an expected-text prompt. This post-start analysis addition preserves the original ASR and grades. Agreement between transcribers is supporting machine evidence, not human audio verification.
- Whisper and gpt-transcribe are both OpenAI transcription systems; their errors may be correlated. They were not given the expected order facts or benchmark answers.
- RMS gaps are exploratory acoustic diagnostics, not validated response latency. The fixed energy threshold can miss quieter speech. Receipt timestamps are not audible boundaries. Duration is not speaking speed.
- Known USD cost components are dated estimates/posted carrier charges. Missing token modality, final invoices, media/SIP, hosting, storage, taxes and FX remain unresolved; EUR reservations are not spend.
- Seven development calls are excluded. Evaluation code and assignments were frozen before the first scored call.
- Patrick's personal scores and human-validated complete-task/latency measurements remain pending unless explicitly supplied in a later report.
- The frozen lexical hangup fallback misses bye/bye-bye when the caller omits its finish_call tool. Preserve these silent tails and charges, but do not call them slow target task completion.
- The strict stock-followup grader distinguishes an empty optional order reference from an absent one; the single-message rule also rejects a separate contact note. Per-call assessments disclose these grading limitations rather than treating every strict failure as failure of the customer's business goal.
- A declared post-start erratum treats an empty optional stock-request order reference as absent. It is applied equally to both targets and preserves original scores; it does not relax quantity, message count, stock, order ownership or policy checks.

See data.json for each recording, assignment, transcript, state transition, assessment and cost component. Listen before making a model claim.
