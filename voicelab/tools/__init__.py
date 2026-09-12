"""Tools: what the model may call, rendered per model, executed by the bridge.

A :class:`ToolDef` is runtime-neutral: a name, a description, a JSON-Schema
``parameters`` object and an async ``handler``. The registry renders the same
definitions into whatever shape a model's API wants (today: Gemini function
declarations, as the keyword arguments of ``types.FunctionDeclaration``) and
executes calls with one contract the bridge can rely on: **execute never
raises**. An unknown tool, a handler that throws and a handler slower than its
timeout all come back as a :class:`ToolResult` with ``ok=False`` and a result
dict the model can speak to ("I could not check that"), because on
``gemini-3.1-flash-live-preview`` a tool call is synchronous: the model is
silent until the response arrives, and an exception that escaped here would be
dead air on the phone.

Nothing in this package imports a model SDK or the bridge. The bridge imports
it; lanes import it; the clinic app builds ``ToolDef``s from its own service
layer and hands them over in an ``AgentSpec`` (step C2).
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

__all__ = ["ToolDef", "ToolHandler", "ToolRegistry", "ToolResult", "failed_result", "tool_failed"]

ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]

#: Gemini function names: letters, digits, underscores, dashes; must start with a
#: letter or underscore; at most 64 characters (the documented limit).
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")

#: Default wall-clock budget for one tool call. Nora's ledger writes take tens of
#: milliseconds; a remote CRM over HTTP a few hundred. Eight seconds is already a
#: long silence on a phone, which is the point: past it the model gets an error
#: it can talk about instead of the caller hearing nothing.
DEFAULT_TIMEOUT_S = 8.0


@dataclass(frozen=True)
class ToolDef:
    """One callable the model may invoke."""

    name: str
    description: str
    handler: ToolHandler
    #: JSON Schema for the arguments (an ``object`` schema). Empty means the tool
    #: takes no arguments and the declaration carries no schema at all.
    parameters: Mapping[str, Any] = field(default_factory=dict)
    timeout_s: float = DEFAULT_TIMEOUT_S
    #: Claims this tool's SUCCESS licenses the model to make, e.g. ``record_order``
    #: licenses "your order is recorded". Read by the listener (step C6), not here.
    licenses: tuple[str, ...] = ()
    #: This tool hangs up. When its result carries ``ending`` truthy (or no
    #: ``ending`` key at all) the bridge drains what the model already said,
    #: waits a short farewell pad and ends the call itself, and the result is
    #: NOT sent to the model: the farewell was spoken before the call, and a
    #: reply here would race the hangup as a second goodbye. A result with
    #: ``ending: False`` (a refused hangup) is sent like any other, so the
    #: model can put things right and call again.
    ends_call: bool = False

    def __post_init__(self) -> None:
        if not _NAME_RE.match(self.name):
            raise ValueError(f"tool name {self.name!r} is not a valid function name")
        if not self.description.strip():
            raise ValueError(f"tool {self.name!r} needs a description; the model reads it")
        if self.timeout_s <= 0:
            raise ValueError(f"tool {self.name!r}: timeout_s must be positive")
        if self.parameters and self.parameters.get("type", "object") != "object":
            raise ValueError(f"tool {self.name!r}: parameters must be an object schema")

    def declaration(self) -> dict[str, Any]:
        """The Gemini function declaration, as ``types.FunctionDeclaration`` kwargs.

        Plain dicts on purpose: the direct lane turns them into SDK objects, the
        fake lane sends them verbatim in its setup frame, and golden tests can
        compare them without importing the SDK.
        """
        decl: dict[str, Any] = {"name": self.name, "description": self.description}
        if self.parameters:
            decl["parameters_json_schema"] = dict(self.parameters)
        return decl


@dataclass(frozen=True)
class ToolResult:
    """What one call produced. ``result`` is what goes back to the model."""

    call_id: str
    name: str
    ok: bool
    result: dict[str, Any]
    elapsed_ms: float
    error: str | None = None


def tool_failed(result: Mapping[str, Any] | None) -> bool:
    """True when a handler's answer says it did not do the thing.

    The tenant's handlers all answer the same way, a refusal and a failure
    alike: ``{"recorded"|"updated"|"cancelled"|"ok": False, "error": "..."}``.
    ``found: False`` on a lookup is an answer, not a failure, so only ``error``
    counts, and only next to a False flag or on its own.
    """
    if not isinstance(result, Mapping):
        return False
    if not result.get("error"):
        return result.get("ok") is False
    return True


def failed_result(result: Mapping[str, Any], note: str | None) -> dict[str, Any]:
    """The failed result with the note the model must read, when there is one."""
    out = dict(result)
    if note:
        out["atentie"] = note
    return out


class ToolRegistry:
    """The tools of one session, in registration order."""

    def __init__(self, tools: Iterable[ToolDef] = ()) -> None:
        self._tools: dict[str, ToolDef] = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"duplicate tool name {tool.name!r}")
            self._tools[tool.name] = tool

    def __len__(self) -> int:
        return len(self._tools)

    def __bool__(self) -> bool:
        return bool(self._tools)

    def __iter__(self) -> Iterator[ToolDef]:
        return iter(self._tools.values())

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    # --- rendering ----------------------------------------------------------

    def to_gemini(self) -> list[dict[str, Any]]:
        """``LiveConnectConfig.tools`` as plain dicts: one Tool, all declarations."""
        if not self._tools:
            return []
        return [{"function_declarations": [t.declaration() for t in self._tools.values()]}]

    # --- execution ----------------------------------------------------------

    async def execute(self, call_id: str, name: str, args: Mapping[str, Any]) -> ToolResult:
        """Run one call. Never raises; cancellation is the one thing that passes through."""
        started = time.perf_counter()

        def done(ok: bool, result: Mapping[str, Any], error: str | None = None) -> ToolResult:
            return ToolResult(
                call_id=call_id,
                name=name,
                ok=ok,
                result=dict(result),
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                error=error,
            )

        tool = self._tools.get(name)
        if tool is None:
            msg = f"unknown tool {name!r}"
            return done(False, {"ok": False, "error": msg}, msg)
        try:
            value = await asyncio.wait_for(tool.handler(dict(args)), timeout=tool.timeout_s)
        except TimeoutError:
            msg = f"timeout after {tool.timeout_s:g}s"
            return done(False, {"ok": False, "error": msg}, msg)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # the model must get an answer, whatever broke
            msg = f"{type(exc).__name__}: {exc}"
            return done(False, {"ok": False, "error": msg}, msg)
        if isinstance(value, Mapping):
            return done(True, value)
        return done(True, {"result": value})
