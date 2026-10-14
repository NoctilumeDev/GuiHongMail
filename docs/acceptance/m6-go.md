# M6 Go 工程候选资格记录

## exact-main 候选

M6 运行候选先经 [PR #16](https://github.com/NoctilumeDev/GuiHongMail/pull/16) 合入 main `aa615b9eb25461f4cfa47124c03a6e59c36263e5`。首轮收据依次暴露 M3 截图子目录错误和 `WindowsPath` 不能写入 JSON；原失败、PR #17 首轮 CI 失败及两轮失效的 fresh 证据均保留。修复分别经 [PR #17](https://github.com/NoctilumeDev/GuiHongMail/pull/17)与 [PR #18](https://github.com/NoctilumeDev/GuiHongMail/pull/18) 合入，最终运行候选为 main `ce1929aad5b9595270cd5fbe36f34fa29d78d9ad`；同 SHA 的 [main CI](https://github.com/NoctilumeDev/GuiHongMail/actions/runs/38545866957) 中静态合同、Go 后端和 Web 三项全部通过。

两个不同路径的 fresh detached checkout 分别从锁文件安装 VeriTrail Core 0.13.0、收集器和前端依赖，并各自执行前端构建、Go test/vet 与三二进制构建。两份独立 build receipt 的 `mailbox.exe`、`ingress.exe`、`delivery.exe` 及三个前端资产哈希完全一致；Round A `guihong-m6round-356147cd7c62456ba9b553f88707c423` 的 SHA-256 为 `b1cc40959a2ec2d6d71ec5bf4df3fc962646511a79adc88ef5461cf974d7022c`，Round B `guihong-m6round-7cdee79665a148bba546aa0e26eed8e1` 的 SHA-256 为 `6dec94503ae1dade1df75286330f82a27a7669089281aaa46b98523e667ebb87`。

每轮使用三套 fresh owned lab，分别重新取得 M3、M4 与 M5 resilience PASS。两轮共同覆盖真实 SMTP/MIME/附件/BCC、有限重试、`UNKNOWN` 暂停与明确确认、取消竞争、真实 Edge 桌面和 390px 移动端、账户切换隔离、规则/人工决定/算法故障隔离、重启持久化、T0 旧快照与缺账册 `NOT_RECONCILED`、精确恢复及无重复外发。六套 lab 的应用、容器、网络、卷和端口清理读回均为零。

独立产品复核 `guihong-m6review-5588c6c2f68f401b999471982ae7f34d` 为 PASS，review SHA-256 为 `bd914c15f81493cb644779f34e5dd6e3c09389e58bd47d8ce2736ada3a8b3439`。六项产品断言全过；功能、安全与移动端路径取得工程资格，视觉状态明确保持 `VISUAL_POLISH_PENDING`，公网邮件保持 `NOT_PROVEN`。

## 公开工程候选

[prerelease `v0.1.0-ec.1`](https://github.com/NoctilumeDev/GuiHongMail/releases/tag/v0.1.0-ec.1) 的 tag 精确指向 `ce1929aad5b9595270cd5fbe36f34fa29d78d9ad`。匿名 GitHub API 与公开下载读回 `guihong-m6release-44297a17765f478bb7432985b763300a` 为 PASS，readback SHA-256 为 `3a28f0b1ed552e9d82a03b49b42de4bff1ccc79cfcc8bb89a9f6107b272d80c4`；三个二进制、工程候选 manifest 与 `SHA256SUMS.txt` 的公开字节、API 大小和预期 SHA-256 全部一致。

M6 Core 聚合 `guihong-m6-a99a836137794bb4ac9195547463b86f` 为 `COMPLETED / PASS`，12 项预封存断言全部通过。Plan 摘要为 `88f7296dd15490ace3c098cd8ab3c552d18a8cbe004fb64d0de78603917c055a`，事实摘要为 `f3d75f7e1baf88be34c6be72e16a04884dfb8cb3d0b68f9c02aee87d17af87f3`，请求摘要为 `65ed8e8fef3d405ca83c156c6c42fe493204e3b333b635cd74236f558a0aa52c`，evidence SHA-256 为 `0daf815bc70009eb2a3a08ed235837bcd4e79c86febed8126f49e41ea1d1a050`，bundle manifest SHA-256 为 `c1c936fb4deaaf957c11e4d84a185a0815393535d616fb3f9f2a20de3b8ecd18`。

错误绑定负控 `guihong-m6-885ac4542874402d87ab9e6b9974ff65` 为 `INCONCLUSIVE`，缺证据负控 `guihong-m6-fdfedaa7ac434a86955850bfc62e04e5` 为 `PENDING`，错误 Release 负控 `guihong-m6-16e2f7f72d234bd6b5c4f3a0b6e0bb8e` 为 `FAIL`。把本机绝对路径放入封存坐标的首次调用被 Core 以敏感值拒绝；最终聚合只使用稳定相对引用，没有放宽校验。

## 资源、时间与边界

双轮资源窗口的宿主峰值为 `14,217,744,384 bytes`，低于 14 GiB 停止线；容器最小内存余量为 `17.11%`，最小 PID 余量为 28，均高于资源合同 1.3 的硬线。启动准入使用 2 GiB，运行期 14 GiB 三连停线、10% 内存余量、16 PID 余量、384 MiB/app 与 C 盘 10 GiB 均未改变。

M1 第一施工动作为 `2026-10-13T04:06:43.7320975Z`，M6 最后一项预注册断言闭合于 `2026-10-14T10:51:37.996974Z`，实际墙钟为 `1.06:44:54.2648765`。账册记录 7 次具名人工介入；各次实际操作时长与总人工时长为 `UNKNOWN`，不推算。工期不参与资格裁决。

M6 在运行 main `ce1929aad5b9595270cd5fbe36f34fa29d78d9ad` 取得 `QUALIFIED / ENGINEERING_CANDIDATE / VISUAL_POLISH_PENDING`。当前自动施工状态为 `AWAITING_M7_HUMAN_REVIEW`：M7 最终视觉精修、E1 公网互通和正式生产发布均未授权，不能从本记录推导。
