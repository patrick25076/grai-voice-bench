"""Offline regression checks: routing exclusion and honest unknown costs."""

import tempfile
import unittest
from pathlib import Path

from costs import estimate_usage
from phone import session_lock
from voicelab.bench.suite import normalize_address


class RunnerChecks(unittest.TestCase):
    def test_second_run_cannot_release_first_runs_lock(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = Path(root) / "budget.json"
            with session_lock(ledger):
                with self.assertRaises(FileExistsError), session_lock(ledger):
                    self.fail("Second run acquired the route")
                self.assertTrue(ledger.with_suffix(".lock").exists())
            self.assertFalse(ledger.with_suffix(".lock").exists())

    def test_failed_run_releases_lock(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = Path(root) / "budget.json"
            with self.assertRaises(RuntimeError), session_lock(ledger):
                raise RuntimeError("simulated call failure")
            with session_lock(ledger):
                pass

    def test_unknown_model_is_not_free(self):
        cost = estimate_usage({"model_usage": [{"model": "unknown"}]})
        self.assertIsNone(cost["known_component_estimate_usd"])
        self.assertIsNone(cost["invoice_total_usd"])

    def test_address_abbreviations_preserve_house_number(self):
        self.assertEqual(
            normalize_address("str. Exemplului, nr. 10"), normalize_address("Strada Exemplului 10")
        )
        self.assertNotEqual(
            normalize_address("Strada Exemplului 11"), normalize_address("Strada Exemplului 10")
        )


if __name__ == "__main__":
    unittest.main()
