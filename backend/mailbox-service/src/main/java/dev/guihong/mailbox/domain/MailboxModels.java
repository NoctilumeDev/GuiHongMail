package dev.guihong.mailbox.domain;

import java.time.Instant;
import java.util.List;

public final class MailboxModels {
    private MailboxModels() {}

    public enum Folder { INBOX, SENT, ARCHIVE, SPAM, TRASH }
    public enum DraftMode { COMPOSE, REPLY, REPLY_ALL, FORWARD }
    public enum RecipientKind { TO, CC, BCC }

    public record Address(String address,String name) {}
    public record Recipient(RecipientKind kind,int ordinal,String address,String name) {}
    public record Attachment(String id,String objectId,String fileName,String mediaType,String sha256,long size) {}
    public record MessageSummary(String entryId,String contentId,Folder folder,boolean read,String categoryId,long version,
                                 String fromAddress,String fromName,String subject,String preview,Instant sentAt,Instant receivedAt,
                                 int attachmentCount) {}
    public record MessageDetail(MessageSummary summary,String textBody,String safeHtml,List<Recipient> recipients,
                                List<Attachment> attachments,String rawSha256,long rawSize) {}
    public record Page<T>(List<T> items,String nextCursor) {}
    public record FolderCount(Folder folder,long total,long unread) {}
    public record Category(String id,String name,long version,long total,long unread) {}
    public record Draft(String id,long version,String subject,String textBody,String htmlBody,List<String> to,List<String> cc,
                        List<String> bcc,DraftMode mode,String sourceContentId,List<Attachment> attachments,
                        Instant createdAt,Instant updatedAt) {}
    public record ParsedMessage(String messageId,Address from,String subject,String textBody,String safeHtml,Instant sentAt,
                                List<Recipient> recipients,List<ParsedAttachment> attachments) {}
    public record ParsedAttachment(String fileName,String mediaType,byte[] bytes,String sha256) {}
}

