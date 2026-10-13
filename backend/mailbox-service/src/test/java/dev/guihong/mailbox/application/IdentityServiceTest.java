package dev.guihong.mailbox.application;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

import dev.guihong.mailbox.domain.IdentityRepository;
import dev.guihong.mailbox.domain.PasswordHasher;
import dev.guihong.mailbox.domain.Principal;
import java.util.HashMap;
import java.util.Map;
import org.junit.jupiter.api.Test;

final class IdentityServiceTest {
    @Test void invalidRequestsCannotConsumeTheRightToUseCorrectCredentials() {
        MemoryRepository repository=new MemoryRepository();
        repository.account=new IdentityRepository.Account("account-1","alice@guihong.test","Alice","hash:correct-password",true,0,"USER");
        IdentityService service=new IdentityService(repository,new PlainHasher());

        for(int attempt=1;attempt<=5;attempt++)
            assertEquals("AUTHENTICATION_FAILED",assertThrows(IllegalArgumentException.class,
                ()->service.login("alice@guihong.test","wrong-password","127.0.0.1")).getMessage());
        assertEquals("RATE_LIMITED",assertThrows(IllegalArgumentException.class,
            ()->service.login("alice@guihong.test","wrong-password","127.0.0.1")).getMessage());

        IdentityService.Session session=service.login("ALICE@GUIHONG.TEST","correct-password","127.0.0.1");
        assertEquals("account-1",session.principal().accountId());
        assertNotNull(repository.sessionTokenHash);
        assertEquals(6,repository.failedAttempts.values().iterator().next());
    }

    private static final class PlainHasher implements PasswordHasher {
        public String hash(String raw){return "hash:"+raw;}
        public boolean matches(String raw,String encoded){return encoded.equals(hash(raw));}
    }

    private static final class MemoryRepository implements IdentityRepository {
        Account account;String sessionTokenHash;Map<String,Integer> failedAttempts=new HashMap<>();
        public boolean available(){return true;}
        public int failedLoginAttempt(String bucket,long minute){return failedAttempts.merge(bucket,1,Integer::sum);}
        public Account byAddress(String address){return account!=null && account.address().equals(address)?account:null;}
        public Account byId(String id){return account;}
        public Principal authenticate(String tokenHash){return null;}
        public void session(Account value,String tokenHash,String csrfHash,String oldHash){sessionTokenHash=tokenHash;}
        public void logout(String sessionHash){}
        public String provision(String address,String passwordHash,String displayName){throw new UnsupportedOperationException();}
        public void enabled(String accountId,boolean enabled){throw new UnsupportedOperationException();}
    }
}
