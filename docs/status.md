# 当前阶段与资格

本文件是实际阶段状态入口，冻结合同定义义务，`docs/acceptance/*` 保存取得资格的精确证据。合同原件的制订标记不自动调度下一阶段，也不回写历史字节。

| 项目 | 当前事实 |
| --- | --- |
| M0 | `FROZEN`，17项冻结字节，摘要 `1feb3418b68f0f176645350196313076a8e113ee7b7f54273f9efac8218fc460` |
| M0.1 | `GO_RUNTIME_APPROVED / PREFLIGHT_PASS`；追加授权不改写原 M0 字节；M1G 只授权 Go M1 实施，见 [Go 运行时修订](m0.1-go-runtime.md)与[M1G 证据](acceptance/m1g.md) |
| M0资格主线 | `b34783bd7b440cc466512986f0c74869a4c748e5`；仅文档/授权边界 |
| M1 | Go `QUALIFIED`，运行资格 main `2a1dd5ae86ed01655cc723ae2d94176e8cdf4054`；PR/CI、fresh exact-main 三子门、资源聚合、三类负控和 owned 清理闭合。Java main `51fe46533cc45d7ef5d010db6803165de0780905` 的历史资格保留为对照；[Go M1 资格](acceptance/m1-go.md)、[Java M1 资格](acceptance/m1.md)、[M1G 证据](acceptance/m1g.md)、[资源合同修订 1.1](m1-resource-contract-1.1.md)、[运行账册](run-ledger.md) |
| M2 | Go `QUALIFIED`，运行资格 main `4f92a5dfc646693237b476b4f38448d7bd798af6`；PR/CI、fresh exact-main 16 项运行门、真实 Edge、资源窗口、两类负控和 owned 清理闭合。Java 候选 `3136c6f` 只作迁移历史，不向 Go 提供资格；见 [Go M2 资格](acceptance/m2-go.md) |
| M3 | Go `QUALIFIED`，运行资格 main `3cce7d162a1a5889fc69db7c4a42087b21682a09`；PR/CI、fresh exact-main 18 项 SMTP/投递门、真实 Edge、资源窗口、两类负控和 owned 清理闭合；见 [Go M3 资格](acceptance/m3-go.md)、[M3 计划](m3-plan.md)与[线缆修订 1.1](m3-plan-1.1.md) |
| M4 | `PLAN_FROZEN / IN_PROGRESS`；分类规则、Python 算法合同、人工优先、自动授权/撤销、双账户隔离与 16 个有限用例见 [M4 计划](m4-plan.md) |
| M5–M6 | `AUTHORIZED / NOT_STARTED`，依前一阶段门禁连续串行推进 |
| M7 | `DEFERRED_HUMAN_PARTICIPATION`，需用户另行开启 |
| E1 | `NOT_AUTHORIZED` |
| 运行时 | 当前主线为 Go `1.27.2` 三服务，`rocketmq-client-go/v2@v2.1.2` 对接无 Proxy 的 RocketMQ 5.5.0；Go M1、M2、M3 已分别取得 exact-main 资格，尚无 M4+ 产品资格 |

M0 状态发布已在 `da2ab376c1c84b0b487e3c33b5baafece320b105` 经原 PR 门、受保护合入、新 exact-main 文档门和具名公开读回闭合。Go M1、M2、M3 资格分别绑定 `2a1dd5ae86ed01655cc723ae2d94176e8cdf4054`、`4f92a5dfc646693237b476b4f38448d7bd798af6`、`3cce7d162a1a5889fc69db7c4a42087b21682a09` 的独立 exact-main 运行证据，不由状态文字或 Java 基线推导。下一阶段为 Go M4。
