# 当前仓库护栏维护

## 本批范围 · 2026-10-23

从 `main@157424731b71659a983a5ef4be4b4d643c8ad9c0` 开独立分支。用户要求先完成青野、期序、归鸿本轮护栏，中间件依赖升级与专项复验后置另开一轮。不制作发布包，不创建 Release，不重开 M7 视觉精修或 E1 公网接入。

已有 [engineering-gates.md](engineering-gates.md) 是 M0 封存输入，不在原文上改写成当前状态。本页单独记录治理增量。保留三服务 Go 运行边界、历史 Java 基线、SMTP/邮箱事实分离、算法人工优先和原 Plan/Bundle；不改业务、依赖锁、历史失败与发布资产。

本批要补的是：前端虽有 CI，却未被列为必需检查；保护配置缺少仓库内的读回与负控入口；CI 原始检查身份和输出缺少有限留存；缺少当前贡献说明。本批通过不等于整个治理计划完成。

## 三项必需检查

| 名称 | 当前实际职责 | 来源 |
| --- | --- | --- |
| `Static contracts and boundaries` | 原 M0 seal、文档/结构/包边界/有限敏感信息检查，以及本批保护负控 | GitHub Actions `15368` |
| `Go backend` | Python 工程/分类/代理测试，Go test、vet、三个命令构建 | GitHub Actions `15368` |
| `Web typecheck, tests and production build` | 锁定安装、前端逻辑测试、vue-tsc 与生产构建 | GitHub Actions `15368` |

CI 不具备真实 SMTP/MQ/对象存储全链路、灾备、浏览器精修或公网资格；这些属于原阶段具名证据，不能由当前绿灯自动继承。`scripts/check.py all` 是静态/结构检查，不是实际 Go/npm 构建测试。

最低保护见 [main-protection.json](../.github/main-protection.json)：最新基线、PR、失效审阅清理、会话解决、对管理员生效、禁止强推和删除，不设显式 PR bypass。保留现有合并策略，批准人数仍为 0，因此不宣称平台强制独立人工审阅。

有管理读取权限的维护者执行 `python -B scripts/check-branch-protection.py`，只做 GET；无权限、缺配置、检查缺失或来源不符都失败。`--snapshot <GET响应.json>` 只验证保存的时点，不宣称当前远端状态。普通 PR 只跑离线负控，不注入管理员 token；设置变更、合并前后另做 live GET。维护者仍能修改配置，读回不等于永久不可绕过。

## 验收与停止条件

依据 [GitHub 必需检查的来源绑定说明](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)，本批负控逐个验证缺检查、无 App 绑定、错误 App、放松最新基线、管理员豁免、强推、删除、缺 PR、显式 bypass、权限/网络失败会被拒绝。正向保留额外更强检查；不向主线尝试违规 push。

本地静态门禁、原 seal 校验与新负控必须通过。候选公开 CI 须实际执行三个 job 并成功，不接受跳过/neutral 充当执行证据。Go 测试以 JSON 原输出留存，管道启用 pipefail，不能让 tee 成功掩盖测试失败；前端保留 Vitest JUnit 结果。各 job 保存实际 checkout/run/attempt/job 坐标，只输出允许的字段，不转储环境变量。

附件限于使用虚构数据实际运行生成的测试输出及检查身份，30 天留存；失败后也尝试上传，不上传真实邮件、凭据、数据库或整个工作树。缺报告时保留缺失，不伪造测试结论；强制取消/超时可能来不及上传。长期资格仍归原正式证据，不把短期 CI 附件替代原 Bundle。

退出：负控、原检查及本候选 CI 通过，远端所需三检查与 App 读回匹配，变更仅在声明范围；合并后另查 exact-main。额外问题独立记录，不无限追求“零告警”，不把旧 M6 资格给新源码授权。

## 剩余工作分开记录

后续 Go/npm 护栏批次见 [质量与安全护栏记录](governance-quality.md)，本页保留 PR #22 批次的原始范围与观察，不把旧批次状态改写成新事实。

后续按实际缺口核对当前 Go/前端依赖与许可、静态质量/覆盖盲区、敏感信息检查覆盖及维护渠道，不机械套用 Java 工具。中间件风险由归鸿维护者保留所有者、受影响坐标、来源、状态与重入条件，待本轮之后专项处理；后置不等于风险接受。尚未检查的项不是 PASS，本页不新许诺支持周期或响应时限。

## 本批观察记录

2026-10-23 的管理员 GET 确认：main 只有静态合同和 Go 两个必需检查，现有前端成功检查来自 `15368`。原配置由新读回器拒绝后，仅 PATCH 必需检查集合追加前端及该 App；后续 live GET 匹配最低规则，其他保护字段逐字段比较未变。原响应、首次拒绝和新响应保存在 `artifacts/local/governance/binding-20261023/`，未尝试违规推主线。

本地静态门禁通过，M0 seal 仍为 `1feb3418b68f0f176645350196313076a8e113ee7b7f54273f9efac8218fc460`；新负控普通/-O 各 8 项全部通过。候选 CI、实际 Go/npm 输出和合并后坐标另按本批 PR 记录，不由静态结果预填通过。这不是中间件风险处理结果。
