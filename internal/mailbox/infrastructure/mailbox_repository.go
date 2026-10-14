package infrastructure

import (
	"context"
	"database/sql"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/NoctilumeDev/GuiHongMail/internal/mailbox/domain"
	"github.com/NoctilumeDev/GuiHongMail/internal/platform"
	"github.com/go-sql-driver/mysql"
	"github.com/google/uuid"
)

const summarySQL = `SELECT e.entry_id,e.content_id,e.folder,e.is_read,e.category_id,e.version_no,e.created_at,c.from_address,c.from_name,c.subject,c.text_body,c.sent_at,(SELECT COUNT(*) FROM message_attachments a WHERE a.content_id=e.content_id) FROM mailbox_entries e JOIN message_contents c ON c.content_id=e.content_id`

type MailboxRepository struct {
	database *sql.DB
	witness  *platform.Witness
	writable func(context.Context) bool
}

func NewMailboxRepository(database *sql.DB, witness *platform.Witness, writable func(context.Context) bool) *MailboxRepository {
	return &MailboxRepository{database: database, witness: witness, writable: writable}
}
func (r *MailboxRepository) Available(ctx context.Context) bool { return r.writable(ctx) }
func (r *MailboxRepository) AccountAddress(ctx context.Context, accountID string) (string, error) {
	var value string
	err := r.database.QueryRowContext(ctx, "SELECT address FROM accounts WHERE account_id=? AND enabled=1", accountID).Scan(&value)
	if errors.Is(err, sql.ErrNoRows) {
		return "", domain.ErrNotFound
	}
	return value, err
}
func (r *MailboxRepository) ReplyReference(ctx context.Context, accountID, contentID string) (string, error) {
	var value sql.NullString
	err := r.database.QueryRowContext(ctx, `SELECT c.message_id FROM message_contents c JOIN mailbox_entries e ON e.content_id=c.content_id WHERE e.account_id=? AND c.content_id=?`, accountID, contentID).Scan(&value)
	if errors.Is(err, sql.ErrNoRows) {
		return "", domain.ErrNotFound
	}
	if err != nil {
		return "", err
	}
	return value.String, nil
}
func (r *MailboxRepository) ready(ctx context.Context) error {
	if !r.Available(ctx) {
		return fmt.Errorf("SERVICE_UNAVAILABLE")
	}
	return nil
}
func invalid(code string) error { return &domain.InvalidError{Code: code} }
func duplicate(err error, code string) error {
	var e *mysql.MySQLError
	if errors.As(err, &e) && e.Number == 1062 {
		return invalid(code)
	}
	return err
}

func (r *MailboxRepository) ImportMessage(ctx context.Context, message domain.ImportedMessage, members []domain.Member) error {
	if err := r.ready(ctx); err != nil {
		return err
	}
	err := r.witness.Write(ctx, "mailbox-import|"+message.ContentID+"|"+message.RawSHA256, func(tx *sql.Tx) error {
		p := message.Parsed
		_, err := tx.ExecContext(ctx, `INSERT INTO message_contents(content_id,raw_object_id,raw_sha256,raw_size,message_id,from_address,from_name,subject,text_body,safe_html,sent_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)`, message.ContentID, message.RawObjectID, message.RawSHA256, message.RawSize, nullString(p.MessageID), p.From.Address, nullString(p.From.Name), p.Subject, p.TextBody, p.SafeHTML, p.SentAt)
		if err != nil {
			return err
		}
		for _, recipient := range p.Recipients {
			if _, err = tx.ExecContext(ctx, `INSERT INTO message_recipients(content_id,recipient_kind,ordinal_no,address,display_name) VALUES(?,?,?,?,?)`, message.ContentID, recipient.Kind, recipient.Ordinal, recipient.Address, recipient.Name); err != nil {
				return err
			}
		}
		for ordinal, attachment := range message.Attachments {
			if _, err = tx.ExecContext(ctx, `INSERT INTO message_attachments(attachment_id,content_id,object_id,ordinal_no,file_name,media_type,sha256,byte_size) VALUES(?,?,?,?,?,?,?,?)`, attachment.ID, message.ContentID, attachment.ObjectID, ordinal, attachment.FileName, attachment.MediaType, attachment.SHA256, attachment.Size); err != nil {
				return err
			}
		}
		for _, member := range members {
			var enabled bool
			if err = tx.QueryRowContext(ctx, "SELECT enabled FROM accounts WHERE account_id=?", member.AccountID).Scan(&enabled); err != nil || !enabled {
				return invalid("MEMBER_ACCOUNT_UNAVAILABLE")
			}
			if _, err = tx.ExecContext(ctx, "INSERT INTO mailbox_entries(entry_id,account_id,content_id,folder,is_read) VALUES(?,?,?,?,?)", uuid.NewString(), member.AccountID, message.ContentID, member.Folder, member.Read); err != nil {
				return err
			}
		}
		return nil
	})
	return duplicate(err, "MESSAGE_ALREADY_IMPORTED")
}

func (r *MailboxRepository) FolderCounts(ctx context.Context, accountID string) ([]domain.FolderCount, error) {
	if err := r.ready(ctx); err != nil {
		return nil, err
	}
	counts := map[domain.Folder]domain.FolderCount{}
	for _, f := range []domain.Folder{domain.Inbox, domain.Sent, domain.Archive, domain.Spam, domain.Trash} {
		counts[f] = domain.FolderCount{Folder: f}
	}
	rows, err := r.database.QueryContext(ctx, "SELECT folder,COUNT(*),SUM(IF(is_read,0,1)) FROM mailbox_entries WHERE account_id=? GROUP BY folder", accountID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var f domain.Folder
		var total, unread int64
		if err := rows.Scan(&f, &total, &unread); err != nil {
			return nil, err
		}
		counts[f] = domain.FolderCount{Folder: f, Total: total, Unread: unread}
	}
	result := make([]domain.FolderCount, 0, 5)
	for _, f := range []domain.Folder{domain.Inbox, domain.Sent, domain.Archive, domain.Spam, domain.Trash} {
		result = append(result, counts[f])
	}
	return result, rows.Err()
}

func (r *MailboxRepository) List(ctx context.Context, accountID string, folder *domain.Folder, categoryID *string, query string, size int, cursor string) (domain.Page[domain.MessageSummary], error) {
	if err := r.ready(ctx); err != nil {
		return domain.Page[domain.MessageSummary]{}, err
	}
	statement := summarySQL + " WHERE e.account_id=?"
	args := []any{accountID}
	if categoryID != nil {
		var exists int
		if err := r.database.QueryRowContext(ctx, "SELECT 1 FROM categories WHERE account_id=? AND category_id=?", accountID, *categoryID).Scan(&exists); errors.Is(err, sql.ErrNoRows) {
			return domain.Page[domain.MessageSummary]{}, domain.ErrNotFound
		} else if err != nil {
			return domain.Page[domain.MessageSummary]{}, err
		}
		statement += " AND e.category_id=?"
		args = append(args, *categoryID)
	} else {
		statement += " AND e.folder=?"
		args = append(args, *folder)
	}
	if strings.TrimSpace(query) != "" {
		pattern := "%" + escapeLike(strings.TrimSpace(query)) + "%"
		statement += ` AND (c.from_address LIKE ? ESCAPE '\\' OR c.from_name LIKE ? ESCAPE '\\' OR c.subject LIKE ? ESCAPE '\\' OR c.text_body LIKE ? ESCAPE '\\' OR EXISTS(SELECT 1 FROM message_recipients sr WHERE sr.content_id=c.content_id AND sr.address LIKE ? ESCAPE '\\'))`
		for range 5 {
			args = append(args, pattern)
		}
	}
	if cursor != "" {
		at, id, err := decodeCursor(cursor)
		if err != nil {
			return domain.Page[domain.MessageSummary]{}, err
		}
		statement += " AND (e.created_at<? OR (e.created_at=? AND e.entry_id<?))"
		args = append(args, at, at, id)
	}
	statement += " ORDER BY e.created_at DESC,e.entry_id DESC LIMIT ?"
	args = append(args, size+1)
	rows, err := r.database.QueryContext(ctx, statement, args...)
	if err != nil {
		return domain.Page[domain.MessageSummary]{}, err
	}
	defer rows.Close()
	items := []domain.MessageSummary{}
	for rows.Next() {
		item, err := scanSummary(rows)
		if err != nil {
			return domain.Page[domain.MessageSummary]{}, err
		}
		items = append(items, item)
	}
	if err := rows.Err(); err != nil {
		return domain.Page[domain.MessageSummary]{}, err
	}
	var next *string
	if len(items) > size {
		items = items[:size]
		value := encodeCursor(items[len(items)-1].ReceivedAt, items[len(items)-1].EntryID)
		next = &value
	}
	return domain.Page[domain.MessageSummary]{Items: items, NextCursor: next}, nil
}

func (r *MailboxRepository) Message(ctx context.Context, accountID, entryID string) (domain.MessageDetail, error) {
	if err := r.ready(ctx); err != nil {
		return domain.MessageDetail{}, err
	}
	item, err := scanSummary(r.database.QueryRowContext(ctx, summarySQL+" WHERE e.account_id=? AND e.entry_id=?", accountID, entryID))
	if errors.Is(err, sql.ErrNoRows) {
		return domain.MessageDetail{}, domain.ErrNotFound
	}
	if err != nil {
		return domain.MessageDetail{}, err
	}
	recipients := []domain.Recipient{}
	rows, err := r.database.QueryContext(ctx, "SELECT recipient_kind,ordinal_no,address,display_name FROM message_recipients WHERE content_id=? AND (?='SENT' OR recipient_kind<>'BCC') ORDER BY FIELD(recipient_kind,'TO','CC','BCC'),ordinal_no", item.ContentID, item.Folder)
	if err != nil {
		return domain.MessageDetail{}, err
	}
	for rows.Next() {
		var v domain.Recipient
		if err := rows.Scan(&v.Kind, &v.Ordinal, &v.Address, &v.Name); err != nil {
			rows.Close()
			return domain.MessageDetail{}, err
		}
		recipients = append(recipients, v)
	}
	rows.Close()
	attachments, err := r.attachments(ctx, "SELECT attachment_id,object_id,file_name,media_type,sha256,byte_size FROM message_attachments WHERE content_id=? ORDER BY ordinal_no", item.ContentID)
	if err != nil {
		return domain.MessageDetail{}, err
	}
	detail := domain.MessageDetail{Summary: item, Recipients: recipients, Attachments: attachments}
	err = r.database.QueryRowContext(ctx, "SELECT text_body,safe_html,raw_sha256,raw_size FROM message_contents WHERE content_id=?", item.ContentID).Scan(&detail.TextBody, &detail.SafeHTML, &detail.RawSHA256, &detail.RawSize)
	return detail, err
}

func (r *MailboxRepository) Change(ctx context.Context, accountID, entryID string, change domain.MessageChange) (domain.MessageDetail, error) {
	if err := r.ready(ctx); err != nil {
		return domain.MessageDetail{}, err
	}
	descriptor := fmt.Sprintf("mailbox-change|%s|%s", accountID, entryID)
	err := r.witness.Write(ctx, descriptor, func(tx *sql.Tx) error {
		current, err := lockedVersion(ctx, tx, "mailbox_entries", "entry_id", entryID, accountID)
		if err != nil {
			return err
		}
		if change.ExpectedVersion != nil && *change.ExpectedVersion != current {
			return &domain.VersionConflictError{Current: current}
		}
		if change.CategorySet && change.CategoryID != nil {
			var one int
			if err := tx.QueryRowContext(ctx, "SELECT 1 FROM categories WHERE account_id=? AND category_id=?", accountID, *change.CategoryID).Scan(&one); err != nil {
				return domain.ErrNotFound
			}
		}
		var readSet bool
		var read bool
		if change.Read != nil {
			readSet = true
			read = *change.Read
		}
		var folderSet bool
		folder := domain.Inbox
		if change.Folder != nil {
			folderSet = true
			folder = *change.Folder
		}
		_, err = tx.ExecContext(ctx, "UPDATE mailbox_entries SET is_read=IF(?,?,is_read),folder=IF(?,?,folder),category_id=IF(?,?,category_id),version_no=version_no+1 WHERE entry_id=? AND account_id=?", readSet, read, folderSet, folder, change.CategorySet, change.CategoryID, entryID, accountID)
		return err
	})
	if err != nil {
		return domain.MessageDetail{}, err
	}
	return r.Message(ctx, accountID, entryID)
}

func (r *MailboxRepository) CreateDraft(ctx context.Context, accountID string, input domain.DraftInput) (domain.Draft, error) {
	if err := r.ready(ctx); err != nil {
		return domain.Draft{}, err
	}
	id := uuid.NewString()
	err := r.witness.Write(ctx, "draft-create|"+accountID+"|"+id, func(tx *sql.Tx) error {
		if err := assertSourceMembership(ctx, tx, accountID, input.SourceContentID); err != nil {
			return err
		}
		to, _ := json.Marshal(input.To)
		cc, _ := json.Marshal(input.CC)
		bcc, _ := json.Marshal(input.BCC)
		_, err := tx.ExecContext(ctx, "INSERT INTO drafts(draft_id,account_id,subject,text_body,html_body,to_json,cc_json,bcc_json,mode,source_content_id) VALUES(?,?,?,?,?,?,?,?,?,?)", id, accountID, input.Subject, input.TextBody, input.HTMLBody, string(to), string(cc), string(bcc), input.Mode, input.SourceContentID)
		return err
	})
	if err != nil {
		return domain.Draft{}, err
	}
	return r.Draft(ctx, accountID, id)
}
func (r *MailboxRepository) Draft(ctx context.Context, accountID, draftID string) (domain.Draft, error) {
	if err := r.ready(ctx); err != nil {
		return domain.Draft{}, err
	}
	return r.readDraft(ctx, accountID, draftID)
}
func (r *MailboxRepository) readDraft(ctx context.Context, accountID, draftID string) (domain.Draft, error) {
	var d domain.Draft
	var to, cc, bcc string
	var source sql.NullString
	err := r.database.QueryRowContext(ctx, "SELECT draft_id,version_no,subject,text_body,html_body,to_json,cc_json,bcc_json,mode,source_content_id,created_at,updated_at FROM drafts WHERE account_id=? AND draft_id=?", accountID, draftID).Scan(&d.ID, &d.Version, &d.Subject, &d.TextBody, &d.HTMLBody, &to, &cc, &bcc, &d.Mode, &source, &d.CreatedAt, &d.UpdatedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return d, domain.ErrNotFound
	}
	if err != nil {
		return d, err
	}
	_ = json.Unmarshal([]byte(to), &d.To)
	_ = json.Unmarshal([]byte(cc), &d.CC)
	_ = json.Unmarshal([]byte(bcc), &d.BCC)
	if d.To == nil {
		d.To = []string{}
	}
	if d.CC == nil {
		d.CC = []string{}
	}
	if d.BCC == nil {
		d.BCC = []string{}
	}
	if source.Valid {
		d.SourceContentID = &source.String
	}
	d.Attachments, err = r.attachments(ctx, "SELECT attachment_id,object_id,file_name,media_type,sha256,byte_size FROM draft_attachments WHERE draft_id=? ORDER BY created_at,attachment_id", draftID)
	return d, err
}
func (r *MailboxRepository) Drafts(ctx context.Context, accountID string, size int, cursor string) (domain.Page[domain.Draft], error) {
	if err := r.ready(ctx); err != nil {
		return domain.Page[domain.Draft]{}, err
	}
	statement := "SELECT draft_id,updated_at FROM drafts WHERE account_id=?"
	args := []any{accountID}
	if cursor != "" {
		at, id, err := decodeCursor(cursor)
		if err != nil {
			return domain.Page[domain.Draft]{}, err
		}
		statement += " AND (updated_at<? OR (updated_at=? AND draft_id<?))"
		args = append(args, at, at, id)
	}
	statement += " ORDER BY updated_at DESC,draft_id DESC LIMIT ?"
	args = append(args, size+1)
	rows, err := r.database.QueryContext(ctx, statement, args...)
	if err != nil {
		return domain.Page[domain.Draft]{}, err
	}
	type ref struct {
		id string
		at time.Time
	}
	refs := []ref{}
	for rows.Next() {
		var v ref
		if err := rows.Scan(&v.id, &v.at); err != nil {
			rows.Close()
			return domain.Page[domain.Draft]{}, err
		}
		refs = append(refs, v)
	}
	rows.Close()
	items := []domain.Draft{}
	for _, v := range refs {
		d, err := r.readDraft(ctx, accountID, v.id)
		if err != nil {
			return domain.Page[domain.Draft]{}, err
		}
		items = append(items, d)
	}
	var next *string
	if len(items) > size {
		items = items[:size]
		value := encodeCursor(items[len(items)-1].UpdatedAt, items[len(items)-1].ID)
		next = &value
	}
	return domain.Page[domain.Draft]{Items: items, NextCursor: next}, nil
}
func (r *MailboxRepository) UpdateDraft(ctx context.Context, accountID, draftID string, expected int64, input domain.DraftInput) (domain.Draft, error) {
	err := r.witness.Write(ctx, fmt.Sprintf("draft-update|%s|%s|%d", accountID, draftID, expected), func(tx *sql.Tx) error {
		current, err := lockedVersion(ctx, tx, "drafts", "draft_id", draftID, accountID)
		if err != nil {
			return err
		}
		if current != expected {
			return &domain.VersionConflictError{Current: current}
		}
		if err := assertSourceMembership(ctx, tx, accountID, input.SourceContentID); err != nil {
			return err
		}
		to, _ := json.Marshal(input.To)
		cc, _ := json.Marshal(input.CC)
		bcc, _ := json.Marshal(input.BCC)
		_, err = tx.ExecContext(ctx, "UPDATE drafts SET subject=?,text_body=?,html_body=?,to_json=?,cc_json=?,bcc_json=?,mode=?,source_content_id=?,version_no=version_no+1 WHERE draft_id=? AND account_id=?", input.Subject, input.TextBody, input.HTMLBody, string(to), string(cc), string(bcc), input.Mode, input.SourceContentID, draftID, accountID)
		return err
	})
	if err != nil {
		return domain.Draft{}, err
	}
	return r.Draft(ctx, accountID, draftID)
}
func (r *MailboxRepository) DeleteDraft(ctx context.Context, accountID, draftID string, expected int64) ([]domain.Attachment, error) {
	var released []domain.Attachment
	err := r.witness.Write(ctx, fmt.Sprintf("draft-delete|%s|%s|%d", accountID, draftID, expected), func(tx *sql.Tx) error {
		current, err := lockedVersion(ctx, tx, "drafts", "draft_id", draftID, accountID)
		if err != nil {
			return err
		}
		if current != expected {
			return &domain.VersionConflictError{Current: current}
		}
		rows, err := tx.QueryContext(ctx, "SELECT attachment_id,object_id,file_name,media_type,sha256,byte_size FROM draft_attachments WHERE draft_id=?", draftID)
		if err != nil {
			return err
		}
		for rows.Next() {
			var a domain.Attachment
			if err := rows.Scan(&a.ID, &a.ObjectID, &a.FileName, &a.MediaType, &a.SHA256, &a.Size); err != nil {
				rows.Close()
				return err
			}
			released = append(released, a)
		}
		rows.Close()
		_, err = tx.ExecContext(ctx, "DELETE FROM drafts WHERE draft_id=? AND account_id=?", draftID, accountID)
		return err
	})
	return released, err
}
func (r *MailboxRepository) AddDraftAttachment(ctx context.Context, accountID, draftID string, expected int64, a domain.StoredAttachment) (domain.Draft, error) {
	err := r.witness.Write(ctx, "draft-attachment|"+accountID+"|"+draftID+"|"+a.ID, func(tx *sql.Tx) error {
		current, err := lockedVersion(ctx, tx, "drafts", "draft_id", draftID, accountID)
		if err != nil {
			return err
		}
		if current != expected {
			return &domain.VersionConflictError{Current: current}
		}
		var count int
		var total int64
		if err := tx.QueryRowContext(ctx, "SELECT COUNT(*),COALESCE(SUM(byte_size),0) FROM draft_attachments WHERE draft_id=? FOR UPDATE", draftID).Scan(&count, &total); err != nil {
			return err
		}
		if count >= 20 || total+a.Size > 4*1024*1024 {
			return invalid("ATTACHMENT_TOTAL_EXCEEDED")
		}
		if _, err := tx.ExecContext(ctx, "INSERT INTO draft_attachments(attachment_id,draft_id,object_id,file_name,media_type,sha256,byte_size) VALUES(?,?,?,?,?,?,?)", a.ID, draftID, a.ObjectID, a.FileName, a.MediaType, a.SHA256, a.Size); err != nil {
			return err
		}
		_, err = tx.ExecContext(ctx, "UPDATE drafts SET version_no=version_no+1 WHERE draft_id=?", draftID)
		return err
	})
	if err != nil {
		return domain.Draft{}, err
	}
	return r.Draft(ctx, accountID, draftID)
}

func (r *MailboxRepository) AuthorizedMessageAttachment(ctx context.Context, accountID, entryID, attachmentID string) (domain.Attachment, error) {
	return r.attachment(ctx, "SELECT a.attachment_id,a.object_id,a.file_name,a.media_type,a.sha256,a.byte_size FROM mailbox_entries e JOIN message_attachments a ON a.content_id=e.content_id WHERE e.account_id=? AND e.entry_id=? AND a.attachment_id=?", accountID, entryID, attachmentID)
}
func (r *MailboxRepository) AuthorizedDraftAttachment(ctx context.Context, accountID, draftID, attachmentID string) (domain.Attachment, error) {
	return r.attachment(ctx, "SELECT a.attachment_id,a.object_id,a.file_name,a.media_type,a.sha256,a.byte_size FROM drafts d JOIN draft_attachments a ON a.draft_id=d.draft_id WHERE d.account_id=? AND d.draft_id=? AND a.attachment_id=?", accountID, draftID, attachmentID)
}

func (r *MailboxRepository) Categories(ctx context.Context, accountID string) ([]domain.Category, error) {
	if err := r.ready(ctx); err != nil {
		return nil, err
	}
	rows, err := r.database.QueryContext(ctx, "SELECT c.category_id,c.name,c.version_no,COUNT(e.entry_id),COALESCE(SUM(IF(e.is_read,0,1)),0) FROM categories c LEFT JOIN mailbox_entries e ON e.category_id=c.category_id AND e.account_id=c.account_id WHERE c.account_id=? GROUP BY c.category_id,c.name,c.version_no ORDER BY c.name,c.category_id", accountID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []domain.Category{}
	for rows.Next() {
		var c domain.Category
		if err := rows.Scan(&c.ID, &c.Name, &c.Version, &c.Total, &c.Unread); err != nil {
			return nil, err
		}
		items = append(items, c)
	}
	return items, rows.Err()
}
func (r *MailboxRepository) CreateCategory(ctx context.Context, accountID, name string) (domain.Category, error) {
	id := uuid.NewString()
	err := r.witness.Write(ctx, "category-create|"+accountID+"|"+id, func(tx *sql.Tx) error {
		var count int
		if err := tx.QueryRowContext(ctx, "SELECT COUNT(*) FROM categories WHERE account_id=? FOR UPDATE", accountID).Scan(&count); err != nil {
			return err
		}
		if count >= 50 {
			return invalid("CATEGORY_LIMIT")
		}
		_, err := tx.ExecContext(ctx, "INSERT INTO categories(category_id,account_id,name) VALUES(?,?,?)", id, accountID, name)
		return err
	})
	if err = duplicate(err, "CATEGORY_NAME_EXISTS"); err != nil {
		return domain.Category{}, err
	}
	return r.category(ctx, accountID, id)
}
func (r *MailboxRepository) RenameCategory(ctx context.Context, accountID, id string, expected int64, name string) (domain.Category, error) {
	err := r.witness.Write(ctx, fmt.Sprintf("category-rename|%s|%s|%d", accountID, id, expected), func(tx *sql.Tx) error {
		current, err := lockedVersion(ctx, tx, "categories", "category_id", id, accountID)
		if err != nil {
			return err
		}
		if current != expected {
			return &domain.VersionConflictError{Current: current}
		}
		_, err = tx.ExecContext(ctx, "UPDATE categories SET name=?,version_no=version_no+1 WHERE category_id=? AND account_id=?", name, id, accountID)
		return err
	})
	if err = duplicate(err, "CATEGORY_NAME_EXISTS"); err != nil {
		return domain.Category{}, err
	}
	return r.category(ctx, accountID, id)
}
func (r *MailboxRepository) DeleteCategory(ctx context.Context, accountID, id string, expected int64) error {
	return r.witness.Write(ctx, fmt.Sprintf("category-delete|%s|%s|%d", accountID, id, expected), func(tx *sql.Tx) error {
		current, err := lockedVersion(ctx, tx, "categories", "category_id", id, accountID)
		if err != nil {
			return err
		}
		if current != expected {
			return &domain.VersionConflictError{Current: current}
		}
		if _, err = tx.ExecContext(ctx, "UPDATE mailbox_entries SET category_id=NULL,version_no=version_no+1 WHERE account_id=? AND category_id=?", accountID, id); err != nil {
			return err
		}
		_, err = tx.ExecContext(ctx, "DELETE FROM categories WHERE category_id=? AND account_id=?", id, accountID)
		return err
	})
}
func (r *MailboxRepository) category(ctx context.Context, accountID, id string) (domain.Category, error) {
	items, err := r.Categories(ctx, accountID)
	if err != nil {
		return domain.Category{}, err
	}
	for _, c := range items {
		if c.ID == id {
			return c, nil
		}
	}
	return domain.Category{}, domain.ErrNotFound
}

type rowScanner interface{ Scan(...any) error }

func scanSummary(row rowScanner) (domain.MessageSummary, error) {
	var v domain.MessageSummary
	var category, from sql.NullString
	var sent sql.NullTime
	var text string
	err := row.Scan(&v.EntryID, &v.ContentID, &v.Folder, &v.Read, &category, &v.Version, &v.ReceivedAt, &v.FromAddress, &from, &v.Subject, &text, &sent, &v.AttachmentCount)
	if category.Valid {
		v.CategoryID = &category.String
	}
	if from.Valid {
		v.FromName = &from.String
	}
	if sent.Valid {
		t := sent.Time
		v.SentAt = &t
	}
	v.Preview = strings.Join(strings.Fields(text), " ")
	if len([]rune(v.Preview)) > 200 {
		v.Preview = string([]rune(v.Preview)[:200])
	}
	return v, err
}
func (r *MailboxRepository) attachments(ctx context.Context, query string, args ...any) ([]domain.Attachment, error) {
	rows, err := r.database.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []domain.Attachment{}
	for rows.Next() {
		var a domain.Attachment
		if err := rows.Scan(&a.ID, &a.ObjectID, &a.FileName, &a.MediaType, &a.SHA256, &a.Size); err != nil {
			return nil, err
		}
		items = append(items, a)
	}
	return items, rows.Err()
}
func (r *MailboxRepository) attachment(ctx context.Context, query string, args ...any) (domain.Attachment, error) {
	var a domain.Attachment
	err := r.database.QueryRowContext(ctx, query, args...).Scan(&a.ID, &a.ObjectID, &a.FileName, &a.MediaType, &a.SHA256, &a.Size)
	if errors.Is(err, sql.ErrNoRows) {
		return a, domain.ErrNotFound
	}
	return a, err
}
func lockedVersion(ctx context.Context, tx *sql.Tx, table, column, id, account string) (int64, error) {
	var current int64
	err := tx.QueryRowContext(ctx, "SELECT version_no FROM "+table+" WHERE "+column+"=? AND account_id=? FOR UPDATE", id, account).Scan(&current)
	if errors.Is(err, sql.ErrNoRows) {
		return 0, domain.ErrNotFound
	}
	return current, err
}
func assertSourceMembership(ctx context.Context, tx *sql.Tx, accountID string, contentID *string) error {
	if contentID == nil {
		return nil
	}
	var one int
	err := tx.QueryRowContext(ctx, "SELECT 1 FROM mailbox_entries WHERE account_id=? AND content_id=?", accountID, *contentID).Scan(&one)
	if errors.Is(err, sql.ErrNoRows) {
		return domain.ErrNotFound
	}
	return err
}
func nullString(value string) any {
	if strings.TrimSpace(value) == "" {
		return nil
	}
	return value
}
func escapeLike(value string) string {
	value = strings.ReplaceAll(value, "\\", "\\\\")
	value = strings.ReplaceAll(value, "%", "\\%")
	return strings.ReplaceAll(value, "_", "\\_")
}
func encodeCursor(at time.Time, id string) string {
	return base64.RawURLEncoding.EncodeToString([]byte(at.UTC().Format(time.RFC3339Nano) + "|" + id))
}
func decodeCursor(value string) (time.Time, string, error) {
	raw, err := base64.RawURLEncoding.DecodeString(value)
	if err != nil {
		return time.Time{}, "", invalid("INVALID_CURSOR")
	}
	parts := strings.Split(string(raw), "|")
	if len(parts) != 2 {
		return time.Time{}, "", invalid("INVALID_CURSOR")
	}
	at, err := time.Parse(time.RFC3339Nano, parts[0])
	if err != nil {
		return time.Time{}, "", invalid("INVALID_CURSOR")
	}
	id, err := uuid.Parse(parts[1])
	if err != nil {
		return time.Time{}, "", invalid("INVALID_CURSOR")
	}
	return at, id.String(), nil
}
