package dev.guihong.platform;

import static org.junit.jupiter.api.Assertions.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.apache.rocketmq.client.consumer.DefaultMQPullConsumer;
import org.apache.rocketmq.client.consumer.PullStatus;
import org.apache.rocketmq.client.producer.DefaultMQProducer;
import org.apache.rocketmq.client.producer.SendStatus;
import org.apache.rocketmq.common.TopicConfig;
import org.apache.rocketmq.common.message.Message;
import org.apache.rocketmq.remoting.protocol.subscription.SubscriptionGroupConfig;
import org.apache.rocketmq.tools.admin.DefaultMQAdminExt;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import tools.jackson.databind.ObjectMapper;

/** A real bounded protocol probe. It is disabled in compilation-only CI, never mocked into success. */
@EnabledIfEnvironmentVariable(named="GUIHONG_INTEGRATION",matches="1")
class OwnedMqIntegrationTest {
    @Test void persistentSendAndIndependentPull() throws Exception {
        String owner=System.getenv("GUIHONG_LAB_ID");assertNotNull(owner);assertTrue(owner.matches("guihong-[a-z0-9-]{1,40}"));
        String topic=System.getenv("GUIHONG_MQ_PROBE_TOPIC");assertTrue(topic.startsWith(owner.replace('-','_')+"_probe_"));
        String group=topic+"_consumer",namesrv="127.0.0.1:19876",broker="127.0.0.1:20911";
        Path out=Path.of(System.getenv("GUIHONG_MQ_PROBE_OUT"));assertFalse(Files.exists(out));
        byte[] payload=("归鸿真实 MQ 见证|"+topic).getBytes(StandardCharsets.UTF_8);
        Map<String,Object> facts=new LinkedHashMap<>();facts.put("topic",topic);facts.put("payload_sha256",Hashes.sha256(payload));
        DefaultMQAdminExt admin=new DefaultMQAdminExt(3000);admin.setNamesrvAddr(namesrv);admin.setInstanceName(topic+"_admin");admin.setClientCallbackExecutorThreads(1);
        DefaultMQProducer producer=new DefaultMQProducer(topic+"_producer");producer.setNamesrvAddr(namesrv);producer.setInstanceName(topic+"_producer");producer.setClientCallbackExecutorThreads(1);producer.setRetryTimesWhenSendFailed(0);
        DefaultMQPullConsumer consumer=new DefaultMQPullConsumer(group);consumer.setNamesrvAddr(namesrv);consumer.setInstanceName(topic+"_consumer");consumer.setClientCallbackExecutorThreads(1);consumer.setConsumerPullTimeoutMillis(3000);
        boolean created=false;boolean complete=false;
        try {
            admin.start();admin.fetchBrokerRuntimeStats(broker);
            TopicConfig config=new TopicConfig(topic,1,1);admin.createAndUpdateTopicConfig(broker,config);created=true;
            SubscriptionGroupConfig subscription=new SubscriptionGroupConfig();subscription.setGroupName(group);admin.createAndUpdateSubscriptionGroupConfig(broker,subscription);
            producer.start();consumer.start();
            long deadline=System.nanoTime()+30_000_000_000L;Set<org.apache.rocketmq.common.message.MessageQueue> queues=null;
            while(System.nanoTime()<deadline){try{queues=consumer.fetchSubscribeMessageQueues(topic);if(!queues.isEmpty())break;}catch(org.apache.rocketmq.client.exception.MQClientException unavailable){if(unavailable.getResponseCode()!=17)throw unavailable;}Thread.sleep(500);}
            assertNotNull(queues);assertEquals(1,queues.size());
            var send=producer.send(new Message(topic,payload),queues.iterator().next(),5000);
            facts.put("send_status",send.getSendStatus().name());facts.put("message_id",send.getMsgId());facts.put("queue_offset",send.getQueueOffset());
            assertEquals(SendStatus.SEND_OK,send.getSendStatus());
            org.apache.rocketmq.client.consumer.PullResult pull=null;
            for(int i=0;i<10;i++){pull=consumer.pull(send.getMessageQueue(),"*",send.getQueueOffset(),1,3000);if(pull.getPullStatus()==PullStatus.FOUND)break;Thread.sleep(300);}
            assertNotNull(pull);facts.put("pull_status",pull.getPullStatus().name());
            assertEquals(PullStatus.FOUND,pull.getPullStatus());assertEquals(1,pull.getMsgFoundList().size());
            byte[] actual=pull.getMsgFoundList().get(0).getBody();Files.write(out.resolveSibling(out.getFileName()+".body"),actual,StandardOpenOption.CREATE_NEW);
            facts.put("received_sha256",Hashes.sha256(actual));facts.put("received_bytes",actual.length);
            assertArrayEquals(payload,actual);complete=true;
        } catch(Exception | AssertionError error){facts.put("exception",error.getClass().getName());throw error;}
        finally {
            consumer.shutdown();producer.shutdown();
            try {
                if(created && complete){admin.deleteTopicInBroker(Set.of(broker),topic);admin.deleteTopicInNameServer(Set.of(namesrv),topic);admin.deleteSubscriptionGroup(broker,group,false);facts.put("cleanup","EXACT_CREATED_TOPIC_AND_GROUP");}
            } catch(Exception cleanup){facts.put("cleanup_exception",cleanup.getClass().getName());throw cleanup;}
            finally{admin.shutdown();new ObjectMapper().writeValue(out.toFile(),facts);}
        }
    }
}
