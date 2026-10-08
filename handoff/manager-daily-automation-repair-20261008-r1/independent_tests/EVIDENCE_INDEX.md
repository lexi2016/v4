# 独立证据索引与结论优先级

本索引由 Root 整理，不修改独立 Reviewer 的报告、测试或原日志。

## 最终冻结证据

当前33份源码／实现测试对应的唯一最终独立行为结论是 [final_review.json](final_review.json)，捕获时间为2026-10-08 18:21:29 UTC，状态为 `PASS_WITH_SCOPED_SOURCE_CLOSURE_BLOCKERS`。该报告的 `candidate_identity` 绑定最终 source manifest 及20份生产源码 SHA；完整逐文件清单另包括13份实现测试／fixture。

- [最终 review 日志](final_review.log)与 [Root 的源码和证据绑定](../evidence/package/review_source_binding.json)保留文件身份核验。
- [实现者报告](../evidence/writer/writer_final_report.json)及其9份原日志独立保留。Writer 的用例与独立复验分别记录，重复和交叉数量不累加。
- [独立包装报告](../evidence/package/final_packaging_source_review.json)只核源码前像、目标根、文件和补丁重建；不冒充正式运行或行为验收。
- [分层验收状态](../acceptance_status.json)与 [TESTING.md](../TESTING.md)说明现场未验事项、合成边界和基线失败。

报告保留捕获时的原 cwd 和绝对日志路径。交付中的相同字节副本使用同一文件名放在本目录，Writer 副本位于 `evidence/writer/`；复现时按 [README.md](README.md) 的源码根和运行时变量替换实际位置。原日志中的临时测试根、日期、报价和产品均不代表生产现场。

## 最终测试组与日志

| 测试组 | 最终日志 | 判定 |
| --- | --- | --- |
| 原每日调用与晚到公告后续补算 | [daily_owner_chain_freeze_final.log](daily_owner_chain_freeze_final.log) | 14 passed；renderer单列。 |
| US原owner与workspace | [us_workspace_freeze_final.log](us_workspace_freeze_final.log) | 18 passed。 |
| 原POST到精确普通页GET绑定 | [daily_exact_page_binding_final.log](daily_exact_page_binding_final.log) | 1 passed。 |
| 原多日公告范围及真实source变化 | [daily_reviewed_source_window_final.log](daily_reviewed_source_window_final.log) | 1 passed。 |
| 实际路由DTO到TS校验／投影 | [ui_reviewer_final.log](ui_reviewer_final.log) | 2 passed；没有父页面挂载或浏览器验收。 |
| HK同次发布、两日接续及篡改拒绝 | [hk_independent_final.log](hk_independent_final.log) | 4 passed；合成边界见最终报告。 |
| 独立重跑Writer的HK用例 | [hk_writer_chain_freeze_final.log](hk_writer_chain_freeze_final.log) | 11 passed；不冒充Reviewer自写用例。 |
| 原supplement完整文件 | [hk_supplement_suite_current.log](hk_supplement_suite_current.log) | 13 passed / 2 failed；[原基线两项](hk_supplement_two_failures_base.log)与[本轮两项](hk_supplement_two_failures_current.log)同值复现。 |
| 实际renderer／binding闭包 | [daily_renderer_closure_final.log](daily_renderer_closure_final.log) | BLOCKED；缺原上级marker，且干净共享导入有原Stage依赖缺口，未补造。 |

## 中间报告与红测的正确使用

[us_workspace_final_review.json](us_workspace_final_review.json)、[daily_final_review.json](daily_final_review.json)及[hk_final_review.json](hk_final_review.json)是各阶段的原始报告，包含较早版本身份。文件名中的 `final` 只表示当时阶段结束；最终源码以本目录 `final_review.json` 为准。较早的 `*_post_fix.log`、`*_final.log` 也不能替代上表指定的冻结后日志。

- 精确日期绑定的原红测、field/path diff 展示保存后几秒的cutoff/context漂移，后续真实read_at接续修复已由最终路由与投影用例验证。
- [daily_owner_chain_cutoff_contract_red.log](daily_owner_chain_cutoff_contract_red.log)要求09:45晚到产品立即改变09:27封存计划，属于与原cutoff合同冲突的断言。修正后用原10:00 catch-up消费新SHA、保存新run并读回，旧盘前历史保持；这次断言更正不冒充生产缺陷修复。
- [daily_reviewed_source_window_pre_fix.log](daily_reviewed_source_window_pre_fix.log)最早探针用了不合法的目标／公告日期对，归为 `INVALID_TEST_PAIR`。最终有效多日来源测试另见上表。
- [hk_two_day_cross_readback_pre_fix.log](hk_two_day_cross_readback_pre_fix.log)包含重复pack fixture顺序问题，归为 `INVALID_FIXTURE_ORDERING`，不作为生产缺陷红测。真实跨日latest误绑定的分析在 [Root的前期发现](../evidence/pre_fix/hk_cross_date_pointer_review.json)，修复后的原updater／publisher两日链见最终独立HK组。
- [本机命令的前期审查](../evidence/pre_fix/host_handoff_command_review.json)保留当时发现；最终 [HOST_EXECUTION.md](../docs/HOST_EXECUTION.md)已经明确分根、真实事后时点、原POST职责和过去日期的 `dynamic` 页面口径。前期报告中的OPEN状态不是最终未修复结论。

上述分类及日期／输入合同见 [REVIEW_CONTRACT_DECISIONS.md](../docs/REVIEW_CONTRACT_DECISIONS.md)。仍未通过的原supplement两项、完整入口和现场自然运行并未因过程证据归档而关闭。
