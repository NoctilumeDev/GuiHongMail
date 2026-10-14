# M5 Go 韧性候选记录

## 本地候选

Go 候选 `395426fc3e14104dea29ac2cffe82ca59c6c5a52` 于 `2026-10-14T15:42:27.399687+08:00` 取得 M5 本地聚合 `COMPLETED / PASS`。聚合运行身份为 `guihong-m5-9cee5e1c1d224b2cb29c3a7147edcf81`；Plan 摘要 `605940fcba7c62930e17efa3ea1bb38fe978bd0c2772547c387f11dbda7b1468`，事实摘要 `c82ff2e34644eaa4900ae38496a516d7365404d7bdfc43f3ea3062afa823c8fb`，请求摘要 `5ad566d38f2822a37a87c437c12f6359c2684e7bdeb92455624dd2978ab96fd9`。构建回执 SHA-256 为 `6687be57627f28e7bddeaf906456e28122cbfe89d1d079f615a64d056929e61a`，bundle manifest SHA-256 为 `a9a1fa2cc0f5a8cd3ec0848a090ce720a0cd45f1c76ef887405a0805f61a2041`。

18 个预封存 M5 用例全部 PASS。聚合器只接受同一 source 的五份已完成 PASS：M2 `guihong-m2-e0fbe9b0282c449482e7d9eb38405db6`、M3 `guihong-m3-1979b5cfaddb426896335f9b1e7c2242`、M4 `guihong-m4-35c92eed7f464dc1bc59b06dd6eaef26`、对象生命周期 `guihong-objects-a055c5daf6174ccfbbe78e8c07f68a02`、M5 韧性 `guihong-m5r-96ecd0652ce2470fb4543d5a02826022`。五份 evidence SHA-256 与规范化事实摘要均写入聚合证据。

韧性门实际证明 Broker 暂停后的 Outbox 恢复、旧 Worker epoch/lease fencing、DATA 后 lease 过期归入 `UNKNOWN` 且不自动重复投递、毒消息隔离后后续合法消息继续处理、三服务 T0 旧快照 fail closed、T1 精确恢复，以及缺失事务账册时 `NOT_RECONCILED` 与恢复后 `READY`。对象门实际证明 PUT/GET/DELETE、引用保护、COMMIT 响应丢失、六对象有界 GC、`DELETING` 重入、损坏对象和缺账册恢复。

150 秒资源守卫取得 21 个完整拓扑样本，停止原因为空。宿主峰值 `13,974,446,080 bytes`，低于 14 GiB 停止线；Go 应用 RSS 峰值 `22,929,408 bytes`，容器最小内存余量 `17.85%`，最小 PID 余量 34。完整实验启动准入按资源合同 1.2 使用 3 GiB 空闲；运行期 14 GiB 三连停线、10% 容器内存余量、16 PID 余量、384 MiB/app 与 C 盘 10 GiB 均未改变。

错误绑定负控 `guihong-m5-9f8cc79130e44adc934d842d06459df4` 得到预期 `COMPLETED / INCONCLUSIVE`；缺证据负控 `guihong-m5-aa9298cc2e724f5e96e8d5ae2adf35b3` 得到预期 `COMPLETED / PENDING`。

从资源修订和 M5 计划封存到本地聚合 PASS 的实际墙钟为 `02:34:30.0026321`。阶段内唯一人工介入是项目所有者授权 3 GiB 启动准入修订；没有以关闭应用、改资源硬线或手工修数据取得 PASS。

## 保留的首败

- `guihong-m5r-f533b09b6e904584a8ccc29eba3b5f4e` 为 9/10 FAIL：100 秒只取得 14 个完整样本；只把观察时长延长到 150 秒，18 样本分母和全部资源线不变。
- `guihong-m3-b7d2a892d7f842e9bb6c5d4259eab4c7` 为 ERROR/PENDING：M4 分类下拉框使旧浏览器探针的“主题”标签定位歧义；定位收紧为名称精确匹配的 textbox，并增加守卫。
- `guihong-objects-97a5af4a9d57484c8b83b2af5de753d0` 为 ERROR/PENDING：外层误先启动三服务，owned PID 守卫拒绝对象采集器重复接管；fresh lab 改由采集器独占生命周期。
- `guihong-m5-fdc068b098044cf282b84026b2e10b06` 为 ERROR/PENDING：聚合器未识别对象门既有的 `execution` 摘要字段；修复后接受两种既有 schema，冲突仍拒绝。
- `guihong-objects-e7f2dc3b715c47a9bbd26f47b86fc2d8` 为 COMPLETED/FAIL：重启耗时使旧 GC 夹具在保护性 GC 中先被合法回收；新合同在保护性 GC 后创建专用故障对象，证明一个 `DELETING` 见证与六对象最终删除。

## 资格边界

当前结论仅为 `LOCAL_CANDIDATE_PASS / NOT_QUALIFIED`。仍需受保护 PR/CI、合入 main、fresh exact-main 重建、五个子门、聚合、负控和 owned 清理闭合，才可把 M5 标为 `QUALIFIED` 并开始 M6。
