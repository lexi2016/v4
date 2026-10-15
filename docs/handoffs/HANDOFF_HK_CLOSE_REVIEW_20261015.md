# 港股通收盘复盘与阶段证据交接（2026-10-15）

## 交接结论

本聊天已完成收盘采集时间判断修复、旧 scheduler 阶段读取兼容修复，以及“七阶段并集不可用”的显示修复。2026-10-14 的结果没有丢失：70 条阶段观察、27 个去重股票，命中当日收盘 Top20 的 7 只；0.2 候选命中 9/20。

09:40–09:45 的证据仍待验证：分钟数据为事后补采，不能证明当时已获得，且未留存该时段盘口。页面已经具体展示原因，不能将观察结果升级为正式七阶段并集或 PIT 验证通过。

本文汇总截至 2026-10-14 最后一次实际验收的事实，编写日期为 2026-10-15。本轮仅整理文档，未重新核验 2026-10-15 的行情、阶段产物、自然调度或运行进程。当前浏览器日期为 20261015，不代表本文中的 27 只、7/20 也是该日结果。

## 固定边界

- 唯一源码：`/Users/lexi/Desktop/学习/v4_app`；统一用户入口：8873。
- Vibe 8910 保持原样，不修改源码、配置或服务。
- 复用既有快照、阶段产物及 producer，不另建数据链，不跨日填充，不伪造历史盘口或采集时间。
- 保持研究专用：RESEARCH_ONLY=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。
- 本批按用户要求由主助手直接处理、未派子智能体。独立 REVIEWED / TESTED / BEHAVIOR_VERIFIED 为 NOT_RUN；实际执行的回归与页面核验按下文单列。
- 本轮文档允许路径仅为本文；不包含业务代码修改、重跑、服务重启或新监控。

## 已完成的三项修复

### 1. 收盘时间判断

原错误要求每只股票的价格更新时间都晚于 16:10。实际应验证本次查询发生在当天 16:10 后，保留股票原始价格更新时间及同日检查。

修改文件为 `ops/collect_hkconnect_close_snapshot.py`、`infrastructure/hkconnect_close_store.py`，相关回归在 `tests/test_close_review_producer.py`。2026-10-13 的人工恢复不能算自然成功。

2026-10-14 既有 com.lexi.v35.scheduler 自然执行 1610，首次尝试、LIVE、非 catchup、lag=0，查询发生于 16:10:15+08:00；698 行均为同日数据，价格原始更新时间范围 13:37:44–16:08:32，未改写。仅此“收盘采集时间修复”已达到 NATURAL_VERIFIED。

自然 run：`4f2b02a075724a929357749624e2a995`。
快照 SHA256：`00200c692080ea10850944d5c47b9f6c2db1fc0d1003cbba7391a4f1b0730a44`。

### 2. 旧 scheduler 读取阶段产物

自然复盘当时仅读到竞价 10 行。首个真实断点是旧运行包 SelectionStore 不认识已批准的全 D-1 池算法 SHA，报 `SelectionError: selection algorithm SHA mismatch`；不是当日阶段结果消失。

canonical 已支持该算法。运行包仅补入既有算法身份与读取允许列表，不改评分、输入 producer、PIT 或交易门禁。未知 SHA 仍拒绝。随后使用原 `ops.build_close_review` 从既有快照及七阶段产物人工重建，没有再次请求行情源。

重建后的复盘 SHA256：`99e58cde4f85cce5052ac3f40584b6a926fa8c40d5f3cd20b50c574efa2ed533`。这一步状态为 MANUAL_RECOVERY；原自然回执未改写。完整修复链的下一次自然收盘仍待验收，不能据此宣称整体 NATURAL_VERIFIED。

### 3. 七阶段并集卡片显示

文件：
- `apps/web/src/components/review/HkCloseReviewPanel.vue`
- `apps/web/src/components/review/HkCloseReviewPanel.spec.ts`

页面改为显示：
> 七阶段并集  
> 7/20  
> 已有观察结果 27 只  
> 09:40–09:45证据待验证：分钟数据为事后补采，不能证明当时已获得；没有留存该时段盘口

正式统计存在时优先显示正式值，包括真实的 0；否则仅使用通过既有代码去重及数量一致性检查的观察统计。原研究观察卡片保留。API 中正式并集仍为未确认，没有改写指标或门禁。

组件 SHA256：`7a1eacbe709d38071107e116cdc81be8eed3659e5eaf9ca294273c1f88127e33`。
测试 SHA256：`f7043f8dc1ef94da3efdf2a106241b25ac0e54ca4cb0498165b0271637a596d3`。
代码同步 commit：`bf5e1a46e8de3a1e63bbf25ce5ca73fbebeaa1cd`，私有分支 `codex/close-union-label-20261014`，远端 ref 及三个同步文件已读回逐字核对。

## 最后已验证的运行身份

以下是 2026-10-14 的部署回执，不是对 2026-10-15 当前进程的重新确认。

| 服务 | release | manifest SHA256 |
| --- | --- | --- |
| com.lexi.v35.scheduler | hk-close-reader-20261014-r1 | 335d368cedcd6829b00532587e81708d3ced0c9fe770883547564629dd30b327 |
| com.lexi.v35.api-only（8873） | close-union-label-api-20261014-r1 | 48db403b12cc96cdb8852baf414d79c1ff1aea5ee99290dd04bede0d49044d5e |

release 应用根统一位于 `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/<release>/app`。API 部署时间为 2026-10-14 17:37:54+08:00；scheduler 为 16:48:44+08:00。继续工作前先读实际 launchd 绑定和 release manifest，不根据本文盲目覆盖现役版本。

## 验收与缺口

- 收盘时间修复 canonical 回归：31 passed。
- scheduler 兼容修复：七阶段各读取 10 行；候选的相关 canonical 回归 7 passed。
- 卡片组件回归：8/8 passed；Vite build passed。完整命令和环境日志位于下列证据目录。
- 更广的 ReviewView 测试存在一个既有失败：无效 fixture 预期 3/20；使用修改前组件已复现同一失败，本批未扩修。
- API_VERIFIED：`/api/v3/review?date=20261014` 在卡片部署前后的 HK payload 完全一致；Top20=20、港股通=698、0.2 候选=100、阶段观察=70、去重=27、观察命中=7/20。
- UI_VERIFIED：实际刷新用户 8873 页面并打开第 9 项 16:10 收盘复盘，卡片数字与具体原因均可见，截图已留存。
- 状态仍为 `MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE`；保留 `UNVERIFIED_STAGE:STAGE_0940_0945`、`FUTU_AFTERFACT_CAPTURE_NOT_PIT_SAFE`、`HK_HISTORICAL_ORDERBOOK_UNAVAILABLE`、`HK_MODEL_SOURCE_PIT_AVAILABILITY_CANNOT_CONFIRM`。
- 单次收盘核验 automation-3 已删除。没有继续运行该监控。
- 已知独立 backlog：1555 A 股池 `RANK_FOR_REVIEW_ONLY_NOT_BUY_PRIORITY`，未纳入本批修复。

## 后续接手顺序

1. 先确定用户要检查的日期；如检查 20261015，应读取该日真实产物，不复用 20261014 的数字。
2. 若继续验收完整自然收盘链，读取实际 scheduler 的自然 1610 回执、同日快照、阶段输入、复盘产物，再核 API 与真实刷新页面；保留 run_id、时间、SHA 和首个失败点。人工补跑单独标记。
3. 若处理 09:40–09:45 缺口，只复用已有权威数据和真实采集记录；历史分钟补采先读 `docs/hk_history_backfill.md`。事后补采不能证明当时已可获得，缺失的历史盘口不能补造。
4. 如果只是确认卡片修复，复用既有测试及截图；没有新失败不扩重构、不重复部署。需要新监控时另按用户当前授权安排。

## 证据与前序文档

本地原始数据和完整响应仅留本机，不上传 GitHub。

- `/Users/lexi/Desktop/学习/agents调试/V4_HK_CLOSE_TIME_REPAIR_20261013`：时间修复的回归、采集、人工恢复与部署回执。
- `/Users/lexi/Desktop/学习/agents调试/V4_HK_CLOSE_NATURAL_20261014`：natural-dispatch.json、reader-verification.json、manual-rebuild.json、部署/API/UI 回执。
- `/Users/lexi/Desktop/学习/agents调试/V4_CLOSE_UNION_LABEL_20261014`：component-tests.txt、baseline-test.txt、build.txt、api-before.json、api-after.json、activation-r2.json、ui.txt、ui.png、github-sync.json。
- [时间修复明细](HANDOFF_HK_CLOSE_TIME_REPAIR_20261013.md)
- [自然采集与 reader 修复明细](HANDOFF_HK_CLOSE_NATURAL_20261014.md)
- [卡片修复与源文件前后 SHA](HANDOFF_CLOSE_UNION_LABEL_20261014.md)

本文 GitHub 同步从上述卡片 commit 新建独立交接分支 `codex/hk-close-handoff-20261015`，仅增加本文，保留原冻结分支和其他并行修改。
