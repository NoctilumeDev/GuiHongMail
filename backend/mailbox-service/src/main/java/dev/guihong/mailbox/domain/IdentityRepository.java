package dev.guihong.mailbox.domain;
public interface IdentityRepository {
    record Account(String id,String address,String name,String password,boolean enabled,long epoch,String role) {}
    boolean available();
    int failedLoginAttempt(String bucketHash,long minute);
    Account byAddress(String address);
    Account byId(String id);
    Principal authenticate(String tokenHash);
    void session(Account account,String tokenHash,String csrfHash,String oldHash);
    void logout(String sessionHash);
    String provision(String address,String passwordHash,String displayName);
    void enabled(String accountId,boolean enabled);
}
