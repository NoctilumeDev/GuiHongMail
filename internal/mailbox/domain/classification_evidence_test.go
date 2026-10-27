package domain

import "testing"

func TestClassificationEvidence(t *testing.T) {
	samples := []TrainingSample{
		{CategoryID: "a", Features: []string{"shared", "a-only", "mostly-b"}},
		{CategoryID: "a", Features: []string{"shared", "a-only"}},
		{CategoryID: "b", Features: []string{"shared", "b-only", "mostly-b"}},
		{CategoryID: "b", Features: []string{"shared", "b-only", "mostly-b"}},
	}
	for _, tc := range []struct {
		name, category string
		query          []string
		want           bool
	}{
		{"common sender only", "a", []string{"shared"}, false},
		{"unknown title", "a", []string{"shared", "unseen"}, false},
		{"candidate has distinct support", "a", []string{"shared", "a-only"}, true},
		{"other class's support is not candidate support", "a", []string{"shared", "b-only"}, false},
		{"normalized evidence for minority", "b", []string{"mostly-b"}, true},
		{"weaker evidence cannot support majority", "a", []string{"mostly-b"}, false},
		{"unknown category", "absent", []string{"a-only"}, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			for _, repeats := range []int{1, 30, 120} {
				var skewed []TrainingSample
				for _, sample := range samples {
					n := 1
					if sample.CategoryID == "a" {
						n = repeats
					}
					for i := 0; i < n; i++ {
						skewed = append(skewed, sample)
					}
				}
				if got := HasClassificationEvidence(skewed, tc.query, tc.category); got != tc.want {
					t.Fatalf("repeats=%d got=%v want=%v", repeats, got, tc.want)
				}
			}
		})
	}
	if HasClassificationEvidence(samples[:2], []string{"a-only"}, "a") {
		t.Fatal("single-class history is insufficient")
	}
	if HasClassificationEvidence(samples, nil, "a") {
		t.Fatal("empty query is insufficient")
	}
	duplicates := []TrainingSample{{CategoryID: "a", Features: []string{"same", "same"}}, {CategoryID: "b", Features: []string{"same"}}}
	if HasClassificationEvidence(duplicates, []string{"same", "same"}, "a") {
		t.Fatal("duplicate tokens must not inflate support")
	}
}
