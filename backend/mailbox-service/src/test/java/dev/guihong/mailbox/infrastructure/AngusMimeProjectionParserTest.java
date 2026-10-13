package dev.guihong.mailbox.infrastructure;

import static org.junit.jupiter.api.Assertions.*;
import dev.guihong.mailbox.application.MailboxExceptions.InvalidInput;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;

final class AngusMimeProjectionParserTest {
    private final AngusMimeProjectionParser parser=new AngusMimeProjectionParser(new OwaspHtmlContentSanitizer());

    @Test void stripsActiveAndRemoteHtmlWhilePreservingReadableContent() {
        String raw="""
            From: Alice <alice@guihong.test>\r
            To: Bob <bob@guihong.test>\r
            Subject: =?UTF-8?B?5bCP6K+V?=\r
            MIME-Version: 1.0\r
            Content-Type: text/html; charset=UTF-8\r
            \r
            <p onclick="fetch('https://evil.invalid')">正文</p><script>alert(1)</script><img src="https://tracker.invalid/pixel"><form action="https://evil.invalid"><input></form>
            """;
        var message=parser.parse(raw.getBytes(StandardCharsets.UTF_8));
        assertEquals("小试",message.subject());assertTrue(message.safeHtml().contains("正文"));
        assertFalse(message.safeHtml().contains("script"));assertFalse(message.safeHtml().contains("onclick"));
        assertFalse(message.safeHtml().contains("tracker.invalid"));assertFalse(message.safeHtml().contains("form"));
    }

    @Test void readsAttachmentBytesAndMetadata() {
        String raw="""
            From: alice@guihong.test\r
            To: bob@guihong.test\r
            Subject: attachment\r
            MIME-Version: 1.0\r
            Content-Type: multipart/mixed; boundary=x\r
            \r
            --x\r
            Content-Type: text/plain; charset=UTF-8\r
            \r
            hello\r
            --x\r
            Content-Type: text/plain\r
            Content-Disposition: attachment; filename="notes.txt"\r
            \r
            bytes\r
            --x--\r
            """;
        var message=parser.parse(raw.getBytes(StandardCharsets.UTF_8));
        assertEquals(1,message.attachments().size());assertEquals("notes.txt",message.attachments().get(0).fileName());
        assertTrue(new String(message.attachments().get(0).bytes(),StandardCharsets.UTF_8).contains("bytes"));
    }

    @Test void rejectsAttachmentFileNamesThatContainAPath() {
        String raw="""
            From: alice@guihong.test\r
            To: bob@guihong.test\r
            Subject: path\r
            MIME-Version: 1.0\r
            Content-Type: text/plain\r
            Content-Disposition: attachment; filename="../secret.txt"\r
            \r
            bytes
            """;
        assertEquals("MIME_FILE_NAME_INVALID",assertThrows(InvalidInput.class,()->parser.parse(raw.getBytes(StandardCharsets.UTF_8))).code());
    }
}
