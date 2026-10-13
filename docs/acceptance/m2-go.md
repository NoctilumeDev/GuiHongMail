# M2 Go 邮箱与 Web 资格记录

## 本地候选

Go 候选 `0fef1ca77358c130b8602bdd74e7d2a08eb15168` 于 `2026-10-14T05:25:26.830121+08:00` 在 fresh owned lab `guihong-local-773383203000` 取得 `COMPLETED / PASS`。运行身份为 `guihong-m2-f888a5fc538c4135818a68dc6f5d1700`，边界为 `M2_MAILBOX_AND_WEB_ONLY`；M2 合同摘要 `40230cafb3046b46d3abed6e25c018ed9b87918626de1687a2f08c54a54a889b`，Plan 摘要 `c32556b4c132ff91ba49834e8920c5672e9f6b55b5656ffcf8607bde0ee266d2`，事实摘要 `52fe19bea10578e76b3bf7c076df57de376278d59d57624d10e7af5d81b46a38`，请求摘要 `4a396b2f40d4acef8bfccce17fdc746610178c102d499443e873db6d99ccc91c`。构建回执 SHA-256 为 `1327cb0e2da3b7fe61da50272b13a99d1b0b5adb28f4fbee2c5ac405add532b0`，绑定 Go 1.27.2、前端资产及三个应用二进制；bundle manifest SHA-256 为 `42ae4c020f0359f5e7cc7af274472e5393302793cba0346bdcd0fb8cac00abfb`。

16 个预封存用例全部 PASS。事实覆盖两个账户的独立成员状态与共享内容、跨账户 404、草稿版本冲突和重启恢复、回复/全部回复/转发草稿、中文 MIME 与附件、HTML 安全投影、文件名拒绝、系统目录移动与恢复、已读切换、个人分类、搜索与游标分页、桌面三滚动区、移动端浏览器返回、账户切换迟到响应隔离、附件草稿及三服务重启。真实 Edge `155.0.4283.45` 执行页面流程；外部请求为空，危险脚本未执行，恢复与已读/未读按钮均被真实点击观察。

资源守卫取得 13 个样本，其中 12 个为完整拓扑；停止原因为空。宿主峰值 `13,027,823,616 bytes`，低于 14 GiB 停止线；单个 Go 应用 RSS 峰值 `19,877,888 bytes`；容器最小内存余量 `53.61%`，最小 PID 余量 66。三应用正常停止，owned 容器、网络和三个具名卷经标签核对后精确清理；private lab 与资源见证移入本地 ignored 的 qualified-labs 归档。

同一来源事实负控 `guihong-m2-d35009f4b6a54728807e42d734c72030` 将绑定摘要改错，得到预期 `COMPLETED / INCONCLUSIVE`；`guihong-m2-2a07db045f5e494bae24a6b4225b34b5` 移除必需证据，得到预期 `COMPLETED / PENDING`。两者证明缺失或绑定错误的证据不能取得 PASS。

本 PASS 只证明精确本地源码的 M2 候选。PR、CI、受保护合入和 fresh exact-main 尚未完成，因此当前状态为 `LOCAL_CANDIDATE_PASS / NOT_QUALIFIED`，不得据此启动 M3。

## 保留的首败与被替代候选

- 首次隔离构建在 source `ded9819b0bdaa76768b30ce25affcc9dba5cbae9` 因空 Go module cache 失败；修复只在构建步骤显式执行依赖下载并保留锁文件，未改系统代理或全局 Go 配置。
- `guihong-m2-2e9fa4b8a3924886af4b90846108fc3a` 在 source `088607cc16db13eab492a53025553004b0041324` 为 `ERROR / INCONCLUSIVE`。收集器把只读服务端字段原样 PUT 回草稿 API，严格请求边界返回 `REQUEST_MALFORMED`；修复将前端和收集器都限制为具名可写字段。
- `guihong-m2-572f6e0df69c45099879506a1063c6cc` 在 source `5187832ed4e579b675ce1d3c217ad23bd1c36295` 为 `ERROR / INCONCLUSIVE`。Playwright 的字符串 `wait_for_function` 被产品 CSP 正确拒绝；修复改为直接 evaluate 轮询观察，不放宽 CSP。
- `guihong-m2-c6391fbaffde41ba8485c342080b0f19` 在 source `ddeb1057270d1e9410310a8cd5e5174ba8f3de8e` 为 `COMPLETED / INCONCLUSIVE`，仅 M2-11 失败。采集器在归档后才检查收件箱分页，观察顺序污染前提；修复把分页读回放到状态变更前，产品语义与断言未改。
- `guihong-m2-973a4d049ddb44ce8339f1b44e608849` 在 source `d1f95f187ecaf4109a6e80563cc5adc448c6a613` 的 16 个业务事实均为 true，但 Evidence 缺少 sealed request 摘要，绑定为 `INCONCLUSIVE`。修复补齐请求摘要，并保留该拒绝结果。
- `guihong-m2-5092749544a9421591ae6e8e7cfb56f4` 在 source `c1bfda39869849b763ba484948228fc139678869` 为 `COMPLETED / PASS`，但提交前合同对照发现页面没有公开“恢复”和“已读/未读切换”入口。该 PASS 不追溯改判，标为被 `0fef1ca` 候选替代；最终候选新增真实浏览器动作后重新完整取证。

## exact-main

`PENDING`。只有本分支通过 PR/CI、受保护合入，并在 fresh owned lab 对合入后的精确 `origin/main` 重建、运行、负控、资源与清理全部通过，M2 才可升级为 `QUALIFIED`。
