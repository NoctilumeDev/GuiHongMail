package dev.guihong.mailbox.domain;
public interface PasswordHasher {
    String hash(String password);
    boolean matches(String password,String hash);
}
