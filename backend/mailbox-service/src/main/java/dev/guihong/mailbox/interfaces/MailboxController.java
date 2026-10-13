package dev.guihong.mailbox.interfaces;

import dev.guihong.mailbox.application.MailboxService;
import dev.guihong.mailbox.domain.MailboxModels.*;
import dev.guihong.mailbox.domain.MailboxRepository.DraftInput;
import dev.guihong.mailbox.domain.MailboxRepository.MessageChange;
import dev.guihong.mailbox.domain.Principal;
import jakarta.servlet.http.HttpServletRequest;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.List;
import java.util.Map;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

@RestController
public final class MailboxController {
    public record DraftBody(Long version,String subject,String textBody,String htmlBody,List<String> to,List<String> cc,List<String> bcc,String mode,String sourceContentId) {}
    public record ChangeBody(Long version,Boolean read,String folder,String categoryId,Boolean clearCategory) {}
    public record CategoryBody(Long version,String name) {}
    public record ImportMember(String accountId,String folder,Boolean read) {}
    public record ImportBody(String base64,List<ImportMember> members) {}
    private final MailboxService mailbox;
    public MailboxController(MailboxService mailbox){this.mailbox=mailbox;}

    @GetMapping("/api/mailbox/folders") public List<FolderCount> folders(HttpServletRequest request){return mailbox.folderCounts(principal(request).accountId());}
    @GetMapping("/api/mailbox/messages") public Page<MessageSummary> messages(@RequestParam(required=false) String folder,@RequestParam(name="category_id",required=false) String categoryId,@RequestParam(name="q",required=false) String query,@RequestParam(defaultValue="30") int size,@RequestParam(required=false) String cursor,HttpServletRequest request){
        return mailbox.list(principal(request).accountId(),folder==null?null:folder(folder),categoryId,query,size,cursor);
    }
    @GetMapping("/api/mailbox/messages/{entryId}") public MessageDetail message(@PathVariable String entryId,HttpServletRequest request){return mailbox.message(principal(request).accountId(),entryId);}
    @PatchMapping("/api/mailbox/messages/{entryId}") public MessageDetail change(@PathVariable String entryId,@RequestBody ChangeBody body,HttpServletRequest request){
        Folder target=body.folder()==null?null:folder(body.folder());boolean category=body.categoryId()!=null || Boolean.TRUE.equals(body.clearCategory());
        return mailbox.change(principal(request).accountId(),entryId,new MessageChange(body.version(),body.read(),target,target!=null,Boolean.TRUE.equals(body.clearCategory())?null:body.categoryId(),category));
    }

    @GetMapping("/api/mailbox/drafts") public Page<Draft> drafts(@RequestParam(defaultValue="30") int size,@RequestParam(required=false) String cursor,HttpServletRequest request){return mailbox.drafts(principal(request).accountId(),size,cursor);}
    @PostMapping("/api/mailbox/drafts") public ResponseEntity<Draft> createDraft(@RequestBody DraftBody body,HttpServletRequest request){return ResponseEntity.status(201).body(mailbox.createDraft(principal(request).accountId(),draft(body)));}
    @GetMapping("/api/mailbox/drafts/{draftId}") public Draft draft(@PathVariable String draftId,HttpServletRequest request){return mailbox.draft(principal(request).accountId(),draftId);}
    @PutMapping("/api/mailbox/drafts/{draftId}") public Draft updateDraft(@PathVariable String draftId,@RequestBody DraftBody body,HttpServletRequest request){return mailbox.updateDraft(principal(request).accountId(),draftId,body.version()==null?0:body.version(),draft(body));}
    @DeleteMapping("/api/mailbox/drafts/{draftId}") public ResponseEntity<?> deleteDraft(@PathVariable String draftId,@RequestParam long version,HttpServletRequest request){mailbox.deleteDraft(principal(request).accountId(),draftId,version);return ResponseEntity.noContent().build();}
    @PostMapping("/api/mailbox/messages/{entryId}/drafts") public ResponseEntity<Draft> deriveDraft(@PathVariable String entryId,@RequestParam String mode,HttpServletRequest request){return ResponseEntity.status(201).body(mailbox.deriveDraft(principal(request).accountId(),entryId,mode(mode)));}
    @PostMapping(path="/api/mailbox/drafts/{draftId}/attachments",consumes=MediaType.MULTIPART_FORM_DATA_VALUE) public ResponseEntity<Draft> attach(@PathVariable String draftId,@RequestParam long version,@RequestPart("file") MultipartFile file,HttpServletRequest request) throws Exception {
        return ResponseEntity.status(201).body(mailbox.attach(principal(request).accountId(),draftId,version,file.getOriginalFilename(),file.getContentType(),file.getBytes()));
    }
    @GetMapping("/api/mailbox/messages/{entryId}/attachments/{attachmentId}") public ResponseEntity<byte[]> messageAttachment(@PathVariable String entryId,@PathVariable String attachmentId,HttpServletRequest request){
        String account=principal(request).accountId();Attachment meta=mailbox.messageAttachment(account,entryId,attachmentId);return download(meta,mailbox.readMessageAttachment(account,entryId,attachmentId));
    }
    @GetMapping("/api/mailbox/drafts/{draftId}/attachments/{attachmentId}") public ResponseEntity<byte[]> draftAttachment(@PathVariable String draftId,@PathVariable String attachmentId,HttpServletRequest request){
        String account=principal(request).accountId();Attachment meta=mailbox.draftAttachment(account,draftId,attachmentId);return download(meta,mailbox.readDraftAttachment(account,draftId,attachmentId));
    }

    @GetMapping("/api/mailbox/categories") public List<Category> categories(HttpServletRequest request){return mailbox.categories(principal(request).accountId());}
    @PostMapping("/api/mailbox/categories") public ResponseEntity<Category> createCategory(@RequestBody CategoryBody body,HttpServletRequest request){return ResponseEntity.status(201).body(mailbox.createCategory(principal(request).accountId(),body.name()));}
    @PutMapping("/api/mailbox/categories/{categoryId}") public Category renameCategory(@PathVariable String categoryId,@RequestBody CategoryBody body,HttpServletRequest request){return mailbox.renameCategory(principal(request).accountId(),categoryId,body.version()==null?0:body.version(),body.name());}
    @DeleteMapping("/api/mailbox/categories/{categoryId}") public ResponseEntity<?> deleteCategory(@PathVariable String categoryId,@RequestParam long version,HttpServletRequest request){mailbox.deleteCategory(principal(request).accountId(),categoryId,version);return ResponseEntity.noContent().build();}

    @PostMapping("/internal/mailbox/fixtures") public Map<String,Object> importFixture(@RequestBody ImportBody body){
        if(body.base64()==null || body.base64().length()>7*1024*1024)throw new dev.guihong.mailbox.application.MailboxExceptions.InvalidInput("MIME_SIZE_EXCEEDED");
        byte[] raw;try{raw=Base64.getDecoder().decode(body.base64());}catch(IllegalArgumentException invalid){throw new dev.guihong.mailbox.application.MailboxExceptions.InvalidInput("MIME_BASE64_INVALID");}
        List<MailboxService.ImportMember> members=body.members()==null?List.of():body.members().stream().map(m->new MailboxService.ImportMember(m.accountId(),folder(m.folder()),Boolean.TRUE.equals(m.read()))).toList();
        return Map.of("content_id",mailbox.importMime(raw,members));
    }

    private Principal principal(HttpServletRequest request){return (Principal)request.getAttribute("principal");}
    private DraftInput draft(DraftBody body){return new DraftInput(body.subject(),body.textBody(),body.htmlBody(),body.to(),body.cc(),body.bcc(),body.mode()==null?DraftMode.COMPOSE:mode(body.mode()),body.sourceContentId());}
    private Folder folder(String value){try{return Folder.valueOf(value.toUpperCase(java.util.Locale.ROOT));}catch(RuntimeException invalid){throw new dev.guihong.mailbox.application.MailboxExceptions.InvalidInput("INVALID_FOLDER");}}
    private DraftMode mode(String value){try{return DraftMode.valueOf(value.toUpperCase(java.util.Locale.ROOT));}catch(RuntimeException invalid){throw new dev.guihong.mailbox.application.MailboxExceptions.InvalidInput("INVALID_DRAFT_MODE");}}
    private ResponseEntity<byte[]> download(Attachment meta,byte[] bytes){
        MediaType type;try{type=MediaType.parseMediaType(meta.mediaType());}catch(RuntimeException invalid){type=MediaType.APPLICATION_OCTET_STREAM;}
        return ResponseEntity.ok().header(HttpHeaders.CONTENT_DISPOSITION,ContentDisposition.attachment().filename(meta.fileName(),StandardCharsets.UTF_8).build().toString()).header("X-Content-Type-Options","nosniff").contentLength(bytes.length).contentType(type).body(bytes);
    }
}

