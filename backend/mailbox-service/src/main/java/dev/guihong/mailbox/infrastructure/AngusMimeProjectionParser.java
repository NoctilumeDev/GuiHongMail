package dev.guihong.mailbox.infrastructure;

import static dev.guihong.mailbox.application.MailboxExceptions.InvalidInput;
import dev.guihong.mailbox.application.HtmlContentSanitizer;
import dev.guihong.mailbox.application.MimeProjectionParser;
import dev.guihong.mailbox.domain.MailboxModels.*;
import dev.guihong.platform.Hashes;
import jakarta.mail.Address;
import jakarta.mail.Message;
import jakarta.mail.Multipart;
import jakarta.mail.Part;
import jakarta.mail.Session;
import jakarta.mail.internet.ContentType;
import jakarta.mail.internet.InternetAddress;
import jakarta.mail.internet.MimeMessage;
import jakarta.mail.internet.MimeUtility;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Properties;

public final class AngusMimeProjectionParser implements MimeProjectionParser {
    private static final int MAX_BYTES=5*1024*1024,MAX_PARTS=20,MAX_DEPTH=8;
    private final HtmlContentSanitizer sanitizer;
    public AngusMimeProjectionParser(HtmlContentSanitizer sanitizer){this.sanitizer=sanitizer;}

    public ParsedMessage parse(byte[] raw){
        try{
            if(raw.length==0 || raw.length>MAX_BYTES)throw new InvalidInput("MIME_SIZE_EXCEEDED");
            MimeMessage message=new MimeMessage(Session.getInstance(new Properties()),new ByteArrayInputStream(raw));
            State state=new State();walk(message,0,state);
            Address[] from=message.getFrom();
            if(from==null || from.length!=1 || !(from[0] instanceof InternetAddress sender) || sender.getAddress()==null)throw new InvalidInput("MIME_FROM_REQUIRED");
            String subject=value(message.getSubject(),998);String messageId=header(message,"Message-ID",998);
            var recipients=new ArrayList<Recipient>();
            recipients.addAll(recipients(message,Message.RecipientType.TO,RecipientKind.TO));
            recipients.addAll(recipients(message,Message.RecipientType.CC,RecipientKind.CC));
            recipients.addAll(recipients(message,Message.RecipientType.BCC,RecipientKind.BCC));
            Instant sent=message.getSentDate()==null?null:message.getSentDate().toInstant();
            String text=state.plain.toString();String safeHtml=sanitizer.sanitize(state.html.toString());
            if(text.isBlank() && !safeHtml.isBlank())text=safeHtml.replaceAll("<[^>]+>"," ").replaceAll("\\s+"," ").strip();
            return new ParsedMessage(messageId,new dev.guihong.mailbox.domain.MailboxModels.Address(sender.getAddress().toLowerCase(Locale.ROOT),value(sender.getPersonal(),200)),subject,text,safeHtml,sent,List.copyOf(recipients),List.copyOf(state.attachments));
        }catch(InvalidInput rejected){throw rejected;}
        catch(Exception malformed){throw new InvalidInput("MIME_MALFORMED");}
    }

    private void walk(Part part,int depth,State state) throws Exception {
        if(depth>MAX_DEPTH || ++state.parts>MAX_PARTS)throw new InvalidInput("MIME_PART_LIMIT");
        String file=part.getFileName();boolean attachment=Part.ATTACHMENT.equalsIgnoreCase(part.getDisposition()) || file!=null;
        if(attachment){
            byte[] bytes=bounded(part,MAX_BYTES-state.decoded);state.decoded+=bytes.length;
            if(state.decoded>MAX_BYTES)throw new InvalidInput("MIME_DECODED_SIZE_EXCEEDED");
            String name=file==null?"attachment-"+state.attachments.size():MimeUtility.decodeText(file);
            name=safeFileName(name);String media=new ContentType(part.getContentType()).getBaseType().toLowerCase(Locale.ROOT);
            state.attachments.add(new ParsedAttachment(name,media,bytes,Hashes.sha256(bytes)));return;
        }
        if(part.isMimeType("multipart/*")){
            Object content=part.getContent();if(!(content instanceof Multipart multipart))throw new InvalidInput("MIME_MALFORMED");
            for(int index=0;index<multipart.getCount();index++)walk(multipart.getBodyPart(index),depth+1,state);return;
        }
        if(part.isMimeType("message/rfc822")){
            Object nested=part.getContent();if(!(nested instanceof Part nestedPart))throw new InvalidInput("MIME_MALFORMED");walk(nestedPart,depth+1,state);return;
        }
        if(part.isMimeType("text/plain") || part.isMimeType("text/html")){
            byte[] bytes=bounded(part,MAX_BYTES-state.decoded);state.decoded+=bytes.length;
            if(state.decoded>MAX_BYTES)throw new InvalidInput("MIME_DECODED_SIZE_EXCEEDED");
            Charset charset=charset(part.getContentType());String value=new String(bytes,charset);
            StringBuilder target=part.isMimeType("text/html")?state.html:state.plain;
            if(target.length()>0)target.append('\n');target.append(value);return;
        }
        bounded(part,Math.min(MAX_BYTES-state.decoded,64*1024));
    }
    private byte[] bounded(Part part,int remaining) throws Exception {
        if(remaining<0)throw new InvalidInput("MIME_DECODED_SIZE_EXCEEDED");
        try(var input=part.getInputStream()){byte[] bytes=input.readNBytes(remaining+1);if(bytes.length>remaining)throw new InvalidInput("MIME_DECODED_SIZE_EXCEEDED");return bytes;}
    }
    private Charset charset(String contentType){
        try{String name=new ContentType(contentType).getParameter("charset");return name==null?StandardCharsets.UTF_8:Charset.forName(MimeUtility.javaCharset(name));}
        catch(Exception invalid){return StandardCharsets.UTF_8;}
    }
    private List<Recipient> recipients(MimeMessage message,Message.RecipientType type,RecipientKind kind) throws Exception {
        Address[] values=message.getRecipients(type);if(values==null)return List.of();var result=new ArrayList<Recipient>();
        for(int index=0;index<values.length;index++){
            if(!(values[index] instanceof InternetAddress address) || address.getAddress()==null)throw new InvalidInput("MIME_RECIPIENT_INVALID");
            result.add(new Recipient(kind,index,address.getAddress().toLowerCase(Locale.ROOT),value(address.getPersonal(),200)));
        }return result;
    }
    private String header(MimeMessage message,String name,int max) throws Exception {String[] values=message.getHeader(name);return values==null || values.length==0?null:value(values[0],max);}
    private String value(String value,int max){if(value==null)return "";String clean=value.replace("\r","").replace("\n","").strip();if(clean.length()>max)throw new InvalidInput("MIME_HEADER_LIMIT");return clean;}
    private String safeFileName(String input){if(input.contains("/") || input.contains("\\") || input.contains("\r") || input.contains("\n"))throw new InvalidInput("MIME_FILE_NAME_INVALID");String value=input.strip();if(value.isEmpty() || value.length()>255 || value.equals(".") || value.equals(".."))throw new InvalidInput("MIME_FILE_NAME_INVALID");return value;}
    private static final class State {int parts;int decoded;StringBuilder plain=new StringBuilder();StringBuilder html=new StringBuilder();List<ParsedAttachment> attachments=new ArrayList<>();}
}

