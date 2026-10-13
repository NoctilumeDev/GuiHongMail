package dev.guihong.mailbox.infrastructure;

import dev.guihong.mailbox.application.*;
import dev.guihong.mailbox.domain.MailboxRepository;
import dev.guihong.platform.BlobRepository;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class MailboxConfiguration {
    @Bean public HtmlContentSanitizer htmlContentSanitizer(){return new OwaspHtmlContentSanitizer();}
    @Bean public MimeProjectionParser mimeProjectionParser(HtmlContentSanitizer sanitizer){return new AngusMimeProjectionParser(sanitizer);}
    @Bean public MailboxObjectStore mailboxObjectStore(BlobRepository blobs){return new PlatformMailboxObjectStore(blobs);}
    @Bean public MailboxService mailboxService(MailboxRepository repository,MimeProjectionParser mime,HtmlContentSanitizer html,MailboxObjectStore objects){return new MailboxService(repository,mime,html,objects);}
}

