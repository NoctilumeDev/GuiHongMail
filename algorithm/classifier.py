#!/usr/bin/env python3
"""Bounded stateless GuiHong classification contract; standard library only."""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict

CONTRACT = "guihong-classifier/1"
ALGORITHM = "multinomial-nb/1"
HEX = re.compile(r"^[0-9a-f]{64}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def fail(code: str) -> None:
    print(json.dumps({"contract": CONTRACT, "algorithm": ALGORITHM, "status": code}, separators=(",", ":")))
    raise SystemExit(0)


def main() -> None:
    raw = sys.stdin.buffer.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        fail("INPUT_TOO_LARGE")
    try:
        request = json.loads(raw)
    except Exception:
        fail("INPUT_INVALID")
    if not isinstance(request, dict):
        fail("INPUT_INVALID")
    if request.get("contract") != CONTRACT or request.get("algorithm") != ALGORITHM:
        fail("CONTRACT_MISMATCH")
    samples = request.get("samples")
    query = request.get("query")
    if not isinstance(samples, list) or len(samples) > 1000 or not isinstance(query, dict):
        fail("INPUT_INVALID")
    normalized = []
    category_counts: Counter[str] = Counter()
    feature_counts: dict[str, Counter[str]] = defaultdict(Counter)
    feature_totals: Counter[str] = Counter()
    vocabulary: set[str] = set()
    sample_ids: set[str] = set()
    for sample in samples:
        if not isinstance(sample, dict):
            fail("INPUT_INVALID")
        category = sample.get("category_id")
        sample_id = sample.get("sample_id")
        features = sample.get("features")
        if not isinstance(category, str) or not UUID.fullmatch(category) or not isinstance(sample_id, str) or not UUID.fullmatch(sample_id):
            fail("INPUT_INVALID")
        if not isinstance(features, list) or len(features) > 64 or any(not isinstance(v, str) or not HEX.fullmatch(v) for v in features):
            fail("INPUT_INVALID")
        if sample_id in sample_ids:
            fail("INPUT_INVALID")
        sample_ids.add(sample_id)
        clean = sorted(set(features))
        normalized.append({"sample_id": sample_id, "category_id": category, "features": clean})
        category_counts[category] += 1
        feature_counts[category].update(clean)
        feature_totals[category] += len(clean)
        vocabulary.update(clean)
        if len(category_counts) > 50:
            fail("INPUT_INVALID")
    query_features = query.get("features")
    if not isinstance(query_features, list) or len(query_features) > 64 or any(not isinstance(v, str) or not HEX.fullmatch(v) for v in query_features):
        fail("INPUT_INVALID")
    query_features = sorted(set(query_features))
    if len(samples) < 6 or len(category_counts) < 2 or any(count < 2 for count in category_counts.values()):
        fail("COLD_START")
    if not query_features:
        fail("EMPTY_FEATURES")
    categories = sorted(category_counts)
    vocab_size = max(1, len(vocabulary))
    scores: dict[str, float] = {}
    for category in categories:
        score = math.log(category_counts[category] / len(samples))
        denominator = feature_totals[category] + vocab_size
        for feature in query_features:
            score += math.log((feature_counts[category][feature] + 1) / denominator)
        scores[category] = score
    maximum = max(scores.values())
    weights = {category: math.exp(score - maximum) for category, score in scores.items()}
    total = sum(weights.values())
    probabilities = sorted(((weight / total, category) for category, weight in weights.items()), reverse=True)
    confidence, category = probabilities[0]
    second = probabilities[1][0] if len(probabilities) > 1 else 0.0
    model = {
        "algorithm": ALGORITHM,
        "category_counts": dict(sorted(category_counts.items())),
        "feature_counts": {key: dict(sorted(value.items())) for key, value in sorted(feature_counts.items())},
        "feature_totals": dict(sorted(feature_totals.items())),
        "vocabulary_size": vocab_size,
    }
    response = {
        "contract": CONTRACT,
        "algorithm": ALGORITHM,
        "status": "PREDICTED",
        "category_id": category,
        "confidence": confidence,
        "margin": confidence - second,
        "sample_count": len(samples),
        "category_counts": dict(sorted(category_counts.items())),
        "sample_digest": digest(sorted(normalized, key=lambda row: row["sample_id"])),
        "model_version": digest(model),
        "model": model,
        "matched_features": sum(1 for value in query_features if feature_counts[category][value] > 0),
    }
    encoded = canonical(response)
    if len(encoded) > 1024 * 1024:
        fail("OUTPUT_TOO_LARGE")
    sys.stdout.buffer.write(encoded + b"\n")


if __name__ == "__main__":
    main()
