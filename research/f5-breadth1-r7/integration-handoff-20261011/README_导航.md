# R7 实际接口集成问题包导航

此目录是供 Chat 修复与独立复核使用的最小问题包。入口先读 `CHAT_REQUEST_CN.md`，再按本文件看目录。源代码、控制、回执均按原字节复制；完整 `EXPERIMENT_REGISTRY.jsonl`、原始行情/数组、模型权重和密钥均未打包。

## 当前状态

- 当前 R7 源码映射包含 runner SHA `49b7d01ab6dff04ed5130a55466826804589569b2ccd13d698a7dfe8df61b673`；7 个模块逐文件见 `PACKAGE_MANIFEST.json` 与 `source/`。
- 外部上传的 R7 安装包只通过 `original_chat_bundle/UPLOAD_POINTER.json` 指向；其中的安装 manifest/runbook 已复制以便查阅。
- 离线 84 项验证曾通过，但真实链路仍有两次预目标/准入集成失败，详见 `actual_pipeline_failure_01/` 与 `_02/`。离线/mock PASS 不能替代当前真实接口预检查。
- 只读预检查 01/02 都已真实登记并终止为失败；完整 reviewer stdout、stderr 与 terminal 见 `probe_01/`、`probe_02/`。
- 预检查 03 的代码、合同和绑定已准备，但从未启动：`CONTRACT_ONLY_NOT_COUNTED`，见 `probe_03_contract_only/PREPARATION_STATUS.json`；不声称它通过或失败。
- R7 逻辑准入 debit 保持 1，已消耗且不退款；当前 fit/predict/model-load/truth 都为 0，状态 `NO_FIT`。失败事件和原始回执保留。

## 文件导航

| 目录 | 内容 |
|---|---|
| `source/` | 当前 7 个 R3/BREADTH1 源模块，runner 为 49b7… |
| `official_registry/` | 官方 adapter、execution guard、builder、validator；只含 6 条精确执行 ID 匹配的事件行与 registry 元数据快照 |
| `controls/original_r7/` | 已消耗的 R7 原合同、binding、read release/plan、grant、scope lock |
| `controls/resume_v2/` | 当前 resume authorization/control graph 与 registered audit contract/binding |
| `probe_01/`, `probe_02/` | 实际只读 probe、注册 wrapper、完整输出和终态 |
| `probe_03_contract_only/` | 未启动的第三份预检查准备件及 CONTRACT_ONLY 状态 |
| `actual_pipeline_failure_01/`, `_02/` | 两次真实 pipeline invocation 的命令回执、日志与终态 |
| `package_application/` | 用户包 pin/apply/post-apply 及离线 84 项状态回执 |
| `original_chat_bundle/` | 原用户包 manifest、runbook 与两层 SHA 的只读指针 |

## 可复核范围

从原始 registry excerpt 只复制了三个执行 ID（R7 实际 action 与预检查 01/02）对应的原始 JSONL 事件。当前 registry 完整文件 SHA/大小及 `_03` 事件数=0 记录在 `official_registry/REGISTRY_SNAPSHOT.json`；全 registry 不在本包。`PACKAGE_MANIFEST.json` 列出每个打包文件的原路径、大小和 SHA；manifest 自身不对自身递归列 hash。
