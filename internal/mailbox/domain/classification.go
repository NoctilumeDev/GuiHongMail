package domain

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"strings"
	"time"
	"unicode"
)

type RuleType string

const (
	RuleFromAddress     RuleType = "FROM_ADDRESS"
	RuleFromDomain      RuleType = "FROM_DOMAIN"
	RuleSubjectContains RuleType = "SUBJECT_CONTAINS"
)

func (kind RuleType) Valid() bool {
	switch kind {
	case RuleFromAddress, RuleFromDomain, RuleSubjectContains:
		return true
	default:
		return false
	}
}

type ClassificationRule struct {
	ID         string    `json:"id"`
	CategoryID string    `json:"categoryId"`
	Type       RuleType  `json:"type"`
	Pattern    string    `json:"pattern"`
	Priority   int       `json:"priority"`
	AutoApply  bool      `json:"autoApply"`
	Enabled    bool      `json:"enabled"`
	Version    int64     `json:"version"`
	CreatedAt  time.Time `json:"createdAt"`
	UpdatedAt  time.Time `json:"updatedAt"`
}

type ClassificationSettings struct {
	AlgorithmEnabled bool            `json:"algorithmEnabled"`
	Version          int64           `json:"version"`
	CategoryAuto     map[string]bool `json:"categoryAuto"`
}

type ClassificationInput struct {
	EntryID        string
	AccountID      string
	CategoryID     *string
	CategorySource *string
	CategoryAction *string
	Version        int64
	Folder         Folder
	Read           bool
	FromAddress    string
	Subject        string
}

type TrainingSample struct {
	ID         string   `json:"sample_id"`
	CategoryID string   `json:"category_id"`
	Features   []string `json:"features"`
}

type ModelPrediction struct {
	Status          string         `json:"status"`
	CategoryID      *string        `json:"category_id"`
	Confidence      float64        `json:"confidence"`
	Margin          float64        `json:"margin"`
	SampleCount     int            `json:"sample_count"`
	CategoryCounts  map[string]int `json:"category_counts"`
	SampleDigest    string         `json:"sample_digest"`
	ModelVersion    string         `json:"model_version"`
	Model           any            `json:"model"`
	MatchedFeatures int            `json:"matched_features"`
}

type ClassificationSuggestion struct {
	ID           string    `json:"id"`
	EntryID      string    `json:"entryId"`
	CategoryID   *string   `json:"categoryId"`
	Source       string    `json:"source"`
	Status       string    `json:"status"`
	Confidence   float64   `json:"confidence"`
	Margin       float64   `json:"margin"`
	Reason       string    `json:"reason"`
	RuleID       *string   `json:"ruleId"`
	RuleVersion  *int64    `json:"ruleVersion"`
	ModelVersion *string   `json:"modelVersion"`
	EntryVersion int64     `json:"entryVersion"`
	ActionID     *string   `json:"actionId,omitempty"`
	CreatedAt    time.Time `json:"createdAt"`
}

type ClassificationEvaluation struct {
	State      string                    `json:"state"`
	Manual     bool                      `json:"manual"`
	Suggestion *ClassificationSuggestion `json:"suggestion"`
}

type ClassificationRepository interface {
	Available(context.Context) bool
	Rules(context.Context, string) ([]ClassificationRule, error)
	CreateRule(context.Context, string, ClassificationRule) (ClassificationRule, error)
	UpdateRule(context.Context, string, ClassificationRule) (ClassificationRule, error)
	DeleteRule(context.Context, string, string, int64) error
	Settings(context.Context, string) (ClassificationSettings, error)
	SetAlgorithmEnabled(context.Context, string, int64, bool) (ClassificationSettings, error)
	SetCategoryAuto(context.Context, string, string, bool) (ClassificationSettings, error)
	ClassificationInput(context.Context, string, string) (ClassificationInput, error)
	CurrentClassification(context.Context, string, string, string) (ClassificationSuggestion, error)
	TrainingSamples(context.Context, string, int) ([]TrainingSample, error)
	StoreModel(context.Context, string, ModelPrediction) error
	SaveSuggestion(context.Context, string, ClassificationInput, ClassificationSuggestion) (ClassificationSuggestion, error)
	ApplySuggestion(context.Context, string, string, string, int64, string, bool) (ClassificationSuggestion, error)
	RejectSuggestion(context.Context, string, string, string) (ClassificationSuggestion, error)
	UndoClassification(context.Context, string, string, string, int64) (MessageDetail, error)
	PendingClassification(context.Context, int) ([]ClassificationInput, error)
	MarkClassificationChecked(context.Context, string, string) error
}

func ClassificationFeatures(fromAddress, subject string) []string {
	values := []string{}
	address := strings.ToLower(strings.TrimSpace(fromAddress))
	if address != "" {
		values = append(values, "from:"+address)
		if at := strings.LastIndex(address, "@"); at >= 0 && at+1 < len(address) {
			values = append(values, "domain:"+address[at+1:])
		}
	}
	var token []rune
	flush := func() {
		if len(token) == 0 {
			return
		}
		values = append(values, "subject:"+strings.ToLower(string(token)))
		token = nil
	}
	for _, r := range strings.TrimSpace(subject) {
		if unicode.IsLetter(r) || unicode.IsNumber(r) {
			token = append(token, unicode.ToLower(r))
		} else {
			flush()
		}
	}
	flush()
	if len(values) > 64 {
		values = values[:64]
	}
	result := make([]string, 0, len(values))
	seen := map[string]bool{}
	for _, value := range values {
		sum := sha256.Sum256([]byte(value))
		digest := hex.EncodeToString(sum[:])
		if !seen[digest] {
			seen[digest] = true
			result = append(result, digest)
		}
	}
	return result
}
