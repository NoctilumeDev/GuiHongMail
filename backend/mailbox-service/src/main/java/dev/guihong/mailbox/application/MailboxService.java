package dev.guihong.mailbox.application;

import static dev.guihong.mailbox.application.MailboxExceptions.*;
import dev.guihong.mailbox.domain.MailboxModels.*;
import dev.guihong.mailbox.domain.MailboxRepository;
import dev.guihong.mailbox.domain.MailboxRepository.*;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.UUID;
import java.util.regex.Pattern;

public final class MailboxService {
    public record ImportMember(String accountId,Folder folder,boolean read) {}
    private record Reference(String objectId,String kind,String referenceId) {}
    private static final Pattern ADDRESS=Pattern.compile("[a-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[a-z0-9.-]{1,189}");
    private static final Pattern MEDIA=Pattern.compile("[a-z0-9!#$&^_.+-]{1,64}/[a-z0-9!#$&^_.+-]{1,64}");
    private static final int MAX_MIME=5*1024*1024,MAX_ATTACHMENTS=20,MAX_ATTACHMENT_BYTES=4*1024*1024;
    private final MailboxRepository repository;
    private final MimeProjectionParser mime;
    private final HtmlContentSanitizer html;
    private final MailboxObjectStore objects;

    public MailboxService(MailboxRepository repository,MimeProjectionParser mime,HtmlContentSanitizer html,MailboxObjectStore objects){
        this.repository=repository;this.mime=mime;this.html=html;this.objects=objects;
    }

    public String importMime(byte[] raw,List<ImportMember> requestedMembers){
        if(raw==null || raw.length==0 || raw.length>MAX_MIME)throw new InvalidInput("MIME_SIZE_EXCEEDED");
        if(requestedMembers==null || requestedMembers.isEmpty() || requestedMembers.size()>10)throw new InvalidInput("INVALID_MEMBERS");
        var members=new ArrayList<Member>();var identities=new LinkedHashSet<String>();
        for(var member:requestedMembers){
            uuid(member.accountId());if(member.folder()==null || !identities.add(member.accountId()))throw new InvalidInput("INVALID_MEMBERS");
            members.add(new Member(member.accountId(),member.folder(),member.read()));
        }
        ParsedMessage parsed=mime.parse(raw);
        if(parsed.attachments().size()>MAX_ATTACHMENTS)throw new InvalidInput("MIME_PART_LIMIT");
        long attachmentBytes=parsed.attachments().stream().mapToLong(a->a.bytes().length).sum();
        if(attachmentBytes>MAX_ATTACHMENT_BYTES)throw new InvalidInput("ATTACHMENT_TOTAL_EXCEEDED");
        String contentId=UUID.randomUUID().toString();var references=new ArrayList<Reference>();
        try{
            var rawObject=objects.store(raw,"message:"+contentId,"MESSAGE_RAW",contentId);
            references.add(new Reference(rawObject.id(),"MESSAGE_RAW",contentId));
            var attachments=new ArrayList<StoredAttachment>();int ordinal=0;
            for(var part:parsed.attachments()){
                String attachmentId=UUID.randomUUID().toString();
                var stored=objects.store(part.bytes(),"message-attachment:"+attachmentId,"MESSAGE_ATTACHMENT",attachmentId);
                references.add(new Reference(stored.id(),"MESSAGE_ATTACHMENT",attachmentId));
                attachments.add(new StoredAttachment(attachmentId,stored.id(),part.fileName(),part.mediaType(),stored.sha256(),stored.size()));
                ordinal++;
            }
            repository.importMessage(new ImportedMessage(contentId,rawObject.id(),rawObject.sha256(),rawObject.size(),parsed,attachments),members);
            return contentId;
        }catch(CommitOutcomeUnknown unknown){throw unknown;}
        catch(RuntimeException failure){
            for(int index=references.size()-1;index>=0;index--){var ref=references.get(index);try{objects.release(ref.objectId(),ref.kind(),ref.referenceId());}catch(RuntimeException suppressed){failure.addSuppressed(suppressed);}}
            throw failure;
        }
    }

    public List<FolderCount> folderCounts(String accountId){uuid(accountId);return repository.folderCounts(accountId);}
    public Page<MessageSummary> list(String accountId,Folder folder,String categoryId,String query,int size,String cursor){
        uuid(accountId);if((folder==null)==(categoryId==null))throw new InvalidInput("FOLDER_OR_CATEGORY_REQUIRED");
        if(categoryId!=null)uuid(categoryId);if(size<1 || size>100)throw new InvalidInput("INVALID_PAGE_SIZE");
        if(query!=null && query.length()>200)throw new InvalidInput("SEARCH_TOO_LONG");
        return repository.list(accountId,folder,categoryId,query==null?null:query.strip(),size,cursor);
    }
    public MessageDetail message(String accountId,String entryId){uuid(accountId);uuid(entryId);return repository.message(accountId,entryId);}
    public MessageDetail change(String accountId,String entryId,MessageChange change){uuid(accountId);uuid(entryId);if(change==null)throw new InvalidInput("INVALID_CHANGE");if(change.categorySet() && change.categoryId()!=null)uuid(change.categoryId());return repository.change(accountId,entryId,change);}

    public Draft createDraft(String accountId,DraftInput input){uuid(accountId);return repository.createDraft(accountId,validateDraft(input));}
    public Draft draft(String accountId,String draftId){uuid(accountId);uuid(draftId);return repository.draft(accountId,draftId);}
    public Page<Draft> drafts(String accountId,int size,String cursor){uuid(accountId);if(size<1 || size>100)throw new InvalidInput("INVALID_PAGE_SIZE");return repository.drafts(accountId,size,cursor);}
    public Draft updateDraft(String accountId,String draftId,long expectedVersion,DraftInput input){uuid(accountId);uuid(draftId);if(expectedVersion<1)throw new InvalidInput("INVALID_VERSION");return repository.updateDraft(accountId,draftId,expectedVersion,validateDraft(input));}
    public void deleteDraft(String accountId,String draftId,long expectedVersion){
        uuid(accountId);uuid(draftId);if(expectedVersion<1)throw new InvalidInput("INVALID_VERSION");
        List<Attachment> released=repository.deleteDraft(accountId,draftId,expectedVersion);
        for(var attachment:released)objects.release(attachment.objectId(),"DRAFT_ATTACHMENT",attachment.id());
    }
    public Draft deriveDraft(String accountId,String entryId,DraftMode mode){uuid(accountId);uuid(entryId);if(mode==null || mode==DraftMode.COMPOSE)throw new InvalidInput("INVALID_DRAFT_MODE");return repository.deriveDraft(accountId,entryId,mode);}

    public Draft attach(String accountId,String draftId,long expectedVersion,String fileName,String mediaType,byte[] bytes){
        uuid(accountId);uuid(draftId);if(expectedVersion<1)throw new InvalidInput("INVALID_VERSION");
        String safeName=fileName(fileName);String safeMedia=mediaType==null?"application/octet-stream":mediaType.toLowerCase(Locale.ROOT);
        if(!MEDIA.matcher(safeMedia).matches())safeMedia="application/octet-stream";
        if(bytes==null || bytes.length>MAX_ATTACHMENT_BYTES)throw new InvalidInput("ATTACHMENT_SIZE_EXCEEDED");
        String attachmentId=UUID.randomUUID().toString();MailboxObjectStore.Stored stored=objects.store(bytes,"draft-attachment:"+attachmentId,"DRAFT_ATTACHMENT",attachmentId);
        try{return repository.addDraftAttachment(accountId,draftId,expectedVersion,new StoredAttachment(attachmentId,stored.id(),safeName,safeMedia,stored.sha256(),stored.size()));}
        catch(CommitOutcomeUnknown unknown){throw unknown;}
        catch(RuntimeException failure){try{objects.release(stored.id(),"DRAFT_ATTACHMENT",attachmentId);}catch(RuntimeException suppressed){failure.addSuppressed(suppressed);}throw failure;}
    }
    public byte[] readMessageAttachment(String accountId,String entryId,String attachmentId){return objects.read(repository.authorizedMessageAttachment(uuid(accountId),uuid(entryId),uuid(attachmentId)).objectId());}
    public byte[] readDraftAttachment(String accountId,String draftId,String attachmentId){return objects.read(repository.authorizedDraftAttachment(uuid(accountId),uuid(draftId),uuid(attachmentId)).objectId());}
    public Attachment messageAttachment(String accountId,String entryId,String attachmentId){return repository.authorizedMessageAttachment(uuid(accountId),uuid(entryId),uuid(attachmentId));}
    public Attachment draftAttachment(String accountId,String draftId,String attachmentId){return repository.authorizedDraftAttachment(uuid(accountId),uuid(draftId),uuid(attachmentId));}

    public List<Category> categories(String accountId){return repository.categories(uuid(accountId));}
    public Category createCategory(String accountId,String name){return repository.createCategory(uuid(accountId),categoryName(name));}
    public Category renameCategory(String accountId,String categoryId,long expectedVersion,String name){return repository.renameCategory(uuid(accountId),uuid(categoryId),expectedVersion,categoryName(name));}
    public void deleteCategory(String accountId,String categoryId,long expectedVersion){repository.deleteCategory(uuid(accountId),uuid(categoryId),expectedVersion);}

    private DraftInput validateDraft(DraftInput input){
        if(input==null)throw new InvalidInput("INVALID_DRAFT");
        String subject=input.subject()==null?"":input.subject().strip();
        if(subject.getBytes(StandardCharsets.UTF_8).length>998)throw new InvalidInput("SUBJECT_TOO_LONG");
        String text=input.textBody()==null?"":input.textBody();String rawHtml=input.htmlBody()==null?"":input.htmlBody();
        if(text.getBytes(StandardCharsets.UTF_8).length+rawHtml.getBytes(StandardCharsets.UTF_8).length>MAX_MIME)throw new InvalidInput("DRAFT_SIZE_EXCEEDED");
        List<String> to=addresses(input.to()),cc=addresses(input.cc()),bcc=addresses(input.bcc());
        if(to.size()+cc.size()+bcc.size()>10)throw new InvalidInput("RECIPIENT_LIMIT");
        String source=input.sourceContentId();if(source!=null)uuid(source);
        return new DraftInput(subject,text,html.sanitize(rawHtml),to,cc,bcc,input.mode()==null?DraftMode.COMPOSE:input.mode(),source);
    }
    private List<String> addresses(List<String> input){
        if(input==null)return List.of();var unique=new LinkedHashSet<String>();
        for(String candidate:input){if(candidate==null)throw new InvalidInput("INVALID_ADDRESS");String normalized=candidate.strip().toLowerCase(Locale.ROOT);if(!ADDRESS.matcher(normalized).matches())throw new InvalidInput("INVALID_ADDRESS");unique.add(normalized);}
        return List.copyOf(unique);
    }
    private String categoryName(String name){if(name==null)throw new InvalidInput("INVALID_CATEGORY");String value=name.strip();if(value.isEmpty() || value.length()>40)throw new InvalidInput("INVALID_CATEGORY");return value;}
    private String fileName(String name){
        if(name==null || name.contains("/") || name.contains("\\"))throw new InvalidInput("INVALID_FILE_NAME");String value=name.strip();
        if(value.isEmpty() || value.length()>255 || value.equals(".") || value.equals("..") || value.indexOf('\0')>=0 || value.contains("\r") || value.contains("\n"))throw new InvalidInput("INVALID_FILE_NAME");return value;
    }
    private String uuid(String value){try{return UUID.fromString(value).toString();}catch(RuntimeException invalid){throw new InvalidInput("INVALID_ID");}}
}

