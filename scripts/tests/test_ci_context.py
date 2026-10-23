import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location("ci_context", Path(__file__).parents[1] / "ci_context.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CIContextTest(unittest.TestCase):
    def test_only_allowlisted_identity_is_recorded_and_no_verdict_is_invented(self):
        result = module.context({"GITHUB_RUN_ID": "123", "GITHUB_SHA": "event-sha",
                                 "GITHUB_TOKEN": "secret-fixture", "GUIHONG_DB_PASSWORD": "private-fixture"},
                                "actual-checkout-sha")
        self.assertEqual(result["checkout_sha"], "actual-checkout-sha")
        self.assertEqual(result["github"]["GITHUB_SHA"], "event-sha")
        self.assertNotIn("GITHUB_TOKEN", result["github"])
        self.assertNotIn("GUIHONG_DB_PASSWORD", result["github"])
        self.assertNotIn("verdict", result)
        self.assertIn("NOT_TEST_RESULT", result["boundary"])


if __name__ == "__main__":
    unittest.main()
