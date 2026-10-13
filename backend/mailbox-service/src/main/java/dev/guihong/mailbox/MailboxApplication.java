package dev.guihong.mailbox;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Import;
import dev.guihong.platform.FoundationConfiguration;
@SpringBootApplication
@Import(FoundationConfiguration.class)
public class MailboxApplication {
    public static void main(String[] args) {
        System.setProperty("guihong.role", "mailbox");
        SpringApplication.run(MailboxApplication.class,args);
    }
}
