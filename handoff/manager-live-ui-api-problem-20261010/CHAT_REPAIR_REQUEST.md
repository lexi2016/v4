# 直接交给 Chat 的修复任务

请基于本包 code/current_fused_app/ 的固定现役源码快照，针对真实页面与 API receipt 做最小问题修复/代码提案。你没有本机 Mac owner roots、真实 owner state 或当前 8873 service；不要尝试连接本机服务、执行 owner capture/import、重抓行情或声称已完成真实 API/UI/自然时段验收。

这不是只有“数据缺失”的问题：同一 run 在 owner POST 紧邻两次 GET 中均 CURRENT/consumed=true，稍后的独立浏览器 GET 对同一 run 和产品 SHA 返回 STALE_INPUTS_CHANGED/consumed=false；日期绑定、semantic version 和 research cutoff 相同，input_identity 不同。包内保存了三张真实截图和独立运行时 review。独立 counterfactual 已证明全局 manifest SHA 可在 1,970 个 material 叶子其余不变、40 对 payload/receipt 当前完全匹配时改变 candidate projection identity；这是 P2 over-broad coupling contributor。它没有证明此次 live mismatch 的唯一原因：旧 manifest bytes、GET body SHA 和其他 identity extensions 未闭环。请按包内 evidence 检查并修复语义 identity，保留全局 manifest SHA 作为 provenance；live changed field 若仍未能从固定 receipt/code 证明，写 CANNOT_CONFIRM。不得禁用 stale guard、复用旧 identity 或强制 CURRENT。

同时修复三个已定位的页面问题：现有 daily_channels 字段和 renderDailyChannels helper 没有接入 catalystObservationPanel.render(value)，因此页面没有每日 ANNOUNCEMENT/HK_CONNECT/OVERSOLD 摘要；上方“美股：尚未评估”读取 assessment_state，下方“4 个已审关系 VALID_EMPTY / 0 match”读取 daily_run，二者 scope 不同，应在相邻标签中明确范围；catalystObservationPanel 当前把研究注意力/映射 section 放在 stocks/background 后，真实页面先出现 100 行 raw observations。将已有摘要接入现有 workspace 响应并前置核心结果；完整输入/审计行保留在可展开区域，不得删除或截断 producer 输入或变更金融门禁。候选 bundle SHA 已知，但 browser-loaded bundle SHA 为 CANNOT_CONFIRM。

请沿包内 owner → source manifest/run/SHA → workspace channel → plan input identity → GET → 当前页面查明：

- 目标 20261009；公告日期 20261008；执行/回看 20261010；
- 后端 P2 contributor 的独立可复现边界：saved global manifest SHA c8a8fc… → current 864e1f…；1,970 source refs 仅此字段变化时 projection identity ca3292… → 9decd5…；40/40 当前 payload/receipt pairs 及 manifest entries 仍与已保存 binding 相同；这不是唯一 live cause。
- 之前 target 20261008 / publication 20261007 的 613 Reader + 613 独立 Reviewer + 33 selected + VERIFIED import 是可复用的原 owner 子链，不是 20261009 的消费结果；
- 目标 20261009 / publication 20261008 当前公告尚未解析导入；
- corrected V3.5 root 下 20261008 panel 存在；exact 20261008 security master 缺 entry，六日量纲/scale 未证、provider finality 未认证；HK target membership authority 未闭环；
- daily US VALID_EMPTY 仅覆盖 4 个已审关系，不是 full-market empty；另一条 corrected isolated run 的 external_finance payload READY 但没有 market_snapshot；
- 用户报告的 2026-09-30 独立成功 receipt 本次仍 CANNOT_CONFIRM，不要否定用户报告。

请交最小 diff、围绕确切状态转移和 global-manifest-only counterfactual、现有 renderer wiring 和三个 channel/date binding 的回归测试、执行命令与实际结果，并列出每处 source SHA。backend review 涉及的四个 source SHA 和精确位置见包内 root_cause_report。前端 reviewer 报告中的 synthetic helper render PASS 不能替代页面挂载测试；其 focused regression 与 full suite 均 NOT_RUN。若只在包内 snapshot 上实施，明确 PROPOSAL_ONLY；真实 owner/API/UI 和自然时段仍需 Mac 侧验证。

安全不变：RESEARCH_ONLY=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。不要新增 producer、不回填历史数据、不改 HK/US 池合同、不绕开旧版 current-run/stale identity guard。