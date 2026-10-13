# 服务边界、持久化与协议交接合同 0.1

**M0 draft — NOT IMPLEMENTED**。仅约束状态主人及通信，不冻结 Java package 名称和接口字段。

## 三个状态所有者

`mailbox-service`：账户/凭证摘要/会话、Draft、不可变提交快照、MessageContent、MailboxEntry（每人独立 folder/unread/category）、用户自定义分类、显式匹配规则、分类建议/反馈/模型版本、查询/搜索投影、`SendIntent` 和 outbox。前端只有这里的 Web API。此服务接受内部收件导入时必须验证来源、幂等及完整内容；不能把外部 gateway 的“收件成功”反推为本账户可见成功。

`smtp-ingress`：受控 SMTP server，仅接受 allowlist local domain/有效收件人（或额外已授权的 submission）。成功 DATA 之后的 `AcceptedSpool` 和 `IngressEvent` 属于本服务，在传给 mailbox 确认完成前不可释放；失败不能返回成功。不要提供匿名外部 relay，不接受任意收件目的域作为中继。真实网络监听默认 loopback、显式高端口，公网地址需要 E1 新授权。

`delivery-worker`：每个 envelope recipient 的 `DeliveryJob/Attempt/Lease/Outcome`，可用真实 SMTP client 到受控下一跳；`UNKNOWN` 保留为独立状态。它不能重写 MailboxEntry 或源 MIME。客户端提交成功后，发件人看到的是 `SendIntent` 与其只读投递投影，不是直接调用外部 SMTP 的乐观成功。

## 事件与主数据的通路

```text
Browser -- authenticated API --> mailbox-service
     drafts / immutable SendIntent / owner Outbox
                                |
                                v
                       RocketMQ (event)
                                |
                                v
                        delivery-worker
                           SMTP client
                                |
                                v
                    SMTP next hop / local ingress
                                |
                                v
                 smtp-ingress durable spool
                           owner Outbox
                                |
                                v
                      mailbox-service
                    import/visibility commit
                                |
                     import acknowledgement
                                v
                     ingress spool GC-eligible
```

**不能跨服务的边界：** schema 写、MySQL JOIN、共有业务 Entity、共用 JPA/Mappers、反向同步调用环、无归属的全局 `mail_status`、共享可变 MIME、跨服务使用同一 MinIO Root 密钥。`platform-common` 仅为请求相关 ID、脱敏日志、技术错误模型、契约校验工具，不承载业务状态机。分类算法只在 Mailbox 内经确定性输入/输出合同提供可替换实现，不设第四个微服务。

## 原子性与非原子性

- 本服务数据库事实、幂等回执和 Outbox 同事务；MQ 发布位于事务之外，重试可导致重复事件，消费者按事件来源身份幂等。
- Blob 对象存储与 MySQL 不存在跨资源原子事务。先写入不可变 staging 对象并验 hash/size，再提交指向对象的数据库事实；失败保留不完整候选并在确定性归属条件下 GC。数据库事实绝不能引用尚未完整确认的内容。
- Ingress `250` 仅在收件 spool 具备可恢复的持久事实后返回；mailbox 延迟导入不构成 spool 丢失授权。若 mailbox 永久拒绝导入，保留重试/异常处置，不静默删除已接受邮件。
- 每个服务自己的版本化迁移、账号、审计与 retry 责任；事件合同版本化、消息内容不可由订阅方自行推测，缺字段 fail closed。
- 数据传递只能经具名读 API / 有界的短期内容访问能力；其他服务不持有源存储的管理权限。传输重试必须绑定源 hash 与 owner id。

## 微服务拆分的反例门

三个进程是初始实验假设，不是不可修改的 KPI。若经故障验证发现必须在同一事务内才能维护某个不可分割的不变量，优先重新讨论事实所有权，必要时并回同一服务，而不是借两阶段提交或互写库粉饰边界。禁止仅为了引入中间件再造业务。

## 包级分层

每个 Java 服务：`interfaces`（HTTP/SMTP/MQ DTO）→ `application`（用例协调）→ `domain`（规则、不变量、状态机）← `infrastructure`（MySQL/MQ/SMTP/MinIO 实现）。严格防止 domain 直接依赖 Spring、SMTP library、SQL、消息客户端。简单实体不为“纯架构”制造接口；只有跨替换、隔离或合同边界才设端口。
