# HK 自动运行验收修复 · 2026-10-15

本批修复已完成独立验收、部署、实际 API 并发读取和刷新 UI 验收。15:55 的 R2 自然任务已自动生成独立验收记录并通过核验；最终 Stage R3/API r4 消费该原记录仍通过。R3 新自然运行尚未发生，不能把 R2 的自然结果改记为 R3。

## 已确认根因与最小修复

- 原 reader 已要求独立 index/attestation，但自然调度缺发布钩子；现于既有自然 final receipt/history 落盘后，由独立程序完整重验并自动发布，失败写明确拒绝回执。
- 补齐未来原始 receipt 的 RESEARCH_ONLY；Stage8 保存本次已取得的 RT_DATA 原始捕获与真实时间，供独立重聚合，无第二行情采集链。
- 分钟窗口过滤与实际获得数据时间分开标记。R1 曾把 PIT 缺口错误降为观察产物不可用，15:00 自动验收被拒；R2 修复可用性判断并通过严格只读重验恢复原有观察行，原失败证明保留。
- 实际页面并发请求预选池和阶段接口时，短暂读锁导致误拒。R3 增加最多 2 秒有界只读等待；pending、输入变化、未知来源和持续忙仍拒绝。
- 新 API 升级 verifier 会误拒已审 R2 自动记录；r4 仅允许明确的 R3/R2 SHA 配对，仍完整重验所有当前输入、回执、自然时间和产物绑定。未知 SHA 不放行。

## 实际验收

15:55 自然启动 15:55:05.897991，`run-65c3b689d2a8847744b2affc`，100 输入 → 100 raw → 10 观察。自动证明签发于 15:55:17.248729，API 和实际刷新页面均显示 HK_CONNECT 执行/自然验收 VERIFIED。该结论仅覆盖研究运行事实。

最终独立验收包括 Stage 40 项、reader 31 项及独立自然时钟反例，真实预选池并发读取，以及部署后四个实际 HTTP 请求。15:00 保持 A10/HK10，缺独立证明；15:55 保持 HK10 和原 R2 有效证明。18 个原运行保护文件字节和修改时间未变。主控整页刷新两个阶段已验证。

现役于 16:15:17/18 接入：Stage `hk-auto-execution-audit-20261015-r3`，API `hk-auto-execution-audit-api-20261015-r4`。接入前后逐项完整库存/CAS 核对，保留并行 history-adjudication API 的 12 项改动。main scheduler 未由本批修改。精确 manifest/plist/receipt SHA、测试环境和运行身份见 result.json 与各 identity 文件。

## 保留的缺口与监看

- PIT 仍 CANNOT_CONFIRM：15:55 RT_DATA 请求 15:55:06.147200–15:55:15.569973，晚于截止。过滤窗口正确不能证明截止前可得。10 行 formal_eligible=false、NO_BUY；未改变正式资格策略。
- 早上四段仍为人工历史恢复；10:30/13:15/15:00 原证据不足保留，不补签自然证明。
- 16:10 自然收盘任务成功，取得当天 698 股票并发布同日复盘；但收盘 reader 未纳入早上四段历史恢复，只有 3/7 阶段、30 观察行、16 去重股票。API/UI 一致为部分证据，完整七阶段仍 CANNOT_CONFIRM。该项按监看范围报告，未重跑或扩改收盘链。
- 继续已有自动化的 16:22/32、17:32/42/52 节点；17:30 发布须按真实目标交易日核自然 source→canonical trio→API/UI。17:52 汇总并暂停，不延至明天。

## 交付与复用

唯一源码 `/Users/lexi/Desktop/学习/v4_app`。私有分支 `codex/hk-auto-execution-audit-20261015`，交付父 commit `438b4fca3f25985b6a717cb3198c0b54d1a8f919`。canonical 工作区包含其他并行修改，因此这里只同步本批源码/测试的精确补丁、必要新增源码和精简身份记录，不把分支称作完整现役快照。

`canonical-minimal.patch` → `r2/canonical-r2-final.patch` → `r3/canonical-r3.patch` → `r4/canonical-reader-compat.patch` 为本批源码顺序；只在各记录的精确 preimage SHA 匹配时应用。runtime actualdiff 用于身份审计，不能盲目覆盖 canonical。旧 R3 API 候选已因并行基底变化停止，最终 API 只认 r4/identity.json 与 result.json。源文件前后 SHA 保留在各 actualdiff/identity。原失败和测试夹具缺环境的诊断未擦除；实际通过证据与失败分开。

不上传原始行情、运行快照、账号/凭证、依赖目录或 dist。RESEARCH_ONLY=true，production_allowed=false，buy_gate_updated=false，orders_sent=false；Vibe8910 原样。
