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

[PR #6](https://github.com/NoctilumeDev/GuiHongMail/pull/6) 的静态合同、Go 后端与 Web 三项检查通过后，于 `2026-10-13T15:17:42Z` 受保护合入 merge SHA `2a1dd5ae86ed01655cc723ae2d94176e8cdf4054`。旧保护规则仍要求已删除的 `Java 17 backend` 检查名，合入前只把该 context 替换为实际运行的 `Go backend`，保留 strict、静态合同和其余保护。main CI `38420821072` 随后成功。

fresh lab `guihong-local-a11c04ab0907` 第一次启动前因空闲内存 `2.63 GiB` 低于 4 GiB 准入线停止，没有创建容器或卷。人工释放资源后空闲内存为 `4.55 GiB`，同一未污染 lab 才获准启动；三个 schema 均为 virgin，并生成新的对象卷、MQ 卷、凭据和 witness。

exact-main 聚合 `guihong-m1-7806c25444504efcaafa887c5ff33113` 于 `2026-10-13T20:22:47.7965929Z` 得到 `COMPLETED / PASS`，边界 `M1_LOCAL_EXACT_MAIN_ONLY`，并实际断言 `HEAD == origin/main`。Plan 摘要 `f4a998075c7efab3c16d4d4a4df9dfaba3dee3f9cadc283f04cef6ae708723ba`，事实摘要 `e1da67fc63844d32ca4870ad798030624d73697e7e3a26e23a6a7f82db063269`，请求摘要 `a7f89bf1c24f4db015ffcdeb037523d6bf6498df68c524952345258f90afc2ad`，构建回执摘要 `9514e49b82feb4fcd2d4b606ba54689e3419cbbb16fed8283adc7c8c01b28b25`。聚合 bundle manifest SHA-256 为 `d2735dd46b86cdb418a63c5af5bf4a3676ec8ce1c315ad0cdae4b7d7404c5ab8`，80 条规则全部 PASS。

| 子门 | 身份 | Bundle manifest SHA-256 | 结果 |
| --- | --- | --- | --- |
| foundation / identity / SMTP / MQ | `guihong-foundation-23ae0cc3fc4d4a08ad45e2b765c5af14` | `001c3dc5f3d4b6d6be09fe4807a6c6d62e14ff9ad4ef03f1a038cdcad8859a8d` | `COMPLETED / PASS` |
| SeaweedFS A04 | `guihong-s3-43ee35455e2848079302db80e28e7a7e` | `ec71517e9e1f947319873f022672932288a4f22afd67f1a7c5a16156cd37cf75` | `COMPLETED / PASS` |
| 对象 / GC / 恢复 A05 | `guihong-objects-b197e587fb5f4fb98543936a0a0a9f2b` | `4f1adf280ce91c886b16cd1e9a9d0cdd62116f6701a7e8b6540b7d2c904de7d4` | `COMPLETED / PASS` |

三个资源窗口分别为 21、9、33 个样本，停止原因均为空并覆盖子证据。最长完整拓扑连续 14 个样本；宿主峰值 `13,743,710,208 bytes`，单个 Go 应用 RSS 峰值 `54,546,432 bytes`。Broker 峰值 `374,236,774 / 536,870,912 bytes`、`139 / 192 PIDs`，最小 PID 余量 53；NameServer 峰值 `161,690,419 / 268,435,456 bytes`、70 / 128 PIDs；所有容器 OOM 均为 false。

exact-main 负控 `guihong-m1-48a95c5b8c1d457f842ae467c77f5a6f`、`guihong-m1-241d276982104e4ca326cc4790c0c67a`、`guihong-m1-3f42d0d131fe4521a1eb8e46205f9442` 分别得到预期的 `FAIL`、`INCONCLUSIVE`、`PENDING`。应用已停止，owned 容器、网络和三个数据卷已精确清理；resource/witness 与标准证据移入 qualified-labs 归档。

## 资格结论

Go M1 在 `2a1dd5ae86ed01655cc723ae2d94176e8cdf4054` 取得 `QUALIFIED`：PR/保护门、main CI、fresh exact-main 构建、三个子门、资源窗口、聚合、负控与 owned 清理闭合。Java `51fe46533cc45d7ef5d010db6803165de0780905` 的历史 M1 资格与 `baseline/java-m2-candidate-20261013` 仍保留为对照，不向 Go 继承 M2 结论。下一阶段为 Go M2。
