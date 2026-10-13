# M3 Go 发送、SMTP 闭环与取消计划 1.1 修订

状态：`FROZEN_MINIMAL_AMENDMENT`。本修订保留 [M3 计划 1.0](m3-plan.md)的 18 个必过用例、业务状态机、失败机制和资源停止线，只版本化 RocketMQ 消费组的线缆标识与创建责任。

## 首败与修订理由

精确 source `2134ffbe8c5ea85c72776946c4d4d5115f8df45f` 首次真实启动时，Mailbox 已创建两个 Topic，随后 `rocketmq-client-go/v2@v2.1.2` 在消费者启动前拒绝 `guihong.mailbox.import.v1`：该客户端只允许消费组匹配 `^[%|a-zA-Z0-9_-]+$`。失败发生在消息消费前，原应用日志和失败候选提交保留，不回写为成功，也不把它扩大解释为 RocketMQ 5.5.0 与 Go 不兼容。

## 版本化坐标

| 逻辑职责 | 1.0 线缆标识 | 1.1 线缆标识 |
| --- | --- | --- |
| Ingress 导入到 Mailbox | `guihong.mailbox.import.v1` | `guihong_mailbox_import_v1` |
| Mailbox 发送到 Delivery | `guihong.delivery.v1` | `guihong_delivery_v1` |

Broker 继续保持 `autoCreateSubscriptionGroup=false`。部署准备只对归属当前 lab 的唯一运行 Broker，通过官方 `mqadmin updateSubGroup` 显式、幂等创建上述两个固定组，并保留命令日志；业务进程不取得 Docker 或 Broker 管理权限。Topic、事件版本、幂等键、消息语义和全部验收断言不变。
