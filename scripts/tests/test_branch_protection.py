import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("protection", ROOT / "scripts/check-branch-protection.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
POLICY = json.loads((ROOT / ".github/main-protection.json").read_text(encoding="utf-8"))
CHECKS = ["Static contracts and boundaries", "Go backend", "Web typecheck, tests and production build"]


def protected():
    return {
        "required_status_checks": {"strict": True, "checks": [
            {"context": name, "app_id": 15368} for name in CHECKS]},
        "enforce_admins": {"enabled": True},
        "required_pull_request_reviews": {"dismiss_stale_reviews": True},
        "required_conversation_resolution": {"enabled": True},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
    }


class BranchProtectionTest(unittest.TestCase):
    def test_policy_retains_current_minimum_without_inventing_human_approvals(self):
        self.assertEqual(POLICY["required_status_checks"], {
            "strict": True, "checks": [{"context": name, "app_id": 15368} for name in CHECKS]})
        for key in ("enforce_admins", "required_conversation_resolution"):
            self.assertIs(POLICY[key], True)
        for key in ("allow_force_pushes", "allow_deletions"):
            self.assertIs(POLICY[key], False)
        self.assertTrue(POLICY["required_pull_request_reviews"]["dismiss_stale_reviews"])
        self.assertEqual(POLICY["required_pull_request_reviews"]["required_approving_review_count"], 0)

    def test_good_and_stronger_config_pass_without_mutating_evidence(self):
        actual = protected()
        self.assertEqual(module.protection_errors(actual, POLICY), [])
        actual["required_status_checks"]["checks"].append({"context": "Extra", "app_id": 15368})
        actual["required_pull_request_reviews"]["required_approving_review_count"] = 1
        original = copy.deepcopy(actual)
        self.assertEqual(module.protection_errors(actual, POLICY), [])
        self.assertEqual(actual, original)

    def test_every_missing_unbound_or_wrong_app_check_is_rejected(self):
        for index, name in enumerate(CHECKS):
            for change in ("missing", "unbound", "wrong-app"):
                with self.subTest(check=name, change=change):
                    actual = protected()
                    if change == "missing":
                        del actual["required_status_checks"]["checks"][index]
                    else:
                        actual["required_status_checks"]["checks"][index]["app_id"] = (
                            None if change == "unbound" else 1)
                    self.assertTrue(module.protection_errors(actual, POLICY))

    def test_absent_protection_and_each_weakened_flag_are_rejected(self):
        for actual in ({}, None, {"message": "Resource not accessible"}):
            self.assertTrue(module.protection_errors(actual, POLICY))
        for key in ("enforce_admins", "required_conversation_resolution",
                    "allow_force_pushes", "allow_deletions"):
            with self.subTest(key=key):
                actual = protected()
                actual[key]["enabled"] = not actual[key]["enabled"]
                self.assertTrue(module.protection_errors(actual, POLICY))
                del actual[key]
                self.assertTrue(module.protection_errors(actual, POLICY))
        actual = protected()
        actual["required_status_checks"]["strict"] = False
        self.assertTrue(module.protection_errors(actual, POLICY))

    def test_pr_requirement_stale_review_rule_and_bypass_are_independent(self):
        actual = protected()
        actual["required_pull_request_reviews"] = None
        self.assertTrue(module.protection_errors(actual, POLICY))
        actual = protected()
        actual["required_pull_request_reviews"]["dismiss_stale_reviews"] = False
        self.assertTrue(module.protection_errors(actual, POLICY))
        for key in ("users", "teams", "apps"):
            actual = protected()
            actual["required_pull_request_reviews"]["bypass_pull_request_allowances"] = {key: [{}]}
            self.assertTrue(module.protection_errors(actual, POLICY))

    def test_live_read_failure_is_not_pass_and_does_not_write(self):
        for error in (subprocess.CalledProcessError(1, ["gh", "api"]),
                      subprocess.TimeoutExpired(["gh", "api"], 30), FileNotFoundError()):
            with self.subTest(error=type(error).__name__), patch("sys.argv", ["check"]), \
                    patch.object(module.subprocess, "run", side_effect=error) as run:
                self.assertEqual(module.main(), 1)
                self.assertEqual(run.call_args.args[0], ["gh", "api", module.ENDPOINT])

    def test_malformed_readback_fails_at_cli(self):
        for raw in ("not-json", '{"required_status_checks": []}',
                    '{"required_status_checks": {"checks": [null]}}'):
            with self.subTest(raw=raw), patch("sys.argv", ["check"]), \
                    patch.object(module.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, raw)):
                self.assertEqual(module.main(), 1)


if __name__ == "__main__":
    unittest.main()
