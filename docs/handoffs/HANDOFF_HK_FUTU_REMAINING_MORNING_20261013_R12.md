# 2026-10-13 剩余早盘港股阶段恢复 R12

## 结果

按用户要求由当前主会话直接处理；未启用子智能体、未增设框架或数据源。
入口仍为 8873；8910 未改动。唯一源码 `/Users/lexi/Desktop/学习/v4_app`。

| 阶段 | HK 输入 | HK 页面 | A 页面 | 数据依据 |
|---|---:|---:|---:|---|
| STAGE_0925 | 20 | 10 | 10 | 同日实际 09:19:49 富途竞价二筛 CSV |
| STAGE_0930_0935 | 100 | 10 | 10 | 保留 R11 既有结果 |
| STAGE_0935_0940 | 100 | 10 | 10 | 既有富途 K_1M 缓存，09:36–09:40，每股 5 条 |
| STAGE_0940_0945 | 100 | 10 | 10 | 同缓存，09:41–09:45，每股 5 条 |
| STAGE_0945_1030 | 100 | 10 | 10 | 同缓存，现有窗口 09:46–10:29，每股 44 条 |

100 个分钟候选严格来自 20261012 信号、20261013 目标的既有 D-1 Top100。
没有重复请求富途。没有用当前盘口补造过去盘口，没有历史额度调用。
分钟阶段的涨幅、支撑、压力、失效位已读回；竞价按现有页面合同仅展示分数和涨幅。
全部 HK 保持 NO_BUY、formal_eligible=false。分钟产物保持事后观察和历史盘口缺失提示。

## 定位与最小修复

1. 上一部署 plist/manifest 将 `r11b` 重复替换为不存在的 `r11bb` 路径。R12 包恢复正确路径并逐项核对真实 CLI、配置、工作目录与 manifest。最终活动包为 `/Users/lexi/Desktop/学习/agents调试/V4_POOL_STAGE_HK_PAGE_REPAIR_20261013_R9/runtime_repair_R12/futu-morning-recovery-20261013-r12b`。
2. `stage_center/_live_collectors_parts/selection_builder_registry.py` 的 hk_builder 投影遗漏竞价分数、日期等字段；涨幅错误退回 last/open，竞价 open=last 导致显示 0。在约第 699 行新增仅 STAGE_0925 生效的字段传递，涨幅使用已有 prev_close 计算值。未改评分、筛选、池范围、BUY 或其他阶段。
3. 真实首行原分数 82、昨收 3.625、现价 3.63；修复后页面分数 82，涨幅 0.138%。旧输出版本保留，新版本 `run-f49bc6e107f26908a18694d7` 由现有 SelectionStore 生成，经原存储锁和旧指针比对更新单个槽位。任务记录仅更新对应 selection 引用，并保留旧记录与手动修复时间；没有追加采集或重置尝试计数。

## 指纹与运行身份

- Git 基线：`f7b03fb5ab6446d3f608ee5e9b435e7247b92825`；新工作分支 `codex/hk-futu-morning-complete-20261013-r12`。
- 上述 canonical 源码修改前 SHA256：`6a744d3384c3de5c00d6e74193b711cd72c694ef34baec5774e7095d9c3743bb`。
- 修改后 SHA256：`6ba88c667acf51c5ef553d39d73dab814ebc816a3ecd9bf9f69cb0dff9a14870`。
- 活动 Stage 的对应源码 SHA256：`a5eff7d6ab441551da7e65309a179601b23618923e97ee3721d0719657f3e28e`。该运行包继承已验收旧版基线，仅移植本次增量，不能冒充与 canonical 全文件相同。
- 活动 Stage manifest SHA256：`5e73413eb278c193422a95e5ec6a154fecb3e427bf14c055fa331fa9773b8547`。
- API/UI 仍由 R10 `research-workbench-stage-partial-display-20261013-r10` 提供；本轮不改前端。
- 富途分钟缓存 SHA256：`5f741e50a891c88a26c8c214e623594ab07d76110ea97d5dee61b09df5b59be3`。
- 竞价 CSV SHA256：`d0bc7bfb31c599e60a4b06366474f7bb954d3ee1ec290c5892a0aecbfcc042e6`。

## 验收

Python 3.14、现役 v3.5-mac 环境，分别对 canonical 和运行候选执行：

```text
python -m pytest -q --basetemp=<R12 独立目录> tests/test_hk_auction_projection.py tests/test_hk_futu_morning_recovery.py tests/test_stage_slot_execution_legacy_collector_kwargs.py
```

两处各 25 passed。最初合并测试的断言通过，但 pytest 清理其他历史临时目录遇到 PermissionError；未修改该无关目录，改用本轮独立临时目录后命令 exit 0。
新测试覆盖非零及真实零分、昨收涨幅、错误目标日期拒绝。

- IMPLEMENTED / INTEGRATED / DEPLOYED：完成。
- 针对性检查：当前主会话直接复跑通过；独立 REVIEWED / BEHAVIOR_VERIFIED：NOT_RUN，依照用户“直接处理，不用子智能体”。
- API_VERIFIED：五个早盘阶段均 HK10/A10，竞价原材料值匹配，无 selection identity conflict。
- UI_VERIFIED：本次恢复四个阶段逐个通过现有 8873 下拉选择、渲染文本及截图核对。
- 原 09:30–09:35 raw/selection 指针未变；竞价更正只改本槽位，其他 selection 指针逐项相同。
- NATURAL_SLOT_UNVERIFIED：本次是同日手动恢复，不能代替自然早盘运行验收。
- 历史盘口缺失：仍保留；分钟结果不可升格为 PIT 安全信号。

本地完整证据目录：`/Users/lexi/Desktop/学习/agents调试/V4_POOL_STAGE_HK_PAGE_REPAIR_20261013_R9/runtime_repair_R12`。关键记录：`FINAL_API_ACCEPTANCE.json`、`FINAL_RUNTIME_IDENTITY.json`、`DATA_API_ACCEPTANCE.json`、`AUCTION_PROJECTION_PUBLICATION.json`、各阶段 `ui.txt/ui.png` 与测试日志。原始行情及运行数据不上传。
私有 GitHub 同步只含本次单文件源码增量、三项回归用例和本报告；远端提交与 blob 读回记录存于同目录 `PRIVATE_GITHUB_SYNC.json`。
