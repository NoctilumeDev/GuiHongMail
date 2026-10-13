package dev.guihong.mailbox.application;

import dev.guihong.mailbox.domain.IdentityRepository;
import dev.guihong.mailbox.domain.IdentityRepository.Account;
import dev.guihong.mailbox.domain.PasswordHasher;
import dev.guihong.mailbox.domain.Principal;
import dev.guihong.platform.Hashes;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.Locale;
import java.util.UUID;

public final class IdentityService {
    public record Session(String token,String csrf,Principal principal) {}
    private final IdentityRepository repository;private final PasswordHasher passwords;
    private final SecureRandom random=new SecureRandom();private final String dummy;
    public IdentityService(IdentityRepository repository,PasswordHasher passwords){this.repository=repository;this.passwords=passwords;this.dummy=passwords.hash("synthetic-account-does-not-exist");}
    private void available(){if(!repository.available())throw new IllegalStateException("SERVICE_UNAVAILABLE");}
    private String token(){byte[] bytes=new byte[32];random.nextBytes(bytes);return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);}
    public Session login(String address,String password,String client){
        available();if(address==null || password==null || address.length()>254 || password.getBytes(StandardCharsets.UTF_8).length>72)throw new IllegalArgumentException("AUTHENTICATION_FAILED");
        String normalized=address.toLowerCase(Locale.ROOT);Account account=repository.byAddress(normalized);
        boolean matches=passwords.matches(password,account==null?dummy:account.password());
        if(account==null || !matches || !account.enabled()){
            if(repository.failedLoginAttempt(Hashes.sha256(client+"|"+normalized),System.currentTimeMillis()/60000)>5)
                throw new IllegalArgumentException("RATE_LIMITED");
            throw new IllegalArgumentException("AUTHENTICATION_FAILED");
        }
        return createSession(account,null);
    }
    private Session createSession(Account a,String oldHash){
        String token=token(),csrf=token(),tokenHash=Hashes.sha256(token),csrfHash=Hashes.sha256(csrf);
        repository.session(a,tokenHash,csrfHash,oldHash);
        return new Session(token,csrf,new Principal(a.id(),a.address(),a.name(),a.role(),tokenHash,csrfHash));
    }
    public Principal authenticate(String token){
        available();return token==null || !token.matches("[a-zA-Z0-9_-]{43}")?null:repository.authenticate(Hashes.sha256(token));
    }
    public Session refresh(Principal p){available();return createSession(repository.byId(p.accountId()),p.sessionHash());}
    public void logout(Principal p){available();repository.logout(p.sessionHash());}
    public String provision(String address,String password,String name){
        available();if(address==null || !address.matches("[a-z0-9._-]{1,64}@guihong\\.test") || password==null || password.length()<12 || password.getBytes(StandardCharsets.UTF_8).length>72 || name==null || name.length()>80)throw new IllegalArgumentException("INVALID_ACCOUNT");
        return repository.provision(address,passwords.hash(password),name);
    }
    public void enabled(String id,boolean enabled){available();UUID.fromString(id);repository.enabled(id,enabled);}
}
