package dev.guihong.mailbox.domain;
public record Principal(String accountId,String address,String displayName,String role,String sessionHash,String csrfHash) {}
