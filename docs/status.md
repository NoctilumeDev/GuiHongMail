# 当前阶段与资格

本文件是实际阶段状态入口，冻结合同定义义务，`docs/acceptance/*` 保存取得资格的精确证据。合同原件的制订标记不自动调度下一阶段，也不回写历史字节。

| 项目 | 当前事实 |
| --- | --- |
| M0 | `FROZEN`，17项冻结字节，摘要 `1feb3418b68f0f176645350196313076a8e113ee7b7f54273f9efac8218fc460` |
| M0.1 | `GO_RUNTIME_APPROVED / PREFLIGHT_PASS`；追加授权不改写原 M0 字节；M1G 只授权 Go M1 实施，见 [Go 运行时修订](m0.1-go-runtime.md)与[M1G 证据](acceptance/m1g.md) |
| M0资格主线 | `b34783bd7b440cc466512986f0c74869a4c748e5`；仅文档/授权边界 |
| M1 | Go `QUALIFIED`，运行资格 main `2a1dd5ae86ed01655cc723ae2d94176e8cdf4054`；PR/CI、fresh exact-main 三子门、资源聚合、三类负控和 owned 清理闭合。Java main `51fe46533cc45d7ef5d010db6803165de0780905` 的历史资格保留为对照；[Go M1 资格](acceptance/m1-go.md)、[Java M1 资格](acceptance/m1.md)、[M1G 证据](acceptance/m1g.md)、[资源合同 1.1](m1-resource-contract-1.1.md)、[M5 本地候选使用的资源合同 1.2](m1-resource-contract-1.2.md)、[当前资源合同 1.3](m1-resource-contract-1.3.md)、[运行账册](run-ledger.md) |
| M2 | Go `QUALIFIED`，运行资格 main `4f92a5dfc646693237b476b4f38448d7bd798af6`；PR/CI、fresh exact-main 16 项运行门、真实 Edge、资源窗口、两类负控和 owned 清理闭合。Java 候选 `3136c6f` 只作迁移历史，不向 Go 提供资格；见 [Go M2 资格](acceptance/m2-go.md) |
| M3 | Go `QUALIFIED`，运行资格 main `3cce7d162a1a5889fc69db7c4a42087b21682a09`；PR/CI、fresh exact-main 18 项 SMTP/投递门、真实 Edge、资源窗口、两类负控和 owned 清理闭合；见 [Go M3 资格](acceptance/m3-go.md)、[M3 计划](m3-plan.md)与[线缆修订 1.1](m3-plan-1.1.md) |
| M4 | Go `QUALIFIED`，运行资格 main `fba2e1469e589928ec54647b4b65dbd4c94db9f5`；PR/CI、fresh exact-main 16 项分类与产品回归门、真实 Edge、资源窗口、两类负控和 owned 清理闭合；见 [Go M4 资格](acceptance/m4-go.md)与[M4 计划](m4-plan.md) |
| M5 | Go `RESOURCE_CONTRACT_REOPENED / NOT_QUALIFIED`；资源合同 1.2 下 source `395426fc3e14104dea29ac2cffe82ca59c6c5a52` 的五个子门、18 项聚合与两类负控 PASS 作为历史候选保留。当前资源合同 1.3 使用 2 GiB 启动准入，须在新 source 上重新取证并完成 PR/CI、受保护合入与 fresh exact-main 全量复验。见 [Go M5 候选记录](acceptance/m5-go.md)、[M5 计划](m5-plan.md)与[资源合同 1.3](m1-resource-contract-1.3.md) |
| M6 | `AUTHORIZED / NOT_STARTED`，M5 资格成立后依门禁连续串行推进 |
| M7 | `DEFERRED_HUMAN_PARTICIPATION`，需用户另行开启 |
| E1 | `NOT_AUTHORIZED` |
| 运行时 | 当前主线为 Go `1.27.2` 三服务，`rocketmq-client-go/v2@v2.1.2` 对接无 Proxy 的 RocketMQ 5.5.0；Go M1、M2、M3、M4 已分别取得 exact-main 资格，M5 因资源合同 1.3 重开、尚未取得产品资格 |

M0 状态发布已在 `da2ab376c1c84b0b487e3c33b5baafece320b105` 经原 PR 门、受保护合入、新 exact-main 文档门和具名公开读回闭合。Go M1、M2、M3、M4 资格分别绑定 `2a1dd5ae86ed01655cc723ae2d94176e8cdf4054`、`4f92a5dfc646693237b476b4f38448d7bd798af6`、`3cce7d162a1a5889fc69db7c4a42087b21682a09`、`fba2e1469e589928ec54647b4b65dbd4c94db9f5` 的独立 exact-main 运行证据，不由状态文字或 Java 基线推导。当前工作仍是闭合 Go M5 资格，M6 尚未开始。
