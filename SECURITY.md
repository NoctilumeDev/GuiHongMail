# 安全边界与报告

归鸿首轮仅支持受控本机 Web 与 SMTP，不宣称互联网部署、零漏洞或恶意附件完全检测。安全要求以[安全合同](docs/contracts/security.md)、[投递](docs/contracts/delivery-lifecycle.md)、[存储](docs/contracts/storage-lifecycle.md)及[恢复](docs/contracts/recovery.md)为准。

重点保护账户/会话、每用户邮件和附件、BCC、SMTP 接纳责任、内部事件及存储凭据。未经授权读取/发送、open relay、HTML/附件执行、CRLF/MIME 解析歧义、无界资源、秘密公开、过期 Worker 写入和恢复后错误重投属于核心审查范围。

报告应提供受影响提交/版本、受控合成账户、最小触发与预期不变量；真实私信、附件、票据和密钥不得发入公开 issue 或资产。原始私有事实放项目忽略目录；公开报告只提供必要脱敏材料。没有复现时标明静态推导，不把工具或夹具错误当已验证产品漏洞。
