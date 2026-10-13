# 归鸿 · GuiHongMail

> 云水之间，归鸿有信。

**状态：`M0.1_GO_RUNTIME_APPROVED / JAVA_M1_BASELINE_QUALIFIED / GO_PREFLIGHT_NEXT` · 2026-10-13。** Java M1 已在 main `51fe465` 经 PR/CI、fresh exact-main 三子门、资源窗口与公开 Core 聚合取得资格；该结论绑定旧 Java SHA，不能授予 Go 候选。用户随后批准在同一 Git 历史中把三个后端服务迁移到 Go，先执行有限 MQ/资源兼容预检，再从 M1 重新取证。见 [M0.1 Go 追加授权](docs/m0.1-go-runtime.md)、[状态账册](docs/status.md)、[M1 Java 资格证据](docs/acceptance/m1.md)与[原授权](docs/authorization.md)。

## 产品定位

一个**单机真实可用、非简陋、独立业务权责的 Web 邮箱**：至少两名本地用户，以真实 SMTP 协议双向发送/接收，支持 MIME/附件、持久草稿、回复转发、搜索、状态恢复和故障期间的明确反馈。首轮使用回环/隔离域 `guihong.test`；公网与 QQ/Gmail 互通须另开 E1 资格，不以本地证明冒充。

## 用户可见范围（冻结候选）

七个基础入口：**写信、收件箱、已发邮件、草稿箱、归档、垃圾邮件、已删除**。另有 **「我的分类」**：用户先建类别与显式规则，后按本人确认的归类历史由本地算法提出建议，受用户授权才自动采纳；未读红点独立来自实际邮箱事实。搜索/账户设置是工具，不增加星标、文件区、营销页或系统预设分类。

视觉取 **开元之气、笺纸之雅、水墨之意，以轻为重**。清白、极淡墨山水、鸿雁与少量朱砂；取消堆卡片与硬框。桌面左目录/中列表可独立折叠，三栏独立纵向滚动；手机逐层路由。真实操作先做，最终美术精修留给人参与。

## 工程结构

独立仓库为 `NoctilumeDev/GuiHongMail`，本地目录 `C:\Users\lenovo\Desktop\GitHubProjects\GuiHongMail`。三个有状态职责的服务：`mailbox-service`、`smtp-ingress`、`delivery-worker`，每个服务独立数据所有权与失败生命周期；Go 是新后端运行时，Vue 3 + TypeScript 是 Web 客户端，Python 只在 M4 真正需要算法时经可替换合同接入。MySQL8、RocketMQ、SeaweedFS 本地 S3 仍是当前项目隔离依赖，**不预设 Redis/Nacos/独立 Gateway**；RocketMQ 的 Go 客户端路径先经过 M1G 兼容预检，失败不得悄悄增加 Proxy 或替换消息队列。

## 连续施工与截止点

**M0 由用户确认；发出一次 `M1_START` 后，Codex/Agent 连续按 M1→M6 依次施工、验证、修复与独立复验。正常阶段切换不等人工逐关批准。** M5 是有限反例击打，按失败机制而不是无穷组合收束。M6 工程候选闭合后自动停止，状态 `AWAITING_M7_HUMAN_REVIEW`；M7 前端精修需新授权。记录真实起止时间、人工介入和未证明边界；快不等于通过。出现权限/资源/硬性安全等 STOP 必须立即停。

## 资料入口

1. [M0 决策总纲](docs/m0.md)
2. [阶段门与退出标准](docs/milestones.md)
3. [一次授权连续运行合同](docs/continuous-run.md)
4. [架构/服务所有权](docs/contracts/service-boundaries.md)
5. [邮件与分类事实](docs/contracts/mail-facts.md)
6. [安全合同](docs/contracts/security.md)
7. [汉唐水墨视觉合同和参考图](docs/design.md)
8. [有限故障反例矩阵](docs/failure-matrix.md)
9. [VeriTrail 证据与裁决](docs/verification.md)
10. [工程门禁、CI 与目录](docs/engineering-gates.md)
11. [决策账册](docs/decisions.md) / [前端精修记录](design-qa.md) / [Agent 施工宪法](AGENTS.md)
12. [连续施工交接词与实际授权](docs/codex-handoff.md)
13. [M0.1 Go 运行时追加授权](docs/m0.1-go-runtime.md)

补齐的冻结义务：[投递与取消状态机](docs/contracts/delivery-lifecycle.md)、[存储及接受后责任](docs/contracts/storage-lifecycle.md)、[旧快照恢复隔离](docs/contracts/recovery.md)、[验迹必过项](docs/acceptance-obligations.md)。

**任何文档声明均不自动取得运行时资格。** M0 冻结以后，只能用新的明确版本更新合同，不能倒改既有失败证据或验收标准。
