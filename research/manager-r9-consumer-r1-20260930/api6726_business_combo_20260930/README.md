# Issue #8：已验 API 6726 + 原 B1/US 的最小组合接续

本包只适配交付工具与测试组合，不改公告／关系业务逻辑。旧 `284945925e6c4dd5f03cd3f5aff400798d134d2f` 的完整 31 文件置于 `original_business/`，源码、断言、41项历史日志、manifest 原字节保留。不要再使用其中固定旧 workspace pin 的 `tools/run_tests.py`；从本包根执行 `tools/prepare_combo.py`。

目标为 `6726a3dcd853246734486dc0a38fb3b5b41230f1` 的独立已验 API 候选，不是旧 R3B-only 组合。新的 `COMBINATION_PINS.json` 独立冻结这组 11 个 API 前像与 12 个组合后像，不把新旧 SHA 混成可任选的允许列表。

- 保留 workspace `35c9292d3b422c9d5a744590cc472de5bfa2da8a62d12c6382ca0d1a9b3a6168`。
- 保留 autorun `e785ae1d465175bec0517e7c3b4a8d6e16593967cba554aa0428817a85cd079b`，即使只跑 business 33 项也核对此依赖。
- 原 B1/US 的两改一增、runtime.patch 与测试断言不变。既有 R3B、WorkspaceReadError、SCHEDULED_MORNING 不回退。
- 新 API 完整 workspace 与 autorun 已从上传的精确 actual_diff + R3B 原字节重建，均匹配 writer 完整 SHA，不缺这两个文件的字节。见 evidence/API_SOURCE_READBACK.json。
- B2 当前 native 组合未适配：新上传 canonical cycle 是 RPC owner dispatch，非 8851 本地计划路径。最终候选的 cycle/RPC/router 身份未纳入 API 11-pin 回执。本工具不套旧 cycle 或旧 autorun，也不自动跑旧 B2 8 项。缺口只限制 B2；见 B2_ENTRY_STATUS.md。

## 一次 Work 命令

在本包根目录执行 WORK_ONCE.md 的一条命令，复制已验 API 到新的输出目录，只应用原 B1/US patch，然后执行原 33 项断言。原 API 输入不写入。成功范围明确为 B1/US 组合，不是 B2 接线或整个经理恢复。

## 本轮新增验证

旧 runner 在新组合上因 workspace pin 退出1，0项测试执行。新 runner 在同一新 API 核心 pin 上执行原 B1 20 + US 13：33 passed / 0 skipped。组合工具7项通过（新pin、旧字节拒绝、B2不盲套、测试身份和符号链接边界）。旧14项未重跑，旧41项仅作原交付证据保留。

作者环境 Linux / Python 3.13.5，原参考依赖不是完整 Mac API；不把此次结果当本机独立验收。未部署／合并／启调度／请求Futu。PR9保持Draft，Issue8保持Open。GitHub为唯一协作入口，无空间维护。
