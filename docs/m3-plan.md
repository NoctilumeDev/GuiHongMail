# M3 Go 发送、SMTP 闭环与取消计划 1.0

状态：`FROZEN_BEFORE_IMPLEMENTATION`。本计划只具体化 M0 的 A08–A12、F01–F11 与发送合同；不修改 M0 字节，不引入公网邮件、定时发送、发送后撤回、DKIM/域名信誉或 M5 的旧 Worker 接管与旧快照恢复。

## 状态主人和协议坐标

- Mailbox 在一个本地事务中冻结 Draft 为不可变 `SendIntent`、规范 payload hash、发送 MIME 对象、envelope recipients、sender、幂等 receipt、SENT 成员视图和 Outbox。`Idempotency-Key` 为 1–128 个可打印 ASCII 字符；同账户同 key 同 hash 返回原收据，异 hash 返回 409。提交回执只叫 `SUBMITTED_LOCAL`。
- Mailbox Outbox topic 固定为 `guihong.mail.send.v1`，事件包含 version、owner service、source intent、dispatch scope、raw hash/size、sender、envelope recipients 与只读内容能力；发布可重复。单批最多 20 项，正常重试间隔 1 秒。
- Delivery 消费组固定为 `guihong.delivery.v1`。它以 `source service + intent id` 幂等创建一个 `DispatchScope` 和逐 envelope recipient job；它拥有 `QUEUED/CANCELLED/STARTED`、`ever_started`、attempt、lease epoch 和结果。取消与首次领取锁定同一 scope 行。
- 受控出站下一跳默认 `127.0.0.1:12525`。确定 4xx 最多 3 次总 attempt，退避 1 秒、2 秒；确定 5xx 不重试。SMTP socket/命令/会话总超时 10 秒；lease 30 秒。发送 DATA 终止符后最终响应丢失即 `UNKNOWN`，只暂停关联 recipient，显式承认重复风险后才可创建新 attempt。
- Ingress 只接受 `guihong.test` 的有效启用账户，单连接最多 10 个 RCPT、raw MIME 最多 5 MiB、并发连接 2。DATA 原字节先写 ingress 专属 S3 staging 并验 hash，再在一个 ingress 事务中写 `AcceptedSpool`、recipient、幂等 source receipt 和 Outbox，成功 COMMIT 后才能回复 `250`。
- Ingress Outbox topic 固定为 `guihong.ingress.accepted.v1`，Mailbox 消费组固定为 `guihong.mailbox.import.v1`。Mailbox 按 ingress source/spool/recipient 幂等导入，逐账户建立成员事实并发出具名 ack；Ingress 只有读到持久 ack 后才把 spool 标为 GC eligible。MQ ACK 丢失或重复事件不得重复成员效果。
- 内部 HTTP、内容读取和 ack 都要求既有 bearer token、caller、source id/hash/version；loopback 不是授权。三服务仍只写自己的 schema，不跨库 JOIN 或互写。

## Web 合同

草稿编辑页开放“发送”，客户端必须生成并复用 `Idempotency-Key` 直到取得确定提交结果。页面显示本地提交收据、逐收件人状态、`UNKNOWN` 的暂停说明与“确认可能重复后重试”，以及仅在整个 scope 尚未开始时可用的“取消发送”。取消请求未取得 Delivery 持久决定时显示处理中；Worker 已领取时明确显示「邮件已进入发送流程，无法取消」。页面不得把下一跳 `250` 写成最终送达或已读。

## 预封存必过集合

| 用例 | 必须成立 | 独立事实 |
| --- | --- | --- |
| M3-01 | 同账户同 key/hash 十次只产生一个 SendIntent、一个 scope；同 key 异正文 409 | Mailbox HTTP、SQL、receipt、Delivery SQL |
| M3-02 | Draft 冻结后的修改不改变发送快照；MIME/raw hash/附件与 envelope 固定 | Draft/intent SQL、S3 原字节、解析读回 |
| M3-03 | BCC 在 sender 已发送视图可见，但不出现在给 To/CC/BCC 的可见头；envelope 仍含全部收件人 | raw MIME、envelope、双账户 API |
| M3-04 | Mailbox COMMIT 后、MQ 发布前中断，恢复后 Outbox 发布；重复事件只创建一个逻辑 scope/job 集合 | Outbox SQL、MQ key、Delivery SQL |
| M3-05 | Alice→Bob 与 Bob 回复 Alice 真实经过 Delivery SMTP→Ingress spool→MQ→Mailbox import/ack；中文、附件、reply headers 与 raw hash 保持 | SMTP transcript、三库 SQL、三桶 S3、两账户 API |
| M3-06 | 未知本地域、禁用账户、域外 relay、RCPT/大小超限在承担责任前拒绝且无 spool/成员副作用 | 原始 SMTP、Ingress SQL、Mailbox SQL |
| M3-07 | S3 PUT/Ingress COMMIT 失败不回 `250`；成功路径只在 raw 与 spool/outbox 已耐久后回 `250` | S3、COMMIT 故障触达、SMTP transcript、SQL |
| M3-08 | Mailbox 暂停或 MQ ACK 丢失时 spool 保留；恢复及事件重放只产生一次账户成员，持久 ack 后才可清理 | Ingress/Mailbox SQL、MQ、S3 |
| M3-09 | 同次提交的接受、4xx、5xx/RCPT 拒绝逐 recipient 隔离，确定结果不互相覆盖 | 受控 next-hop transcript、attempt/job SQL |
| M3-10 | 4xx 严格在 3 次总 attempt 内按 1/2 秒退避后成功或终止；5xx 不重试 | attempt 时间、next-hop 计数、最终状态 |
| M3-11 | DATA 终止符后的最终响应丢失只把关联 recipient 置 `UNKNOWN`，不自动重投且保存最后阶段、实际 RCPT、证据摘要 | 受控 next-hop、attempt SQL、持续观察窗 |
| M3-12 | 用户明确确认重复风险的同 key 重试只创建一个新 attempt，保留原 UNKNOWN；未确认请求被拒绝 | HTTP receipt、attempt 链、next-hop 计数 |
| M3-13 | 取消先成功：`QUEUED → CANCELLED` 后无 SMTP attempt；重复取消、MQ 重放、进程重启均返回原决定且不能复活 | Delivery SQL、重启、next-hop 零连接 |
| M3-14 | Worker 先领取：`ever_started=true` 后取消明确失败，已开始 attempt 保留 | 并发 API、Delivery SQL、SMTP transcript |
| M3-15 | 取消与首次领取真实数据库并发，恰好一方取得资格；重复运行不要求固定赢家 | 并发屏障、事务结果、SQL、next-hop |
| M3-16 | Web 真实展示 `SUBMITTED_LOCAL`、逐收件人结果、UNKNOWN 暂停/显式重试和取消两种裁决，不泄露 BCC 或前账户迟到响应 | Edge DOM/网络/截图、API |
| M3-17 | 三服务重启后 SendIntent、spool、scope、attempt、ack 与成员状态一致，Outbox 重放不增加逻辑效果 | 重启前后 SQL/API/S3/MQ |
| M3-18 | 全拓扑资源窗不少于 12 个 5 秒样本，宿主/容器/应用停止线维持 M1 合同，drain 后不接新写且 owned 清理闭合 | resource guard、身份/端口、Docker 标签 |

## 负控与停止条件

最终候选必须另跑错 source/hash、错 Evidence 绑定与缺证据，得到声明的非 PASS。正常业务 `UNKNOWN` 可以使相应业务断言 PASS；资格证据缺失的 `UNKNOWN/PENDING/INCONCLUSIVE` 不能过门。

任何结果若需要放宽 14 GiB 宿主停止线、容器 10% 内存余量、16 PID 余量、5 MiB/10 RCPT 限制、三次 attempt 上限、UNKNOWN 暂停、四个取消见证或 M0 安全边界，立即保留首败并停止 M3。代表性故障已经覆盖不同不变量；不追加无界调度排列。
