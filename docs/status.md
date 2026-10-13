# 当前阶段与资格

本文件是实际阶段状态入口，冻结合同定义义务，`docs/acceptance/*` 保存取得资格的精确证据。合同原件的制订标记不自动调度下一阶段，也不回写历史字节。

| 项目 | 当前事实 |
| --- | --- |
| M0 | `FROZEN`，17项冻结字节，摘要 `1feb3418b68f0f176645350196313076a8e113ee7b7f54273f9efac8218fc460` |
| M0.1 | `GO_RUNTIME_APPROVED / PREFLIGHT_REQUIRED`；追加授权不改写原 M0 字节，见 [Go 运行时修订](m0.1-go-runtime.md) |
| M0资格主线 | `b34783bd7b440cc466512986f0c74869a4c748e5`；仅文档/授权边界 |
| M1 | `QUALIFIED`，运行资格 main `51fe46533cc45d7ef5d010db6803165de0780905`；PR #4、main CI `38393031035`、fresh exact-main 三子门与资源聚合闭合；原非 PASS 保留；[资格证据](acceptance/m1.md)、[资源合同修订 1.1](m1-resource-contract-1.1.md)、[运行账册](run-ledger.md) |
| M2 | Java 候选 `3136c6f` 为 `IMPLEMENTED / NATIVE_TESTED / NOT_QUALIFIED`；Go 版本须在新 M1 闭合后重新取得 M2 资格 |
| M3–M6 | `AUTHORIZED / NOT_STARTED`，依前一阶段门禁连续串行推进 |
| M7 | `DEFERRED_HUMAN_PARTICIPATION`，需用户另行开启 |
| E1 | `NOT_AUTHORIZED` |
| 运行时 | Java M1 底座取得主线资格；Go `1.27.2` 已安装在 D 盘，`rewrite/go-runtime` 只获准执行 M1G MQ/资源预检，尚无 Go M1 或任何 M2+ 产品资格 |

M0 状态发布已在 `da2ab376c1c84b0b487e3c33b5baafece320b105` 经原 PR 门、受保护合入、新 exact-main 文档门和具名公开读回闭合。M1 Java 资格独立绑定上述 main 运行身份，不由 M0、本状态文字或 M0.1 推导给 Go。Go 迁移先通过 [M1G 预检](m1g-preflight.md)，再从 M1 重建并经过新的 PR/CI/exact-main。
