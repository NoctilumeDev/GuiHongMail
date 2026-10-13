package dev.guihong.mailbox.infrastructure;

import dev.guihong.mailbox.application.HtmlContentSanitizer;
import org.owasp.html.PolicyFactory;
import org.owasp.html.Sanitizers;

public final class OwaspHtmlContentSanitizer implements HtmlContentSanitizer {
    private static final PolicyFactory POLICY=Sanitizers.BLOCKS.and(Sanitizers.FORMATTING).and(Sanitizers.TABLES).and(Sanitizers.LINKS);
    public String sanitize(String html){return html==null?"":POLICY.sanitize(html);}
}

