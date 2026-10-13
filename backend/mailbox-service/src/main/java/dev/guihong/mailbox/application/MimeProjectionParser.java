package dev.guihong.mailbox.application;

import dev.guihong.mailbox.domain.MailboxModels.ParsedMessage;

public interface MimeProjectionParser {
    ParsedMessage parse(byte[] rawMime);
}

