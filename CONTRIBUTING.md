# 参与归鸿维护

先读 [AGENTS](AGENTS.md)、[当前仓库护栏](docs/governance-maintenance.md)及[安全边界](SECURITY.md)。当前运行时为 Go；保留的 Java 工程是历史基线，不以历史构建结论替代当前 Go 事实。

1. 从当前 main 建独立分支，写清基线 SHA、范围、保护的行为、不做什么、验收和停止条件。
2. `python -B scripts/check.py all` 只做静态/结构门禁。实际后端另跑 CI 中的 Python 测试、`go test ./...`、`go vet ./...`、`go build ./cmd/...`；前端在 `frontend/web` 按锁文件 `npm ci --ignore-scripts` 后运行 `npm test` 和 `npm run build`。工具链与隔离要求按项目原运行说明。
3. 本批保护负控入口为 `python -B -m unittest discover -s scripts/tests`，同时以 `-O` 复验。远端保护由有管理权限的维护者执行 `python -B scripts/check-branch-protection.py` 读回，普通 CI 不需要管理员密钥。
4. PR 留命令、环境、实际结果、首次失败和剩余边界。走三项必需检查与受保护合并，不用管理员绕过；合并前后分别核对候选与新 main。CI 成功不等于 SMTP 已投递、真人已读或生产部署安全。

三服务的事实所有权、UNKNOWN、幂等、恢复、邮件/附件隐私和人工分类优先不能被“治理整理”顺手改掉。不得改原封存合同、Plan、Bundle或删除首败来制造成功。新问题有自己的来源、所有者、处置状态；不能为了本轮收口抹去风险。

本轮不创建 Release、不制作安装包、不扩业务、不启动 M7/E1。中间件升级、深入安全归因与专项复验在三仓护栏之后另开。公开复现只用合成账户和邮件，敏感报告遵守 SECURITY.md，不把真实私信、票据或凭据写进 Issue、PR 或 CI 附件。
