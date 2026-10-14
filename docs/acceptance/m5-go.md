# M5 Go 韧性候选记录

## 本地候选

Go 候选 `395426fc3e14104dea29ac2cffe82ca59c6c5a52` 于 `2026-10-14T15:42:27.399687+08:00` 取得 M5 本地聚合 `COMPLETED / PASS`。聚合运行身份为 `guihong-m5-9cee5e1c1d224b2cb29c3a7147edcf81`；Plan 摘要 `605940fcba7c62930e17efa3ea1bb38fe978bd0c2772547c387f11dbda7b1468`，事实摘要 `c82ff2e34644eaa4900ae38496a516d7365404d7bdfc43f3ea3062afa823c8fb`，请求摘要 `5ad566d38f2822a37a87c437c12f6359c2684e7bdeb92455624dd2978ab96fd9`。构建回执 SHA-256 为 `6687be57627f28e7bddeaf906456e28122cbfe89d1d079f615a64d056929e61a`，bundle manifest SHA-256 为 `a9a1fa2cc0f5a8cd3ec0848a090ce720a0cd45f1c76ef887405a0805f61a2041`。

18 个预封存 M5 用例全部 PASS。聚合器只接受同一 source 的五份已完成 PASS：M2 `guihong-m2-e0fbe9b0282c449482e7d9eb38405db6`、M3 `guihong-m3-1979b5cfaddb426896335f9b1e7c2242`、M4 `guihong-m4-35c92eed7f464dc1bc59b06dd6eaef26`、对象生命周期 `guihong-objects-a055c5daf6174ccfbbe78e8c07f68a02`、M5 韧性 `guihong-m5r-96ecd0652ce2470fb4543d5a02826022`。五份 evidence SHA-256 与规范化事实摘要均写入聚合证据。

韧性门实际证明 Broker 暂停后的 Outbox 恢复、旧 Worker epoch/lease fencing、DATA 后 lease 过期归入 `UNKNOWN` 且不自动重复投递、毒消息隔离后后续合法消息继续处理、三服务 T0 旧快照 fail closed、T1 精确恢复，以及缺失事务账册时 `NOT_RECONCILED` 与恢复后 `READY`。对象门实际证明 PUT/GET/DELETE、引用保护、COMMIT 响应丢失、六对象有界 GC、`DELETING` 重入、损坏对象和缺账册恢复。

150 秒资源守卫取得 21 个完整拓扑样本，停止原因为空。宿主峰值 `13,974,446,080 bytes`，低于 14 GiB 停止线；Go 应用 RSS 峰值 `22,929,408 bytes`，容器最小内存余量 `17.85%`，最小 PID 余量 34。完整实验启动准入按资源合同 1.2 使用 3 GiB 空闲；运行期 14 GiB 三连停线、10% 容器内存余量、16 PID 余量、384 MiB/app 与 C 盘 10 GiB 均未改变。

错误绑定负控 `guihong-m5-9f8cc79130e44adc934d842d06459df4` 得到预期 `COMPLETED / INCONCLUSIVE`；缺证据负控 `guihong-m5-aa9298cc2e724f5e96e8d5ae2adf35b3` 得到预期 `COMPLETED / PENDING`。

从资源修订和 M5 计划封存到本地聚合 PASS 的实际墙钟为 `02:34:30.0026321`。阶段内唯一人工介入是项目所有者授权 3 GiB 启动准入修订；没有以关闭应用、改资源硬线或手工修数据取得 PASS。

## 资源合同 1.3 重开

项目所有者于 `2026-10-14T07:49:42.3361217Z` 进一步授权把未取得资格阶段的完整实验启动准入从 3 GiB 改为 2 GiB。上面的本地 PASS 仍只证明 source `395426fc3e14104dea29ac2cffe82ca59c6c5a52` 与资源合同 1.2，不转写为新合同下的 PASS。资源合同 1.3 保持 14 GiB 三连停线和其他运行门禁，并要求新 source 重新取得五个子门、18 项聚合与负控。

## exact-main 资格

[PR #14](https://github.com/NoctilumeDev/GuiHongMail/pull/14) 在资源合同 1.3 提交上通过 Go、静态合同与 Web 三项 CI，随后以 merge commit `b77cd819f94c7319dc74bf130e99f8ee63b9ee4d` 合入 main；同一提交的 [main CI](https://github.com/NoctilumeDev/GuiHongMail/actions/runs/38531212451) 三项再次通过。fresh detached worktree 实际确认 `HEAD == origin/main`，从锁文件重建 VeriTrail Core 0.13.0、收集器、前端依赖及三份 Go 二进制；构建回执 SHA-256 为 `f894ccb78d961ff70e55de5391423b44c5a2e9004e23e63c2aa196593af4356c`。

同一 exact source 在五个 fresh owned lab 取得 M2 `guihong-m2-4c84b6d54fbe4ffe9ee5c5e238d62d22`、M3 `guihong-m3-5e56fe128ab94cfda9bbe8a5c18d4f55`、M4 `guihong-m4-022c779764f74b09b8c0e2d36c824e76`、对象生命周期 `guihong-objects-085fa4b314ba4857a8795a0f99e78337`、韧性 `guihong-m5r-4e8ac0bbbabb4d2da60fb8457cf93906` 五个 PASS。独立聚合 `guihong-m5-9bc902e597c1424bb393c01fdbcc8bd2` 为 `COMPLETED / PASS`，18 项全过；Plan 摘要 `b0d5070c1649fef7df47862179f89c447c82b257a6fcdc3e7a5ae5af9268b7b9`，事实摘要 `a8c30aef122f7d5f2ae4dc2a3bd27458f2ed3fa227ad03c7bf4f1db335679b4e`，请求摘要 `27a4fa4db71c3dac549386511a0ba0cdde2ea1a9d76ea0e52d7525116fdeb406`，bundle manifest SHA-256 为 `cab5de0bd604db9b4582f68d1cfaa68e97380396d0c6eccf23ab3a9d9bf8c228`。

韧性资源窗取得 21 个完整拓扑样本，停止原因为空；宿主峰值 `13,877,383,168 bytes`，低于 14 GiB 停止线；Go 应用 RSS 峰值 `23,089,152 bytes`，容器最小内存余量 `23.87%`，最小 PID 余量 30。五轮启动前空闲量依次为 `6,098,563,072`、`3,489,071,104`、`3,849,228,288`、`4,374,609,920`、`4,008,759,296 bytes`；M3 的 `3,489,071,104 bytes` 低于旧 4 GiB 准入、但高于新 2 GiB 准入，并在完整运行门下 PASS，直接证明本次修订获得了真实可启动窗口。

错误绑定负控 `guihong-m5-32d170aed38f462ba5302b164b7b44c5` 为 `COMPLETED / INCONCLUSIVE`，缺证据负控 `guihong-m5-aff8716e5ee0454ca78b6d23c0e90a4f` 为 `COMPLETED / PENDING`。五个 lab 的应用均正常停止，其 exact owned 容器、网络和三个卷读回均为零，private witness 与标准 evidence 保留在 ignored 归档。从 1.3 授权到 exact-main 聚合 PASS 的实际墙钟为 `00:43:38.792616`；除该具名授权外没有新增人工介入。

## 保留的首败

- `guihong-m5r-f533b09b6e904584a8ccc29eba3b5f4e` 为 9/10 FAIL：100 秒只取得 14 个完整样本；只把观察时长延长到 150 秒，18 样本分母和全部资源线不变。
- `guihong-m3-b7d2a892d7f842e9bb6c5d4259eab4c7` 为 ERROR/PENDING：M4 分类下拉框使旧浏览器探针的“主题”标签定位歧义；定位收紧为名称精确匹配的 textbox，并增加守卫。
- `guihong-objects-97a5af4a9d57484c8b83b2af5de753d0` 为 ERROR/PENDING：外层误先启动三服务，owned PID 守卫拒绝对象采集器重复接管；fresh lab 改由采集器独占生命周期。
- `guihong-m5-fdc068b098044cf282b84026b2e10b06` 为 ERROR/PENDING：聚合器未识别对象门既有的 `execution` 摘要字段；修复后接受两种既有 schema，冲突仍拒绝。
- `guihong-objects-e7f2dc3b715c47a9bbd26f47b86fc2d8` 为 COMPLETED/FAIL：重启耗时使旧 GC 夹具在保护性 GC 中先被合法回收；新合同在保护性 GC 后创建专用故障对象，证明一个 `DELETING` 见证与六对象最终删除。

## 资格边界

M5 在 `b77cd819f94c7319dc74bf130e99f8ee63b9ee4d` 取得 `QUALIFIED`。资源合同 1.2 的本地候选与首败保持历史绑定；资源合同 1.3 的 PR/CI、main CI、fresh exact-main 重建、五个子门、18 项聚合、负控和 owned 清理已经闭合。该资格只覆盖 M5 有限反例与恢复义务；M6 工程验收仍需独立施工和资格证据。
