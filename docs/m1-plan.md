# M1 单宿主施工与验收合同 1.0

本阶段具体化 M0 的 A02–A05，不更改冻结语义。M1 实际开工 `2026-10-13T04:06:43.7320975Z`，初始 main `da2ab376c1c84b0b487e3c33b5baafece320b105`。每个子门在运行前绑定干净源码、环境、此合同与依赖锁，封存独立 AcceptancePlan；子门 PASS 不能代替整个 M1。

## 部署及资源

Windows 11 开发机，15.78 GiB 可用物理内存。Docker Linux 引擎；中间件为项目独占容器，应用为三个独立 Java 17 进程。镜像按 linux/amd64 摘要锁定，见 [依赖锁](environment-lock.json)。不修改全局 Docker、代理、Maven/npm 配置或原有 MySQL 服务。

启动完整实验前空闲内存至少 4 GiB，C 盘至少 10 GiB；总占用大于 14 GiB 连续三次（每 5 秒）即保存事实、停止本次 owned 实验。单次只运行一个 full lab，最多两个竞争参与者；构建与重型探针串行。中间件容器硬上限：MySQL 512 MiB、SeaweedFS 256 MiB、NameServer 192 MiB、Broker 512 MiB；每个应用 JVM heap 192 MiB，单应用 RSS 超过 384 MiB 停止实验。全机停止线优先于这些局部上限，不上调以掩盖 OOM。

资源资格不能从宿主机总占用倒推中间件占用。watchdog 每 5 秒同时保存四个运行中容器各自的实际 memory/PID、硬上限、余量、OOM 状态，以及三个 owned 应用的 RSS；任一容器剩余内存低于其上限的 10%，或 PID 余量低于 16，均保留首个样本并停止本轮。M1 聚合必须读回四个具名容器，且至少一个子门窗口连续 6 个样本同时看到四个依赖和三个业务 JVM，证明完整拓扑持续至少 25 秒。该窗口只证明 M1 有界基础负载，不替代 M5 故障压力和 M6 回归。

项目标识必须匹配 `guihong-[a-z0-9-]+`；所有容器、卷、网络带 owner 和 run 标记。清理只允许精确名称及标签匹配；不执行 prune，不删除已存在的共享镜像。数据库、对象数据与库外 witness 使用三个不同持久位置；实际凭据、用户会话与本机日志在忽略的 `.artifacts` 内。

服务只监听回环：Mailbox 18080、Ingress 管理 18081 / SMTP 12525、Delivery 18082。独立 MySQL 容器映射 13306；SeaweedFS 仅映射 S3 19833，其 master/filer/volume/gRPC、WebDAV、Admin/IAM 不向宿主应用开放。MQ NameServer 19876、Broker 20911，仅回环；不增加 Proxy 进程。

## 必过机制（有限分母）

| 子门 | 独立预期与必需见证 |
| --- | --- |
| foundation | 三个应用独立启停，Flyway 各自迁移；三个 DB 用户对自己 schema 正常读写，对另两个 schema 拒绝；就绪因真实依赖/恢复状态改变，drain 拒绝新写且有限退出；实际端口、进程、资源、退出与 owned 清理 |
| identity | 两个合成账户真实登录，HttpOnly/SameSite 会话，刷新与登出失效；停用账户拒绝后续操作；错误密码/未知账户统一响应，有界登录频率；Origin/CSRF 拒绝，A 读取 B 的账户资源拒绝，用户 Cookie 不能获得内部命令权限；仅具名服务凭据能执行相应内部命令 |
| smtp-foundation | 真实 TCP SMTP，外域 recipient 拒绝，M1 本域接收尚未实施时临时拒绝，不能返回成功承担不存在的责任；监听仅回环，无 open relay |
| storage-qualification | 三服务各自 PUT/GET 原字节与 hash 正确；DELETE 后 GET 404；保留对象在停止/重启同一 SeaweedFS 后原字节不变；每个凭据跨另两个桶的 GET/PUT/DELETE 拒绝（18个有界检查），匿名/错误签名拒绝；不向宿主映射后端入口，实际配置与 OCI 身份吻合 |
| object-lifecycle | 应用通过标准 S3 端口；PUT 失败不提交引用；PUT 成功 DB 确定回滚形成可归属孤儿，有限 GC 可重入；COMMIT 结果未知及引用/在途存在时保留对象；已提交对象故障明确返回故障且保留 DB 摘要；真实 SQL/S3 独立核对 |
| recovery-foundation | 正常停止/重启保持 generation 与实际引用；journal 缺失/错误或对象核对失败进入 NOT_RECONCILED，禁止写/GC；旧快照挑战仍是 M5/M6 的必过义务，M1 不代替它 |
| core-compatibility | 使用真实公开 Core 0.13.0；错摘要 FAIL、错绑定 INCONCLUSIVE、缺必需证据 PENDING，任何一个不允许 PASS；原件与首次失败保留 |

最大邮件/MIME 5 MiB、附件合计 4 MiB、10 个收件人、20 个 parts、8 层 multipart，单账户存储 100 MiB、每天 100 次发送提交；初轮两账户串行使用。上传/SMTP/解析实际执行这些界限，到阶段实现前不宣称生效。SMTP/HTTP 超时 10 秒，单探针 180 秒，整子门 600 秒。GC 每次最多 50 项、单次 30 秒，宽限 60 秒并且必须证明零引用/无在途/恢复已对账，不能仅按年龄删。

## 证据与退出

每个子门给出 actual source facts；采集器不提供 all_passed 或 mail_delivered 综合真值。Plan 通过明示断言计算结果，源身份与证据绑定错误必须非 PASS。保存第一次环境/工具/产品失败的分别身份。原生构建、私有完整事实、公开合成摘要、独立读回的范围分别说明。

M1 退出必须全部子门成立，干净构建、有限架构检查与 CI、保护合入、exact-main 复验、安装公开 Core 独立读回以及当前状态投影闭合。M1 只证明底座，不宣称真实收发链路或 M2 产品完整。
