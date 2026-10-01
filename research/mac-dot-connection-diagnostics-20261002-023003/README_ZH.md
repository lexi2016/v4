# ChatGPT Mac dot Computers 连接诊断包

这是 2026-10-02 的只读快照。本机环境与进程元数据在 02:36–02:59（UTC 2026-10-01 18:36–18:59）收集。没有触发用户侧点击或强制复现，也没有操作应用、网络、服务或设置。

## 已确认的本机事实

- `/Applications/ChatGPT.app`：版本 `26.928.31416`，build `12553`，bundle `com.openai.codex`，可执行文件 `ChatGPT`。
- macOS `26.6.2`，build `25G83`。
- 采集时 ChatGPT 主进程、3 个 Codex Service 进程和 `SkyComputerUseService` 进程存在；可执行路径、启动时间和各 bundle 版本见 `environment.json`。没有采集进程参数。
- 已审阅的干净预任务 t1 日志来源为 `codex-desktop-<session-id-redacted>-59071-t1-i1-002131-0.log`（仅 UUID/session 标识段已脱敏，其余 basename 保持原样），共审阅第 1–71 行，嵌入时间范围为 UTC `2026-10-01T00:21:34.186Z` 至 `2026-10-01T18:26:45.442Z`，早于主控提供的 `18:29:44Z` 截止。该窗口未能确认 dot 状态、请求体、响应状态/错误、请求标识或握手/关闭结果；未发现可用于定位 dot 失败的具体事件。
- 主 t0 日志在诊断期间持续增长。截止之后的记录整体排除；部分记录带有与当前诊断上下文相似的 session 风格标识，可能来自本任务的对话、工具或 session 记录。准确事件类型和来源 `CANNOT_CONFIRM`。这些记录不作为产品连接遥测，也没有保留标识值或条目计数。

## UI 来源与边界

当前 dot UI 状态由主控转述，未由本采集者直接观察，也没有截图：`嘻嘻 → Computers → lexideMacBook-Pro.local` 显示 `Offline`，`Allow` 禁用，cloud 显示 `Connected`。此前出现过 `Couldn’t finish setup` 和 `无法更新远程控制状态`；UI 观察的精确时间未提供。主控提供的 `18:29:44Z` 是日志排除截止，不是截图或 UI 事件时间。

主控尝试用 CUA 读取界面时，工具返回：`Computer Use is not allowed to use app com.openai.codex for safety reasons.` 因此没有截图或独立 UI 状态回执。这是工具安全限制，不能据此判断 macOS 权限被拒绝。

## 当前判断

用户报告的症状指向 dot 显示的目标主机状态或 Allow 状态，但具体失败步骤仍是 `CANNOT_CONFIRM`。现有干净日志没有可归属到 dot 的请求或状态回执，当前 UI 也没有独立截图。不能判断问题发生在本地注册、认证、连接、服务端状态更新或页面刷新；也不能认定 dot Computers 等同于 Codex Remote `remoteControl`、Work Sync 或 Responses 模型 WebSocket。

## 需要官方团队核实

请以 `lexideMacBook-Pro.local`、ChatGPT `26.928.31416` / build `12553` 和用户实际看到 Offline 的时间为线索核查 dot Computers。该 UI 时间在此包中未记录；`18:29:44Z` 仅为日志排除截止，不应当作 UI 事件时间。请提供 dot 所属服务、主机注册/认证/connect/disconnect 状态、Allow 禁用原因、实际请求与响应状态/错误，以及 WebSocket 握手/关闭结果；请分别给出客户端标识与服务端 request ID。此包没有可安全关联到 dot 的请求标识。

## 缺口

- 新鲜的 dot 页面截图、用户侧真实点击或直接 UI/API 回执：`CANNOT_CONFIRM`。
- `remoteControl` enable/status/read/changed 的实际请求体、响应体、HTTP 状态和错误：`日志未提供`。
- 属于 dot 的主机注册、认证、connect/disconnect 状态和 Allow 禁用原因：`CANNOT_CONFIRM`。
- 客户端标识、服务端 request ID、主机握手/关闭结果及服务端关联：`CANNOT_CONFIRM`。
- dot Computers 与 Codex Remote、Work Sync、Responses 模型 WebSocket 的 owner 映射：`CANNOT_CONFIRM`。

`redacted_logs.txt` 记录已审阅日志范围和排除说明；`timeline.csv` 提供时间轴；`environment.json` 提供机器可读环境与证据字段。包内没有完整日志、账号数据、Cookie、Authorization、token、对话内容、被排除记录的标识值或命令行参数。`CANNOT_CONFIRM` 是当前结论，不是根因确认。
