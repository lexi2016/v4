# 三个问题与已知边界

| 问题 | 症状和已证事实 | 原因与未知 | Chat修复目标 |
|---|---|---|---|
| 公告 Reader → Reviewer → 导入 | target 20261009、publication 20261008；当前 PARTIAL / NOT_IMPORTED。检查的恢复证据无 capture、不同 Reader、不同 Reviewer 或 imported product。 | 精确首个断点在 trigger、capture、external handoff、import 哪一跳为 CANNOT_CONFIRM。不能只写“缺输入”，不能伪造 review 或建第二 producer。 | 沿原任务和既有 owner 修复触发、handoff、导入与消费读回。 |
| US mapping daily | 20261008 POST_CLOSE 输入存在。owner run a95450cd4b264fb6840308d7d2681cf6 是 VALID_EMPTY，33/33 available/configured、4 reviewed、0 US matches、0 HK relation、full_market=false。17:23 live GET daily NOT_RUN、plan NOT_MATERIALIZED。 | 原trigger/调度、映射保存消费、API/页面的因果断点 CANNOT_CONFIRM。C1 disabled、R2 enabled只是观察。 | 修复现有触发/映射持久化、消费、API/页面连通性；不改排名算法或放宽阈值。 |
| 超跌 screen | 16:01 plan run dba211c2677045afb4e0ef8c990367ee 对 session 20261008 为 PARTIAL，loader抛 StoreError。17:23 session 20261009 POST_CLOSE仍报StoreError。 | 16:01历史快照有36日期至20260930；17:34只读复现时latest.json已更新为37日期至20261009，但仍缺20261008，entry lookup抛精确异常，尚未到该日schema/source校验。16:50另见 exact-date panel missing。17:23的20261009内层原因 CANNOT_CONFIRM。 | 修复原authority reader/权威输入消费，保留确切日期验证；不建第二producer，不把695 snapshot冒充D1 master。 |
