"""Offline integration of the actual SDK tool wrappers and hidden-state grader."""

import asyncio
import sys
from pathlib import Path

test_root = Path(__file__).resolve().parent
if not (test_root / "voicelab").is_dir():
    sys.path.insert(0, str(test_root.parents[1] / "src"))

from livekit.agents import Agent
from livekit.agents.metrics import AgentSessionUsage
from voicelab.bench.suite import CASES, grade_state
from voicelab.bench.tools import _satisfies

from benchmark_support import BenchmarkContext, usage_snapshot


async def main():
    assert usage_snapshot(AgentSessionUsage(model_usage=[])) == {"model_usage": []}
    for name in CASES:
        b = BenchmarkContext(name, 41, "en")
        agent = Agent(instructions=b.prompts()[1], tools=b.tools())
        assert len(agent.tools) >= 3
        assert not grade_state(b.call, b.backend)["state_pass"]
        if b.call.world.domain == "clinic":
            slot = next(s for s in b.backend.slots if _satisfies(s, b.call.world))
            args = dict(
                slot.as_dict(), family_name="Smythe", phone="07700 900123", service="check-up"
            )
            tool = next(t for t in agent.tools if t.info.name == "book_appointment")
        else:
            args = dict(
                family_name="Smythe",
                phone="07700 900123",
                product="dry ice",
                quantity_kg=200,
                delivery_date="2026-09-15",
                delivery_time="14:00",
                delivery_address="10 Example Street",
            )
            tool = next(t for t in agent.tools if t.info.name == "place_order")
        result = await tool(raw_arguments=args)
        assert result["ok"], result
        assert grade_state(b.call, b.backend)["state_pass"], b.result()
        assert len(b.executions) == 1
        assert len(b.backend.log.entries) == 1
        assert grade_state(b.call, b.backend)["overall_pass"] is None
    print("Six scenarios: SDK tools executed, state checks passed, audio review remains required")


if __name__ == "__main__":
    asyncio.run(main())
