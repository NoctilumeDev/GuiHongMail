# M1G · Go 与当前 RocketMQ 拓扑兼容预检 1.0

**状态：`SEALED_BEFORE_OBSERVATION / NOT_YET_RUN` · 2026-10-13。** 本门只裁决是否允许开始 Go 三服务的 M1 重建，不授予 M1、M2、邮件发送或产品资格。运行坐标必须绑定干净源码、构建摘要、fresh owned lab、工具链和下列有限分母。

## 固定问题

在不增加 RocketMQ Proxy、不修改 Broker 功能语义、不放宽 M0 资源停止线的前提下，Apache `rocketmq-client-go/v2` Remoting 客户端能否与当前 RocketMQ 5.5.0 单机 NameServer + Broker 完成归鸿需要的普通持久异步消息最小生命周期？

官方 RocketMQ 5.x Go gRPC SDK 需要至少 5.0 服务端并启用 Proxy；它不属于当前预检拓扑。预检选择官方 Apache Remoting 客户端 `v2.1.2`，tag 解析到 commit `7eedaf948c6076c716972724782f4837e1f9caa6`。选中不表示兼容，只有下列真实观察可回答。

## 有限必过项

| ID | 真实观察 | 必需源事实 |
| --- | --- | --- |
| M1G-01 | 官方 Go `1.27.2 windows/amd64`、ZIP 完整摘要、客户端 module/version/commit 与构建产物绑定同一干净源码 | `go version`、下载元数据、`go.mod/go.sum`、binary hash、Git SHA |
| M1G-02 | Go admin 在关闭自动建 Topic 的实际 Broker 上创建具名 Topic，读回存在 | admin API、Broker/NameServer topic 列表 |
| M1G-03 | Go producer 同步发送两条具名普通消息，Broker 接受身份与原 payload hash 可绑定 | SendResult、消息 key、原字节 SHA-256 |
| M1G-04 | 第一条在消费者启动前写入，Broker 正常重启后仍由新 consumer 取得 | owned 启停、容器身份、消费消息 ID/hash |
| M1G-05 | 处理函数第一次明确返回 retry，后续取得同一业务 key/hash 并成功确认；重复交付不伪造第二个业务事实 | callback 次数/结果、key/hash、受控业务幂等账册 |
| M1G-06 | 运行拓扑只有 MySQL、SeaweedFS、NameServer、Broker 与 Go 探针，没有 Proxy 或额外 Java 应用进程 | Docker labels/inspect、进程身份 |
| M1G-07 | consumer/producer/admin 正常关闭后，精确 Topic 与 subscription group 被清除并独立读回不存在 | admin 列表、具名清理命令与退出码、再次读回 |
| M1G-08 | 至少连续 6 个 5 秒样本同时观察四个依赖和 Go 探针；宿主低于 14 GiB、容器内存余量至少 10%、PID 余量至少 16、无 OOM，探针 RSS 不超过原 Java 应用 384 MiB 停止线 | watchdog JSONL、Docker stats/inspect、Windows RSS |
| M1G-09 | 错 payload hash 或错 run/topic/group 绑定不能得到 PASS | VeriTrail 负向控制 bundle |
| M1G-10 | fresh lab 停止且只清理该 owner 的容器、网络、数据卷和临时研究目录；失败原件与标准 Evidence 保留 | owner labels、清理前后清单、bundle/hash |

## 允许的故障与顺序

唯一主动故障是 M1G-04 的一次正常 Broker 重启。消费 retry 是客户端回调的显式业务结果，不通过杀进程制造。不得在本门增加网络代理、丢包器、磁盘破坏、并发压力、Proxy 或第三种 MQ；这些属于后续 M1/M5 或消息队列替代评估。

执行顺序固定为：fresh lab → watchdog → 建 Topic → 发持久消息 → Broker 重启 → consumer retry/成功 → 第二条正常消息 → 关闭客户端 → 清 Topic/group → 独立读回 → 停止并清理 owned lab。首个失败保留，最小修复后必须重复同一顺序和断言。

## 资源与退出

沿用 M1 资源合同 1.1 的 MySQL 512 MiB、SeaweedFS 256 MiB、NameServer 256 MiB、Broker 512 MiB、Broker PID 192 及其他具名 PID 上限。宿主总占用连续三次超过 14 GiB、任一容器余量不合格、OOM、观察失真或未知 owner 时立即停止该实验。

PASS 只升级为 `GO_RUNTIME_PREFLIGHT_PASS / M1G_IMPLEMENTATION_AUTHORIZED`。任何消息生命周期、清理或资源项失败即为 `GO_RUNTIME_PREFLIGHT_BLOCKED`；不得以“Go 更轻”推断成功，也不得自动改用 RabbitMQ。所有公开状态在新 Go M1 exact-main 资格前仍指向 Java main。
