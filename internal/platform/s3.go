package platform

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"
)

const MaxObjectBytes = 5 * 1024 * 1024

var objectKeyPattern = regexp.MustCompile(`^[a-zA-Z0-9][a-zA-Z0-9/_-]{0,180}$`)

type S3StatusError struct {
	Operation string
	Status    int
}

func (failure *S3StatusError) Error() string {
	return fmt.Sprintf("s3 %s returned status %d", failure.Operation, failure.Status)
}

// S3Client is a deliberately small, retry-free, path-style S3 client. A
// transport error remains an unknown operation result instead of being hidden
// behind an SDK retry.
type S3Client struct {
	endpoint *url.URL
	bucket   string
	key      string
	secret   string
	client   *http.Client
	now      func() time.Time
}

func NewS3Client(endpoint, bucket, key, secret string) (*S3Client, error) {
	parsed, err := url.Parse(endpoint)
	if err != nil || parsed.Scheme != "http" || parsed.Hostname() != "127.0.0.1" || parsed.Port() == "" || parsed.Path != "" {
		return nil, fmt.Errorf("approved profile requires a bare loopback S3 endpoint")
	}
	if bucket == "" || strings.ContainsAny(bucket, "/\\") || key == "" || secret == "" {
		return nil, fmt.Errorf("invalid S3 identity")
	}
	transport := &http.Transport{
		Proxy:                 nil,
		DisableKeepAlives:     true,
		ResponseHeaderTimeout: 8 * time.Second,
		DialContext:           (&net.Dialer{Timeout: 3 * time.Second, KeepAlive: -1}).DialContext,
	}
	return &S3Client{
		endpoint: parsed, bucket: bucket, key: key, secret: secret,
		client: &http.Client{Timeout: 10 * time.Second, Transport: transport},
		now:    time.Now,
	}, nil
}

func (store *S3Client) Close() {
	if transport, ok := store.client.Transport.(*http.Transport); ok {
		transport.CloseIdleConnections()
	}
}

func (store *S3Client) Ready(ctx context.Context) bool {
	response, err := store.request(ctx, http.MethodHead, "", nil)
	if err != nil {
		return false
	}
	_ = response.Body.Close()
	return response.StatusCode >= 200 && response.StatusCode < 300
}

func (store *S3Client) Put(ctx context.Context, key string, data []byte) error {
	if len(data) > MaxObjectBytes {
		return fmt.Errorf("message size limit exceeded")
	}
	response, err := store.request(ctx, http.MethodPut, key, data)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, 64*1024))
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return &S3StatusError{Operation: "PUT", Status: response.StatusCode}
	}
	return nil
}

func (store *S3Client) Get(ctx context.Context, key string) ([]byte, error) {
	response, err := store.request(ctx, http.MethodGet, key, nil)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return nil, &S3StatusError{Operation: "GET", Status: response.StatusCode}
	}
	if response.ContentLength > MaxObjectBytes {
		return nil, fmt.Errorf("stored object exceeds limit")
	}
	data, err := io.ReadAll(io.LimitReader(response.Body, MaxObjectBytes+1))
	if err != nil {
		return nil, err
	}
	if len(data) > MaxObjectBytes {
		return nil, fmt.Errorf("stored object exceeds limit")
	}
	return data, nil
}

func (store *S3Client) Delete(ctx context.Context, key string) error {
	response, err := store.request(ctx, http.MethodDelete, key, nil)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, 64*1024))
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return &S3StatusError{Operation: "DELETE", Status: response.StatusCode}
	}
	return nil
}

func (store *S3Client) request(ctx context.Context, method, key string, data []byte) (*http.Response, error) {
	if key != "" && !objectKeyPattern.MatchString(key) {
		return nil, fmt.Errorf("invalid object coordinate")
	}
	path := "/" + escapeS3Segment(store.bucket)
	if key != "" {
		segments := strings.Split(key, "/")
		for index := range segments {
			segments[index] = escapeS3Segment(segments[index])
		}
		path += "/" + strings.Join(segments, "/")
	}
	payload := data
	if payload == nil {
		payload = []byte{}
	}
	payloadSum := sha256.Sum256(payload)
	payloadHash := hex.EncodeToString(payloadSum[:])
	now := store.now().UTC()
	amzDate := now.Format("20060102T150405Z")
	shortDate := now.Format("20060102")
	canonicalHeaders := "host:" + store.endpoint.Host + "\n" +
		"x-amz-content-sha256:" + payloadHash + "\n" +
		"x-amz-date:" + amzDate + "\n"
	signedHeaders := "host;x-amz-content-sha256;x-amz-date"
	canonicalRequest := strings.Join([]string{method, path, "", canonicalHeaders, signedHeaders, payloadHash}, "\n")
	requestSum := sha256.Sum256([]byte(canonicalRequest))
	scope := shortDate + "/us-east-1/s3/aws4_request"
	stringToSign := "AWS4-HMAC-SHA256\n" + amzDate + "\n" + scope + "\n" + hex.EncodeToString(requestSum[:])
	dateKey := hmacSHA256([]byte("AWS4"+store.secret), shortDate)
	regionKey := hmacSHA256(dateKey, "us-east-1")
	serviceKey := hmacSHA256(regionKey, "s3")
	signingKey := hmacSHA256(serviceKey, "aws4_request")
	signature := hex.EncodeToString(hmacSHA256(signingKey, stringToSign))
	requestURL := *store.endpoint
	requestURL.Path = path
	request, err := http.NewRequestWithContext(ctx, method, requestURL.String(), bytes.NewReader(payload))
	if err != nil {
		return nil, err
	}
	request.Host = store.endpoint.Host
	request.Header.Set("X-Amz-Content-Sha256", payloadHash)
	request.Header.Set("X-Amz-Date", amzDate)
	request.Header.Set("Authorization", "AWS4-HMAC-SHA256 Credential="+store.key+"/"+scope+", SignedHeaders="+signedHeaders+", Signature="+signature)
	return store.client.Do(request)
}

func escapeS3Segment(value string) string {
	return strings.ReplaceAll(url.PathEscape(value), "+", "%20")
}
