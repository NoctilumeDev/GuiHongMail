package dev.guihong.ingress;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Import;
import dev.guihong.platform.FoundationConfiguration;
@SpringBootApplication
@Import(FoundationConfiguration.class)
public class IngressApplication {
    public static void main(String[] args) {
        System.setProperty("guihong.role", "ingress");
        SpringApplication.run(IngressApplication.class,args);
    }
}
