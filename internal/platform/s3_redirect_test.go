package platform

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
)

// Both endpoints are owned loopback test servers. No external target is contacted.
func TestS3ClientDoesNotFollowRedirects(t *testing.T) {
	for _, status := range []int{301, 302, 303, 307, 308} {
		for _, method := range []string{http.MethodHead, http.MethodGet, http.MethodPut, http.MethodDelete} {
			t.Run(fmt.Sprintf("%s/%d", method, status), func(t *testing.T) {
				var sourceCalls, targetCalls atomic.Int32
				target := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					targetCalls.Add(1)
					w.WriteHeader(http.StatusOK)
				}))
				defer target.Close()
				source := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					sourceCalls.Add(1)
					w.Header().Set("Location", target.URL+"/redirected")
					w.WriteHeader(status)
				}))
				defer source.Close()
				client, err := NewS3Client(source.URL, "owned", "synthetic-access", "synthetic-secret")
				if err != nil {
					t.Fatal(err)
				}
				defer client.Close()
				ctx := context.Background()
				switch method {
				case http.MethodHead:
					if client.Ready(ctx) {
						t.Error("redirect must not make the configured bucket ready")
					}
				case http.MethodGet:
					_, err = client.Get(ctx, "objects/synthetic")
				case http.MethodPut:
					err = client.Put(ctx, "objects/synthetic", []byte("synthetic-object"))
				case http.MethodDelete:
					err = client.Delete(ctx, "objects/synthetic")
				}
				if method != http.MethodHead {
					var statusError *S3StatusError
					if !errors.As(err, &statusError) || statusError.Status != status || statusError.Operation != method {
						t.Errorf("want original %s status %d, got %v", method, status, err)
					}
				}
				if sourceCalls.Load() != 1 || targetCalls.Load() != 0 {
					t.Errorf("redirect crossed request boundary: source=%d target=%d", sourceCalls.Load(), targetCalls.Load())
				}
			})
		}
	}
}

func TestS3ClientDoesNotFollowRelativeObjectRedirect(t *testing.T) {
	var originalCalls, otherObjectCalls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/owned/objects/synthetic" {
			originalCalls.Add(1)
			w.Header().Set("Location", "/owned/objects/different")
			w.WriteHeader(http.StatusTemporaryRedirect)
			return
		}
		otherObjectCalls.Add(1)
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()
	client, err := NewS3Client(server.URL, "owned", "synthetic-access", "synthetic-secret")
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	_, err = client.Get(context.Background(), "objects/synthetic")
	var statusError *S3StatusError
	if !errors.As(err, &statusError) || statusError.Status != http.StatusTemporaryRedirect {
		t.Errorf("want original redirect error, got %v", err)
	}
	if originalCalls.Load() != 1 || otherObjectCalls.Load() != 0 {
		t.Errorf("signed object coordinate changed: original=%d other=%d", originalCalls.Load(), otherObjectCalls.Load())
	}
}
