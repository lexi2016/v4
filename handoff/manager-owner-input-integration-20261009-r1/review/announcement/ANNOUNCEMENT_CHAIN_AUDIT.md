# 公告 owner → R2 workspace consumer 独立核查

## 结论与身份边界

当前冻结的 `target=20261009 / publication=20261008` 公告缺口，证据支持 **真实 owner 输入与 import 尚未具备**，未证实固定 R2 的公告消费者发生代码断线。完整 `create_app` 注入的实际 consumer 已用明确标注的 synthetic owner 工件独立运行并验证能显示原 SELECTED row。因此本轮公告生产源码保持零 diff。

`evidence/app_wired_get_summary_20261009.json` 的 `ANNOUNCEMENT_ANALYSIS_NOT_IMPORTED` 对应 `workspace_announcements.read_analysis_consumption` 2366–2370 的精确产品文件缺失分支。该分支尚未到 catalog、Reader、Reviewer、owner receipt 或 cutoff 校验。`announcement_review=NOT_RUN` 是另一条原始公告扫描投影的状态，不能据此推断已导入的独立分析产品必然无法消费。

这不否定用户所述 2026-09-30 独立成功入口；包内未提供其 receipt。2026-10-07→10-08 的 metadata 证明过公告子链消费：33 selected、54 watch、75 pending，87 channel rows，channel PARTIAL。该证据不证明 10-09 有真实 capture/import，也不证明 HK Connect、oversold 或整份 plan 已完成。

源码权威边界如下：

- 生产分析基线：`input/package/code/r2_chat_patch_target`，固定 commit `a7f5d09fb19de10564925757207977aadc080cc1` 的附件投影。
- 离线测试根：`four_function_gaps/work/baseline/app`。附件中的 20 个固定 R2 文件覆盖对应位置；其余文件由协调者按同 commit Git blob 核验，仅作运行支撑，见 `four_function_gaps/work/support_provenance.json`。缺失的 30 处通用 `_namespace.py` 则逐字节复用同 commit 原始 527 字节 helper，仅标为 ISOLATED_TEST_IMPORT_SUPPORT，详见 `four_function_gaps/work/import_support_adaptation.json`；不能据此声明完整 Mac 构建身份一致。
- 为使附件 `create_app` 能调用原非 manager review router，并匹配 manager API 所需支撑接口，协调者另从同 commit 补回原 API review router、API research_attention 与原 canonical package initializer；所有字节身份见 `work/api_support_alignment.json`。未采用 wrapper、空 router 或替换 manager owner 行为。
- 历史 reference runner：`input/package/code/actual_owner_runner_20261009/ops/run_manager_daily_announcement.py`，不能冒充 R2 或 Mac 当前进程的 CLI。
- Mac 实际状态、已导入原始产品、实际 Reader/Reviewer 身份、部署、API/UI 和自然时段运行：**CANNOT_CONFIRM / NOT_RUN**。

## 逐段接线证据

| 链路 | 固定 R2 锚点 | 可证实行为 |
|---|---|---|
| App 注入 | `apps/api/v35_api/app.py` 3790–3816、3854–3889、5222–5270 | manager state 显式参数优先，其后专用环境变量，再按 host/隔离根规则解析；私有 runtime package 装载实际服务。同一 manager root 下的 `materials` 构造唯一 MaterialStore；store 与 provider 均接此实例。公告没有缺失的另一个 workspace reader 注入参数。 |
| Service | `v4/manager_research/service.py` 441–459 | `get_announcement_date_catalog → read_date_catalog`；`get_announcement_analysis → announcement_analysis.read`；`import_announcement_analysis → announcement_analysis.import_product`。 |
| 精确产品位置 | `announcement_analysis.py` 20、57–62 | `store.root/workspace_announcements/{target}/eastmoney_date_catalog/{publication_token}/analysis.v1.json`。不能用其他目标日或 publication 重贴日期。 |
| catalog 回读 | `workspace_announcements.py` 1072–1118 | 验证 target/publication、产品 digest、原 MaterialStore 字节、分页 owner attempt/receipt 与 run；缺失返回 NOT_RUN，坏来源 READBACK_FAILED。GET 不采集。 |
| 注册工件 | `workspace_announcements.py` 2013–2154 | 固定 evidence root 内的原 Reader/Reviewer/body/catalog/decisions/product 文件必须齐全并 hash 一致；日期/run/decision/source identity 必须匹配；检查 capture receipt 和 acquisition time。 |
| 独立身份 | `workspace_announcements.py` 1714–1758 | Reader/Reviewer 均非空，strip 后不能同名；输出 SHA 和决策 payload SHA 均绑定。这是声明身份的字节链验证，代码本身不提供平台身份签名认证。 |
| owner import API | `manager_research_router.py` 490–563 | 请求只收 evidence_run_id、handoff manifest SHA 和 product SHA 引用；调用原注册验证和 service import，写完整四绑定字段的 owner receipt，回读并验证消费链。 |
| API GET | `manager_research_router.py` 461–488 | 用存储的完整原 product 验证 owner receipt，再调用共享 `read_analysis_consumption`；GET 不构造新分析产品。 |
| exact pair 与 cutoff | `workspace_announcements.py` 2297–2505 | 显式 publication 只读一个日期对；缺产品即 NOT_IMPORTED；通过产品/source/judgment/import receipt/handoff/source time 后才到 cutoff；晚于 cutoff 不消费。合法 pair 分别消费，坏的旧邻居不全局拦截新的合法 pair。 |
| workspace 接收 | `workspace.py` 684–699、846–856、881–903 | 原公告材料与 reviewed analysis 均由现有 reader 获得；`announcement_reviewed_analysis` 进入 workspace；已消费 product identity 进入最终 plan input identity。 |
| daily channel | `workspace_daily_channels.py` 79–134 | 只显示 target/publication 精确匹配且 CONSUMED 的产品引用，保留原 SELECTED/CONDITIONAL_WATCH 与理由。未评估保持 PARTIAL；完全未导入时 candidate_count=None，不能标有效空。此通道不受 HK Connect 或 oversold 缺项的全局阻断。 |

## R1 与 R2 比较

`announcement_analysis.py` 在 R1 与 R2 完全相同，SHA-256 均为：

`b60b8c0c663b203d2ece5a5b451eb41ca296396b2db3630dff4a92a8566f373f`

`workspace_announcements.py` 差异仅包括更严的 Reader 非空/strip 身份校验及新增 `validate_owner_analysis_readback`，未移除 R1 已证明能消费的 `read_analysis_consumption` 主链。两版本哈希：

- R1：`ea259666727b71c78760d666f3fe7f90350829bdce5f2b55745927528546af04`
- R2：`82187a190f2a308cc193473a9583f0c8edb82782ce45217a1dce8c866f172f0b`

## 历史 runner 与 R2 新 receipt 的兼容问题

旧 reference runner `_readback` 641–646 把 API analysis 投影缩成 `{target_trade_date, publication_date, sha256}`，再交给 `validate_owner_analysis_import_receipt`。R2 验证器 2179–2188 对带新四绑定字段的 receipt 要求完整 `agent_judgment_receipt`；薄投影必然缺此信息，错误为 `ANNOUNCEMENT_OWNER_IMPORT_RECEIPT_HANDOFF_BINDING_INVALID`。

这属于**已定位的旧 CLI / 四字段绑定 receipt 合同不兼容**，发生于导入后的独立 CLI readback，不解释 10-09 在 import 之前就没有产品的冻结缺口。四字段验证已存在于 R1 consumer 2179–2188，R1 router 403–405 也写这类新 receipt；因此不是声称 R2 独有的新回归。仅含 legacy parent/product 绑定的旧 v1 receipt 不触发此分支。旧 runner `_import` 454 使用 evidence 内的完整 product，不能与 `_readback` 的薄投影问题混为一谈。

固定 Git 支撑 `ops/run_manager_daily_announcement.py` 645 已调用 R2 专用 `validate_owner_analysis_readback(result)`，无需本轮重复修补。其 SHA-256 为 `aee0e5c31f30b296864a7ad81263fbc748b65cb9b4d443f83a756019cbc94a38`；旧 reference runner SHA-256 为 `bfb853fb982e0b2da1024fa942ae9dc5d67fa88a8d112f46054608641129c1ee`。Mac 实际执行哪个 SHA 仍需原 owner 确认。

## 独立回归与结果

新增实验仅在 `review/announcement/test_app_wired_announcement_chain.py`；未修改生产文件。

测试复用基线已存在的 source fixture 与原 catalog/body owner，所有来源文本、Reader/Reviewer 身份均显式标注 synthetic，并只写 pytest 临时目录。随后用 **完整 `create_app` 注入的实际私有包 service** 完成 reference import、analysis GET、workspace GET，保留其默认 MaterialStore 和独立读取器。

断言包括：

1. 相同 state 下未 import 时保留 `ANNOUNCEMENT_ANALYSIS_NOT_IMPORTED`、零 rows、未知 candidate_count。
2. 现有工件注册后通过完整 app POST import，GET 显示原 SELECTED row，并让 run/product/manifest/owner receipt SHA 贯穿一致；本例可用时间满足 cutoff，input_identity 随这次合格导入变化。
3. HK Connect/oversold 缺少 owner 输入且原 announcement review NOT_RUN 时，已导入 analysis 仍可独立进入公告 channel。
4. 精确 publication 不匹配时不回退；Reader 原字节被测试损坏后，即使 product 和 receipt 留存，也同时被 API 与 workspace consumer 拒绝。
5. GET 前后保存字节完全相同；任何实际 socket connection 都被测试禁用；安全 flags 与 natural_run_verified=false 不变。

历史 reference CLI 的版本兼容比较放在独立 `reference_readback_compatibility.py`，使新 app-wired 测试可以直接作为普通项目回归使用，不依赖附件 reference 路径。该脚本对同一原 R2 owner GET 证明旧 CLI 触发既有四字段 receipt 合同错误、固定 Git 支撑 CLI 通过专用 readback validator。

首次运行现有 parity/handoff 测试的命令：

```sh
/workspace/scratch/0e089a11ee60/work/python_runtime/bin/python -m pytest tests/test_manager_announcement_parity_20261008.py tests/test_manager_announcement_handoff_20261009.py -q --disable-warnings --maxfail=1
```

运行根为 `four_function_gaps/work/baseline/app`。首次结果：**ENVIRONMENT_BLOCKED，测试未收集**；`ModuleNotFoundError: No module named 'starlette'`。

随后统一使用 `four_function_gaps/runtime_locked/bin/python`；协调者已逐项核对 31 项锁定依赖版本。实际 Python 为 3.12.14，低于项目 `>=3.14` 声明，仍是明确测试环境限制。所有后续测试使用 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:tests` 和 `-p no:cacheprovider`，不在冻结 baseline 写入字节。

| 测试 | 当前结果 | raw log |
|---|---|---|
| 新 app-wired 回归首次 collection | exit=2：支撑闭包缺 `stage_center._selection_parts._namespace` | `app_wired_test.log` |
| 现有 parity + handoff 首次 collection | exit=2：支撑闭包缺 `ops.daily_materialize` | `existing_parity_handoff_tests.log` |
| 现有 parity 首次 `--maxfail=1` | exit=1：7 PASS，1 FAIL | `parity_only_test.log` |
| 现有 parity 完整运行 | exit=1：38 PASS，1 FAIL，3.69s | `parity_complete_tests.log` |
| 补齐 import 支撑后的现有 handoff | exit=0：20 PASS，2.90s | `existing_handoff_after_support.log` |
| 补齐 import 支撑后的新 app-wired | exit=1：`create_app` 的非 manager review router 签名不兼容 | `app_wired_test_after_support.log` |
| 旧 runner / 固定支撑 CLI 对同一原 R2 owner GET | exit=0：已复现预期旧错误、新 CLI 通过且 GET 无字节改写 | `reference_readback_compatibility_result.json` |
| 补齐已核验 API 支撑后的新 app-wired | **exit=0：1 PASS，2.35s** | `app_wired_test_aligned.log` |
| 同一最终 API 支撑下完整 parity + handoff | **exit=1：58 PASS，1 FAIL，6.19s** | `existing_parity_handoff_aligned.log` |
| 可移入项目 tests 的最终 app-wired 文件 | **exit=0：1 PASS** | `app_wired_test_final.log` |

parity 的唯一 FAIL 是 `test_missing_original_archive_is_not_empty_connect_selection` 381：该测试手工 scope 未提供 `calendar_applicability`，R2 `connect_selection.formal_selection` 依法返回 `CANNOT_CONFIRM / HK_CONNECT_CALENDAR_UNVERIFIED`，上层 diagnostics 是 PARTIAL，而旧 fixture 仍期望 READY。`legacy_fixture_failure_diagnostic.json` 保存了调用实际生产函数得到的原因。未修改测试或放宽生产门槛来掩盖 FAIL。其余 38 项公告日期、import、owner/shared consumer、Reader/Reviewer 身份、cutoff、hash、partial/empty 和 legacy 产品回归均通过。

新 app-wired 初次构造失败是 `app.py` 5165 向旧支撑 review router 传入其不支持的 `hk_close_root`；该初始故障完整保留。协调者从同 commit 找到支持此参数的原 API review router 后，最终完整 app-wired 回归通过。实际实例类型为 `_v4_manager_research_runtime.service.ManagerResearchJobService`，从独立 manager root 与原 MaterialStore 读取，未使用最小 mock service 替换其注入路径。

最终有效命令为：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:tests \
  /workspace/scratch/0e089a11ee60/four_function_gaps/runtime_locked/bin/python \
  -m pytest -p no:cacheprovider \
  /workspace/scratch/0e089a11ee60/four_function_gaps/review/announcement/test_app_wired_announcement_chain.py \
  -q --tb=short --maxfail=1

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:tests \
  /workspace/scratch/0e089a11ee60/four_function_gaps/runtime_locked/bin/python \
  -m pytest -p no:cacheprovider \
  tests/test_manager_announcement_parity_20261008.py \
  tests/test_manager_announcement_handoff_20261009.py -q --tb=short
```

以上是离线合成工件、真实应用代码与 in-process ASGI 接口验证；不是 10-09 真实公告数据验收、Mac 运行验收、外部 API/UI 验收或自然时段成功。最后唯一既有测试 FAIL 仍原样保留，未改为跳过或预期失败。

## 交回 Mac 原 owner 的最小动作

在同一实际 state root、确切日期对和 cutoff 下，核查已有 catalog/body capture receipt、原 Reader output 与原独立 Reviewer output、run 与 SHA；已有工件只走原 `prepare → register-handoff → import → readback` 合同。若缺 capture 或实际审阅，仍由原 owner/原独立角色完成，Chat 不代造。

完整真实工件导入后，原 plan owner 以明确 `selection_date=20261009, announcement_date=20261008` 重建，再通过实际 `create_app` 服务 GET 回读 product/input SHA。缺工件仍 CANNOT_CONFIRM，晚于 cutoff 仍不消费，旧计划仍服从 stale identity guard。修复和验收都不改变 `RESEARCH_ONLY=true / production_allowed=false / buy_gate_updated=false / orders_sent=false`。
