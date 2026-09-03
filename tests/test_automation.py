import json
import os
import unittest


class AutomationContractTests(unittest.TestCase):
    def setUp(self):
        self.root = os.path.dirname(os.path.dirname(__file__))
        with open(os.path.join(self.root, "automation", "policy.json"), encoding="utf-8") as handle:
            self.policy = json.load(handle)

    def test_policy_has_confidence_gate_and_allowlist(self):
        self.assertGreaterEqual(self.policy["minimum_confidence"], 0.5)
        self.assertIn("reset_redis_proxy", self.policy["allowed_actions"])
        self.assertIn("restart_payments", self.policy["allowed_actions"])

    def test_policy_has_recovery_guard(self):
        verify = self.policy["verification"]
        self.assertGreaterEqual(verify["checkout_requests"], 3)
        self.assertGreaterEqual(verify["minimum_success_ratio"], 0.8)
        self.assertTrue(self.policy["fallback"]["enabled"])

    def test_investigator_exposes_only_allowlisted_action_vocabulary(self):
        with open(os.path.join(self.root, "agent", "investigator.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("remediation_action", source)
        self.assertIn("Choose none unless", source)
        self.assertNotIn('scenario["expected"]["remediation"]', source.split("def ask_ollama", 1)[1].split("def load_scenario", 1)[0])

    def test_chaos_controller_has_scoped_repairs(self):
        with open(os.path.join(self.root, "chaos", "chaosctl.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("def repair(target)", source)
        self.assertIn('target == "payments-service"', source)


if __name__ == "__main__":
    unittest.main()
