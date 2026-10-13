package dev.guihong.platform;

import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import javax.sql.DataSource;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;
import org.apache.rocketmq.tools.admin.DefaultMQAdminExt;
import org.springframework.context.ConfigurableApplicationContext;

@RestController
public final class FoundationController {
    private final WitnessGate witness; private final ObjectStore objects; private final FoundationSettings settings;
    private final ConfigurableApplicationContext context; private final AtomicBoolean draining=new AtomicBoolean();
    public FoundationController(WitnessGate witness,ObjectStore objects,FoundationSettings settings,ConfigurableApplicationContext context) {
        this.witness=witness;this.objects=objects;this.settings=settings;this.context=context;
    }
    @GetMapping("/health/live") public Map<String,Object> live() { return Map.of("service",settings.role(),"alive",true); }
    @GetMapping("/health/ready") public ResponseEntity<Map<String,Object>> ready() {
        if (witness.state().equals("WAITING_DEPENDENCY")) witness.initialize();
        boolean db=witness.verifyCurrent(); boolean storage=objects.ready(); boolean mq=false;
        if (db && storage && !draining.get()) {
            DefaultMQAdminExt admin=new DefaultMQAdminExt(3000);
            admin.setNamesrvAddr(settings.namesrv());admin.setInstanceName(settings.role()+"-readiness");
            admin.setClientCallbackExecutorThreads(1);
            try { admin.start();admin.fetchBrokerRuntimeStats(settings.broker());mq=true; }
            catch (Exception unavailable) { mq=false; } finally { admin.shutdown(); }
        }
        boolean active=db && storage && mq && !draining.get();
        return ResponseEntity.status(active?200:503).body(Map.of("service",settings.role(),"state",draining.get()?"DRAINING":witness.state(),"database",db,"storage",storage,"mq",mq));
    }
    @GetMapping("/internal/identity") public Map<String,Object> identity() {
        return Map.of("service",settings.role(),"source_sha",settings.sourceSha(),"generation",witness.generation(),"state",witness.state());
    }
    @PostMapping("/internal/drain") public Map<String,Object> drain() { draining.set(true);return Map.of("service",settings.role(),"state","DRAINING"); }
    @PostMapping("/internal/shutdown") public ResponseEntity<Map<String,Object>> shutdown() {
        draining.set(true);
        Thread closer=new Thread(() -> {
            try { Thread.sleep(150); } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
            context.close();
        },settings.role()+"-owned-shutdown");
        closer.setDaemon(false);closer.start();
        return ResponseEntity.accepted().body(Map.of("service",settings.role(),"state","DRAINING"));
    }
    public boolean writable() { return !draining.get() && witness.verifyCurrent(); }
}
