# 第三轮：S3 请求重定向边界

基线：`main@98867d1982079a5ea8ab7b8fe11fdcedfafeca5b`。2026-10-27 的有限验证只处理当前 Go S3 客户端，不变更 M0 合同、依赖、服务权责或历史验收证据。

## 问题与最小修复

`NewS3Client` 只接受固定的 `http://127.0.0.1:port` 入口，但原 `http.Client` 会跟随重定向，导致一次已签名的对象操作额外请求另一个地址或对象。初始地址检查不能约束这次后续请求。

客户端现在通过 `CheckRedirect` 返回 `http.ErrUseLastResponse`，保留本批有效 Location 的第一份 3xx 响应，并沿用既有处理：`Ready` 返回 false，`Get/Put/Delete` 返回原操作及状态码的 `S3StatusError`。不产生第二次请求、不重新签名、不增加重试。畸形 Location 仍可能由 `net/http` 提前返回请求错误，不把所有 3xx 一概归为同一种错误。

## 同条件验证

两个由测试拥有的回环 HTTP 端点、虚构对象内容；不访问外网或真实邮件。新增测试在原源码及修复源码上分别执行：

```text
go test -count=1 -json ./internal/platform -run TestS3Client
```

| 条件 | 原源码 | 修复后 |
| --- | --- | --- |
| HEAD/GET/PUT/DELETE × 301/302/303/307/308，目标端点应收到 0 次请求 | 20 个叶子案例均失败，目标端点各收到 1 次 | 20 个均通过，原端点 1 次、目标 0 次 |
| 同主机的相对对象跳转 | 失败，另一个对象被请求 | 通过，不改变对象坐标 |
| 原有签名、Ready/PUT/GET/DELETE 正常流程及非法对象键对照 | 2 项通过 | 2 项通过 |

Go JSON 另外包含父测试汇总；原输出的 22 个 fail 事件不代表 22 个独立缺陷。修复后共 23 个叶子案例通过。

本地 Go 1.27.2 / Windows：`go test -count=1 -json ./...`、`go vet ./...`、`go build ./cmd/...` 通过。全包输出 45 个 pass 事件包含父测试，5 个没有测试文件的包不算执行过测试。静态合同、治理检查普通与优化模式各 21 项、MySQL 代理 6 项、工程护栏 15 项、分类器 3 项均通过。

保留的原始输出 SHA-256：

| 原始文件 | SHA-256 |
| --- | --- |
| `s3-before.jsonl` | `465b239b88e9d7df32cbf129c0a5a264a83718af6c43ddc7db82d29dbb3743de` |
| `s3-after.jsonl` | `6229f3b3d9edb2e83f8449fbea293499821c7b5a13703439975590b6bdfa9e96` |
| `go-all.jsonl` | `d03daa8a39708c91b63358329241ad85a4db77f5fdecb8b0a8524901cd134860` |

原源码失败、新源码通过、测试源码及执行输出保存在本批独立证据包。重新验证负控时，使用独立基线检出，仅放入相同测试文件；不能把编译、下载或超时失败当作预期拒绝断言失败。

## 原候选的独立阻塞与结论边界

以下保留 `4a1748159934060f9f12c5e7bb4728a4a543ece6` 候选当时的阻塞和范围。后续经授权独立处理依赖阻塞，见 [2026-10-27 依赖维护](dependency-maintenance-20261027.md)；不回写原始失败或继承为安全结论。

[主线定期 CI 40305495179](https://github.com/NoctilumeDev/GuiHongMail/actions/runs/40305495179) 的 Go backend 已在本候选之前失败：Go 测试、vet、构建完成后，依赖门禁报告 `npm-web: findings changed; review required`。保存的 artifact `12643040322` SHA-256 为 `38ce4e1545b576c1f4020bae07dbc4fc40485ef3ec19f6e46b13d4eaa4cb58e2`。

原锁文件中的 `jsdom 29.1.1 → undici 7.30.0` 开发依赖新增三条公告：

- [GHSA-f72v-6w45-q472](https://github.com/nodejs/undici/security/advisories/GHSA-f72v-6w45-q472)
- [GHSA-4qv8-2p9j-2685](https://github.com/nodejs/undici/security/advisories/GHSA-4qv8-2p9j-2685)
- [GHSA-xjj6-f33q-929c](https://github.com/nodejs/undici/security/advisories/GHSA-xjj6-f33q-929c)

输入哈希与 129 包清单未变，Go 两平台的原三项公告也未变。上述 npm 候选由 NoctilumeDev/GuiHongMail 维护者独立处置，状态为 `UNRESOLVED`，后续核对触发路径与最小依赖候选。不以开发依赖身份自动豁免，不在本 PR 改依赖、更新放行基线或接受风险；候选必须仍受现有必需检查约束。

本批证明的是 HTTP 客户端的请求边界，未重跑真实 SeaweedFS、SMTP、MySQL、RocketMQ 或故障恢复全链路；不声称取得新系统资格。Go 标准库 `GO-2026-6809` 仍是独立未解决事项，不因关闭重定向就宣布修复。本批不重开 M7/E1，不创建 Release；公开候选 CI、受保护合并及新 main 验证仍需各自取得结果。
