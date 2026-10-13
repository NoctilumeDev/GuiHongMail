# M1G · Go / RocketMQ 兼容预检证据

**结论：`GO_RUNTIME_PREFLIGHT_PASS / M1G_IMPLEMENTATION_AUTHORIZED`。** 该结论只允许开始 Go 版 M1 重建，不授予 Go M1、M2 或邮件产品资格；Java main `51fe46533cc45d7ef5d010db6803165de0780905` 的 M1 资格继续作为回退基线。

## 精确坐标

| 项目 | 事实 |
| --- | --- |
| source | `e33e80b6c97116057184ba04b0b50f188095381e`，clean |
| Go | `go1.27.2 windows/amd64`；归档 SHA-256 `1314008898bd40df77af4b014f777f08873dbdfbcd3d92308728ee03304fe04f` |
| client | `github.com/apache/rocketmq-client-go/v2@v2.1.2`；tag commit `7eedaf948c6076c716972724782f4837e1f9caa6` |
| probe binary | SHA-256 `abf264965d1dec07c4dca46205e5e920df93257312d6a16525de16bdc2cc41ee` |
| server | RocketMQ `5.5.0` NameServer + Broker；无 Proxy |
| PASS run | `guihong-m1g-3410087aaf4b4a9aaf590cb20c7c3a50`，Plan `9d5416aab2ce793cd4343837e6a1e6b3bce3dd4f455497d631630d5f0348490e` |
| PASS bundle manifest | SHA-256 `05b5ece025c03459bbc77b2ad4f4bb312f8490e6d46229f00a9bc0a5b00d2daa`；5/5 文件独立核验 |
| wrong-hash control | `guihong-m1g-0d3631cb403c4802aec7106c226c3e37`，`COMPLETED / FAIL`；仅 `fact-hashes` 失败 |
| control bundle manifest | SHA-256 `2d01f607f43a76f7e57511996a0366b8cd23a0b2811dd7847647f7d52300e5e1`；5/5 文件独立核验 |

原始 Plan、Evidence、Bundle、日志与此前非 PASS run 保留在本机 ignored `artifacts/local/<run>`；它们包含本机绝对构建路径，不作为公共仓库资产。此文只发布可复核的摘要和摘要坐标，不替代原件。

## 真实观察

- Go admin 在关闭自动建 Topic 的 Broker 上创建并读回具名 Topic；第一条消息在 consumer 启动前同步持久发送，Broker 正常重启后仍被取得。
- consumer 对第一条消息明确返回一次 `RETRY`，随后以同一业务 key、payload SHA-256 成功；consumer 启动后发送的第二条消息正常成功。共 3 次 callback、2 个幂等业务事实。
- producer、consumer 与 admin 正常关闭；具名 group、主 Topic 和自动生成的 `%RETRY%` Topic 被精确删除，独立读回 topic/group 均不存在。
- 运行拓扑只有 MySQL、SeaweedFS、RocketMQ NameServer、Broker 与 Go 探针；没有 Proxy 或额外 Java 应用进程。
- 7 个完整资源样本全部无停止：宿主峰值 12.609 GiB；Go 探针 RSS 峰值 14.4 MiB；Broker 峰值 232.2 MiB、139 PIDs、最小 PID 余量 53；NameServer 峰值 108 MiB。所有容器内存余量至少 10%、PID 余量至少 16、无 OOM。
- 本 run 的容器、卷、网络、private lab 与临时客户端研究目录均已清除；证据原件与首败保留。

VeriTrail Core `0.13.0` 对真实 run 的 49 条规则全部 PASS；错哈希 control 为 48 PASS / 1 FAIL，证明错误消费哈希不能取得兼容资格。

## 保留的非 PASS

- `guihong-m1g-c321b3f324264e328f250df505ca8f68`：Seal 前 `COLLECTOR_SETUP_FAILURE`，离线单模块 lookup 被禁；lab 未启动。
- `guihong-m1g-d2f76d62994649aeb13949383543c1be`：真实生命周期完成，清理后的 false JSON 字段被省略，采集器 `ERROR / PENDING`。
- `guihong-m1g-81bf6bd01a0b40b8a753776227b506cf`：7 个合格样本与生命周期完成后，正常进程退出被误判为 PID 变化，`ERROR / PENDING`。

这些历史身份不由最终 PASS 覆盖。后续 Go M1 必须重建三个服务、重新验证三类存储与完整资源拓扑，并取得自己的 PR/CI、exact-main 与独立验迹资格。
