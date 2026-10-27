package application

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/NoctilumeDev/GuiHongMail/internal/mailbox/domain"
	"github.com/google/uuid"
)

type ClassificationAlgorithm interface {
	Predict(context.Context, []domain.TrainingSample, []string) (domain.ModelPrediction, error)
}

type Classifier struct {
	repository domain.ClassificationRepository
	algorithm  ClassificationAlgorithm
}

func NewClassifier(repository domain.ClassificationRepository, algorithm ClassificationAlgorithm) *Classifier {
	return &Classifier{repository: repository, algorithm: algorithm}
}

func (c *Classifier) Rules(ctx context.Context, account string) ([]domain.ClassificationRule, error) {
	if err := validateID(account); err != nil {
		return nil, err
	}
	return c.repository.Rules(ctx, account)
}

func (c *Classifier) CreateRule(ctx context.Context, account string, value domain.ClassificationRule) (domain.ClassificationRule, error) {
	if err := validatePair(account, value.CategoryID); err != nil {
		return domain.ClassificationRule{}, err
	}
	value.ID = ""
	if err := normalizeRule(&value); err != nil {
		return domain.ClassificationRule{}, err
	}
	return c.repository.CreateRule(ctx, account, value)
}

func (c *Classifier) UpdateRule(ctx context.Context, account string, value domain.ClassificationRule) (domain.ClassificationRule, error) {
	if err := validateTriple(account, value.ID, value.CategoryID); err != nil {
		return domain.ClassificationRule{}, err
	}
	if value.Version < 1 {
		return domain.ClassificationRule{}, &domain.InvalidError{Code: "INVALID_VERSION"}
	}
	if err := normalizeRule(&value); err != nil {
		return domain.ClassificationRule{}, err
	}
	return c.repository.UpdateRule(ctx, account, value)
}

func (c *Classifier) DeleteRule(ctx context.Context, account, id string, version int64) error {
	if err := validatePair(account, id); err != nil {
		return err
	}
	if version < 1 {
		return &domain.InvalidError{Code: "INVALID_VERSION"}
	}
	return c.repository.DeleteRule(ctx, account, id, version)
}

func (c *Classifier) Settings(ctx context.Context, account string) (domain.ClassificationSettings, error) {
	if err := validateID(account); err != nil {
		return domain.ClassificationSettings{}, err
	}
	return c.repository.Settings(ctx, account)
}

func (c *Classifier) SetAlgorithmEnabled(ctx context.Context, account string, version int64, enabled bool) (domain.ClassificationSettings, error) {
	if err := validateID(account); err != nil {
		return domain.ClassificationSettings{}, err
	}
	if version < 1 {
		return domain.ClassificationSettings{}, &domain.InvalidError{Code: "INVALID_VERSION"}
	}
	return c.repository.SetAlgorithmEnabled(ctx, account, version, enabled)
}

func (c *Classifier) SetCategoryAuto(ctx context.Context, account, category string, enabled bool) (domain.ClassificationSettings, error) {
	if err := validatePair(account, category); err != nil {
		return domain.ClassificationSettings{}, err
	}
	return c.repository.SetCategoryAuto(ctx, account, category, enabled)
}

func (c *Classifier) Evaluate(ctx context.Context, account, entry string) (evaluation domain.ClassificationEvaluation, failure error) {
	if err := validatePair(account, entry); err != nil {
		return domain.ClassificationEvaluation{}, err
	}
	input, err := c.repository.ClassificationInput(ctx, account, entry)
	if err != nil {
		return domain.ClassificationEvaluation{}, err
	}
	defer func() {
		if failure == nil {
			failure = c.repository.MarkClassificationChecked(ctx, account, entry)
		}
	}()
	if input.CategorySource != nil && *input.CategorySource == "MANUAL_LOCKED" {
		return domain.ClassificationEvaluation{State: "MANUAL_LOCKED", Manual: true}, nil
	}
	if input.CategorySource != nil {
		if input.CategoryAction == nil {
			return domain.ClassificationEvaluation{State: "CLASSIFICATION_STATE_UNAVAILABLE"}, nil
		}
		suggestion, err := c.repository.CurrentClassification(ctx, account, entry, *input.CategoryAction)
		if err != nil {
			return domain.ClassificationEvaluation{}, err
		}
		return domain.ClassificationEvaluation{State: "AUTO_APPLIED", Suggestion: &suggestion}, nil
	}
	rules, err := c.repository.Rules(ctx, account)
	if err != nil {
		return domain.ClassificationEvaluation{}, err
	}
	matched := matchingRules(rules, input)
	if len(matched) > 0 {
		return c.evaluateRules(ctx, account, input, matched)
	}
	settings, err := c.repository.Settings(ctx, account)
	if err != nil {
		return domain.ClassificationEvaluation{}, err
	}
	if !settings.AlgorithmEnabled {
		return domain.ClassificationEvaluation{State: "ALGORITHM_DISABLED"}, nil
	}
	samples, err := c.repository.TrainingSamples(ctx, account, 1001)
	if err != nil {
		return domain.ClassificationEvaluation{}, err
	}
	if len(samples) > 1000 {
		return c.saveUnknown(ctx, account, input, "ALGORITHM", "TRAINING_LIMIT", nil)
	}
	features := domain.ClassificationFeatures(input.FromAddress, input.Subject)
	prediction, failure := c.algorithm.Predict(ctx, samples, features)
	if failure != nil {
		return c.saveUnknown(ctx, account, input, "ALGORITHM", "ALGORITHM_UNAVAILABLE", nil)
	}
	if prediction.Status != "PREDICTED" || prediction.CategoryID == nil {
		return c.saveUnknown(ctx, account, input, "ALGORITHM", prediction.Status, nil)
	}
	if err := c.repository.StoreModel(ctx, account, prediction); err != nil {
		return domain.ClassificationEvaluation{}, err
	}
	model := prediction.ModelVersion
	if prediction.Confidence < .80 || prediction.Margin < .25 || prediction.MatchedFeatures == 0 {
		return c.saveUnknown(ctx, account, input, "ALGORITHM", "LOW_CONFIDENCE", &model)
	}
	if !domain.HasClassificationEvidence(samples, features, *prediction.CategoryID) {
		return c.saveUnknownReason(ctx, account, input, "ALGORITHM", "INSUFFICIENT_EVIDENCE",
			"已命中特征不能区分预测类目与其他类目，保留未知；请手动分类或设置明确规则。", &model)
	}
	reason := fmt.Sprintf("本账户 %d 条确认历史，本地模型 %s，置信 %.1f%%，领先 %.1f%%", prediction.SampleCount, shortVersion(model), prediction.Confidence*100, prediction.Margin*100)
	suggestion := domain.ClassificationSuggestion{ID: uuid.NewString(), EntryID: entry, CategoryID: prediction.CategoryID, Source: "ALGORITHM", Status: "PENDING", Confidence: prediction.Confidence, Margin: prediction.Margin, Reason: reason, ModelVersion: &model, EntryVersion: input.Version}
	suggestion, err = c.repository.SaveSuggestion(ctx, account, input, suggestion)
	if err != nil {
		return domain.ClassificationEvaluation{}, err
	}
	if settings.CategoryAuto[*prediction.CategoryID] && prediction.Confidence >= .95 && prediction.Margin >= .40 {
		suggestion, err = c.repository.ApplySuggestion(ctx, account, entry, suggestion.ID, input.Version, "ALGORITHM_AUTO", false)
		if err != nil {
			return domain.ClassificationEvaluation{}, err
		}
		return domain.ClassificationEvaluation{State: "AUTO_APPLIED", Suggestion: &suggestion}, nil
	}
	return domain.ClassificationEvaluation{State: "SUGGESTED", Suggestion: &suggestion}, nil
}

func (c *Classifier) evaluateRules(ctx context.Context, account string, input domain.ClassificationInput, matched []domain.ClassificationRule) (domain.ClassificationEvaluation, error) {
	top := matched[0].Priority
	candidates := []domain.ClassificationRule{}
	categories := map[string]bool{}
	for _, rule := range matched {
		if rule.Priority != top {
			break
		}
		candidates = append(candidates, rule)
		categories[rule.CategoryID] = true
	}
	if len(categories) != 1 {
		conflicts := make([]string, 0, len(candidates))
		for _, candidate := range candidates {
			conflicts = append(conflicts, fmt.Sprintf("%s/v%d→%s", shortVersion(candidate.ID), candidate.Version, shortVersion(candidate.CategoryID)))
		}
		return c.saveUnknownReason(ctx, account, input, "RULE", "RULE_CONFLICT", "同优先级规则冲突："+strings.Join(conflicts, "、"), nil)
	}
	rule := candidates[0]
	reason := fmt.Sprintf("规则 %s v%d 命中 %s=%q，优先级 %d", shortVersion(rule.ID), rule.Version, rule.Type, rule.Pattern, rule.Priority)
	version := rule.Version
	ruleID := rule.ID
	suggestion := domain.ClassificationSuggestion{ID: uuid.NewString(), EntryID: input.EntryID, CategoryID: &rule.CategoryID, Source: "RULE", Status: "PENDING", Confidence: 1, Margin: 1, Reason: reason, RuleID: &ruleID, RuleVersion: &version, EntryVersion: input.Version}
	suggestion, err := c.repository.SaveSuggestion(ctx, account, input, suggestion)
	if err != nil {
		return domain.ClassificationEvaluation{}, err
	}
	if rule.AutoApply {
		suggestion, err = c.repository.ApplySuggestion(ctx, account, input.EntryID, suggestion.ID, input.Version, "RULE_AUTO", false)
		if err != nil {
			return domain.ClassificationEvaluation{}, err
		}
		return domain.ClassificationEvaluation{State: "AUTO_APPLIED", Suggestion: &suggestion}, nil
	}
	return domain.ClassificationEvaluation{State: "SUGGESTED", Suggestion: &suggestion}, nil
}

func (c *Classifier) saveUnknown(ctx context.Context, account string, input domain.ClassificationInput, source, reason string, model *string) (domain.ClassificationEvaluation, error) {
	return c.saveUnknownReason(ctx, account, input, source, reason, reason, model)
}

func (c *Classifier) saveUnknownReason(ctx context.Context, account string, input domain.ClassificationInput, source, state, reason string, model *string) (domain.ClassificationEvaluation, error) {
	suggestion := domain.ClassificationSuggestion{ID: uuid.NewString(), EntryID: input.EntryID, Source: source, Status: "UNKNOWN", Reason: reason, ModelVersion: model, EntryVersion: input.Version}
	suggestion, err := c.repository.SaveSuggestion(ctx, account, input, suggestion)
	if err != nil {
		return domain.ClassificationEvaluation{}, err
	}
	return domain.ClassificationEvaluation{State: state, Suggestion: &suggestion}, nil
}

func (c *Classifier) Decide(ctx context.Context, account, entry, suggestion, decision string, version int64) (domain.ClassificationSuggestion, error) {
	if err := validateTriple(account, entry, suggestion); err != nil {
		return domain.ClassificationSuggestion{}, err
	}
	switch strings.ToUpper(decision) {
	case "ACCEPT":
		if version < 1 {
			return domain.ClassificationSuggestion{}, &domain.InvalidError{Code: "INVALID_VERSION"}
		}
		return c.repository.ApplySuggestion(ctx, account, entry, suggestion, version, "MANUAL_LOCKED", true)
	case "REJECT":
		return c.repository.RejectSuggestion(ctx, account, entry, suggestion)
	default:
		return domain.ClassificationSuggestion{}, &domain.InvalidError{Code: "INVALID_CLASSIFICATION_DECISION"}
	}
}

func (c *Classifier) Undo(ctx context.Context, account, entry, action string, version int64) (domain.MessageDetail, error) {
	if err := validateTriple(account, entry, action); err != nil {
		return domain.MessageDetail{}, err
	}
	if version < 1 {
		return domain.MessageDetail{}, &domain.InvalidError{Code: "INVALID_VERSION"}
	}
	return c.repository.UndoClassification(ctx, account, entry, action, version)
}

func (c *Classifier) Run(ctx context.Context) error {
	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()
	for {
		if !c.repository.Available(ctx) {
			select {
			case <-ctx.Done():
				return nil
			case <-ticker.C:
				continue
			}
		}
		pending, err := c.repository.PendingClassification(ctx, 20)
		if err != nil {
			return err
		}
		for _, input := range pending {
			_, failure := c.Evaluate(ctx, input.AccountID, input.EntryID)
			var conflict *domain.VersionConflictError
			if failure != nil && !errors.As(failure, &conflict) {
				return failure
			}
			if failure == nil {
				if err := c.repository.MarkClassificationChecked(ctx, input.AccountID, input.EntryID); err != nil {
					return err
				}
			}
		}
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
		}
	}
}

func normalizeRule(value *domain.ClassificationRule) error {
	if !value.Type.Valid() || value.Priority < 0 || value.Priority > 1000 {
		return &domain.InvalidError{Code: "INVALID_CLASSIFICATION_RULE"}
	}
	value.Pattern = strings.ToLower(strings.TrimSpace(value.Pattern))
	if value.Pattern == "" || !utf8.ValidString(value.Pattern) || len([]rune(value.Pattern)) > 254 {
		return &domain.InvalidError{Code: "INVALID_CLASSIFICATION_RULE"}
	}
	switch value.Type {
	case domain.RuleFromAddress:
		if !mailboxAddress.MatchString(value.Pattern) {
			return &domain.InvalidError{Code: "INVALID_CLASSIFICATION_RULE"}
		}
	case domain.RuleFromDomain:
		if strings.ContainsAny(value.Pattern, "@/\\ \t\r\n") || !regexp.MustCompile(`^[a-z0-9.-]+$`).MatchString(value.Pattern) {
			return &domain.InvalidError{Code: "INVALID_CLASSIFICATION_RULE"}
		}
	case domain.RuleSubjectContains:
		if len([]rune(value.Pattern)) > 80 {
			return &domain.InvalidError{Code: "INVALID_CLASSIFICATION_RULE"}
		}
	}
	return nil
}

func matchingRules(rules []domain.ClassificationRule, input domain.ClassificationInput) []domain.ClassificationRule {
	address := strings.ToLower(strings.TrimSpace(input.FromAddress))
	domainValue := ""
	if at := strings.LastIndex(address, "@"); at >= 0 {
		domainValue = address[at+1:]
	}
	subject := strings.ToLower(input.Subject)
	matched := []domain.ClassificationRule{}
	for _, rule := range rules {
		if !rule.Enabled {
			continue
		}
		ok := false
		switch rule.Type {
		case domain.RuleFromAddress:
			ok = address == rule.Pattern
		case domain.RuleFromDomain:
			ok = domainValue == rule.Pattern
		case domain.RuleSubjectContains:
			ok = strings.Contains(subject, rule.Pattern)
		}
		if ok {
			matched = append(matched, rule)
		}
	}
	sort.Slice(matched, func(i, j int) bool {
		if matched[i].Priority != matched[j].Priority {
			return matched[i].Priority > matched[j].Priority
		}
		return matched[i].ID < matched[j].ID
	})
	return matched
}

func shortVersion(value string) string {
	if len(value) > 8 {
		return value[:8]
	}
	return value
}
