package dev.guihong.mailbox.infrastructure;
import dev.guihong.mailbox.application.IdentityService;
import dev.guihong.mailbox.domain.IdentityRepository;
import dev.guihong.mailbox.domain.PasswordHasher;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
@Configuration
public class IdentityConfiguration {
    @Bean public PasswordHasher passwords(){return new PasswordHasher(){
        private final BCryptPasswordEncoder encoder=new BCryptPasswordEncoder(10);
        public String hash(String password){return encoder.encode(password);}
        public boolean matches(String password,String hash){return encoder.matches(password,hash);}
    };}
    @Bean public IdentityService identities(IdentityRepository repository,PasswordHasher passwords){return new IdentityService(repository,passwords);}
}
