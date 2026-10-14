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
| M5 | Go `QUALIFIED`，运行资格 main `b77cd819f94c7319dc74bf130e99f8ee63b9ee4d`；资源合同 1.3 的 PR/CI、main CI、fresh exact-main 五子门、18 项聚合、两类负控和 owned 清理闭合。资源合同 1.2 的本地候选与首败保留原绑定。见 [Go M5 资格](acceptance/m5-go.md)、[M5 计划](m5-plan.md)与[资源合同 1.3](m1-resource-contract-1.3.md) |
| M6 | Go `QUALIFIED / ENGINEERING_CANDIDATE / VISUAL_POLISH_PENDING / AWAITING_M7_HUMAN_REVIEW`，运行资格 main `ce1929aad5b9595270cd5fbe36f34fa29d78d9ad`；两轮不同 checkout 独立重建、六套 fresh lab、产品复核、prerelease 匿名资产读回、12 项 Core 聚合、三类负控与 owned 清理闭合。见 [M6 资格](acceptance/m6-go.md)、[M6 退出计划](m6-plan.md)与[操作手册](operator-guide.md) |
| M7 | `DEFERRED_HUMAN_PARTICIPATION`，需用户另行开启 |
| E1 | `NOT_AUTHORIZED` |
| 运行时 | 当前工程候选为 Go `1.27.2` 三服务，`rocketmq-client-go/v2@v2.1.2` 对接无 Proxy 的 RocketMQ 5.5.0；Go M1–M6 已分别取得 exact-main 资格，自动施工停止在 M7 前 |

M0 状态发布已在 `da2ab376c1c84b0b487e3c33b5baafece320b105` 经原 PR 门、受保护合入、新 exact-main 文档门和具名公开读回闭合。Go M1–M6 资格分别绑定 `2a1dd5ae86ed01655cc723ae2d94176e8cdf4054`、`4f92a5dfc646693237b476b4f38448d7bd798af6`、`3cce7d162a1a5889fc69db7c4a42087b21682a09`、`fba2e1469e589928ec54647b4b65dbd4c94db9f5`、`b77cd819f94c7319dc74bf130e99f8ee63b9ee4d`、`ce1929aad5b9595270cd5fbe36f34fa29d78d9ad` 的独立 exact-main 运行证据，不由状态文字或 Java 基线推导。当前自动施工已停止，等待用户另行授权 M7 人工前端精修。
