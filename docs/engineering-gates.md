# 工程配套与运行门禁（M0 设计，未实施）

## 目录与职责

```text
GuiHongMail/
  README.md / AGENTS.md / SECURITY.md / design-qa.md
  .github/workflows/ci.yml      # M1 开始建立，不伪称已存在
  backend/
    mailbox-service/
    smtp-ingress/
    delivery-worker/
    contracts/                  # DTO/schema；严禁共享业务实体
  frontend/web/                     # 七个基础入口 + 我的分类
  deploy/compose.yaml           # 项目专用 profile / volume / 网络
  scripts/check.py              # M1 按真实实现建立统一入口
  docs/
    m0.md / milestones.md / continuous-run.md / design.md / verification.md
    engineering-gates.md / failure-matrix.md / decisions.md
    contracts/
  artifacts/                    # 只提交合成、脱敏、具名的公开最小证据
```

## M1 前要确定的工程环境

- 当前 Windows/Linux、Docker/Compose、JDK17、Node、MySQL8、MQ、SeaweedFS S3、Java 邮件库具体稳定版本/锁与下载来源。不是一次性自动更新到“最新”。
- 项目唯一的容器、schema、queue/group/topic、spool 根目录与监听名前缀；每个资源的 owner、预算、创建和清理步骤。
- 采用 `.env.example` + 忽略的实际凭据，测试合成账户；`smtp-ingress` 默认本机端口映射，严禁公网开放中继。
- 可用内存测量、Docker 上限、实例并行上限、消息/附件限额；OOM/空间不足的可观察终止和恢复路径。

## 最小公开门禁（要在 M1 实际建成）

- `docs`: 链接/合同一致性、Source SHA与里程碑非虚构状态、敏感文件/生成残留与路径扫描。
- `backend`: 锁定依赖构建/测试、包层架构规则、真实 MySQL schema 迁移；M3 起增加真正 SMTP/MIME 协议测试与 MQ/SeaweedFS S3 受控集成。
- `frontend`: 依赖锁、typecheck、可访问性/基础 unit、生产构建、无秘密/未授权外联；目录栏与列表栏独立折叠、三栏独立滚动、手机返回/键盘、用户分类与红点。
- `security`: 关键凭据与依赖检查、open relay 负例、MIME/HTML 安全测试、上传容量边界。
- `serial-lab`: 单机已分配的真实 API/SMTP/MQ/SeaweedFS S3 组合故障和浏览器端到端；按测量预算串行，不把 GitHub CI 占位结果当真机或宿主容量证据。

M1 后提供 `scripts/check.py docs|backend|frontend|security|hygiene|all` 或等价可复现入口。`all` 可以串行聚合，但不得隐式安装/启动未授权资源或触碰别的项目。CI 可以只跑可稳定复现的公开有限资格，重型长压测独立留账，不盲目塞满 PR 门禁。

## 一次运行与交付计时

用户批准 M0 并发出 `M1_START` 后，Agent 从 M1 连续到 M6，正常门禁闭合直接进入下一阶段；M6 后收口停止，M7 需新授权。计时方式、授权上限和 STOP 见 [连续运行合同](continuous-run.md)。审美非阻断问题进 M7，真实使用阻断不能推迟。

## 从候选到发布

合同批准 → 单目的分支/提交 → 真实环境源事实 → 失败修复与原条件复验 → 独立核验 → 受保护 main → exact-main CI/读回 → 两次 fresh 安装/可用性与清理 → Release identity。PR 数、代码行数、测试数量不成为完成 KPI。原有失败保留不可覆盖；未经验证标 `PENDING/NOT_PROVEN`。

前端按已选候选图做真实功能与最低可用视觉，M2/M4 完成正常用户功能，M5 有限反例，M6 工程候选与独立产品复核；M7 用户参与最终精修。视觉验收绑定同状态、同视口、相同源数据、规范化比较、真实操作；参考图不是整屏实现也不是功能断言。

## 单机存储与恢复门

M1 SeaweedFS 的具体版本、OCI 摘要、标准 S3 客户端、权限隔离、PUT/GET/DELETE、重启持久性、对象/数据库故障窗口、GC、恢复与资源资格缺一不可。M5/M6 旧快照隔离按[恢复合同](contracts/recovery.md)，不能复用普通重启结论。各阶段必过集合见[固定清单](acceptance-obligations.md)。
