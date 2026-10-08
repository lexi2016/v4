# Issue #29：三条原业务链与每日输入接续核对

固定新输入：`b22836ef3f8fcc6b9218f3422a9bcd7aa61152e9`。本报告为 Chat 在 Linux 中的只读源码/已发布回执核对，不是重新执行 Mac、采集、计划或页面。当前 listener 身份仍须本机独立核对。该只读核对子任务没有修改生产源码、Stage、共享 app.py、启动配置或业务产物；本交付的两项代码变更另见 README 与 source_manifest.json。

## 结论与修复边界

1. **已找到历史业务成果，不能以当前 plan reader 的拒读否定它们。** 已发布证据分别证明：9/29 原公告正文抓取；9/30 17:20 原日面板及证券主表自然生产；10/4 以 9/30 输入形成的 689 条超跌/研究决策在 10/2 回看页面逐条对应；10/6 发布的 9/30 五条 US→HK 回顾研究，以及原每日 US owner 的手动保存/HTTP 读回。它们覆盖的日期、运行种类及完成层次不同，不能拼成“9/30 三路自然运行全部完成”，也不能抹掉用户报告的单日成功。
2. **新 Mac service 已有 US 每日原入口。** b228 `service.py:412–415` 的 `refresh_us_mapping_research(target_trade_date, *, now)` 调用原 `persist_daily_run`。此前仅在旧 assembled source 中未找到该方法的结论，不能套用到这份 Mac 切片。
3. **10/8 缺主表的原生产链落点已明确，但这次失败原因尚未闭合。** 原 `research_panel_daily_hk` 的同一次调用可以依次完成 captured membership、HK02 面板和 securities master；具体本次是否没触发、传错日期、写到别的 root 或在后段验证失败，仍缺 10/7、10/8 的实际 dispatch/capture/ensure 回执。不能根据缺文件直接选择其中一个原因改代码。
4. **10/8 面板已经存在。** Issue #29 的新 manifest 核对取代早期“latest 只有 10/2”的表述；它不补齐 10/7、当日主表、目标日 V2 publication，也不证明 volume unit 或 native finality。现行 StoreError 隔离修复保留。
5. **US attention、US 原文关系、US reviewed/daily 以及 HK_CONNECT 资格必须分开。** Mac 页面已把 `us_mapping_research` 传给原 research renderer；三路摘要中的 `HK_CONNECT` 仍是资格过滤后的既有 focus，不是美股映射。把该标签改成美股或借用其数量，会造成语义错误。

## 一、原入口 → 日期 → 输入 → 消费 → 产物 → 页面

以下 `M` 表示实际注入的 `service.store.root`；`S` 表示 API 实际绑定的 shared authority root；`P` 表示原 `ResearchPeripheralStore` data root。不能从目录名称推定三者相同。完整路径与运行身份应由 Mac 回执一起绑定。

| 流程及已经找到的版本 | 日期参数及规则 | 原 producer / 输入路径 | 原 consumer | 结果路径与 API / UI | 已证范围及缺口 |
| --- | --- | --- | --- | --- | --- |
| 公告：原 `ManagerResearchJobService.refresh_announcements`；9/29 run `c5d263c65c7540eba022d81e1f644002` | 原 run 的日期为 20260929，`MANUAL_REFRESH`，06:32:31.310103Z。新版按 target 与 publication 两个日期绑定，不能把 9/29 capture 改成 9/30 新采集 | `workspace_announcements.refresh` 使用既有 Eastmoney/HKEX 来源及 MaterialStore；历史产品在 `M/workspace_announcements/20260929/eastmoney_hk/<run>.json`，正文通过已有 source_key/blob_sha 读回 | 原正文/发行主体 classifier；新链的 reviewed analysis 通过已注册 reader/reviewer handoff、原 owner import、同 target/publication/SHA 读取 | 日期目录 `M/workspace_announcements/<target>/eastmoney_date_catalog/<publication>/`；`analysis.v1.json`；GET announcement-analysis 与 workspace；普通公告区及 daily ANNOUNCEMENT | [#8 历史抓取记录](https://github.com/lexi2016/v4/issues/8#issuecomment-5923282281) 证实正文与分页 SHA，PDF本体当次未重读。#29 另证实 10/7 的 33/54/75 同产品消费及日期切换。9/30 用户所指另一完整成功 run 尚未定位，保留 CANNOT_CONFIRM |
| US→HK 原材料关系：`us_market_bridge.project_us_market` → `research_attention` / `research_evidence`，#8/#22/#24 已验过的链 | `latest_completed_session(research_cutoff)` 使用原 US 日历；不是直接把香港 target 当 US session。材料须保留 publication/available/retrieved 与 cutoff，不能用 first_seen 别名补时钟 | 原 `v4_dispatcher.us_market_digest` / `ops.us_market_digest` 写 `P/research/peripherals/<US session>/external_finance.json`，配套 receipt+manifest；原 ResearchLaneSource 提供发行主体材料 | `ResearchPeripheralUsMarketReader.read_exact_session` → `project_us_market` 仅验证/投影涨幅；`issuer_us_relations.material_us_relations` → `research_evidence.us_mappings` 才产生合格关系 | workspace `us_market_attention` 是输入；`research_attention.us_mapping_diagnostics` 才是关系评估，原 renderer 展示二者。#22 对成功 reason 的说明已修并部署 | 9/30 09:53 plan 的 attention READY 只证明固定 24 行业代理/33 配置标的输入，不证明关系 join。#22 合成正向 detail 已验，真实原材料 84 条缺取得时钟仍保留；不能回退 #22 或伪造 0/成功 |
| US→HK reviewed 与每日 projection：历史 `manager-us-mapping-daily-20261006-r2`；新 Mac service 入口已保留 | reviewed 只绑定 20260930；其文档为后续回顾研究，不能当 9/30 当时已知。daily 使用显式 target、aware now、原 `plan_context`、精确完成 US session 和已发布 registry availability | 历史 `us_mapping_reviewed_20260930.json` + `us_mapping_relation_registry.json`，再读上述同一个 US owner。固定四个 reviewed US ticker 的关系范围，既非全市场也非新关系自动发现 | 原 `ManagerResearchJobService.refresh_us_mapping_research` → `persist_daily_run` → `_read_saved`；workspace 的 `_daily_mapping_plan_reference` 保留精确日期/cutoff/产品身份 | `M/us_mapping_research/<target>/runs/<run>.json` 与同日 `latest.json`；workspace `us_mapping_research.daily_run`、`reviewed_research`；Mac catalyst panel 第 472 行传入原 research renderer | [PAGE/DAILY 交付](https://github.com/lexi2016/v4/tree/840b9538c45c9ba8fd56f8e89048aff230df0f0f/handoff/us-mapping-daily-workbench-20261005) 记录 5 条历史卡片 live 8873 通过、一个手动计划 CURRENT/PARTIAL、09:27 配置安装；自然未验。新 Mac 实现模块/registry 的逐文件 SHA 与实际每日 run 尚未附，不能复制旧 R2 覆盖 |
| 超跌：原 `read_rebound_screen` / `REBOUND_V3`，R10 历史接受记录；b228 新 Mac 完整函数已读 | 原规则保持收盘 ≤ 此前 60 个完整交易日高点的 80%，成交量 ≥ 前 5 个完整交易日均量的 1.5。`screen_context` 根据 HK 原日历选择 cutoff 前已完成的完整 session；盘前与收盘后的数据日可能不同，原 plan 的 market_session 不被重写 | 原 HK02 `S/assets/hk_0_2/panels/<date>-<sha12>/manifest.json` 和 parquet，精确 `S/assets/hk_security_master/latest.json.entries[screen_date]` → 同日 manifest/receipt/artifact；如存在则读原 HK02 supplement | `workspace.get_workspace` 通过 `_workspace_screen_authority_root`，否则已绑定 `_workspace_security_master_root` 调 `read_rebound_screen`；`build_research_selection_ledger` 只投影原逐股决策 | workspace `market_screen`、`research_attention.research_selection`；daily OVERSOLD 与原全部逐股决策区。保存仍由原 `refresh_workspace_plan` 写 `M/workspace_plans/<target>/<run>.json` | [R10 原验收](https://github.com/lexi2016/v4/blob/815aac0e4f6751a8917e912eec339f1d56cab3ef/research/manager-selection-gaps-20261003/mac-business-r10/FINAL_ACCEPTANCE.json) 对 source=20260930/target=20261002 回看给出 689 条、58/349/250/32，API/UI 与原 owner一致。不能把该回看改成自然盘前结果。10/8 首个读断点是精确主表 StoreError，后续 10/7 与量纲缺口仍在 |

### US 三层不能混称

`us_market_attention.READY` 表示 US 源快照条件通过。`research_attention.us_mapping_diagnostics.ASSESSED_WITH_RELATIONS` 表示原材料/双源/时点关系层确已评估，并由 `VERIFIED_RELATIONS_PASSED_TWO_SOURCE_PIT` 给出成功原因。`us_mapping_research` 则包含单独的 reviewed 回顾卡和按日持久化匹配。任何一个 NOT_RUN 都不能证明另两个字段从未产生成果。

b228 的 `workspace_daily_channels.py:140–169` 将 `HK_CONNECT` 明确绑定到 target universe V2 和既有 focus。`catalystObservationPanel.ts:471–472` 则分别调用每日摘要及带 `us_mapping_research` 的 research renderer。恢复时应验证真实 US 字段与其原 renderer，不把资格通道当 US 映射完成。

## 二、证券主表 / V2 universe / HK02 的原生产与读取位置

原 owner 静态来源为已冻结的 `0fd5eb.../handoff/v4-running-source-20261005/canonical/`。这些函数存在不等于它们已在 10/8 当前 scheduler 中加载。新 b228 只有部分 Mac manager 源码，未附实际 HK child 的完整逐文件身份。

| 环节 | 原源码位置及行为 | 需要对照的日期、root、回执 |
| --- | --- | --- |
| 调度触发 | `contracts/runtime_workloads.json` 中 `research_panel_daily_hk` 的原 owner 为 `v35_dispatcher.research_panel_daily_hk`，原已证自然 slot 为 1720。`executor_registry.py:531` 分派至 HK handler | 10/7、10/8 scheduler 的实际 release、catalog SHA、日历判定、claim/dispatch receipt；不能以 daemon cycle SUCCEEDED 代替 workload运行 |
| 子进程与日期 | `_executor_registry_parts/panel_execution.py:153–232`；208 行传 `--date request.business_date --lane HK`。HK child 有五项 app/manifest/release/module pin，验证后只改变该 workload 的 cwd/env | 实际 `V35_RESEARCH_PANEL_HK_CHILD_*` 五项、传给 child 的原 argv、实际导入文件 SHA；普通 api release 与 HK child 可不同 |
| 写入根 | `_macos_research_panel_daily_parts/hk_capture_gate.py:18–41`：capture 在 `RECEIPT_ROOT/hk_capture/<target>/<run>.json`，`store_root = HK_ASSET_ROOT.parent.parent`；原 `ensure_hk_security_master` 接收 `trade_date=target` | 当次 `HK_ASSET_ROOT` 派生的 store_root 要与 manager 实际消费的 S 对照；缺少当次 root 证据时不能认定是 root错配 |
| membership 提前发布 | 同文件 33–60 行，把同一次两板块 capture 传 `membership_ready_callback`；`ops/ensure_hk_security_master.py:725–753` 以 membership_only 校验并发布 V2；不用第二次 provider 请求 | 当日完整 per-plate capture、acquired_at、capture SHA/run、forward source owner。第二 plate 失败不能发布；行情不足不能拿 quote-only集合冒充资格 |
| V2 publication | `ensure_hk_security_master.py:551–670` 原 helper写 artifact/manifest/receipt/capture/current，全部读回后再记录真实 publication available_at。`domains/manager_research_evidence.py:136–220` 原 reader复建同一合同逐字比对 | `S/universes/<target>/HK_CONNECT_FULL_MARKET.json`；对应 `.authority/<run>/capture.json`、`publication.json`、manifest/receipt/current；不能只补顶层名单或改旧日期 |
| HK02 构建 | `hk_capture_gate.py:190` 原 .day打包；254–273 调现有 `run_hk_0_2_authority`，校验精确日期及面板；285–313 比较同 capture 的 exact-date code set | 本次 packed input identity、updater module和实际 Python、panel+manifest SHA；一份 10/8面板不能证明同次 master/V2后段也成功 |
| 主表发布 | `hk_capture_gate.py:318–327` 再用同 capture/panel_binding 调原 ensure。`ensure_hk_security_master.py:785–835` 验证/复用或发布原 `security_master_rows`；shared `hk_security_master.py:95–175` 写同日期不可变run与日期索引 | `S/assets/hk_security_master/runs/<date>/<run>/{artifact.csv,manifest.json,receipt.json}` 与 `latest.json.entries[date]`；captured_at 在此为发布时点，不回填成每个 plate 请求时钟 |
| 主表读取 | b228 `workspace_plan.py:614–638` 原 witness → shared `load_verified_hk_security_master`；后者按 `entries[trade_date]` 精确取同日，不读最大日代替 | 日期缺失会产生 StoreError。b228 1021–1027 已正确隔离该异常，不是该 consumer 应生成主表的理由 |
| universe读取 | b228 `connect_selection.py:73–140`，只从显式 universe root 和 owner root/SHA调用原 `read_universe_evidence(..., require_v2=True)`，然后再核取得及发布时点 ≤ cutoff | `V4_MANAGER_UNIVERSE_ROOT` 与实际 producer root；D1 capture仅附为 previous_session_capture，不能授予目标日正式资格 |

### 已证的 9/30 原自然生产基线

已读取 [natural_1720_readback.json](https://github.com/lexi2016/v4/blob/d26d34610e7021d9ad1712bc418a32d667b50bd2/research/manager-r9-consumer-r1-20260930/r3_business_fix_20260930/natural_1720_readback.json)。其记录：

- release `20260929-manager-1555-pytdx-r1`，dispatch run `22f8189530d0492698aa697130bce0c6`，结束 `2026-09-30T09:20:08.269649Z`。
- 原 membership 696，日面板有效 689、排除行情7；资格集合不能用689替代。
- capture run `20260930-11854-a344440cbff68a1fa82fee15`；raw SHA `16cebcc6733e6ed7501697ece4c237b9e39d82459af1d0dc1659667493946fa9`。
- panel SHA `151fbe7168efefc769e51920d8c153e92c1d4659a46cc76b100fa7182e5f51ec`。
- 主表 run `49ffde1ebebdc85e4680e701`、artifact SHA `754794679937494dc8dc6cdc8dfbd14dfa4b070ea709f551874e39006aa712dd`、manifest SHA `acb3308410a8601651818b14fb519ff39a019adadc37ac3beec86c8cad5d5eb5`。
- 当时 capture 没有 per-plate 原记录或采集时钟，因此这次自然日面板/master成功本身不证明 V2资格链。后续 #8 R3A 与 HK-only bridge 的修复/部署应保留，但其10/1回执仍明确未验自然17:20。

## 三、10/8 当前断点：可判与不可判

**Issue #29 最新事实**：20:33–20:39只读观察中，manager shared root的 master最新日20260930，另一个明确root最大20260918；缺20261007/08。10/8 HK02 manifest SHA `a9c75b248d264e2ed78532cbfc1004f8de97b8e8f91c587a66b50f5afa020bee`，panel SHA `785212e96f9f088075800f55dfaf09ef83fccdde7c220e24f9f14d8808db5f90`；只新增10/8、parent最大10/2，缺精确10/7。volume unit=NOT_PROVEN；native finality=NOT_ATTESTED_BY_PROVIDER。目标日 universe V2 publication亦缺。

源代码能解释为什么“已有10/8面板，主表仍失败”在机制上可能发生：原 gate在 panel产出后还验证代码集合及绑定，随后才发布主表；如果实际10/8面板由另一个已存在权威修复步骤生成，也不能由面板推出1720完整gate已跑。**这些是待回执区分的可能路径，本报告没有将其中一种宣布为本次根因。**

修复主表后还要继续核精确10/7历史与前5日单位。只补master不能自动让超跌规则可执行；不得用10/2代10/7、用手数猜股数、把未评估计为0。HK证券交易日与Connect日历保持分开；若唯一已证 target-day资格发布是17:20，它不能倒签成当天09:27已可用。是否另有原合法盘前 publication，需实际owner回执说明。

## 四、日常 US 入口差异与最小接续方向

已读取的旧 `840b9538` canonical `plan_owner_dispatch.py` 在 PREOPEN计划分支返回后调用 `service.refresh_us_mapping_research(date, now=now)`。其 DAILY_DELIVERY 区分 canonical SHA `a09d5d...` 与部署 SHA `f4ddb61...`，不能把 canonical当部署字节。

R1固定交付 `66339d...` 的 `plan_owner_dispatch.py:185–202,262–287` 则保留原计划执行并对 US返回 `NOT_ATTEMPTED/NOT_EVALUATED`；原因是这份closure没有独立有界US调度hook，不能让US处理耗尽正式plan的限时窗口。**它没有实现 US 每日owner执行**。b228新service方法存在，不能再报 `US_MAPPING_DAILY_OWNER_UNAVAILABLE` 为静态结论；但缺当前实际dispatch和binding身份，不能从交付静态文件直接推断listener行为。

已经核查的独立入口包括：旧 `840b9538` 包完整 operators 目录及其 `prepare_manager_daily_binding.py`，以及原 `runtime_workloads.json`、US registry handler 和 scheduler/ops 中的原调用点。该 operator 仅准备原 plan-only 绑定，没有独立 US mapping job。原 `us_market_digest` 的 04:15、05:15、21:00、22:00 slot 调用 `ops.us_market_digest`，用原 US 日历写 peripheral capture；`_executor_registry_parts/us_digest.py:14–97` 没有调用 `persist_daily_run` 或 `refresh_us_mapping_research`。因此已找到的四个 US slot 不能当作每日映射产物已经自动保存的证据。这个结论限于已核源码；缺当前 scheduler/owner/binding inventory 时，不扩张为所有版本均无独立入口。

后续最小接续应复用已存在 `refresh_us_mapping_research`、原US读取根和原产物路径。先核真实当前模块/registry/dispatch/version及原9/30报告，再让单一集成owner按原调度生命周期安置有界调用，独立记录其run/日期/cutoff及读回；保留计划原deadline和不覆盖旧run的约束。不要新增一个市场producer、不要恢复旧的无界RPC尾部调用、不要把 phase3 9/25 canary 当该接续已完成。

本报告只定位入口差异，不在未知current依赖上提交US算法或scheduler代码。它也不授权正式调用、采集或服务切换。

## 五、最小本机补证集合

| 缺口 | 按原owner只读取得的最小证据 | 取得后的可执行决定 |
| --- | --- | --- |
| 9/30用户所指三路原成功结果 | 原入口命令/API、execution_kind、run_id、data/target/publication/session日期、结果与回执SHA、当时release；除plan store，还查上述公告、US reviewed/daily及screen原结果路径 | 建立成功基线；旧reader迁移只在合法原件上进行，不用新日结果替代 |
| 10/7、10/8主表/V2未接续 | 当日原1720 claim/dispatch、HK child五pins、argv、capture manifest+rawSHA、panel/ensure/status摘要、实际写root；无需上传原始行情 | 定位首次失败步骤或读写root差异后，限定到原owner的真实断点做最小增量 |
| 10/8 API消费者绑定 | 当前listener release、manager三个root、已加载 service/workspace_plan/connect reader的路径与SHA；单一发布owner状态 | 防止把canonical或旧child复制到新release，保证不回退#28和已验经理修复 |
| US每日owner身份与接续 | 当前 `us_mapping_research.py`、reviewed seed、registry、`plan_owner_dispatch.py`、实际renderer的逐文件SHA/来源；原US slot claim、peripheral receipt与同日daily run摘要 | 有界接通原调用与页面；旧R2 reference仅作对照，不获得覆盖当前版本资格 |
| 10/7价格与成交量证明 | 原HK02/TDX/tdxpy owner已有的精确缺日证据及补采方案；单位/scale/session范围的真实证明 | 缺日恢复由原数据owner执行；未证明单位时保留unknown，原门槛不变 |

## 六、保留已完成修复与报告适用范围

- #22：成功reason文案/九项定向回归及随后R8部署已经完成；不再重做，不把后续StoreError/主表缺口归因该文案。
- #24：[Mac R9最终回执](https://github.com/lexi2016/v4/issues/24#issuecomment-5967029030) 已对原333,005,411字节10/2 run完成只读验证、34项原生测试、部署及GET CURRENT/consumed。没有重复POST或重封历史。它不证明所有后续reader版本兼容。
- #8 R10：真实689条研究决策及对应页面已验，适用scope仅9/30源、10/2现在回看；US84条取得时钟缺口与自然运行未关闭。
- #29 R2：公告同产品33/54/75、日期切换、StoreError隔离、序列化比较修复直接保留。固定计数不是未来硬编码预期。

本子任务 `DIAGNOSED/SOURCE_RECONCILED`；没有新增生产实现或运行测试。`INTEGRATED/DEPLOYED/API_VERIFIED/UI_VERIFIED/BEHAVIOR_VERIFIED/NATURAL_VERIFIED` 均不在本轮新验范围。引用的旧PASS明确保留原作者、日期及适用范围。`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。
