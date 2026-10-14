# M3 Go 发送、SMTP 闭环与取消计划 1.1 修订

状态：`FROZEN_MINIMAL_AMENDMENT`。本修订保留 [M3 计划 1.0](m3-plan.md)的 18 个必过用例、业务状态机、失败机制和资源停止线，只版本化 RocketMQ Topic/消费组的线缆标识与创建责任。

## 首败与修订理由

精确 source `2134ffbe8c5ea85c72776946c4d4d5115f8df45f` 首次真实启动时，`rocketmq-client-go/v2@v2.1.2` 在消费者启动前拒绝 `guihong.mailbox.import.v1`。source `ee48a6158311cb61778a95ddab8f9a1a4b66c11e` 增加路由读回后又证明：Go 管理客户端把带点号 Topic 的 Broker 拒绝误报为创建成功，而官方 `mqadmin` 明确返回同一非法字符错误。RocketMQ 5.5.0 对 Topic 和消费组都只允许匹配 `^[%|a-zA-Z0-9_-]+$`。失败均发生在业务消息消费前，原应用日志和失败候选提交保留，不回写为成功，也不把它扩大解释为 RocketMQ 5.5.0 与 Go 不兼容。

## 版本化坐标

| 逻辑职责 | 1.0 线缆标识 | 1.1 线缆标识 |
| --- | --- | --- |
| Mailbox 发送 Topic | `guihong.mail.send.v1` | `guihong_mail_send_v1` |
| Ingress 接纳 Topic | `guihong.ingress.accepted.v1` | `guihong_ingress_accepted_v1` |
| Ingress 导入到 Mailbox | `guihong.mailbox.import.v1` | `guihong_mailbox_import_v1` |
| Mailbox 发送到 Delivery | `guihong.delivery.v1` | `guihong_delivery_v1` |

Broker 继续保持 `autoCreateTopicEnable=false` 与 `autoCreateSubscriptionGroup=false`。部署准备只对归属当前 lab 的唯一运行 Broker，通过官方 `mqadmin updateTopic` / `topicRoute` 与 `updateSubGroup` 显式、幂等创建并读回上述固定坐标，保留命令日志；业务进程不取得 Docker 或 Broker 管理权限。事件版本、幂等键、消息语义和全部验收断言不变。
