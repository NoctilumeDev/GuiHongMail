# 当前阶段与资格

本文件是实际阶段状态入口，冻结合同定义义务，`docs/acceptance/*` 保存取得资格的精确证据。合同原件的制订标记不自动调度下一阶段，也不回写历史字节。

| 项目 | 当前事实 |
| --- | --- |
| M0 | `FROZEN`，17项冻结字节，摘要 `1feb3418b68f0f176645350196313076a8e113ee7b7f54273f9efac8218fc460` |
| M0资格主线 | `b34783bd7b440cc466512986f0c74869a4c748e5`；仅文档/授权边界 |
| M1 | `QUALIFIED`，运行资格 main `51fe46533cc45d7ef5d010db6803165de0780905`；PR #4、main CI `38393031035`、fresh exact-main 三子门与资源聚合闭合；原非 PASS 保留；[资格证据](acceptance/m1.md)、[资源合同修订 1.1](m1-resource-contract-1.1.md)、[运行账册](run-ledger.md) |
| M2 | `AUTHORIZED / NEXT`，依连续施工合同进入邮箱核心，不继承 M1 资格替代 M2 证据 |
| M3–M6 | `AUTHORIZED / NOT_STARTED`，依前一阶段门禁连续串行推进 |
| M7 | `DEFERRED_HUMAN_PARTICIPATION`，需用户另行开启 |
| E1 | `NOT_AUTHORIZED` |
| 运行时 | M1 底座取得主线资格；尚无 M2 邮箱产品、M3 真实投递、M4 Web 或 M5/M6 工程候选资格 |

M0 状态发布已在 `da2ab376c1c84b0b487e3c33b5baafece320b105` 经原 PR 门、受保护合入、新 exact-main 文档门和具名公开读回闭合。M1 资格独立绑定上述 main 运行身份，不由 M0 或本状态文字推导；M2 仍须建立自己的增量合同与证据。
