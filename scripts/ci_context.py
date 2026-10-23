"""Retain a small, allowlisted CI identity, not environment dumps or a verdict."""
import json
import os
from pathlib import Path
import platform
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def context(environment, checkout):
    return {
        "checkout_sha": checkout,
        "github": {key: environment.get(key) for key in (
            "GITHUB_REPOSITORY", "GITHUB_EVENT_NAME", "GITHUB_SHA",
            "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB", "RUNNER_OS")},
        "python": platform.python_version(),
        "boundary": "CHECKOUT_IDENTITY_ONLY_NOT_TEST_RESULT",
    }


def main():
    checkout = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, encoding="utf-8").strip()
    output = ROOT / "artifacts/local/ci/checkout.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(context(os.environ, checkout), stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
