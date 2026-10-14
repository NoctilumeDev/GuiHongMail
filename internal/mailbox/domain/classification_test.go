package domain

import (
	"encoding/hex"
	"testing"
)

func TestClassificationFeaturesExposeOnlyStableDigests(t *testing.T) {
	features := ClassificationFeatures(" Alice@Example.TEST ", "Quarterly 报告, quarterly")
	if len(features) != 4 {
		t.Fatalf("expected de-duplicated address, domain and subject features, got %d: %#v", len(features), features)
	}
	for _, value := range features {
		decoded, err := hex.DecodeString(value)
		if err != nil || len(decoded) != 32 {
			t.Fatalf("feature is not a SHA-256 digest: %q", value)
		}
	}
	again := ClassificationFeatures("alice@example.test", "quarterly 报告 quarterly")
	if len(again) != len(features) {
		t.Fatalf("normalization changed feature cardinality: %#v %#v", features, again)
	}
	for index := range features {
		if features[index] != again[index] {
			t.Fatalf("normalization is not deterministic: %#v %#v", features, again)
		}
	}
}

func TestClassificationFeaturesEnforceFeatureLimit(t *testing.T) {
	subject := ""
	for index := 0; index < 100; index++ {
		subject += " token"
	}
	if count := len(ClassificationFeatures("a@example.test", subject)); count > 64 {
		t.Fatalf("feature limit exceeded: %d", count)
	}
}
