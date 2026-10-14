package platform

import "testing"

func TestTokenForInternalTargetUsesTargetCredential(t *testing.T) {
	config := Config{InternalTokens: map[string]string{"mailbox": "mailbox-secret", "ingress": "ingress-secret", "delivery": "delivery-secret"}}
	token, err := tokenForInternalTarget(config, "http://127.0.0.1:18080/internal/send-intents/id/raw")
	if err != nil || token != "mailbox-secret" {
		t.Fatalf("mailbox target credential mismatch: token=%q err=%v", token, err)
	}
	for _, target := range []string{"https://127.0.0.1:18080/internal/x", "http://localhost:18080/internal/x", "http://127.0.0.1:19000/internal/x"} {
		if _, err := tokenForInternalTarget(config, target); err == nil {
			t.Fatalf("unexpected internal target accepted: %s", target)
		}
	}
}
