# M5 有限反例击打计划

**状态：`RESEALED_BEFORE_RESOURCE_1_3_REQUALIFICATION`。** M5 于 `2026-10-14T05:07:57.4464404Z` 从 main `d84e1384af64cca7f4f3c8ac93cdbfa1bd27eff5` 开工；原 18 项计划及资源合同 1.2 候选均保留在 Git 历史和证据绑定中。项目所有者于 `2026-10-14T07:49:42.3361217Z` 授权把启动准入修订为[合同 1.3](m1-resource-contract-1.3.md)，本计划在新一轮观察前重新封存，18 项分母和所有运行停止线不变。它只具体化 A11–A16 和既有失败机制；不改变 M0 的邮件语义、状态所有权、三服务边界或 M1–M4 资格。

## 固定候选与执行纪律

- 每轮绑定 exact source、build receipt、fresh owned lab、独立随机凭据、数据库 generation、对象卷、MQ topic/group、库外 witness 和受控下一跳身份。正常控制、最小故障、独立读回、恢复和精确清理形成一个机制见证。
- 故障只作用于项目拥有的容器、进程、代理、数据库连接和模拟 SMTP。不得修改系统代理、Docker 全局配置、未知进程或用户数据。
- 首次出现的新失败保留原日志、SQL、协议原文、资源窗口和 source。只修复该失败机制并用同一断言重跑；后继成功不覆盖首败。
- 按失败机制收束，不排列 endpoint × 状态 × 服务 × 调度。下表 18 项为资格分母；新增实验只允许用于解释已有项的新失败机制或高后果反证。

## 必过用例

| ID | 机制与固定断言 | 独立证据 |
| --- | --- | --- |
| M5-01 | 无故障控制完成 Alice→Bob 真实 SMTP、回复、附件与 M4 分类路径；原消息、收据和分类决定可读 | TCP SMTP、三库 SQL、S3 hash、MQ、Edge |
| M5-02 | DATA 最终响应丢失只把实际不确定收件人置 `UNKNOWN`，保留最后阶段/RCPT/原 attempt；持续窗口内不自动重投 | 受控下一跳、attempt SQL、连接计数 |
| M5-03 | 用户未确认重复风险时重试被拒；同一具名确认键重复调用只建一个新 attempt，原 UNKNOWN 不被覆盖 | HTTP 收据、attempt 链、下一跳计数 |
| M5-04 | 同一 scope 的确定 4xx 最多三次、1/2 秒退避，确定 5xx 终止；部分收件结果互不改写 | SMTP transcript、逐 recipient SQL、时序 |
| M5-05 | 取消先完成、重复消息和进程重启后仍为 `CANCELLED`，不存在 SMTP attempt 或连接 | scope/job SQL、重启、下一跳零连接 |
| M5-06 | Worker 先领取后取消明确失败；已开始事实、attempt 和最终结果保留 | API、claim/attempt SQL、下一跳 |
| M5-07 | 取消与首次领取真实竞争只产生一个持久赢家；若取消胜出无投递，若领取胜出不假报取消 | 并发调用、锁定行 SQL、下一跳 |
| M5-08 | Worker A lease 过期后由 B 接管尚未提交 DATA 的作业；epoch 单调递增，A 的迟到本地完成更新被拒 | 两 worker 身份、epoch/attempt SQL、受控下一跳 |
| M5-09 | A 已可能产生外部效果再失去 lease 时进入 `UNKNOWN`，不把 fencing 宣称为撤销外部效果，也不自动由 B 重投 | SMTP 接受见证、epoch、attempt 终态 |
| M5-10 | MQ 不可用时已提交 Outbox 持久积压；恢复后有界排空，同一事件重放不增加第二业务效果 | Outbox/MQ/业务 SQL、积压采样 |
| M5-11 | 一条格式错误或摘要不符的毒消息有限失败后进入具名隔离记录；后续有效消息仍推进，不形成热循环 | MQ 投递次数、隔离 SQL、资源窗口 |
| M5-12 | Mailbox 暂时离线时 Ingress 只在 raw/spool 耐久后回 250；恢复后每账户恰好一个导入效果，spool 才可完成 | 原始 SMTP、S3、spool/import receipt SQL |
| M5-13 | S3/数据库代表性中断不假成功；恢复后按现有 receipt/对账推进，孤儿与当前引用的 GC 结果可区分 | 故障到达、S3 hash、对象/引用 SQL、GC |
| M5-14 | Python 分类器超时/退出和 MQ/投影迟到时显示 `UNAVAILABLE/UNKNOWN`，不移动邮件、不跨账户取样；人工锁和规则决定保持最终权 | 双账户训练 SQL、分类版本、API/Edge |
| M5-15 | A→B 会话切换期间旧响应迟到、附件越权请求、BCC/发送 envelope 与显示头分离均不泄露 A 或 BCC | 双会话 Edge Network/DOM、授权响应、raw MIME |
| M5-16 | 危险 HTML、远程像素、事件属性和附件文件名经真实页面显示时不执行、不外连、不逃逸下载边界 | Edge 请求列表/DOM、CSP、附件响应 |
| M5-17 | T0 后真实外发并由下一跳接受，再恢复 T0 数据库快照：服务进入 `NOT_RECONCILED`，拒绝写、领取、重试、导入、Outbox 和 GC，下一跳无第二次投递 | T0 摘要、库外账册、恢复 SQL、下一跳计数、readiness |
| M5-18 | 当前数据库正常控制后仅移除/损坏账册，同样进入 `NOT_RECONCILED`；恢复正确账册后同一 generation 可读且没有自动外发 | 账册 hash、marker SQL、拒绝与恢复事实 |

M5-05、M5-06、M5-07 与 M5-05 内的重启/重放共同保留用户批准的四个取消见证。M5-08 只允许接管尚未形成不可确定外部效果的作业；M5-09 单独证明 fence 的边界。M5-17 与 M5-18 分别隔离“旧快照”和“缺账册”机制，不再排列三库全部回退组合。

## 资源、时间与退出

- 完整三服务、四个中间件、受控下一跳和按需 Python 必须取得至少 18 个完整拓扑 5 秒样本，并覆盖 MQ 中断/恢复、lease 接管和快照隔离窗口。宿主持续占用、容器余量、PID、应用 RSS 与 OOM 按资源合同 1.3 判定。
- 每个故障等待有显式截止；SMTP 会话沿用 10 秒、lease 沿用 30 秒、4xx 沿用三次总 attempt。单个反例不得用无界 sleep、重试、队列或内存缓冲等待成功。
- 最终候选另跑错 source/hash、错 Evidence 绑定与缺证据负控，必须得到声明的非 PASS。业务 `UNKNOWN` 可使对应正确性断言 PASS；资格 `PENDING/INCONCLUSIVE/NOT_PROVEN` 不得通过。
- 18 项全过后仍需三项 CI、受保护合入、fresh exact-main 全量重建复验、负控、公开状态读回和 owned 清理，才可把 M5 标为 `QUALIFIED` 并进入 M6。
