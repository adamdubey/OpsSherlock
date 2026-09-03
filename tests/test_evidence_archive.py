import os
import unittest
from pathlib import Path


class EvidenceArchiveContractTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(os.path.dirname(os.path.dirname(__file__)))

    def text(self, *parts):
        return self.root.joinpath(*parts).read_text(encoding="utf-8")

    def test_pages_checks_out_evidence_branch(self):
        workflow = self.text(".github", "workflows", "pages.yml")
        self.assertIn("ref: evidence", workflow)
        self.assertIn("path: .published-evidence", workflow)
        self.assertIn("No published OpsSherlock incidents", workflow)

    def test_publish_script_defaults_to_evidence_branch(self):
        source = self.text("scripts", "publish_evidence.py")
        self.assertIn('DEFAULT_BRANCH = os.getenv("EVIDENCE_BRANCH", "evidence")', source)
        self.assertIn('git("checkout", "--orphan", branch', source)
        self.assertIn('gh, "workflow", "run", "pages.yml", "--ref", "main"', source)

    def test_makefile_exposes_publish_evidence(self):
        makefile = self.text("Makefile")
        self.assertIn("publish-evidence:", makefile)
        self.assertIn("scripts/publish_evidence.py", makefile)


if __name__ == "__main__":
    unittest.main()
