# 归鸿独立核验与 VeriTrail 接入边界 0.1

**M0 draft — NO RUN CLAIMS**。

参照 [Qixu 验迹接入合同](https://github.com/NoctilumeDev/Qixu/blob/main/docs/verification.md)，本项目先由业务自己确定 SMTP/邮箱不变量，再用项目拥有的 collectors 制作标准 Evidence；Core 只按人事先封存的条件判定充分性。

当前已知公开版本 [VeriTrail Core 0.13.0](https://github.com/NoctilumeDev/VeriTrail/releases/tag/v0.13.0) 可以作为候选固定依赖。**三服务+MQ+对象存储不是 Starter 0.2 的受支持预设**；不能调用 Starter 伪称通用自动编排。使用公开 AcceptancePlan/标准 Evidence/独立 Core 0.13 接口前，M1 先做真实兼容探针；不满足合同直接停止并修复适配方案，不私改 Core，也不利用未发布 O/T 插件冒充现成功能。

## 实际事实的所有权

- Source-run 产物：真实 SMTP transcript（删敏）、原始受控邮件 MIME digest、真实 MySQL 行/锁/回执、MQ 与 MinIO 元信息、容器/进程身份/退出码、浏览器 network/DOM/截屏。
- Producer 只将 source facts 规范化为 Evidence；不准预先写 `mail_delivered=true`、`all_passed=true` 等跨来源复合结论假冒 Core verdict。
- 每个 Plan 在首次运行前封存 source SHA、工具链、拓扑、环境、最大 payload、目标、受控变量、允许的故障窗口、停止线和必需断言。输出各自 Run ID、Evidence/Bundle/hash 与失败原件。
- 需要证明跨 Evidence 的身份绑定时，由 Core 的明示 assertion/binding 表达；不允许凭某次采集器都写了同样字符串就当成独立绑定证明。
- 将执行状态 `COMPLETED/ABORTED/ERROR` 和有限 Verdict `PASS/FAIL/INCONCLUSIVE/PENDING` 分开存；环境阻断是环境事实，不能据此声明产品失败或成功。

## 正向与负向最低链路

1. 固定发送者 A、收件者 B、原始 MIME、附件摘要、固定 token/消息身份；在本域真实 TCP SMTP 完成事务。
2. Mailbox SendIntent、Outbox、DeliveryJob、Ingress spool、Import 事实和 B 的 MailboxEntry 均有独立来源 ID；在测试时间预算内收敛，但不压缩成一步成功。
3. 两个客户端登录 B 的不同会话、查看/已读/归档；A 的状态和 B 的状态不混同。
4. 控制组：正常发信；处理组：只改变一个指定故障（例如 SMTP DATA `250` 响应丢失）；恢复组：清除故障、沿原键恢复，验证没有悄悄换义务。
5. 负向观察：把 envelope recipient/原 MIME/SHA/来源身份中的一个改错，保证 verifier 能明确拒绝或 `INCONCLUSIVE`；收集器错误与真实产品错误分开。
6. M4 对分类规则和算法反馈作双账户、显式规则优先、人工作为最终决定、训练版本和建议不越权验证；M5 按失败机制进行有限反例击打；M6 从固定 SHA 做独立测试者和产品视角的有限复核，审阅者不能直接采用施工者的“全部通过”自评。

## 计时及终止

`docs/continuous-run.md` 绑定 M1 实际开工、M6 门禁完成/阻断的 UTC 时点和人工干预事实。Core Verdict 只服务封存条件，与工期快慢无关。M6 完成后停止等待 M7 人类审美精修，不自动替用户开启。

## 每类陈述的证明上限

`UI sent toast` < `Mailbox submitted` < `Delivery worker observed next-hop SMTP 250`；即使下一跳是受控接收服务，除非独立阅读源事实，否则不能宣传最终用户已收/已读。SMTP 真实失败/恢复的证据是原始会话、持久事实、重放路径，不是只看日志里出现“success”。浏览器截图只能证明某状态可见，不能单独证明 SMTP 真实执行。

独立复验不应构造一个只复制生产验证器算法的“oracle”；业务预期来自预冻结不变量与独立 SQL/原字节/SMTP transcript。原始失败记录不覆盖，后续 PASS 取得新的版本与身份。
