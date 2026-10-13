package platform

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

func InternalRequest(ctx context.Context, runtime *Runtime, method, target string, input any, limit int64) (int, []byte, error) {
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
	request.Header.Set("Authorization", "Bearer "+runtime.Config.InternalToken)
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
