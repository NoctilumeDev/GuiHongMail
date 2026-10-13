package dev.guihong.delivery;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Import;
import dev.guihong.platform.FoundationConfiguration;
@SpringBootApplication
@Import(FoundationConfiguration.class)
public class DeliveryApplication {
    public static void main(String[] args) {
        System.setProperty("guihong.role", "delivery");
        SpringApplication.run(DeliveryApplication.class,args);
    }
}
