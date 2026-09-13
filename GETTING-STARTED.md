# Try the sandbox before making a call

GRAI Voice Bench is an MIT-licensed experimental toolkit from GRAI Labs. Start
with the offline inspector: it needs no accounts, API keys or paid calls.

## First run: Python 3.12 or 3.13, no dependencies

```sh
git clone https://github.com/patrick25076/grai-voice-bench.git
cd grai-voice-bench
python -m voicelab.simulations demo --language en --output runs/first-demo
```

Open `runs/first-demo/index.html` in your browser. Choose a case, then compare its
reference and deliberately broken traces. The event slider shows tool arguments,
responses and business state before and after each action. `results.json` contains
the same evidence for your own reports. Use a new output directory for each run.

This is a **scripted fixture demo**, with eight cases and two traces per case.
It does not call an AI or generate audio. Passing these fixtures validates the
example environment and checks; it does not measure a model's performance.

Without Python, [download the standalone example inspector](https://github.com/patrick25076/grai-voice-bench/releases/download/v0.2.0/simulation-inspector.html)
and open that HTML file locally.

## What you can use today

| Component | What a developer can do |
| --- | --- |
| Seeded order sandbox | Test creates, amendments, address changes, cancellations, lookups and follow-up messages without a real CRM. |
| Fault injection | Test a lost response after a committed write and detect duplicate orders or stock reservations. |
| Tool-trace replay | Replay a JSON list of tool calls through the sandbox and inspect state and lifecycle checks. |
| Runtime-neutral registry | Wire the same names, descriptions, schemas and handlers into your own agent runtime. |
| LiveKit + Twilio phone runner | Run the included agents over a real phone leg with your own accounts and dedicated test routing. |
| Evidence and timing tools | Inspect original recordings, tool receipts, grades, configuration and usage; analyze speech gaps offline. |

The eight cases cover a specific synthetic order workflow. Adapt the business
rules and expected checks to your application before interpreting a failure.
Browser and Telnyx transports, a native Pipecat adapter and one-click evaluation
of an arbitrary hosted agent are **not implemented**. Opening the HTML inspector
in a browser is not browser-based voice testing.

## Replay a trace

A trace is a JSON array of `{"tool": "name", "arguments": {...}}` objects.
For a simple read-only example, save this as `tool-trace.json`:

```json
[
  {"tool": "get_price", "arguments": {"quantity_kg": 200}},
  {"tool": "check_stock", "arguments": {"quantity_kg": 200}}
]
```

```sh
python -m voicelab.simulations replay --case sim-no-consent --language en --script tool-trace.json --output runs/replayed-trace
```

This deliberately includes no write. See the inspector's checks to understand
the case's requirements. Real tool traces must match the sandbox's contracts;
replaying a trace does not recreate the original conversation or its timing.

## Connect your agent's tool dispatcher

Create a fresh case for each session. The following is the interface to adapt;
it is not a complete audio transport:

```python
from voicelab.simulations.cases import SimulationCase

case = SimulationCase("sim-amend-quantity", seed=41, language="en")
registry = case.sandbox.registry()

# Register these fields using your provider SDK's tool format.
schemas = [
    {"name": tool.name, "description": tool.description,
     "parameters": dict(tool.parameters)}
    for tool in registry
]

async def dispatch(call_id, name, arguments):
    response = await registry.execute(call_id, name, arguments)
    return response.result  # Send this business response back to your model.

# After the conversation:
evidence = case.result()
```

Keep the case object alive for the whole session and collect `case.result()`
after the last action. Give the answering agent business instructions and the
tool schemas, not the caller's hidden agenda or evaluator assertions. See
`benchmark_support.py` and `worker.py` for the included LiveKit integration.
`ToolDef.declaration()` is Gemini-shaped; translate the neutral fields above
when using another SDK.

`ToolResult.ok` describes dispatcher execution, not proof that a business write
committed. Inspect `response.result` and the before/after state. A simulated
`outcome_unknown` can mean the write committed but its response was lost.

## What still needs listening

A tool's `confirmed: true` is the agent's assertion, not evidence that the caller
actually agreed. Separate saved-state checks, prohibited attempts, spoken claims,
caller adherence and human listening. A blocked attempt is different from a
committed action; a pleasant conversation is different from a completed task.

For new phone calls, continue with [README: Run](README.md#run) and
[the study protocol](STUDY-60.md). These require `uv sync --locked`, your own
model/LiveKit/Twilio access, dedicated test routing and a spending budget.
The simulation `plan` command only writes a plan; it does not place calls.
Read [security and data handling](SECURITY.md) before connecting accounts.
