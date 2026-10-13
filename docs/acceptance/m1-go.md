# M1 Go 重建资格记录

## 本地候选

Go 候选 `66277da54ede3fbc3ee96b3dbb631363e496b846` 于 `2026-10-13T15:08:35.4436503Z` 取得本地聚合 `COMPLETED / PASS`。聚合身份为 `guihong-m1-44e0299c5ed24ef28b447b2d4fce486b`，边界为 `M1_LOCAL_CANDIDATE_ONLY`；Plan 摘要 `6ff818d093673a27e4c2b2cc6fa2be9febb5c01308d90bee0186d81d5d9522e9`，事实摘要 `109ebb9ecd81692337abce0ccf95af2bed7de8604984e81a87f96c5aae0949e7`，请求摘要 `2730f049a1a853969115d0cde0ce7199b886f9ae776f12b5f4161ee6689f9dfd`。

| 子门 | 身份 | Bundle manifest SHA-256 | 结果 |
| --- | --- | --- | --- |
| foundation / identity / SMTP / MQ | `guihong-foundation-5c8adfc8fbd74ba3bbd3d609182f36bb` | `eac5743fbda76640bd24c8d553af91dbde491709bd9d00ac5f146c9651a98c56` | `COMPLETED / PASS` |
| SeaweedFS A04 | `guihong-s3-1db27b0e155a426ba202190ce5b27682` | `8c234699d7a6c85d3b68027ecff2868b70a7111dea41dca7caafeb06f4736d5b` | `COMPLETED / PASS` |
| 对象 / GC / 恢复 A05 | `guihong-objects-acb595d3612246ae8a40209bd7a9190e` | `0fc5eea9d1617d7cf87bbb3122c397fc1c7519092322fd2b03d13a37e1f4e9db` | `COMPLETED / PASS` |

三个 Go 二进制的不可变构建回执 SHA-256 为 `a90a9df45b8959f2967e43d1f2c78441af32ddfc00bd2275f8a23f9e025212ac`，绑定 `go version go1.27.2 windows/amd64`、精确源码、构建日志和各产物摘要。聚合 bundle manifest SHA-256 为 `4199509ecdeeeb9099cc18e1c2cfcade56cddd8de00b2290c5a7f078fccc09dd`，79 条规则全部 PASS。

资源窗口分别为 21、9、33 个样本，停止原因均为空并覆盖对应子证据。最长完整拓扑连续 14 个样本；宿主峰值 `13,374,386,176 bytes`，低于 14 GiB 停止线；单个 Go 应用 RSS 峰值 `15,986,688 bytes`，低于 384 MiB。Broker 峰值 `452,879,974 / 536,870,912 bytes`、`158 / 192 PIDs`，最小 PID 余量 34；NameServer 峰值 `133,588,582 / 268,435,456 bytes`、68 / 128 PIDs；所有容器 OOM 均为 false。

负控使用同一子证据和资源原件：错误哈希 `guihong-m1-26af2fd9ca8c4a0ca2c58f334c4ecb53` 为 `COMPLETED / FAIL`，错误绑定 `guihong-m1-1dcc9217529e474dab7aeaa4870279c2` 为 `COMPLETED / INCONCLUSIVE`，缺失证据 `guihong-m1-2d276a6787c541b1989910555cddf2bb` 为 `COMPLETED / PENDING`。三者均命中预先声明的非 PASS 结果。

本 PASS 证明同一干净 SHA 的 Go M1 底座、三服务身份与关闭、身份会话、拒绝型 SMTP、普通 MQ 生命周期、S3、对象故障窗口、GC 重入和恢复基础。它不证明受保护主线、exact-main 或 M2 邮箱功能；Go M1 仍为 `LOCAL_CANDIDATE_PASS / NOT_QUALIFIED`，须经 PR/CI、受保护合入和 fresh exact-main 复验。

## 保留的非 PASS

- `guihong-objects-27b5cafc5cb34675bb7b3665323fd5d3` 在 source `2798824bc01abe8e1869b88de55c16a47eca0f94` 为 `COMPLETED / FAIL`。MySQL 对 `DELETING -> DELETING` 更新报告零 changed rows，旧实现把已经取得删除资格的对象静默跳过；`mailbox-gc`、`mailbox-absent` 和 `gc-bounded` 三条硬断言失败。修复在行锁内把无引用的 `DELETING` 作为合法重试，并优先恢复该状态，原失败不重判。
- `guihong-local-1408e2b6cf97` 因收集器未实现 `--help` 而被帮助探测意外启动两个真实收集器，违反串行坐标；该 lab 与 `guihong-objects-e99488f475fc4ccb8e460e6d00863207` 的 `ERROR / PENDING` 已封存，不进入资格链。
- 首次聚合 `guihong-m1-6a697c98aee94fbe979dfa429a64ac2c` 为 `COMPLETED / FAIL`。功能子门均为 PASS，但 storage 守卫首样本晚于子证据起点，`storage-resource-time` 失败。只重开 storage 子门并在收集前取得首个资源样本，未修改阈值或断言。

## exact-main

尚未取得。此节只有在受保护合入后，以新的 fresh lab、精确 `origin/main`、新的三个子门和 `--mode exact-main` 聚合闭合后才能升级。
