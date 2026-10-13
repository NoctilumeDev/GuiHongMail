package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/NoctilumeDev/GuiHongMail/internal/mqprobe"
	"github.com/apache/rocketmq-client-go/v2"
	"github.com/apache/rocketmq-client-go/v2/admin"
	"github.com/apache/rocketmq-client-go/v2/consumer"
	"github.com/apache/rocketmq-client-go/v2/primitive"
	"github.com/apache/rocketmq-client-go/v2/producer"
)

const hashProperty = "guihong-sha256"

type commonFlags struct {
	binding mqprobe.Binding
	namesrv string
	broker  string
	out     string
	timeout time.Duration
}

type sendEvidence struct {
	Key         string `json:"key"`
	BodySHA256  string `json:"body_sha256"`
	MessageID   string `json:"message_id"`
	OffsetMsgID string `json:"offset_message_id"`
	QueueOffset int64  `json:"queue_offset"`
	SendStatus  string `json:"send_status"`
}

type evidence struct {
	Schema        string            `json:"schema"`
	Command       string            `json:"command"`
	CapturedAt    string            `json:"captured_at"`
	Binding       mqprobe.Binding   `json:"binding"`
	Nameserver    string            `json:"nameserver"`
	Broker        string            `json:"broker"`
	TopicPresent  bool              `json:"topic_present,omitempty"`
	GroupPresent  bool              `json:"group_present,omitempty"`
	Topics        []string          `json:"owned_topics,omitempty"`
	Groups        []string          `json:"owned_groups,omitempty"`
	DeletedTopics []string          `json:"deleted_topics,omitempty"`
	Sends         []sendEvidence    `json:"sends,omitempty"`
	Attempts      []mqprobe.Attempt `json:"attempts,omitempty"`
	Facts         []mqprobe.Fact    `json:"facts,omitempty"`
	Complete      bool              `json:"complete"`
	StartedAt     string            `json:"started_at,omitempty"`
	FinishedAt    string            `json:"finished_at,omitempty"`
}

func main() {
	if len(os.Args) < 2 {
		fatal(errors.New("command required: prepare, consume, inspect, or delete-topic"))
	}
	var err error
	switch os.Args[1] {
	case "prepare":
		err = runPrepare(os.Args[2:])
	case "consume":
		err = runConsume(os.Args[2:])
	case "inspect":
		err = runInspect(os.Args[2:])
	case "delete-topic":
		err = runDeleteTopic(os.Args[2:])
	default:
		err = fmt.Errorf("unknown command %q", os.Args[1])
	}
	if err != nil {
		fatal(err)
	}
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "mqprobe:", err)
	os.Exit(1)
}

func parseCommon(command string, args []string) (commonFlags, error) {
	flags := flag.NewFlagSet(command, flag.ContinueOnError)
	flags.SetOutput(os.Stderr)
	var cfg commonFlags
	flags.StringVar(&cfg.binding.Run, "run", "", "owned run identity")
	flags.StringVar(&cfg.binding.Topic, "topic", "", "owned topic")
	flags.StringVar(&cfg.binding.Group, "group", "", "owned subscription group")
	flags.StringVar(&cfg.namesrv, "namesrv", "127.0.0.1:19876", "NameServer address")
	flags.StringVar(&cfg.broker, "broker", "127.0.0.1:20911", "Broker address")
	flags.StringVar(&cfg.out, "out", "", "new JSON evidence file")
	flags.DurationVar(&cfg.timeout, "timeout", 90*time.Second, "bounded operation timeout")
	if err := flags.Parse(args); err != nil {
		return cfg, err
	}
	if flags.NArg() != 0 {
		return cfg, fmt.Errorf("unexpected positional arguments")
	}
	if err := mqprobe.ValidateBinding(cfg.binding); err != nil {
		return cfg, err
	}
	if cfg.out == "" || cfg.namesrv == "" || cfg.broker == "" {
		return cfg, fmt.Errorf("out, namesrv, and broker are required")
	}
	if cfg.timeout < 5*time.Second || cfg.timeout > 3*time.Minute {
		return cfg, fmt.Errorf("timeout outside allowed range")
	}
	return cfg, nil
}

func newAdmin(namesrv string) (admin.Admin, error) {
	client, err := admin.NewAdmin(admin.WithResolver(primitive.NewPassthroughResolver([]string{namesrv})))
	if err != nil {
		return nil, err
	}
	return client, nil
}

func runPrepare(args []string) error {
	cfg, err := parseCommon("prepare", args)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), cfg.timeout)
	defer cancel()
	api, err := newAdmin(cfg.namesrv)
	if err != nil {
		return err
	}
	defer api.Close()
	if err := api.CreateTopic(ctx, admin.WithTopicCreate(cfg.binding.Topic), admin.WithBrokerAddrCreate(cfg.broker), admin.WithReadQueueNums(1), admin.WithWriteQueueNums(1)); err != nil {
		return fmt.Errorf("create topic: %w", err)
	}
	topics, err := api.FetchAllTopicList(ctx)
	if err != nil {
		return fmt.Errorf("read topic list: %w", err)
	}
	if !contains(topics.TopicList, cfg.binding.Topic) {
		return fmt.Errorf("created topic absent from readback")
	}

	body, _ := mqprobe.Payload(cfg.binding.Run, "stored-before-restart")
	key, _ := mqprobe.Key(cfg.binding.Run, "stored-before-restart")
	sent, err := send(ctx, cfg, key, body)
	if err != nil {
		return err
	}
	return writeNewJSON(cfg.out, evidence{
		Schema: "GuiHongM1GProbe/1.0", Command: "prepare", CapturedAt: now(), Binding: cfg.binding,
		Nameserver: cfg.namesrv, Broker: cfg.broker, TopicPresent: true, Topics: []string{cfg.binding.Topic},
		Sends: []sendEvidence{sent}, Complete: true,
	})
}

func runConsume(args []string) error {
	flags := flag.NewFlagSet("consume", flag.ContinueOnError)
	flags.SetOutput(os.Stderr)
	var cfg commonFlags
	var minLive time.Duration
	flags.StringVar(&cfg.binding.Run, "run", "", "owned run identity")
	flags.StringVar(&cfg.binding.Topic, "topic", "", "owned topic")
	flags.StringVar(&cfg.binding.Group, "group", "", "owned subscription group")
	flags.StringVar(&cfg.namesrv, "namesrv", "127.0.0.1:19876", "NameServer address")
	flags.StringVar(&cfg.broker, "broker", "127.0.0.1:20911", "Broker address")
	flags.StringVar(&cfg.out, "out", "", "new JSON evidence file")
	flags.DurationVar(&cfg.timeout, "timeout", 90*time.Second, "bounded operation timeout")
	flags.DurationVar(&minLive, "min-live", 35*time.Second, "minimum live observation window")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if flags.NArg() != 0 || cfg.out == "" || cfg.namesrv == "" || cfg.broker == "" {
		return fmt.Errorf("invalid consume arguments")
	}
	if err := mqprobe.ValidateBinding(cfg.binding); err != nil {
		return err
	}
	if cfg.timeout < 5*time.Second || cfg.timeout > 3*time.Minute || minLive < 30*time.Second || minLive >= cfg.timeout {
		return fmt.Errorf("invalid timeout or min-live")
	}

	started := time.Now().UTC()
	bodyA, _ := mqprobe.Payload(cfg.binding.Run, "stored-before-restart")
	bodyB, _ := mqprobe.Payload(cfg.binding.Run, "sent-after-consumer")
	keyA, _ := mqprobe.Key(cfg.binding.Run, "stored-before-restart")
	keyB, _ := mqprobe.Key(cfg.binding.Run, "sent-after-consumer")
	ledger, err := mqprobe.NewLedger(map[string]string{keyA: mqprobe.SHA256(bodyA), keyB: mqprobe.SHA256(bodyB)}, keyA)
	if err != nil {
		return err
	}

	client, err := rocketmq.NewPushConsumer(
		consumer.WithGroupName(cfg.binding.Group),
		consumer.WithInstance(cfg.binding.Run+"-consumer"),
		consumer.WithNsResolver(primitive.NewPassthroughResolver([]string{cfg.namesrv})),
		consumer.WithConsumerModel(consumer.Clustering),
		consumer.WithConsumeFromWhere(consumer.ConsumeFromFirstOffset),
		consumer.WithConsumeGoroutineNums(1),
		consumer.WithConsumeMessageBatchMaxSize(1),
		consumer.WithPullBatchSize(1),
	)
	if err != nil {
		return fmt.Errorf("create consumer: %w", err)
	}
	if err := client.Subscribe(cfg.binding.Topic, consumer.MessageSelector{}, func(ctx context.Context, messages ...*primitive.MessageExt) (consumer.ConsumeResult, error) {
		if concurrent, ok := primitive.GetConcurrentlyCtx(ctx); ok {
			concurrent.DelayLevelWhenNextConsume = 1
		}
		retry := false
		for _, message := range messages {
			if ledger.Observe(message.GetKeys(), message.MsgId, message.Body, message.ReconsumeTimes) {
				retry = true
			}
		}
		if retry {
			return consumer.ConsumeRetryLater, nil
		}
		return consumer.ConsumeSuccess, nil
	}); err != nil {
		return fmt.Errorf("subscribe: %w", err)
	}
	if err := client.Start(); err != nil {
		return fmt.Errorf("start consumer: %w", err)
	}
	defer client.Shutdown()

	ctx, cancel := context.WithTimeout(context.Background(), cfg.timeout)
	defer cancel()
	sentB, err := send(ctx, cfg, keyB, bodyB)
	if err != nil {
		return err
	}
	ticker := time.NewTicker(200 * time.Millisecond)
	defer ticker.Stop()
	for {
		if ledger.Complete() && time.Since(started) >= minLive {
			break
		}
		select {
		case <-ctx.Done():
			return fmt.Errorf("consume outcome incomplete before deadline: %w", ctx.Err())
		case <-ticker.C:
		}
	}
	if err := client.Shutdown(); err != nil {
		return fmt.Errorf("shutdown consumer: %w", err)
	}
	attempts, facts := ledger.Snapshot()
	sort.Slice(facts, func(i, j int) bool { return facts[i].Key < facts[j].Key })
	return writeNewJSON(cfg.out, evidence{
		Schema: "GuiHongM1GProbe/1.0", Command: "consume", CapturedAt: now(), Binding: cfg.binding,
		Nameserver: cfg.namesrv, Broker: cfg.broker, Sends: []sendEvidence{sentB}, Attempts: attempts,
		Facts: facts, Complete: ledger.Complete(), StartedAt: started.Format(time.RFC3339Nano), FinishedAt: now(),
	})
}

func runInspect(args []string) error {
	cfg, err := parseCommon("inspect", args)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), cfg.timeout)
	defer cancel()
	api, err := newAdmin(cfg.namesrv)
	if err != nil {
		return err
	}
	defer api.Close()
	topics, err := api.FetchAllTopicList(ctx)
	if err != nil {
		return fmt.Errorf("read topic list: %w", err)
	}
	groups, err := api.GetAllSubscriptionGroup(ctx, cfg.broker, 5*time.Second)
	if err != nil {
		return fmt.Errorf("read subscription groups: %w", err)
	}
	ownedTopics := ownedTopics(topics.TopicList, cfg.binding)
	ownedGroups := make([]string, 0)
	for group := range groups.SubscriptionGroupTable {
		if strings.HasPrefix(group, cfg.binding.Run) {
			ownedGroups = append(ownedGroups, group)
		}
	}
	sort.Strings(ownedGroups)
	return writeNewJSON(cfg.out, evidence{
		Schema: "GuiHongM1GProbe/1.0", Command: "inspect", CapturedAt: now(), Binding: cfg.binding,
		Nameserver: cfg.namesrv, Broker: cfg.broker, TopicPresent: contains(topics.TopicList, cfg.binding.Topic),
		GroupPresent: contains(ownedGroups, cfg.binding.Group), Topics: ownedTopics, Groups: ownedGroups, Complete: true,
	})
}

func runDeleteTopic(args []string) error {
	cfg, err := parseCommon("delete-topic", args)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), cfg.timeout)
	defer cancel()
	api, err := newAdmin(cfg.namesrv)
	if err != nil {
		return err
	}
	defer api.Close()
	topics, err := api.FetchAllTopicList(ctx)
	if err != nil {
		return fmt.Errorf("read owned topics before deletion: %w", err)
	}
	owned := ownedTopics(topics.TopicList, cfg.binding)
	for _, topic := range owned {
		if err := api.DeleteTopic(ctx, admin.WithTopicDelete(topic), admin.WithBrokerAddrDelete(cfg.broker), admin.WithNameSrvAddr([]string{cfg.namesrv})); err != nil {
			return fmt.Errorf("delete owned topic %q: %w", topic, err)
		}
	}
	deadline := time.Now().Add(10 * time.Second)
	for {
		topics, readErr := api.FetchAllTopicList(ctx)
		if readErr != nil {
			return fmt.Errorf("topic deletion readback: %w", readErr)
		}
		if len(ownedTopics(topics.TopicList, cfg.binding)) == 0 {
			return writeNewJSON(cfg.out, evidence{
				Schema: "GuiHongM1GProbe/1.0", Command: "delete-topic", CapturedAt: now(), Binding: cfg.binding,
				Nameserver: cfg.namesrv, Broker: cfg.broker, DeletedTopics: owned, Complete: true,
			})
		}
		if time.Now().After(deadline) {
			return fmt.Errorf("topic still present after deletion")
		}
		time.Sleep(250 * time.Millisecond)
	}
}

func send(ctx context.Context, cfg commonFlags, key string, body []byte) (sendEvidence, error) {
	client, err := rocketmq.NewProducer(
		producer.WithGroupName(cfg.binding.Run+"-producer"),
		producer.WithInstanceName(cfg.binding.Run+"-producer"),
		producer.WithNsResolver(primitive.NewPassthroughResolver([]string{cfg.namesrv})),
		producer.WithRetry(0),
	)
	if err != nil {
		return sendEvidence{}, fmt.Errorf("create producer: %w", err)
	}
	if err := client.Start(); err != nil {
		return sendEvidence{}, fmt.Errorf("start producer: %w", err)
	}
	defer client.Shutdown()
	message := primitive.NewMessage(cfg.binding.Topic, body).WithKeys([]string{key})
	message.WithProperty(hashProperty, mqprobe.SHA256(body))
	result, err := client.SendSync(ctx, message)
	if err != nil {
		return sendEvidence{}, fmt.Errorf("send %s: %w", key, err)
	}
	if result.Status != primitive.SendOK {
		return sendEvidence{}, fmt.Errorf("broker returned send status %v", result.Status)
	}
	return sendEvidence{
		Key: key, BodySHA256: mqprobe.SHA256(body), MessageID: result.MsgID, OffsetMsgID: result.OffsetMsgID,
		QueueOffset: result.QueueOffset, SendStatus: fmt.Sprint(result.Status),
	}, nil
}

func writeNewJSON(path string, value any) error {
	absolute, err := filepath.Abs(path)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(absolute), 0o755); err != nil {
		return err
	}
	file, err := os.OpenFile(absolute, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return fmt.Errorf("create evidence: %w", err)
	}
	encoder := json.NewEncoder(file)
	encoder.SetEscapeHTML(false)
	encoder.SetIndent("", "  ")
	encodeErr := encoder.Encode(value)
	closeErr := file.Close()
	return errors.Join(encodeErr, closeErr)
}

func contains(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

func ownedTopics(values []string, binding mqprobe.Binding) []string {
	internalRetry := "%RETRY%" + binding.Group
	internalDLQ := "%DLQ%" + binding.Group
	filtered := make([]string, 0)
	for _, value := range values {
		if strings.HasPrefix(value, binding.Run) || value == internalRetry || value == internalDLQ {
			filtered = append(filtered, value)
		}
	}
	sort.Strings(filtered)
	return filtered
}

func now() string {
	return time.Now().UTC().Format(time.RFC3339Nano)
}
