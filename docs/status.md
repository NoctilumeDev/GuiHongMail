# 当前阶段与资格

本文件是实际阶段状态入口，冻结合同定义义务，`docs/acceptance/*` 保存取得资格的精确证据。合同原件的制订标记不自动调度下一阶段，也不回写历史字节。

| 项目 | 当前事实 |
| --- | --- |
| M0 | `FROZEN`，17项冻结字节，摘要 `1feb3418b68f0f176645350196313076a8e113ee7b7f54273f9efac8218fc460` |
| M0资格主线 | `b34783bd7b440cc466512986f0c74869a4c748e5`；仅文档/授权边界 |
| M1 | `AUTHORIZED / IN_PROGRESS / NO_RUNTIME_QUALIFICATION`，实际开始 `2026-10-13T04:06:43.7320975Z`；原资源失败保持非 PASS，后续候选绑定[资源合同修订 1.1](m1-resource-contract-1.1.md)；[基础合同](m1-plan.md)、[运行账册](run-ledger.md) |
| M2–M6 | `AUTHORIZED / NOT_STARTED`，依前一阶段门禁连续串行推进 |
| M7 | `DEFERRED_HUMAN_PARTICIPATION`，需用户另行开启 |
| E1 | `NOT_AUTHORIZED` |
| 运行时 | 尚无真实邮箱、安全、存储、收发或恢复资格 |

M0 状态发布已在 `da2ab376c1c84b0b487e3c33b5baafece320b105` 经原 PR 门、受保护合入、新 exact-main 文档门和具名公开读回闭合。M0既有身份与资格不因发布提交自动转移为M1资格。M1 的施工状态不是验收通过。
