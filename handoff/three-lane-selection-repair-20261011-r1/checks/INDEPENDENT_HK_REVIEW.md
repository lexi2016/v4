# HK 原 Stage 摘要与 SelectionStore 复用：独立只读审查

## 结论与范围

本次候选代码审查发现的 `code` / `symbol` membership 身份不一致问题已由主代理修复；原顺序、显式安全标志和原回放字段的边界缺口也已补齐。最终独立检查为 **30 个 HK 投影边界 probes 通过、5 项原 SelectionStore / 原 provenance helper 检查通过、候选现有 focused pytest 39 项通过**。这些结果分别来自不同测试层，不能合并为现役或天然执行通过。

当前候选在已审查的“原 reader 返回值 → HK 研究摘要”及“原 SelectionStore → 三份文件身份”的范围内，未发现剩余阻塞性行为问题。完整 `stage_center.consumer` 仍因缺少依赖而不能导入。没有访问 Mac、采集真实行情、生成 D1 Top100、验证现役 scheduler/API/UI、发布或修改业务/测试文件；P3/P4 的真实数据与天然执行验收仍未成立。

审查者只写入本目录的报告和独立 harness。主代理是 candidate 的唯一 Writer。

## 已发现并修复的问题

### 1. membership 校验与展示股票可以不一致

原 HK 摘要核验 `row.code`，随后复用的 `connect_selection.filter_cards` 优先使用 `row.symbol`，摘要又输出 `row.code`。在既有 synthetic reader fixture 中，仅把第一行改成 `code=HK.00888`（不在目标 V2 名单）和 `symbol=HK.00002`（在目标名单），修复前即可返回 `READY`、候选 2，并展示 `HK.00888`。

现版本在原行声明 `symbol` 时要求其与 `code` 一致。独立复跑确认冲突行使通道 `CANNOT_CONFIRM`，`candidate_count=null`，没有回退到 focus；相同别名仍可正常展示。没有改写原行，也没有重新打分、排序或构造名单。

### 2. 原 projected order、显式安全标志与回放声明

原 consumer 的 `_project_market` 在复制每条合法原行后，无条件令 `order = len(projected_rows) + 1`。原 API 的 `selection_markets` 保留未经截断的 canonical 市场行。因此，对输入原序进行 1-based 整数校验符合已有合同，且不应按 rank 排序。现代码拒绝布尔或不连续原 order；V2 过滤后保留原 order，允许摘要中的剩余原行出现空号。例如第一行被拒绝时，第二行仍为 `order=2`。

现代码拒绝原行明确声明的 `RESEARCH_ONLY=False`、`production_allowed=True`、`buy_gate_updated=True` 或 `orders_sent=True`；未声明的可选行级标志不会凭空补成 owner 证据。

现回放检查覆盖 stage、market、execution_evidence 和 rows 中已有的 `mode` / `recovery_mode` / `source_mode` / `status` / `second_filter_status`，以及行的 `lane_evidence` / `candidate_lanes` 与显式 backfill 身份。这些字段有原源码依据：原 `selection.py` 的 D1 reference 分支输出 `HK_CONNECT_D1_PRESELECT_REFERENCE` 和 `WAITING_0920_SECOND_FILTER`；原 runner receipt 写入 `mode=BACKFILL` 和 `backfill_run_id`。独立 probes 确认这些声明不能进入普通 HK 摘要。

本次没有为缺失的现役 execution module 创造新的状态白名单，也没有从匹配 run 或 receipt 字符串推断天然执行通过。

## 当前调用与身份合同

| 位置 | 已核查行为 |
|---|---|
| `candidate/v4/manager_research/workspace.py`，`_compute_workspace` 起于 712 行 | 722 行读取一次 STAGE owner；828 行保留这同一次结果的深拷贝，不发起第二次 owner 请求。 |
| `candidate/v4/manager_research/workspace_projection.py`，479–502 行 | 整个原 `stage` 进入 `identity_inputs`、总语义身份及 `projection.stage` component。摘要小字典没有复制 rows，并不意味着原行未被总 plan 身份覆盖。 |
| `candidate/v4/manager_research/workspace.py`，`_readback_plan` 起于 1096 行 | 已保存 plan 必须满足身份 MATCH、总身份与 semantic version / 日期绑定一致、原 plan attempt 回读验证后，才 overlay 本次 `stage_selection`。overlay 保留原保存字节与计划 run，不重写 owner 文件。 |
| `candidate/v4/manager_research/workspace_daily_channels.py`，`_hk_stage_channel` 起于 151 行 | 读取原 HK canonical 市场投影，核目标 V2 scope、日历适用、固定 `STAGE_0935_0940`、三份 selection 文件身份、精确日期 D1 证据、计数与行身份，再做原 membership 过滤。 |
| `candidate/stage_center/consumer.py`，`_verified_selection_provenance` 起于 236 行 | 原 helper 保持不变；重新读取 exact latest entry 和同 run，校验 latest 的 artifact / manifest / receipt SHA 后返回 trio provenance。 |
| `candidate/stage_center/consumer.py`，670 行 | 普通 HK 或原有 backfill 分支复用相同 helper；A 股普通分支没有增加这一调用。 |
| `support_source/contracts/stages.py`，22 行 | `STAGE_0935_0940` 原 cutoff 是 `09:40:05`。摘要直接读取原合同，没有自行改成 `09:40:00`。 |

原 API 参考源码中，`project_shared_selection` 保留顶层原 payload，并以 `selection_markets=canonical_markets` 保留未截断行。Manager reader 使用原 consumer exact date / `STAGE_0935_0940` / `HK_CONNECT` 读取；现役 API 模块本次未完整导入，因此这里属于源码合同核查。

### artifact、raw 与执行回执的区别

`selection_artifact_sha256` 是 owner 保存的 `artifact.csv` 字节 SHA；`raw_artifact_sha256` 是原 Stage 输入身份。二者不能要求相等，不能互相替代。

`selection_manifest_sha256` 与 `selection_receipt_sha256` 按原 SelectionStore 的 canonical JSON 算法计算。原 JSON 文件末尾包含换行，因此其字节 SHA 通常与 canonical SHA 不同。独立 harness 对实际原 store 写出的测试 trio 核对了这一区别。

`execution_evidence.observed_sha256` 是原执行 reader 读取 receipt 后观察到的文件身份。`selection_binding=BOUND_TO_VERIFIED_SELECTION` 加上声明的四个身份字段（run、artifact、algorithm SHA、raw SHA）和 selected count 一致，仅绑定 selection reference。它不证明天然调度、PIT、真实进程或 API/UI 回读。

摘要顶层及摘要行的 plan run / product SHA 继续代表已保存计划；原 Stage run 和 selection trio SHA 位于 `source_selection` / `source_refs`。完整原 `stage_selection` 保留供回溯，`natural_run_verified` 仍为 false，行的 `formal_eligible=False`、`action_level=NO_BUY` 保持原值。

### 合法空结果

当前 `READY_EMPTY / candidate_count=0` 需要上述目标身份、scope、trio 与截止时间条件全部成立，还需要原 selection 为零行、`selected_rows=0`、`requested_rows=source_rows=100`、输入与 selection 状态一致、没有 missing/cannot-confirm 或 membership 拒绝，且同目标 Stage receipt 对 selected count 0 的 selection reference 绑定成立。

独立复跑确认：没有输入不能成为 0；只有 99 个原输入不能成为完整 0；空 selection 缺少执行 reference 绑定时为 `PARTIAL`、未知数量；非空已验证 selection 缺少执行绑定时仍可展示原研究候选并标为 `PARTIAL`。这既保留研究信息，也不把未评估或未完成伪装成完整空名单。

## 独立执行结果

| 检查层 | 实际结果 | 证据文件 |
|---|---:|---|
| 原 SelectionStore 真模块导入 + 原 helper 未改 AST + 原仓库测试 fixture | 5 PASS / 0 FAIL | `original_selection_provenance_results.json` |
| 既有 synthetic verified-reader fixture 的独立 HK 投影边界检查 | 30 PASS / 0 FAIL | `hk_daily_boundary_results.json` |
| candidate 现有 `test_manager_three_lane_channels_r1.py` | 39 passed in 0.44s | `focused_pytest.log` |
| 完整 `stage_center.consumer` 导入 | BLOCKED | 原 store 结果 JSON 中保留完整异常 |

原 store 检查使用固定 GitHub ref `a1b722e4c82defcb9537d5c05915c6a8072c02d3` 下的原 `_a_row` / `_hk_row` / `_publish_both` 单元 fixture。下载 fixture 的 Git blob SHA 为 `95cb72cc630399ef32cf54b2371313705fc2acfe`；它仅在自动清理的 TemporaryDirectory 中调用原 owner 写测试数据。没有把 fixture 的 20260813 测试 run 或 synthetic SHA 当成真实市场证据。

五项检查分别覆盖：正常 trio / 原 hash 语义 / 读不改写；latest 指向不同 run；latest artifact SHA 不一致；artifact 字节被改动；receipt row_count 被改动。额外验证了一个实际差异：原 `read_verified` 比较 latest 的 manifest / receipt SHA，但不会单独拒绝 latest 的 artifact SHA 被改动；原 helper 会拒绝这一情形，因此对普通 HK 复用该 helper 有实际完整性收益。

两套独立 harness 都核验了运行前后的被审源码 SHA 未变化。测试没有写 candidate、业务数据或原仓库测试文件。

### 复跑命令

在 `/workspace/scratch/ff44f882fe5c` 下执行：

```bash
PYTHONDONTWRITEBYTECODE=1 test_env314/bin/python review_outputs/hk_rebound_review/verify_original_selection_provenance.py --output review_outputs/hk_rebound_review/original_selection_provenance_results.json
PYTHONDONTWRITEBYTECODE=1 test_env314/bin/python review_outputs/hk_rebound_review/verify_hk_daily_boundary.py --output review_outputs/hk_rebound_review/hk_daily_boundary_results.json
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=candidate:candidate/tests:support_source:support_source/upstreams test_env314/bin/python -m pytest -q -p no:cacheprovider candidate/tests/test_manager_three_lane_channels_r1.py
```

## 最终被审源码 SHA256

| 文件 | SHA256 |
|---|---|
| `candidate/v4/manager_research/workspace_daily_channels.py` | `69f6a824a133343dff7c5bf7f0db240ab1d3af0bc3f74b618832982bd2b0b622` |
| `candidate/v4/manager_research/workspace.py` | `6d7119ba6fc762dbcd0ccd43897a26956eb24430e4f54352bed0aace6f9b07a7` |
| `candidate/v4/manager_research/connect_selection.py` | `238f608d8b130aaed6ecfeaea6a66550bf918045c82adeb9aa3ce4f7000ea291` |
| `candidate/stage_center/consumer.py` | `cbc91d835c94e88b5065c6e95711017f9e97fd4d5bd7c230b7e88acab54f1557` |
| `candidate/stage_center/selection.py`，与附件一致 | `31e80e068890be03957920870719030463262c78911953541be3074f8650d4c9` |
| `candidate/tests/test_manager_three_lane_channels_r1.py` | `0e888e94196fe6672018a26ac231340dc5266ae25ef3a853e586ce633892c232` |

原 helper 源码 SHA256 为 `57c1135b932c05f3cbd69861808f7cb4ecdedfb8c6d2d7cbcd17707fa3fbb16a`；其 AST 与附件中的原函数一致。报告及结果文件自身的 SHA 见本目录 `SHA256SUMS.txt`。

## 尚未完成的真实集成与证据

完整 consumer 导入首先报 `ModuleNotFoundError: No module named 'infrastructure.preselection_pool_store'`。即使补齐该历史依赖，candidate 也没有所需的现役 `stage_center/execution_evidence.py`：consumer 第 20 行需要 `research_source_projection`，第 798 行需要接受 `selection_store` / `selection_stores` 的 `read_stage_execution`。固定仓库里补读到的旧版模块不具备这些接口。未添加 fake/stub，也未用旧接口冒充现役。

原 SelectionStore / 原 helper 的可验证部分已经完成；真正运行 `StageSelectionConsumer.get`、Manager owner 保存与 sealed plan 回读、真实 API/UI 和 scheduler/receipt 闭环仍需现役源码依赖与原数据。附件仍是源配置快照，固定 GitHub 历史 activation/loaded 回执不能替代当前 Mac 进程证据。

HK V2 精确目标日 membership、原 canonical D1 Top100、原 Stage execution receipt 及完整 rebound 输入没有因本次候选代码修复而补齐。55 公告、10 backfill、214 strict 仍不能作为正式名单或 PIT 证据。P4 现有研究 decision ledger 的复用行为由 focused tests 覆盖部分边界，本报告没有声称 60 交易日数据、量来源、全部原股票判定和现役保存/UI 端到端均已验证。
