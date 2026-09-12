"""Run scripted tool traces to debug the environment and grader, without an AI."""

from __future__ import annotations

import copy
import hashlib
import json
import random
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from . import VERSION
from .cases import CASES, SimulationCase


def reference_actions(case):
    """A fixture-validating example, never a model benchmark result."""
    create = {**case.initial_order, "confirmed": True, "idempotency_key": "create-1"}
    if case.name == "sim-no-consent":
        return [("check_stock", {"quantity_kg": 200}), ("get_price", {"quantity_kg": 200})]
    if case.name in {"sim-existing-order", "sim-stock-shortage"}:
        query = (
            ("lookup_order", {})
            if case.name == "sim-existing-order"
            else ("check_stock", {"quantity_kg": 200})
        )
        return [
            query,
            (
                "take_message",
                {
                    "message": "Please follow up on the requested order; no change promised.",
                    "request_type": "amend_existing"
                    if case.name == "sim-existing-order"
                    else "stock_request",
                    "quantity_kg": 250 if case.name == "sim-existing-order" else 200,
                    **({"order_id": "PREVIOUS-001"} if case.name == "sim-existing-order" else {}),
                },
            ),
        ]
    actions = [("record_order", create)]
    common = {"order_id": "NEW-001", "confirmed": True, "idempotency_key": "change-1"}
    if case.name == "sim-amend-quantity":
        actions.append(("update_order", {**common, "changes": {"quantity_kg": 250}}))
    if case.name == "sim-change-address":
        actions.append(
            ("update_order", {**common, "changes": {"delivery_address": case.second_address}})
        )
    if case.name == "sim-cancel-order":
        actions.append(("cancel_order", common))
    if case.name == "sim-retry-after-timeout":
        actions.append(("record_order", copy.deepcopy(create)))
    return actions


async def replay(case, actions):
    registry = case.sandbox.registry()
    for index, (tool, args) in enumerate(actions):
        result = await registry.execute(f"script-{index}", tool, args)
        # Unknown registry tools never reach the environment; retain them as errors.
        if tool not in tuple(registry.names()):
            raise ValueError(f"Unknown tool in replay: {tool}: {result.error}")
    return {"execution_mode": "scripted_tool_trace_no_ai_no_audio", **case.result()}


def study_plan(
    *, repetitions=5, language="ro", caller_providers=("gemini", "gptlive"), seed=20260912
):
    if repetitions < 1 or language not in {"ro", "en"}:
        raise ValueError("Use positive repetitions and en/ro language")
    if not caller_providers or any(c not in {"gemini", "gptlive"} for c in caller_providers):
        raise ValueError("Unknown caller provider")
    if len(set(caller_providers)) != len(caller_providers):
        raise ValueError("Caller strata must be unique")
    rng = random.Random(seed)
    blocks = [
        (name, caller, rep)
        for name in CASES
        for caller in caller_providers
        for rep in range(repetitions)
    ]
    rng.shuffle(blocks)
    trials = []
    # Alternate first target inside each case/caller block; randomized initial arm.
    first_arms = {
        (name, caller): rng.choice(("gemini", "gptlive"))
        for name in CASES
        for caller in caller_providers
    }
    for name, caller, repetition in blocks:
        first = first_arms[(name, caller)]
        if repetition % 2:
            first = "gptlive" if first == "gemini" else "gemini"
        targets = [first, "gptlive" if first == "gemini" else "gemini"]
        fixture_seed = seed + repetition
        pair_id = f"{name}-{language}-{caller}-{repetition + 1:02d}"
        case = SimulationCase(name, fixture_seed, language)

        def digest(value):
            return hashlib.sha256(
                json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()

        fingerprints = {
            "fixture_sha256": digest(case.sandbox.initial_state),
            "caller_prompt_sha256": digest(case.call.caller_prompt),
            "job_spec_sha256": digest(asdict(case.job)),
            "tool_schema_sha256": digest([tool.declaration() for tool in case.sandbox.registry()]),
        }
        for index, target in enumerate(targets):
            trials.append(
                {
                    "pair_id": pair_id,
                    "arm_order": index + 1,
                    "scenario": name,
                    "language": language,
                    "seed": fixture_seed,
                    "caller_provider": caller,
                    "provider": target,
                    "output_name": f"{pair_id}-{target}",
                    "seconds": 180,
                }
            )
            trials[-1]["tool_delay_ms"] = 0
            trials[-1].update(fingerprints)
    sources = {}
    source_root = Path(__file__).parent
    for path in sorted(source_root.glob("*.py")):
        sources[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "suite_version": VERSION,
        "kind": "planned_not_executed",
        "plan_seed": seed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": sources,
        "caller_strata": list(caller_providers),
        "repetitions_per_case_per_stratum": repetitions,
        "target_models": {
            "gemini": "gemini-3.1-flash-live-preview",
            "gptlive": {"voice": "gpt-live-1", "backend": "gpt-5.6-terra"},
        },
        "estimated_total_cost": None,
        "call_count": len(trials),
        "trials": trials,
    }


def write_viewer(path, results):
    data = json.dumps(results, ensure_ascii=False).replace("<", "\\u003c")
    html = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GRAI Labs · Simulation inspector</title>
<style>body{font:16px system-ui;background:#10171b;color:#e2eee9;margin:32px;max-width:1400px}
h1{font-size:30px}select,button{font:inherit;padding:10px;background:#233239;color:inherit;border:1px solid #4f6b6c;border-radius:6px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}section{padding:16px;background:#19252b;border-radius:8px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}input{width:100%}.muted{color:#b0c5bb}
@media(max-width:700px){.grid{grid-template-columns:1fr}body{margin:16px}}</style>
<h1>GRAI Labs · Simulation inspector</h1>
<p class="muted">Scripted tool traces validate the sandbox and grader. These are not AI calls or model scores.</p>
<label>Scenario and trace <select id="pick"></select></label>
<p id="outcome"></p><div class="grid"><section><h2>Checks</h2><pre id="checks"></pre></section>
<section><h2>Tool result</h2><pre id="result"></pre></section></div>
<h2 id="step"></h2><input id="slider" type="range" min="0" value="0" aria-label="Tool event">
<div class="grid"><section><h2>Before</h2><pre id="before"></pre></section>
<section><h2>After</h2><pre id="after"></pre></section></div>
<script type="application/json" id="data">__DATA__</script><script>
const rows=JSON.parse(document.getElementById('data').textContent);
const el=id=>document.getElementById(id), show=(id,x)=>el(id).textContent=JSON.stringify(x,null,2);
rows.forEach((r,i)=>{const o=document.createElement('option');o.value=i;o.textContent=r.scenario+' / '+r.trace;el('pick').append(o)});
function event(){const r=rows[Number(el('pick').value)], events=r.sandbox.events,e=events[Number(el('slider').value)];
el('step').textContent=e?`Event ${e.sequence+1}: ${e.tool}`:'No tool events';
show('result',e?{arguments:e.arguments,result:e.result}:{});show('before',e?e.before:r.sandbox.initial_state);show('after',e?e.after:r.sandbox.final_state)}
function select(){const r=rows[Number(el('pick').value)];el('outcome').textContent=`State checks: ${r.grade.state_pass?'PASS':'FAIL'} · Policy: ${r.grade.policy_pass?'PASS':'FAIL'} · Spoken consent and caller behavior: UNREVIEWED`;
show('checks',r.grade.checks);el('slider').max=Math.max(0,r.sandbox.events.length-1);el('slider').value=0;event()}
el('pick').onchange=select;el('slider').oninput=event;select();</script></html>"""
    path.write_text(html.replace("__DATA__", data), encoding="utf-8")
