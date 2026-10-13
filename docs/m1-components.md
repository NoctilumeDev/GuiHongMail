# M1 有界实现补充

此文件说明已批准 A02–A05 的实现参数；不修改 M0 或用新检查替换既有分母。每个正式采集 Plan 在观察前绑定本文件的实际摘要。

会话为 32 字节随机 token，数据库只存摘要；30 分钟到期，HttpOnly、SameSite Strict、Path /api。当前回环 HTTP profile 的唯一浏览器 Origin 为 `http://127.0.0.1:18080`；写请求同时检查 Origin 与会话独立 CSRF nonce。刷新竞争在同一事务中删除旧 token 并创建新 token；停用与 auth epoch 改变阻止旧会话。密码采用 BCrypt cost 10，输入最多 72 个 UTF-8 字节；不存在账户也执行同 cost 比较，错误反馈一致。登录每回环客户端每分钟最多 5 次，预算持久化；两合成账户不构成公网账户能力。

库外事务 witness 最多 10 MiB / 10000 个事务，PREPARE 在 COMMIT 前 fsync；没有确定 COMMIT 结果就保存 U 并禁止写/GC。DB receipt 与 generation/sequence 在业务事务内提交。库外 schema history 摘要先与当前 DB 核对，再允许候选源码的待执行 Flyway 迁移；迁移先写独立 pending 记录，结果未知时不得自动重做/修复。首次开发底座 `9b7be12651ac5584de9ae1fc69aadbbff16f6918` 尚无业务事务：升级至 schema witness 时只在三个 generation 正确、receipt 为空、sequence 0、事务日志为空的已观察首次初始化状态建立一次基线，保存观察原件。正式 M1 起缺失 schema witness 一律阻止恢复；没有 reset/adopt 功能。

Broker 单 CPU、512 MiB、128 PID 的预算保持；JVM 显式感知 1 CPU，使用明确 HEAP_OPTS。普通消息使用 SYNC_FLUSH；关闭未使用的 POP 服务，经典 delay level 收束到 1s/5s/10s。Delivery 的重试仍由本地数据库状态机裁决，不实现用户定时发送。默认 19 个异步日志线程由单一同步 INFO 控制台替代，Docker 本容器日志最多 3×10 MiB，实际首败另存。服务创建真实 MQ 客户端后仍须重新验证资源余量，启动文字不构成消息资格。

组件 profile 修订 1.1：第一真实 MQ 运行在 topic 清理处失败，发现 5.5.0 删除路径和 housekeeping 无条件访问 TimerWheel。原先禁用 TimerWheel 的 workaround 不兼容，撤销；原事件、源码和 Plan 保留。实际镜像 jar 的 TimerWheel 固定 604800 slots，对应 38707200 字节；初始化的驻留直接缓冲和 Files.readAllBytes 临时直接缓冲合计已超过 64 MiB。**不提高 512 MiB 容器上限或既有 256 MiB heap+direct 合计预算**，改为 heap 128 MiB / direct 128 MiB（原 192/64），初始 heap 96 MiB；TimerWheel get/put 各 1 线程。全部原始收发、清理和资源条件必须复验；若 heap/总占用/PID 验证失败保留证据并阻断，不继续增加上限。

资源 watchdog 每 5 秒保存全机与各具名应用 RSS；全机连续三次大于 14 GiB、任一应用 RSS 大于 384 MiB 时停止精确 owned 实验，保留数据库、对象卷和库外 witness。各执行窗口最长 3600 秒，可在下一明确窗口继续，不构成计划任务。

组件 profile 修订 1.2：首次逐容器补采显示 Broker 约 313.9 MiB / 512 MiB、121 / 128 PIDs；这是 PID 余量不合格，原 foundation/S3 结果仅保留为部分证据。一次诊断曾关闭 Lite Pull/Lite Event、账户统计、广播 offset 存储及详细统计，空闲态降至 107 PIDs，但真实 MQ 探针先后达到 113 和 117，且 topic 清理返回错误；这些功能开关全部撤销，不能用破坏生命周期换资源资格。保持 512 MiB 与 128 PID 上限，最终有界复验只使用标准 JVM 单核小堆配置：关闭分层编译、一个 JIT compiler thread、Serial GC；经典 Consumer、同步刷盘、TimerWheel、topic 生命周期和三档 Delivery 重试保持。若同一 watchdog 仍失败，结论为环境阻断，不继续关闭 RocketMQ 功能。

同一逐容器门随后在 NameServer 冷启动捕获 181,298,790 bytes，即 172.9 MiB / 192 MiB，内存余量 9.95%，按预封存的 10% 停止线失败。先前把原始 bytes 误按十进制 MB 写成 181.3 MiB，现按二进制 MiB 更正，原始样本和阻断结论不变。保持 192 MiB 容器上限与 32 MiB direct memory，单机路由服务的 heap 从 96 MiB 收束到 64 MiB、初始 heap 32 MiB，并与 Broker 一样固定单编译线程；真实路由注册、MQ 收发与恢复仍须按原条件复验。
