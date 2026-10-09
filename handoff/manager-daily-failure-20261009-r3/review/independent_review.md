# R3 独立包装审查

**结论：PASS（仅限冻结的问题包与交接合同）。** Reviewer `/root/r3_failure_package_review`，独立于 Writer `/root/r3_failure_package_writer`。本审查验收问题包、来源证据和 Chat 修复范围；不代表业务代码已修复，也不代表 10/8、10/9 真实计划已生成。

## 审查范围与证据

- 已检查 `package/README.md`、`CHAT_TASK.md`、`EVIDENCE.md`、`acceptance.json`、`current_vs_candidate.json`、`root_cause_matrix.json`、`source_manifest.json`，以及三份 `evidence/` JSON 和 `tools/validate_package.py`。未修改 package/evidence/tools 原件。
- 独立按 manifest 的源根、相对路径与快照逐项计算字节数和 SHA-256：33 条记录中，32 个可用快照与源及记录相符；1 个缺失的 active API namespace 明确标记为缺失且未造 stub；其余 3 个可用源没有 expected SHA，并在 receipt 中单独列出。Issue32 三个保护文件的源与快照 SHA 相符。
- 七份 package/evidence JSON 均可解析。对 package、evidence、tools 再做一次高置信凭证模式扫描，命中 0 项。两次 GET 的响应正文没有写入包；投影仅保留状态、字节数和响应 SHA。未发现原始行情、名单、计划/state 或凭证材料。
- 静态调度路径与证据吻合：worker 调用 `request_bound_plan_cycle`（`source_snapshot/current_bound_announcement_worker_20261006/ops/run_manager_announcement_cycle.py:256-257`）；API 先比较 binding SHA，再检查 enabled（`source_snapshot/current_api_manager/v4/manager_research/plan_owner_dispatch.py:348-356`）。因此 `PLAN_OWNER_BINDING_SHA_MISMATCH` 是条件式静态预测，不是实际 dispatch 错误回执。
- 11:00 两次顺序 GET 投影都记录计划 `NOT_MATERIALIZED`、无 `run_id`、US daily run `NOT_RUN`；11:06 身份投影记录 scheduler/API binding SHA 与 app root 不一致。dispatch receipt 未读取，故“10/9 是否触发”仍为 `CANNOT_CONFIRM`。R1/R2 候选 PASS 只证明其冻结候选测试范围，不能证明已部署或产出经理计划。
- `coordination/DELIVERY_README.md` 按发布根 README 的路径编写；完整保留包目录层级时，package/evidence 链接可解析。远端逐文件读回尚待主控完成。

## 定向复审与目标合同

首次审查发现的 P1 是 Chat 任务没有限定日期对应的 `view` 行为。Writer 已修正 `package/CHAT_TASK.md` 与 `package/acceptance.json`：

- 10/8 事后保存的计划显式用 `view=dynamic` 验证，普通 `view=auto` 保留既有历史资格与读回语义；不要求 auto 消费这次事后 run。
- 10/9 仅在当日计划已保存时，要求普通 `view=auto` 回读同日期、`run_id`、产品 SHA 与输入身份。
- 任一日期输入缺失时保留 `CANNOT_CONFIRM` 和原因，不强制生成 run/SHA/股票列表；输入完整但合法筛选为空时，允许可追溯空结果。
- 合成 fixture 只证明代码合同；真实 10/8 与 10/9 产品仍待 Mac 执行验收。

定向复核确认以上合同在 `CHAT_TASK.md:16-19,23-24,31-41` 与 `acceptance.json` 中一致。修订 SHA 与 `evidence/validation_receipt.json` 登记值相符：Chat 任务 `2f60c6cfbde6982457c7f64fd45706ebbc931ad851bd77f8a26027a6b00a06ec`，acceptance `6298ffe5bb5f0cfcf3d9d5c64fdfcb817019e5e0e3469cb30c27293b817d7aee`。修订后的 receipt SHA-256 为 `efba9abd62ae7797b16254533859ef5b45d11c3465c2379dc3b6a9a4c88ed064`。

## 风险与验收状态

- **P0：无。P1：无（原日期合同 P1 已修复）。P2：无。** 本批无需增加业务回归测试；Chat 任务已列出绑定门禁、调度/API 同身份、日期路径、合法空结果与缺失输入的针对性合成测试。
- `REVIEWED=PASS`：只表示本报告所列包装与合同审查通过。
- `IMPLEMENTED/TESTED`：问题包材料由 Writer 交付；Writer 的机器验证回执为 PASS，Reviewer 复核了目标修订与其 SHA。未将 Writer 回执当作真实业务行为证据。
- `BEHAVIOR_VERIFIED=CANNOT_CONFIRM`：本次不运行真实 owner 请求、不生成计划，也不重读 API/UI 或自然时段结果。10/8、10/9 计划产物、真实选股与逐股理由、实际 dispatch、Python 已加载模块身份均未证实。
- `GITHUB_SYNC_AND_READBACK=CANNOT_CONFIRM`：等待主控发布并逐文件读回。本结论不替代该交付步骤。

**范围声明：这是问题包验收，不是业务修复。**
