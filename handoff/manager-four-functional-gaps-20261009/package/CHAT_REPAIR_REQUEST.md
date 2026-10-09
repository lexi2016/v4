# 可直接转交 Chat 的修复请求

请以本包内固定 R2 source snapshot 为基线，提出并实现/输出最小 manager workbench 接入修复。你没有 Mac 本地 owner 环境；请将真实行情、owner state 和运行状态保持为 CANNOT_CONFIRM。

重点先复用已存在代码和单日 owner 链路，不重新造 collector、producer、分析器或第二份研究数据底板：

- R3 2026-09-30 pinned source snapshot、R1 2026-10-07 announcement consumer，以及 2026-10-09 原 owner runner/checker 都在 package/code/。先读 DAY_RUN_REUSE_AND_INTEGRATION.md 的调用顺序和日期边界。2026-09-30 用户报告的独立成功入口 receipt 本次未定位；不要宣称其不曾存在。09:53 manager saved plan 只证明 US attention READY 的固定范围，announcement NOT_RUN、screen CANNOT_CONFIRM、plan PARTIAL。10/07 publication 的 10/08 readback 证明 announcement 子链曾被消费，但 channel 仍 PARTIAL，HK/oversold/plan 未完成。
- 以 package/code/r2_chat_patch_target/apps/api/v35_api/app.py 的 create_app 注入路径与 manager_research_router.py、service/workspace/workspace_plan/workspace_daily_channels/announcement modules 为实际集成合同；不得只对 minimal runner 测试推断生产根因。
- 四个冻结验收项见 FOUR_ISSUE_MATRIX.md。当前 app-wired 结果和 source owner 已在 package/evidence/ 下做过最小 metadata-only 投影。

每项请沿 existing owner output → manifest/run/SHA → R2 injected reader → workspace channel → plan input identity → GET readback 查实。对 announcement 要复用原 capture/Reader/Reviewer/register/import contract；HK Connect 要读取现有 exact-date V2 authority root；oversold 要读取精确日 security master/HK02 panel；plan 必须保留 stale identity guard。接入缺数据时保持 fail closed；不要将全零股票数标成 VALID_EMPTY，不得改 BUY/production flags。

交付 Chat 的目标：给出最小实际 source diff、相关确定性 regression test、测试命令和结果、源/配置 SHA、每个问题的 owner/consumer/acceptance。只要输出了建议而未运行，应明确标记 PROPOSAL_ONLY / NOT_RUN。无需部署、发布、改服务或触碰 Mac state。

离线接口 smoke（从 ZIP 解压根目录，即包含 `package/` 的目录运行）：
  python3 package/tools/contract_smoke.py

该 smoke 仅测试 synthetic failure-envelope 的字段/日期/安全标志，它不是证券结果，也不是 R2 代码的运行验收。
