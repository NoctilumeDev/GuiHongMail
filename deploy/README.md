# 归鸿单机实验

配置固定镜像与回环端口，版本/预算见 [M1 合同](../docs/m1-plan.md)。只允许一套完整 lab；不共享原有项目 schema/topic/data。三个应用稍后在 M1 建立，当前容器配置本身不授予底座资格。

使用现有 Python 3.10 和已启动的 Docker Desktop，从仓库根目录显式执行：

```powershell
python -B scripts/setup_collector.py --proxy http://127.0.0.1:7897
.artifacts/lab-env/Scripts/python.exe -B scripts/lab.py init
.artifacts/lab-env/Scripts/python.exe -B scripts/lab.py up --storage-only
.artifacts/lab-env/Scripts/python.exe -B scripts/veritrail_storage.py
.artifacts/lab-env/Scripts/python.exe -B scripts/lab.py down
```

`up` 不带 `--storage-only` 时明确启动全部中间件；不会自动创建 Java 应用或把停止的其他项目容器拉起。下载代理仅作用于安装进程，loopback S3 请求明确禁用代理。启动由源合同与门禁控制，`scripts/check.py all` 不自动启动实验。

`init` 生成随机 owner 和忽略的 `.artifacts/lab` 中实际凭据，拒绝覆盖既有目录。服务使用各自 schema、S3 凭据/桶；只能经 S3 到对象服务，后台接口不映射。数据库数据、对象数据分别由具名 volume 保存，恢复 witness 在 lab 根的独立目录。

`down` 验 owner 后停止并删除本 lab 容器/网络，保留数据卷与 witness。**本命令不会删除邮件数据**。最终删除持久数据要经单独的具名处置流程，不能用 `down -v`、prune 或目录年龄替代责任核对。若名称、标签、端口或归属不能确认，停止操作。

S3 资格探针使用合成字节，先封存 Plan 再做真实操作，保留首次非 PASS。正常 PASS 只清理自己的资格对象；负向控制和失败的对象暂留，后续按具名记录处理。三服务、MySQL 对象引用与恢复、身份和 SMTP 资格尚未完成前，不能宣称 M1 通过。
