package application

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"time"

	"github.com/NoctilumeDev/GuiHongMail/internal/mailbox/domain"
	"github.com/NoctilumeDev/GuiHongMail/internal/platform"
	"github.com/google/uuid"
)

const ingressTopic = "guihong.ingress.accepted.v1"

type ingressEvent struct {
	Version       int    `json:"version"`
	SourceService string `json:"sourceService"`
	SpoolID       string `json:"spoolId"`
	RawSHA256     string `json:"rawSha256"`
	RawSize       int64  `json:"rawSize"`
	RawURL        string `json:"rawUrl"`
	AckURL        string `json:"ackUrl"`
	Recipients    []struct {
		AccountID string `json:"accountId"`
		Address   string `json:"address"`
	} `json:"recipients"`
}

type IngressImporter struct {
	sends   domain.SendRepository
	parser  MessageParser
	objects *platform.ObjectRepository
}

func NewIngressImporter(sends domain.SendRepository, parser MessageParser, objects *platform.ObjectRepository) *IngressImporter {
	return &IngressImporter{sends: sends, parser: parser, objects: objects}
}

func (s *Sender) Run(ctx context.Context, runtime *platform.Runtime, importer *IngressImporter) error {
	for _, topic := range []string{sendTopic, ingressTopic} {
		ensureCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
		err := platform.EnsureTopic(ensureCtx, runtime, topic)
		cancel()
		if err != nil {
			return err
		}
	}
	errorsChannel := make(chan error, 2)
	go func() { errorsChannel <- s.publishLoop(ctx, runtime) }()
	go func() { errorsChannel <- importer.consume(ctx, runtime) }()
	select {
	case <-ctx.Done():
		return nil
	case err := <-errorsChannel:
		return err
	}
}

func (s *Sender) publishLoop(ctx context.Context, runtime *platform.Runtime) error {
	publisher, err := platform.NewPublisher(runtime, "guihong-mailbox-outbox-v1")
	if err != nil {
		return err
	}
	defer publisher.Close()
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()
	for {
		if runtime.Writable(ctx) {
			events, err := s.sends.PendingSendEvents(ctx, 20)
			if err != nil {
				return err
			}
			for _, event := range events {
				messageID, sendErr := publisher.Send(ctx, event.Topic, event.Key, event.Payload)
				if sendErr != nil {
					break
				}
				if err := s.sends.MarkSendEventPublished(ctx, event.ID, messageID); err != nil {
					break
				}
			}
		}
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
		}
	}
}

func (importer *IngressImporter) consume(ctx context.Context, runtime *platform.Runtime) error {
	return platform.Consume(ctx, runtime, "guihong.mailbox.import.v1", ingressTopic, func(callback context.Context, _ string, body []byte) error {
		var event ingressEvent
		if err := json.Unmarshal(body, &event); err != nil || event.Version != 1 || event.SourceService != "ingress" || len(event.Recipients) == 0 || len(event.Recipients) > 10 {
			return fmt.Errorf("invalid ingress event")
		}
		status, raw, err := platform.InternalRequest(callback, runtime, http.MethodGet, event.RawURL, nil, 5*1024*1024)
		if err != nil || status != http.StatusOK || int64(len(raw)) != event.RawSize || platform.SHA256(raw) != event.RawSHA256 {
			return fmt.Errorf("ingress content unavailable or mismatched")
		}
		_, err = importer.importMessage(callback, event, raw)
		if err != nil {
			return err
		}
		status, _, err = platform.InternalRequest(callback, runtime, http.MethodPost, event.AckURL, map[string]any{"rawSha256": event.RawSHA256, "imported": true}, 4096)
		if err != nil || (status != http.StatusOK && status != http.StatusNoContent) {
			return fmt.Errorf("ingress acknowledgement unavailable")
		}
		return nil
	})
}

func (importer *IngressImporter) importMessage(ctx context.Context, event ingressEvent, raw []byte) (bool, error) {
	parsed, err := importer.parser.Parse(raw)
	if err != nil {
		return false, err
	}
	if len(parsed.Attachments) > 20 {
		return false, &domain.InvalidError{Code: "MIME_PART_LIMIT"}
	}
	contentID := uuid.NewString()
	type reference struct{ object, kind, id string }
	references := []reference{}
	rawBlob, err := importer.objects.Stage(ctx, uuid.NewString(), "ingress-raw:"+event.SpoolID, raw)
	if err != nil {
		return false, err
	}
	if rawBlob, err = importer.objects.Reference(ctx, rawBlob.ID, "MESSAGE_RAW", contentID); err != nil {
		return false, err
	}
	references = append(references, reference{rawBlob.ID, "MESSAGE_RAW", contentID})
	attachments := make([]domain.StoredAttachment, 0, len(parsed.Attachments))
	for _, value := range parsed.Attachments {
		id := uuid.NewString()
		blob, failure := importer.objects.Stage(ctx, uuid.NewString(), "ingress-attachment:"+id, value.Bytes)
		if failure != nil {
			err = failure
			break
		}
		if blob, failure = importer.objects.Reference(ctx, blob.ID, "MESSAGE_ATTACHMENT", id); failure != nil {
			err = failure
			break
		}
		references = append(references, reference{blob.ID, "MESSAGE_ATTACHMENT", id})
		attachments = append(attachments, domain.StoredAttachment{ID: id, ObjectID: blob.ID, FileName: value.FileName, MediaType: value.MediaType, SHA256: blob.SHA256, Size: blob.Size})
	}
	if err == nil {
		members := make([]domain.Member, 0, len(event.Recipients))
		for _, recipient := range event.Recipients {
			members = append(members, domain.Member{AccountID: recipient.AccountID, Folder: domain.Inbox, Read: false})
		}
		created, failure := importer.sends.ImportIngress(ctx, domain.IngressImport{SpoolID: event.SpoolID, RawSHA256: event.RawSHA256,
			Imported: domain.ImportedMessage{ContentID: contentID, RawObjectID: rawBlob.ID, RawSHA256: rawBlob.SHA256, RawSize: rawBlob.Size, Parsed: parsed, Attachments: attachments}, Members: members})
		if failure == nil && created {
			return true, nil
		}
		err = failure
	}
	var unknown *platform.CommitUnknownError
	if !errors.As(err, &unknown) {
		for _, value := range references {
			_ = importer.objects.Dereference(ctx, value.object, value.kind, value.id)
		}
	}
	return false, err
}
