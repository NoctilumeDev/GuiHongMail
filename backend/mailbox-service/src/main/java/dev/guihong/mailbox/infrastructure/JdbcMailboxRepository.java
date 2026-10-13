package dev.guihong.mailbox.infrastructure;

import static dev.guihong.mailbox.application.MailboxExceptions.*;
import dev.guihong.mailbox.domain.MailboxModels.*;
import dev.guihong.mailbox.domain.MailboxRepository;
import dev.guihong.platform.CommitUnknownException;
import dev.guihong.platform.FoundationController;
import dev.guihong.platform.WitnessGate;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Base64;
import java.util.EnumMap;
import java.util.List;
import java.util.Locale;
import java.util.UUID;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

@Repository
public final class JdbcMailboxRepository implements MailboxRepository {
    private static final String SUMMARY="""
        SELECT e.entry_id,e.content_id,e.folder,e.is_read,e.category_id,e.version_no,e.created_at,
               c.from_address,c.from_name,c.subject,c.text_body,c.sent_at,
               (SELECT COUNT(*) FROM message_attachments a WHERE a.content_id=e.content_id) attachment_count
          FROM mailbox_entries e JOIN message_contents c ON c.content_id=e.content_id
        """;
    private final JdbcTemplate jdbc;private final WitnessGate witness;private final FoundationController foundation;
    private final RowMapper<MessageSummary> summary=(r,n)->summary(r);
    public JdbcMailboxRepository(JdbcTemplate jdbc,WitnessGate witness,FoundationController foundation){this.jdbc=jdbc;this.witness=witness;this.foundation=foundation;}
    private void ready(){if(!foundation.writable())throw new IllegalStateException("SERVICE_UNAVAILABLE");}

    public void importMessage(ImportedMessage message,List<Member> members){
        ready();try{write("mailbox-import|"+message.contentId()+"|"+message.rawSha256(),c->{
            try(var q=c.prepareStatement("INSERT INTO message_contents(content_id,raw_object_id,raw_sha256,raw_size,message_id,from_address,from_name,subject,text_body,safe_html,sent_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)")){
                q.setString(1,message.contentId());q.setString(2,message.rawObjectId());q.setString(3,message.rawSha256());q.setLong(4,message.rawSize());q.setString(5,emptyToNull(message.parsed().messageId()));q.setString(6,message.parsed().from().address());q.setString(7,emptyToNull(message.parsed().from().name()));q.setString(8,message.parsed().subject());q.setString(9,message.parsed().textBody());q.setString(10,message.parsed().safeHtml());setInstant(q,11,message.parsed().sentAt());q.executeUpdate();
            }
            try(var q=c.prepareStatement("INSERT INTO message_recipients(content_id,recipient_kind,ordinal_no,address,display_name) VALUES(?,?,?,?,?)")){
                for(var recipient:message.parsed().recipients()){q.setString(1,message.contentId());q.setString(2,recipient.kind().name());q.setInt(3,recipient.ordinal());q.setString(4,recipient.address());q.setString(5,emptyToNull(recipient.name()));q.addBatch();}q.executeBatch();
            }
            try(var q=c.prepareStatement("INSERT INTO message_attachments(attachment_id,content_id,object_id,ordinal_no,file_name,media_type,sha256,byte_size) VALUES(?,?,?,?,?,?,?,?)")){
                int ordinal=0;for(var attachment:message.attachments()){q.setString(1,attachment.id());q.setString(2,message.contentId());q.setString(3,attachment.objectId());q.setInt(4,ordinal++);q.setString(5,attachment.fileName());q.setString(6,attachment.mediaType());q.setString(7,attachment.sha256());q.setLong(8,attachment.size());q.addBatch();}q.executeBatch();
            }
            try(var verify=c.prepareStatement("SELECT enabled FROM accounts WHERE account_id=?");var insert=c.prepareStatement("INSERT INTO mailbox_entries(entry_id,account_id,content_id,folder,is_read) VALUES(?,?,?,?,?)")){
                for(var member:members){verify.setString(1,member.accountId());try(var rows=verify.executeQuery()){if(!rows.next() || !rows.getBoolean(1))throw new InvalidInput("MEMBER_ACCOUNT_UNAVAILABLE");}
                    insert.setString(1,UUID.randomUUID().toString());insert.setString(2,member.accountId());insert.setString(3,message.contentId());insert.setString(4,member.folder().name());insert.setBoolean(5,member.read());insert.addBatch();}insert.executeBatch();
            }return null;
        });}catch(DataIntegrityViolationException duplicate){throw new InvalidInput("MESSAGE_ALREADY_IMPORTED");}
    }

    public List<FolderCount> folderCounts(String accountId){
        ready();var counts=new EnumMap<Folder,long[]>(Folder.class);for(var folder:Folder.values())counts.put(folder,new long[2]);
        jdbc.query("SELECT folder,COUNT(*) total,SUM(IF(is_read,0,1)) unread FROM mailbox_entries WHERE account_id=? GROUP BY folder",r->{counts.put(Folder.valueOf(r.getString(1)),new long[]{r.getLong(2),r.getLong(3)});},accountId);
        var result=new ArrayList<FolderCount>();for(var folder:Folder.values()){var values=counts.get(folder);result.add(new FolderCount(folder,values[0],values[1]));}return result;
    }

    public Page<MessageSummary> list(String accountId,Folder folder,String categoryId,String query,int size,String cursor){
        ready();var sql=new StringBuilder(SUMMARY).append(" WHERE e.account_id=?");var args=new ArrayList<Object>();args.add(accountId);
        if(categoryId!=null){sql.append(" AND e.category_id=?");args.add(categoryId);}else{sql.append(" AND e.folder=?");args.add(folder.name());}
        if(query!=null && !query.isBlank()){String pattern="%"+escapeLike(query)+"%";sql.append(" AND (c.from_address LIKE ? ESCAPE '\\\\' OR c.from_name LIKE ? ESCAPE '\\\\' OR c.subject LIKE ? ESCAPE '\\\\' OR c.text_body LIKE ? ESCAPE '\\\\')");for(int i=0;i<4;i++)args.add(pattern);}
        if(cursor!=null && !cursor.isBlank()){Cursor decoded=cursor(cursor);sql.append(" AND (e.created_at<? OR (e.created_at=? AND e.entry_id<?))");args.add(Timestamp.from(decoded.time));args.add(Timestamp.from(decoded.time));args.add(decoded.id);}
        sql.append(" ORDER BY e.created_at DESC,e.entry_id DESC LIMIT ?");args.add(size+1);
        List<MessageSummary> rows=jdbc.query(sql.toString(),summary,args.toArray());boolean more=rows.size()>size;if(more)rows=new ArrayList<>(rows.subList(0,size));
        String next=more?cursor(rows.get(rows.size()-1).receivedAt(),rows.get(rows.size()-1).entryId()):null;return new Page<>(List.copyOf(rows),next);
    }

    public MessageDetail message(String accountId,String entryId){
        ready();List<MessageSummary> rows=jdbc.query(SUMMARY+" WHERE e.account_id=? AND e.entry_id=?",summary,accountId,entryId);if(rows.isEmpty())throw new NotFound();
        MessageSummary item=rows.get(0);List<Recipient> recipients=jdbc.query("SELECT recipient_kind,ordinal_no,address,display_name FROM message_recipients WHERE content_id=? AND (?='SENT' OR recipient_kind<>'BCC') ORDER BY FIELD(recipient_kind,'TO','CC','BCC'),ordinal_no",(r,n)->new Recipient(RecipientKind.valueOf(r.getString(1)),r.getInt(2),r.getString(3),r.getString(4)),item.contentId(),item.folder().name());
        List<Attachment> attachments=jdbc.query("SELECT attachment_id,object_id,file_name,media_type,sha256,byte_size FROM message_attachments WHERE content_id=? ORDER BY ordinal_no",(r,n)->attachment(r),item.contentId());
        return jdbc.queryForObject("SELECT text_body,safe_html,raw_sha256,raw_size FROM message_contents WHERE content_id=?",(r,n)->new MessageDetail(item,r.getString(1),r.getString(2),recipients,attachments,r.getString(3),r.getLong(4)),item.contentId());
    }

    public MessageDetail change(String accountId,String entryId,MessageChange change){
        ready();write("mailbox-change|"+accountId+"|"+entryId+"|"+String.valueOf(change.expectedVersion()),c->{
            long version=lockedVersion(c,"mailbox_entries","entry_id",entryId,accountId);
            if(change.expectedVersion()!=null && change.expectedVersion()!=version)throw new VersionConflict(version);
            if(change.categorySet() && change.categoryId()!=null)assertCategory(c,accountId,change.categoryId());
            String sql="UPDATE mailbox_entries SET is_read=IF(?, ?, is_read),folder=IF(?, ?, folder),category_id=IF(?, ?, category_id),version_no=version_no+1 WHERE entry_id=? AND account_id=?";
            try(var q=c.prepareStatement(sql)){q.setBoolean(1,change.read()!=null);q.setBoolean(2,Boolean.TRUE.equals(change.read()));q.setBoolean(3,change.folderSet());q.setString(4,change.folder()==null?Folder.INBOX.name():change.folder().name());q.setBoolean(5,change.categorySet());q.setString(6,change.categoryId());q.setString(7,entryId);q.setString(8,accountId);q.executeUpdate();}return null;
        });return message(accountId,entryId);
    }

    public Draft createDraft(String accountId,DraftInput input){
        ready();String id=UUID.randomUUID().toString();write("draft-create|"+accountId+"|"+id,c->{
            try(var q=c.prepareStatement("INSERT INTO drafts(draft_id,account_id,subject,text_body,html_body,to_json,cc_json,bcc_json,mode,source_content_id) VALUES(?,?,?,?,?,?,?,?,?,?)")){
                q.setString(1,id);q.setString(2,accountId);draftValues(q,3,input);q.executeUpdate();}return null;
        });return draft(accountId,id);
    }

    public Draft draft(String accountId,String draftId){
        ready();List<Draft> rows=jdbc.query("SELECT * FROM drafts WHERE account_id=? AND draft_id=?",(r,n)->draft(r,attachmentsForDraft(draftId)),accountId,draftId);if(rows.isEmpty())throw new NotFound();return rows.get(0);
    }

    public Page<Draft> drafts(String accountId,int size,String cursor){
        ready();StringBuilder sql=new StringBuilder("SELECT * FROM drafts WHERE account_id=?");var args=new ArrayList<Object>();args.add(accountId);
        if(cursor!=null && !cursor.isBlank()){Cursor decoded=cursor(cursor);sql.append(" AND (updated_at<? OR (updated_at=? AND draft_id<?))");args.add(Timestamp.from(decoded.time));args.add(Timestamp.from(decoded.time));args.add(decoded.id);}
        sql.append(" ORDER BY updated_at DESC,draft_id DESC LIMIT ?");args.add(size+1);List<Draft> rows=jdbc.query(sql.toString(),(r,n)->draft(r,attachmentsForDraft(r.getString("draft_id"))),args.toArray());
        boolean more=rows.size()>size;if(more)rows=new ArrayList<>(rows.subList(0,size));String next=more?cursor(rows.get(rows.size()-1).updatedAt(),rows.get(rows.size()-1).id()):null;return new Page<>(List.copyOf(rows),next);
    }

    public Draft updateDraft(String accountId,String draftId,long expectedVersion,DraftInput input){
        ready();write("draft-update|"+accountId+"|"+draftId+"|"+expectedVersion,c->{long current=lockedVersion(c,"drafts","draft_id",draftId,accountId);if(current!=expectedVersion)throw new VersionConflict(current);
            try(var q=c.prepareStatement("UPDATE drafts SET subject=?,text_body=?,html_body=?,to_json=?,cc_json=?,bcc_json=?,mode=?,source_content_id=?,version_no=version_no+1 WHERE draft_id=? AND account_id=?")){draftValues(q,1,input);q.setString(9,draftId);q.setString(10,accountId);q.executeUpdate();}return null;});return draft(accountId,draftId);
    }

    public List<Attachment> deleteDraft(String accountId,String draftId,long expectedVersion){
        ready();return write("draft-delete|"+accountId+"|"+draftId+"|"+expectedVersion,c->{long current=lockedVersion(c,"drafts","draft_id",draftId,accountId);if(current!=expectedVersion)throw new VersionConflict(current);
            var attachments=attachments(c,"SELECT attachment_id,object_id,file_name,media_type,sha256,byte_size FROM draft_attachments WHERE draft_id=?",draftId);
            try(var q=c.prepareStatement("DELETE FROM drafts WHERE draft_id=? AND account_id=?")){q.setString(1,draftId);q.setString(2,accountId);q.executeUpdate();}return attachments;});
    }

    public Draft deriveDraft(String accountId,String entryId,DraftMode mode){
        MessageDetail source=message(accountId,entryId);String own=jdbc.queryForObject("SELECT address FROM accounts WHERE account_id=?",String.class,accountId);
        String subject=source.summary().subject();List<String> to=new ArrayList<>(),cc=new ArrayList<>();
        if(mode==DraftMode.REPLY || mode==DraftMode.REPLY_ALL)to.add(source.summary().fromAddress());
        if(mode==DraftMode.REPLY_ALL)for(var recipient:source.recipients())if(recipient.kind()!=RecipientKind.BCC && !recipient.address().equalsIgnoreCase(own) && !to.contains(recipient.address()) && !cc.contains(recipient.address())){if(recipient.kind()==RecipientKind.TO)to.add(recipient.address());else cc.add(recipient.address());}
        if(mode==DraftMode.FORWARD)subject=prefix(subject,"Fwd: ");else subject=prefix(subject,"Re: ");
        String text=mode==DraftMode.FORWARD?"\n\n--- Forwarded message ---\n"+source.textBody():"\n\n"+source.textBody();
        String safe=source.safeHtml().isBlank()?"":"<br><br><blockquote>"+source.safeHtml()+"</blockquote>";
        return createDraft(accountId,new DraftInput(subject,text,safe,to,cc,List.of(),mode,source.summary().contentId()));
    }

    public Draft addDraftAttachment(String accountId,String draftId,long expectedVersion,StoredAttachment attachment){
        ready();write("draft-attachment|"+accountId+"|"+draftId+"|"+attachment.id(),c->{long current=lockedVersion(c,"drafts","draft_id",draftId,accountId);if(current!=expectedVersion)throw new VersionConflict(current);
            try(var q=c.prepareStatement("SELECT COUNT(*),COALESCE(SUM(byte_size),0) FROM draft_attachments WHERE draft_id=? FOR UPDATE")){q.setString(1,draftId);try(var rows=q.executeQuery()){rows.next();if(rows.getInt(1)>=20 || rows.getLong(2)+attachment.size()>4*1024*1024)throw new InvalidInput("ATTACHMENT_TOTAL_EXCEEDED");}}
            try(var q=c.prepareStatement("INSERT INTO draft_attachments(attachment_id,draft_id,object_id,file_name,media_type,sha256,byte_size) VALUES(?,?,?,?,?,?,?)")){q.setString(1,attachment.id());q.setString(2,draftId);q.setString(3,attachment.objectId());q.setString(4,attachment.fileName());q.setString(5,attachment.mediaType());q.setString(6,attachment.sha256());q.setLong(7,attachment.size());q.executeUpdate();}
            try(var q=c.prepareStatement("UPDATE drafts SET version_no=version_no+1 WHERE draft_id=?")){q.setString(1,draftId);q.executeUpdate();}return null;});return draft(accountId,draftId);
    }

    public Attachment authorizedMessageAttachment(String accountId,String entryId,String attachmentId){
        ready();List<Attachment> rows=jdbc.query("SELECT a.attachment_id,a.object_id,a.file_name,a.media_type,a.sha256,a.byte_size FROM mailbox_entries e JOIN message_attachments a ON a.content_id=e.content_id WHERE e.account_id=? AND e.entry_id=? AND a.attachment_id=?",(r,n)->attachment(r),accountId,entryId,attachmentId);if(rows.isEmpty())throw new NotFound();return rows.get(0);
    }
    public Attachment authorizedDraftAttachment(String accountId,String draftId,String attachmentId){
        ready();List<Attachment> rows=jdbc.query("SELECT a.attachment_id,a.object_id,a.file_name,a.media_type,a.sha256,a.byte_size FROM drafts d JOIN draft_attachments a ON a.draft_id=d.draft_id WHERE d.account_id=? AND d.draft_id=? AND a.attachment_id=?",(r,n)->attachment(r),accountId,draftId,attachmentId);if(rows.isEmpty())throw new NotFound();return rows.get(0);
    }

    public List<Category> categories(String accountId){
        ready();return jdbc.query("SELECT c.category_id,c.name,c.version_no,COUNT(e.entry_id),COALESCE(SUM(IF(e.is_read,0,1)),0) FROM categories c LEFT JOIN mailbox_entries e ON e.category_id=c.category_id AND e.account_id=c.account_id WHERE c.account_id=? GROUP BY c.category_id,c.name,c.version_no ORDER BY c.name,c.category_id",(r,n)->new Category(r.getString(1),r.getString(2),r.getLong(3),r.getLong(4),r.getLong(5)),accountId);
    }
    public Category createCategory(String accountId,String name){
        ready();String id=UUID.randomUUID().toString();try{write("category-create|"+accountId+"|"+id,c->{
            try(var owner=c.prepareStatement("SELECT account_id FROM accounts WHERE account_id=? FOR UPDATE")){owner.setString(1,accountId);try(var rows=owner.executeQuery()){if(!rows.next())throw new NotFound();}}
            try(var count=c.prepareStatement("SELECT COUNT(*) FROM categories WHERE account_id=?")){count.setString(1,accountId);try(var rows=count.executeQuery()){rows.next();if(rows.getInt(1)>=50)throw new InvalidInput("CATEGORY_LIMIT");}}
            try(var q=c.prepareStatement("INSERT INTO categories(category_id,account_id,name) VALUES(?,?,?)")){q.setString(1,id);q.setString(2,accountId);q.setString(3,name);q.executeUpdate();}return null;});}catch(DataIntegrityViolationException duplicate){throw new InvalidInput("CATEGORY_NAME_EXISTS");}return category(accountId,id);
    }
    public Category renameCategory(String accountId,String categoryId,long expectedVersion,String name){
        ready();try{write("category-rename|"+accountId+"|"+categoryId+"|"+expectedVersion,c->{long current=lockedVersion(c,"categories","category_id",categoryId,accountId);if(current!=expectedVersion)throw new VersionConflict(current);try(var q=c.prepareStatement("UPDATE categories SET name=?,version_no=version_no+1 WHERE category_id=? AND account_id=?")){q.setString(1,name);q.setString(2,categoryId);q.setString(3,accountId);q.executeUpdate();}return null;});}catch(DataIntegrityViolationException duplicate){throw new InvalidInput("CATEGORY_NAME_EXISTS");}return category(accountId,categoryId);
    }
    public void deleteCategory(String accountId,String categoryId,long expectedVersion){
        ready();write("category-delete|"+accountId+"|"+categoryId+"|"+expectedVersion,c->{long current=lockedVersion(c,"categories","category_id",categoryId,accountId);if(current!=expectedVersion)throw new VersionConflict(current);try(var clear=c.prepareStatement("UPDATE mailbox_entries SET category_id=NULL,version_no=version_no+1 WHERE account_id=? AND category_id=?")){clear.setString(1,accountId);clear.setString(2,categoryId);clear.executeUpdate();}try(var q=c.prepareStatement("DELETE FROM categories WHERE category_id=? AND account_id=?")){q.setString(1,categoryId);q.setString(2,accountId);q.executeUpdate();}return null;});
    }

    private Category category(String accountId,String id){return categories(accountId).stream().filter(c->c.id().equals(id)).findFirst().orElseThrow(NotFound::new);}
    private void assertCategory(Connection c,String accountId,String categoryId) throws Exception {try(var q=c.prepareStatement("SELECT 1 FROM categories WHERE account_id=? AND category_id=?")){q.setString(1,accountId);q.setString(2,categoryId);try(var rows=q.executeQuery()){if(!rows.next())throw new NotFound();}}}
    private long lockedVersion(Connection c,String table,String idColumn,String id,String accountId) throws Exception {String sql="SELECT version_no FROM "+table+" WHERE "+idColumn+"=? AND account_id=? FOR UPDATE";try(var q=c.prepareStatement(sql)){q.setString(1,id);q.setString(2,accountId);try(var rows=q.executeQuery()){if(!rows.next())throw new NotFound();return rows.getLong(1);}}}
    private <T> T write(String descriptor,WitnessGate.SqlWork<T> work){try{return witness.write(descriptor,work);}catch(CommitUnknownException unknown){throw new CommitOutcomeUnknown(unknown);}}
    private MessageSummary summary(ResultSet r) throws java.sql.SQLException {Timestamp sent=r.getTimestamp("sent_at"),received=r.getTimestamp("created_at");String text=r.getString("text_body");String preview=text==null?"":text.replaceAll("\\s+"," ").strip();if(preview.length()>200)preview=preview.substring(0,200);return new MessageSummary(r.getString("entry_id"),r.getString("content_id"),Folder.valueOf(r.getString("folder")),r.getBoolean("is_read"),r.getString("category_id"),r.getLong("version_no"),r.getString("from_address"),r.getString("from_name"),r.getString("subject"),preview,sent==null?null:sent.toInstant(),received.toInstant(),r.getInt("attachment_count"));}
    private Attachment attachment(ResultSet r) throws java.sql.SQLException{return new Attachment(r.getString("attachment_id"),r.getString("object_id"),r.getString("file_name"),r.getString("media_type"),r.getString("sha256"),r.getLong("byte_size"));}
    private List<Attachment> attachmentsForDraft(String draftId){return jdbc.query("SELECT attachment_id,object_id,file_name,media_type,sha256,byte_size FROM draft_attachments WHERE draft_id=? ORDER BY created_at,attachment_id",(r,n)->attachment(r),draftId);}
    private List<Attachment> attachments(Connection c,String sql,String id) throws Exception {try(var q=c.prepareStatement(sql)){q.setString(1,id);try(var rows=q.executeQuery()){var result=new ArrayList<Attachment>();while(rows.next())result.add(attachment(rows));return result;}}}
    private Draft draft(ResultSet r,List<Attachment> attachments) throws java.sql.SQLException{return new Draft(r.getString("draft_id"),r.getLong("version_no"),r.getString("subject"),r.getString("text_body"),r.getString("html_body"),json(r.getString("to_json")),json(r.getString("cc_json")),json(r.getString("bcc_json")),DraftMode.valueOf(r.getString("mode")),r.getString("source_content_id"),attachments,r.getTimestamp("created_at").toInstant(),r.getTimestamp("updated_at").toInstant());}
    private void draftValues(PreparedStatement q,int start,DraftInput input) throws Exception {q.setString(start,input.subject());q.setString(start+1,input.textBody());q.setString(start+2,input.htmlBody());q.setString(start+3,json(input.to()));q.setString(start+4,json(input.cc()));q.setString(start+5,json(input.bcc()));q.setString(start+6,input.mode().name());q.setString(start+7,input.sourceContentId());}
    private String json(List<String> values){return values.isEmpty()?"[]":"[\""+String.join("\",\"",values)+"\"]";}
    private List<String> json(String value){if(value==null || value.equals("[]"))return List.of();if(value.length()<4)throw new IllegalStateException("Invalid persisted address list");return List.of(value.substring(2,value.length()-2).split("\\\",\\\"",-1));}
    private String prefix(String subject,String prefix){return subject.regionMatches(true,0,prefix,0,prefix.length())?subject:prefix+subject;}
    private String emptyToNull(String value){return value==null || value.isBlank()?null:value;}
    private void setInstant(PreparedStatement q,int index,Instant value) throws Exception {if(value==null)q.setTimestamp(index,null);else q.setTimestamp(index,Timestamp.from(value));}
    private String escapeLike(String value){return value.replace("\\","\\\\").replace("%","\\%").replace("_","\\_");}
    private record Cursor(Instant time,String id) {}
    private Cursor cursor(String encoded){try{String value=new String(Base64.getUrlDecoder().decode(encoded),StandardCharsets.UTF_8);int split=value.lastIndexOf('|');return new Cursor(Instant.parse(value.substring(0,split)),UUID.fromString(value.substring(split+1)).toString());}catch(RuntimeException invalid){throw new InvalidInput("INVALID_CURSOR");}}
    private String cursor(Instant time,String id){return Base64.getUrlEncoder().withoutPadding().encodeToString((time.toString()+"|"+id).getBytes(StandardCharsets.UTF_8));}
}

