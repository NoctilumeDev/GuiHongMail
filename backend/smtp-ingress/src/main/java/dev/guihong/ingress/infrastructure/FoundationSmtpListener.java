package dev.guihong.ingress.infrastructure;

import dev.guihong.platform.FoundationController;
import java.io.InputStream;
import java.net.InetAddress;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.subethamail.smtp.MessageHandler;
import org.subethamail.smtp.RejectException;
import org.subethamail.smtp.server.SMTPServer;

/** M1 never accepts responsibility before the durable ingress implementation exists. */
@Configuration
public class FoundationSmtpListener {
    @Bean(initMethod="start",destroyMethod="stop")
    public SMTPServer smtpServer(FoundationController foundation) throws Exception {
        return SMTPServer.port(12525).bindAddress(InetAddress.getByName("127.0.0.1"))
            .hostName("guihong.test").softwareName("GuiHong M1")
            .maxConnections(2).connectionTimeoutMs(10000).maxRecipients(10).maxMessageSize(5*1024*1024)
            .messageHandlerFactory(context -> new MessageHandler() {
                public void from(String address) throws RejectException {
                    if (!foundation.writable()) throw new RejectException(451,"Service temporarily unavailable");
                }
                public void recipient(String address) throws RejectException {
                    int at=address.lastIndexOf('@');
                    if (at<1 || !address.substring(at+1).equalsIgnoreCase("guihong.test"))
                        throw new RejectException(550,"Relay denied");
                    throw new RejectException(451,"Durable local reception not available in M1");
                }
                public String data(InputStream data) throws RejectException {
                    throw new RejectException(451,"No accepted recipient or durable responsibility");
                }
                public void done() {}
            }).build();
    }
}
