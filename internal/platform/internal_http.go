package platform

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"time"
)

func InternalRequest(ctx context.Context, runtime *Runtime, method, target string, input any, limit int64) (int, []byte, error) {
	token, err := tokenForInternalTarget(runtime.Config, target)
	if err != nil {
		return 0, nil, err
	}
	var body io.Reader
	if input != nil {
		encoded, err := json.Marshal(input)
		if err != nil {
			return 0, nil, err
		}
		body = bytes.NewReader(encoded)
	}
	request, err := http.NewRequestWithContext(ctx, method, target, body)
	if err != nil {
		return 0, nil, err
	}
	request.Header.Set("Authorization", "Bearer "+token)
	request.Header.Set("X-GuiHong-Service", runtime.Config.Role)
	if input != nil {
		request.Header.Set("Content-Type", "application/json")
	}
	client := &http.Client{Timeout: 10 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	response, err := client.Do(request)
	if err != nil {
		return 0, nil, err
	}
	defer response.Body.Close()
	data, err := io.ReadAll(io.LimitReader(response.Body, limit+1))
	if err != nil {
		return response.StatusCode, nil, err
	}
	if int64(len(data)) > limit {
		return response.StatusCode, nil, fmt.Errorf("internal response exceeded limit")
	}
	return response.StatusCode, data, nil
}

func tokenForInternalTarget(config Config, target string) (string, error) {
	parsed, err := url.Parse(target)
	if err != nil || parsed.Scheme != "http" || parsed.Hostname() != "127.0.0.1" || parsed.User != nil {
		return "", fmt.Errorf("internal target is outside the fixed loopback topology")
	}
	role := map[string]string{"18080": "mailbox", "18081": "ingress", "18082": "delivery"}[parsed.Port()]
	token := config.InternalTokens[role]
	if role == "" || token == "" {
		return "", fmt.Errorf("internal target has no configured service credential")
	}
	return token, nil
}
