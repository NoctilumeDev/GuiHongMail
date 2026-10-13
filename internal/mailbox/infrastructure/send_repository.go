package infrastructure

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/NoctilumeDev/GuiHongMail/internal/mailbox/domain"
	"github.com/go-sql-driver/mysql"
	"github.com/google/uuid"
)

func (r *MailboxRepository) ExistingSend(ctx context.Context, account, key string) (*domain.SendIntent, error) {
	if err := r.ready(ctx); err != nil {
		return nil, err
	}
	return r.readSend(ctx, account, "request_key", key)
}

func (r *MailboxRepository) Send(ctx context.Context, account, id string) (domain.SendIntent, error) {
	if err := r.ready(ctx); err != nil {
		return domain.SendIntent{}, err
	}
	value, err := r.readSend(ctx, account, "intent_id", id)
	if value == nil {
		return domain.SendIntent{}, err
	}
	return *value, err
}

func (r *MailboxRepository) readSend(ctx context.Context, account, column, value string) (*domain.SendIntent, error) {
	if column != "request_key" && column != "intent_id" {
		return nil, fmt.Errorf("invalid send lookup")
	}
	var intent domain.SendIntent
	var envelope []byte
	err := r.database.QueryRowContext(ctx, `SELECT intent_id,draft_id,draft_version,request_key,payload_sha256,dispatch_scope_id,content_id,raw_object_id,raw_sha256,raw_size,sender_address,envelope_json,state,created_at FROM send_intents WHERE account_id=? AND `+column+`=?`, account, value).Scan(
		&intent.ID, &intent.DraftID, &intent.DraftVersion, &intent.RequestKey, &intent.PayloadSHA256,
		&intent.DispatchScopeID, &intent.ContentID, &intent.RawObjectID, &intent.RawSHA256, &intent.RawSize,
		&intent.SenderAddress, &envelope, &intent.State, &intent.CreatedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if err := json.Unmarshal(envelope, &intent.Envelope); err != nil {
		return nil, err
	}
	return &intent, nil
}

func (r *MailboxRepository) SendRaw(ctx context.Context, id string) (string, string, int64, error) {
	var object, digest string
	var size int64
	err := r.database.QueryRowContext(ctx, "SELECT raw_object_id,raw_sha256,raw_size FROM send_intents WHERE intent_id=?", id).Scan(&object, &digest, &size)
	if errors.Is(err, sql.ErrNoRows) {
		return "", "", 0, domain.ErrNotFound
	}
	return object, digest, size, err
}

func (r *MailboxRepository) FreezeSend(ctx context.Context, command domain.SendFreeze) (domain.SendIntent, error) {
	if err := r.ready(ctx); err != nil {
		return domain.SendIntent{}, err
	}
	envelope, _ := json.Marshal(command.Envelope)
	err := r.witness.Write(ctx, "send-freeze|"+command.AccountID+"|"+command.IntentID+"|"+command.PayloadSHA256, func(tx *sql.Tx) error {
		var current int64
		if err := tx.QueryRowContext(ctx, "SELECT version_no FROM drafts WHERE account_id=? AND draft_id=? FOR UPDATE", command.AccountID, command.Draft.ID).Scan(&current); errors.Is(err, sql.ErrNoRows) {
			return domain.ErrNotFound
		} else if err != nil {
			return err
		}
		if current != command.Draft.Version {
			return &domain.VersionConflictError{Current: current}
		}
		p := command.Parsed
		if _, err := tx.ExecContext(ctx, `INSERT INTO message_contents(content_id,raw_object_id,raw_sha256,raw_size,message_id,from_address,from_name,subject,text_body,safe_html,sent_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)`, command.ContentID, command.RawObjectID, command.RawSHA256, command.RawSize, nullString(p.MessageID), p.From.Address, nullString(p.From.Name), p.Subject, p.TextBody, p.SafeHTML, p.SentAt); err != nil {
			return err
		}
		for _, recipient := range p.Recipients {
			if _, err := tx.ExecContext(ctx, `INSERT INTO message_recipients(content_id,recipient_kind,ordinal_no,address,display_name) VALUES(?,?,?,?,?)`, command.ContentID, recipient.Kind, recipient.Ordinal, recipient.Address, recipient.Name); err != nil {
				return err
			}
		}
		for ordinal, attachment := range command.MessageFiles {
			if _, err := tx.ExecContext(ctx, `INSERT INTO message_attachments(attachment_id,content_id,object_id,ordinal_no,file_name,media_type,sha256,byte_size) VALUES(?,?,?,?,?,?,?,?)`, attachment.ID, command.ContentID, attachment.ObjectID, ordinal, attachment.FileName, attachment.MediaType, attachment.SHA256, attachment.Size); err != nil {
				return err
			}
			if _, err := tx.ExecContext(ctx, `INSERT INTO object_refs(ref_kind,ref_id,object_id) VALUES('MESSAGE_ATTACHMENT',?,?)`, attachment.ID, attachment.ObjectID); err != nil {
				return err
			}
		}
		if _, err := tx.ExecContext(ctx, "INSERT INTO mailbox_entries(entry_id,account_id,content_id,folder,is_read) VALUES(?,?,?,'SENT',1)", uuid.NewString(), command.AccountID, command.ContentID); err != nil {
			return err
		}
		if _, err := tx.ExecContext(ctx, `INSERT INTO send_intents(intent_id,account_id,draft_id,draft_version,request_key,payload_sha256,dispatch_scope_id,content_id,raw_object_id,raw_sha256,raw_size,sender_address,envelope_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)`, command.IntentID, command.AccountID, command.Draft.ID, command.Draft.Version, command.RequestKey, command.PayloadSHA256, command.DispatchScopeID, command.ContentID, command.RawObjectID, command.RawSHA256, command.RawSize, command.SenderAddress, string(envelope)); err != nil {
			return err
		}
		if _, err := tx.ExecContext(ctx, `INSERT INTO mailbox_outbox(event_id,aggregate_id,topic,message_key,payload) VALUES(?,?, 'guihong_mail_send_v1',?,?)`, command.OutboxEventID, command.IntentID, "send:"+command.IntentID, string(command.OutboxPayload)); err != nil {
			return err
		}
		if _, err := tx.ExecContext(ctx, `DELETE r FROM object_refs r JOIN draft_attachments a ON a.attachment_id=r.ref_id AND r.ref_kind='DRAFT_ATTACHMENT' WHERE a.draft_id=?`, command.Draft.ID); err != nil {
			return err
		}
		_, err := tx.ExecContext(ctx, "DELETE FROM drafts WHERE draft_id=? AND account_id=?", command.Draft.ID, command.AccountID)
		return err
	})
	if err != nil {
		var duplicate *mysql.MySQLError
		if errors.As(err, &duplicate) && duplicate.Number == 1062 {
			existing, readErr := r.ExistingSend(ctx, command.AccountID, command.RequestKey)
			if readErr == nil && existing != nil && existing.DraftID == command.Draft.ID && existing.PayloadSHA256 == command.PayloadSHA256 {
				return *existing, nil
			}
			return domain.SendIntent{}, domain.ErrIdempotencyConflict
		}
		return domain.SendIntent{}, err
	}
	value, err := r.Send(ctx, command.AccountID, command.IntentID)
	return value, err
}

func (r *MailboxRepository) PendingSendEvents(ctx context.Context, limit int) ([]domain.OutboxEvent, error) {
	if limit < 1 || limit > 20 {
		return nil, fmt.Errorf("invalid outbox batch")
	}
	rows, err := r.database.QueryContext(ctx, `SELECT event_id,topic,message_key,payload FROM mailbox_outbox WHERE published_at IS NULL AND next_attempt_at<=CURRENT_TIMESTAMP(6) ORDER BY created_at,event_id LIMIT ?`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []domain.OutboxEvent{}
	for rows.Next() {
		var value domain.OutboxEvent
		if err := rows.Scan(&value.ID, &value.Topic, &value.Key, &value.Payload); err != nil {
			return nil, err
		}
		result = append(result, value)
	}
	return result, rows.Err()
}

func (r *MailboxRepository) MarkSendEventPublished(ctx context.Context, id, messageID string) error {
	return r.witness.Write(ctx, "send-outbox-published|"+id+"|"+messageID, func(tx *sql.Tx) error {
		_, err := tx.ExecContext(ctx, "UPDATE mailbox_outbox SET published_at=CURRENT_TIMESTAMP(6),attempts=attempts+1 WHERE event_id=? AND published_at IS NULL", id)
		return err
	})
}

func (r *MailboxRepository) EnabledAccount(ctx context.Context, address string) (string, error) {
	var id string
	err := r.database.QueryRowContext(ctx, "SELECT account_id FROM accounts WHERE address=? AND enabled=1", address).Scan(&id)
	if errors.Is(err, sql.ErrNoRows) {
		return "", domain.ErrNotFound
	}
	return id, err
}

func (r *MailboxRepository) ImportIngress(ctx context.Context, command domain.IngressImport) (domain.IngressImportResult, error) {
	if err := r.ready(ctx); err != nil {
		return domain.IngressImportResult{}, err
	}
	result := domain.IngressImportResult{}
	err := r.witness.Write(ctx, "ingress-import|"+command.SpoolID+"|"+command.RawSHA256, func(tx *sql.Tx) error {
		existing := map[string]string{}
		rows, err := tx.QueryContext(ctx, "SELECT recipient_account_id,raw_sha256 FROM ingress_import_receipts WHERE spool_id=? FOR UPDATE", command.SpoolID)
		if err != nil {
			return err
		}
		for rows.Next() {
			var account, digest string
			if err := rows.Scan(&account, &digest); err != nil {
				rows.Close()
				return err
			}
			existing[account] = digest
		}
		rows.Close()
		for _, member := range command.Members {
			if digest, ok := existing[member.AccountID]; ok && digest != command.RawSHA256 {
				return domain.ErrIdempotencyConflict
			}
		}
		if len(existing) == len(command.Members) {
			return nil
		}
		result.Created = true
		message := command.Imported
		p := message.Parsed
		contentID := ""
		err = tx.QueryRowContext(ctx, "SELECT content_id FROM message_contents WHERE raw_sha256=? AND raw_size=? FOR UPDATE", message.RawSHA256, message.RawSize).Scan(&contentID)
		if errors.Is(err, sql.ErrNoRows) {
			contentID = message.ContentID
			if _, err = tx.ExecContext(ctx, `INSERT INTO message_contents(content_id,raw_object_id,raw_sha256,raw_size,message_id,from_address,from_name,subject,text_body,safe_html,sent_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)`, contentID, message.RawObjectID, message.RawSHA256, message.RawSize, nullString(p.MessageID), p.From.Address, nullString(p.From.Name), p.Subject, p.TextBody, p.SafeHTML, p.SentAt); err != nil {
				return err
			}
			result.AdoptedObjects = true
		} else if err != nil {
			return err
		}
		if result.AdoptedObjects {
			for _, recipient := range p.Recipients {
				if _, err = tx.ExecContext(ctx, `INSERT INTO message_recipients(content_id,recipient_kind,ordinal_no,address,display_name) VALUES(?,?,?,?,?)`, contentID, recipient.Kind, recipient.Ordinal, recipient.Address, recipient.Name); err != nil {
					return err
				}
			}
			for ordinal, attachment := range message.Attachments {
				if _, err = tx.ExecContext(ctx, `INSERT INTO message_attachments(attachment_id,content_id,object_id,ordinal_no,file_name,media_type,sha256,byte_size) VALUES(?,?,?,?,?,?,?,?)`, attachment.ID, contentID, attachment.ObjectID, ordinal, attachment.FileName, attachment.MediaType, attachment.SHA256, attachment.Size); err != nil {
					return err
				}
			}
		}
		for _, member := range command.Members {
			if _, ok := existing[member.AccountID]; ok {
				continue
			}
			var enabled bool
			if err := tx.QueryRowContext(ctx, "SELECT enabled FROM accounts WHERE account_id=?", member.AccountID).Scan(&enabled); err != nil || !enabled {
				return invalid("MEMBER_ACCOUNT_UNAVAILABLE")
			}
			entry := uuid.NewString()
			if _, err := tx.ExecContext(ctx, "INSERT INTO mailbox_entries(entry_id,account_id,content_id,folder,is_read) VALUES(?,?,?,?,?)", entry, member.AccountID, contentID, member.Folder, member.Read); err != nil {
				return err
			}
			if _, err := tx.ExecContext(ctx, "INSERT INTO ingress_import_receipts(spool_id,recipient_account_id,raw_sha256,entry_id) VALUES(?,?,?,?)", command.SpoolID, member.AccountID, command.RawSHA256, entry); err != nil {
				return err
			}
		}
		return nil
	})
	return result, err
}
