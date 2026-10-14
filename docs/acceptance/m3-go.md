# M3 Go SMTP 与投递资格记录

## 本地候选

Go 候选 `f20442cc0391917a8f39abb1e029bf22ecc422d1` 于 `2026-10-14T07:59:08.715339+08:00` 在 fresh owned lab `guihong-local-a1b32f7fd81e` 取得 `COMPLETED / PASS`。运行身份为 `guihong-m3-0ba433e8c6944038b9f7f48f884496f0`；Plan 摘要 `e437d0e5e3358bbafd97d1bbdadb5541fd0850ae40078081763558aa5c16110a`，事实摘要 `b9b87fc3a62d21ffc42bf1a72713fdda7e7057682f307af4931e8787d801ab11`，请求摘要 `6cb4df40904ca7402e0b56df6fa7dbbc9100789cc2614d8b77bce1b43d17f988`。构建回执 SHA-256 为 `8d33f15cb15abc14ade2980c2c9f89a406c7284a3e42f4f72f70ce9420e6f640`，bundle manifest SHA-256 为 `866b2f850d71bde9b006d9921ba757a38ca3a52d3abb4519ed874f727c41651a`。

18 个预封存用例全部 PASS。事实覆盖 SendIntent 冻结、Outbox 提交后发布与恢复、BCC 隔离、逐收件人 SMTP 结果、确定 4xx 的有限重试、5xx 终止、最终回复丢失后的 UNKNOWN 暂停、用户明确承担重复风险后的重试、取消与 Worker 领取互斥、真实 SMTP 接入与本地域拒绝、10+1 收件人数和 5 MiB SIZE 拒绝、S3 故障、DATA 接受后的 Mailbox 中断、导入幂等、最终 spool COMMIT 不确定、回复链头、服务重启和真实页面动作。Edge `155.0.4283.45` 实际完成排队取消与 UNKNOWN 明示重试；外部请求为空。

资源守卫取得 13 个完整拓扑样本，停止原因为空。宿主峰值 `13,321,043,968 bytes`，容器最小内存余量 `52.91%`，最小 PID 余量 53。三应用正常停止，owned 容器、网络和三个具名卷经标签核对后精确清理；private lab 与资源见证移入本地 ignored 的 qualified-labs 归档。

同一来源事实负控 `guihong-m3-e7fa7a21347f47fa8b68f123002b1c56` 将绑定改错，得到预期 `COMPLETED / INCONCLUSIVE`；`guihong-m3-526367e5183e4e0fa7efe904a1877ae5` 移除必需证据，得到预期 `COMPLETED / PENDING`。本 PASS 当时只证明精确本地源码，不能替代 PR、CI、受保护合入或 fresh exact-main。

## 保留的首败

- 消费组、Topic、路由传播、内部目标凭据和不可变内容复用的前置失败已逐项记入[运行账册](../run-ledger.md)和 M3 计划 1.1；每次只修复对应线缆或责任机制。
- `guihong-m3-68f9ef33b0454e8c8b8027ec14408683` 至 `guihong-m3-9f4f81112b304ced9d930a61569e475a` 的六轮候选分别暴露错误探针端口、RCPT 前错误停服、故障注入命中错误 COMMIT、页面反馈层阻挡取消按钮及 SMTP 错误未结构化等采集/实现问题，均保留为 `PENDING`，没有被最终 PASS 覆盖。
- `guihong-m3-7e960594cdc5436cb400e842f3cfbc0d` 在 source `0e93e71e48fe6e0dbcb110d8cdc90b5ab31515fd` 得到真实 `COMPLETED / FAIL`：18 项中 16 项通过，未声明 SIZE 的超限 DATA 在 Windows 上得到连接重置而非明确 552，65 秒资源窗只有 9 个完整拓扑样本。最终候选改用标准 SMTP `SIZE=5242881` 预检取得明确 552，并恢复预封存的 90 秒资源窗；没有降低上限、样本数或业务断言。

## exact-main

[PR #10](https://github.com/NoctilumeDev/GuiHongMail/pull/10) 的静态合同、Go 后端与 Web 三项检查通过后，于 `2026-10-14T00:04:15Z` 受保护合入 merge SHA `3cce7d162a1a5889fc69db7c4a42087b21682a09`。PR CI `38487873812` 与该 SHA 的 main CI `38488014223` 均成功。

fresh worktree 实际确认 `HEAD == origin/main == 3cce7d162a1a5889fc69db7c4a42087b21682a09` 且工作树干净。fresh lab `guihong-local-3d1b30ba7151` 首次启动前因空闲内存低于 4 GiB 准入线停止，没有创建容器或卷；用户释放资源后复测空闲 `8.388 GiB`，同一未污染 lab 才启动，三个 schema 均为 virgin。exact-main 从锁文件重新安装收集器和前端依赖并重建三个二进制；构建回执 SHA-256 为 `100e8d0f5a1d0c0d4b6bf13444b4a28206ca0279023da5eb6f2f84160c8e08c5`。

exact-main 运行 `guihong-m3-249cd1e8d6c448d085518ffea4bed7ee` 于 `2026-10-14T09:54:38.948346+08:00` 得到 `COMPLETED / PASS`，18 个硬用例全部通过。Plan 摘要 `048fddbf2e78a1e229932eab1a821755547b8024e4311e75e280b206659473c5`，事实摘要 `31d264be3939ea6bce40b8f2182d6ea7805dd9fec81af7f437f61eef077f2d98`，请求摘要 `e8d5ebf576ef0e8de9776ecabe435b9b4932ee2993da76f2b1d1cdc7aa4a75e8`，bundle manifest SHA-256 `5f7fa50ef9fd3983b61a4c008f5f3b6f5007e641316d5c7ab3a4b1fc9e2c0e13`。

资源守卫取得 13 个完整拓扑样本，停止原因为空。宿主峰值 `13,217,464,320 bytes`，容器最小内存余量 `39.88%`，最小 PID 余量 53。真实 Edge 再次完成取消与 UNKNOWN 明示重试，外部请求为空。错误绑定负控 `guihong-m3-6fa9f4bd87e5486da48fa0c1f07ddee1` 为 `COMPLETED / INCONCLUSIVE`，缺证据负控 `guihong-m3-722c50f9c8fc4658b113964bd071e90c` 为 `COMPLETED / PENDING`。应用已正常停止，owned 容器、网络和三个卷经标签核对后精确清理；private lab 与见证归档。

## 资格结论

Go M3 在 `3cce7d162a1a5889fc69db7c4a42087b21682a09` 取得运行资格：本地候选、两轮 CI、受保护合入、fresh exact-main 重建、18 项 SMTP/投递/浏览器门、资源窗口、负控及 owned 清理闭合。M3 状态为 `QUALIFIED`，下一阶段为 Go M4；本记录不提前证明 M4 智能分类、M5 故障矩阵或 M6 工程候选资格。
