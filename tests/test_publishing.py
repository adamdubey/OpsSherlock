import os
import unittest
from pathlib import Path


class PublishingContractTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(os.path.dirname(os.path.dirname(__file__)))

    def text(self, *parts):
        return self.root.joinpath(*parts).read_text(encoding="utf-8")

    def test_playwright_publisher_is_pinned(self):
        dockerfile = self.text("evidence", "Dockerfile")
        self.assertIn("mcr.microsoft.com/playwright/python:v1.62.0-noble", dockerfile)
        self.assertIn("playwright==1.62.0", dockerfile)

    def test_compose_has_publisher_with_artifact_mount(self):
        compose = self.text("docker-compose.yml")
        self.assertIn("publisher:", compose)
        self.assertIn("./artifacts:/app/artifacts", compose)
        self.assertIn("GRAFANA_URL: http://grafana:3000", compose)

    def test_capture_targets_both_dashboards(self):
        source = self.text("evidence", "capture.py")
        self.assertIn("incident-investigation", source)
        self.assertIn("baker-street-overview", source)
        self.assertIn("page.screenshot", source)

    def test_site_exposes_benchmark_and_failures(self):
        source = self.text("site", "build.py")
        self.assertIn("benchmark.json", source)
        self.assertIn("Failed-diagnosis gallery", source)
        self.assertIn("Grafana evidence", source)

    def test_investigator_records_model_metadata(self):
        source = self.text("agent", "investigator.py")
        self.assertIn('"agent_version": "0.6.0"', source)
        self.assertIn('"eval_count"', source)
        self.assertIn('"total_duration_ns"', source)


if __name__ == "__main__":
    unittest.main()
