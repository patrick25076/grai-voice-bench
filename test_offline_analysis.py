import copy
import unittest

from voicelab.simulations.cases import SimulationCase
from voicelab.simulations.runner import reference_actions, replay

from offline_analysis import check_sandbox


class ReplayAuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_uncertain_commit_and_retry_replay_exactly(self):
        case = SimulationCase("sim-retry-after-timeout")
        evidence = await replay(case, reference_actions(case))
        self.assertTrue((await check_sandbox(evidence))["exact_state_results_and_grade_match"])

    async def test_changed_result_and_grade_cannot_pass_integrity(self):
        case = SimulationCase("sim-create-order")
        evidence = copy.deepcopy(await replay(case, reference_actions(case)))
        evidence["sandbox"]["events"][0]["result"]["order"]["quantity_kg"] = 999
        evidence["grade"]["state_pass"] = False
        result = await check_sandbox(evidence)
        self.assertFalse(result["exact_state_results_and_grade_match"])
        self.assertIn("event_0_result", result["differences"])
        self.assertIn("grade", result["differences"])


if __name__ == "__main__":
    unittest.main()
