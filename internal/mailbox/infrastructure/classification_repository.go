package infrastructure

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/NoctilumeDev/GuiHongMail/internal/mailbox/domain"
	"github.com/google/uuid"
)

func (r *MailboxRepository) Rules(ctx context.Context, accountID string) ([]domain.ClassificationRule, error) {
	rows, err := r.database.QueryContext(ctx, `SELECT rule_id,category_id,rule_type,pattern_value,priority_no,auto_apply,enabled,version_no,created_at,updated_at FROM classification_rules WHERE account_id=? ORDER BY priority_no DESC,rule_id`, accountID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []domain.ClassificationRule{}
	for rows.Next() {
		value, err := scanRule(rows)
		if err != nil {
			return nil, err
		}
		result = append(result, value)
	}
	return result, rows.Err()
}

func (r *MailboxRepository) CreateRule(ctx context.Context, accountID string, value domain.ClassificationRule) (domain.ClassificationRule, error) {
	value.ID = uuid.NewString()
	err := r.witness.Write(ctx, "classification-rule-create|"+accountID+"|"+value.ID, func(tx *sql.Tx) error {
		if err := ownedCategory(ctx, tx, accountID, value.CategoryID); err != nil {
			return err
		}
		var count int
		if err := tx.QueryRowContext(ctx, "SELECT COUNT(*) FROM classification_rules WHERE account_id=? FOR UPDATE", accountID).Scan(&count); err != nil {
			return err
		}
		if count >= 100 {
			return invalid("CLASSIFICATION_RULE_LIMIT")
		}
		if _, err := tx.ExecContext(ctx, `INSERT INTO classification_rules(rule_id,account_id,category_id,rule_type,pattern_value,normalized_pattern,priority_no,auto_apply,enabled) VALUES(?,?,?,?,?,?,?,?,?)`, value.ID, accountID, value.CategoryID, value.Type, value.Pattern, value.Pattern, value.Priority, value.AutoApply, value.Enabled); err != nil {
			return err
		}
		_, err := tx.ExecContext(ctx, "UPDATE mailbox_entries SET classification_checked_at=NULL WHERE account_id=? AND category_source IS NULL", accountID)
		return err
	})
	if err != nil {
		return domain.ClassificationRule{}, err
	}
	return r.rule(ctx, accountID, value.ID)
}

func (r *MailboxRepository) UpdateRule(ctx context.Context, accountID string, value domain.ClassificationRule) (domain.ClassificationRule, error) {
	err := r.witness.Write(ctx, fmt.Sprintf("classification-rule-update|%s|%s|%d", accountID, value.ID, value.Version), func(tx *sql.Tx) error {
		var current int64
		err := tx.QueryRowContext(ctx, "SELECT version_no FROM classification_rules WHERE account_id=? AND rule_id=? FOR UPDATE", accountID, value.ID).Scan(&current)
		if errors.Is(err, sql.ErrNoRows) {
			return domain.ErrNotFound
		}
		if err != nil {
			return err
		}
		if current != value.Version {
			return &domain.VersionConflictError{Current: current}
		}
		if err := ownedCategory(ctx, tx, accountID, value.CategoryID); err != nil {
			return err
		}
		_, err = tx.ExecContext(ctx, `UPDATE classification_rules SET category_id=?,rule_type=?,pattern_value=?,normalized_pattern=?,priority_no=?,auto_apply=?,enabled=?,version_no=version_no+1 WHERE account_id=? AND rule_id=?`, value.CategoryID, value.Type, value.Pattern, value.Pattern, value.Priority, value.AutoApply, value.Enabled, accountID, value.ID)
		if err == nil {
			_, err = tx.ExecContext(ctx, "UPDATE mailbox_entries SET classification_checked_at=NULL WHERE account_id=? AND category_source IS NULL", accountID)
		}
		return err
	})
	if err != nil {
		return domain.ClassificationRule{}, err
	}
	return r.rule(ctx, accountID, value.ID)
}

func (r *MailboxRepository) DeleteRule(ctx context.Context, accountID, id string, version int64) error {
	return r.witness.Write(ctx, fmt.Sprintf("classification-rule-delete|%s|%s|%d", accountID, id, version), func(tx *sql.Tx) error {
		var current int64
		err := tx.QueryRowContext(ctx, "SELECT version_no FROM classification_rules WHERE account_id=? AND rule_id=? FOR UPDATE", accountID, id).Scan(&current)
		if errors.Is(err, sql.ErrNoRows) {
			return domain.ErrNotFound
		}
		if err != nil {
			return err
		}
		if current != version {
			return &domain.VersionConflictError{Current: current}
		}
		if _, err = tx.ExecContext(ctx, "DELETE FROM classification_rules WHERE account_id=? AND rule_id=?", accountID, id); err != nil {
			return err
		}
		_, err = tx.ExecContext(ctx, "UPDATE mailbox_entries SET classification_checked_at=NULL WHERE account_id=? AND category_source IS NULL", accountID)
		return err
	})
}

func (r *MailboxRepository) rule(ctx context.Context, accountID, id string) (domain.ClassificationRule, error) {
	value, err := scanRule(r.database.QueryRowContext(ctx, `SELECT rule_id,category_id,rule_type,pattern_value,priority_no,auto_apply,enabled,version_no,created_at,updated_at FROM classification_rules WHERE account_id=? AND rule_id=?`, accountID, id))
	if errors.Is(err, sql.ErrNoRows) {
		return value, domain.ErrNotFound
	}
	return value, err
}

func (r *MailboxRepository) Settings(ctx context.Context, accountID string) (domain.ClassificationSettings, error) {
	if _, err := r.database.ExecContext(ctx, "INSERT IGNORE INTO classification_settings(account_id) VALUES(?)", accountID); err != nil {
		return domain.ClassificationSettings{}, err
	}
	value := domain.ClassificationSettings{CategoryAuto: map[string]bool{}}
	if err := r.database.QueryRowContext(ctx, "SELECT algorithm_enabled,version_no FROM classification_settings WHERE account_id=?", accountID).Scan(&value.AlgorithmEnabled, &value.Version); err != nil {
		return value, err
	}
	rows, err := r.database.QueryContext(ctx, "SELECT category_id,enabled FROM classification_category_auto WHERE account_id=?", accountID)
	if err != nil {
		return value, err
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var enabled bool
		if err := rows.Scan(&id, &enabled); err != nil {
			return value, err
		}
		value.CategoryAuto[id] = enabled
	}
	return value, rows.Err()
}

func (r *MailboxRepository) SetAlgorithmEnabled(ctx context.Context, accountID string, version int64, enabled bool) (domain.ClassificationSettings, error) {
	err := r.witness.Write(ctx, fmt.Sprintf("classification-settings|%s|%d", accountID, version), func(tx *sql.Tx) error {
		if _, err := tx.ExecContext(ctx, "INSERT IGNORE INTO classification_settings(account_id) VALUES(?)", accountID); err != nil {
			return err
		}
		var current int64
		if err := tx.QueryRowContext(ctx, "SELECT version_no FROM classification_settings WHERE account_id=? FOR UPDATE", accountID).Scan(&current); err != nil {
			return err
		}
		if current != version {
			return &domain.VersionConflictError{Current: current}
		}
		if _, err := tx.ExecContext(ctx, "UPDATE classification_settings SET algorithm_enabled=?,version_no=version_no+1 WHERE account_id=?", enabled, accountID); err != nil {
			return err
		}
		if !enabled {
			if _, err := tx.ExecContext(ctx, "UPDATE classification_suggestions SET status_value='WITHDRAWN',decided_at=CURRENT_TIMESTAMP(6) WHERE account_id=? AND source_kind='ALGORITHM' AND status_value='PENDING'", accountID); err != nil {
				return err
			}
		}
		_, err := tx.ExecContext(ctx, "UPDATE mailbox_entries SET classification_checked_at=NULL WHERE account_id=? AND category_source IS NULL", accountID)
		return err
	})
	if err != nil {
		return domain.ClassificationSettings{}, err
	}
	return r.Settings(ctx, accountID)
}

func (r *MailboxRepository) SetCategoryAuto(ctx context.Context, accountID, categoryID string, enabled bool) (domain.ClassificationSettings, error) {
	err := r.witness.Write(ctx, "classification-category-auto|"+accountID+"|"+categoryID, func(tx *sql.Tx) error {
		if err := ownedCategory(ctx, tx, accountID, categoryID); err != nil {
			return err
		}
		if _, err := tx.ExecContext(ctx, `INSERT INTO classification_category_auto(account_id,category_id,enabled) VALUES(?,?,?) ON DUPLICATE KEY UPDATE enabled=VALUES(enabled),version_no=version_no+1`, accountID, categoryID, enabled); err != nil {
			return err
		}
		_, err := tx.ExecContext(ctx, "UPDATE mailbox_entries SET classification_checked_at=NULL WHERE account_id=? AND category_source IS NULL", accountID)
		return err
	})
	if err != nil {
		return domain.ClassificationSettings{}, err
	}
	return r.Settings(ctx, accountID)
}

func (r *MailboxRepository) ClassificationInput(ctx context.Context, accountID, entryID string) (domain.ClassificationInput, error) {
	var value domain.ClassificationInput
	var category, source sql.NullString
	var action sql.NullString
	err := r.database.QueryRowContext(ctx, `SELECT e.entry_id,e.account_id,e.category_id,e.category_source,e.category_action_id,e.version_no,e.folder,e.is_read,c.from_address,c.subject FROM mailbox_entries e JOIN message_contents c ON c.content_id=e.content_id WHERE e.account_id=? AND e.entry_id=?`, accountID, entryID).Scan(&value.EntryID, &value.AccountID, &category, &source, &action, &value.Version, &value.Folder, &value.Read, &value.FromAddress, &value.Subject)
	if errors.Is(err, sql.ErrNoRows) {
		return value, domain.ErrNotFound
	}
	if category.Valid {
		value.CategoryID = &category.String
	}
	if source.Valid {
		value.CategorySource = &source.String
	}
	if action.Valid {
		value.CategoryAction = &action.String
	}
	return value, err
}

func (r *MailboxRepository) CurrentClassification(ctx context.Context, accountID, entryID, actionID string) (domain.ClassificationSuggestion, error) {
	value, err := scanSuggestion(r.database.QueryRowContext(ctx, `SELECT s.suggestion_id,s.entry_id,s.category_id,s.source_kind,s.status_value,s.confidence,s.margin_value,s.reason_text,s.rule_id,s.rule_version,s.model_version,s.entry_version,s.created_at FROM classification_actions a JOIN classification_suggestions s ON s.suggestion_id=a.suggestion_id WHERE a.account_id=? AND a.entry_id=? AND a.action_id=? AND a.undone_at IS NULL`, accountID, entryID, actionID))
	if errors.Is(err, sql.ErrNoRows) {
		return value, domain.ErrNotFound
	}
	if err == nil {
		value.ActionID = &actionID
	}
	return value, err
}

func (r *MailboxRepository) TrainingSamples(ctx context.Context, accountID string, limit int) ([]domain.TrainingSample, error) {
	rows, err := r.database.QueryContext(ctx, `SELECT f.feedback_id,f.category_id,f.features_json FROM classification_feedback f WHERE f.account_id=? AND f.decision='CONFIRMED' AND f.category_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM classification_feedback n WHERE n.account_id=f.account_id AND n.entry_id=f.entry_id AND (n.created_at>f.created_at OR (n.created_at=f.created_at AND n.feedback_id>f.feedback_id))) ORDER BY f.created_at,f.feedback_id LIMIT ?`, accountID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []domain.TrainingSample{}
	for rows.Next() {
		var value domain.TrainingSample
		var raw []byte
		if err := rows.Scan(&value.ID, &value.CategoryID, &raw); err != nil {
			return nil, err
		}
		if err := json.Unmarshal(raw, &value.Features); err != nil {
			return nil, err
		}
		result = append(result, value)
	}
	return result, rows.Err()
}

func (r *MailboxRepository) StoreModel(ctx context.Context, accountID string, value domain.ModelPrediction) error {
	counts, err := json.Marshal(value.CategoryCounts)
	if err != nil {
		return err
	}
	model, err := json.Marshal(value.Model)
	if err != nil {
		return err
	}
	_, err = r.database.ExecContext(ctx, `INSERT INTO classification_models(account_id,model_version,sample_digest,sample_count,category_counts,model_json) VALUES(?,?,?,?,?,?) ON DUPLICATE KEY UPDATE model_version=VALUES(model_version),sample_digest=VALUES(sample_digest),sample_count=VALUES(sample_count),category_counts=VALUES(category_counts),model_json=VALUES(model_json),created_at=CURRENT_TIMESTAMP(6)`, accountID, value.ModelVersion, value.SampleDigest, value.SampleCount, string(counts), string(model))
	return err
}

func (r *MailboxRepository) SaveSuggestion(ctx context.Context, accountID string, input domain.ClassificationInput, value domain.ClassificationSuggestion) (domain.ClassificationSuggestion, error) {
	if value.ID == "" {
		value.ID = uuid.NewString()
	}
	evidence, _ := json.Marshal(map[string]any{"confidence": value.Confidence, "margin": value.Margin})
	err := r.witness.Write(ctx, "classification-suggestion|"+accountID+"|"+value.ID, func(tx *sql.Tx) error {
		var current int64
		err := tx.QueryRowContext(ctx, "SELECT version_no FROM mailbox_entries WHERE account_id=? AND entry_id=? FOR UPDATE", accountID, input.EntryID).Scan(&current)
		if errors.Is(err, sql.ErrNoRows) {
			return domain.ErrNotFound
		}
		if err != nil {
			return err
		}
		if current != input.Version {
			return &domain.VersionConflictError{Current: current}
		}
		if _, err = tx.ExecContext(ctx, "UPDATE classification_suggestions SET status_value='WITHDRAWN',decided_at=CURRENT_TIMESTAMP(6) WHERE account_id=? AND entry_id=? AND status_value='PENDING'", accountID, input.EntryID); err != nil {
			return err
		}
		_, err = tx.ExecContext(ctx, `INSERT INTO classification_suggestions(suggestion_id,account_id,entry_id,category_id,source_kind,status_value,confidence,margin_value,reason_text,evidence_json,rule_id,rule_version,model_version,entry_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)`, value.ID, accountID, input.EntryID, value.CategoryID, value.Source, value.Status, value.Confidence, value.Margin, value.Reason, string(evidence), value.RuleID, value.RuleVersion, value.ModelVersion, input.Version)
		return err
	})
	if err != nil {
		return domain.ClassificationSuggestion{}, err
	}
	return r.suggestion(ctx, accountID, input.EntryID, value.ID)
}

func (r *MailboxRepository) ApplySuggestion(ctx context.Context, accountID, entryID, suggestionID string, expected int64, source string, confirmed bool) (domain.ClassificationSuggestion, error) {
	actionID := uuid.NewString()
	err := r.witness.Write(ctx, fmt.Sprintf("classification-apply|%s|%s|%d", accountID, suggestionID, expected), func(tx *sql.Tx) error {
		var category sql.NullString
		var suggestionSource, status string
		err := tx.QueryRowContext(ctx, "SELECT category_id,source_kind,status_value FROM classification_suggestions WHERE account_id=? AND entry_id=? AND suggestion_id=? FOR UPDATE", accountID, entryID, suggestionID).Scan(&category, &suggestionSource, &status)
		if errors.Is(err, sql.ErrNoRows) || !category.Valid {
			return domain.ErrNotFound
		}
		if err != nil {
			return err
		}
		if status != "PENDING" {
			return invalid("SUGGESTION_ALREADY_DECIDED")
		}
		if (source == "RULE_AUTO" && suggestionSource != "RULE") ||
			(source == "ALGORITHM_AUTO" && suggestionSource != "ALGORITHM") ||
			(source == "MANUAL_LOCKED" && suggestionSource != "RULE" && suggestionSource != "ALGORITHM") {
			return invalid("SUGGESTION_SOURCE_MISMATCH")
		}
		var current int64
		var priorCategory, priorSource sql.NullString
		err = tx.QueryRowContext(ctx, "SELECT version_no,category_id,category_source FROM mailbox_entries WHERE account_id=? AND entry_id=? FOR UPDATE", accountID, entryID).Scan(&current, &priorCategory, &priorSource)
		if err != nil {
			return err
		}
		if current != expected {
			return &domain.VersionConflictError{Current: current}
		}
		if priorSource.Valid && priorSource.String == "MANUAL_LOCKED" {
			return &domain.VersionConflictError{Current: current}
		}
		if _, err = tx.ExecContext(ctx, "UPDATE mailbox_entries SET category_id=?,category_source=?,category_action_id=?,classification_checked_at=CURRENT_TIMESTAMP(6),version_no=version_no+1 WHERE account_id=? AND entry_id=?", category.String, source, actionID, accountID, entryID); err != nil {
			return err
		}
		decision := "AUTO_APPLIED"
		if confirmed {
			decision = "ACCEPTED"
		}
		if _, err = tx.ExecContext(ctx, "UPDATE classification_suggestions SET status_value=?,decided_at=CURRENT_TIMESTAMP(6) WHERE suggestion_id=?", decision, suggestionID); err != nil {
			return err
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO classification_actions(action_id,account_id,entry_id,source_kind,suggestion_id,prior_category_id,prior_source,applied_category_id,entry_version_before,entry_version_after) VALUES(?,?,?,?,?,?,?,?,?,?)`, actionID, accountID, entryID, source, suggestionID, nullable(priorCategory), nullable(priorSource), category.String, current, current+1); err != nil {
			return err
		}
		if confirmed {
			var fromAddress, subject string
			if err = tx.QueryRowContext(ctx, `SELECT c.from_address,c.subject FROM mailbox_entries e JOIN message_contents c ON c.content_id=e.content_id WHERE e.account_id=? AND e.entry_id=?`, accountID, entryID).Scan(&fromAddress, &subject); err != nil {
				return err
			}
			features, _ := json.Marshal(domain.ClassificationFeatures(fromAddress, subject))
			if _, err = tx.ExecContext(ctx, `INSERT INTO classification_feedback(feedback_id,account_id,entry_id,category_id,decision,features_json,suggestion_id) VALUES(?,?,?,?,'CONFIRMED',?,?)`, uuid.NewString(), accountID, entryID, category.String, string(features), suggestionID); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		return domain.ClassificationSuggestion{}, err
	}
	value, err := r.suggestion(ctx, accountID, entryID, suggestionID)
	value.ActionID = &actionID
	return value, err
}

func (r *MailboxRepository) RejectSuggestion(ctx context.Context, accountID, entryID, suggestionID string) (domain.ClassificationSuggestion, error) {
	err := r.witness.Write(ctx, "classification-reject|"+accountID+"|"+suggestionID, func(tx *sql.Tx) error {
		var category sql.NullString
		var status string
		if err := tx.QueryRowContext(ctx, "SELECT category_id,status_value FROM classification_suggestions WHERE account_id=? AND entry_id=? AND suggestion_id=? FOR UPDATE", accountID, entryID, suggestionID).Scan(&category, &status); errors.Is(err, sql.ErrNoRows) {
			return domain.ErrNotFound
		} else if err != nil {
			return err
		}
		if status != "PENDING" {
			return invalid("SUGGESTION_ALREADY_DECIDED")
		}
		var fromAddress, subject string
		if err := tx.QueryRowContext(ctx, `SELECT c.from_address,c.subject FROM mailbox_entries e JOIN message_contents c ON c.content_id=e.content_id WHERE e.account_id=? AND e.entry_id=?`, accountID, entryID).Scan(&fromAddress, &subject); err != nil {
			return err
		}
		features, _ := json.Marshal(domain.ClassificationFeatures(fromAddress, subject))
		if _, err := tx.ExecContext(ctx, "UPDATE classification_suggestions SET status_value='REJECTED',decided_at=CURRENT_TIMESTAMP(6) WHERE suggestion_id=?", suggestionID); err != nil {
			return err
		}
		_, err := tx.ExecContext(ctx, `INSERT INTO classification_feedback(feedback_id,account_id,entry_id,category_id,decision,features_json,suggestion_id) VALUES(?,?,?,?,'REJECTED',?,?)`, uuid.NewString(), accountID, entryID, nullable(category), string(features), suggestionID)
		return err
	})
	if err != nil {
		return domain.ClassificationSuggestion{}, err
	}
	return r.suggestion(ctx, accountID, entryID, suggestionID)
}

func (r *MailboxRepository) UndoClassification(ctx context.Context, accountID, entryID, actionID string, expected int64) (domain.MessageDetail, error) {
	err := r.witness.Write(ctx, fmt.Sprintf("classification-undo|%s|%s|%d", accountID, actionID, expected), func(tx *sql.Tx) error {
		var source string
		var priorCategory, priorSource sql.NullString
		var undone sql.NullTime
		err := tx.QueryRowContext(ctx, "SELECT source_kind,prior_category_id,prior_source,undone_at FROM classification_actions WHERE account_id=? AND entry_id=? AND action_id=? FOR UPDATE", accountID, entryID, actionID).Scan(&source, &priorCategory, &priorSource, &undone)
		if errors.Is(err, sql.ErrNoRows) {
			return domain.ErrNotFound
		}
		if err != nil {
			return err
		}
		if source != "RULE_AUTO" && source != "ALGORITHM_AUTO" {
			return invalid("ACTION_NOT_UNDOABLE")
		}
		if undone.Valid {
			return invalid("ACTION_ALREADY_UNDONE")
		}
		var current int64
		var currentAction sql.NullString
		if err = tx.QueryRowContext(ctx, "SELECT version_no,category_action_id FROM mailbox_entries WHERE account_id=? AND entry_id=? FOR UPDATE", accountID, entryID).Scan(&current, &currentAction); err != nil {
			return err
		}
		if current != expected {
			return &domain.VersionConflictError{Current: current}
		}
		if !currentAction.Valid || currentAction.String != actionID {
			return invalid("ACTION_SUPERSEDED")
		}
		if _, err = tx.ExecContext(ctx, "UPDATE mailbox_entries SET category_id=?,category_source=?,category_action_id=NULL,classification_checked_at=CURRENT_TIMESTAMP(6),version_no=version_no+1 WHERE account_id=? AND entry_id=?", nullable(priorCategory), nullable(priorSource), accountID, entryID); err != nil {
			return err
		}
		_, err = tx.ExecContext(ctx, "UPDATE classification_actions SET undone_at=CURRENT_TIMESTAMP(6) WHERE action_id=?", actionID)
		return err
	})
	if err != nil {
		return domain.MessageDetail{}, err
	}
	return r.Message(ctx, accountID, entryID)
}

func (r *MailboxRepository) PendingClassification(ctx context.Context, limit int) ([]domain.ClassificationInput, error) {
	rows, err := r.database.QueryContext(ctx, `SELECT e.entry_id,e.account_id,e.category_id,e.category_source,e.category_action_id,e.version_no,e.folder,e.is_read,c.from_address,c.subject FROM mailbox_entries e JOIN message_contents c ON c.content_id=e.content_id WHERE e.folder='INBOX' AND e.category_source IS NULL AND e.classification_checked_at IS NULL ORDER BY e.created_at,e.entry_id LIMIT ?`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []domain.ClassificationInput{}
	for rows.Next() {
		value, err := scanClassificationInput(rows)
		if err != nil {
			return nil, err
		}
		result = append(result, value)
	}
	return result, rows.Err()
}

func (r *MailboxRepository) MarkClassificationChecked(ctx context.Context, accountID, entryID string) error {
	_, err := r.database.ExecContext(ctx, "UPDATE mailbox_entries SET classification_checked_at=CURRENT_TIMESTAMP(6) WHERE account_id=? AND entry_id=? AND category_source IS NULL", accountID, entryID)
	return err
}

func (r *MailboxRepository) suggestion(ctx context.Context, accountID, entryID, id string) (domain.ClassificationSuggestion, error) {
	value, err := scanSuggestion(r.database.QueryRowContext(ctx, `SELECT suggestion_id,entry_id,category_id,source_kind,status_value,confidence,margin_value,reason_text,rule_id,rule_version,model_version,entry_version,created_at FROM classification_suggestions WHERE account_id=? AND entry_id=? AND suggestion_id=?`, accountID, entryID, id))
	if errors.Is(err, sql.ErrNoRows) {
		return value, domain.ErrNotFound
	}
	return value, err
}

func scanRule(row rowScanner) (domain.ClassificationRule, error) {
	var value domain.ClassificationRule
	err := row.Scan(&value.ID, &value.CategoryID, &value.Type, &value.Pattern, &value.Priority, &value.AutoApply, &value.Enabled, &value.Version, &value.CreatedAt, &value.UpdatedAt)
	return value, err
}

func scanClassificationInput(row rowScanner) (domain.ClassificationInput, error) {
	var value domain.ClassificationInput
	var category, source, action sql.NullString
	err := row.Scan(&value.EntryID, &value.AccountID, &category, &source, &action, &value.Version, &value.Folder, &value.Read, &value.FromAddress, &value.Subject)
	if category.Valid {
		value.CategoryID = &category.String
	}
	if source.Valid {
		value.CategorySource = &source.String
	}
	if action.Valid {
		value.CategoryAction = &action.String
	}
	return value, err
}

func scanSuggestion(row rowScanner) (domain.ClassificationSuggestion, error) {
	var value domain.ClassificationSuggestion
	var category, ruleID, model sql.NullString
	var ruleVersion sql.NullInt64
	err := row.Scan(&value.ID, &value.EntryID, &category, &value.Source, &value.Status, &value.Confidence, &value.Margin, &value.Reason, &ruleID, &ruleVersion, &model, &value.EntryVersion, &value.CreatedAt)
	if category.Valid {
		value.CategoryID = &category.String
	}
	if ruleID.Valid {
		value.RuleID = &ruleID.String
	}
	if ruleVersion.Valid {
		value.RuleVersion = &ruleVersion.Int64
	}
	if model.Valid {
		value.ModelVersion = &model.String
	}
	return value, err
}

func ownedCategory(ctx context.Context, tx *sql.Tx, accountID, categoryID string) error {
	var one int
	err := tx.QueryRowContext(ctx, "SELECT 1 FROM categories WHERE account_id=? AND category_id=?", accountID, categoryID).Scan(&one)
	if errors.Is(err, sql.ErrNoRows) {
		return domain.ErrNotFound
	}
	return err
}

var _ domain.ClassificationRepository = (*MailboxRepository)(nil)
