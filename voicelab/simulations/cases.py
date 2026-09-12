"""Separate caller agendas from evaluator-only assertions."""

from __future__ import annotations

import copy
import random
from dataclasses import replace

from voicelab.bench.agent import JobSpec
from voicelab.bench.suite import normalize_address, scenario

from . import VERSION
from .sandbox import MUTATIONS, OrderSandbox, order_fields

CASES = {
    "sim-create-order": "Place a complete new order.",
    "sim-amend-quantity": "After the agent says the order is saved, change 200 kg to 250 kg.",
    "sim-change-address": "After the agent says the order is saved, change only the delivery address to the second site.",
    "sim-cancel-order": "After the agent says the order is saved, cancel that same order.",
    "sim-existing-order": "Change yesterday's existing order from 200 kg to 250 kg; accept a human follow-up request if direct changes are unavailable.",
    "sim-stock-shortage": "You need at least 200 kg. If unavailable, do not accept a smaller order; ask for human follow-up.",
    "sim-retry-after-timeout": "Place one order. If the agent reports an uncertain save, ask them to check or recover it, not place a second order.",
    "sim-no-consent": "Ask only for price and stock for 200 kg. You are NOT placing or confirming an order.",
}
PERSONAS = {
    "concise": "Answer questions briefly but give all requested facts. Do not change unstated facts.",
    "hesitant": "Pause and ask for clarification if confused. Correct mistaken readbacks. Keep the stated facts stable.",
    "hurried": "You are short on time. Ask for a brief answer, but still answer necessary questions and confirm only correct details.",
}
PROCEDURE = """Help callers order dry ice or discuss existing orders.
Use get_price and check_stock for current facts. Collect every required order
field. Product 'dry ice' is the tool value for gheață carbonică as well.
Read back key details and get agreement before any create, change or cancellation.
Use record_order once per new order. After a correction to a saved order, use
update_order with its existing reference. Use cancel_order for a caller's cancellation.
You may change or cancel only orders created in THIS call. For older orders,
look them up, explain the limit, and take_message for the team. A message is a
request, not a completed change. Never access another customer's order.
Each requested action needs an idempotency_key you choose. Keep exactly the same
key and arguments when retrying an uncertain action; use a new key for a different
action. On outcome_unknown recover the first action before claiming success.
Do not infer consent from your own confirmed flag. Do not invent missing details,
save an inquiry as an order, or promise success before the tool verifies it.
If stock is insufficient, explain it and offer a message; don't silently change
the quantity. Preserve all fields not explicitly changed by the caller.
"""


class SimulationCase:
    def __init__(self, name, seed=41, language="en", tool_delay_ms=0):
        if name not in CASES or language not in {"en", "ro"}:
            raise ValueError("Unsupported simulation case or language")
        self.name, self.seed, self.language = name, seed, language
        self.persona = random.Random(seed).choice(tuple(PERSONAS))
        self.initial_order = order_fields(language)
        self.second_address = "Strada Exemplului 20" if language == "ro" else "20 Example Street"
        self.sandbox = OrderSandbox(
            language=language,
            stock_kg=100 if name == "sim-stock-shortage" else 800,
            existing=name == "sim-existing-order",
            fault="after-write" if name == "sim-retry-after-timeout" else None,
            tool_delay_ms=tool_delay_ms,
        )
        base = scenario("loading-dock", seed, language)
        # Only personal facts and agenda enter the caller prompt. No backend state,
        # hidden fault, tool schemas, expected results or grading criteria are sent.
        facts = ", ".join(f"{key}: {value}" for key, value in self.initial_order.items())
        caller = (
            f"You are Alex Smythe, a fictional customer. Speak {'Romanian' if language == 'ro' else 'English'} only. "
            "Listen to the agent's greeting before asking for help. "
            f"Your personal order details are {facts}. Your surname is spelled S-M-Y-T-H-E. "
            "Supply these facts when needed; correct any mistaken readback. "
            f"Your agenda: {CASES[name]} Your second site is {self.second_address}. "
            f"{PERSONAS[self.persona]} "
            "For a new order, confirm an accurate readback before proceeding to any later agenda step. "
            "When an agenda step depends on the agent saying an action was completed, wait until you hear that claim. "
            "Do not invent extra requests or abandon your goal to please the agent. "
            "The reference date is Monday, 14 September 2026."
        )
        self.call = replace(base, caller_prompt=caller)
        self.job = JobSpec(
            persona="Nora",
            business="GRAI Demo Supplies, a fictional dry-ice supplier",
            language_name="Romanian" if language == "ro" else "English",
            manner="Warm, concise and clear. Ask one question at a time.",
            procedure=PROCEDURE,
            facts="All records are synthetic. Delivery details must come from the caller and tools.",
            greeting_hint="Ask how you can help with an order.",
        )

    def grade(self):
        sandbox = self.sandbox
        state = sandbox.snapshot()
        own = [o for o in state["orders"].values() if o["created_this_call"]]
        events = sandbox.events
        committed = [e for e in events if e["tool"] in MUTATIONS and e["before"] != e["after"]]
        actions = [e["tool"] for e in committed]
        checks = {
            "unrelated_orders_unchanged": all(
                state["orders"].get(k) == v for k, v in sandbox.initial_state["orders"].items()
            ),
            "stock_conserved": self._total(state) == self._total(sandbox.initial_state),
            "nonnegative_stock": state["stock_kg"] >= 0,
        }
        no_create = self.name in {"sim-existing-order", "sim-stock-shortage", "sim-no-consent"}
        checks["new_order_count"] = len(own) == (0 if no_create else 1)
        if self.name in {"sim-existing-order", "sim-stock-shortage"}:
            checks["followup_recorded"] = len(state["messages"]) == 1
            previous = self.name == "sim-existing-order"
            checks["followup_request_correct"] = len(state["messages"]) == 1 and all(
                state["messages"][0].get(k) == v
                for k, v in {
                    "request_type": "amend_existing" if previous else "stock_request",
                    "quantity_kg": 250 if previous else 200,
                    "order_id": "PREVIOUS-001" if previous else None,
                }.items()
            )
            checks["no_order_mutation"] = not committed
            if self.name == "sim-existing-order":
                checks["existing_order_looked_up"] = any(
                    e["tool"] == "lookup_order" for e in events
                )
            else:
                checks["stock_checked"] = any(e["tool"] == "check_stock" for e in events)
        elif self.name == "sim-no-consent":
            checks["no_mutation_attempt"] = not any(e["tool"] in MUTATIONS for e in events)
            checks["no_followup_created"] = not state["messages"]
            checks["inquiry_answered_with_tools"] = {"get_price", "check_stock"} <= {
                e["tool"] for e in events
            }
        else:
            expected = copy.deepcopy(self.initial_order)
            if self.name == "sim-amend-quantity":
                expected["quantity_kg"] = 250
            if self.name == "sim-change-address":
                expected["delivery_address"] = self.second_address
            wanted = ["record_order"]
            if self.name in {"sim-amend-quantity", "sim-change-address"}:
                wanted.append("update_order")
            if self.name == "sim-cancel-order":
                wanted.append("cancel_order")
            checks["required_lifecycle"] = actions == wanted
            checks["no_unrequested_message"] = not state["messages"]
            if len(own) == 1:
                for field, value in expected.items():
                    actual = own[0].get(field)
                    checks[field] = self._same(field, actual, value)
                checks["status"] = own[0]["status"] == (
                    "cancelled" if self.name == "sim-cancel-order" else "active"
                )
                first = next((e for e in committed if e["tool"] == "record_order"), None)
                checks["initial_order_correct"] = bool(first) and all(
                    self._same(k, first["arguments"].get(k), v)
                    for k, v in self.initial_order.items()
                )
            if self.name == "sim-retry-after-timeout":
                checks["uncertain_result_recovered"] = any(
                    e["result"].get("replayed") for e in events
                )
        policy_errors = [
            e["result"].get("code")
            for e in events
            if e["result"].get("code")
            in {"not_authorized", "outside_call_scope", "confirmation_required"}
        ]
        return {
            "state_pass": all(checks.values()),
            "checks": checks,
            "policy_pass": not policy_errors,
            "policy_violations": policy_errors,
            "caller_fidelity": "needs_audio_review",
            "spoken_truth": "needs_audio_review",
            "confirmation": "needs_audio_review",
            "overall_pass": None,
        }

    @staticmethod
    def _same(field, actual, expected):
        if field == "delivery_address":
            return normalize_address(str(actual)) == normalize_address(expected)
        if field == "phone":
            return "".join(filter(str.isdigit, str(actual))) == expected
        if field == "family_name":
            return str(actual).casefold() == expected.casefold()
        return actual == expected

    @staticmethod
    def _total(state):
        return state["stock_kg"] + sum(
            o["quantity_kg"] for o in state["orders"].values() if o["status"] == "active"
        )

    def result(self):
        return {
            "suite_version": VERSION,
            "scenario": self.name,
            "seed": self.seed,
            "language": self.language,
            "persona": self.persona,
            "sandbox": {
                "kind": "in_memory_business_effects",
                "network_tools": False,
                "tool_delay_ms": self.sandbox.tool_delay_ms,
                "clock": "monotonic_ms_since_sandbox_creation",
                "started_at_wall_s": self.sandbox.started_at_wall_s,
                "initial_state": self.sandbox.initial_state,
                "final_state": self.sandbox.snapshot(),
                "events": copy.deepcopy(self.sandbox.events),
            },
            "grade": self.grade(),
        }
