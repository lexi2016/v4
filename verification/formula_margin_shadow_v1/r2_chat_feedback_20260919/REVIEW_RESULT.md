# R2 独立验收结果

结论：FAIL。无P0，有2个P1。本轮独立Reviewer为formula_shadow_review，与Writer不同身份。仅报告并反馈Chat，未继续修复。

## 已通过
Fix1实际source/rule/formula/D1字节SHA绑定及rawSHA一致、完整有序canonical rows；Fix3 hit/markout分离；Fix4共享static capture helper（日期缺陷除外）；comparator冲突拒绝、固定100行、真实selector Top10与baseline一致、默认关闭和callback失败隔离。
selection.py和ops均与R2冻结版本一致。

## P1-1 truth authority仍未在程序中阻断
位置stage_center/formula_margin_shadow.py:_truth_metadata（约1592行）。传入临时生成40行JSON，truth_universe_version=operator-made-anything-v1，truth_source_version=caller-json-v1，coverage_ratio=1，Top20与自造JSON计算一致，实际append_labels返回READY，invalid_reasons=[]，universe_count=40。改source_version=HISTORICAL_ARCHIVE_FIXTURE仍READY。
没有绑定既有exact-date membership authority/manifest、close producer/FINAL、公司行动、停牌及source tie-break。文档写“truth adapter blocked / every truth unit CANNOT_CONFIRM”但运行仍允许。现有数据源七项事实见SOURCE_AUTHORITY_FACTS.md。

## P1-2 前一日时间可伪装当天forward capture
位置_validate_capture_request_static约1118行、time_evidence约1201、build_shadow约1252。仅captured_at<=cutoff而未要求上海时区日期与trade_date一致。
反例：trade_date=20260921；cutoff_ts=2026-09-21T09:35:05+08:00；captured_at=2026-09-20T09:35:00+08:00。
实际preflight_capture_input -> READY_FOR_SELECTOR_CAPTURE；capture_selector_snapshot -> READY/FROZEN；freeze_snapshot -> FROZEN。

## P2/待裁决
删除time_evidence.source仍可READY_FOR_SELECTOR_CAPTURE；目前只对mapping/captured_at做校验。time-evidence binding是否必须包含source identity需要明确，不能自行定义。
WATCH_ONLY+no_trade_gate=0手工拒绝通过，但缺独立自动测试；自制且自洽全集反例未加入现有自动测试。

## 独立测试（组合有重叠，不能相加为不重复总数）
1. tests/test_formula_margin_shadow.py + tests/test_stage_scoring.py + stage_center/tests/test_selection_consumer_batch3.py：29 passed。
2. tests/test_close_review_producer.py + tests/test_stage_name_read_overlay.py：22 passed。
3. stage_center/tests/test_selection_consumer_batch3.py + tests/test_stage_projection_regressions.py：19 passed。
另一次含tests/test_recurrence_repairs.py的宽回归：37 passed,7 failed；scheduler/runner/ledger已有其他批次修改，独立Reviewer无法归因于本三文件diff，记CANNOT_CONFIRM，不声称全仓库通过。

自然样本0。未启动5日canary、20日pilot、40日验证；无automation/BUY/交易/部署。
