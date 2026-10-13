package dev.guihong.mailbox.domain;

import dev.guihong.mailbox.domain.MailboxModels.*;
import java.util.List;

public interface MailboxRepository {
    record StoredAttachment(String id,String objectId,String fileName,String mediaType,String sha256,long size) {}
    record ImportedMessage(String contentId,String rawObjectId,String rawSha256,long rawSize,ParsedMessage parsed,List<StoredAttachment> attachments) {}
    record Member(String accountId,Folder folder,boolean read) {}
    record DraftInput(String subject,String textBody,String htmlBody,List<String> to,List<String> cc,List<String> bcc,
                      DraftMode mode,String sourceContentId) {}
    record MessageChange(Long expectedVersion,Boolean read,Folder folder,boolean folderSet,String categoryId,boolean categorySet) {}

    void importMessage(ImportedMessage message,List<Member> members);
    List<FolderCount> folderCounts(String accountId);
    Page<MessageSummary> list(String accountId,Folder folder,String categoryId,String query,int size,String cursor);
    MessageDetail message(String accountId,String entryId);
    MessageDetail change(String accountId,String entryId,MessageChange change);
    Draft createDraft(String accountId,DraftInput input);
    Draft draft(String accountId,String draftId);
    Page<Draft> drafts(String accountId,int size,String cursor);
    Draft updateDraft(String accountId,String draftId,long expectedVersion,DraftInput input);
    List<Attachment> deleteDraft(String accountId,String draftId,long expectedVersion);
    Draft deriveDraft(String accountId,String entryId,DraftMode mode);
    Draft addDraftAttachment(String accountId,String draftId,long expectedVersion,StoredAttachment attachment);
    Attachment authorizedMessageAttachment(String accountId,String entryId,String attachmentId);
    Attachment authorizedDraftAttachment(String accountId,String draftId,String attachmentId);
    List<Category> categories(String accountId);
    Category createCategory(String accountId,String name);
    Category renameCategory(String accountId,String categoryId,long expectedVersion,String name);
    void deleteCategory(String accountId,String categoryId,long expectedVersion);
}

