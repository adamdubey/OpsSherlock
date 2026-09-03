import json
import os
import unittest


class ChaosContractTests(unittest.TestCase):
    def setUp(self):
        self.root = os.path.dirname(os.path.dirname(__file__))
        with open(os.path.join(self.root, "chaos", "scenarios.json"), encoding="utf-8") as handle:
            self.scenarios = json.load(handle)

    def test_expected_scenarios_exist(self):
        expected = {
            "checkout_latency",
            "redis_latency",
            "redis_outage",
            "payments_latency",
            "payments_timeout",
            "payments_container_crash",
            "postgres_latency",
            "postgres_outage",
        }
        self.assertEqual(expected, set(self.scenarios))

    def test_scenarios_have_ground_truth_and_difficulty(self):
        for name, scenario in self.scenarios.items():
            self.assertIn(scenario["severity"], {"SEV-1", "SEV-2", "SEV-3"}, name)
            self.assertIn(scenario["difficulty"], {"easy", "medium", "hard"}, name)
            self.assertIn("injector", scenario, name)
            self.assertIn("expected", scenario, name)
            self.assertTrue(scenario["expected"].get("affected_service"), name)
            self.assertTrue(scenario["expected"].get("keywords"), name)

    def test_dependency_routes_use_toxiproxy(self):
        with open(os.path.join(self.root, "docker-compose.yml"), encoding="utf-8") as handle:
            compose = handle.read()
        self.assertIn("REDIS_URL: redis://toxiproxy:8667/0", compose)
        self.assertIn("PAYMENTS_URL: http://toxiproxy:8666", compose)
        self.assertIn("toxiproxy:8668", compose)
        self.assertIn("ghcr.io/shopify/toxiproxy:2.12.0", compose)

    def test_agent_prompt_does_not_include_scenario_metadata(self):
        with open(os.path.join(self.root, "agent", "investigator.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("you are NOT told which scenario was used", source)
        self.assertNotIn("SCENARIO: {scenario", source)


if __name__ == "__main__":
    unittest.main()
