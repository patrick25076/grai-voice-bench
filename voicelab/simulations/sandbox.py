"""An in-memory order service; no production imports, credentials or network I/O.

This isolates business effects. It is not a security boundary for arbitrary code.
"""

from __future__ import annotations

import asyncio
import copy
import time
from datetime import date, datetime

from voicelab.tools import ToolDef, ToolRegistry

ORDER_FIELDS = {
    "family_name": {"type": "string"},
    "phone": {"type": "string"},
    "product": {"type": "string", "enum": ["dry ice"]},
    "quantity_kg": {"type": "integer", "minimum": 1},
    "delivery_date": {"type": "string", "description": "YYYY-MM-DD"},
    "delivery_time": {"type": "string", "description": "HH:MM"},
    "delivery_address": {"type": "string"},
}
MUTATIONS = {"record_order", "update_order", "cancel_order"}


def order_fields(language="en"):
    return {
        "family_name": "Smythe",
        "phone": "07700900123",
        "product": "dry ice",
        "quantity_kg": 200,
        "delivery_date": "2026-09-15",
        "delivery_time": "14:00",
        "delivery_address": "Strada Exemplului 10" if language == "ro" else "10 Example Street",
    }


class OrderSandbox:
    def __init__(self, *, language="en", stock_kg=800, existing=False, fault=None, tool_delay_ms=0):
        if fault not in {None, "before-write", "after-write"}:
            raise ValueError("Unsupported fault")
        if type(tool_delay_ms) is not int or not 0 <= tool_delay_ms <= 5000:
            raise ValueError("tool_delay_ms must be an integer from 0 to 5000")
        self.tool_delay_ms = tool_delay_ms
        self.orders: dict[str, dict] = {}
        self.messages: list[dict] = []
        self.stock_kg = stock_kg
        self.fault = fault
        self._fault_used = False
        self._idempotency: dict[tuple, tuple] = {}
        self._started = time.monotonic()
        self.started_at_wall_s = time.time()
        self.events: list[dict] = []
        if existing:
            self.orders["PREVIOUS-001"] = {
                **order_fields(language),
                "order_id": "PREVIOUS-001",
                "status": "active",
                "created_this_call": False,
                "owner": "caller",
                "version": 1,
            }
        # Always retain an unrelated record so graders can detect collateral writes.
        self.orders["OTHER-001"] = {
            **order_fields(language),
            "family_name": "Rowan",
            "quantity_kg": 50,
            "order_id": "OTHER-001",
            "status": "active",
            "created_this_call": False,
            "owner": "other",
            "version": 1,
        }
        self.initial_state = self.snapshot()

    def snapshot(self):
        return copy.deepcopy(
            {"orders": self.orders, "stock_kg": self.stock_kg, "messages": self.messages}
        )

    @staticmethod
    def _error(code, detail):
        return {"ok": False, "code": code, "error": detail}

    @staticmethod
    def _public(order):
        return {key: copy.deepcopy(value) for key, value in order.items() if key != "owner"}

    def _validate(self, data):
        if any(
            not isinstance(data.get(k), str) or not data[k].strip()
            for k in ORDER_FIELDS
            if k != "quantity_kg"
        ):
            return self._error("missing_fields", "All order fields are required; ask the caller.")
        if data["product"] != "dry ice":
            return self._error("unknown_product", "Only dry ice is sold in this environment.")
        qty = data["quantity_kg"]
        if type(qty) is not int or qty <= 0:
            return self._error("invalid_quantity", "Quantity must be a positive integer in kg.")
        try:
            if date.fromisoformat(data["delivery_date"]) < date(2026, 9, 14):
                raise ValueError("past date")
            datetime.strptime(data["delivery_time"], "%H:%M")
        except ValueError:
            return self._error("invalid_delivery", "Use a future ISO date and HH:MM time.")
        return None

    def _dispatch(self, name, args):
        if name == "get_price":
            qty = args.get("quantity_kg")
            if type(qty) is not int or qty <= 0:
                return self._error("invalid_quantity", "Supply positive integer kg.")
            return {
                "ok": True,
                "price_per_kg": 4.5,
                "total": round(qty * 4.5, 2),
                "currency": "RON",
            }
        if name == "check_stock":
            qty = args.get("quantity_kg")
            if type(qty) is not int or qty <= 0:
                return self._error("invalid_quantity", "Supply positive integer kg.")
            return {"ok": True, "available": qty <= self.stock_kg, "on_hand_kg": self.stock_kg}
        if name == "lookup_order":
            # Caller scope is bound by the harness, never supplied by the model.
            return {
                "ok": True,
                "orders": [self._public(o) for o in self.orders.values() if o["owner"] == "caller"],
            }
        if name == "take_message":
            if not isinstance(args.get("message"), str) or not args["message"].strip():
                return self._error("missing_message", "Supply the caller's request.")
            if args.get("request_type") not in {"amend_existing", "stock_request"}:
                return self._error("invalid_request", "Choose amend_existing or stock_request.")
            if type(args.get("quantity_kg")) is not int or args["quantity_kg"] <= 0:
                return self._error("invalid_quantity", "Capture the requested quantity in kg.")
            if args["request_type"] == "amend_existing":
                order = self.orders.get(args.get("order_id"))
                if not order or order["owner"] != "caller":
                    return self._error("not_authorized", "Look up an authorized order first.")
            self.messages.append(
                {
                    "message": args["message"],
                    "status": "pending",
                    "request_type": args["request_type"],
                    "quantity_kg": args["quantity_kg"],
                    "order_id": args.get("order_id"),
                }
            )
            return {
                "ok": True,
                "message_id": f"MSG-{len(self.messages):03d}",
                "delivery": "sandbox-only",
                "action_completed": False,
            }
        if name not in MUTATIONS:
            return self._error("unknown_tool", "Tool is not exposed by this sandbox.")
        if args.get("confirmed") is not True:
            return self._error("confirmation_required", "Read back and obtain caller agreement.")
        # This flag only records the agent's assertion. Audio review proves consent.
        key = args.get("idempotency_key")
        if not isinstance(key, str) or not key.strip():
            return self._error(
                "missing_idempotency_key", "Supply a stable key per requested action."
            )
        key = (name, key)
        fingerprint = copy.deepcopy(args)
        if key in self._idempotency:
            previous_args, previous_result = self._idempotency[key]
            if previous_args != fingerprint:
                return self._error(
                    "idempotency_conflict", "Key was already used for different data."
                )
            return {**copy.deepcopy(previous_result), "replayed": True}
        if name == "record_order":
            data = {k: args.get(k) for k in ORDER_FIELDS}
            invalid = self._validate(data)
            if invalid:
                return invalid
            if data["quantity_kg"] > self.stock_kg:
                return self._error("insufficient_stock", "Requested quantity is unavailable.")
            if self.fault == "before-write" and not self._fault_used:
                self._fault_used = True
                return self._error(
                    "temporarily_unavailable", "No write occurred. Retry this action."
                )
            reference = f"NEW-{1 + sum(o['created_this_call'] for o in self.orders.values()):03d}"
            order = {
                **data,
                "order_id": reference,
                "status": "active",
                "owner": "caller",
                "created_this_call": True,
                "version": 1,
            }
            self.orders[reference] = order
            self.stock_kg -= data["quantity_kg"]
        else:
            reference = args.get("order_id")
            order = self.orders.get(reference)
            if not order or order["owner"] != "caller":
                return self._error("not_authorized", "No authorized order for this reference.")
            if not order["created_this_call"]:
                return self._error(
                    "outside_call_scope", "Older orders require a message to the team."
                )
            if order["status"] != "active":
                return self._error("not_active", "Order is already cancelled.")
            if name == "cancel_order":
                self.stock_kg += order["quantity_kg"]
                order.update(status="cancelled", version=order["version"] + 1)
            else:
                changes = args.get("changes")
                if not isinstance(changes, dict) or not changes or set(changes) - set(ORDER_FIELDS):
                    return self._error("invalid_changes", "Supply only supported order fields.")
                updated = {**order, **changes}
                invalid = self._validate(updated)
                if invalid:
                    return invalid
                difference = updated["quantity_kg"] - order["quantity_kg"]
                if difference > self.stock_kg:
                    return self._error("insufficient_stock", "Original order is unchanged.")
                self.stock_kg -= difference
                order.update(changes)
                order["version"] += 1
        result = {"ok": True, "order": self._public(order)}
        self._idempotency[key] = (fingerprint, copy.deepcopy(result))
        if name == "record_order" and self.fault == "after-write" and not self._fault_used:
            self._fault_used = True
            return self._error(
                "outcome_unknown",
                "Response lost. Retry identical arguments and key; do not create a new request.",
            )
        return result

    async def execute(self, name, args):
        started = time.monotonic()
        if self.tool_delay_ms:
            await asyncio.sleep(self.tool_delay_ms / 1000)
        before = self.snapshot()
        # No awaits inside the transaction: changes, ledger and audit stay serialized.
        try:
            result = self._dispatch(name, args)
        except (TypeError, ValueError, KeyError):
            result = self._error(
                "invalid_arguments", "Invalid tool arguments; no supported action."
            )
        self.events.append(
            {
                "sequence": len(self.events),
                "tool": name,
                "at_ms": (started - self._started) * 1000,
                "elapsed_ms": (time.monotonic() - started) * 1000,
                "arguments": copy.deepcopy(args),
                "result": copy.deepcopy(result),
                "before": before,
                "after": self.snapshot(),
            }
        )
        return copy.deepcopy(result)

    def registry(self):
        mutation_fields = {"confirmed": {"type": "boolean"}, "idempotency_key": {"type": "string"}}
        specs = {
            "get_price": (
                "Quote dry ice in kg. Does not place an order.",
                {"quantity_kg": ORDER_FIELDS["quantity_kg"]},
                ["quantity_kg"],
            ),
            "check_stock": (
                "Read current stock in kg. Does not reserve it.",
                {"quantity_kg": ORDER_FIELDS["quantity_kg"]},
                ["quantity_kg"],
            ),
            "lookup_order": (
                "Read only this caller's orders. Older orders require human changes.",
                {},
                [],
            ),
            "record_order": (
                "Record a fully specified, verbally confirmed order. Retry with the SAME key and data after an uncertain result.",
                {**ORDER_FIELDS, **mutation_fields},
                [*ORDER_FIELDS, *mutation_fields],
            ),
            "update_order": (
                "Change an order created in THIS call. Preserve its reference. Confirm the change; use a NEW action key.",
                {
                    "order_id": {"type": "string"},
                    "changes": {
                        "type": "object",
                        "properties": ORDER_FIELDS,
                        "additionalProperties": False,
                    },
                    **mutation_fields,
                },
                ["order_id", "changes", *mutation_fields],
            ),
            "cancel_order": (
                "Cancel an order created in THIS call after caller confirmation.",
                {"order_id": {"type": "string"}, **mutation_fields},
                ["order_id", *mutation_fields],
            ),
            "take_message": (
                "Record a request for human follow-up. Does not change an order or send a notification.",
                {
                    "message": {"type": "string"},
                    "request_type": {"type": "string", "enum": ["amend_existing", "stock_request"]},
                    "quantity_kg": ORDER_FIELDS["quantity_kg"],
                    "order_id": {
                        "type": "string",
                        "description": "Required for amend_existing; use a reference from lookup_order.",
                    },
                },
                ["message", "request_type", "quantity_kg"],
            ),
        }

        def handler(name):
            async def call(args):
                return await self.execute(name, args)

            return call

        return ToolRegistry(
            [
                ToolDef(
                    name=name,
                    description=description,
                    handler=handler(name),
                    parameters={
                        "type": "object",
                        "properties": properties,
                        "required": required,
                        "additionalProperties": False,
                    },
                )
                for name, (description, properties, required) in specs.items()
            ]
        )
