# 附件原 103 项测试：27 个基线失败分诊

## 结论与适用身份

**最终统一 API 支撑后，原 103 项在基线与候选均为 78 PASS / 25 FAIL，失败用例集合相同；此前 76 PASS / 27 FAIL 的原日志完整保留。** 两项转绿来自主控补齐已核验的 API `announcement_observation.py` 辅助字节，不属于生产补丁。本分诊没有删除或修改原测试，没有更改生产源码，没有把诊断用例通过计入原 103 项。本次证据未证实一项新的“真实失败读回被成功返回/被 GET 消费”的 P1 缺陷；但也不能把全部 27 个历史失败统称为旧 fixture。其中包含缺失的发布/工件闭包、API/canonical 辅助源码不匹配，以及一个已复现的 journal 顺序差异。

这份报告的逐项历史归因和独立诊断描述 `work/baseline_package_tests_aligned.log` 对应的离线支撑状态。该日志 SHA-256 为 `ba749ae258409128ce9f86587ce82c2f2ed99cb62157f40a4aec08503ad6d41b`。后续主控的最终支撑与回归结果另列于下一节，没有覆盖此日志或倒推这里的失败从未存在。

基线是附件指定 commit `a7f5d09fb19de10564925757207977aadc080cc1` 的 20 份固定 R2 文件；离线实际源码根为 `/workspace/scratch/0e089a11ee60/four_function_gaps/work/baseline/app`。两次诊断都核对这 20 份文件与 `input/package/code/r2_chat_patch_target` 完全一致，并验证所有被监测的源文件及四份原测试在诊断前后未改变。辅助源码来自已记录的冻结 Git 字节，只是离线导入支撑，不是当前 Mac release 绑定。

关键固定生产字节：

| 文件 | SHA-256 |
|---|---|
| `v4/manager_research/workspace.py` | `a6225ef5583a73c066a5c31400f84e237aaceb63abefcf199cfb8c9b8af7dcdc` |
| `v4/manager_research/connect_selection.py` | `eaa01a13d8065b11cc8397a12edaad8b892f183158aa1f9475d29645dee09d83` |

执行环境为 Linux、`runtime_locked/bin/python`、CPython 3.12.14，31 项依赖版本与锁定清单完全相同。项目要求 Python `>=3.14`；Mac/Python 3.14、现役 owner state、实际 UI/API、自然时段、部署及服务验收均为 **NOT_RUN / CANNOT_CONFIRM**。测试输入全部是合成材料，真实网络访问由诊断进程的 audit hook 拒绝。没有读取行情或账号数据，没有服务操作或 GitHub 写入。

## 最终支撑统一后的收敛

主控完成辅助文件对齐后，本分诊只读核对了 `work/verification/{baseline,repaired}/supplied_regressions.json`、对应 rawlog、最终辅助文件 SHA 和原测试 SHA。两树都使用 API `announcement_observation.py`（5,599 bytes，Git blob `9e28c8b939fccc3f82da89d19a0f9dc157a26b92`，SHA-256 `8e58cab8e9e398d7c628c2f994a5005442d3a6c5ba5f218a155d949b8af74f54`），其第 72 行确实传递 `positive_observations`。四份原测试字节保持一致。

- `test_scope_filter_keeps_counts_gaps_and_original_lane_unchanged` 和 `test_observation_only_never_uses_invalid_or_duplicate_evidence[duplicate]` 在两树最终原测试运行中都 PASS，印证先前的辅助投影缺口归因。
- Issue8 最终剩 3 FAIL：旧日期错误枚举断言、verified-scope 正例、缺冻结子树。**verified-scope 仍为 0 卡的唯一已定位直接原因是原 `scope()` 没有声明 V2 `membership_semantics`。** `evidence_view` 对两条 official documents 调用 `filter_cards` 时，`_scope_error` 先返回 `HK_CONNECT_MEMBERSHIP_SEMANTICS_UNVERIFIED`，两个文档均被剔除，attention 的输入已经为空。它与本轮 `read_at` 身份修复无关；最终 API 正例投影字段已经补齐，历史上的第二个潜在投影问题不再是最终失败原因。
- Catalog 2、supervisor 13、plan 7 的失败集合均未改变；因此总数为 3+2+13+7=25。

| 主控最终分组（只读核对，未由本分诊重跑） | 基线 | 候选 |
|---|---:|---:|
| 附件原 supplied regressions，103 项 | 78 PASS / 25 FAIL | 78 PASS / 25 FAIL |
| app wiring，20 项 | 17 PASS / 3 FAIL | 20 PASS / 0 FAIL |
| 既有 announcement，59 项 | 58 PASS / 1 FAIL | 58 PASS / 1 FAIL |
| adjacent owner contracts，113 项 | 112 PASS / 1 FAIL | 112 PASS / 1 FAIL |
| 合计，295 项 | 265 PASS / 30 FAIL | 268 PASS / 27 FAIL |

Adjacent 唯一失败为 `test_worker_plan_only_uses_bound_rpc_and_never_builds_collection_service`：`ops/run_manager_announcement_cycle.py:497` 的真实入口显式检查 `sys.version_info < (3,14)` 并抛出 `PYTHON_314_REQUIRED`。两树一致，属于当前 Python 3.12 离线环境无法完成的入口验收；保留 FAIL，不能改版本门禁或伪装解释器版本。这里的 295 项汇总不扩展本分诊的生产缺陷结论。

| 最终原 103 项 rawlog | SHA-256 |
|---|---|
| `work/verification/baseline/supplied_regressions.log` | `910855b456de0e1823bf02bf757004f61b6baa4cda6a57a8f4521585a1bb5c50` |
| `work/verification/repaired/supplied_regressions.log` | `597ac40201842f25a99968751838f4c415ad8e5d82b48b5fdb29f99fa511454f` |

## 原 27 FAIL 的四组历史归因

| 原测试文件 | FAIL | 分诊 |
|---|---:|---|
| `test_issue8_selection_gaps.py` | 5 | 2 项 V2 语义 fixture 差异（其中一个还存在后续投影差异）；2 项 API/canonical 投影支撑不匹配；1 项缺少环境绑定且缺少冻结工件。 |
| `test_manager_announcement_date_catalog.py` | 2 | 旧 master 交集断言与所用 catalog 支撑的 source-identity 合同不同。 |
| `test_manager_announcement_supervisor.py` | 13 | 都在 `_binding()` 复制缺失的 `apps/__init__.py` 时失败，尚未进入各自要验证的绑定断言。 |
| `test_manager_plan_readback_issue24.py` | 7 | 1 项 legacy fixture 没有当前要求的 owner journal；5 项注入真实读回函数不会产生的自相矛盾成功标志；1 项严格 journal 顺序断言未满足，但最终调用和后续 GET 仍拒绝消费。 |

## Issue8：逐项归因

这里有两个独立差异，不能混为一个 V2 问题。

第一，原测试 `scope()` 第 26–32 行设置了 `OWNER_VERIFIED`、来源 SHA、日期和 identity，却没有 `membership_semantics`。固定 `connect_selection._scope_error()` 第 144–166 行明确要求 `TARGET_DATE_CAPTURED_HK_CONNECT_AUTHORITY_V2`；只有在该语义成立后才按相应合同核 source date 和 identity。缺少语义时返回 `HK_CONNECT_MEMBERSHIP_SEMANTICS_UNVERIFIED` 是当前 fail-closed 行为。

第二，本轮当时使用的 `announcement_observation.event_lane()` 来自 10/05 **canonical** 辅助文件，返回对象没有 `positive_observations`。已经对齐的 `research_attention.py` 来自同日 **API** 文件，其 `_positive_observation_view()` 读取 `lane.positive_observations`。输入 review 的 positive statement 因此在中间投影处丢失。这是确定的离线支撑合同缺口；该辅助文件不在附件固定 20 文件中，没有足够证据将它归为当前 R2/Mac 生产缺陷。

| 原失败用例 | 实际触发 | 分类与处置 |
|---|---|---|
| `test_open_unknown_membership_not_promoted_and_prior_day_rejected` | 第 128 行期望日期/role 错误，但 `scope()` 缺 V2 语义，先返回 `HK_CONNECT_MEMBERSHIP_SEMANTICS_UNVERIFIED`。接受列表仍为空。 | `FIXTURE_CONTRACT_SKEW`。诊断只在内存中给该 scope 声明明确 V2 语义后，旧日期立即得到原期望的日期拒绝。不得放松 V2 gate。 |
| `test_scope_filter_keeps_counts_gaps_and_original_lane_unchanged` | 第 142 行期望 1 个 observation，实际 0；此前 counts、gaps、原 lane 不变等断言已通过。当前 `event_lane` 没传 positive 字段。 | `SUPPORT_API_CANONICAL_PROJECTION_MISMATCH`。先核 API 辅助文件身份，不能据此改固定生产文件。 |
| `test_verified_scope_admits_fresh_official_evidence_only_and_does_not_create_focus` | 第 155 行 scored cards 为空；scope 缺 V2 语义，official documents 已在 `evidence_view` 被拒绝。 | `FIXTURE_CONTRACT_SKEW`，另有后续潜在投影失败。内存补充 V2 语义后 admitted official=1、scored symbol=`HK.01234`；observation 仍为 0，因为 event_lane 另缺字段。两项来源必须分别处理。 |
| `test_observation_only_never_uses_invalid_or_duplicate_evidence[duplicate]` | 第 175 行期望去重后 1 个，实际 0；positive 输入在到达去重逻辑前已丢失。 | `SUPPORT_API_CANONICAL_PROJECTION_MISMATCH`。诊断在中间合成 lane 恢复原 positive 字段并放入两条相同输入后，得到 1 条 observation、0 scored cards，focus/qualified/buy 均为 false。这是定位探针，不是源码修复。 |
| `test_frozen_positive_subtree_preserved_without_promoting_five_stocks` | 第 240 行 `V4_INPUT_ROOT` 未设置，且附件不存在 `evidence/FROZEN_SELECTED_FIELDS.json`。 | `FROZEN_EVIDENCE_NOT_SUPPLIED`。仅设置环境变量仍不能运行原精确子树断言；不得制造那 9 个 observation / 5 个 symbol 或用新数据替代。保留 FAIL，实际子树验收 NOT_RUN。 |

辅助文件身份与待绑定替代：

| 角色 | 冻结仓库路径/字节 |
|---|---|
| 诊断时 `announcement_observation.py` | `handoff/v4-running-source-20261005/canonical/v4/manager_research/announcement_observation.py`；Git blob `1f585c53233cd49de8e4d104b05b3d5ed6f6a03d`；5,435 bytes；SHA-256 `f86f2f0ac90b4e4490a74a27984c84f9c632075c47862d3627493282afef17ed`。 |
| API 替代版本 | `handoff/v4-running-source-20261005/api/v4/manager_research/announcement_observation.py`；Git blob `9e28c8b939fccc3f82da89d19a0f9dc157a26b92`；5,599 bytes。独立诊断时只确认 tree 元数据；之后由主控核实字节并对齐，最终 SHA 与回归结果见上一节。 |
| 诊断时 `research_attention.py` | API 支撑已对齐；Git blob `c3edf3996d77247615da563c4309dac8967113bc`；SHA-256 `3f5385ed850b0336cb85ad85cac3aeab44d2908620c636a4cfc19f5fdf3619aa`。 |

## Catalog：两个旧合同断言

当前辅助 `announcement_catalog.py` 来自 `handoff/manager-daily-chain-20261008/compat_r3/candidate_app/v4/manager_research/announcement_catalog.py`，Git blob `aa12f2f47edb63819d91519c6c4747882512dd6f`，SHA-256 `25b07260dbe6591a6b26c3560d1873fe2e01fd76edd07a55d977bb80b0696a68`。它不属于附件固定 20 文件。

| 原失败用例 | 证据与结论 |
|---|---|
| `test_dynamic_pagination_proves_empty_terminal_and_preserves_display_mismatch` | 分页、21 行计数、终止空页、强制请求标志和日期 mismatch 等断言均已通过；失败在第 111 行 `manager_consumer_use` 的旧文案。当前函数第 394–407 行明确使用 `SOURCE_IDENTITY_RESEARCH_REFERENCE_ONLY_NOT_CONNECT_ELIGIBILITY_OR_SELECTION_RESULT`，并声明 `connect_eligibility_status=NOT_ASSESSED`。分类为 `CATALOG_CONTRACT_VERSION_SKEW`。 |
| `test_source_116_h_identifiers_are_preserved_even_when_not_numeric_master_tickers` | 第 132 行期望 manager rows 为空；当前 source-identity 合同保留合成来源标识 `H5354`，同时 `matched_master_codes=[]`、Connect eligibility 未评估、semantic analysis 未运行。分类同上；这不是把 `H5354` 升格为已验证证券或 Connect 成员的证据。 |

来源重派生诊断再次用合成内存 listing blob 运行 `verify_product_sources()`，验证 product SHA 和来源投影一致。当前源码第 508–524 行还保留 `source_identity_basis` 缺失时的 legacy master-intersection 重派生分支，直接证明这两套合同有意并存。不要为通过旧断言而删去源标识或放松 membership/semantic 安全边界。

## Supervisor：13 项没有进入业务断言

原测试 `_binding()` 第 64–82 行先复制源目录，再在第 70 行执行 `shutil.copy2(original/'apps/__init__.py', ...)`。下面 13 项全部在该处以相同 `FileNotFoundError` 中止。**原运行结果是 FAIL；要检验的正/负向 `validate_binding` 行为则是 NOT_RUN。**

| # | 原失败用例 |
|---:|---|
| 1 | `test_binding_inventory_includes_full_stage_and_body_capture_dependency_closure` |
| 2 | `test_complete_bound_source_inventory_and_disabled_config` |
| 3 | `test_plan_only_binding_requires_separate_matching_manual_owner_canary` |
| 4 | `test_plan_only_binding_accepts_fresh_manual_owner_evidence_from_same_api_root` |
| 5 | `test_plan_only_binding_rejects_response_body_with_wrong_sha` |
| 6 | `test_plan_only_binding_rejects_forged_or_announcement_canary` |
| 7 | `test_plan_only_binding_rejects_owner_source_migration_mismatch` |
| 8 | `test_binding_rejects_source_and_root_drift[missing_catalog]` |
| 9 | `test_binding_rejects_source_and_root_drift[unlisted_new_source]` |
| 10 | `test_binding_rejects_source_and_root_drift[changed_source]` |
| 11 | `test_binding_rejects_source_and_root_drift[state_overlap]` |
| 12 | `test_binding_rejects_source_and_root_drift[python_target]` |
| 13 | `test_binding_rejects_source_and_root_drift[unsafe_flag]` |

附加只读闭包核查：

- 当前 `REQUIRED_FILES` 和 `PLAN_OWNER_REQUIRED_FILES` 显式清单都**仅缺** `apps/__init__.py`；`PLAN_OWNER_SOURCE_FILES` 的八项均存在。这只说明显式清单状态，不证明递归导入、运行时绑定或 canary 通过。
- 冻结 `base_repository_tree.json` 的 `truncated=false`。全树没有 `apps/__init__.py` 的已确认原始字节，不能从该 tree 补齐。
- `apps/api/__init__.py` 唯一已列版本是 canonical 路径，Git blob `481352bbb1ecff3a6a08b12f73f6ed8ab3be3dcf`、41 bytes。当前文件 SHA-256 `ba6c324cbd4be60367b15bd3d6035c8165ee11c8ef9950d3282a0bb75849c991` 已匹配该冻结支撑。
- 不创建空 initializer，不减少 REQUIRED_FILES，不把缺发布文件当成业务缺陷。只有拿到可信的完整发布源字节后，才能重跑这 13 项并确认其后续结果。

## Plan issue24：旧 mock 与真实读回分开

### Legacy 大文件读取与消费资格是两个判断

`test_legacy_over_64_mib_is_read_losslessly_without_rewrite` 第 52–58 行的大文件读取相等、inode/size/mtime 不变断言已通过；只有第 59 行把 legacy product 直接判为 CURRENT 的断言失败。该 fixture 的 `put_legacy()` 只写 `workspace_plans/<date>/latest.json`，没有写 `workspace_plan_runs/<date>/<run_id>.json`。

固定 `verified_plan_attempt()` 第 969–980 行要求精确同 run 的 owner journal，缺失时返回 `WORKSPACE_PLAN_ATTEMPT_MISSING`，真实 `_readback_plan` 投影为 `OWNER_ATTEMPT_UNVERIFIED / consumed=false`。小体量同构诊断确认 `_read_plan` 仍无损读取、无重写，消费资格拒绝。**分类：`LEGACY_FIXTURE_MISSING_OWNER_ATTESTATION`；不应取消 owner 验证来满足旧 CURRENT 断言。** 本分诊没有重复运行 64 MiB 内容测试，实际大文件断言结果来自原 rawlog 的失败位置。

### 五个 “DID NOT RAISE” 是自相矛盾的 mock envelope

原参数化用例第 179–185 行直接替换 `_readback_plan`。除 `CURRENT_NOT_CONSUMED` 外，所有参数都设置 `consumed=True`，包括 status 为 `READBACK_FAILED`、`STALE_INPUTS_CHANGED`、`NOT_MATERIALIZED` 的返回，及错 run/SHA 的 CURRENT 返回。

固定真实函数第 1035–1069 行使用同一个 `same` 决定 `status='CURRENT'` 与 `consumed=True`，并从同一个已验证 saved product 投影 run 和 SHA。它不会自然输出上述自相矛盾组合。固定刷新函数也已将最早的持久化检查移到 `_read_plan` 第 1236–1239 行：在写成功 journal 之前核验存盘 schema/日期/input identity/SHA，并比较期望 run 和产品 SHA。

| 原参数 | 原断言结果 | 分诊 |
|---|---|---|
| `READBACK_FAILED` | DID NOT RAISE | `CONTRADICTORY_MOCK_ENVELOPE`：失败状态却 consumed=true。真实此状态不带消费成功。 |
| `STALE_INPUTS_CHANGED` | DID NOT RAISE | 同上；真实 stale 必须 consumed=false。 |
| `NOT_MATERIALIZED` | DID NOT RAISE | 同上；真实无 saved product 不会有成功消费。 |
| `CURRENT_WRONG_RUN` | DID NOT RAISE | mock 替換最终投影却绕过此前真实产品 run 检查；真实错误 run 诊断已被终态前拒绝。 |
| `CURRENT_WRONG_SHA` | DID NOT RAISE | mock 替換最终投影却绕过此前真实存盘 hash/expected SHA 检查；真实错误 SHA 诊断已被终态前拒绝。 |

这些原测试继续记 FAIL。最终仅检查 `consumed` 的代码并非对任意外部不可信 envelope 的通用验证器；但该私有调用点读取的是同模块的固定函数。没有独立真实触发路径时，不能为了旧 mock 全绿添加一项“生产 P1”归因。若未来允许替换读回实现，可另做 status/run/SHA 的防御性闭包校验；本轮没有提出该范围扩展。

### `CURRENT_NOT_CONSUMED` 暴露了真实顺序差异

该参数通过了预期异常断言，却在第 188 行发现曾写 `SUCCEEDED_EMPTY`。这是固定生产代码的真实顺序：先完成存盘产品核验，再封存并读回 terminal attempt，最后 `_readback_plan` 才能用这份同 run 终态 journal 验证 owner。若最后的完整读回失败，异常分支会把 attempt 改回 FAILED、恢复先前 `last_success_at`、删除 `success_scope`。

本次保留真实 `_readback_plan`，只在临时 SafeRoot 的指定读取点注入合成 I/O 故障，并在写入真正完成后记录 journal 状态：

| 合成场景 | 完成写入的 latest journal 顺序 | 调用/后续真实 GET |
|---|---|---|
| 无故障 | RUNNING → SUCCEEDED_EMPTY | 返回 CURRENT/consumed=true；后续 GET 同样 CURRENT。 |
| 首次产品读回 StoreError | RUNNING → FAILED | 抛 StoreError；GET 为 OWNER_ATTEMPT_UNVERIFIED、consumed=false。 |
| 首次产品读回为另一合法 run | RUNNING → FAILED | 抛 WORKSPACE_PLAN_SAVE_READBACK_FAILED；GET 拒绝消费。 |
| 首次产品读回 SHA 被改 | RUNNING → FAILED | 抛 WORKSPACE_STORED_PLAN_INVALID；GET 拒绝消费。 |
| 成功终态写完后的产品读取 StoreError | RUNNING → SUCCEEDED_EMPTY → FAILED | 真实读回为 READBACK_FAILED，刷新抛 WORKSPACE_PLAN_SAVE_READBACK_FAILED；GET 拒绝消费。 |
| 成功终态写完后的 exact-run journal 读取 StoreError | RUNNING → SUCCEEDED_EMPTY → FAILED | 真实读回为 OWNER_ATTEMPT_UNVERIFIED/consumed=false，刷新抛异常；GET 拒绝消费。 |

所有五个真实故障场景最终均无成功返回，terminal 为 FAILED，初始无历史成功的 fixture 中 `last_success_at=null`，且没有 `success_scope`。因此确认的是 **`STRICT_JOURNAL_ORDER_NOT_MET`**，不是“真实失败已成功消费”。原严格断言应继续作为 FAIL 保留。

如果 owner 仍要求“任何观察者在任何时刻都不得见到成功 journal，直到全部读回完成”，就需要单独明确提交协议和并发/崩溃语义；不能直接把最终 `_readback_plan` 移到 terminal journal 写入之前，因为当前同 run owner 校验会因此必然失败。安全的后续设计应先区分候选终态验证与对外提交，保留产品 SHA、exact-run journal、日期/input identity 和失败回收校验，再针对读回故障、并发观察、进程中断验证。**这一更强协议不是本轮两个已确认 source patch 的附带修改。并发/进程中断/自然 I/O 故障没有执行，保持 NOT_RUN。**

## 诊断命令、真实结果与文件

工作目录：`/workspace/scratch/0e089a11ee60/four_function_gaps`。

`test_diagnostics.py` 是对历史支撑状态的取证脚本，其中明确检查“当时 event_lane 缺少 positive 字段”。最终两树已对齐该 API 辅助文件，因此不要把这份历史诊断整文件原样作为最终候选的回归套件；应按记录的旧辅助 SHA 重建历史环境，或仅运行不依赖该历史差异的 journal 诊断。最终候选回归以主控 `work/verification/` 的固定命令和记录为准。

第一次执行仅为诊断 suite：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=work/baseline/app runtime_locked/bin/python -m pytest -q -s -p no:cacheprovider -c /dev/null --confcutdir=review/baseline_triage --basetemp=review/baseline_triage/tmp review/baseline_triage/test_diagnostics.py
```

结果 **1 FAIL / 3 PASS**，保存在 `diagnostic_initial_harness_error.txt`。失败是诊断脚本只捕获 ValueError/OSError，未捕获继承 RuntimeError 的 `StoreError`；生产代码已经写 FAILED。随后只在诊断脚本的捕获元组补上 `s.StoreError`，保留原脚本和原日志，没有修改生产或原测试。其余 3 个诊断已完成，结构化结果在 `diagnostic_initial_results.json`。

只重跑该一个诊断：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=work/baseline/app runtime_locked/bin/python -m pytest -q -s -p no:cacheprovider -c /dev/null --confcutdir=review/baseline_triage --basetemp=review/baseline_triage/tmp_plan_rerun review/baseline_triage/test_diagnostics.py -k real_plan_readback_fault_boundaries
```

结果 **1 PASS / 3 DESELECTED**，保存在 `diagnostic_rawlog.txt`；完整六场景结构化记录在 `diagnostic_results.json`。这不意味着原 103 项全绿，也没有重复原全部项目 suite。

| 证据文件 | SHA-256 |
|---|---|
| `diagnostic_initial_harness_error.txt` | `127692c936198ae5766f7335d1b82018715838a8a19c3dd4566855ca52b9475d` |
| `diagnostic_rawlog.txt` | `35e0bc0a1eecea553936663261709c18712759a8117ad9ee959d78dd2a4098ea` |
| 修正后的 `test_diagnostics.py` | `b1a37c745d8db0622d2aec20e4588a476e955ede51732569fcd00c72f1fe1213` |

精简交接建议保留本报告、`triage_summary.json`、诊断源码、两次 rawlog 和结构化结果。临时 `tmp/`、`tmp_plan_rerun/` 内均为合成运行状态，不进入源码补丁或发布闭包。原错误与原 27 FAIL 不能抹除；发布/owner 完整性仍由原主控在真实版本绑定后独立验收。
