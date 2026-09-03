import os
import unittest

class RepositoryContractTests(unittest.TestCase):
    def test_expected_service_sources_exist(self):
        root=os.path.dirname(os.path.dirname(__file__))
        for service in ["gateway","catalog","checkout","payments","orders"]:
            self.assertTrue(os.path.exists(os.path.join(root,"services",service,"app.py")))

if __name__ == "__main__":
    unittest.main()
