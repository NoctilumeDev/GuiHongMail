package infrastructure

import "testing"

func TestSMTPFailureOutcomePreservesTheExternalEffectBoundary(t *testing.T) {
	tests := []struct {
		code      int
		submitted bool
		want      string
	}{
		{451, false, "TEMPORARY_FAILURE"},
		{550, false, "PERMANENT_FAILURE"},
		{0, true, "UNKNOWN"},
		{451, true, "TEMPORARY_FAILURE"},
		{550, true, "PERMANENT_FAILURE"},
	}
	for _, test := range tests {
		if got := smtpFailureOutcome(test.code, test.submitted); got != test.want {
			t.Fatalf("smtpFailureOutcome(%d,%t)=%s want %s", test.code, test.submitted, got, test.want)
		}
	}
}
