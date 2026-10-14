package platform

import (
	"context"
	"fmt"
	"time"

	rocketmq "github.com/apache/rocketmq-client-go/v2"
	"github.com/apache/rocketmq-client-go/v2/admin"
	"github.com/apache/rocketmq-client-go/v2/consumer"
	"github.com/apache/rocketmq-client-go/v2/primitive"
	"github.com/apache/rocketmq-client-go/v2/producer"
)

type Publisher struct {
	client rocketmq.Producer
}

func NewPublisher(runtime *Runtime, group string) (*Publisher, error) {
	client, err := rocketmq.NewProducer(
		producer.WithGroupName(group),
		producer.WithInstanceName(group+"-"+runtime.Witness.Generation()),
		producer.WithNsResolver(primitive.NewPassthroughResolver([]string{runtime.Config.NameServer})),
		producer.WithRetry(0),
	)
	if err != nil {
		return nil, err
	}
	if err := client.Start(); err != nil {
		return nil, err
	}
	return &Publisher{client: client}, nil
}

func (publisher *Publisher) Close() error { return publisher.client.Shutdown() }

func (publisher *Publisher) Send(ctx context.Context, topic, key string, body []byte) (string, error) {
	message := primitive.NewMessage(topic, body).WithKeys([]string{key})
	message.WithProperty("guihong-body-sha256", SHA256(body))
	result, err := publisher.client.SendSync(ctx, message)
	if err != nil {
		return "", err
	}
	if result.Status != primitive.SendOK {
		return "", fmt.Errorf("broker send status %v", result.Status)
	}
	return result.MsgID, nil
}

func EnsureTopic(ctx context.Context, runtime *Runtime, topic string) error {
	api, err := admin.NewAdmin(admin.WithResolver(primitive.NewPassthroughResolver([]string{runtime.Config.NameServer})))
	if err != nil {
		return err
	}
	defer api.Close()
	if err := api.CreateTopic(ctx, admin.WithTopicCreate(topic), admin.WithBrokerAddrCreate(runtime.Config.Broker), admin.WithReadQueueNums(1), admin.WithWriteQueueNums(1)); err != nil {
		// RocketMQ reports an error when the exact topic already exists. A readback
		// is the authority for treating that case as success.
		topics, readErr := api.FetchAllTopicList(ctx)
		if readErr != nil {
			return err
		}
		found := false
		for _, existing := range topics.TopicList {
			if existing == topic {
				found = true
				break
			}
		}
		if !found {
			return err
		}
	}
	var lastErr error
	for {
		queues, routeErr := api.FetchPublishMessageQueues(ctx, topic)
		if routeErr == nil && len(queues) > 0 {
			return nil
		}
		if routeErr != nil {
			lastErr = routeErr
		} else {
			lastErr = fmt.Errorf("no publish queue returned")
		}
		select {
		case <-ctx.Done():
			return fmt.Errorf("topic %s route did not become visible: %w (last route error: %v)", topic, ctx.Err(), lastErr)
		case <-time.After(100 * time.Millisecond):
		}
	}
}

func Consume(ctx context.Context, runtime *Runtime, group, topic string, handle func(context.Context, string, []byte) error) error {
	client, err := rocketmq.NewPushConsumer(
		consumer.WithGroupName(group),
		consumer.WithInstance(group+"-"+runtime.Witness.Generation()),
		consumer.WithNsResolver(primitive.NewPassthroughResolver([]string{runtime.Config.NameServer})),
		consumer.WithConsumerModel(consumer.Clustering),
		consumer.WithConsumeFromWhere(consumer.ConsumeFromFirstOffset),
		consumer.WithConsumeGoroutineNums(1),
		consumer.WithConsumeMessageBatchMaxSize(1),
		consumer.WithPullBatchSize(1),
	)
	if err != nil {
		return err
	}
	if err := client.Subscribe(topic, consumer.MessageSelector{}, func(callback context.Context, messages ...*primitive.MessageExt) (consumer.ConsumeResult, error) {
		for _, message := range messages {
			if err := handle(callback, message.GetKeys(), message.Body); err != nil {
				if concurrent, ok := primitive.GetConcurrentlyCtx(callback); ok {
					concurrent.DelayLevelWhenNextConsume = 1
				}
				return consumer.ConsumeRetryLater, nil
			}
		}
		return consumer.ConsumeSuccess, nil
	}); err != nil {
		return err
	}
	if err := client.Start(); err != nil {
		return err
	}
	defer client.Shutdown()
	<-ctx.Done()
	return nil
}
