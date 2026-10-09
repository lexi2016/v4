# V4 Stage 恢复候选包：最终独立代码审查

## 结论

**PASS：可交付用于精确 SHA 匹配后的独立研究 canary。当前未关闭 Critical 0 项、Important 0 项。** 本结论针对已知源码、完整候选包和离线贯通验证；审查及测试运行主机为 Linux，不是 Mac。没有进行发布、真实行情验收或 NATURAL 执行验收。

本审查按 `superpowers:requesting-code-review` 进行，独立阅读相关前后像、接线代码和工具，并用边界回归复现问题。审查者只写自己的测试与报告，未修改业务源码。主控完成修复后，审查者核对了最终字节和验证收据。

## 固定版本与可信边界

- 候选包：`/workspace/scratch/49c844334a98/v4/handoff/stage-research-recovery-20261009-r2`。
- GitHub 交付锚点：`0fc3e8304e11700230517616ded0c86f83a4b257`；该值不代表已确认当前 Mac 正在运行的版本。各历史前像的来源仍以 SOURCE_MAP 逐文件记录为准。
- 最终 SOURCE_MAP SHA256：`f402f93009ff1e8ef588e04c994eec1897274d80970fc20ee07748a506156ce4`。
- 21 个源码文件：Stage 16、API 2、UI 3。before/after SHA 全部匹配；Stage 与 integration_app、API/UI 与实际测试副本全部匹配；3 个补丁与完整 before/after 一致；166 个离线支撑源码校验通过。
- 21 项 `current_mac_bytes_verified` 均为 false。实际落地仍只接受精确命中的已知前像或已知后像，不把缺失的当前 Mac/APIconsumer/UI 源码冒充已获得，也不进行模糊覆盖。
- 研究标记为 `RESEARCH_ONLY=true`，`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。

## 最终验证证据

最终收据：`/workspace/scratch/49c844334a98/package_verify_api_namespace/RESULTS.json`。

SHA256：`f2851fc64edfbe992f3708ba5fd330378690014473699208c3e818240497baa4`。

| 检查 | 最终结果 | 审查核对方式 |
|---|---:|---|
| Stage | 148 通过，0 失败，0 错误，0 跳过 | 读取最终 pytest XML 与 stdout |
| API | 82 通过，0 失败，0 错误，0 跳过 | 含最后新增的 6 项 backfill 默认回执根回归 |
| Vue | 45 通过，0 失败，0 跳过 | 读取最终 TAP 与真实 SFC 编译/SSR 结果 |
| 包字节检查 | PASS，21 源码、166 支撑源 | 审查者最后独立执行 verify_package.py，并再次比较源码副本 |
| 新建全链 fixture | PASS | 原 owner 历史 tick → 同 namespace store/owner receipt → 完整 consumer → 原可获得 API projection → 实际 App/Panel |

上述整包运行由主控执行；审查者独立检查了收据、XML、日志、fixture 断言及其源码。审查者此前另外实跑了 integration+边界 47 项、A 行情字段与算法 52 项、canary 初版 11 项，以及坏 manifest 诊断 1 项；这些与整包检查有重叠，不相加。最后 consumer 的 6 行接线修复由最终整包 82 项 API 和新建全链 fixture 覆盖，未用更早的绿测替代它。

### 最后一条实际接线已经覆盖

`export_integration_fixture.py` 调用原 `owner.tick(..., historical_backfill=True)`。读回时只构造 `StageSelectionConsumer(actual_namespace_selection_root)`，与已存档原 API 的调用方式一致，不额外传入 receipt root。构造器只把 `<root>/selection/backfill/<safe-id>` 映射到同一 `<root>/receipts/backfill/<same-id>`；显式传入的 receipt root 优先，普通 stage/selection 规则保留，其他布局不扫描或回退。

最终 fixture 的同次 run_id 为 `run-2c40a8d057e1beffde847ab1`。HK 请求与有效行情均为 695，保留原算法选出的 10 行。A 缺证据时保持自己的 CANNOT_CONFIRM/无结果身份，没有借用 HK 行或 run。owner 历史记录为 `OWNER_HISTORY_SHA_BOUND`，selection 为 `BOUND_TO_VERIFIED_SELECTION_TRIO`。

- HK algorithm SHA256：`fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506`。
- Raw artifact SHA256：`3c942a34e3dcb713ed250f0d42e5f031f4aa09e0cb09b3691678a0a288576741`。
- Selection artifact bytes SHA256：`aa69e1d04c009ac033434ec5be156465bff2db964b2a14815c00c7b894054100`。
- 全链绑定相同日期、阶段、市场、run、raw 和 algorithm。API 保留真实选股结果；原 projection 的观察展示不会抹掉 owner 已核验的 10 行结果。Vue 主结果显示“已计算 10 只”与“行情 695 / 695”，同时展示名单日期、stale 和 Connect 资格待确认。
- 执行来源保留 CURRENT_DAY_RESEARCH_REPLAY，attempt_mode 为 RECOVERY，execution_verified 与 natural_verified 都为 false，UI 未显示自然执行标签。

## 已关闭的具体问题

| 编号 | 原问题与最终位置 | 修复及证据 |
|---|---|---|
| FR-01 | A 发布前指针重读异常可能中止 HK；slot_execution.py 第 560、606、623 行 | 最终重读按市场隔离；A 的观察计数保留，失效输入不发布 A raw/selection，HK 继续选 10。独立 pointer 竞态回归已包含于最终 Stage 检查。 |
| FR-02 | API/Panel 未穷尽 replay origin；execution_evidence.py 第 339 行、StageExecutionEvidencePanel.vue 第 73 行 | 四种显式 replay origin 全部阻止 NATURAL。历史/晚到与旧 natural 字段冲突的回归已通过。 |
| FR-03 | 原 owner 的 NOT_DUE 早退回执缺 markets，最终 reader 拒读；runner_receipts.py 第 66 行 | writer 归档前补空对象，不发明市场执行；真实 tick→reader 仍保留来源与不可变历史绑定。 |
| FR-04 | 合法 JSON 但形状错误的 manifest 使只读诊断抛 traceback；diagnose_source_witness.py 第 124、144、165、194 行 | 增补 AttributeError/KeyError 的安全失败处理，输出 CANNOT_CONFIRM；验证器与输入不变。manifest=[] 红测转绿。 |
| FR-05 | 拷贝后的全 consumer 测试仍引用旧工作区；tests/test_final_review_edges.py 第 78 行 | 运行中的测试改用包相对路径；最终整包在新输出目录执行通过。 |
| FR-06 | 原 API 只传 selection_root，canary backfill 结果无法自动绑定 owner 回执；consumer.py 第 294、303 行 | 精确同 namespace 默认映射，6 项 API 回归以及原构造方式的完整新 fixture 通过。此项由主控发现、独立复核。 |

最终未发现仍会阻断本次已知源研究恢复目标的 Critical 或 Important。修复没有放宽证据校验，没有把另一市场的结果或回执当成本市场证据。

## 原算法与输入边界

- 默认 STRICT 保留；当前研究名单仅由显式 hk_current_day_research_root 启用。四个输入文件的 raw SHA 固定；metadata/reference 用于代码与来源绑定，不能成为报价、正式 PIT 或港股通资格证明。
- Pin 保留 trade_date=20261009、universe_as_of=20261008、captured_at=2026-10-09T15:38:41+08:00、stale_universe=true、CURRENT_DAY_RESEARCH_ONLY、Connect=CANNOT_CONFIRM、formal_d1_eligible=false、formal_pit=false。
- 行情仍通过现有 PyTDX ExHQ 的精确阶段分钟来源进入原算法。当前研究通路仅覆盖六个普通分钟阶段；09:25 和 Stage8 所需的不同来源缺失时不以 snapshot 或分钟数据冒充。
- HK 四路公式、排序与 Top10 未换算法；A live/auction 相对本次 stage_base_app 的算法文件逐字节不变。该 baseline 已包含此前 R1 的 null/真实 0 输出修复，本次没有重写其打分与排序。A 的 216 输入/205 或 206 有行情仍按原算法研究选 10。
- 09:25 的 prev_close 传递和拒绝 bool 昨收属于字段契约恢复，未替换算法。输入、行情投影和 builder 失败分别保留各市场的证据。
- writer 记录当次已加载模块的路径与磁盘文件 SHA；这是观察，不是内存中实际执行字节的证明。manual/research/historical/late 回放不会获得 NATURAL 身份。

| 原算法 family | SHA256 |
|---|---|
| A_SHARE_LIVE_AND_AUCTION | `eee20b08b50a693dd673f93937ef4eedc63e909295820a0141ce5e728a3754d2` |
| HK_FOUR_LANE | `fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506` |

四个原算法核心文件的 baseline/candidate SHA 对照及四 raw 输入 SHA 完整保存在配套 JSON。真实四份用户文件尚未提供给 Chat；695 fixture 是合成安全资料和外部行情 I/O，不能被描述为已跑通用户真实 695 数据。

## 21 个最终源码后像 SHA256

以下路径相对包内对应 after/<group> 根；完整前像、来源、测试副本和当前 Mac 未核验字段保存在配套 JSON。

| 分组 | 文件 | 后像 SHA256 |
|---|---|---|
| stage | `ops/_run_stage_center_nodes_parts/deadline_supervision.py` | `1f65476c5a274195b789a3529a3e95821bfcf81278c6ac72e01c52655932cf08` |
| stage | `ops/_run_stage_center_nodes_parts/node_entry.py` | `fd544913cacff11e9fe8ed5ca682239d3ff4185d8c1b810934637580cdb65aa2` |
| stage | `ops/_run_stage_center_nodes_parts/runtime_arguments.py` | `515a739b73e4a874489958aa4d207ae7aca643166a356c2bc05d494ad5f2a93a` |
| stage | `ops/run_stage_center_tick.py` | `f362bb04734fb78e847bdf6e435a29bc01a66f6186ddfd4c52cb0efc7c21b439` |
| stage | `stage_center/_live_collectors_parts/hk_minute.py` | `03300128a9525d49b0aedd77b35fa7cbeda464900d6802b503a001172a5ccf65` |
| stage | `stage_center/_live_collectors_parts/selection_builder_registry.py` | `13fa73cc9b00c1255c05421f43eddc4155a0c14b4488b2a9829a0b496f6337df` |
| stage | `stage_center/_runner_parts/configuration.py` | `62416ad875ff37a95ae222e3c8c4094a351b53229daa5313d43f5d27a98899be` |
| stage | `stage_center/_runner_parts/hk_candidate_authority.py` | `57bf97d5edb73ba2f226d102bb81c9079f84aebf67ead45d5649ebfe5cc932cb` |
| stage | `stage_center/_runner_parts/hk_input_validation.py` | `7bd2ca1e47a9831170c64b2d5d6ecbfe5b0e66d7e664ae4b2c3dcc9d4aaf1c74` |
| stage | `stage_center/_runner_parts/runner_receipts.py` | `94fb3592619a8012904e4193280b5cd4f78f5c898b8fdd6cc5751398dc7f882d` |
| stage | `stage_center/_runner_parts/selection_input_validation.py` | `87265f5027b2c8fb4c7d74dc8ea0c748df7f449516bc21f20b2f839de8a595fb` |
| stage | `stage_center/_runner_parts/slot_execution.py` | `3ed350bb9b072806a8b033055dbfa29b1ccc7292df6d79cbff61e55c8409112e` |
| stage | `stage_center/_selection_parts/a_auction.py` | `01b00f748daa0ef7b0502805d977d883b20616c2070aa35685744af8f9131af1` |
| stage | `stage_center/_selection_parts/a_live.py` | `4225b27df7067663da42b635773bf90e94b4601fc2478b8decb5c635f77d86a0` |
| stage | `stage_center/runner.py` | `ea9909bb4f39c4248032771aedd9611a852353e940451e0b0c7273bde8c26345` |
| stage | `upstreams/v3_shared_data/scripts/live_acquisition/pytdx_hq.py` | `fdd849fc032b5745d6611df31b5f9a147b14207d77dca953dff7b0ea4140cea2` |
| api | `stage_center/execution_evidence.py` | `1be96e736fda2863f6f8ff2315e8879a98499bbd30f5a911b46423c4dc6f094b` |
| api | `stage_center/consumer.py` | `16f004edb60ab256993f02ec4df36caa5d2cb3aa55bff643834c3119ec86d207` |
| ui | `apps/web/src/App.vue` | `01903e69d06579c29d4d576bfe739420112ddb2778b6c321f7cb6ef587141f7d` |
| ui | `apps/web/src/components/review/StageExecutionEvidencePanel.vue` | `a9d044cd03325cb09acefd5e3c57c2a7e49cb1b61e22eadba0c50cf51963b273` |
| ui | `apps/web/src/contracts/runtime.ts` | `b3d437e906f81d08af045f5b0f3990662c64676572376d42edddaf109f3dd980` |

## 6 个交付工具源码 SHA256

以下均为最终包内工具；prepare/diagnose 已含 RESEARCH_ONLY=true，不以 lane_hk 的旧副本作为最终字节。canary driver 与 a_fields 冻结值一致。

| 工具 | SHA256 | 字节 |
|---|---|---:|
| `tools/diagnose_source_witness.py` | `f7907128a8dd256b86e7320313ee4df2a9374a3100490a6f354965d3bff25dec` | 11304 |
| `tools/export_integration_fixture.py` | `f8705126a5f80dee7a016ed1c1f654e0dcb4bbbbc74309da49f88a7c5670f45b` | 1710 |
| `tools/prepare_canary.py` | `e09ea8493dbf775b6162c252b0707b5dc2f121cf0ab7495c0b953efa2135b751` | 12760 |
| `tools/run_checks.py` | `2bfdd7afc8ecbbbc3307958a4d80e8dd27dbc71e5e0d1e17b0b6bc4a4bc4a0e5` | 6069 |
| `tools/run_current_research_canary.py` | `802657e5edcde27904b18635aeaa717c481cb49aa8a9884e939f30dbc7ebd679` | 18523 |
| `tools/verify_package.py` | `3583ef87d7d298c1dec72dc0ce2883a19833b6f1c6e8b12cb2e625a85952611b` | 4159 |

## 可移植性及尚未验证的事实

主要执行入口和最终执行测试使用包相对路径或显式参数/环境路径。UI 依赖通过 --ui-runtime 或 STAGE_UI_RUNTIME 指定；测试输出放入新目录。归档辅助 checks/api/tests/run_verification.py 仍保留一个旧默认 runtime 路径，它不由 tools/run_checks.py 调用；本审查不把历史辅助脚本里的每个绝对字符串都说成已清除。

canary driver 会先核验候选 Stage/HQ 后像和四个 pin 文件，再创建独立输出；需要复制外部 shared_data 时，先核验原 HQ 的精确已知前/后像，再复制依赖并写入已知后像。原输入与配置保持不变。真实 owner 以子进程和历史模式运行；没有 HK 行时报告 EXECUTED_NO_HK_SELECTION 并非零退出，不把空结果说成成功。

当前 Mac 的源文件、owner 进程、HTTP 服务、实时 PyTDX 可用性、真实四文件与当前 canonical 状态没有在此主机验收。已知前像精确匹配失败应停止落地，不改成 fuzzy。真实 quote 与自然时点执行仍需要在 Mac 按本任务已约定的落地测试确认；这些事实缺失不被列为已知代码错误，也不被隐藏成通过。

报告的可交付结论以本次 SOURCE_MAP、21 后像、6 工具及最终 RESULTS 的 SHA 为边界。任一这些字节变化后，应针对实际变化复核，不能沿用本报告声称它已经审过。
