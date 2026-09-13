# GRAI Labs launch drafts

Drafts only. No posts have been sent.

## X: 60-call evidence release

We ran 60 real phone calls: 50 English, 10 Romanian. Gemini Live and GPT-Live,
stateful mock tools, recordings and inspectable outcomes. Did the agent actually
do what it said? The framework and evidence are open:
https://github.com/patrick25076/grai-voice-bench

## X: why inspect the tools

One sample claimed a follow-up was saved, but no message existed. Others reached
the right final state while skipping confirmation. We published all 60 calls,
tool traces and assessment limits so these failures can be examined and retested:
https://patrick25076.github.io/grai-voice-bench/

These drafts describe the observed study, not a universal model ranking. The
release keeps original scores, a declared grading correction and caller failures
visible. Personal listening scores and validated latency remain pending.

## X: initial release

We're open-sourcing GRAI Voice Bench: AI callers testing Gemini Live and
GPT-Live on real phone tasks. Six reusable scenarios, shared mock tools, call
recordings, usage capture and saved-state checks. First pilot and its limits:
https://github.com/patrick25076/grai-voice-bench

## X: what the pilot taught us

Our first paired phone test: Gemini saved an order with the wrong surname.
GPT-Live reached confirmation but didn't save within 2 minutes. Two calls
aren't a leaderboard. They're a reason to inspect what the agent actually
writes. Code + report: https://github.com/patrick25076/grai-voice-bench

## X: invite contributors

Building voice agents? We're looking for reproducible failures: lost names,
missed constraints, bad confirmations, awkward interruptions. GRAI Voice Bench
turns phone tasks into reusable tests. Bring a synthetic scenario or help review
the measurements: https://github.com/patrick25076/grai-voice-bench

## Who this helps first

Engineers and technical founders deploying phone agents for appointments,
orders, or customer support. The immediate problem is verifying that a spoken
conversation produces the correct business action across model and prompt
changes. Model voice quality alone does not answer that question.

For customer discovery, ask about their most recent failed call: what the caller
said, what the agent saved, how they found the error, and how they reproduce it
before a release. Then ask whether they can contribute an anonymized synthetic
version and what evidence would let them approve a model change. Avoid treating
interest in the repository as proof that they will buy an observability product.
