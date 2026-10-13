# 20261013 港股早盘富途恢复 R11

已恢复 8873 的 `20261013 / STAGE_0930_0935`：精确 D-1 Top100 输入，富途 100/100，每只 09:31–09:35 共 5 根分钟线，原四路选择器生成 10 条 NO_BUY 观察行。涨幅、支撑、压力、失效位已在实际页面确认；A 股原 10 条 receipt 内容完全保留。

根因和最小修改：
- `stage_center/_runner_parts/slot_execution.py` 重新传递已有同日恢复标记，并恢复旧版对兄弟市场已验证 raw 的合并，避免仅补港股时 bundle 市场集合报错。
- `stage_center/acquisition.py` 在 canonical 保留该恢复字段；现役旧版已具备此字段。
- `stage_center/_live_collectors_parts/hk_minute.py` 早盘复用已有富途桥接；补采保留历史盘口缺失，不重新用当前盘口筛早盘。
- `upstreams/v3_shared_data/scripts/live_acquisition/futu_bridge.py` HK 沿用已成功参数：首次推送、K_1M、AuType.NONE、1000 根后精确裁窗；A 参数保持。增加实际采集时间和返回行 SHA。元数据解析沿用 raw_decode，兼容尾随供应商日志。
- `stage_center/_live_collectors_parts/selection_builder_registry.py` 让富途补采沿用已有观察分支，保持 NO_BUY、formal_eligible=false。
- `ops/_run_stage_center_nodes_parts/stage_dispatch.py` 原预算内零港股 cutoff 恢复不再只识别 10 月 12 日，保留日期、市场、状态和人工恢复边界。

验收：现役 Python 3.14，22 个针对性测试通过。真实富途响应缓存经原 runner/RawStore/SelectionStore 完整隔离验收后，沿原 slot lock 和 scoped recovery 保存；API 返回 A10/HK10，实际 8873 浏览器已截图。未派子智能体（用户要求直接处理），独立 Reviewer NOT_RUN。

本轮第一次实际运行的元数据 JSON 解析失败被完整保留。修复后人工单次恢复记录第 4 次尝试，保留原失败 receipt 和 manual_futu_bugfix_r11.json；自动重试上限未提高。初次测试退出还遇到 pytest 清理旧临时目录权限问题，改用本轮独立临时目录后 22 tests exit 0。

边界：这是中午补采的研究观察，不能证明早盘当时可获得该数据；历史盘口仍缺，natural_verified=false。其他早盘阶段本轮未重新发布。8910 与 gateway 前端源码/服务均未改动。

源码根：`/Users/lexi/Desktop/学习/v4_app`。
现役 Stage：`runtime_repair_R11/futu-morning-20261013-r11b/app`（在下述证据根内）。canonical 与现役旧版存在已知接口差异，本轮按相同最小修改分别应用，未整体替换旧模块。
证据根：`/Users/lexi/Desktop/学习/agents调试/V4_POOL_STAGE_HK_PAGE_REPAIR_20261013_R9/runtime_repair_R11`。
关键证据：`FINAL_RECEIPT.json`、`source_delta.json`、`tests_actual_3.log`、`canary_result.json`、`published_result.json`、`api_after.json`、`ui_stage0930.txt/png`、现役包 `stage_activation_receipt.json`。

Git 基线：`ffebeb368de746e963a25ce9cecdc19b9b5a707e`；目标独立分支 `codex/hk-futu-stage-recovery-20261013-r11`。仅必要源码、测试、本文；原始行情、缓存、截图和部署包不上传。远端 commit 与文件 SHA 的读回结果保存本地 `PRIVATE_GITHUB_SYNC.json`。
