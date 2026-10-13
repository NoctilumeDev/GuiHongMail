package platform

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
)

func SHA256(value []byte) string {
	digest := sha256.Sum256(value)
	return hex.EncodeToString(digest[:])
}

func Same(left, right string) bool {
	return left != "" && right != "" && hmac.Equal([]byte(left), []byte(right))
}

func hmacSHA256(key []byte, value string) []byte {
	mac := hmac.New(sha256.New, key)
	_, _ = mac.Write([]byte(value))
	return mac.Sum(nil)
}
