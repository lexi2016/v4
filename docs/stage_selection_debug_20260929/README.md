# V4 阶段选股修复与 Mac 接续

固定输入：`8851f7f84e3d506d3f1317eec03ba92c8f49e324`。
代码提交：`912a259e522c5ca1cc548cdd556a23e7eb781a57`，包含先前竞价修复 `1716cec795db1389bb57b13919a90ce2e9b60529`。
修复分支：`codex/stage-selection-debug-20260929`；PR #6 的 base 为 `codex/v4-source-review-20260929`，不是 main。

状态：**源码候选已实现，作者 Linux 合同测试通过；独立审查、Mac 集成、发布、localhost API/UI 及自然时段验收均未完成。** 不合并、不部署、不操作本机服务。本目录不是 Mac 执行回执。

## 1. 真实调用链与证据边界

```text
服务 plist / 实际 release / 解释器 / stage_center_tick_config
  → ops/run_stage_center_nodes.py（PREP、各 stage 调度）
  → ops/materialize_stage_acquisition_universe.py
      resolve_source_root(data_root, preselection_source_root)
      V35 原始预选池 → V4 严格候选发布（职责不切换）
  → ops/_run_stage_center_nodes_parts/stage_dispatch.py
      市场日历 → due/cutoff → 原 slot 锁/尝试预算 → capture_attempt
  → stage_center/runner.py / _runner_parts
      A 精确候选与来源授权；HK 精确冻结 D-1 池与独立日期
  → live_collectors / _live_collectors_parts
      A 竞价或分钟；HK ExHQ + active snapshot；HK stage8 独立 RT_DATA replay
  → 原 raw_store → production_selection_builders → 原 selection 公式
      A 14:45 另经 research_context → 完整来源见证及归档投影校验
  → SelectionStore.publish / store_publication / artifact_codec
  → SelectionStore.read_verified / store_verification
  → StageSelectionConsumer.get
      正式 lane 优先；只有空 CANNOT_CONFIRM 可读取显式绑定的已封存历史 run
  → 原 apps/api/v35_api/app.py 的 project_shared_selection
  → 普通 workbench API / shared API / 只读 ensure
  → 原 App.vue 阶段卡片、主列表和历史来源说明
```

用户报告的 100 个 HK 代码、40,000 根历史 bars、六阶段各 10 行、A 190 条竞价输入、14:00 原归档及本机隔离修复均是**用户提供的 Mac 运行事实**，本轮没有取得这些正式数据，也没有再次独立验证它们。

本轮从固定 GitHub 提交验证的事实：来源根 helper 和参数传递、嵌套 manifest 身份兼容、原 HK 历史观察选择器及原不可变存储合同已存在；下述缺陷仍存在。没有重新安装或拆分原 37 项。读取了根 README、AGENTS、快照 manifest 头部及 exclusions；未声称逐一审计 1,312 份文件。16 份行情 fixture 的排除不作为产品缺陷。

## 2. 根因、第一拒绝点和最小失败例

行号针对上面的代码提交；Git PR diff 提供精确前后像。

| 症状 / 层 | 第一拒绝点、证据及最小失败例 | 最小修复 |
|---|---|---|
| A 准备阶段或服务仍读错来源 / 配置部署 | `infrastructure/stage_source_roots.py:55`、`ops/materialize_stage_acquisition_universe.py:57,114-116`、runner 配置已显式传递来源根。源码存在不证明实际 release 已加载。 | 复用当前来源根修复；不改 V35 producer，不切根。Mac 核实际配置和加载 SHA。 |
| 构建漏掉拆分 helper / 发布 | 旧默认及 legacy overlay 不含 SelectionStore 的三个 helper。最小例是对两套清单断言这三个路径都存在。 | `ops/stage_selection_release_contract.py` 固定 88 文件 SHA（87 Stage + domains/research）；overlay 接入完整 cohort 和本地 Stage 静态导入检查。缺路径、错 SHA、symlink、半套清单及新增未审核 helper 都拒绝。 |
| manifest 层级错误 / 发布 | 固定提交的 `_active_stage_manifest_identity` 已支持 `candidate.app_root/root/release_id`，也保留冲突/缺失拒绝。 | 不重修 builder。复用并增加匹配、冲突、缺失测试。构建器原 `require_stage_overlay_source_hashes` 在候选目录创建前执行。 |
| HK 历史分钟数据被清空 / 采集 | `_live_collectors_parts/hk_minute.py:92`：不安全 active snapshot 直接清空 rows，后续已有观察选择器到不了。合成 ExHQ 12 行 + temporal unsafe 即可复现。 | 在第 70 行前置限定历史分支，仅显式 historical_backfill、ExHQ、READY/PARTIAL、有行时保留观察输入。剥离当前 active lane，保留错误原因，标记历史快照不可得。自然运行时间检查、失败源、stage8 路由不放松。 |
| A 14:45 合法归档投影不一致 / 选择前来源验证 | `research_context.py:280-313` 完整对象比较；源含 affected_codes 时原 `build_research_archive` 未重建排除警告。合成 27 codes 的全对象比较复现。 | `domains/research.py:385-394` 按源声明生成警告并验证声明类型，沿用全对象和 SHA 校验。没有日期/SHA 特例，没有删 cannot_confirm；15:00:02 仍拒绝。 |
| A 竞价缺昨收显示 0% / 展示与证据 | `_selection_parts/primitives_io.py` 把显式 null 又变成 last/open；前端 `aShareChangePct` 再次回退。None/空/0/-1 昨收分别能复现 0 或 -1100。 | `a_auction.py:53-60,97,110` 显示值 nullable、依据 UNAVAILABLE；`primitives_io.py:104` 只对键缺失保留旧 fallback；前端 formatters:61,116 明确显示未知。冻结评分输入、公式、排序不变。 |
| 补抓成功，普通页面仍空 / 消费 | 旧 consumer 只读正式指针；精确历史 run 已封存也不会被普通 get 读取。合成绑定 + 正式失败可复现。 | 新 `historical_readback.py` 显式绑定现有 backfill run；`consumer.py:426-430,447` 接入原读回。API 文件不需要修改，原投影保留根级历史血缘；`App.vue:209-218` 展示原正式失败与历史 run/SHA。 |

归档规则是通用的“来源声明 → 确定性警告”投影，不是对一个历史 SHA 放行。未携带该声明的源保持旧投影。声明存在但旧归档没有这些警告的组合仍会被完整对象比较拒绝；不得通过忽略差异兼容。Mac 必须用实际 producer 身份、source manifest 和完整归档核对适用性。

竞价修复区分显示和评分内部缺失值政策，没有借此补造昨收、修改历史排名或修改 `trade_status` / `action_level` / `formal_eligible`。现有 builder 的字段传递/评分策略不因本补丁改写；本轮不宣称恢复了缺失的实际昨收。

## 3. 每阶段普通读回合同

| stage ID | A | HK | 历史产物前提 |
|---|---|---|---|
| STAGE_0925 | 适用 | 适用 | 各自合法竞价/replay 产物；不拿分钟代替竞价 |
| STAGE_0930_0935 | 适用 | 适用 | 精确池、窗口、原 raw/selection 证据；HK 可为明确历史 ExHQ 观察 |
| STAGE_0935_0940 | 适用 | 适用 | 同上，必须绑定本 stage 的独立 run |
| STAGE_0940_0945 | 适用 | 适用 | 同上 |
| STAGE_0945_1030 | 适用 | 适用 | 同上 |
| STAGE_1300_1315 | 适用 | 适用 | 同上 |
| STAGE_1445_1500 | 适用 | 适用 | A 还须合法研究归档/source witness，严格 15:00:00 cutoff |
| STAGE_1545_1555 | 不适用 | 适用 | 原 stage8 精确 RT_DATA replay，不走 ExHQ fallback |

共同读回：`selection_root/historical_readbacks/<date>/<stage>/<market>.json` 只引用 `selection_root/backfill/<backfill_run_id>` 下精确 `selection_run_id`。写入需要显式日期、阶段、市场、两个 run ID 和三项 expected SHA。CSV 是字节 SHA；manifest/receipt 是 **SelectionStore 原合同的 canonical JSON SHA**，不要拿文件字节 SHA 混用。

绑定经原 `_verify_run` 核验完整三件套和算法/身份；要求明确 backfill source_evidence、非空合法结果、全部安全位 false。原锁内复验后只原子创建引用。相同引用幂等；冲突、跨日期/阶段/市场、路径穿越、symlink、错 SHA、无历史标记都拒绝。不查最新目录、不按 mtime、不自动重写绑定，不改正式 latest 或历史三件套。

每次读取重新核验。正式有行或 READY_EMPTY 优先；仅正式空 CANNOT_CONFIRM 可使用有效绑定。一个市场历史损坏不清空另一个有效市场。无合法绑定仍为空并保留失败，而非强制 READY。

历史投影包含 `result_origin=HISTORICAL_BACKFILL`、`real_time_success=false`、原正式 run/status/cannot_confirm、绑定 SHA；行的排序、NO_TRADE/NO_BUY 等真实字段不改。API 的 `historical_readbacks` 与 canonical/alias rows 同源。原 natural/recovery receipt 血缘仍独立保留，不伪造自然成功。

## 4. 实际测试与未通过项

详见 `validation.txt`。作者环境为 Linux Python 3.13.5 / pytest 9.0.2、Node 22.16.0；仓库要求 Python >=3.14，因此这里不是目标环境验收。因本容器 Starlette 不提供仓库 warning filter 引用的类别，使用 `-o addopts='-W error'` 进行限定测试，仍保留 warnings-as-errors；没有修改依赖或 pytest 配置。

最终针对性组合：117 passed。包含竞价11、HK历史10、归档投影10、历史消费者/API36、发布合同11，以及原 name/consumer/source-root 回归。三项 Node 检查中两项执行真实格式化函数，一项只检查 HK-only 的 SFC 条件分支；不是浏览器渲染测试。目标 TypeScript 文件检查 exit0。

额外回归组合：32 passed、2 failed。失败分别为 `test_persistent_v4_node_entrypoint_checks_ten_nodes`（本机配置检查 exit3）及 `test_node_cli_check_is_reproducible_without_network`（Mac 绝对解释器路径不存在）。没有跳过后冒充全绿；与117项有重叠，不能相加成独立通过总数。

全部市场输入均为确定性合成 fixture。HK 测试只证明桥接/原选择器/存储逻辑，不能证明真实 bars 时间、分页、自然采集或授权；TestClient 只证明原 API 的进程内逻辑，不是连接 8873。未运行完整 Vue 构建/浏览器、全仓测试、真实行情验收或 Mac 服务检查。

## 5. Mac 接续：先前像适配，再验收，不覆盖隔离新修复

### A. 独立目录和前像

先读本机上位 AGENTS 和工作区规则。获取 PR 后使用新的独立目录，不在 dirty 工作区 reset/覆盖：

```sh
git fetch origin codex/stage-selection-debug-20260929
git worktree add --detach "$REVIEW_WORKTREE" 912a259e522c5ca1cc548cdd556a23e7eb781a57
```

`source_receipt.json` 列出18个源码/测试路径的 before/after SHA。逐文件把 Mac 当前源与固定输入、候选后像比较。当前等于后像则复用；等于前像才可直接应用该最小差异；其他值（尤其本机 HK/UI/API/归档/overlay 隔离候选）必须三方适配和独立审查。API `app.py` 本轮未修改，但必须保留本机新增 owner 接线。不要回装旧 runner、slot lock 或三个 store helper。

适配改变了 cohort 字节时，独立审核差异后更新对应显式 pin 并重测；不能自动把所有当前 SHA 认作批准版本。88项是本地 Stage 静态依赖集合，不是第三方和动态 provider 的完整运行证明。严格模式若要求当前快照缺少的 `stage_center/commit_store.py`，原拒绝保留：核清现役 publication_mode/已批准 owner，不切模式绕过。

### B. 目标解释器测试和非活动候选

用实际服务解释器在隔离目录运行本目录测试命令；目标环境应执行仓库正常 pytest 配置。补跑上述两个 Mac 依赖检查以及既有运行依赖探针。确认 V35 来源根、V4 发布根、A/HK独立池日期与 SHA。分别读取 scheduler、hk-deadline 的实际 plist/release/manifest；后者保留 `--deadline-only`。

通过后才使用原构建器生成**非活动候选**，下列变量必须来自现役只读配置而非猜测：

```sh
"$SERVICE_PYTHON" ops/build_release_candidate.py \
  --stage-service-candidate \
  --source-root "$INTEGRATED_SOURCE" \
  --candidate-root "$NEW_INACTIVE_CANDIDATE" \
  --stage-plist "$EXISTING_STAGE_PLIST" \
  --stage-runtime-python "$SERVICE_PYTHON" \
  --release-id "$REVIEWED_RELEASE_ID" \
  --formal-release-root "$FORMAL_RELEASES_ROOT" \
  --receipt-path "$CANDIDATE_RECEIPT"
```

对两个服务分别按各自现役基线验证；未批准前不改绑定、不 reload。该候选不自动更新 8873 的 API/Web。API 也须按既有发布流程加载修复后的 consumer/helper；确认 `stage_center_selection_root` 指向同一个正式 selection 根而不是 None/另一个 backfill 根。Web 需在既有工程执行 `npm --prefix apps/web run typecheck`、`npm --prefix apps/web run build` 和相关组件/浏览器测试。这里没有自动发布命令。

### C. 只绑定已经独立验收的现有历史结果

先确认原 raw/PIT/cutoff/候选池/producer 证据已被 Mac owner 验收。本模块只复用原 SelectionStore 封存核验，不代替重新核验原行情和业务正确性。不得为适配本模块修改旧三件套、补历史标记或补时间。

```sh
"$SERVICE_PYTHON" -m stage_center.historical_readback \
  --selection-root "$SELECTION_ROOT" \
  --trade-date "$EXACT_DATE" --stage-id "$EXACT_STAGE" --market "$EXACT_MARKET" \
  --backfill-run-id "$ACCEPTED_BACKFILL_RUN" --selection-run-id "$ACCEPTED_SELECTION_RUN" \
  --expected-artifact-sha256 "$CSV_SHA" \
  --expected-manifest-sha256 "$CANONICAL_MANIFEST_SHA" \
  --expected-receipt-sha256 "$CANONICAL_RECEIPT_SHA"
```

这是**本机后续经批准执行的引用写入**，不是本轮已执行。不同历史 owner 目录/标记若不符合既有 backfill 合同，先据精确身份适配 reader，不能搬数据造第二底板。无需重新抓取用户已验收的40,000根 bars。

逐个适用 date/stage/market核对普通 `/api/v3/workbench/stage`、`/api/v3/stage-center/selection`、只读 ensure 以及 `/?date=20260928&stage=...`。比较 run/artifact/SHA、顺序、逐行 status/action/formal、未知涨幅、来源标记，不只比10条。无需特殊 backfill_run_id URL。A 的 HK-only 阶段显示不适用。

### D. 发布后和自然时段的独立证据

任何后续部署均由 Mac owner 另行批准。发布后逐个进程核 `__file__` 与源码 SHA、解释器、manifest/inventory、实际配置根；“主仓已有代码”不等于服务加载。自然时段按原调度采集合法输入并核 attempt → raw → selection三件套 → 普通API/UI；未发生前不写自然成功。合法缺证仍可 CANNOT_CONFIRM，不承诺外部行情永不失败。

撤销候选时不改原正式历史记录：未部署直接保留现役服务；需要撤销本机新建历史引用时先暂停该引用的接入、核准确切绑定 SHA，并按既有变更审批处理；不要删除 backfill 数据、正式指针或改写原 receipts。代码回退仅针对本 PR、经当前字节核对后在新分支 revert，不覆盖本机其他修复。

## 6. 最小可脱敏证据，不需要源码/行情 ZIP

仅需每服务 label/release_id、解释器版本、实际加载模块相对路径及 SHA、manifest SHA及相关 inventory 行、来源/目标根角色；每结果 date/stage/market、两个run ID、三项SHA、raw SHA、原正式状态和第一拒绝原因；A归档生成时刻/cutoff/producer身份SHA；HK冻结D-1池日期/数量/SHA；普通API读回的origin/count/status及一条脱敏字段样例。路径可角色化，保留相等/不同关系。不要发送凭证、完整配置或原始行情。

安全始终保持 RESEARCH_ONLY、production_allowed=false、buy_gate_updated=false、orders_sent=false。源码实现、作者测试、独立审查、集成、部署、真实API/UI和自然运行必须分别记录。
