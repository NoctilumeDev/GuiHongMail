package platform

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

func TestWitnessJournalRejectsCompoundOutcome(t *testing.T) {
	root := t.TempDir()
	generation := "b63e442c-d7d8-4706-a702-fc8164284262"
	chain := SHA256([]byte("GuiHongWitness/1.0|" + generation))
	id := "c7063fd9-e4af-4e71-8bd1-107dbbd03155"
	payload := SHA256([]byte("payload"))
	first, next := witnessLine(1, id, "P", payload, chain)
	second, _ := witnessLine(1, id, "CA", payload, next)
	if err := os.WriteFile(filepath.Join(root, "transactions.log"), []byte(first+second), 0o600); err != nil {
		t.Fatal(err)
	}
	witness := &Witness{root: root, generation: generation, chain: chain}
	if _, _, _, err := witness.readJournal(); err == nil {
		t.Fatal("compound outcome must not be admitted")
	}
}

func TestWitnessJournalReadsPreparedAndCommitted(t *testing.T) {
	root := t.TempDir()
	generation := "b63e442c-d7d8-4706-a702-fc8164284262"
	chain := SHA256([]byte("GuiHongWitness/1.0|" + generation))
	id := "c7063fd9-e4af-4e71-8bd1-107dbbd03155"
	payload := SHA256([]byte("payload"))
	first, next := witnessLine(1, id, "P", payload, chain)
	second, _ := witnessLine(1, id, "C", payload, next)
	if err := os.WriteFile(filepath.Join(root, "transactions.log"), []byte(first+second), 0o600); err != nil {
		t.Fatal(err)
	}
	witness := &Witness{root: root, generation: generation, chain: chain}
	prepared, outcomes, maximum, err := witness.readJournal()
	if err != nil || maximum != 1 || prepared[id].digest != payload || outcomes[id] != "C" {
		t.Fatalf("prepared=%v outcomes=%v maximum=%d err=%v", prepared, outcomes, maximum, err)
	}
}

func witnessLine(sequence int64, id, outcome, payload, previous string) (string, string) {
	content := fmt.Sprintf("%d|%s|%s|%s|%s", sequence, id, outcome, payload, previous)
	digest := SHA256([]byte(content))
	return content + "|" + digest + "\n", digest
}

func TestInternalAuthenticationDoesNotAcceptUserBearer(t *testing.T) {
	runtime := &Runtime{Config: Config{InternalToken: "owned-operator-token"}}
	if err := runtime.RequireInternal("lab", "Bearer owned-operator-token"); err != nil {
		t.Fatal(err)
	}
	if err := runtime.RequireInternal("", "Bearer owned-operator-token"); err == nil {
		t.Fatal("missing service capability was accepted")
	}
	if err := runtime.RequireInternal("lab", "Bearer user-session-token"); err == nil {
		t.Fatal("user bearer was accepted as operator capability")
	}
}
