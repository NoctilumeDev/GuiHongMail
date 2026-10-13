package domain

import (
	"context"
	"errors"
	"time"
)

var ErrIdempotencyConflict = errors.New("IDEMPOTENCY_CONFLICT")

type SendIntent struct {
	ID              string              `json:"id"`
	DraftID         string              `json:"draftId"`
	DraftVersion    int64               `json:"draftVersion"`
	RequestKey      string              `json:"requestKey"`
	PayloadSHA256   string              `json:"payloadSha256"`
	DispatchScopeID string              `json:"dispatchScopeId"`
	ContentID       string              `json:"contentId"`
	RawObjectID     string              `json:"-"`
	RawSHA256       string              `json:"rawSha256"`
	RawSize         int64               `json:"rawSize"`
	SenderAddress   string              `json:"senderAddress"`
	Envelope        []EnvelopeRecipient `json:"envelope"`
	State           string              `json:"state"`
	CreatedAt       time.Time           `json:"createdAt"`
}

type EnvelopeRecipient struct {
	Kind    string `json:"kind"`
	Address string `json:"address"`
}

type SendFreeze struct {
	IntentID        string
	AccountID       string
	Draft           Draft
	RequestKey      string
	PayloadSHA256   string
	DispatchScopeID string
	ContentID       string
	RawObjectID     string
	RawSHA256       string
	RawSize         int64
	SenderAddress   string
	Envelope        []EnvelopeRecipient
	Parsed          ParsedMessage
	MessageFiles    []StoredAttachment
	OutboxEventID   string
	OutboxPayload   []byte
}

type OutboxEvent struct {
	ID      string
	Topic   string
	Key     string
	Payload []byte
}

type IngressImport struct {
	SpoolID   string
	RawSHA256 string
	Imported  ImportedMessage
	Members   []Member
}

type SendRepository interface {
	ExistingSend(context.Context, string, string) (*SendIntent, error)
	FreezeSend(context.Context, SendFreeze) (SendIntent, error)
	Send(context.Context, string, string) (SendIntent, error)
	SendRaw(context.Context, string) (string, string, int64, error)
	PendingSendEvents(context.Context, int) ([]OutboxEvent, error)
	MarkSendEventPublished(context.Context, string, string) error
	EnabledAccount(context.Context, string) (string, error)
	ImportIngress(context.Context, IngressImport) (bool, error)
}
