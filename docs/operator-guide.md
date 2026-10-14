# 归鸿工程候选操作手册

本手册适用于 Windows 单宿主、回环域 `guihong.test` 的工程候选。它不配置系统代理、DNS、防火墙、Docker daemon 或公网邮件；不提供正式生产部署承诺。

## 固定前提

- Docker Desktop 已可用；项目只创建带当前 `guihong-local-*` owner 的容器、网络和卷。
- Go `1.27.2` 位于 `D:\DevTools\Go\go1.27.2`，Python `3.10.6` 位于 `D:\python-3.10.6`，Node 位于 `D:\Node.js\current`。
- 依赖只安装到当前 checkout 的 `.artifacts` 和 `frontend/web/node_modules`。需要网络时仅给该命令显式设置 `HTTP_PROXY` / `HTTPS_PROXY=http://127.0.0.1:7897`。
- 启动前至少 2 GiB 空闲、C 盘至少 10 GiB；运行中宿主占用大于 14 GiB 连续三次即停止 owned 实验。容器内存余量、PID、OOM 与应用 RSS 继续按资源合同 1.3。

## 首次构建

在 clean checkout 根目录依次执行：

```powershell
D:\python-3.10.6\python.exe -m venv .artifacts\lab-env
.\.artifacts\lab-env\Scripts\python.exe -m pip install --require-hashes -r scripts\collector-requirements.lock
$env:PATH='D:\DevTools\Go\go1.27.2\bin;'+$env:PATH
.\.artifacts\lab-env\Scripts\python.exe scripts\go_apps.py build
```

`build` 会执行前端锁安装、前端测试与生产构建、Go 测试/vet/构建，并生成绑定 exact source 的不可覆盖 receipt。失败后保留原 attempt；源码不变时不会用第二份 receipt 覆盖它。

## 首次启动

```powershell
.\.artifacts\lab-env\Scripts\python.exe scripts\lab.py init
.\.artifacts\lab-env\Scripts\python.exe scripts\lab.py up
.\.artifacts\lab-env\Scripts\python.exe scripts\go_apps.py prepare
.\.artifacts\lab-env\Scripts\python.exe scripts\go_apps.py start
.\.artifacts\lab-env\Scripts\python.exe scripts\go_apps.py status
```

`init` 只生成项目忽略的随机凭据、owned 标识和 witness；已有 lab 时拒绝覆盖。`prepare` 只接受三套 virgin schema。三个业务服务只监听回环端口，`status` 必须逐项读到 source identity 与 READY；`NOT_RECONCILED` 需要按恢复合同处理，不能重置数据冒充健康。

## 停止、再次启动与退出

保留数据的正常停止：

```powershell
.\.artifacts\lab-env\Scripts\python.exe scripts\go_apps.py stop
.\.artifacts\lab-env\Scripts\python.exe scripts\lab.py down
```

再次启动同一代数据时不要重新执行 `init` 或 `prepare`：

```powershell
.\.artifacts\lab-env\Scripts\python.exe scripts\lab.py up
.\.artifacts\lab-env\Scripts\python.exe scripts\go_apps.py start
.\.artifacts\lab-env\Scripts\python.exe scripts\go_apps.py status
```

再次停止后，只有在已经保存所需 evidence、核对 `guihong.owner` 与 exact lab ID、并明确不再需要该代数据时，才删除该 lab 的具名卷。禁止 `docker system prune`、按端口盲杀或删除其他项目资源。资格运行由 M6 收集器保存清理读回；普通使用者可保留卷以便下次启动。

## 已证明与未证明

工程候选证明本机回环环境中的多账户、真实 SMTP、MIME/附件、异步投递、UNKNOWN/取消、分类、恢复和资源窗口。公网 MX/SPF/DKIM/DMARC、QQ/Gmail 收件结果和最终视觉均未获资格。页面可继续在 M7 做人工视觉精修，但当前功能、安全、状态与移动端路径不得因视觉待定而失效。
