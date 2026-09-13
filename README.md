# GRAI Labs: 60 recorded voice-agent tests

Completed collection: **50 English and 10 Romanian calls**, 30 matched pairs.
Gemini 3.1 Flash Live / Puck and GPT-Live-1 / marin plus GPT-5.6-Terra each
answered 30 calls. All records and business tools are synthetic.

- [Read the results and limitations](REPORT.md).
- [Open the hosted evidence viewer](https://patrick25076.github.io/grai-voice-bench/).
- [Download and cite this version](https://github.com/patrick25076/grai-voice-bench/releases/tag/study60-v1).
- [Reuse the framework](https://github.com/patrick25076/grai-voice-bench).

For a local copy, unzip this dataset, run `python -m http.server 8784 --bind
127.0.0.1` from its directory and open http://127.0.0.1:8784/. Opening index.html
as a file may prevent the browser from loading data.json.

`audio/` contains original stereo WAVs, unchanged in volume and speed. Channel 0
is the simulated caller; channel 1 is the answering agent. `data.json` contains
per-call tool-state evidence, native transcripts, both transcription passes,
assessments and known cost components. `trials.csv` is the flat comparison table.
`frozen-study-public.json` is the pre-evaluation public protocol. `SHA256SUMS.json`
hashes every other dataset file. The separate source ZIP preserves the analysis
source bytes whose hashes are recorded in data.json.

State checks include strict lifecycle and message-count rules. Original scores
and the one declared scoring correction are both retained. Caller deviations,
ASR disagreements and skipped confirmations remain visible. This is exploratory
configured-system evidence, not a human-validated model leaderboard.

Patrick's personal ratings are pending and are not part of this release. The
framework's separate local review app records those ratings before revealing
labels, with revision history and audio hashes. Energy-gap diagnostics are not
human-validated response latency. Known USD components are not full invoices.
Seven development calls are excluded from this evaluation dataset.

Suggested citation: GRAI Labs (2026), *GRAI Labs 60-call telephone study: Gemini
3.1 Flash Live and GPT-Live-1*, study60-v1, GitHub release linked above. Include
the report's limitations and file hashes when reusing numerical results.

MIT licensed; see LICENSE. Account routing, credentials and personal votes are
excluded from this explicitly selected synthetic evidence package.
