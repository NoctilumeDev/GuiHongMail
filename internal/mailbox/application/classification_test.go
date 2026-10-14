package application

import (
	"testing"

	"github.com/NoctilumeDev/GuiHongMail/internal/mailbox/domain"
)

func TestMatchingRulesOrdersPriorityAndPreservesConflict(t *testing.T) {
	input := domain.ClassificationInput{FromAddress: "Alice@Example.TEST", Subject: "Quarterly report"}
	rules := []domain.ClassificationRule{
		{ID: "b", CategoryID: "two", Type: domain.RuleFromDomain, Pattern: "example.test", Priority: 10, Enabled: true},
		{ID: "a", CategoryID: "one", Type: domain.RuleFromAddress, Pattern: "alice@example.test", Priority: 10, Enabled: true},
		{ID: "c", CategoryID: "three", Type: domain.RuleSubjectContains, Pattern: "report", Priority: 5, Enabled: true},
		{ID: "disabled", CategoryID: "four", Type: domain.RuleSubjectContains, Pattern: "quarterly", Priority: 20, Enabled: false},
	}
	matched := matchingRules(rules, input)
	if len(matched) != 3 || matched[0].ID != "a" || matched[1].ID != "b" || matched[2].ID != "c" {
		t.Fatalf("unexpected rule order: %#v", matched)
	}
	if matched[0].Priority != matched[1].Priority || matched[0].CategoryID == matched[1].CategoryID {
		t.Fatal("top-priority conflict fixture no longer proves different-category conflict")
	}
}

func TestNormalizeRuleRejectsUnsafeOrUnboundedPatterns(t *testing.T) {
	for _, rule := range []domain.ClassificationRule{
		{Type: domain.RuleFromAddress, Pattern: "not-address", Priority: 1},
		{Type: domain.RuleFromDomain, Pattern: "https://example.test", Priority: 1},
		{Type: domain.RuleSubjectContains, Pattern: string(make([]rune, 81)), Priority: 1},
		{Type: domain.RuleSubjectContains, Pattern: "ok", Priority: 1001},
	} {
		if err := normalizeRule(&rule); err == nil {
			t.Fatalf("accepted invalid rule: %#v", rule)
		}
	}
}
