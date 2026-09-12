"""Attach the shared benchmark tools to either LiveKit model without copying schemas."""

from __future__ import annotations

import time
import uuid

from livekit.agents import function_tool
from voicelab.bench.agent import (
    JOBS,
    gemini_instruction,
    gptlive_backend_prompt,
    gptlive_delegation_prompt,
    gptlive_live_prompt,
)
from voicelab.bench.suite import grade_state, scenario
from voicelab.bench.tools import BENCH_TODAY, build_backend

FINISH_CALL_SCHEMA = {
    "name": "finish_call",
    "description": "End your telephone call after completing your entire customer agenda and saying goodbye. This is a telephone control, not a business tool or proof of success.",
    "parameters": {
        "type": "object",
        "properties": {"reason": {"type": "string"}},
        "required": ["reason"],
    },
}


def usage_snapshot(usage) -> dict:
    """AgentSessionUsage is a dataclass containing Pydantic model-usage rows."""
    return {"model_usage": [item.model_dump() for item in usage.model_usage]}


class BenchmarkContext:
    def __init__(self, name: str, seed: int, language: str, tool_delay_ms: int = 0):
        from voicelab.simulations.cases import CASES as SIMULATION_CASES
        from voicelab.simulations.cases import SimulationCase

        self.name = name
        self.simulation = (
            SimulationCase(name, seed, language, tool_delay_ms)
            if name in SIMULATION_CASES
            else None
        )
        if tool_delay_ms and not self.simulation:
            raise ValueError("Tool-delay injection requires a sim-* scenario")
        if self.simulation:
            self.call = self.simulation.call
            self.backend = self.simulation.sandbox
            self.job = self.simulation.job
        else:
            self.call = scenario(name, seed, language)
            self.backend = build_backend(self.call.world)
            if hasattr(self.backend, "stock_kg"):
                self.backend.stock_kg = 800
            self.job = JOBS[(self.call.world.domain, language)]
        self.registry = self.backend.registry()
        self.executions: list[dict] = []

    def prompts(self) -> tuple[str, str, str]:
        today = f"\nReference date: {BENCH_TODAY.isoformat()}. This is a fictional demo business."
        live = (
            gptlive_live_prompt(self.job)
            + "\n"
            + gptlive_delegation_prompt(self.job, tuple(self.registry.names()))
        )
        return (
            gemini_instruction(self.job) + today,
            live + today,
            gptlive_backend_prompt(self.job) + today,
        )

    def tools(self) -> list:
        def wrap(tool):
            async def execute(raw_arguments: dict):
                started = time.monotonic()
                result = await self.registry.execute(uuid.uuid4().hex, tool.name, raw_arguments)
                self.executions.append(
                    {
                        "name": tool.name,
                        "args": raw_arguments,
                        "result": result.result,
                        "ok": result.ok,
                        "elapsed_ms": (time.monotonic() - started) * 1000,
                    }
                )
                return result.result

            return function_tool(
                execute,
                raw_schema={
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": dict(tool.parameters),
                },
            )

        return [wrap(tool) for tool in self.registry]

    def result(self) -> dict:
        if self.simulation:
            return {**self.simulation.result(), "tool_executions": self.executions}
        return {
            "scenario": self.name,
            "seed": self.call.world.seed,
            "language": self.call.world.language,
            "tool_executions": self.executions,
            "grade": grade_state(self.call, self.backend),
        }
