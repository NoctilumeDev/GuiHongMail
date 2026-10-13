package dev.guihong.platform;

import java.util.Map;
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
    private final ConfigurableApplicationContext context;private final WriteGate gate;private final BlobRepository blobs;
    public FoundationController(WitnessGate witness,ObjectStore objects,FoundationSettings settings,ConfigurableApplicationContext context,WriteGate gate,BlobRepository blobs) {
        this.witness=witness;this.objects=objects;this.settings=settings;this.context=context;this.gate=gate;this.blobs=blobs;
    }
    @GetMapping("/health/live") public Map<String,Object> live() { return Map.of("service",settings.role(),"alive",true); }
    @GetMapping("/health/ready") public ResponseEntity<Map<String,Object>> ready() {
        if (witness.state().equals("WAITING_DEPENDENCY")) witness.initialize();
        boolean db=witness.verifyCurrent(); boolean storage=objects.ready(); boolean mq=false;
        if(db && storage && !gate.objectsReconciled())blobs.reconcileReferences();
        if (db && storage && gate.objectsReconciled() && !gate.draining()) {
            DefaultMQAdminExt admin=new DefaultMQAdminExt(3000);
            admin.setNamesrvAddr(settings.namesrv());admin.setInstanceName(settings.role()+"-readiness");
            admin.setClientCallbackExecutorThreads(1);
            try { admin.start();admin.fetchBrokerRuntimeStats(settings.broker());mq=true; }
            catch (Exception unavailable) { mq=false; } finally { admin.shutdown(); }
        }
        boolean active=db && storage && mq && gate.objectsReconciled() && !gate.draining();
        return ResponseEntity.status(active?200:503).body(Map.of("service",settings.role(),"state",gate.draining()?"DRAINING":witness.state(),"database",db,"storage",storage,"mq",mq,"objects_reconciled",gate.objectsReconciled()));
    }
    @GetMapping("/internal/identity") public Map<String,Object> identity() {
        return Map.of("service",settings.role(),"source_sha",settings.sourceSha(),"generation",witness.generation(),"state",witness.state());
    }
    @PostMapping("/internal/drain") public Map<String,Object> drain() { gate.drain();return Map.of("service",settings.role(),"state","DRAINING"); }
    @PostMapping("/internal/shutdown") public ResponseEntity<Map<String,Object>> shutdown() {
        gate.drain();
        Thread closer=new Thread(() -> {
            try { Thread.sleep(150); } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
            context.close();
        },settings.role()+"-owned-shutdown");
        closer.setDaemon(false);closer.start();
        return ResponseEntity.accepted().body(Map.of("service",settings.role(),"state","DRAINING"));
    }
    public boolean writable() { return gate.writable(); }
}
