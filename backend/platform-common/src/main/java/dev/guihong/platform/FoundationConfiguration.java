package dev.guihong.platform;

import java.io.IOException;
import javax.sql.DataSource;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.boot.web.servlet.FilterRegistrationBean;

@Configuration
public class FoundationConfiguration {
    @Bean public FoundationSettings settings() throws IOException { return FoundationSettings.fromEnvironment(); }
    @Bean(destroyMethod="close") public WitnessGate witness(DataSource dataSource,FoundationSettings settings) throws IOException {
        return new WitnessGate(dataSource,settings.witnessRoot(),settings.role(),settings.sourceSha());
    }
    @Bean(destroyMethod="close") public ObjectStore objects(FoundationSettings settings) {
        return new S3ObjectStore(settings.s3Endpoint(),settings.s3Bucket(),settings.s3Key(),settings.s3Secret());
    }
    @Bean public FoundationController foundationController(WitnessGate witness,ObjectStore objects,FoundationSettings settings,ConfigurableApplicationContext context) {
        return new FoundationController(witness,objects,settings,context);
    }
    @Bean public FilterRegistrationBean<InternalCommandFilter> internalFilter(FoundationSettings settings) {
        FilterRegistrationBean<InternalCommandFilter> registration=new FilterRegistrationBean<>(new InternalCommandFilter(settings));
        registration.addUrlPatterns("/internal/*");registration.setOrder(0);return registration;
    }
}
