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

## 当前边界

本 PASS 只证明精确本地候选源码。M4 尚未经过 PR、CI、受保护合入和 fresh exact-main 复验，因此当前为 `LOCAL_CANDIDATE_PASS / NOT_QUALIFIED`，不能据此启动 M5。
