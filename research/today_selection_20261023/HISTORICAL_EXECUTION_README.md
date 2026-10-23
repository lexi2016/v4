# 2026-10-23 Mac 本地选股执行档案

用途：`HISTORICAL_EXECUTION_EVIDENCE`。本包记录已发生的 Mac R3／原255公式、RAW_UNADJUSTED、2026-01-01 至 2026-10-22 执行；不表示安装、部署或未来可复用入口。

`registry.py` 保留原执行字节，其中错误的 Windows／QFQ 标签已由26条 append-only CORRECTION 修正。有效语义以 `MAC_EXECUTION_SUMMARY.json` 及其 correction receipt SHA 为准。`correct_mac_registration.py` 是该历史 execution 的一次性补正程序，不能用于新运行。

新运行必须另建合同、准确绑定代码／输入及 Mac 口径，并在执行前登记真实 START；使用显式 profile 的新登记实现，不沿用旧 helper 默认字段。本地 `mac_registry.py` 已用于新阶段的准确登记；本档案不作安装、部署或未来复用声明。原5494只结果、数据、公式与候选CSV保持原字节。
