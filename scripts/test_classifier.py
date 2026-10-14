#!/usr/bin/env python3
"""Deterministic contract tests for the isolated M4 classifier."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "algorithm" / "classifier.py"
CONTRACT = "guihong-classifier/1"
ALGORITHM = "multinomial-nb/1"
CATEGORY_A = "11111111-1111-4111-8111-111111111111"
CATEGORY_B = "22222222-2222-4222-8222-222222222222"


def feature(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def request(samples: list[dict[str, object]], features: list[str]) -> dict[str, object]:
    payload = {"contract": CONTRACT, "algorithm": ALGORITHM, "samples": samples, "query": {"features": features}}
    isolated_env = {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    for name in ("SystemRoot", "WINDIR"):
        if os.environ.get(name):
            isolated_env[name] = os.environ[name]
    process = subprocess.run(
        [sys.executable, "-I", str(SCRIPT)], input=json.dumps(payload).encode(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=3,
        env=isolated_env,
    )
    if process.returncode:
        raise AssertionError(process.stderr.decode(errors="replace"))
    return json.loads(process.stdout)


class ClassifierContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.a = feature("from:alice@example.test")
        self.b = feature("from:bob@example.test")
        categories = [CATEGORY_A] * 3 + [CATEGORY_B] * 3
        values = [self.a] * 3 + [self.b] * 3
        self.samples = [
            {"sample_id": f"00000000-0000-4000-8000-{index:012d}", "category_id": category, "features": [value]}
            for index, (category, value) in enumerate(zip(categories, values), 1)
        ]

    def test_prediction_is_deterministic_and_bounded(self) -> None:
        first = request(self.samples, [self.a])
        second = request(list(reversed(self.samples)), [self.a])
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "PREDICTED")
        self.assertEqual(first["category_id"], CATEGORY_A)
        self.assertEqual(first["sample_count"], 6)
        self.assertGreaterEqual(first["confidence"], 0.8)
        self.assertGreaterEqual(first["margin"], 0.25)
        self.assertEqual(first["matched_features"], 1)
        self.assertEqual(len(first["sample_digest"]), 64)
        self.assertEqual(len(first["model_version"]), 64)
        encoded = json.dumps(first, sort_keys=True)
        self.assertNotIn("alice@example.test", encoded)
        self.assertLess(len(encoded.encode()), 1024 * 1024)

    def test_cold_start_does_not_invent_a_category(self) -> None:
        result = request(self.samples[:2], [self.a])
        self.assertEqual(result, {"contract": CONTRACT, "algorithm": ALGORITHM, "status": "COLD_START"})

    def test_invalid_identifier_is_rejected(self) -> None:
        broken = [dict(self.samples[0], sample_id="-" * 36)]
        result = request(broken, [self.a])
        self.assertEqual(result["status"], "INPUT_INVALID")


if __name__ == "__main__":
    unittest.main()
