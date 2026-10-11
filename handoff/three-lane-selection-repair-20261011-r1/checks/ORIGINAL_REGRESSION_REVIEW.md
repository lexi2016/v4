# 独立只读最终复核：历史／身份／O 诊断

## 本轮结论

- 最终共享依赖环境下，新 Parquet 诊断专项独立复跑：3 passed，0 failed，0 error，0 skipped。
- 固定附件基线 `31f5a39ce1ee7cd76bbf268e68760b6adc319774` 与候选，同一 Python 3.14.6、同一 28 个 support Python/JSON 文件、同一 5 个原测试：两边各 77 passed / 29 failed / 0 error / 0 skipped。106 个 collected IDs 完全相同；candidate-only failed = 0；baseline-only failed = 0。
- 候选后来提交为 `cd93198cb0de06c8f32386ed1fc808a5b4e53bec`，提交后复核 127 个基线 tracked 路径的候选字节与测试期间完全相同。没有用新 HEAD 重新导出基线。
- 原包与候选对同一真实 Parquet 成功计算的独立对照：10/10 断言为 true，完整 screen、plan、research attention、research selection ledger 相等。
- 本轮只写 reviewer 专用临时副本、harness、日志、JUnit、哈希记录和测试临时产物；未修改 candidate、candidate/tests、baseline、support。

## 原测试逐文件结果（基线与候选相同）

| 原测试文件 | passed | failed |
|---|---:|---:|
| test_manager_plan_identity_r2.py | 6 | 3 |
| test_manager_plan_readback_issue24.py | 22 | 9 |
| test_manager_workspace_targeted_r2.py | 35 | 10 |
| test_manager_us_daily_chain.py | 1 | 5 |
| test_manager_announcement_date_catalog.py | 13 | 2 |
| 合计 | 77 | 29 |

“无本次新增失败”只针对这 5 个文件的本次执行；不能表述为原回归通过。Git 源文件 provenance 由 root 的固定 Git blob 审计提供；本复核独立确认了全部 28 个 support 文件在执行前后没有变化。原 5 个测试文件在两树中 SHA 相同，两个源码树在执行期间 SHA 均不变。

## 共同失败的实证归因与边界

1. **US daily 5 项：缺原始证据 JSON。** 两树均缺 `us_mapping_reviewed_20260930.json`、`us_mapping_relation_registry.json`、`us_mapping_relation_evidence_20261011.json`、`us_mapping_relation_evidence_review_20261011.json`。原 `attach_current_relation_evidence` 在同一 33-symbol fixture 上实际返回 `NOT_EVALUATED`、空 source artifacts、`US_HK_RELATION_AVAILABILITY_UNVERIFIED` 和 `US_RELATION_EVIDENCE_ARTIFACT_INVALID`。因此 fixture 期待的 10 个 mapped symbol / 14 条关系、5 条 NVDA matches 以及更换现有 source SHA 不具备前提。这是缺随源码读取的证据产物；不是本轮新增 source_metrics 误哈希（该改动已撤回）。
2. **issue24 中 3 项身份／成功读回断言：fixture 没有现有 v2 身份组件。** `current()` 与其自身实际比较也返回 `SAVED_IDENTITY_COMPONENTS_UNAVAILABLE_OWNER_REFRESH_REQUIRED`，外层 d*64 相同不够。`test_legacy_over_64_mib...` 中大文件本体 read、完整字典相等、inode/size/mtime 保持断言已通过，失败发生在随后要求 `CURRENT` 的身份比较。这个字符串仅记录原函数诊断，不是刷新历史的操作建议。
3. **issue24 另 6 个 bad_readback 注入参数：原函数与断言已有分歧。** 5 个注入保持 `consumed=True`，外层原 owner 在最终 `_readback_plan` 后只校验 consumed，因此不抛出预期异常。`CURRENT_NOT_CONSUMED` 确实抛出，但原代码此前已经写入过 `SUCCEEDED_EMPTY`，然后写 FAILED，违反测试“从不出现成功回执”的断言。基线和候选一致。不能把这 6 项统称为缺依赖，也不能因基线失败就宣称该门禁验收通过；本轮没有修改这段生产流程。
4. **plan_identity 3 项：fixture／owner 合同与时间前提。** 两个 scheduled fixture 使用 `old/new/same` 身份、没有同 run 完整 owner attempt / v2 组件；另一个 reuse 测试没有固定 `_now`，走重新发布后撞上 2026-09-28 deadline。autorun fixture 只返回 plan_product 和 plan_context，原 `owner_plan_readback` 实際报 `PLAN_OWNER_PRODUCT_AND_ATTEMPT_REQUIRED`。
5. **HK recovery 3 项：原 fixture 缺 lineage 字段。** `_write_hk02_revision` 没有写原 reader 已要求的 `new_dates`、`new_row_count`，所以基线与候选均先返回 `PLAN_HK_02_PANEL_RECOVERY_LINEAGE_INVALID`，到不了测试期望的 parent/cutoff 分支。
6. **half-day 2 项：固定日历与测试预期不同。** 实际原共享日历把 `20261228` 解析为 `FULL_TRADING_DAY`，本次 `20261230` 计算的较早完成 session 是 12/28，focus 起点为 `2026-12-28T16:10:00+08:00`。测试期待 12/24 的半日收市并期待读取 half_day_close；该路径前提在此日历中不成立。这里只报告给定日历的实际解析，不判定外部市场日历哪个正确。
7. **issuer 3 项：原语义门禁已有拒绝。** 原／新纯函数 `rejection_audit` 相同：越疆句为 `PUBLISHER_OR_ANALYST_NOT_SUBJECT`；“南方港股通红利政策变化”与“周大福基本面待核”为 `NO_SUBJECT_LOCAL_ACTION_OR_RESEARCH_CLAIM`。不能把这些结果归为新 alias / 日期修改导致。
8. **local_source 1 项：缺原 app 文件。** 测试用 `Path(__file__).parents[1]/apps/api/v35_api/app.py` 直接读文件；基线与候选均没有此文件。即使同名模块通过 support 可 import，也不能满足这个硬路径文本检查。
9. **workspace API 1 项：实盘前边界与事后写入测试。** 默认 GET `view=auto`，目标为 20260921，两个临时 POST 实际都在 20261011 生成。原／新 `select_plan` 对 `2026-09-21T09:30:00+08:00` 边界都返回 None，读取后的临时 owner 文件 SHA 全不变。两日志 expected SHA 不同是两个独立实际 run 的 seal 不同；终态均 `None != post product SHA`，不是新增候选失败。
10. **catalog 2 项：基线已使用更新 source identity 合同。** 测试仍期待 `CODE_INTERSECTION_ONLY_NOT_SELECTION_RESULT` 和 H5354 consumer 空列表；原代码已经返回 `SOURCE_IDENTITY_RESEARCH_REFERENCE_ONLY_NOT_CONNECT_ELIGIBILITY_OR_SELECTION_RESULT`，并保留有效 source identity 的 research rows。候选未改该模块。

## O 诊断最终行为证据

Python 3.14.6 / pandas 3.0.6 / pyarrow 26.0.0。真实写入与读取 Parquet，使用原日历与 screen 计算主体；panel/master/supplement 是明确的合成 reader 边界。最终独立专项的 JUnit tests=3、failures=0、errors=0、skipped=0。

- 完整 screen、build_workspace plan、build_research_attention/ledger 在候选有无可选 diagnostics 参数时相等；诊断没有增加 panel/master owner 读取。
- HK.00002 缺 prior60：20260716、20261005；缺 previous5：20261005；两个 duplicate 列表均为 20261006。target=20261012、source session=20261009，diagnostic cutoff 与真实调用 context 相同。
- 改诊断 source_refs 不改 screen，说明 deepcopy 隔离成立。第二股读取异常时，已处理第一股的局部诊断不发布；输出 CANNOT_CONFIRM / rows=[] / sha256=None，旧 decision identity 和 gaps 被清除。
- 额外从固定基线分别加载原 workspace_plan / workspace_projection / research_attention，对同一个 Parquet（SHA `89a67cb2bbe4a3e640a16638407cf8c2a30bb41c44286a640dbe2960fb17f16b`）与候选成功计算比较，10/10 断言为 true。完整 screen/plan/attention/ledger 均相等。两边 READY_WITH_GAPS、input=2、pending=2、strict=0；未证明成交量单位仍为 NOT_PROVEN。
- 该额外比较的顶层原模块独立加载，相对依赖仍在同一候选 package/shared namespace；不能扩大成完整旧应用隔离或真实 owner provenance 证明。

## 仍保留的已审范围限制

- P1 原 plan body 单32MiB／累计64MiB不变；journal 是另外最多64×64KiB元数据。缺 journal 时 latest 与 immutable 同 run 大文件可重复计入预算，仍可能 SOURCE_FAILED；不允许仅凭 run_id 跳过未核字节。
- P5 frozen field 二次比较已用现有 narrow semantic_value；没有扩大全局 SHA ignore。但真实 10/12 原 payload／当前 payload 两个身份组件没有实测，不能称 live 污染已消失。
- 无 Mac 连接、无当前 owner / natural schedule 实跑证明，无刷新绕过失效。

## 全部 29 个共同失败 ID

```text
tests/test_manager_announcement_date_catalog.py::test_dynamic_pagination_proves_empty_terminal_and_preserves_display_mismatch
tests/test_manager_announcement_date_catalog.py::test_source_116_h_identifiers_are_preserved_even_when_not_numeric_master_tickers
tests/test_manager_plan_identity_r2.py::test_autorun_cannot_shortcut_stale_plan_by_timestamp_alone
tests/test_manager_plan_identity_r2.py::test_scheduled_existing_plan_is_not_reused_when_inputs_changed
tests/test_manager_plan_identity_r2.py::test_scheduled_same_inputs_do_not_double_publish
tests/test_manager_plan_readback_issue24.py::test_failed_save_readback_never_gets_success_journal[CURRENT_NOT_CONSUMED]
tests/test_manager_plan_readback_issue24.py::test_failed_save_readback_never_gets_success_journal[CURRENT_WRONG_RUN]
tests/test_manager_plan_readback_issue24.py::test_failed_save_readback_never_gets_success_journal[CURRENT_WRONG_SHA]
tests/test_manager_plan_readback_issue24.py::test_failed_save_readback_never_gets_success_journal[NOT_MATERIALIZED]
tests/test_manager_plan_readback_issue24.py::test_failed_save_readback_never_gets_success_journal[READBACK_FAILED]
tests/test_manager_plan_readback_issue24.py::test_failed_save_readback_never_gets_success_journal[STALE_INPUTS_CHANGED]
tests/test_manager_plan_readback_issue24.py::test_legacy_over_64_mib_is_read_losslessly_without_rewrite
tests/test_manager_plan_readback_issue24.py::test_null_and_insufficient_evidence_survive_lossless_save
tests/test_manager_plan_readback_issue24.py::test_success_returns_read_back_terminal_attempt
tests/test_manager_us_daily_chain.py::test_daily_persistence_readback_keeps_full_assessments_and_artifact_sha
tests/test_manager_us_daily_chain.py::test_daily_uses_shared_33_symbol_relation_resolution_and_keeps_mover_filter
tests/test_manager_us_daily_chain.py::test_existing_daily_dispatch_path_reaches_the_same_persisted_owner
tests/test_manager_us_daily_chain.py::test_relation_source_and_review_sha_changes_invalidate_daily_reuse
tests/test_manager_us_daily_chain.py::test_sealed_20261009_daily_archive_withholds_20261011_relation_bodies
tests/test_manager_workspace_targeted_r2.py::test_half_day_close_is_native_and_can_anchor_window
tests/test_manager_workspace_targeted_r2.py::test_hk02_panel_pointer_after_cutoff_fails_closed_without_older_revision
tests/test_manager_workspace_targeted_r2.py::test_hk02_panel_pointer_selects_verified_repair_only_after_it_is_available
tests/test_manager_workspace_targeted_r2.py::test_hk02_panel_rejects_recovery_manifest_pinned_to_the_wrong_parent
tests/test_manager_workspace_targeted_r2.py::test_local_source_title_and_wechat_preserved
tests/test_manager_workspace_targeted_r2.py::test_missing_half_day_close_is_an_explicit_calendar_gap
tests/test_manager_workspace_targeted_r2.py::test_native_name_prefix_collision_uses_longest_non_overlapping_match[\u5357\u65b9\u6e2f\u80a1\u901a\u7ea2\u5229\u653f\u7b56\u53d8\u5316-master2-expected2]
tests/test_manager_workspace_targeted_r2.py::test_native_name_separate_source_positions_keep_both_issuers
tests/test_manager_workspace_targeted_r2.py::test_two_character_unique_chinese_issuer_in_delimited_title
tests/test_manager_workspace_targeted_r2.py::test_workspace_api_is_bodyless_same_origin_and_original_owner
```

## 可复验文件

- `run_regression_pair.py`：固定旧基线 SHA 的同环境复跑入口。
- `baseline_export_manifest.json`：原 git archive 来源及127个导出文件 SHA。
- `original_regression_comparison_exact.json`：两组命令、环境、106条 testcase 结果、完整29失败差集。
- `original_regressions_baseline_exact.log`、`original_regressions_candidate_exact.log`：原始完整输出。
- `original_regressions_baseline_exact.xml`、`original_regressions_candidate_exact.xml`：JUnit。
- `original_regression_hashes_before.json`、`original_regression_hashes_after.json`：两树与 support 字节绑定。
- `candidate_commit_binding.json`：提交cd93198后仍与本次测试字节一致。
- `inspect_original_failure_facts.py` 与 `original_failure_facts_baseline.json`、`original_failure_facts_candidate.json`：缺件／calendar／identity／PIT／原语义拒绝的原函数实证。
- `o_subreview/exact_support_final_20261011T082039322779Z/review_result.json`：最终3项独立Parquet测试及34文件前后哈希。
- `o_subreview/original_screen_comparison_20261011T082459203829Z/comparison_result.json`：原包与候选同Parquet10断言及37文件前后哈希。
