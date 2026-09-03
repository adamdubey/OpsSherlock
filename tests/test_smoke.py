import json
import os
import unittest


class RepositoryContractTests(unittest.TestCase):
    def setUp(self):
        self.root = os.path.dirname(os.path.dirname(__file__))

    def test_expected_service_sources_exist(self):
        for service in ["gateway", "catalog", "checkout", "payments", "orders"]:
            self.assertTrue(os.path.exists(os.path.join(self.root, "services", service, "app.py")))

    def test_observability_configs_exist(self):
        expected = [
            "observability/alloy/config.alloy",
            "observability/loki/loki.yml",
            "observability/tempo/tempo.yml",
            "observability/prometheus/prometheus.yml",
            "observability/grafana/provisioning/datasources/datasources.yml",
            "observability/grafana/dashboards/baker-street-overview.json",
            "observability/grafana/dashboards/incident-investigation.json",
        ]
        for path in expected:
            self.assertTrue(os.path.exists(os.path.join(self.root, path)), path)

    def test_dashboards_are_valid_json(self):
        directory = os.path.join(self.root, "observability", "grafana", "dashboards")
        for filename in os.listdir(directory):
            if filename.endswith(".json"):
                with open(os.path.join(directory, filename), encoding="utf-8") as handle:
                    dashboard = json.load(handle)
                self.assertIn("title", dashboard)
                self.assertIn("panels", dashboard)

    def test_no_legacy_inventory_service(self):
        with open(os.path.join(self.root, "docker-compose.yml"), encoding="utf-8") as handle:
            compose = handle.read()
        self.assertNotIn("inventory:", compose)


if __name__ == "__main__":
    unittest.main()
