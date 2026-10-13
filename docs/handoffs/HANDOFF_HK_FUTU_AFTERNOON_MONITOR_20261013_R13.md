# 2026-10-13 下午自动选股故障修复及监控 R13

## 故障与最小修复

13:15 launchd 自然触发成功，A10，但 HK 的 100 条富途分钟聚合数据在选股环节返回 `HK_LANE_EVIDENCE_MISSING`，HK0。不能将有行情但缺少阶段候选依据解释为市场无符合股票。

唯一源码 `/Users/lexi/Desktop/学习/v4_app`，入口8873，8910未动。修改 `stage_center/_live_collectors_parts/hk_minute.py`：原下午分支取得 Futu bars 后直接返回，遗漏早盘已使用的来源字段和候选快照处理。将13:00–13:15、14:45–15:00接入既有流程，删去重复采集分支；缺少/过时快照时保存为已有 NO_BUY 观察结果并保留盘口缺口。已验证无符合活跃股、损坏快照、空富途返回不混同成“缺失可恢复”。Stage8原自然RT_DATA流程保留。

本次不新增框架、producer、来源、第三方调用、门禁或策略。不伪造 LIVE_HKCONNECT_GAINER；只有原核验快照能提供该标记。观察结果均 formal_eligible=false。

## 13:15 实际恢复

- 精确日20261013，D-1信号20261012 Top100，原自然 raw SHA256 `141b2785fb25dcd1157cf375b582cef7cf6fc0da7e9edc56a4ab29c7192b0fc5`。
- 复用原存储100只，每只14条分钟聚合（现有窗口13:01–13:14）；未重新采集。
- 原自然失败回执保留。用现有builder生成观察Top10、现有SelectionStore生成不可变新版本，原锁与旧指针对比后更新仅本HK槽位，其余槽位相同。
- 新run `run-8576a457b7113369acf6bdc8`；任务引用标为 `RECOVERY` / `MANUAL_SELECTION_REBUILD_FROM_NATURAL_RAW`，未重置尝试数；不追认自然PASS。
- API及真实8873页面 HK10/A10。西普尼阶段涨幅2.117%，支撑49.6、压力51.85、失效49.6。
- 原采集时间未落盘，保留 `FUTU_CAPTURE_TIME_NOT_PERSISTED`；未使用文件mtime冒充采集时间。盘口缺失和观察标记保留。

## 验证与身份

- 当前主助手直接实施和复跑，依用户不派子智能体；独立 REVIEWED / BEHAVIOR_VERIFIED 为 NOT_RUN。
- Python3.14现役v3.5-mac环境，canonical与候选各20passed：
  `python -m pytest -q --basetemp=<R13独立目录> tests/test_hk_futu_afternoon_routing.py tests/test_hk_futu_morning_recovery.py tests/test_hk_auction_projection.py`。
- 其中8项新用例覆盖两个下午阶段接入快照、缺失/过时快照保留观察、合法零匹配与损坏不混同、迟到不抓当前盘口、空返回不造行。
- IMPLEMENTED / INTEGRATED / DEPLOYED / API_VERIFIED / UI_VERIFIED 已完成。NATURAL_SLOT_UNVERIFIED：13:15原自然结果有故障，本次为恢复；15:00、15:55尚未验收。
- Stage实际包 `/Users/lexi/Desktop/学习/agents调试/V4_POOL_STAGE_HK_PAGE_REPAIR_20261013_R9/runtime_repair_R13/futu-afternoon-20261013-r13`；API/UI仍R10 `research-workbench-stage-partial-display-20261013-r10`。
- Stage manifest SHA256 `e7be1ac5e39793a902ab12bde7525500ab15522dff0a6b3d695c9d02c39dc6b8`，scheduler/deadline真实工作目录及CLI --help均通过。
- canonical源码前 `f734196e1f1128954627562447323b1b9b06f8171416fbd5744a3233d2bda70e`，后 `82effcf2cbb0f3821031510b9a995bd9f949e5af18becec99a7f659027510e96`；实际运行文件 `2d11b12d1275041eb9236b10b2e04e817c53d15677f43405cac844286c7a16b0`。运行旧基线仅移植本次区块，不将其整个文件冒充canonical。
- Git基线 `3e58b7f4a12339755c4c794f4d3f7f961d2d1c1f`，私有工作分支 `codex/hk-futu-afternoon-monitor-20261013-r13`。

## 后续自动监控

更新已有本聊天heartbeat `v4`，没有重复新建监控。检查13:15、15:00、15:55自然任务、同日完整来源、API和8873页面；发现具体故障直接最小修复，并把手工恢复与自然验收分开。有新问题、修复结果或阶段完成才通知。当天三个阶段完成验收和授权修复后暂停；不自动扩展次日。scheduler现有15:00、15:50预采、15:55及deadline15:01、15:56时间点保持。

证据目录：`/Users/lexi/Desktop/学习/agents调试/V4_POOL_STAGE_HK_PAGE_REPAIR_20261013_R9/runtime_repair_R13`。`natural_1300_receipt.json`、`PUBLICATION.json`、`recovery_receipt.json`、`api.json`、`ui.txt/ui.png`、测试日志及运行指纹。GitHub只同步本次源码、回归用例和本报告，排除行情、账户、运行原始数据；远端commit及blob读回见 `PRIVATE_GITHUB_SYNC.json`。
