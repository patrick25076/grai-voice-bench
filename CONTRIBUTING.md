# Contributing

Useful first contributions are synthetic tasks with clear expected state,
offline regression checks, provider usage reconciliation, and reviewed audio
turn annotations. Run `uv sync --locked`, `uv run python test_benchmark_support.py`
and `uv run python test_runner.py` before a pull request. CI makes no paid calls.

A new scenario needs a fictional caller identity, explicit facts, feasible
business tools and constraints, and a saved-state grader. Keep the caller
separate from the tool registry and grading results. Mark behavior that needs
listening review as unreviewed. Add case-specific disclosure or sequence checks
when the difference cannot be established from final state alone.

For a new provider, connect it through the shared worker and tool adapter;
declare model IDs, prompt differences, codecs, settings, usage semantics and
hosting. Compare with a fixed caller configuration before adding caller strata.
Capture missing data explicitly and preserve failed attempts.

Use synthetic data in issues and PRs. Raw recordings, transcripts, account
identifiers and environment files belong outside the public repository unless
a separate anonymized evidence release has been reviewed. The included MIT
license covers this repository, not provider services or dependencies.
