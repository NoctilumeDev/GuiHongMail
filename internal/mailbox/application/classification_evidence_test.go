package application_test

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"testing"

	"github.com/NoctilumeDev/GuiHongMail/internal/mailbox/application"
	"github.com/NoctilumeDev/GuiHongMail/internal/mailbox/domain"
	"github.com/NoctilumeDev/GuiHongMail/internal/mailbox/infrastructure"
)

// Exercise the real feature extraction, Python predictor and Go decision gate.
// Only persistence is replaced; no real user's mail or training data is involved.
func TestClassificationEvidenceWithRealPredictor(t *testing.T) {
	python := os.Getenv("GUIHONG_TEST_PYTHON")
	if python == "" {
		for _, name := range []string{"python3", "python"} {
			if path, err := exec.LookPath(name); err == nil {
				python = path
				break
			}
		}
	}
	if python == "" {
		t.Fatal("Python 3 is required for the classifier integration test")
	}
	algorithm := infrastructure.NewPythonClassifier(python, filepath.Join("..", "..", "..", "algorithm", "classifier.py"))
	titles := []string{"学费缴费通知", "课程考试安排", "旅行酒店预订"}
	for _, tc := range []struct {
		name           string
		counts         []int
		distinctSender bool
		subject        string
		want           string
	}{
		{"imbalanced unseen title", []int{120, 4, 4}, false, "课程考试安排第100期", "INSUFFICIENT_EVIDENCE"},
		{"balanced unseen title", []int{12, 12, 12}, false, "课程考试安排第100期", "LOW_CONFIDENCE"},
		{"distinct sender remains useful", []int{12, 12, 12}, true, "课程考试安排第100期", "AUTO_APPLIED"},
		{"known minority title rejects unsupported majority", []int{120, 4, 4}, false, "课程考试安排第1期", "INSUFFICIENT_EVIDENCE"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r := &classificationRepository{auto: true, input: domain.ClassificationInput{AccountID: fixtureID(1000), EntryID: fixtureID(1001), Version: 1, FromAddress: "notice@campus.test", Subject: tc.subject}}
			if tc.distinctSender {
				r.input.FromAddress = "notice@dept1.test"
			}
			for category, count := range tc.counts {
				for i := 0; i < count; i++ {
					from := "notice@campus.test"
					if tc.distinctSender {
						from = fmt.Sprintf("notice@dept%d.test", category)
					}
					r.samples = append(r.samples, domain.TrainingSample{ID: fixtureID(len(r.samples) + 10), CategoryID: fixtureID(category + 1), Features: domain.ClassificationFeatures(from, fmt.Sprintf("%s第%d期", titles[category], i))})
				}
			}
			result, err := application.NewClassifier(r, algorithm).Evaluate(context.Background(), r.input.AccountID, r.input.EntryID)
			if err != nil {
				t.Fatal(err)
			}
			if result.State != tc.want {
				t.Fatalf("want %s, got %s; raw score=%f matched=%d applied=%d", tc.want, result.State, r.model.Confidence, r.model.MatchedFeatures, r.applied)
			}
			if tc.want == "AUTO_APPLIED" {
				if r.applied != 1 || r.saved.CategoryID == nil || *r.saved.CategoryID != fixtureID(2) {
					t.Fatalf("normal automatic classification lost: %#v", r.saved)
				}
				// The evidence gate does not grant auto-apply permission.
				r.auto, r.applied = false, 0
				onlySuggested, err := application.NewClassifier(r, algorithm).Evaluate(context.Background(), r.input.AccountID, r.input.EntryID)
				if err != nil || onlySuggested.State != "SUGGESTED" || r.applied != 0 || r.saved.Status != "PENDING" {
					t.Fatalf("category opt-in was bypassed: %#v, %v", onlySuggested, err)
				}
			} else if r.applied != 0 || r.saved.CategoryID != nil || r.saved.Status != "UNKNOWN" {
				t.Fatalf("unsupported classification changed a category: %#v", r.saved)
			}
			if !r.checked {
				t.Fatal("classification check was not recorded")
			}
		})
	}
}

type classificationRepository struct {
	domain.ClassificationRepository
	input   domain.ClassificationInput
	samples []domain.TrainingSample
	rules   []domain.ClassificationRule
	auto    bool
	saved   domain.ClassificationSuggestion
	model   domain.ModelPrediction
	applied int
	checked bool
}

type forbiddenAlgorithm struct{}

func (forbiddenAlgorithm) Predict(context.Context, []domain.TrainingSample, []string) (domain.ModelPrediction, error) {
	panic("manual or rule decisions must not invoke the algorithm")
}

func TestClassificationEvidencePreservesManualAndRulePriority(t *testing.T) {
	for _, manual := range []bool{false, true} {
		r := &classificationRepository{input: domain.ClassificationInput{AccountID: fixtureID(1000), EntryID: fixtureID(1001), Version: 1, FromAddress: "notice@campus.test", Subject: "课程考试安排"}}
		r.rules = []domain.ClassificationRule{{ID: fixtureID(2000), CategoryID: fixtureID(2), Type: domain.RuleFromAddress, Pattern: "notice@campus.test", Enabled: true, AutoApply: true, Version: 1}}
		if manual {
			source := "MANUAL_LOCKED"
			r.input.CategorySource = &source
		}
		result, err := application.NewClassifier(r, forbiddenAlgorithm{}).Evaluate(context.Background(), r.input.AccountID, r.input.EntryID)
		if err != nil {
			t.Fatal(err)
		}
		if manual {
			if result.State != "MANUAL_LOCKED" || r.applied != 0 {
				t.Fatal("manual ownership changed")
			}
		} else if result.State != "AUTO_APPLIED" || r.saved.Source != "RULE" || r.applied != 1 {
			t.Fatal("explicit rule priority changed")
		}
	}
}

func fixtureID(i int) string { return fmt.Sprintf("00000000-0000-4000-8000-%012d", i) }
func (r *classificationRepository) ClassificationInput(context.Context, string, string) (domain.ClassificationInput, error) {
	return r.input, nil
}
func (r *classificationRepository) MarkClassificationChecked(context.Context, string, string) error {
	r.checked = true
	return nil
}
func (r *classificationRepository) Rules(context.Context, string) ([]domain.ClassificationRule, error) {
	return r.rules, nil
}
func (r *classificationRepository) Settings(context.Context, string) (domain.ClassificationSettings, error) {
	return domain.ClassificationSettings{AlgorithmEnabled: true, CategoryAuto: map[string]bool{fixtureID(1): r.auto, fixtureID(2): r.auto, fixtureID(3): r.auto}}, nil
}
func (r *classificationRepository) TrainingSamples(context.Context, string, int) ([]domain.TrainingSample, error) {
	return r.samples, nil
}
func (r *classificationRepository) StoreModel(_ context.Context, _ string, p domain.ModelPrediction) error {
	r.model = p
	return nil
}
func (r *classificationRepository) SaveSuggestion(_ context.Context, _ string, _ domain.ClassificationInput, s domain.ClassificationSuggestion) (domain.ClassificationSuggestion, error) {
	r.saved = s
	return s, nil
}
func (r *classificationRepository) ApplySuggestion(context.Context, string, string, string, int64, string, bool) (domain.ClassificationSuggestion, error) {
	r.applied++
	r.saved.Status = "APPLIED"
	return r.saved, nil
}
