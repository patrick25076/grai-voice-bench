"""The benchmark's tester: callers with hidden ground truth, not scripts.

See `docs/plans/voice-benchmark-plan.md`. The short version is that a test
caller must never be told how the call should end, because a caller told to
accept cannot fail the agent.

Submodules are resolved lazily so that ``python -m voicelab.bench.generate``
does not import `generate` twice and trip runpy's double-import warning.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - these exist for type checkers only
    from .generate import (  # noqa: F401
        GeneratedCall,
        PromptLeak,
        assert_no_leakage,
        generate,
    )
    from .world import (  # noqa: F401
        CallerBehavior,
        CallerWorld,
        Constraint,
        Disclosure,
        Identity,
        Need,
        Rubric,
    )

_EXPORTS = {
    "GeneratedCall": "generate",
    "PromptLeak": "generate",
    "assert_no_leakage": "generate",
    "generate": "generate",
    "CallerBehavior": "world",
    "CallerWorld": "world",
    "Constraint": "world",
    "Disclosure": "world",
    "Identity": "world",
    "Need": "world",
    "Rubric": "world",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(f".{module}", __name__), name)
