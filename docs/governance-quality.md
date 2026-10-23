# Go/npm 质量与安全护栏

## 本批范围与停止线

入口为 `main@c6284cb0f393f70583f896e8047819a67de3ecc3`。期序本轮结束后，只补归鸿当前 Go 与 Web npm 的持续依赖检查、有限凭据检测、覆盖盲区记录及维护渠道。不改三服务业务、SMTP/MIME/UNKNOWN 语义、人工分类优先、Go/npm 业务依赖、M0 seal、历史 Plan/Bundle 和发行资产；不重开 M7/E1，不创建 Release。

当前已有 Go test/vet/build、前端逻辑测试/类型检查/构建、包边界与三项来源绑定的必需检查。本批复用这些入口，不为对齐其他仓库更换技术栈。Java 树保留为历史基线，不作为当前 Go 运行依赖；其历史维护责任保留，不宣称已完成本轮 Java 依赖审计。

验收要求：新检查实际运行；工具失败、缺失/不完整报告、依赖输入改变或未经复核的公告变化均不能通过；有限负控验证否决能力。覆盖率只测量并核对分母，不设任意百分比。现有风险保留所有者、来源、状态、后续动作，不通过自动刷新账册清空告警。

候选需要原三项 CI、固定提交复核和保护读回；合并仍需授权，合并后核对 exact-main。停止条件是所选护栏有效且剩余事项可追踪，不是零漏洞或生产资格。中间件依赖维护另行开展；确认正在暴露的严重问题单独报告，不静默忽略。

## 观察与渠道状态

2026-10-23 获得精确文本和单项设置授权后，已启用 Private Vulnerability Reporting；管理员 GET 返回 `enabled=true`，公开 Security 页面存在 `Report a vulnerability` 入口。两项读回后，才在根 SECURITY.md 末尾原样追加批准文本，原业务安全边界不动。账号通知配置 `NOT_VERIFIED`、实际投递 `DELIVERY_NOT_VERIFIED`；没有制造测试报告。文档公开落地仍须 PR 合并，不把候选文件当作 main。

## 依赖检查的具体分母

入口：`python -B scripts/dependency_gate.py`。固定 Go `1.27.2`、govulncheck `v1.9.0`；扫描器只安装到本次忽略输出目录，不更改业务依赖。先校验锁定模块和下载校验和，再分别以 `GOOS=windows/linux GOARCH=amd64 CGO_ENABLED=0` 对 `./...` 连同测试进行符号级扫描。独立 `go list -deps -test` 与扫描器 SBOM 核对包根、模块和版本；工具失败、分母缩小、报告缺失或冲突不能当成零告警。

当前完整解析图含 67 个第三方模块；实际导入扫描覆盖 Windows 24 / Linux 25 个模块坐标（含项目自身与标准库）。未被这些目标导入的其余解析模块只登记来源，不声称完成漏洞扫描；其他架构、CGO、额外 build tags、历史 Java 与外部服务端均不在此分母内。npm 使用 v3 锁文件、显式公共 registry，含 dev/optional/peer，当前分母为 129 个包，不只扫描生产子集。

[初次完整观察](governance/dependency-observation.json)来自 `main@c6284cb0f393f70583f896e8047819a67de3ecc3` 加本分支治理检查器的未提交状态；依赖输入未变，不冒充 exact-commit CI。原始 JSON/错误输出、exit code、工具身份与每次 run.json 留在 `artifacts/local/governance/dependencies/run-*`，CI 成功/失败均尝试上传 30 天，扫描器二进制不上传。

[风险账册](governance/dependency-review.json)绑定输入、模块分母及每条公告内容，**只登记，不接受风险**。绿灯名为 `CHANGE_GATE_PASS`，表示本次没有未经复核的依赖/公告变化，不表示存量风险已解决。扫描失败、新增/消失/改变的公告、依赖变更均要求人工复核；脚本没有自动改写账册入口。`--collect-only` 只产生观察，不取得门禁通过。CI 使用普通 gate 模式。

| 候选 | 本次观察 | 状态与后续 |
| --- | --- | --- |
| [GO-2025-4188](https://pkg.go.dev/vuln/GO-2025-4188) · Logrus 1.4.0 | 模块及包命中，本次未报告受影响符号调用链 | `UNRESOLVED`；归鸿维护者在第二轮 RocketMQ 传递依赖维护中核对 Writer 路径及兼容升级，不借此豁免 |
| [GO-2026-5932](https://pkg.go.dev/vuln/GO-2026-5932) · x/crypto 0.58.0 | 模块命中，本次未报告受影响 OpenPGP 包导入 | `UNRESOLVED`；归鸿维护者保留导入/目标范围变化重入条件；不是所有配置不适用的结论 |
| [GO-2026-6809](https://pkg.go.dev/vuln/GO-2026-6809) · Go 1.27.2 标准库 | 观察到 `S3Client.Delete → … → crypto/x509.Certificate.Verify` 静态链 | `UNRESOLVED`；归鸿维护者单列 Go 工具链维护，核对系统信任库与受损中间证书条件。实际部署暴露未验证，任何 HTTPS/公网支持前优先处置；不是中间件升级的附属项 |

Windows/Linux 各保存上述 3 条，共 6 条平台记录，**只有 3 个不同公告**。前端本次 129 包未命中，不等于没有未知漏洞。标准库链是静态过近似；`internal/platform/s3.go` 当前构造器只接受 HTTP 回环入口，但这不足以单独证明所有网络路径都不可达，因此仍保留未知，不新增部署承诺、不以普通 CI 授予公网资格。

## 许可、凭据与质量边界

[Go 许可来源清单](governance/go-license-sources.json)对 67 模块的顶层 LICENSE/LICENCE/COPYING/NOTICE 文件计算哈希；66 模块找到来源，`github.com/chzyer/logex@v1.1.10` 为 `LICENSE_SOURCE_UNVERIFIED`。所有者为归鸿维护者，后续需核对该锁定版本的上游来源/打包授权；本轮不发布资产，不把缺失判成禁止使用或已获许可。找到文件也只是 `SOURCE_HASHED_NOT_LEGAL_REVIEW`，不是全面法律审查。npm 129 条包记录都有许可证声明，声明随锁文件绑定，但未逐包核验上游条款。现有自有素材/历史来源不在本轮被重新授权。

有限凭据扫描现在覆盖所有 Git 跟踪文本，包括 Vue/TS/JS，不再按扩展名或 2 MB 阈值跳过；NUL 输入只作 UTF-16 特征探测，文件读取/编码/空分母失败即拒绝。输出文件、行号和规则，不打印候选值。私钥头、GitHub、AWS、API、Slack 特征有合成负控；这不是历史 Git、压缩包、任意二进制或所有凭据格式的完整扫描。

沿用既有包边界检查、Python 工程/分类测试、Go test/vet/build 与 Web 类型/测试/构建。本批增加 Go `-coverpkg=./...` 语句覆盖报告；Windows 初次测得 **11.7%**，只说明这套单元测试的有限覆盖，不给 SMTP、MySQL、S3、RocketMQ、恢复和公网链路授予资格。不任设覆盖率百分比，不重跑或改写历史 M6 证据来补数字。

## 初次失败与复验规则

联调首败均保留，不以最终成功覆盖：

- `run-_ehy5p50`：完整模块图中存在未下载的间接模块源码，许可来源采集失败；补充仅下载锁定坐标，不改 go.mod/go.sum。
- `run-kmkuviyo` / `run-pdmftpma`：根目录无 Go 文件以及 module-only 模式不接受包模式；改为项目实际需要的 source/symbol `./...` 连同测试，并独立核对导入图。
- `run-lij57gm6`：解析器误拒绝扫描器跨模块重复输出的相同公告。只合并内容一致的记录，冲突仍拒绝；测试包路径按 Go 工具约定归一化。
- 首次离线负控暴露 npm 规范化结果共享输入对象，已改成独立副本，原条件普通/-O 复验；原始审计报告始终保留。
- 首次本地覆盖报告命令的 PowerShell 参数被拆分，分析步骤找不到 `.out` 文件；测试本身成功。原始文件 `go-coverage-first` 保留，后续使用引用参数，不把路径错误当作零覆盖或通过。

以上是检查器施工失败，不是业务漏洞修复记录。候选提交、真实 CI、负控计数与合并后 exact-main 在本批 PR 留存；文档不预填未来检查通过。
