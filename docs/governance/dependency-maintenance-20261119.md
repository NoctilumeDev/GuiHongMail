# 2026-11-19 · 归鸿 Go 公告账册校准

以保护主线 `eda190973c8b2bcc6c16c23d74efee7633e1d30e` 为准。原 CI 使用 Go 1.27.2 与 Node 24.14.0。比较同一干净工作树的原来通过、两次定时拒绝和最新手动运行。两个清单和两个 Go 平台扫描范围均一致。

| 观察 | Windows | Linux | Web npm |
| --- | --- | --- | --- |
| 11 月 2 日通过 | 24 个模块，3 条 | 25 个模块，3 条 | 129 个包，0 条 |
| 11 月 9 日拒绝 | 模块级来源更新 | 同左 | 0 条 |
| 11 月 16 日及 19 日拒绝 | 来源更新，新增标准库公告 | 同左 | 0 条 |

- `GO-2026-5932` 对两平台均为模块级记录。上游在 11 月 2 日修改公告，扫描的修复版本字段也发生变化，未观察到受影响 OpenPGP 包导入。保留原跟进动作与状态。 [Go 官方公告](https://pkg.go.dev/vuln/GO-2026-5932)
- `GO-2026-6859` 对两个平台均有静态符号记录。固定标准库为 1.27.2，上游列出的同系列修复为 1.27.4。另行核对受支持部署条件并验证工具链补丁；实际部署暴露尚待确认。 [Go 官方公告](https://pkg.go.dev/vuln/GO-2026-6859)

当前账册共四项独立公告，按两平台各留四条记录，状态均为 `UNRESOLVED`，`risk_accepted=false`。既有公告、第一次治理观察和检查器保持原内容。只记录此次可复核的公告变化，Go 维护和 Node 补丁分别验证。

## 原始证据

| 运行 | 后端附件 | ZIP SHA-256 |
| --- | --- | --- |
| [11 月 2 日](https://github.com/NoctilumeDev/GuiHongMail/actions/runs/41445278139) | 13142865279 | `c6d8c240bceca2f635a21589f14dbd580517296713bc9d8ea0bc1affb8b23363` |
| [11 月 9 日](https://github.com/NoctilumeDev/GuiHongMail/actions/runs/42621143899) | 13675183475 | `93d72ac1f92e0c49cee2b86a90ae0bfdb7fcf2fb49c2e0a993cb9cc44c93517d` |
| [11 月 16 日](https://github.com/NoctilumeDev/GuiHongMail/actions/runs/43870079867) | 14228285288 | `f70b153abb051aa592597ee03e2188a28deec258258ea42fdf720d395fbb9088` |
| [11 月 19 日](https://github.com/NoctilumeDev/GuiHongMail/actions/runs/44387864286) | 14466683139 | `bc964c9e16f1022eccccee34d942513a9d9fe04aef440d2955ec2b2a51f3b219` |

附件哈希均已读回，最新两份扫描观察内容相同。19 日本机尝试因 Go 模块或校验服务连接失败而停在前置阶段，最新完整观察取自上述 GitHub 原工作流。GitHub 附件随保留期到期；[旧账册](https://github.com/NoctilumeDev/GuiHongMail/blob/eda190973c8b2bcc6c16c23d74efee7633e1d30e/docs/governance/dependency-review.json)保留其 Git 坐标。
