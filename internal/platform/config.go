package platform

import (
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
)

// BuildSource is set with -ldflags for every service executable.
var BuildSource string

var sourcePattern = regexp.MustCompile(`^[0-9a-f]{40}$`)

type Config struct {
	Role          string
	SourceSHA     string
	HTTPAddress   string
	SMTPAddress   string
	WitnessRoot   string
	InternalToken string
	DatabaseDSN   string
	S3Endpoint    string
	S3Bucket      string
	S3Key         string
	S3Secret      string
	NameServer    string
	Broker        string
}

func LoadConfig(role string) (Config, error) {
	ports := map[string]string{"mailbox": "127.0.0.1:18080", "ingress": "127.0.0.1:18081", "delivery": "127.0.0.1:18082"}
	address, ok := ports[role]
	if !ok {
		return Config{}, fmt.Errorf("unknown service role")
	}
	if !sourcePattern.MatchString(BuildSource) {
		return Config{}, fmt.Errorf("exact build identity required")
	}
	required := func(name string) (string, error) {
		value := os.Getenv(name)
		if value == "" {
			return "", fmt.Errorf("missing required setting %s", name)
		}
		return value, nil
	}
	values := make(map[string]string)
	for _, name := range []string{"GUIHONG_WITNESS_ROOT", "GUIHONG_INTERNAL_TOKEN", "GUIHONG_DB_DSN",
		"GUIHONG_S3_ENDPOINT", "GUIHONG_S3_BUCKET", "GUIHONG_S3_KEY", "GUIHONG_S3_SECRET",
		"GUIHONG_NAMESRV", "GUIHONG_BROKER"} {
		value, err := required(name)
		if err != nil {
			return Config{}, err
		}
		values[name] = value
	}
	root, err := filepath.Abs(values["GUIHONG_WITNESS_ROOT"])
	if err != nil {
		return Config{}, fmt.Errorf("resolve witness root: %w", err)
	}
	info, err := os.Lstat(root)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return Config{}, fmt.Errorf("owned witness root missing or unsafe")
	}
	endpoint, err := url.Parse(values["GUIHONG_S3_ENDPOINT"])
	if err != nil || endpoint.Scheme != "http" || endpoint.Hostname() != "127.0.0.1" || endpoint.Port() == "" {
		return Config{}, fmt.Errorf("approved profile requires loopback S3")
	}
	return Config{
		Role: role, SourceSHA: BuildSource, HTTPAddress: address, SMTPAddress: "127.0.0.1:12525",
		WitnessRoot: root, InternalToken: values["GUIHONG_INTERNAL_TOKEN"], DatabaseDSN: values["GUIHONG_DB_DSN"],
		S3Endpoint: values["GUIHONG_S3_ENDPOINT"], S3Bucket: values["GUIHONG_S3_BUCKET"],
		S3Key: values["GUIHONG_S3_KEY"], S3Secret: values["GUIHONG_S3_SECRET"],
		NameServer: values["GUIHONG_NAMESRV"], Broker: values["GUIHONG_BROKER"],
	}, nil
}
