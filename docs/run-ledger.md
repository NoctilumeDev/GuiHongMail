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

环境可用窗口已恢复，首败不会被后续成功覆盖。主页参考文档按当前中文主线 `NoctilumeDev/NoctilumeDev-ZH@5fe4cddcddc76d883476d004147fcddfaa24ac06` 阅读；同名本地 profile 分支包含更晚的未合入补充，不把它当已发布事实。M6 结束时间、墙钟时长与 Release 身份尚不存在。
