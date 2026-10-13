package mqprobe

import "testing"

func testBinding() Binding {
	run := "guihong-m1g-0123456789abcdef0123456789abcdef"
	return Binding{Run: run, Topic: run + "-topic", Group: run + "-group"}
}

func TestValidateBindingRejectsCrossRunResources(t *testing.T) {
	binding := testBinding()
	if err := ValidateBinding(binding); err != nil {
		t.Fatalf("valid binding rejected: %v", err)
	}
	binding.Topic = "guihong-m1g-fedcba9876543210fedcba9876543210-topic"
	if err := ValidateBinding(binding); err == nil {
		t.Fatal("cross-run topic accepted")
	}
}

func TestLedgerSeparatesRetryFromIdempotentBusinessFacts(t *testing.T) {
	binding := testBinding()
	bodyA, _ := Payload(binding.Run, "stored-before-restart")
	bodyB, _ := Payload(binding.Run, "sent-after-consumer")
	keyA, _ := Key(binding.Run, "stored-before-restart")
	keyB, _ := Key(binding.Run, "sent-after-consumer")
	ledger, err := NewLedger(map[string]string{keyA: SHA256(bodyA), keyB: SHA256(bodyB)}, keyA)
	if err != nil {
		t.Fatal(err)
	}
	if retry := ledger.Observe(keyA, "msg-a", bodyA, 0); !retry {
		t.Fatal("sealed first attempt was acknowledged")
	}
	if retry := ledger.Observe(keyB, "msg-b", bodyB, 0); retry {
		t.Fatal("normal message was retried")
	}
	if retry := ledger.Observe(keyA, "msg-a-retry", bodyA, 1); retry {
		t.Fatal("valid retry was not acknowledged")
	}
	if retry := ledger.Observe(keyA, "msg-a-duplicate", bodyA, 2); retry {
		t.Fatal("valid duplicate was not acknowledged")
	}
	if !ledger.Complete() {
		t.Fatal("finite outcome did not complete")
	}
	_, facts := ledger.Snapshot()
	if len(facts) != 2 {
		t.Fatalf("got %d business facts, want 2", len(facts))
	}
}

func TestLedgerNeverAcknowledgesWrongHash(t *testing.T) {
	binding := testBinding()
	bodyA, _ := Payload(binding.Run, "stored-before-restart")
	bodyB, _ := Payload(binding.Run, "sent-after-consumer")
	keyA, _ := Key(binding.Run, "stored-before-restart")
	keyB, _ := Key(binding.Run, "sent-after-consumer")
	ledger, _ := NewLedger(map[string]string{keyA: SHA256(bodyA), keyB: SHA256(bodyB)}, keyA)
	if retry := ledger.Observe(keyB, "corrupt", []byte("wrong"), 0); !retry {
		t.Fatal("wrong hash was acknowledged")
	}
	if ledger.Complete() {
		t.Fatal("wrong hash produced a complete outcome")
	}
	_, facts := ledger.Snapshot()
	if len(facts) != 0 {
		t.Fatal("wrong hash created a business fact")
	}
}
