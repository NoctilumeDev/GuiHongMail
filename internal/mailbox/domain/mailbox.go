package domain

import (
	"context"
	"errors"
	"fmt"
	"time"
)

var ErrNotFound = errors.New("RESOURCE_NOT_FOUND")

type InvalidError struct{ Code string }

func (e *InvalidError) Error() string { return e.Code }

type VersionConflictError struct{ Current int64 }

func (e *VersionConflictError) Error() string { return fmt.Sprintf("VERSION_CONFLICT:%d", e.Current) }

type Folder string

const (
	Inbox   Folder = "INBOX"
	Sent    Folder = "SENT"
	Archive Folder = "ARCHIVE"
	Spam    Folder = "SPAM"
	Trash   Folder = "TRASH"
)

func (folder Folder) Valid() bool {
	switch folder {
	case Inbox, Sent, Archive, Spam, Trash:
		return true
	default:
		return false
	}
}

type DraftMode string

const (
	Compose  DraftMode = "COMPOSE"
	Reply    DraftMode = "REPLY"
	ReplyAll DraftMode = "REPLY_ALL"
	Forward  DraftMode = "FORWARD"
)

func (mode DraftMode) Valid() bool {
	switch mode {
	case Compose, Reply, ReplyAll, Forward:
		return true
	default:
		return false
	}
}

type Address struct {
	Address string
	Name    string
}
type Recipient struct {
	Kind    string  `json:"kind"`
	Ordinal int     `json:"ordinal"`
	Address string  `json:"address"`
	Name    *string `json:"name"`
}
type Attachment struct {
	ID        string `json:"id"`
	ObjectID  string `json:"objectId"`
	FileName  string `json:"fileName"`
	MediaType string `json:"mediaType"`
	SHA256    string `json:"sha256"`
	Size      int64  `json:"size"`
}
type MessageSummary struct {
	EntryID         string     `json:"entryId"`
	ContentID       string     `json:"contentId"`
	Folder          Folder     `json:"folder"`
	Read            bool       `json:"read"`
	CategoryID      *string    `json:"categoryId"`
	Version         int64      `json:"version"`
	FromAddress     string     `json:"fromAddress"`
	FromName        *string    `json:"fromName"`
	Subject         string     `json:"subject"`
	Preview         string     `json:"preview"`
	SentAt          *time.Time `json:"sentAt"`
	ReceivedAt      time.Time  `json:"receivedAt"`
	AttachmentCount int        `json:"attachmentCount"`
}
type MessageDetail struct {
	Summary     MessageSummary `json:"summary"`
	TextBody    string         `json:"textBody"`
	SafeHTML    string         `json:"safeHtml"`
	Recipients  []Recipient    `json:"recipients"`
	Attachments []Attachment   `json:"attachments"`
	RawSHA256   string         `json:"rawSha256"`
	RawSize     int64          `json:"rawSize"`
}
type FolderCount struct {
	Folder Folder `json:"folder"`
	Total  int64  `json:"total"`
	Unread int64  `json:"unread"`
}
type Category struct {
	ID      string `json:"id"`
	Name    string `json:"name"`
	Version int64  `json:"version"`
	Total   int64  `json:"total"`
	Unread  int64  `json:"unread"`
}
type Draft struct {
	ID              string       `json:"id"`
	Version         int64        `json:"version"`
	Subject         string       `json:"subject"`
	TextBody        string       `json:"textBody"`
	HTMLBody        string       `json:"htmlBody"`
	To              []string     `json:"to"`
	CC              []string     `json:"cc"`
	BCC             []string     `json:"bcc"`
	Mode            DraftMode    `json:"mode"`
	SourceContentID *string      `json:"sourceContentId"`
	Attachments     []Attachment `json:"attachments"`
	CreatedAt       time.Time    `json:"createdAt"`
	UpdatedAt       time.Time    `json:"updatedAt"`
}
type ParsedAttachment struct {
	FileName  string
	MediaType string
	Bytes     []byte
	SHA256    string
}
type ParsedMessage struct {
	MessageID   string
	From        Address
	Subject     string
	TextBody    string
	SafeHTML    string
	SentAt      *time.Time
	Recipients  []Recipient
	Attachments []ParsedAttachment
}
type StoredAttachment struct {
	ID        string
	ObjectID  string
	FileName  string
	MediaType string
	SHA256    string
	Size      int64
}
type ImportedMessage struct {
	ContentID   string
	RawObjectID string
	RawSHA256   string
	RawSize     int64
	Parsed      ParsedMessage
	Attachments []StoredAttachment
}
type Member struct {
	AccountID string
	Folder    Folder
	Read      bool
}
type DraftInput struct {
	Subject         string
	TextBody        string
	HTMLBody        string
	To              []string
	CC              []string
	BCC             []string
	Mode            DraftMode
	SourceContentID *string
}
type MessageChange struct {
	ExpectedVersion *int64
	Read            *bool
	Folder          *Folder
	CategoryID      *string
	CategorySet     bool
}

type Page[T any] struct {
	Items      []T     `json:"items"`
	NextCursor *string `json:"nextCursor"`
}

type MailboxRepository interface {
	Available(context.Context) bool
	AccountAddress(context.Context, string) (string, error)
	ImportMessage(context.Context, ImportedMessage, []Member) error
	FolderCounts(context.Context, string) ([]FolderCount, error)
	List(context.Context, string, *Folder, *string, string, int, string) (Page[MessageSummary], error)
	Message(context.Context, string, string) (MessageDetail, error)
	Change(context.Context, string, string, MessageChange) (MessageDetail, error)
	CreateDraft(context.Context, string, DraftInput) (Draft, error)
	Draft(context.Context, string, string) (Draft, error)
	Drafts(context.Context, string, int, string) (Page[Draft], error)
	UpdateDraft(context.Context, string, string, int64, DraftInput) (Draft, error)
	DeleteDraft(context.Context, string, string, int64) ([]Attachment, error)
	AddDraftAttachment(context.Context, string, string, int64, StoredAttachment) (Draft, error)
	AuthorizedMessageAttachment(context.Context, string, string, string) (Attachment, error)
	AuthorizedDraftAttachment(context.Context, string, string, string) (Attachment, error)
	Categories(context.Context, string) ([]Category, error)
	CreateCategory(context.Context, string, string) (Category, error)
	RenameCategory(context.Context, string, string, int64, string) (Category, error)
	DeleteCategory(context.Context, string, string, int64) error
}
