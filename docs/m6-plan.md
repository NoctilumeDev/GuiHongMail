# M6 工程候选退出计划

**状态：`SEALED_BEFORE_M6_RUNTIME_OBSERVATION`。** M6 worktree 的文件系统创建时间为 `2026-10-14T08:40:08.5574616Z`，从 main `75dd679c2e01ff61a315ba03fe3736f553ac47bf` 进入施工。本计划只具体化 A16–A17，不改变邮件语义、M1–M5 资格、资源合同 1.3、M7 视觉边界或 E1 公网边界。

## 固定候选与两轮独立性

- M6 运行候选必须先经 PR/CI 合入 main。随后从同一 exact-main SHA 创建两个不同路径的 fresh checkout；两轮分别从锁文件安装收集器和前端依赖，分别产生自己的 Go build receipt、fresh owned lab、凭据、数据库 generation、对象卷、MQ 标识、SMTP transcript、浏览器截图和清理读回。
- 两轮串行执行。每轮至少取得 M3、M4、M5 resilience 三份同 source PASS，分别覆盖真实 SMTP/MIME/取消/UNKNOWN、桌面与 390px 移动浏览器/分类、T0 旧快照与缺账册恢复隔离。不得把 M5 已有运行复制成 M6 新轮次。
- 独立产品复核只读两轮规范化事实、截图摘要和产物摘要，不采用施工者的“全部通过”文字。两轮二进制与嵌入前端资产必须逐角色同 hash；差异必须解释并重新固定候选。
- 工程候选 Release 使用 prerelease 身份，tag 精确指向运行候选 SHA；三个 Windows amd64 二进制、候选 manifest 与 SHA256SUMS 必须匿名下载后逐字节复核。它不是正式生产发布。

## 十二项退出门

| ID | 固定断言 | 独立事实 |
| --- | --- | --- |
| M6-01 | Round A 为 clean fresh checkout，同 source 锁依赖重建，三二进制与前端资产均有 hash | Git/source、build receipt、lock hash |
| M6-02 | Round B 使用不同 checkout/lab/运行身份重复 M6-01 | checkout identity、build receipt、generation |
| M6-03 | 两轮真实 SMTP 往返、中文 MIME、附件、BCC envelope/显示头隔离均通过 | M3 TCP、SQL、S3 raw、UI |
| M6-04 | 两轮投递重放、有限重试、UNKNOWN 暂停/显式确认和四个取消见证均通过 | M3 attempt/scope/next-hop/browser |
| M6-05 | 两轮真实 Edge 桌面/移动端可操作，账户切换迟到响应隔离且无远程内容请求 | M3/M4 DOM、Network、截图 |
| M6-06 | 两轮规则优先、人工锁、算法低置信/不可用、反馈和账户模型隔离均通过 | M4 API、SQL、算法与 UI |
| M6-07 | 两轮服务停止/重启后数据库、对象、人工决定与邮件状态摘要保持 | M3/M4 restart digest |
| M6-08 | 两轮 T0 旧快照和缺账册均进入 NOT_RECONCILED，恢复后无重复外发 | M5 resilience T0/T1、外部 effect ledger |
| M6-09 | 两轮完整拓扑均守住 14 GiB 三连停线、10% 容器内存余量、16 PID 余量及 384 MiB/app | resource JSONL 与停止原因 |
| M6-10 | 独立产品复核接受功能与安全事实，并明确 `VISUAL_POLISH_PENDING` | product-review JSON、截图 hash |
| M6-11 | prerelease tag、候选 SHA、main CI、三个二进制、manifest 与 SHA256SUMS 的公开读回一致 | GitHub API、匿名资产字节、hash |
| M6-12 | 两轮按[操作手册](operator-guide.md)证明可重入启停；最终应用、容器、网络、卷与监听均按 owner 清零 | round cleanup receipt、端口读回 |

## 负控、资源与停止

- 聚合器必须以正确输入得到 PASS；错误 Plan 绑定得到 INCONCLUSIVE，缺证据得到 PENDING，错误 release 资产事实得到 FAIL。任一非 PASS 不得发布工程候选。
- 两轮各自使用[资源合同 1.3](m1-resource-contract-1.3.md)。启动准入至少 2 GiB 空闲；运行期门、样本分母及业务断言不因 M6 收口缩小。
- 单轮失败保留原 Plan、Evidence、截图、日志和清理状态；只修复该失败机制并从新的 exact source 重新执行两轮，不用另一轮覆盖。
- M6 PASS 后更新状态为 `ENGINEERING_CANDIDATE / VISUAL_POLISH_PENDING / AWAITING_M7_HUMAN_REVIEW`，记录 M1 开工至 M6 闭合墙钟与人工介入，清理 owned 运行资源并立即停止。M7 与 E1 不自动开始。
