"""Environment and grader regression tests. No model calls or network requests."""

import copy
import unittest
from collections import defaultdict

from voicelab.simulations.cases import CASES, SimulationCase
from voicelab.simulations.runner import reference_actions, replay, study_plan
from voicelab.simulations.sandbox import OrderSandbox, order_fields


class SandboxTests(unittest.IsolatedAsyncioTestCase):
    async def test_handoff_with_wrong_quantity_does_not_pass(self):
        case = SimulationCase("sim-existing-order")
        actions = reference_actions(case)
        actions[-1][1]["quantity_kg"] = 999
        await replay(case, actions)
        self.assertTrue(case.grade()["checks"]["followup_recorded"])
        self.assertFalse(case.grade()["checks"]["followup_request_correct"])
        self.assertFalse(case.grade()["state_pass"])

    async def test_delayed_tools_record_the_injected_wait(self):
        sandbox = OrderSandbox(tool_delay_ms=10)
        await sandbox.execute("check_stock", {"quantity_kg": 200})
        self.assertGreaterEqual(sandbox.events[0]["elapsed_ms"], 9)
        self.assertEqual(sandbox.events[0]["before"], sandbox.events[0]["after"])

    async def test_all_cases_are_solvable_in_both_languages_but_not_prepassed(self):
        for name in CASES:
            for language in ("en", "ro"):
                with self.subTest(name=name, language=language):
                    case = SimulationCase(name, language=language)
                    self.assertFalse(case.grade()["state_pass"])
                    result = await replay(case, reference_actions(case))
                    self.assertTrue(result["grade"]["state_pass"], result["grade"])
                    self.assertTrue(result["grade"]["policy_pass"])
                    self.assertIsNone(result["grade"]["overall_pass"])

    async def test_correct_final_quantity_cannot_hide_missing_correction(self):
        case = SimulationCase("sim-amend-quantity")
        await case.sandbox.execute(
            "record_order",
            {**order_fields(), "quantity_kg": 250, "confirmed": True, "idempotency_key": "x"},
        )
        grade = case.grade()
        self.assertTrue(grade["checks"]["quantity_kg"])
        self.assertFalse(grade["checks"]["initial_order_correct"])
        self.assertFalse(grade["checks"]["required_lifecycle"])
        self.assertFalse(grade["state_pass"])

    async def test_unknown_commit_retry_writes_once(self):
        sandbox = OrderSandbox(fault="after-write")
        args = {**order_fields(), "confirmed": True, "idempotency_key": "one"}
        first = await sandbox.execute("record_order", args)
        self.assertEqual(first["code"], "outcome_unknown")
        self.assertEqual(sandbox.stock_kg, 600)
        second = await sandbox.execute("record_order", args)
        self.assertTrue(second["ok"])
        self.assertTrue(second["replayed"])
        self.assertEqual(sandbox.stock_kg, 600)
        self.assertEqual(sum(o["created_this_call"] for o in sandbox.orders.values()), 1)
        self.assertEqual(sandbox.events[-1]["before"], sandbox.events[-1]["after"])

    async def test_new_key_after_unknown_commit_is_detected_as_duplicate(self):
        case = SimulationCase("sim-retry-after-timeout")
        args = {**order_fields(), "confirmed": True, "idempotency_key": "one"}
        await case.sandbox.execute("record_order", args)
        await case.sandbox.execute("record_order", {**args, "idempotency_key": "two"})
        self.assertFalse(case.grade()["checks"]["new_order_count"])
        self.assertFalse(case.grade()["state_pass"])

    async def test_changed_payload_with_reused_key_fails_without_write(self):
        sandbox = OrderSandbox()
        args = {**order_fields(), "confirmed": True, "idempotency_key": "one"}
        await sandbox.execute("record_order", args)
        before = sandbox.snapshot()
        result = await sandbox.execute("record_order", {**args, "quantity_kg": 300})
        self.assertEqual(result["code"], "idempotency_conflict")
        self.assertEqual(before, sandbox.snapshot())

    async def test_precommit_failure_has_no_write_and_retry_can_succeed(self):
        sandbox = OrderSandbox(fault="before-write")
        args = {**order_fields(), "confirmed": True, "idempotency_key": "one"}
        before = sandbox.snapshot()
        result = await sandbox.execute("record_order", args)
        self.assertFalse(result["ok"])
        self.assertEqual(before, sandbox.snapshot())
        self.assertTrue((await sandbox.execute("record_order", args))["ok"])

    async def test_ownership_and_previous_call_restrictions(self):
        sandbox = OrderSandbox(existing=True)
        lookup = await sandbox.execute("lookup_order", {})
        self.assertEqual([o["order_id"] for o in lookup["orders"]], ["PREVIOUS-001"])
        before = sandbox.snapshot()
        for reference, code in (
            ("OTHER-001", "not_authorized"),
            ("PREVIOUS-001", "outside_call_scope"),
        ):
            result = await sandbox.execute(
                "cancel_order",
                {"order_id": reference, "confirmed": True, "idempotency_key": reference},
            )
            self.assertEqual(result["code"], code)
        self.assertEqual(before, sandbox.snapshot())

    async def test_no_consent_and_invalid_quantity_cannot_write(self):
        for changes in (
            {"confirmed": False},
            {"quantity_kg": -2},
            {"quantity_kg": True},
            {"delivery_date": "yesterday"},
        ):
            sandbox = OrderSandbox()
            before = sandbox.snapshot()
            args = {**order_fields(), "confirmed": True, "idempotency_key": "one", **changes}
            self.assertFalse((await sandbox.execute("record_order", args))["ok"])
            self.assertEqual(before, sandbox.snapshot())

    async def test_failed_amendment_is_atomic_and_cancel_restores_stock(self):
        sandbox = OrderSandbox()
        args = {**order_fields(), "confirmed": True, "idempotency_key": "one"}
        await sandbox.execute("record_order", args)
        before = sandbox.snapshot()
        common = {"order_id": "NEW-001", "confirmed": True, "idempotency_key": "change"}
        result = await sandbox.execute("update_order", {**common, "changes": {"quantity_kg": 900}})
        self.assertFalse(result["ok"])
        self.assertEqual(before, sandbox.snapshot())
        await sandbox.execute("cancel_order", {**common, "idempotency_key": "cancel"})
        self.assertEqual(sandbox.stock_kg, 800)

    async def test_state_and_audit_snapshots_do_not_alias(self):
        a, b = OrderSandbox(), OrderSandbox()
        args = {**order_fields(), "confirmed": True, "idempotency_key": "one"}
        response = await a.execute("record_order", args)
        first_after = copy.deepcopy(a.events[0]["after"])
        response["order"]["quantity_kg"] = 999
        await a.execute(
            "update_order",
            {
                "order_id": "NEW-001",
                "confirmed": True,
                "idempotency_key": "two",
                "changes": {"quantity_kg": 250},
            },
        )
        self.assertEqual(a.events[0]["after"], first_after)
        self.assertEqual(b.snapshot(), b.initial_state)

    async def test_romanian_address_abbreviation_is_accepted_in_both_checkpoints(self):
        case = SimulationCase("sim-create-order", language="ro")
        args = {
            **case.initial_order,
            "delivery_address": "str. Exemplului, nr. 10",
            "phone": "07700 900123",
            "confirmed": True,
            "idempotency_key": "one",
        }
        await case.sandbox.execute("record_order", args)
        self.assertTrue(case.grade()["state_pass"], case.grade())

    async def test_reference_scripts_fail_if_each_required_step_is_removed(self):
        for name in CASES:
            template = SimulationCase(name)
            actions = reference_actions(template)
            for skip in range(len(actions)):
                case = SimulationCase(name)
                await replay(case, actions[:skip] + actions[skip + 1 :])
                self.assertFalse(case.grade()["state_pass"], (name, skip))


class StudyTests(unittest.TestCase):
    def test_pairs_hold_caller_fixture_and_limit_fixed(self):
        plan = study_plan(repetitions=5)
        self.assertEqual(plan["call_count"], 160)
        pairs, first = defaultdict(list), defaultdict(list)
        for row in plan["trials"]:
            pairs[row["pair_id"]].append(row)
            if row["arm_order"] == 1:
                first[(row["scenario"], row["caller_provider"])].append(row["provider"])
        for arms in pairs.values():
            self.assertEqual({a["provider"] for a in arms}, {"gemini", "gptlive"})
            for field in ("caller_provider", "scenario", "seed", "language", "seconds"):
                self.assertEqual(arms[0][field], arms[1][field])
        for order in first.values():
            self.assertLessEqual(abs(order.count("gemini") - order.count("gptlive")), 1)
        self.assertIsNone(plan["estimated_total_cost"])

    def test_caller_prompt_does_not_receive_fault_or_backend_state(self):
        case = SimulationCase("sim-retry-after-timeout")
        for hidden in ("OTHER-001", "after-write", "state_pass", "idempotency_key", "record_order"):
            self.assertNotIn(hidden, case.call.caller_prompt)


if __name__ == "__main__":
    unittest.main()
