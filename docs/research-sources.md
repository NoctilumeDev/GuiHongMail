# M0 参考来源与风险迁移

仅记录已经阅读的官方合同、源码与维护记录。外部事故不证明归鸿已有缺陷，修复记录也不授予归鸿资格；各机制在对应阶段用预封存用例验证。

| 来源 | 已读坐标/观察 | 归鸿适用义务 |
| --- | --- | --- |
| [期序接入合同](https://github.com/NoctilumeDev/Qixu/blob/a27ccd1fefc95a6d761be0d1c92cbd44e5c22f3e/docs/verification.md) | 公开 Core 0.13.0、项目采集器、封存先于观察 | A01及各阶段真实source绑定；不照搬期序业务/测试数 |
| [期序恢复合同](https://github.com/NoctilumeDev/Qixu/blob/a27ccd1fefc95a6d761be0d1c92cbd44e5c22f3e/docs/contracts/m7-restore-fence.md) | 旧库不回滚外部事实，独立账册/marker及NOT_RECONCILED | A16；独立正常控制、旧快照与缺账册机制 |
| [素简记服务边界](https://github.com/NoctilumeDev/PlainJournal/blob/99f049fdc75581af9a608f7a24c40c26369959c3/docs/02-service-architecture.md) | schema/Entity/事实隔离，通知不拥有业务结果 | 三服务所有权；邮件Worker源码只作历史参考，不直接复制其通用失败处理 |
| [JPyxis宪法](https://github.com/NoctilumeDev/JPyxis/blob/9632a4f45c2190da6440e455667090fdd88e4a69/docs/architecture/constitution.md) | 角色而非语言拥有状态，替换端口需真实合同 | 存储端口/投递资格/未来能力不压迫本轮 |
| [Core 0.13.0](https://github.com/NoctilumeDev/VeriTrail/blob/v0.13.0/docs/81-pc1-acceptance-core-implementation.md) | 标准Evidence、明确Plan绑定与四态，未知但结构合法的adapter不等于事实可信 | M1公开包探针及每阶段原生collector，不使用Starter编排三服务 |
| [RFC 5321](https://www.rfc-editor.org/rfc/rfc5321.html#section-4.2.5) | DATA成功回复转移责任；拒绝后不能投递；退信空reverse-path避免循环 | A09/A11接纳、拒绝、UNKNOWN、退信责任 |
| [Apache James维护记录](https://github.com/apache/james-project/blob/master/CHANGELOG.md) | 3.7.1列出JAMES-3787入队错误导致邮件丢失的修复；3.7.5记录SMTP smuggling与CRLF加固 | A08/A09入队责任不丢；A03/A10协议解析profile |
| [Stalwart维护记录](https://github.com/stalwartlabs/stalwart/blob/main/CHANGELOG.md) | 0.16.25记录空match队列配额未执行、日志无限增长、重复训练样本清理影响保留样本 | A15容量/日志预算；A14反馈训练身份与去重 |
| [Haraka](https://github.com/haraka/Haraka) | SMTP hooks与queue责任分离，SMTP server不是邮箱存储 | 协议库必须把最终成功回复放在我方耐久接纳之后 |
| [MinIO官方仓库](https://github.com/minio/minio) | 2026-10-13读回archived=true；网页显示2026-04-25归档、源码分发 | 用户已批准SeaweedFS，不继续沿用旧latest假设 |
| [SeaweedFS 4.48候选](https://github.com/seaweedfs/seaweedfs/releases/tag/4.48) | 公开release存在；具体验收及镜像摘要待M1 | A04/A05单机S3真实权限、重启、GC与对账 |

来源链接中 main/master 会变化，进入实际故障用例时重新锁定引用版本/提交/原字节摘要；不从搜索摘要推定已经复现。来自用户私有会话的决定保留在项目授权账册，不复制个人聊天原文到公开资产。
