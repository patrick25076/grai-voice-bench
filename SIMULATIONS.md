# GRAI Labs simulations

The simulation component tests whether a voice agent changes business state
correctly as a conversation develops. It combines a caller agenda, a fresh
fictional environment, real tool execution against that environment, and checks
on the resulting state and action history.

The eight lifecycle cases are new, separate from the six v0.1 cases. They have
passed offline fixture and SDK-wrapper checks. They have **not yet produced a
new Gemini-versus-GPT phone result**. The September 12 pilot remains one matched
pair on the earlier `loading-dock` case.

## Inspect it without spending money

After `uv sync --locked`:

```sh
uv run python -m voicelab.simulations demo --output runs/simulation-demo
```

Open `runs/simulation-demo/index.html`. Select a case and a reference or broken
trace. Move the event slider to inspect arguments, responses, and state before
and after each tool. The JSON beside it contains the same evidence.

You can also [download the standalone example inspector](https://github.com/patrick25076/grai-voice-bench/releases/download/v0.2.0/simulation-inspector.html)
and open it locally without installing Python. It contains only synthetic traces.

These are scripted tool traces. Their purpose is to prove that the environment
is solvable and that the grader catches errors. They contain no generated voice
and are not AI success scores. `overall_pass` stays null.

## The order lifecycle pack

| Case                      | Caller agenda                                            | What the evaluator checks                                                         |
| ------------------------- | -------------------------------------------------------- | --------------------------------------------------------------------------------- |
| `sim-create-order`        | Order 200 kg for the agreed address and date             | One complete order, correct fields and stock reservation                          |
| `sim-amend-quantity`      | After the agent says it saved 200 kg, increase to 250 kg | Original create, then update of that reference; no duplicate; stock changes by 50 |
| `sim-change-address`      | After the save, switch to the second site                | Same order, new address, all unrelated fields preserved                           |
| `sim-cancel-order`        | After the save, cancel it                                | Same order marked cancelled and stock released                                    |
| `sim-existing-order`      | Change an order from a previous call                     | Lookup and a follow-up message; existing order unchanged                          |
| `sim-stock-shortage`      | Need 200 kg when only 100 kg are available               | Stock checked, no smaller or impossible order, follow-up request saved            |
| `sim-retry-after-timeout` | Complete one order despite an uncertain save             | One committed order, same-key recovery, no duplicate reservation                  |
| `sim-no-consent`          | Ask for price and availability only                      | Read tools used; no order or unnecessary message created                          |

English and Romanian are supported. Seeded caller personas are concise,
hesitant, or hurried. These are conversational instructions, not physical
accent/noise simulation. Initial facts stay fixed; later changes have explicit
triggers such as hearing the agent say that it saved the first order. Live caller
adherence to those triggers still requires evaluation from the recording.

The target receives business rules and tools, not the caller's hidden agenda or
the grader. The caller receives personal facts and an agenda, not backend state,
fault injection settings, schemas or expected checks. An independent evaluator
can inspect both after the call.

## What sandbox means here

`OrderSandbox` is a new in-memory business service for each run. It has no
production database client, credentials, HTTP calls, SMS or email integration.
It exposes `get_price`, `check_stock`, `lookup_order`, `record_order`,
`update_order`, `cancel_order`, and `take_message` through the common tool registry.

Orders have references, versions, status, ownership and a current-call boundary.
Updates reserve or release the quantity difference. Cancellation releases stock.
Retries with the same action key and arguments return the previous result;
reusing a key with different data fails. A fresh key is a fresh operation, so the
grader can catch an agent creating a duplicate after uncertainty.

The same-call amendment restriction mirrors a boundary in Nora's current order
workflow. The public environment is a synthetic approximation, not a copy of
Ice Trust's CRM, price list or customer data. Its stock and order rules are an
explicit test contract; they do not certify the production implementation.

This is **business-effect isolation**, not an operating-system sandbox for
untrusted executable code. An adapter that runs arbitrary code, uses a real CRM,
or sends messages needs a separate isolation boundary before it belongs here.

## Faults, consent and evidence

The service can inject a failure before a write or a lost response after a write.
The latter returns `outcome_unknown` even though state changed. Recovery must
reuse the action's key. This tests a real distributed-systems failure pattern
without creating real orders. The lost response is simulated at the tool contract;
it is not a measured network timeout.

Follow-up messages also carry a structured request type, quantity and, when
applicable, order reference. The grader checks those fields, so saving a generic
or incorrect handoff is not enough to pass the older-order scenario. Free-text
accuracy remains part of semantic review.

`--tool-delay-ms 1500` delays every sandbox tool by 1.5 seconds. Compare this
condition separately, using the same delay for both targets. The supported range
is 0–5000 ms. Delay injection is independent of caller personality.

Every completed tool attempt records arguments, result, sequence, elapsed time,
and deep copies of state before and after. Environment timestamps use milliseconds
since sandbox creation; a wall-clock anchor is retained. Do not subtract these
directly from carrier-audio timestamps without alignment.

The deterministic grader checks final entities, lifecycle order, collateral
changes, stock conservation and prohibited tool attempts. A correct final state
does not erase a bad intermediate action. In the quantity-change case, creating
250 kg immediately fails because the required 200 kg → 250 kg lifecycle never
happened.

The tool's `confirmed: true` is the agent's assertion. It does not prove that a
human or simulated caller consented. Caller fidelity, spoken claims and consent
remain separate recording-based checks. For an overall pass, state and policy
checks must pass and the conversation checks must also pass.

## Use the pack in a real phone test

The existing worker selects the simulation environment from `--scenario`:

```sh
uv run python phone.py --target YOUR_TEST_NUMBER --caller-id YOUR_OWNED_CALLER_ID \
  --sip-host YOUR_LIVEKIT_SIP_HOST --trunk YOUR_DEDICATED_TRUNK \
  --rule YOUR_DEDICATED_RULE --agent grai-bench \
  --provider gemini --caller-provider gemini --scenario sim-amend-quantity \
  --language ro --seed 41 --seconds 180 --tool-delay-ms 0 \
  --output runs/amend-gemini --ledger runs/budget.json --cap-eur 20 --reserve-eur 3
```

Use the updated worker as well as the updated runner. Then repeat with GPT-Live
while holding the caller and all other paired settings fixed. These commands
place paid calls. The offline demo does not. See [STUDY.md](STUDY.md) before a batch.

## Integrate other agents

`OrderSandbox.registry()` exposes runtime-neutral tool definitions and async
handlers. `benchmark_support.py` adapts them to LiveKit function tools; both model
targets use that same adapter. Another runtime can adapt the same definitions
and return `SimulationCase.result()` after the call. The current phone runner
requires the included LiveKit worker; it is not yet a universal hosted-agent
connector or remote tool server.

To debug a failure without an audio model, export a JSON list of
`{"tool": "...", "arguments": {...}}` and replay it:

```sh
uv run python -m voicelab.simulations replay --case sim-amend-quantity \
  --script tool-trace.json --output runs/replayed-trace
```

Add a new environment behind a tool registry, keep fixtures and assertions
separate from the caller prompt, and include both successful traces and examples
that your grader must reject. Future work includes controlled audio replay,
timed interruptions, richer caller validation, and a synchronized audio/tool viewer.
