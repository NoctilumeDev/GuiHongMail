// Package mqprobe contains the deterministic identities and in-memory business
// ledger used by the M1G RocketMQ compatibility probe.
package mqprobe

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"regexp"
	"sync"
)

var runPattern = regexp.MustCompile(`^guihong-m1g-[0-9a-f]{32}$`)

// Binding is the complete owned identity of one probe run.
type Binding struct {
	Run   string `json:"run"`
	Topic string `json:"topic"`
	Group string `json:"group"`
}

// ValidateBinding rejects cross-run or non-owned RocketMQ resources.
func ValidateBinding(binding Binding) error {
	if !runPattern.MatchString(binding.Run) {
		return fmt.Errorf("invalid run identity")
	}
	if binding.Topic != binding.Run+"-topic" {
		return fmt.Errorf("topic does not belong to run")
	}
	if binding.Group != binding.Run+"-group" {
		return fmt.Errorf("group does not belong to run")
	}
	return nil
}

// Payload returns the exact bytes sent for one logical message.
func Payload(run, kind string) ([]byte, error) {
	if !runPattern.MatchString(run) {
		return nil, fmt.Errorf("invalid run identity")
	}
	if kind != "stored-before-restart" && kind != "sent-after-consumer" {
		return nil, fmt.Errorf("invalid message kind")
	}
	return json.Marshal(struct {
		Run  string `json:"run"`
		Kind string `json:"kind"`
	}{Run: run, Kind: kind})
}

// Key returns the single RocketMQ key for one logical message.
func Key(run, kind string) (string, error) {
	if _, err := Payload(run, kind); err != nil {
		return "", err
	}
	return run + "-" + kind, nil
}

// SHA256 returns the lower-case digest of bytes.
func SHA256(value []byte) string {
	digest := sha256.Sum256(value)
	return hex.EncodeToString(digest[:])
}

// Attempt is a single callback decision captured by the probe.
type Attempt struct {
	Key            string `json:"key"`
	MessageID      string `json:"message_id"`
	BodySHA256     string `json:"body_sha256"`
	ReconsumeTimes int32  `json:"reconsume_times"`
	Decision       string `json:"decision"`
	Reason         string `json:"reason"`
}

// Fact is an idempotent business effect, distinct from delivery attempts.
type Fact struct {
	Key        string `json:"key"`
	MessageID  string `json:"message_id"`
	BodySHA256 string `json:"body_sha256"`
}

// Ledger applies the fixed M1G retry and idempotency rules.
type Ledger struct {
	mu       sync.Mutex
	expected map[string]string
	retryKey string
	attempts []Attempt
	facts    map[string]Fact
}

// NewLedger creates a ledger. retryKey must be one of the expected keys.
func NewLedger(expected map[string]string, retryKey string) (*Ledger, error) {
	if len(expected) != 2 {
		return nil, fmt.Errorf("exactly two expected messages required")
	}
	if _, ok := expected[retryKey]; !ok {
		return nil, fmt.Errorf("retry key is not expected")
	}
	copyExpected := make(map[string]string, len(expected))
	for key, digest := range expected {
		if key == "" || len(digest) != sha256.Size*2 {
			return nil, fmt.Errorf("invalid expected message")
		}
		copyExpected[key] = digest
	}
	return &Ledger{expected: copyExpected, retryKey: retryKey, facts: make(map[string]Fact)}, nil
}

// Observe returns true when RocketMQ should retry this delivery.
func (ledger *Ledger) Observe(key, messageID string, body []byte, reconsumeTimes int32) bool {
	ledger.mu.Lock()
	defer ledger.mu.Unlock()

	digest := SHA256(body)
	attempt := Attempt{Key: key, MessageID: messageID, BodySHA256: digest, ReconsumeTimes: reconsumeTimes}
	expectedDigest, known := ledger.expected[key]
	if !known {
		attempt.Decision = "RETRY"
		attempt.Reason = "unknown-key"
		ledger.attempts = append(ledger.attempts, attempt)
		return true
	}
	if digest != expectedDigest {
		attempt.Decision = "RETRY"
		attempt.Reason = "body-hash-mismatch"
		ledger.attempts = append(ledger.attempts, attempt)
		return true
	}
	if key == ledger.retryKey && ledger.countLocked(key) == 0 {
		attempt.Decision = "RETRY"
		attempt.Reason = "sealed-first-attempt"
		ledger.attempts = append(ledger.attempts, attempt)
		return true
	}
	if _, exists := ledger.facts[key]; exists {
		attempt.Decision = "SUCCESS"
		attempt.Reason = "duplicate-no-new-fact"
		ledger.attempts = append(ledger.attempts, attempt)
		return false
	}
	attempt.Decision = "SUCCESS"
	attempt.Reason = "new-business-fact"
	ledger.attempts = append(ledger.attempts, attempt)
	ledger.facts[key] = Fact{Key: key, MessageID: messageID, BodySHA256: digest}
	return false
}

func (ledger *Ledger) countLocked(key string) int {
	count := 0
	for _, attempt := range ledger.attempts {
		if attempt.Key == key {
			count++
		}
	}
	return count
}

// Snapshot copies all observations without exposing mutable ledger state.
func (ledger *Ledger) Snapshot() ([]Attempt, []Fact) {
	ledger.mu.Lock()
	defer ledger.mu.Unlock()
	attempts := append([]Attempt(nil), ledger.attempts...)
	facts := make([]Fact, 0, len(ledger.facts))
	for _, fact := range ledger.facts {
		facts = append(facts, fact)
	}
	return attempts, facts
}

// Complete proves the finite two-message outcome and explicit retry.
func (ledger *Ledger) Complete() bool {
	ledger.mu.Lock()
	defer ledger.mu.Unlock()
	if len(ledger.facts) != len(ledger.expected) {
		return false
	}
	retryAttempts := 0
	retrySuccess := false
	for _, attempt := range ledger.attempts {
		if attempt.Key == ledger.retryKey {
			retryAttempts++
			if attempt.Decision == "SUCCESS" {
				retrySuccess = true
			}
		}
	}
	return retryAttempts >= 2 && retrySuccess
}
