# Timing and personal listening addendum

Analysis version: `study60-timing-listening-v1`, 2026-09-13. This is post-hoc
analysis of the original 60 recordings, not another experimental run.

Public report: https://grailabs.ai/benchmarks/gptvsgemini

## Results and their scope

| Measure | Gemini 3.1 Flash Live | GPT-Live 1 + Terra |
|---|---:|---:|
| Original strict saved-state passes | 24/30 | 18/30 |
| Saved-state passes after declared optional-reference erratum | 24/30 | 20/30 |
| Calls without a prohibited-attempt flag | 23/30 | 30/30 |
| Median of per-call detected non-overlap speech-gap medians | 1.976 s | 1.856 s |
| Paired speech chunks contributing to that metric | 125 | 181 |
| Overlapping chunks, reported separately | 6 | 25 |
| Unpaired caller chunks, reported separately | 42 | 40 |
| Median full recording duration | 99.580 s | 157.360 s |
| Median first-to-last detected speech span | 92.304 s | 119.520 s |
| Patrick's mean overall listening score (1–5) | 4.00, n=5 | 3.25, n=8 |
| Patrick's mean naturalness score | 4.00, n=5 | 3.375, n=8 |

The five pairs with both overall ratings contain three Gemini preferences and
two ties. The other three reviews are unpaired. Ratings use the actual study
labels and matching audio SHA-256, never the reviewer's provider guess. All 13
latest submitted reviews are included. No unrated score is imputed. The two
written notes and explicit speech judgments remain separate from automated
grades. Patrick is the builder, not an independent blinded panel; recognizable
voices, prior knowledge, self-selection and partial coverage limit inference.
There are six rated Romanian calls (three per arm), only ten Romanian calls
in the full study, and no third language. General multilingual superiority
is not established.

## The new timing measurement

`timing.py` runs the same pinned Silero ONNX model on each original PCM16
recording channel. Caller is channel 0, target is channel 1 in this dataset.
The recordings share one sample clock. There is no gain normalization,
resampling, speed change or leading trim.

The detector uses 32 ms frames, .5 onset/.35 offset hysteresis, 96 ms minimum
speech, no boundary padding, and 400 ms silence to confirm a chunk boundary.
The boundary is timestamped at the start of the silence; the confirmation
hold is not added to the gap. Trailing candidate silence is not counted as
speech at end of file. Recurrent state is reset for every channel and file.

Each detected caller chunk is retained as an opportunity:

1. If target speech crosses the caller endpoint, classify overlap separately.
   Overlap is not automatically a useful answer or zero latency.
2. Otherwise pair the first target speech onset at or after the caller endpoint
   and before the next caller chunk. Gap = onset minus endpoint.
3. Otherwise mark the chunk unpaired. This can mean the caller continued;
   it does not establish an unanswered question or failed call.

Primary aggregate: median of the 30 per-call gap medians in each arm. Pooled
chunk distributions are also provided separately: Gemini p50/p95 =
2.080/2.816 s (125 chunks), GPT = 1.824/2.496 s (181 chunks). p95 uses the
nearest-rank definition. A 250 or 700 ms silence setting gives a median of
per-call medians of 1.976 s Gemini and 1.840 s GPT. These are sensitivity checks
using the same model probabilities, not alternate headline selections.

These are **automated speech-gap measurements**, not human-verified semantic
turn latency or pure model latency. VAD may miss soft speech or detect noise.
Speech onset can be an acknowledgment rather than a substantive answer.
Phone transport/buffering is included. There are **zero human-verified timing
boundaries** in the submitted reviews. Time to substantive answer and time from
caller confirmation to audible saved-order confirmation remain unavailable.
The older fixed-energy gap diagnostics are retained in the original dataset;
the new analysis does not retroactively rename them as validated latency.

Full recording duration includes the 180-second cap and delayed hangup. The
frozen farewell fallback missed some “bye” endings when callers omitted their
finish tool. First-to-last detected speech span removes detected opening/tail
silence but includes internal pauses. Neither duration measures time to
successful completion; unfinished calls remain in the analysis. Differences
between medians must not be treated as a causal decomposition of delay.

## GPT backend diagnostic

Native GPT response-created/completed events were captured on the same
monotonic receipt clock. Across 30 target calls, 213 completed backend responses
have a pooled median of 1.368 s and p95 of 2.642 s. The median of per-call
backend medians is 1.345 s. Captured responses use `gpt-5.6-terra`, reasoning
`medium`, service tier `auto`.

A response can end with tool requests; one delegation can contain multiple
responses and continuations. The voice model can speak during backend work.
These intervals are neither whole-delegation duration nor caller silence, and
must not be added to recording gaps. There is no equivalent Gemini backend
trace captured here. Missing or unclosed events stay separate, not zero.
No latency-optimized configuration was tested. Configuration, prompts, model
behavior and caller behavior cannot be causally separated from this pilot.

Mock tool handler medians are 0.459 ms Gemini (69 executions), 0.336 ms GPT
(105 executions). They measure only local mock code, including blocked/error
results, excluding reasoning, transport, and spoken acknowledgment. They do
not substantiate a production integration latency claim.

## Reproduce recording timing locally

Install the optional analysis dependencies after the repository's normal setup:

```sh
uv pip install -r requirements-timing.txt
```

Download Silero's model at the pinned commit below. Verify its SHA-256 before
running; `timing.py` also checks the exact expected digest.

```sh
curl -L 'https://raw.githubusercontent.com/snakers4/silero-vad/867c2aa692646a1f1de3e94a15c9dd9f614c0acb/src/silero_vad/data/silero_vad.onnx' -o silero_vad.onnx
uv run --no-sync python timing.py S027.wav --vad-model silero_vad.onnx \
  --caller-channel 0 --output S027-timing.json
uv run --no-sync python test_timing.py
```

Model SHA-256:
`1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3`.
Silero commit: `867c2aa692646a1f1de3e94a15c9dd9f614c0acb`.
Runtime used: Python 3.12, numpy 2.2.6, onnxruntime 1.22.1, CPU, one intra-op
and one inter-op thread. MIT attribution is in `SILERO-LICENSE`.

Each call's downloadable analysis includes recording SHA-256, speech intervals,
all candidate gaps and exclusions, settings, source fingerprints and timings.
Display waveform peaks have no role in the measurement. The original public
dataset and recordings are unchanged. Native source envelopes remain private;
the addendum exports selected timing/configuration fields without account IDs.

## Sources and artifacts

- [Original dataset and citation](https://github.com/patrick25076/grai-voice-bench/releases/tag/study60-v1)
- [Failure and tool-exposure audit](https://github.com/patrick25076/grai-voice-bench/releases/tag/study60-audit-v1)
- [Timing and listening JSON](https://grailabs.ai/benchmarks/gptvsgemini/analysis.json)
- [Latest saved personal reviews](https://grailabs.ai/benchmarks/gptvsgemini/listening-ratings.json)
- [Silero model and implementation](https://github.com/snakers4/silero-vad/tree/867c2aa692646a1f1de3e94a15c9dd9f614c0acb)
- [OpenAI delegation guidance](https://developers.openai.com/api/docs/guides/live-delegation)
- [Speko's separate speech-to-speech benchmark](https://benchmarks.speko.ai/s2s)

The report is a pilot comparison of configurations, not a universal model
winner or a numerical replication of Speko's provider-direct test.
