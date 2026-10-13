# 发送、UNKNOWN 与取消合同 1.0

本合同落实 2026-10-13 用户决定。状态所有权保持 Mailbox 的不可变 SendIntent 与 Delivery 的投递资格/尝试分离；冻结不等于实现。

## 发送范围与收件人

Mailbox 在同一事务内保存不可变发送快照、规范化请求摘要、完整 envelope recipients、发送者身份、SendIntent 与 Outbox。重放同键同正文返回原收据；异正文冲突。发送者只能以自己获准地址提交；来自匿名 SMTP 的 From/MAIL FROM 只是未验证来源，不获得本地账户可信身份。内部命令/事件须有来源认证、版本、source owner/id、dispatch scope id、内容摘要及收据绑定；回环端口不替代授权。

Delivery 以唯一 SendIntent 身份生成一个 `DispatchScope`，拥有同一发送范围的 `ever_started`、取消决定和 per-recipient jobs。创建、领取、取消、重放均锁定同一 scope 持久坐标。Mailbox 只发布命令或通过具名认证 API 请求，并消费决定投影，不直接写 Delivery schema。HTTP 超时或投影迟到不改变 Delivery 决定。

| 状态/事实 | 允许推进 | 必须拒绝 |
| --- | --- | --- |
| scope QUEUED、ever_started=false | 取消或首次领取，原子二选一 | 同时成功 |
| scope CANCELLED | 查询原取消决定 | 领取、重排、恢复发送、迟到事件复活 |
| 首次领取持久成功 | ever_started=true，并生成具名 attempt/epoch/lease | 后续撤回或清除 ever_started |
| recipient 临时拒绝 RETRY_WAIT | 到期有限重试或达到上限明确失败 | 无限重试、牵连其他确定结果 |
| recipient NEXT_HOP_ACCEPTED | 保留协议观察，后续独立 DSN | 改称最终送达或已读 |
| recipient UNKNOWN | 暂停，查询/核对；显式承认重复风险后新 attempt | 自动重投、改成失败/成功、抹去原 attempt |

取消命令在 Job 创建前到达时，Delivery 用经过认证的 SendIntent 坐标建立取消 tombstone；迟到的创建/重放不能绕过它。无法验证来源或找不到权威对象时拒绝或保留待定，不能凭猜测取消。重复取消返回同一决定。只有 Delivery 的持久 `QUEUED -> CANCELLED` 成功才能向用户确认；Worker 先领取则返回「邮件已进入发送流程，无法取消」。请求未确认显示处理中，不假报成功。

## UNKNOWN 的归属与恢复

每个 attempt 保存 worker、epoch、租约、下一跳、实际 RCPT 集合、各 RCPT 响应、最后协议阶段、DATA 是否已提交、最终响应及观察摘要。发送 DATA 终止符后确认丢失、收到接受响应但记录前崩溃、带不可确定外部效果的超时/进程中断均不能归为确定失败。

UNKNOWN 只影响该会话中无法确认接受的收件人集合；已确定拒绝、其他会话的已接受/永久失败保持原状态。用户重试请求具名、幂等、授权，并记录已确认重复风险；新 attempt 不覆盖旧 UNKNOWN。确定 4xx 按预封存次数/时间预算重试，确定 5xx 按 RCPT/DATA 阶段结束对应义务。来源无法核对时维持待核对。

租约/epoch 防止旧 Worker 修改本地新状态；它们不能取消已经写到 SMTP socket 的外部效果。尚无具名尝试的排队接管与已开始的未知接管分开：不能把 expired lease 自动重新解释为允许投递。取消丢失领取资格的 Worker 在 SMTP 动作前须核对持久能力；被取消的 scope 不可生成有效投递 attempt。

## 有限见证

取消必须有四个预注册见证：取消先成功、Worker 先领取、二者真实数据库并发、取消后进程重启与重复消息。独立 SQL 与受控下一跳观察互斥结果；不穷举全部调度。UNKNOWN 用正常对照、最终响应丢失、确认后本地中断、关联收件人与其他确定结果隔离、显式重试重复风险各一个代表性机制见证。
