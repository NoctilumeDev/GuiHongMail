# M4 Go 智能分类候选记录

## 本地候选

Go 候选 `9e5cff04869590793792c0362f7f846b2ff56e01` 于 `2026-10-14T12:43:37.098214+08:00` 在 fresh owned lab `guihong-local-a1f021dd5d81` 取得 `COMPLETED / PASS`。运行身份为 `guihong-m4-96385d2b7f264a2a86907d0dbbdbeaf1`；Plan 摘要 `b76ef3b6d2721419167a2ce4c2ef2d200eee21b5e6784a1248d6d3826da7a31f`，事实摘要 `aa0d42d99f726ca71174880503f69895faf90d3d29687b3f41d4d3bc0654aa3b`，请求摘要 `401a8a12f091733e95fc96e31d477e3e9aca955f8a4e90b41112f5941cc148fe`。构建回执 SHA-256 为 `71fd44792fc35df17fab792c2ef78954c2f5186587f08ce2b82a0e450fb8d0df`，bundle manifest SHA-256 为 `c7b41340954fc0b1d5722ee0fb451c2bee7ef988a846bdcce3d1e2b4af889fff`。

16 个预封存用例全部 PASS。事实覆盖每账户规则 CRUD、乐观锁与越权隐藏，确定性优先级和同级冲突，人工锁优先，规则建议与显式自动应用/撤销，Python 3.10 短进程 naive Bayes 合同、散列特征、冷启动与低置信度拒绝、双账户模型隔离、建议接受/拒绝/人工覆盖、按分类授权的算法自动应用与撤销、关闭算法后的建议撤回、算法文件缺失时规则继续工作、正文与附件不变、重启恢复，以及 M3 的真实附件发送与回复闭环。

Edge `155.0.4283.45` 实际完成桌面规则优先级修改、搜索、建议接受、账户切换迟到响应隔离和 390×844 移动端建议拒绝；七个邮箱导航入口可见，外部请求为空。Python 分类器仅按需运行，稳态进程数为零；传入算法的训练特征不含发件地址或主题明文。

资源守卫取得 13 个完整拓扑样本，停止原因为空。宿主峰值 `12,516,720,640 bytes`，容器最小内存余量 `48.59%`，最小 PID 余量 54。三应用正常停止，owned 容器、网络和三个具名卷经标签核对后精确清理；private lab 与资源见证移入本地 ignored 的 qualified-labs 归档。

同一来源事实负控 `guihong-m4-62391ded0eec43ac85d11b9194ca4c2b` 将证据绑定改错，得到预期 `COMPLETED / INCONCLUSIVE`；`guihong-m4-4612ce44e3aa4be18fd4ffade30a35c4` 移除必需证据，得到预期 `COMPLETED / PENDING`。

## 保留的首败

- `guihong-m4-c8a69d51512445b291c868c97d084367` 在 source `c7b4b4b1f23b63e48d5959decc316035a785e260` 为 `ERROR / PENDING`：采集器调用了不存在的导入路由并把 404 文本当 JSON。原 lab 与输出保留；只把采集器绑定改到既有 fixture 端点。
- `guihong-m4-eb54adfd503e4d17a239a75e4acb0580` 在 source `7b703e925d969d617dd2cbdeb25bd65d8ef7fe4b` 为 `ERROR / PENDING`：真实 MySQL 拒绝从 binary 参数构造 JSON，Mailbox fail-closed 退出。四个分类 JSON 写入改为 UTF-8 文本绑定，未改变表结构或算法合同。
- `guihong-m4-a2d5f8041a234a92b1f099721b8dca94` 在 source `567b0b72994b14606441d3cbe1bcd125e3596f50` 为 `ERROR / PENDING`：规则刷新已按合同撤回旧建议，采集器却随后决策旧 ID。原结果保留；采集顺序改为先完成建议决策，再验证规则刷新。
- `guihong-m4-0dbf134448ba4903a7d4d7d48da5e0da` 在 source `3ef89155b94f26b79e1715e42d60fadf43e23203` 得到真实 `COMPLETED / FAIL`：16 项中 14 项通过。发送与回复产生的最终异步分类尚未收敛就取了重启前快照；导航按钮的可访问名称被未读徽标扩展。稳态重复重启已证明分类表相等，下一候选要求待分类数先归零并按实际导航元素判断可见性，没有降低重启或产品回归断言。

## exact-main

[PR #12](https://github.com/NoctilumeDev/GuiHongMail/pull/12) 的静态合同、Go 后端与 Web 三项检查通过后，于 `2026-10-14T04:48:36Z` 受保护合入 merge SHA `fba2e1469e589928ec54647b4b65dbd4c94db9f5`。PR CI `38513251711` 与该 SHA 的 main CI `38513314097` 均成功。

fresh detached worktree 实际确认 `HEAD == origin/main == fba2e1469e589928ec54647b4b65dbd4c94db9f5` 且工作树干净。收集器与 Web 依赖分别从哈希锁和 `package-lock.json` 重新安装，三个 schema 在首次迁移前均为 virgin；三个 Go 二进制与前端从 exact-main 重建，构建回执 SHA-256 为 `4aebefb17d53ea9f7e56ecc1c37d6d9878362502316746c548823592126cbfb3`。

fresh lab `guihong-local-1ddfa86aa127` 的运行 `guihong-m4-79b76dfa51eb43c3a7d0f9cb90c71dfe` 于 `2026-10-14T12:58:11.194606+08:00` 得到 `COMPLETED / PASS`，16 个硬用例全部通过。Plan 摘要 `5b71f89673f8424e623d9cc060adc92b193e2f661d9cd922f2b76d50f3447a93`，事实摘要 `4de0b11e351a2aee67fb42db9d266631ba75d0eeb3408abc55ca5e380aba469b`，请求摘要 `ac3aab83c5afebeefcc0ef8d24d48301199035e1df1cd72610dac520b9eee8a0`，bundle manifest SHA-256 `57059188ba1a3287a81c4f3c2604765a6e1ef65950afc146c20fc5790853cb3e`。

资源守卫取得 13 个完整拓扑样本，停止原因为空。宿主峰值 `14,069,026,816 bytes`，低于 14 GiB 停止线；容器最小内存余量 `41.64%`，最小 PID 余量 54。真实 Edge 再次完成桌面与移动端操作，外部请求为空。错误绑定负控 `guihong-m4-97bec9b3530c4e7f9d8fd5bf1e80244d` 为 `COMPLETED / INCONCLUSIVE`，缺证据负控 `guihong-m4-6ae37b9703d541a5a4ba2164a2db1663` 为 `COMPLETED / PENDING`。应用已正常停止，owned 容器、网络和三个卷经标签核对后精确清理；private lab 与见证归档。

## 资格结论

Go M4 在 `fba2e1469e589928ec54647b4b65dbd4c94db9f5` 取得运行资格：本地候选、两轮 CI、受保护合入、fresh exact-main 重建、16 项分类/浏览器/产品回归门、资源窗口、负控及 owned 清理闭合。M4 状态为 `QUALIFIED`，下一阶段为 Go M5；本记录不提前证明 M5 故障矩阵或 M6 工程候选资格。
