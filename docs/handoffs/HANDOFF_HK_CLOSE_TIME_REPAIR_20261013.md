# 20261013 港股收盘时间校验修复

目标：仅修正 16:10 港股收盘采集/缓存时间判断，恢复当天复盘与 8873 显示，接入原定时任务。用户要求主助手直接处理；本批没有独立 Reviewer，不声明独立 REVIEWED。

## 根因与最小变更

原 `ops/collect_hkconnect_close_snapshot.py:185` 及 `infrastructure/hkconnect_close_store.py:79` 要求每只股票 `update_time >= 16:10`。富途该字段是当前价格更新时间，收盘后查询的价格仍可能最后更新于 16:00 或收盘竞价期间。

- 采集器保留当天查询、16:10 后查询、股票时间可解析及同日约束，移除股票更新时间必须晚于 16:10 的判断。
- 缓存校验对 `source_capture.queried_at` 检查同日及 16:10 后，保留逐行原始时间、日期、来源 SHA。未改交易、阶段算法、模型或页面。
- 官方字段说明：https://openapi.futunn.com/futu-api-doc/quote/get-market-snapshot.html

源码根 `/Users/lexi/Desktop/学习/v4_app`；GitHub 基线 `d9458ee3969fa2af47e6c0be5670fddf6fe3d7e7`。本批与基线三个文件前像完全一致，未夹带其他本地改动。

| 文件 | 修改前 SHA256 | 修改后 SHA256 |
| --- | --- | --- |
| ops/collect_hkconnect_close_snapshot.py | ff97600d73ce1d72550e4b8e4064338323d566039cf772ee97a046d43d7c2e38 | 34651399051465d4e13364c7b8db16fdd6c46abe23135f1f87d79c4800b163a9 |
| infrastructure/hkconnect_close_store.py | a3ce27b1cacd1c50bf41866d5b7ec079b97f752b57518aedfaf25cd7b65dc219 | 2dd564b561381f97698aca535b44c8e51fea45d197e29200f1c1096adfb53667 |
| tests/test_close_review_producer.py | 99b3d9f025aebf69b0e047b79f67aa644f194030100fc306aa85c2b0afbb3246 | 55307431f56075539ad93197453bbc6dca897b8e2489d1b2ce82652af3256b9e |

## 验证及恢复

证据目录 `/Users/lexi/Desktop/学习/agents调试/V4_HK_CLOSE_TIME_REPAIR_20261013`，原始行情仅留本地。

- 修改前回归 3 个预期失败，见 `red.log`。修改后 canonical 四文件测试 31 passed：`test_close_review_producer.py`、`test_close_review_verified_inputs.py`、`test_hk_close_daily_binding.py`、`test_close_review_slice.py`，见 `tests_canonical.log`。
- 运行包同套测试 22 passed / 9 failed；9 项均为旧 scheduler 包内的 API 读回兼容测试。未修改的运行基线复跑同样 9 failed / 2 passed，见 `tests_runtime_baseline_api.log`，没有借机替换 scheduler 中的 API。实际 8873 使用独立现役 API，读回验收通过。
- 测试方式：Python 3.14 运行 `-m pytest -q --basetemp=<证据目录下隔离目录> <上述测试路径>`。当前运行虚拟环境 `/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python`；本批直接执行测试，不称独立复验。
- 原采集命令 `-B -m ops.collect_hkconnect_close_snapshot --data-root <v35 state/data> --date 20261013` 成功；随后原 `ops.build_close_review` 使用现役 `v4 state/stage/selection` 发布复盘。
- 今天真实采集时间 `2026-10-13T16:54:21+08:00`，698/698 同日股票，原始价格更新时间范围 09:20:09—16:08:25，未改写时间。
- 快照 SHA `36ab5af7d335efd2c1fe297258ffc9d06d5c4773a39d4935b422575595e66ce2`；复盘 SHA `b7f52f3d592e1c83ded107467155c597f5ba59abc359edffa023a30cc006c90b`。
- 原 `FixedExecutorRegistry._hk_connect_close_review` 真实子进程手动复跑成功，一次尝试；复用同日缓存，不重复抓取。`registered_workload_manual.json` 是手动验证，不是自然回执。
- API_VERIFIED：`/api/v3/review?date=20261013` 返回 Top20=20、港股通=698、模型候选=100、阶段观察=70。
- UI_VERIFIED：刷新用户的 8873 页面，点击第9项16:10入口，看到当天 Top20 全部20行、0.2命中6/20、部分观察并集6/20、70条/31个去重代码/7阶段；`CLOSE_REVIEW_ARTIFACT_MISSING` 消失。证据 `ui.txt`、`ui.png`。

## 部署与剩余边界

沿实际 manager-workbench v8 scheduler 克隆，只有上述两个业务源码替换，保留现役其他配置和暂停设置。当前 release：`hk-close-time-20261013-r1`。

- 实际应用根 `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-close-time-20261013-r1/app`。
- manifest SHA `03f7d1d6f0897b66c074cc30ecfd8d5920919b84d0cb5df97ee11bf8e18948cd`。
- LaunchAgent `com.lexi.v35.scheduler` 已启动；读回 PID 13673、DAEMON_READY 17:03:53、源码 SHA 与本次 canonical 一致。部署回执 `deployment.json`、`launchctl.readback.txt`。
- 首次 Desktop 候选启动受 macOS 目录访问限制（exit126），已将同一代码部署至现有 Application Support releases 目录并验证进程正常；未修改系统权限。
- 今日16:10自然运行原失败仍保留；今日恢复为 MANUAL。下一交易日自然时段尚未发生，NATURAL_SLOT_UNVERIFIED。已安排本聊天2026-10-14 16:16单次回查（automation-3）。
- 复盘状态仍为 MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE：阶段观察数据的历史盘口、PIT等原有缺口不被此收盘修复补造或升级。正式七阶段并集仍不可确认。
- 保持 RESEARCH_ONLY=true、production_allowed=false、buy_gate_updated=false、orders_sent=false；8910未改动。

GitHub 同步仅三个必要文件和本文，目标私有分支 `codex/hk-close-time-fix-20261013`；最终 commit/ref 与文件 blob 读回写在本地 `github_sync.json`，不上传运行行情或完整产物。
