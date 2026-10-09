# R3 原输入接续与 HK 独立重放：Mac owner 执行交接

## 交接状态

本轮已经把原 R1 的三件 HK child 增量按精确前像重放到独立候选，保留现存 namespace；通过实际 API nested consumer 调用点完成 7 项输入行为测试，并完成 4 项 HK 入口/缺口行为和 2 项原 owner 合成发布链测试。最终定向结果为 **13 passed**。原 supplement 套件的 **13 passed / 2 个既有 screen failures**、首次装配的 **11 passed / 2 failed** 及其后续定位日志均保留。没有修改生产 supplement consumer 字节，也没有把 consumer 放进实际 HK02 updater 根。[S4][S5][S6]

这些结果属于 `IMPLEMENTED / TESTED`。实际 Mac 的 `INTEGRATED / DEPLOYED / API / UI / NATURAL` 均为本轮 **NOT_RUN**。真实合法输入、实际加载身份、原自然 dispatch 和两日业务产物仍由原 owner 验收。单个通道的缺口应独立显示；合法独立通道可以沿原 owner 继续，不把未知候选数改成零。

本轮仅处理隔离源码、问题包中的脱敏证据和临时合成数据。没有真实 owner POST、外部采集、真实 plan/state 读写、服务启停、部署或 GitHub 写入。下列 Mac 命令是交接给原 owner 的待执行步骤，不能作为已经运行的回执。所有阶段保留：`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。

## 1. 输入证据与日期合同

### 1.1 本包真正观察到什么

R3 两次 11:00 CST 顺序 GET 的 **plan `date` 均为 `20261009`**。第一份请求是 `date=20261009&selection_date=20261008&announcement_date=20261007&view=auto`；第二份是 `date=20261009&selection_date=20261009&announcement_date=20261008&view=auto`。两者均 HTTP 200、`plan_product=NOT_MATERIALIZED`、`run_id=null`、US `daily_run=NOT_RUN`。不能把它们描述为已经实际读回过 `date=20261008`，也不能从 HTTP 200 推断保存成功。[S1][S2]

当前 scheduler supplied binding 为 enabled plan-only，SHA 为 `c0fbff52449eb5dbf5c1655f17cf08915bea1214f9499cc8a4df1176d9625951`；API supplied binding 是 disabled 的旧 C1 文件，SHA 为 `f3b7cbfa1709b2b27816d294e599cb1ae82ff918ba41ec148644f1a1751f5fd6`。若该调度请求实际到达此 API，静态首个拒绝门为 `PLAN_OWNER_BINDING_SHA_MISMATCH`。本包没有该时段实际 dispatch receipt，具体事件仍是 `CANNOT_CONFIRM`；`hook_executed=false` 的 activation canary 不证明 10/9 自然 owner 已运行。[S1][S2]

| 目标产品 | 应核原输入日期 | 成功后读回合同 | 缺输入时 |
| --- | --- | --- | --- |
| 10/8 事后计划 | announcement publication 10/7；US completed session 10/7；HK 按原交易日历及该目标所需精确资格日 | 原 owner 实际保存后，显式 `view=dynamic` 核同 target/run/product SHA/source/cutoff | 保留原原因与真实状态；不制造 run/SHA/股票 |
| 10/9 当日计划 | announcement publication 10/8；US completed session 10/8；HK 精确 D-1、Top100、PIT 和证券日历边界 | 当日产物已保存时，普通 `view=auto` 应读回同 run/product SHA/输入身份，不能悄悄重算 | 通道分别保留 `NOT_RUN / NOT_IMPORTED / CANNOT_CONFIRM` |
| 合法完整输入但筛选为零 | 所有被实际评估通道均有合法来源与日期证明 | 可保存可追溯空结果，包含 owner、run、SHA、cutoff 和筛选理由 | 不等同于未知输入、未评估或单位未证明 |

若真正执行已晚于目标日，保留实际执行和 availability 时间，不倒签成盘前。普通 auto 原历史资格不因事后补算而放宽；不存在合格历史 run 时，`HISTORY_QUALIFIED_SAVED_PLAN_MISSING` 与“事后 dynamic 产品已保存”可以同时成立。[S1]

### 1.2 证据来源等级

| 来源 | 可以证明 | 不能证明 |
| --- | --- | --- |
| R3 source manifest / source_snapshot / two GET projection | 所提供观测时刻的源码前像、根与 API 投影 | 接手时刻仍是同根；某 Python 模块已经加载；owner 自然执行因果 |
| R2 Mac input audit | 原 US 04:15 receipt；10/8 公告输出、import 与身份边界 | 10/9 公告产品；原 06:30 recurring task 当前 enabled/timezone |
| R1 after 源码与固定测试 | 可重放增量及原断言合同 | 生产部署与真实单位、PIT、自然运行 |
| 本轮新测试与 HK_REPLAY_RECEIPT | 本轮精确候选字节、实际测试导入路径及合成行为 | Mac 完整依赖闭包、实际 updater producer 或两日业务成功 |
| 旧 Chat candidate / candidate_origin | 本轮两份 test-only 原依赖的固定字节来源 | 当前 Mac before、部署身份或现场输入 |

## 2. 最小实施边界与可复用修复

### 2.1 原 owner 续接分工

| 问题层 | 本轮最小处理 | 输入合法后由谁接续 | 仍缺什么 |
| --- | --- | --- | --- |
| 调度 binding 与 API owner 根不一致 | 主包 R3 双 root 身份合同与失败原因；复用原 scheduler/worker/service | 原共享 owner 配置并验证同一 binding；原每日 owner 调用原 mapping 与 plan | 实际 canary、配置 pin、加载身份和自然 dispatch |
| API 经理路径仍是 R1 before | 对最新受保护 API 做有限 R1/R2 累计增量；不能重复叠加 cumulative 和 R3-only | 原 `ManagerResearchJobService` | 真实输入与真实保存/readback |
| US source 已成功而 daily mapping 未运行 | 复用原 `refresh_us_mapping_research` 接续与原 plan-only 分支，不新增 collector | 原 mapping owner → 原 plan owner | 同 target 的 mapping run/输入身份/产品消费证据 |
| 公告已存在合法 Reader/Reviewer 输出 | 复用原 register/import/readback；不新增审查 producer 或替代任务 | 原 announcement automation/Reader/Reviewer/import owner → plan owner | 精确目标输入；当前原任务配置、06:30 自然记录 |
| HK child 入口未连上既有 gate | 按下表重放原 R1 三件增量，保留 namespace | 同次 capture → membership → panel → master → final readback | 真实精确日期输入、各原 owner 的完整依赖与运行证据 |
| API nested supplement 行为未独立测试的 P2 | 生产 consumer 不变；新增从真实 workspace_plan callsite 进入的测试 | 原 API reader 消费原 owner 的确切 sidecar | Mac 同装配行为复验；实际 producer、真实 sidecar、单位与六日尺度证据 |
| HK02 producer / 六日量纲证明缺口 | 本轮不通过复制 consumer、声明单位或调低门槛补齐 | 原 HK02/数据合同 owner 先核原职责、版本和合法证明 | 真实 producer 能力、原生量纲、全六日同源尺度、finality；缺口保留 |

R1/R2 的 independent PASS 是已有隔离成果，并不意味着现役安装了这些字节。源采集成功、原 US raw attention、daily mapping run、plan product 和逐股入选理由是不同层，验收必须逐层关联。[S1][S3][S4]

### 2.2 本轮 HK child 三件重放

来源：原 R1 commit `008649895054cb24f1d1c3df37e215d307615db3`；R3 HK child 三个 before 均精确匹配。独立候选根为本包构建环境中的 `hk_child_candidate`，不是主 API 测试 candidate。全部 before 和 after 已先核 SHA 后复制；主 candidate 的同名生产文件未被本任务改写。[S4]

| HK child 相对路径 | R3 / R1 before SHA-256 | 重放 R1 after SHA-256 |
| --- | --- | --- |
| `ops/macos_research_panel_daily.py` | `07aa9770c6ae0bb0cfd012e57843a37fedda6724a57cd52d7c339d854fc6609b` | `1963990fcde99b2681c837b8b66ea12f1ab066aba47729af5d0900073bc79ef3` |
| `ops/_macos_research_panel_daily_parts/hk_capture_gate.py` | `d3db5b9644bbf2fb1f4e245717907862ebe1cee2d0f650a8d45d732fd4a71940` | `d07be30a40c35aee9d710fcdcc7ae66b031488cc4c5e7029824e3c76ed3fd71c` |
| `ops/ensure_hk_security_master.py` | `6c341a33c0283b023219c46cc2a1c6aaca49cf4b5dcb88aa2fb5527a13145601` | `495ced4f0f06f170606ee576e035dafc99b540cd9fad0a28f2f2a36e5989ddb9` |

必须保留 `ops/_macos_research_panel_daily_parts/_namespace.py` 的现存 SHA：

`45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1`

其 `read_global` 函数 AST 与 R1 namespace after 一致；差异是说明文字、空白/引号，不需要为了旧 R1 “null before” 条件覆盖它。本轮测试已实际调用 globals 查找与 builtins 后备，并核 gate 使用该函数。[S4][S5]

### 2.3 API consumer 与实际 HK02 updater 的准确映射

实际 API 调用点为 `v4/manager_research/workspace_plan.py::_read_hk02_daily_supplement_witness`，延迟导入 **`v3_shared_data.shared_data.hk_daily_supplement`**。它只在确有待修复 codes 且有 cutoff 时读取；本轮保留该文件 R2 after SHA：

`f71d6bb8bc0d55a0205d9734562c37d249654e3e39ccc85e18dd6398aa3c3862`

它在 R3 actual API 的 before 为 `5528a6b44bfb5b79265732b85beb1fb89860355b48a852da07264fb34231c79c`。路径属于 API nested package，不能套用 R1 文档的泛称 `hk_upstream` 把它发布到另一个 updater。[S3][S5]

实际 supplied HK02 根是 `20260923-hk02-owner-rebase-r2/app/upstreams/v3_shared_data`。脚本 `scripts/update_hk_0_2_panel.py` SHA 为 `45d31c1e6608d1a9af163ffd56ea111d5caeb40000c58cd140534cf81859634e`，自行将 `parents[1]` 设为 package root，仅导入 `shared_data.hk_0_2` 与 store。其 `shared_data/hk_0_2.py` SHA 为 `45a5091cb26800b7ccf8d7c3c75b680e951d492ac8ceb5f30b80a1ff9a6eebac`，store SHA 为 `87042083dad178442c75386e59ae4b2fd9bab0a3c92b5c3a090ddb90e6b52a16`。该脚本没有 `--daily-supplement` 参数，实际映射调查未发现它导入 supplement。[S1][S3]

R1 gate 的 `_run_daily_supplement` 在该实际 package 缺少模块时返回 `CANNOT_CONFIRM / HK_DAILY_SUPPLEMENT_OWNER_UNAVAILABLE`，而不是运行子进程。新测试保留了这条行为。primary HK publication chain 的合法阶段可以各自成功；supplement 不可用不能被写成 supplement READY，更不能外推 screen 或整个经理业务已完成。[S5]

## 3. 共享发布、双根 binding 与 Issue32 保留

本节与主 `HOST_HANDOFF.md` 一起执行。使用唯一原 api_platform/shared 发布 owner，继续 Issue30 的 persistent POSIX release lock、active-base CAS、精确 source inventory、module ownership 和有限 delta。接手时在锁内重读最新 API、worker、scheduler、HK child 根、plist/release manifest、入口和实际加载模块 SHA；10/9 问题包快照只是 supplied baseline，不能覆盖后来并行成果。[S1][S7]

当前原 policy 的 manager 前缀只覆盖其既有三类目录，不能授权以下五条路径。独立 `release_policy_review/` proposal 需由原共享 owner **先审查采用**，然后使用采用后的 `POLICY_SHA256` 生成 manager delta receipt。五条新增 shared 值为 `["manager"]`；api_platform 是原发布服务 owner，不据此增加它的模块权限。不得仅在调用方 `shared_paths` 中填名字就绕过旧 policy。[S7]

| 需先采用的 exact shared path | 原因 |
| --- | --- |
| `infrastructure/_research_peripheral_store_parts/_namespace.py` | R1 shared namespace 闭包 |
| `infrastructure/scheduling/manager_announcement_supervisor.py` | 原 worker/supervisor 身份与 daily 合同 |
| `ops/render_manager_announcement_binding.py` | 原 binding renderer |
| `ops/run_manager_announcement_cycle.py` | 原 worker cycle |
| `v3_shared_data/shared_data/hk_daily_supplement.py` | 已核实际 API nested consumer |

HK child 和真正 HK02 updater 是独立 source profile/owner，不能塞进这五条 API ownership 内。旧政策 receipt 的身份保持原样，不能重写其签名或 SHA 来冒充新政策。

Issue32 supplied parent 为 `66bb05a2e12976775ccb997191ce943bae8cc9a5`，必须保留三件保护文件；若最新 owner 已合法变更这些文件，以其最新受保护累计基线重新审查有限 delta，不回退到表中旧字节。[S1]

| 路径 | R3 supplied SHA-256 |
| --- | --- |
| `apps/api/v35_api/app.py` | `5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5` |
| `apps/api/v35_api/preselection_router.py` | `718d54a6c6aa8cde2871ce4dc41cbc1d825f199a57b605e4f5ec70d8c4fe19ae` |
| `apps/api/v35_api/preselection_service.py` | `cbed3aa4797889051eb7bebe4b8e3240b568d72b4dfb5c20f65e914d39e48044` |

采用主包双根 binding：顶层 `app_root/files` 对应实际 manager worker；显式 `plan_owner.app_root/files` 对应真实 8873 API。scheduler 与 API 固定同一份原始 JSON 字节/SHA；worker root 与 API root 可以不同，不能为让它们相等而改写 release 身份。新 canary 要证明真实 API owner execution root 与 inventory，保留原 Python 3.14、enabled、source inventory 和 canary 门禁。所有配置只由原 owner 按主交接渲染到新路径并切换，不能使用 synthetic canary、空 marker 或 shim。[S7]

## 4. US、公告、HK 的原输入续接

### 4.1 US：source receipt 后仍须 mapping owner

R2 Mac audit 已记录 `com.lexi.v4.us-market-digest` 原 10/8、10/9 04:15 自然 `LIVE / SUCCEEDED / dry_run=false`，分别关联 10/7、10/8 US `POST_CLOSE` session。原 runner SHA 为 `16f7895072a66b8a7e6ed0c792f74069101426cfa1194df3bd89e63d95f4d948`；source receipt/payload SHA 和 API reader data root 的关系已在原审计中核对。R3 11:00 daily mapping 仍是 NOT_RUN，因此 source 成功不足以宣布映射或入选完成。[S2][S3]

原 daily 分支已在 MORNING/SAME_DAY_CATCHUP 的 plan owner 前调用原 mapping refresh，保留有界 US 准备预算和独立 plan 预算。当前代码已有这条路径，不需要新采集器、第二 US data root 或启用重复 V35 source workload。Mac 先核原 source/data root 与实际 API store/root 一致，再核实际 mapping attempt、run、target/source session 和 plan consumed 身份。后续失败 attempt 不覆盖之前已保存成功产品。[S7][S8]

跨周按原 NATURAL_DAY 与市场日历读 source：例如 10/12 target 所需 10/9 US completed session 要核原周六 10/10 04:15 的自然 POST_CLOSE receipt，不能用 PRE_OPEN lane 替代。该验收必须用本机原日历版本与真实 receipt，不能用测试日历或人工今天采集倒签。

### 4.2 公告：已有 CLI 消费外部审查，不发起 Reader/Reviewer

R2 audit 的 10/8 target / 10/7 publication 证据 run 为 `3f9d37a643060b57992167f3df05d987`，关联 parent task `01a11654-a832-70c1-b6ba-036c79e146e8`。该次 Reader/Reviewer 613 条来源绑定记录与决定、08:09 CST review、08:55:47 CST import availability 均保留。capture 状态仍为 `PARTIAL_BODY_MATERIAL_CAPTURE_WITH_TERMINAL_GAPS`，handoff 为 `OUTPUT_BOUND`，external identity 为 `DECLARED`，不构成平台身份认证。不能用这组 10/8 输出填成 10/9 产品。[S3]

当前原 06:30 recurring task 的 ID、enabled、timezone 与重试归属仍待原 automation owner 只读核回。原审计没有找到目标启用定义；历史精确 `automation-3/automation.toml` 不存在，同 ID 卡片只返回渲染结果，不能当作配置证据。没有真实外部执行器合同时，保留 `ANNOUNCEMENT_ORIGINAL_HEARTBEAT_EXECUTOR_UNAVAILABLE`；不另建任务，不制造第二 Reader/Reviewer adapter。[S3]

已有 `ops/run_manager_daily_announcement.py` 支持 capture/resume、prepare、register-handoff、import、readback，能验证实际外部输出字节、不同身份、目标/publication 与源 SHA。它不负责调用 Reader 或 Reviewer。本轮只读取该现有源码，不把它视为 R3 新逻辑或当前 Mac 模块加载证据。存在合法审查产物时，原 CLI 可以接续注册、导入及精确 readback；不存在时，先由原 automation owner 恢复原调用合同，不能写统一决定或填假身份。[S3][S8]

### 4.3 HK：同次发布链、真实六日证据与 PIT

R1 已有 gate 固定次序：`CAPTURE → MEMBERSHIP_PUBLICATION → PANEL_PACK → PANEL_AUTHORITY → PANEL_CAPTURE_BINDING → SECURITY_MASTER_PUBLICATION → FINAL_READBACK`。入口重放后实际走该链；旧 panel-only receipt 不足以认定完整 HK READY。历史目标必须存在该日 exact immutable capture；缺失时在 live collector 前停下。损坏 latest 不等于缓存未命中，不得重新抓今天来补旧日。第二日 latest 推进后，第一日 immutable chain 应仍能验证；真实旧原件损坏仍拒绝。[S4][S5]

超跌还依赖精确 security master、代码/流通市值/上市与资格边界、原面板和所需六日量价来源。R3 `HK_UNIVERSE_V2_ARTIFACT_MISSING` 不能用 planning pool READY、全市场列表或今天 membership 绕过，必须保留 D-1 Top100/PIT/证券日历与 Connect 资格区分。10:53 的 `SCREEN_SECURITY_MASTER_READ_FAILED:StoreError` 是用户现场观察；11:00 投影只再次证明 screen CANNOT_CONFIRM，当前 exact error/cause 没有重新确认。[S1][S2]

实际 HK02 `hk_0_2.py` 已包含 `native_observation` 与 `manifest_prepared_at`，不重复套用旧 canonical 的 timestamp 修复。native observation v1 只证明 NEW_INCREMENT_ONLY 的原始读入与 `scale_applied=1` 字节变换；volume/amount 单位仍 NOT_PROVEN，provider session finality 为 NOT_ATTESTED_BY_PROVIDER，旧面板历史尺度未获证明。旧 immutable manifest 不应补写今天 metadata。[S1][S8]

当前 `_screen_panel_volume_evidence` 与 `_screen_supplement_volume_evidence` 明确保留全六日单位/尺度 NOT_PROVEN。六根数值 bar、额外塞入 unit 字段、lot size、amount/price 比值或手动乘除均不能制造合法证明。原数据 owner 若要提供新的可消费 attestation，需要独立版本合同和来源验证；这不是本轮通过输入补填即可认定完成的范围。未知量纲时不能把“筛选为零”保存成合法零入选。[S5][S8]

## 5. Mac 源码门禁与离线复验命令

### 5.1 分根核验

变量都由原 owner 根据当时实际根填写。`manager_r3_package` 是最终交付包；`manager_r3_original_package` 是原 R3 问题包的 `package/` 目录。验收输出目录在业务源码与数据根之外。任何 path/SHA 不符先停止该角色集成，重新获取最新合法前像并形成小增量，不复制旧整树覆盖。

```bash
: "${manager_r3_package:?set final delivery root}"
: "${manager_r3_python:?set original verified Python}"
: "${manager_r3_api_candidate:?set isolated current API candidate}"
: "${manager_r3_hk_child_candidate:?set isolated actual HK child candidate}"
: "${manager_r3_evidence_root:?set local review evidence directory}"

"$manager_r3_python" "$manager_r3_package/tools/verify_delivery.py" \
  --package "$manager_r3_package"

"$manager_r3_python" "$manager_r3_package/tools/verify_delivery.py" \
  --package "$manager_r3_package" --profile api_current \
  --source-root "$manager_r3_api_candidate" --against before

"$manager_r3_python" "$manager_r3_package/tools/verify_delivery.py" \
  --package "$manager_r3_package" --profile hk_child \
  --source-root "$manager_r3_hk_child_candidate" --against before

git -C "$manager_r3_hk_child_candidate" apply --check \
  "$manager_r3_package/runtime/hk_child.patch"
```

上面只核验。通过后仍由原共享 owner/该角色 owner 的 delta builder 应用有限补丁；不是本包自行部署。对 API/worker/HK/web 分别选主包 profile。集成后的相同根重复 `--against after` 并复核保护文件与新源 inventory。HK namespace 必须按 preserve 条目核，不能执行旧 R1 新增文件的 null-before 操作。[S7]

### 5.2 定向测试可移植装配

本轮 Python 为 3.14.6，pytest 为 9.1.1，禁止 bytecode/cache provider；测试输入全部在 pytest tmp_path。最终源码测试文件 SHA 见 `HK_TEST_EVIDENCE.json`。测试本身没有引用另一 scratch 的绝对路径，当前解释器绝对路径只是本轮执行证据，不能照抄成 Mac Python。

Mac 使用**独立测试 app**，由已核完整原源码复制形成。将下列三份未经修改的测试一起放到该 app 的 `tests/`：新 `test_manager_r3_hk_continuation.py`、原 `test_hk_daily_publication_chain.py` 和原 `test_hk_daily_supplement_r4.py`。原 chain helper 用自身 `__file__.parents[1]/upstreams/v3_shared_data` 定位测试 updater，所以仅从包外增加 PYTHONPATH 不足以复现完整装配。该 app 需要真实已有 dependencies，不允许缺什么就造空模块。

准备的 HK child code root 是三件 after 加保留 namespace。新测试把这四份原字节复制到单个 pytest tmp `child-code/`，并从测试 app 复制真实 `stage_center/hk_universe_preflight.py` 到物理相邻路径，保留 ensure 原 loader，SHA 为 `9d3d2c2d5ff3bd1c7713a9485e88000ae882f58b0a457b734656094606ba2941`。这只构造离线依赖布局，不改主 candidate、HK candidate 或真实数据根。

原 11 pass / 2 fail 先因四文件 HK 快照缺少上述物理相邻纯合同而失败；补齐后明确定位到原 `scripts.live_acquisition.contracts` 导入缺失。最终仅提供两份已有原源码，独立放入交付的 `reference/test_dependencies/`，按明确路径加载，无 dummy 实现或 validator 替换：

| Test-only 依赖相对路径 | SHA-256 | 字节数 |
| --- | --- | --- |
| `upstreams/v3_shared_data/scripts/live_acquisition/contracts.py` | `ea20a940814915ec1d744b7df23ea48e4287e4baa9716889a648c9210ea3b34e` | 3162 |
| `upstreams/v3_shared_data/scripts/live_acquisition/orchestrator.py` | `a95fa35e17b6090f3bb196ee6bb75a456d9fb918ce64dd4cd78d7d6005d4f46d` | 8666 |

来源 head 是 `3f2aa6c92d87da098d33b5349698e55d337fd165` 的旧候选原清单，两文件在 `r1_inventory_before_injections` 与 `candidate_inventory_after_injections` 均同 SHA。原 `candidate_origin.json` SHA 为 `df62c2c7e7477cd9660acad8dcb05ad1c256228040bb62a6c625f906f21f5e52`；精确出处保存在随文件的 `DEPENDENCY_ORIGIN.json`。它们是旧源码引用，本轮只验证字节/导入，不证明当前 Mac 有相同依赖，也不应部署到 HK02 来改变 producer 能力。[S5][S6]

```bash
: "${manager_r3_test_app:?set complete isolated test app}"
: "${manager_r3_original_package:?set original R3 package source snapshot}"

cd "$manager_r3_test_app"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$manager_r3_test_app:$manager_r3_test_app/upstreams:$manager_r3_test_app/tests"
export V4_R3_HK_CHILD_ROOT="$manager_r3_hk_child_candidate"
export V4_R3_INPUT_PACKAGE_ROOT="$manager_r3_original_package"
export V4_R3_OWNER_TEST_DEPENDENCY_ROOT="$manager_r3_package/reference/test_dependencies"

"$manager_r3_python" -m pytest -q -s -p no:cacheprovider \
  tests/test_manager_r3_hk_continuation.py

"$manager_r3_python" -m pytest -q -s -p no:cacheprovider \
  tests/test_hk_daily_supplement_r4.py
```

第二条保留两项既有失败；不能删断言、加 xfail 或改变单位/同日身份以追求全绿。Mac 原始输出、exit code、源码 SHA、实际 `__file__` 和依赖根都写本地回执。若装配不同而无法运行，写 `CANNOT_CONFIRM`，不引用 Chat 13 PASS 代替 Mac 结果。

### 5.3 本轮冻结结果和 P2 剩余边界

| 范围 | 本轮实测结果 | 覆盖的行为 |
| --- | --- | --- |
| 实际 API nested consumer | 7 PASS | 真实 callsite 读 READY/PENDING；panel/master/universe 身份拒绝；cutoff、六日集合、immutable SHA 拒绝；缺 exact pointer 不读旧日；读取不写数据；单位仍 NOT_PROVEN |
| 独立 HK child 入口和缺口 | 4 PASS | 保留 namespace/builtins；panel-only 不 READY；历史输入缺失停采；latest 跨日推进后旧链可读；实际 updater 无 supplement owner 时不运行 subprocess（部分断言同一用例） |
| 原 owner 合成 roundtrip | 2 PASS | 原 capture/panel/master 发布断言、同次 receipt、幂等 reuse、损坏拒绝；最终 readback 失败不 promote latest |
| 原 supplement suite | 13 PASS / 2 FAIL | 两个原 screen 候选数断言分别仍为 0 对预期 3、0 对预期 1；不作本轮回归修复 |
| 真正 HK02 producer、真实六日单位/PIT与现场全链 | NOT_RUN / CANNOT_CONFIRM | 需要原输入/owner 合同和本机复验 |

两项保留原失败名为 `test_screen_uses_master_universe_sidecar_volume_and_missing_only_price_overlay` 与 `test_complete_panel_history_skips_sidecar_and_preserves_canonical_baseline`。完整原测试文件未修改。

合成 roundtrip 仍沿原测试使用 Fake Futu、合成 panel seed 和返回 PARTIAL_WITH_PENDING 的 supplement subprocess 替身；用它证明入口/发布/回读合同，不证明实际 updater 有 supplement 模块，也不证明 unit 或最终超跌入选。原实际 updater unavailable 用例另行验证，不与合成成功混为一项。

日志索引为 `HK_TEST_EVIDENCE.json`；保留文件为 `hk_validation/initial_scoped.log`、`isolated_contract_still_missing_imports.log`、`original_supplement.log` 与 `final_scoped.log`。最终 `13 passed in 2.20s` 日志 SHA 是 `aaab8f47ba0f181b9fcaf846592b61a36162da296be30687687ac76881f9e25a`。P2 的“实际 API consumer 没有行为测试”在 Chat 定向装配内已经补齐；Mac 独立复验和真实 source/producer 端的缺口仍分别待验，不把 P2 扩写成已恢复每日业务。[S5]

## 6. 由原 owner 执行的合法输入续接命令

以下命令只在前述源码、ownership、binding、真实输入和相应运行授权已经满足后执行。本轮没有执行。环境变量绑定实际 owner 根/状态路径，输出到本机 evidence 目录，完整研究材料和 plan/state 不上传。

### 6.1 公告已有合法输入时

先由原任务 owner 提供确切 target/publication、evidence run、catalog/body、原 Reader 输出、不同身份 Reviewer 输出、原 parent task/身份与回执。需要真实新 capture 时，恢复原任务链，而不是在这里自动补抓。存在 exact 已保存 capture、只需原失败阶段续跑时，可由原 owner 使用已有 resume 合同；该命令会执行原材料采集/本机写入，必须留真实执行时间：

```bash
: "${manager_r3_announcement_evidence_run:?set exact original evidence run}"
: "${manager_r3_announcement_target:?set target YYYYMMDD}"
: "${manager_r3_announcement_publication:?set publication YYYYMMDD}"
: "${manager_r3_state_root:?set original research state root}"

cd "$manager_r3_api_candidate"
PYTHONPATH="$manager_r3_api_candidate:$manager_r3_api_candidate/upstreams" \
  "$manager_r3_python" -m ops.run_manager_daily_announcement capture \
  --target-date "$manager_r3_announcement_target" \
  --publication-date "$manager_r3_announcement_publication" \
  --api-base http://127.0.0.1:8873 \
  --research-state-root "$manager_r3_state_root" \
  --resume-evidence-run-id "$manager_r3_announcement_evidence_run"
```

已有完整合法 external 输出则不需要为导入重做 capture。原 CLI 的 `prepare` 先验证字节/日期，`register-handoff` 再绑定已有输出；下列 identity 必须来自原已核审查回执，不可用示例值填空：

```bash
PYTHONPATH="$manager_r3_api_candidate:$manager_r3_api_candidate/upstreams" \
  "$manager_r3_python" -m ops.run_manager_daily_announcement prepare \
  --target-date "$manager_r3_announcement_target" \
  --publication-date "$manager_r3_announcement_publication" \
  --catalog-read "$manager_r3_catalog_read" \
  --semantic-catalog "$manager_r3_reader_output" \
  --body-corpus "$manager_r3_body_corpus" \
  --body-capture-evidence-root "$manager_r3_body_evidence_root"

PYTHONPATH="$manager_r3_api_candidate:$manager_r3_api_candidate/upstreams" \
  "$manager_r3_python" -m ops.run_manager_daily_announcement register-handoff \
  --evidence-run-id "$manager_r3_announcement_evidence_run" \
  --research-state-root "$manager_r3_state_root" \
  --target-date "$manager_r3_announcement_target" \
  --publication-date "$manager_r3_announcement_publication" \
  --semantic-catalog "$manager_r3_reader_output" \
  --reviewer-output "$manager_r3_reviewer_output" \
  --decisions "$manager_r3_decisions" \
  --parent-task-id "$manager_r3_parent_task_id" \
  --reader-identity "$manager_r3_reader_identity" \
  --reviewer-identity "$manager_r3_reviewer_identity"

PYTHONPATH="$manager_r3_api_candidate:$manager_r3_api_candidate/upstreams" \
  "$manager_r3_python" -m ops.run_manager_daily_announcement import \
  --evidence-run-id "$manager_r3_announcement_evidence_run" \
  --research-state-root "$manager_r3_state_root" --api-base http://127.0.0.1:8873

PYTHONPATH="$manager_r3_api_candidate:$manager_r3_api_candidate/upstreams" \
  "$manager_r3_python" -m ops.run_manager_daily_announcement readback \
  --target-date "$manager_r3_announcement_target" \
  --publication-date "$manager_r3_announcement_publication" \
  --api-base http://127.0.0.1:8873
```

`--decisions` 只在原输出合同确有该独立文件时提供；否则按原 CLI 合同省略，不制造文件。每一步非零、source SHA/date mismatch、未验证 Reader/Reviewer 或缺 terminal capture 时停止该通道；保留 PARTIAL/terminal gaps 与 DECLARED 身份边界。import 成功还要核 readback 的 owner receipt、product SHA 与被 plan 消费身份。

### 6.2 HK 原 entry：有合法当日/精确历史输入时

绑定实际 child、完整原 dependency root、实际 updater 和其独立 package。历史 target 没有该日 exact capture 时不要调用 live collector；保留 `HK_HISTORICAL_MEMBERSHIP_CAPTURE_UNAVAILABLE`。当前包的四文件 HK 片段不是完整执行根，不能以测试装配当作正式发布 app。

```bash
: "${manager_r3_hk_child_root:?set verified actual child app}"
: "${manager_r3_hk_dependency_root:?set verified original dependency app}"
: "${manager_r3_hk_package_root:?set actual updater parents[1]}"
: "${manager_r3_hk_python:?set original verified HK Python}"
: "${manager_r3_hk_source_date:?set exact source target YYYYMMDD}"
: "${manager_r3_hk_receipt_root:?set original receipt root}"
: "${manager_r3_hk_updater:?set original updater script}"
: "${manager_r3_hk_tdx_root:?set original TDX root}"
: "${manager_r3_hk_asset_root:?set original HK02 assets root}"

PYTHONPATH="$manager_r3_hk_child_root:$manager_r3_hk_dependency_root:$manager_r3_hk_package_root" \
  "$manager_r3_hk_python" "$manager_r3_hk_child_root/ops/macos_research_panel_daily.py" \
  --date "$manager_r3_hk_source_date" --lane HK \
  --receipt-root "$manager_r3_hk_receipt_root" \
  --hk-tdx-root "$manager_r3_hk_tdx_root" \
  --hk-updater-script "$manager_r3_hk_updater" \
  --hk-python-executable "$manager_r3_hk_python" \
  --hk-asset-root "$manager_r3_hk_asset_root"
```

核 capture run/SHA、membership revision/日期、panel manifest/capture binding、master run/artifact SHA、最终 readback/terminal/pointer；不要仅核 panel 更新或进程 exit 0。真实 HK02 缺 supplement owner 时保留独立 unavailable，不把测试 fixture producer复制过去。security master/资格/六日单位或 finality 缺口仍由原数据 owner 核，不能用已有 planning pool 或旧日 master 填空。

### 6.3 原 US mapping 与 plan owner、两日期 readback

在合法输入和 binding gate 满足后，由原 owner 对选定 target 一次接续。下面给出 10/8 事后路径；两个 POST 不生产公告外部审查，也不执行 HK capture，不能拿它们代替源输入恢复。

```bash
curl --fail-with-body --silent --show-error --max-time 15 \
  -X POST -H 'Origin: http://127.0.0.1:8873' \
  'http://127.0.0.1:8873/api/v4/manager/research/workspace/us-mapping/refresh?date=20261008' \
  -o "$manager_r3_evidence_root/20261008-us-retrospective-response.json"

curl --fail-with-body --silent --show-error --max-time 45 \
  -X POST -H 'Origin: http://127.0.0.1:8873' \
  'http://127.0.0.1:8873/api/v4/manager/research/workspace/refresh?date=20261008' \
  -o "$manager_r3_evidence_root/20261008-plan-retrospective-response.json"

curl --fail-with-body --silent --show-error --max-time 40 \
  'http://127.0.0.1:8873/api/v4/manager/research/workspace?date=20261008&selection_date=20261008&announcement_date=20261007&view=dynamic' \
  -o "$manager_r3_evidence_root/20261008-dynamic-readback.json"

curl --fail-with-body --silent --show-error --max-time 40 \
  'http://127.0.0.1:8873/api/v4/manager/research/workspace?date=20261009&selection_date=20261009&announcement_date=20261008&view=auto' \
  -o "$manager_r3_evidence_root/20261009-auto-readback.json"
```

10/9 需要 owner 执行时先检查原 dispatch/attempt 是否已经开始或完成，再按原同 target 路径恢复；不要无条件双重 POST。`--max-time` 只限制客户端等待，不取消已经运行的 owner。任何超时、409、响应无结果时，先由原 owner 只读核 dispatch/run/pointer/immutable attempt，区分未触发、执行中、已保存未返回、gate 拒绝、输入缺失和 owner 失败，再使用原恢复合同；不可立即重试制造重复计划。

成功检查必须关联同 target、input source/date/SHA/availability、cutoff、owner、run_id、product SHA、同 run attempt 和逐股原理由。source lane 成功不能变成 daily mapping 成功，合法 PARTIAL 产品不能隐去坏通道，合法空结果不能代替未知输入。

### 6.4 普通页与连续自然验收

10/8 普通页用现有“读取口径”选择“现在回看（可能含后续消息）”，确认真实请求 `view=dynamic`，并另存 auto 原历史资格结果。10/9 已保存当日计划在普通 auto 刷新、重开链接后仍应同 run/SHA/输入身份；改变 plan/selection/publication 或失败响应时旧股即时清除，逐股理由只来自对应合法通道。

正式完成需要至少两个连续适用 HK 交易日的原自然链：原 scheduler dispatch/slot → 各原 source receipt → mapping/import/screen → 原 plan owner → immutable product → API → 普通页。记录真实 scheduled/start/finish、release/module SHA 和每个输入 availability。次日推进 latest 后，旧日 exact chain/旧 run 仍可读，损坏仍拒绝。手动补算、health 200、daemon 存活和 fixture PASS 均不计自然日；未齐备前保留 `NATURAL_SLOT_UNVERIFIED`。[S1][S7]

## 7. 必须停止的条件与回退

| 触发条件 | 停止范围与保留结果 |
| --- | --- |
| profile before/after、manifest、namespace preserve 或 protected SHA 不符 | 停止该角色补丁/集成，获取最新 owner 前像；不回退并行 Issue32 |
| 五条 exact shared ownership 未被原 owner 采用 | 停止 API shared delta 发布；不绕过旧 policy |
| root/binding SHA/enabled/Python/inventory/canary 不符 | 停止原 owner 调用，保留具体 gate 原因与真实 dispatch outcome |
| 原公告 task/executor/真实 Reader/Reviewer/date/source 不齐 | 停止公告依赖动作，保持原具体缺口；其他合法通道独立继续 |
| 历史 HK exact capture 缺失或 immutable 原件损坏 | 停止该日期采集/发布，不能用今天或旧 fallback 修补 |
| HK V2/master/PIT/六日量纲未证或实际 supplement owner 缺失 | 保留各自 CANNOT_CONFIRM/NOT_PROVEN/unavailable；不制造零入选或单位 |
| API HTTP 200 但 NOT_MATERIALIZED/run null | 未保存，继续按原诊断定位，不宣布业务成功 |
| client timeout/409/已存在 in-flight attempt | 停止立即重 POST；查原 immutable 结果与恢复状态 |
| 新测试 Mac 装配依赖/文件 pin 不符 | 保留本机失败与 CANNOT_CONFIRM，不能借 Chat PASS 覆盖 |
| 两个原 screen 断言仍失败 | 保留 P2 既有失败边界，不调整硬门槛追求全绿 |

未部署候选可保留或弃用，无 live 回退动作。部署后的回退只由原共享 owner 持原锁撤销本次有限 delta，成套保留 API/worker/HK release、binding/pins 身份和 Issue32 功能。不删除或改写真实历史 run、owner attempts、source manifest 或 immutable artifacts；不能用回滚代码倒签来源。Stage、BUY、Vibe 8910、原 US source scheduler 与公告任务不因本包回退而变更。

## 来源与回执索引

包内链接采用交付目录的相对路径；原始问题包和旧交付源码采用固定 commit 链接。引用旧源不改变其来源等级，也不代表当前 Mac 已部署。

- [S1] [R3 CHAT_TASK.md](https://github.com/lexi2016/v4/blob/b98d85c95d19780e2900dce7de9372328e67acf6/handoff/manager-daily-failure-20261009-r3/package/CHAT_TASK.md)、[root_cause_matrix.json](https://github.com/lexi2016/v4/blob/b98d85c95d19780e2900dce7de9372328e67acf6/handoff/manager-daily-failure-20261009-r3/package/root_cause_matrix.json)、[source_manifest.json](https://github.com/lexi2016/v4/blob/b98d85c95d19780e2900dce7de9372328e67acf6/handoff/manager-daily-failure-20261009-r3/package/source_manifest.json)。
- [S2] [R3 two GET projection](https://github.com/lexi2016/v4/blob/b98d85c95d19780e2900dce7de9372328e67acf6/handoff/manager-daily-failure-20261009-r3/evidence/live_get_projection_20261009.json)、[runtime_identity.json](https://github.com/lexi2016/v4/blob/b98d85c95d19780e2900dce7de9372328e67acf6/handoff/manager-daily-failure-20261009-r3/evidence/runtime_identity.json)。
- [S3] [R2 Mac input audit](https://github.com/lexi2016/v4/blob/b98d85c95d19780e2900dce7de9372328e67acf6/handoff/manager-automation-r2-mac-20261009/input_audit/r2-input-identity-audit.md)、[supplement consumer map](https://github.com/lexi2016/v4/blob/b98d85c95d19780e2900dce7de9372328e67acf6/handoff/manager-automation-r2-mac-20261009/integration_audit/supplement_consumer_map.json)、[independent_receipt.json](https://github.com/lexi2016/v4/blob/b98d85c95d19780e2900dce7de9372328e67acf6/handoff/manager-automation-r2-mac-20261009/review/independent_receipt.json)。
- [S4] [HK_REPLAY_RECEIPT.json](HK_REPLAY_RECEIPT.json)、[R1 source manifest](https://github.com/lexi2016/v4/blob/008649895054cb24f1d1c3df37e215d307615db3/handoff/manager-daily-automation-repair-20261008-r1/source_manifest.json)。
- [S5] [HK_TEST_EVIDENCE.json](HK_TEST_EVIDENCE.json)、[new scoped test](tests/app/tests/test_manager_r3_hk_continuation.py)、[final_scoped.log](hk_validation/final_scoped.log)、[original_supplement.log](hk_validation/original_supplement.log)。
- [S6] [test-only DEPENDENCY_ORIGIN.json](reference/test_dependencies/DEPENDENCY_ORIGIN.json)。两份旧源引用仅用于合成测试导入，本轮未将旧候选当当前 Mac before。
- [S7] [HOST_HANDOFF.md](HOST_HANDOFF.md)、[原 Issue30 policy](https://github.com/lexi2016/v4/blob/b98d85c95d19780e2900dce7de9372328e67acf6/handoff/manager-daily-failure-20261009-r3/package/source_snapshot/issue30_release_policy/ops/api_release_integration.py)、[独立 policy proposal](release_policy_review/after/ops/api_release_integration.py)。
- [S8] 本轮只读源码：[workspace_plan.py](https://github.com/lexi2016/v4/blob/b98d85c95d19780e2900dce7de9372328e67acf6/handoff/manager-workbench-mac-completion-20261008/source/api_app/v4/manager_research/workspace_plan.py)、[existing announcement CLI](https://github.com/lexi2016/v4/blob/6a2fa48faf1da0a7d0d1715b3a4a40f55249b64c/ops/run_manager_daily_announcement.py)、[actual HK02 source](https://github.com/lexi2016/v4/blob/b98d85c95d19780e2900dce7de9372328e67acf6/handoff/manager-daily-failure-20261009-r3/package/source_snapshot/hk02_updater_actual/shared_data/hk_0_2.py)。它们分别标识 API 候选、既有 CLI 参考与 supplied actual updater 快照，不混称当前模块运行证明。
