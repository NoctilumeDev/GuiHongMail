# 连续运行账册

| 时间（UTC） | 事实 |
| --- | --- |
| 2026-10-13T04:06:43.7320975Z | M1 第一施工动作：从 main `da2ab376c1c84b0b487e3c33b5baafece320b105` 创建独立 worktree / `build/m1-foundation`；尚无运行时资格 |
| 2026-10-13T04:07:01.8879332Z | 首次 Docker Desktop 启动在 sailor-ingest.sock rename 处失败，归类 ENVIRONMENT_PREFLIGHT_FAILURE；保留本地最小原始日志，不是归鸿构建失败 |
| 2026-10-13T04:12:22.9074307Z | 正常 stop 超时，受支持的 force stop 成功且核对进程清空；从桌面 shell 单次冷启动，未改 socket 目录、数据盘、代理或 Docker 配置 |
| 2026-10-13T04:13:01.9401646Z | 真实 daemon 恢复，Server 29.7.2；既有 8 个其他项目容器全处于退出状态，未更改它们 |
| 2026-10-13T04:14:30.1286495Z | 现有 hello-world 镜像按本地 ID 创建项目具名探针，运行退出并自动清理；只证明已有镜像的创建/执行/清理，未证明网络拉取或根治 |
| 2026-10-13T04:16:10.2587131Z | 人工介入 1：用户报告关闭浏览器；之后实测空闲 7.22 GiB，Docker 仍可访问。人工操作实际起止和时长 UNKNOWN，不推算 |
| 2026-10-13T04:32:10.3087611Z | 首次 lab 启动日志持久化：source `4209bbc8ff52123b7f70dcbab595f8d24dee53d1`；资源归属检查将小写 `no such volume` 当作未知，启动前停止，容器尚未创建。TOOL_SETUP_FAILURE；原 `storage-startup-first.log` 保留，修复仅规范化具名不存在错误 |
| 2026-10-13T04:34:16.129340Z | 首次 A04 source `fd11bfb94ba19710dacf9c46d9e4cfb67a91e408`，运行 `guihong-s3-0cec27b7e33a4b5db5520293105f9a5f`，ERROR / PENDING。CRUD、18 次拒绝等源事实已收；重启后探针只等 TCP，认证 GET 遇连接关闭，未取得持久化证据。COLLECTOR_READINESS_ERROR，原 Plan/Evidence/Bundle/对象保留，按原断言修复就绪等待再验 |
| 2026-10-13T04:45:08Z | Broker 首次启动 source `0833982`：Exit 253 / OOM false；新项目卷 root 目录不允许镜像 UID 3000 创建 store/config/commitlog。DEPLOYMENT_PERMISSION_FAILURE；日志原件在 ignored lab/broker-first-logs 保存；修复仅增加有 owner、无网络、64 MiB 的一次性根目录 chown 初始化，不递归改写卷内数据 |
| 2026-10-13T04:51:07Z | 卷权限修复后 Broker 在 TimerWheel 初始化遇 Java Direct buffer memory，Exit 255；Docker OOM false。保留 after-volume-init 日志。此 profile 不使用 MQ 定时消息；配置禁用默认 timerWheel，不增加 512 MiB 容器上限或直接内存上限，也不改 SYNC_FLUSH、普通持久队列及 Delivery 自有有限重试义务 |
| 2026-10-13T04:56:04Z | 禁用 TimerWheel 后 Broker 的 ScheduleMessageService 启动遇 native thread 创建失败；Docker OOM false，根因未进一步归为全机内存故障。原 after-timer-profile 日志保留；多个默认线程池固定为 18/32，当前单机 profile 将具名线程池收束到 1/2，PID 128 与内存 512 MiB 上限保持 |
| 2026-10-13T05:03:55Z | 有界线程池配置已实际加载，Broker 仍 Exit 255 / OOM false；首败与 after-thread-profile 日志保留，不能宣称 MQ 可用 |
| 2026-10-13T05:50:03Z | 首次编译准备在 PowerShell 参数解析处失败，尚未执行 Java 编译；原 first-compiler-setup.log 保留。后续以独立参数传入 Maven 仓库路径，不改全局配置 |
| 2026-10-13T05:56:56Z | 原配置复现仍 Exit 255；退出前采样 263.8 MiB / 512 MiB、63 PIDs，但未捕获失败瞬间峰值。官方 5.5.0 ScheduleMessageService 按 delay level 启动线程，单机 profile 把默认 18 级收束到 3 级（1s/5s/10s），不提供用户定时发送、不改变 Delivery 重试义务；所有硬上限保持 |

环境可用窗口已恢复，首败不会被后续成功覆盖。主页参考文档按当前中文主线 `NoctilumeDev/NoctilumeDev-ZH@5fe4cddcddc76d883476d004147fcddfaa24ac06` 阅读；同名本地 profile 分支包含更晚的未合入补充，不把它当已发布事实。M6 结束时间、墙钟时长与 Release 身份尚不存在。
