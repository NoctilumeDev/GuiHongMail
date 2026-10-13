package platform

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestS3ClientSignsAndRunsLifecycleWithoutRetries(t *testing.T) {
	t.Helper()
	stored := []byte(nil)
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if request.URL.Path != "/owned/objects/generation/id" {
			if request.Method == http.MethodHead && request.URL.Path == "/owned" {
				writer.WriteHeader(http.StatusOK)
				return
			}
			t.Errorf("unexpected path %q", request.URL.Path)
			writer.WriteHeader(http.StatusNotFound)
			return
		}
		authorization := request.Header.Get("Authorization")
		if !strings.Contains(authorization, "Credential=access/20261013/us-east-1/s3/aws4_request") ||
			!strings.Contains(authorization, "SignedHeaders=host;x-amz-content-sha256;x-amz-date") {
			t.Errorf("invalid authorization %q", authorization)
		}
		switch request.Method {
		case http.MethodPut:
			stored, _ = io.ReadAll(request.Body)
			writer.WriteHeader(http.StatusOK)
		case http.MethodGet:
			_, _ = writer.Write(stored)
		case http.MethodDelete:
			stored = nil
			writer.WriteHeader(http.StatusNoContent)
		default:
			writer.WriteHeader(http.StatusMethodNotAllowed)
		}
	}))
	defer server.Close()
	client, err := NewS3Client(server.URL, "owned", "access", "secret")
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	client.now = func() time.Time { return time.Date(2026, 10, 13, 1, 2, 3, 0, time.UTC) }
	ctx := context.Background()
	if !client.Ready(ctx) {
		t.Fatal("bucket should be ready")
	}
	payload := []byte("exact-object-bytes")
	if err := client.Put(ctx, "objects/generation/id", payload); err != nil {
		t.Fatal(err)
	}
	actual, err := client.Get(ctx, "objects/generation/id")
	if err != nil || string(actual) != string(payload) {
		t.Fatalf("get=%q err=%v", actual, err)
	}
	if err := client.Delete(ctx, "objects/generation/id"); err != nil {
		t.Fatal(err)
	}
}

func TestS3ClientRejectsUnsafeCoordinateBeforeNetwork(t *testing.T) {
	client, err := NewS3Client("http://127.0.0.1:1", "owned", "access", "secret")
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	if err := client.Put(context.Background(), "../escape", []byte("x")); err == nil || !strings.Contains(err.Error(), "invalid object coordinate") {
		t.Fatalf("unsafe key was not rejected: %v", err)
	}
}
