# V4 三路选股闭环：候选修复与逐项验收

## 结论

**整体：PARTIAL／未完成。** 本轮已实际修改候选源码、补充回归、修复独立 Reviewer 发现的问题，并交付可核对的差异。候选工程结果不等于三路真实业务闭环。未访问到用户 Mac 的 8873，也没有实际公告、HK、超跌输入和自然运行回执，A/H/O/I/R/N 均不得报现场通过。

候选以附件的 126 个配置指向源码文件为基线。修改 12 个业务文件，保留既有 owner、两门筛选规则、Stage 排名、HK/US 已有补丁与 BUY 门禁；没有修改 canonical、scheduler 配置、服务或 Vibe 8910。本轮由 Chat 单一 Writer 实施，由独立、只读 Reviewer 审查和复跑；未声称在用户 Mac 上运行了 Luna Max。下一步仍由 Mac 端 Luna Max Writer 与不同身份 Reviewer 完成真实集成。

安全标记持续为 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。没有生成订单或改写生产研究输入。

## 1. 基线、身份和差异

- 输入 ZIP：`V4_三路选股闭环_问题包_20261011(2).zip`，949,918 字节，SHA256 `3e389c00b4c82b4e987b3e06f51af70728d10b48e6d8de1f5554640e8b66eee7`；137 个成员，CRC 通过。
- 附件 `SOURCE_MANIFEST.json` 的 126/126 文件 SHA 和字节数已核对；`PACKAGE_MANIFEST.json` 的 136/136 项已核对。
- 候选快照基线 commit：`2152496bf288b696c5c7eb6e9e2abc08962ca33d`。它是附件源码快照，不能替代完整 V4 仓库或实际加载进程身份。
- 源码根、候选 commit、逐文件 active-before/canonical-before/after SHA、字节数和 Git blob SHA 见 `SHA_MANIFEST.json`。
- `source.patch` 是本轮实际差异；`source_before/` 只含修改前的 12 个业务文件；`source_after/` 含修改后的业务文件、必要测试和实施计划。没有打包依赖环境、行情、真实计划或认证文件。
- canonical 与配置源码根在附件中有 35 个文件不同。**不能对 canonical 整包复制或用现役 SHA 覆盖其未提交改动。** 使用本包只读 preflight 核对；任何混合、未知 SHA 或符号链接必须停在人工三方合并。
- 配置指向的 API 根：`/Users/lexi/Desktop/学习/agents调试/V4_US_MAPPING_DAILY_CHAIN_MAC_20261011_R1/integrated_release/manager-us-mapping-daily-chain-20261011-r1/app`；canonical：`/Users/lexi/Desktop/学习/v4_app`。
- 配置 release manifest SHA 为 `3b548f81684bd48e19b9cad8ac824f036163699f8cf53dc3234bc184df9014ad`，内部仍有 NOT_ACTIVATED/base/旧 plist 元数据冲突。本轮没有篡改该 manifest；配置路径不是 loaded-module 证据。
- 8873 浏览器实际访问失败：`net::ERR_CONNECTION_REFUSED`。本轮没有 Mac PID、loaded-module SHA、部署回执、实际 HTTP 正文字节或页面重载证据。

## 2. 实际修复内容

| 问题 | 本轮代码行为 | 保留的边界 |
|---|---|---|
| P1 历史累计正文溢出 | 在读取其他归档正文前，按精确 run 读取原 `workspace_plan_runs` 有界回执。仅合法、终态、在 cutoff 后才开始的原 owner attempt 可排除该正文；latest 仍核正文 SHA。回执字节也计入扫描预算。 | 32 MiB 单计划、64 MiB 总扫描和 64 runs 上限不变。缺 journal 仍回原正文验证，坏 journal 不能证明历史缺席；不建索引、不删除归档、不把事后计划准入。 |
| P2 公告 owner 导入分叉 | 注册 handoff 的校验、原产品导入、owner receipt 创建/复用和读回统一到原 `import_announcement_analysis` service。HTTP 入口委托同一事务；并发重试保留首次真实可用时间，冲突 receipt 在写产品前拒绝。 | legacy 产品仍可读，但不会因此补造 reviewed receipt；没有把显示的 55 只写入代码或导成历史完成。 |
| P3 HK 正式产品与显示投射 | 从原 Stage consumer 保存完整 canonical `HK_CONNECT` SelectionStore 来源，保留 run、manifest/artifact/receipt/raw SHA、排名、顺序、原理由和 NO_BUY。普通产品也走现有 provenance 读回；不使用 50 行 UI 别名。 | backfill、错日、错市场、缺三件套、行数不符、未核 membership 均拒绝。当前缺执行/可用时间合同，已保存正数最多 PARTIAL；空结果数量仍为 null；历史 HK rows 不准入。 |
| P4 超跌只显示 strict 桶 | 每日摘要读取并重算校验原 `build_research_selection_ledger`，使用完整逐股 decision ledger，保留 SELECTED、NEAR_WATCH、原因、metrics、coverage 和来源身份；绑定原保存计划及精确 attempt。 | 不新造选股算法。未保存或来源不全不能报有效零；该 owner 的最终研究名单与正式 Stage 分开，`formal_selection_input=false` 保留。 |
| P5 全局登记污染 | 完整、可识别的原 peripheral owner 引用只排除非语义全局 manifest SHA；具体 payload、receipt、路径、日期、cutoff 和 raw source content 仍参与。已识别 binding 列表用规范 JSON 排序；attention 外层沿用语义 digest。 | 不是忽略所有 SHA；混合未知引用数组不作泛化豁免。旧已封存 opaque identity 不能安全自动迁移；实际 10/12 的 material identity 变化尚未解释。 |
| 当前回看与保存读回 | `auto` 保持已保存 cutoff；显式 `dynamic` 用当前时间重新读原 owner，保存产物自身 run/SHA/cutoff 不改。历史读回补传原 execution context，精确产品 attempt 与后续最新失败 attempt 分开。 | 不通过刷新或重新封存掩盖旧计划失效。 |
| 统一页面与日期 | 显式 selection/announcement/publication 别名、view 进入 GET/POST 与 URL 重载；公告日变化会重读两处来源，旧异步响应不覆盖新日期。显式日期要求响应返回匹配绑定。 | 不把 legacy `date` 擅自当默认公告日，默认日期仍由原 calendar 决定。 |
| 页面结果完整性 | HK 核完整、有序会员许可行、name/reason/lane evidence、原三件套引用；拒绝截 50、清空造零、重排及单侧来源修改；历史和 backfill 否决条件与后端一致。 | DTO/DOM 校验不是实际 owner 执行或现场浏览器验收。 |

### 计划误失效的兼容限制

附件只提供 10/12 的摘要：46 个 material 引用和 15 个 projection 引用除全局 manifest SHA 外一致，但没有保存产品与当前输入的完整前像。本轮复现并修复了 peripheral binding/外层 digest 的具体污染机制，验证相关输入变化仍失效；**不能由此断言实际旧 run `1e9d511515de47599f05539e43e79b81` 已恢复 CURRENT**。

新规范化可能令部分旧 opaque peripheral identity 一次性不匹配，即使输入未变；没有自动迁移或改写 sealed plan。实际 10/12 产品 SHA `1ce6a9e12c4bf692707b38bbf7c73a75acbea499a9cc3d0bc624538da9234aec` 必须在 Mac 上与当前精确 owner 前像重算，先解释 material component，再决定兼容修复。不得先刷新再把旧故障报作修复。

## 3. 实际测试与独立审查

| 范围 | 结果 | 证明什么 |
|---|---|---|
| 5 个新增 Python 文件 + 2 个原 saved-plan 回归 | Writer 最终 **68 passed，1 个依赖弃用 warning**；后端 Reviewer 独立 **68 passed** | 66 个新增历史、身份、公告事务、三路 ledger/Stage 投射、实际 service 保存和历史读回、当前 cutoff 回归，加原产品篡改与后续 owner 失败保护。 |
| 新增前端 2 文件 + 原 runtime 文件的可执行部分 | **43 passed，1 skipped**；其中新增 34，既有 9 | 真 Vitest/jsdom DOM、真实 API request/response 函数和校验器；网络输入为明确的合成 fixture/mock。 |
| 修改的 3 个前端模块及其实际导入依赖 | TypeScript strict `tsc --noEmit` 通过 | 不是完整应用 build。 |
| 最终 Python 语法、Git 差异、补丁与 SHA | 见 `evidence/verification.json` | 以最终文件字节执行。 |

前端跳过的 1 项要求用户 Mac 上的 `/Users/lexi/Desktop/学习/agents调试/EASTMONEY_HK_ANN_20260929/integration/workspace_after.json`，本环境没有该实际 fixture，明确 NOT_RUN。没有伪造它来让全套通过。

真实测试环境：Linux；Python 3.14.8、pytest 9.1.1、真实离线 FastAPI/httpx。附件缺的 506 个 Python 支持文件通过固定仓库 commit `1ea98799d1763c88be2be1f0ee1b0ccec654532f` Git blob 校验后恢复，仅作隔离测试。公告 helper/fixture 与前端原公告 API helper 也由固定来源恢复。前端 Node 24.19.0、Vitest 4.1.10、TypeScript 5.9.3、Vue 3.5.40、jsdom 28.1.0；240 份缓存 tgz 校验 SHA512 并恢复依赖链接。原 lockfile 不可用，因此这不是 Mac 已安装依赖的复现证明。

`stage_center.execution_evidence` 的配套现役接口未取得：当前 consumer 需要 `research_source_projection` 和 `read_stage_execution(..., selection_store=..., selection_stores=...)`，所有已查到的旧模块均不满足。没有给旧模块加 shim，也没有新造时间字段。**完整现役 Stage consumer 集成 NOT_RUN**，该单点改动仅有语法和独立静态审查。

独立审查发现并修复：后端缺 Stage 时写入空安全标记阻断原 service 保存；历史合法读回丢 execution context；前端 HK 名单截断/伪零/理由和引用松绑；历史/backfill 否决遗漏；显式日期可被缺绑定旧响应绕过。每组先出现失败反例，再修复复跑。完整记录、命令与测试摘要在 `evidence/`；合成输入均标明 `SYNTHETIC_UNIT_INPUTS_NOT_LIVE_OWNER_EVIDENCE`。

### 明确保留的旧套件失败

- 扩展旧 Python 套件在初始 candidate 为 59 passed / 22 failed / 1 skipped；同依赖、原 baseline 为 62 passed / 19 failed / 1 skipped。新增的 3 个失败指向缺 Stage 保存问题，已修复。未把基线缺依赖/旧 fixture 合同问题清零。
- 旧 `test_original_service_future_plan_refresh_does_not_run_catalyst_producer` 的保存路径已恢复；末尾默认 dynamic 读仍要求新时钟 identity 等于保存 identity 的断言与显式当前回看语义不同，该旧断言不计入最终 68 PASS。
- 原公告 parity 套件曾为 38 passed / 1 failed；失败是旧“missing archive 仍应 READY”的 selection diagnostics 预期，不计入最终 PASS 范围。
- 两个 business completion 文件在 Reviewer 环境缺 `tests.r3_scoped_loader`，发生 collection errors；未作全套通过声明。

## 4. README 验收表：逐项结论

| 编号 | 本轮候选证据 | 真实验收结论及缺口 |
|---|---|---|
| A 公告 | 原注册 handoff → 同一 service 事务 → product/receipt → TestClient HTTP 读回与并发/冲突回归通过；页面日期回归通过。 | **PARTIAL / LIVE_NOT_RUN**。缺 20261008 公告原 owner 产品、reviewed receipt/registry 和实际 availability。55/32/121/73 是附件 UI 观察值，不是本轮实跑。未核真实 API 与重载页同 run/SHA。 |
| H 港股通 | 原 canonical Stage 完整读回、三件套和 membership 投射、拒 backfill 与未知非零回归通过。 | **PARTIAL / INPUT_UNVERIFIED**。缺 20261008 security-master、finality/amount/trade units 证明、20261009 D1 Top100 正式 receipt，以及配套现役 execution module。没有原算法的真实正式完成回执。 |
| O 超跌 | 原完整 research ledger 校验；保存计划/精确 attempt 与历史读回通过；合法保存空集可为 0，缺来源 null。 | **PARTIAL / INPUT_UNVERIFIED**。缺目标行情 session、逐 symbol 前 60 个完整 session 的 close 与量价来源、原 screen/decision 输入和 receipt；没有实际最终研究名单。214 strict 不计完成。 |
| I 身份 | 21 项新增身份回归及独立 spotcheck，通过具体 manifest-only 与相关字段变更行为。 | **PARTIAL / EXACT_OLD_PLAN_NOT_REPRODUCED**。缺真实旧保存与当前 material/projection 前像；旧 opaque identity 兼容限制仍在，不能报实际 10/12 CURRENT。 |
| R 历史/现在回看 | 11 项有界历史回归、原历史合法保存读回和显式当前 clock 通过。 | **PARTIAL / LIVE_NOT_RUN**。缺七份实际归档正文和精确 run journals，无法证明真实 10/09 已不溢出。若原 journals 缺失，优化会保守回到有界正文读取，仍可能保留原溢出错误。 |
| D 单路缺件与有效零 | 原 service 缺 Stage 仍保存 PARTIAL；原 ledger 合法零不被其他 lane 缺件污染；DOM 显示未知/有效零并保持其他结果。 | **候选行为 PASS，现场 NOT_RUN**。没有把输入缺失、未运行或未保存记成 0。 |
| N 自然日常运行 | 本轮没有 scheduler、原 owner 自然执行或 Mac 页面重载。 | **NOT_RUN**。核查时仍是 2026-10-11；下一候选目标日 20261012 应按现场原交易日历与实际 schedule 核对。未到下一自然时段不是已有自然成功回执。 |

### 三种时点口径

1. **10/09 09:30+08 历史 PIT：**七个已知归档均生成于 10/10–10/11。优化只能正确排除，不能产生当时合格计划。公告事后成果、HK backfill、事后 panel 均不准入。
2. **显式现在回看：**`view=dynamic` 以本次读取时间复核原 owner；真实注册且日期匹配的事后公告、保存研究名单可以按实际状态显示。没有历史可用时间的 HK 只保留 PARTIAL。此口径尚未用 Mac 的实际产品验收。
3. **下一自然运行：**必须有真实 scheduler trigger、原 owner input/run/product/receipt，以及同日期 API 和浏览器重载。手动 refresh、隔离测试和 scheduled 字符串均不能替代。

## 5. 具体缺件、日期、原 owner 与恢复责任

| 缺件 | 日期/字段 | 原 owner / 现场恢复工作 |
|---|---|---|
| 真实进程身份 | API PID、加载模块绝对路径与 SHA、部署回执；API/scheduler/Stage 分别核 | Mac Luna Max Writer 读实际 launchctl/lsof/进程和原部署回执，Reviewer 独立核。先解释 manifest 与 plist 元数据冲突，不改旧 manifest 让它看似一致。 |
| 历史原件 | `workspace_plans/20261009/{run}.json` 和 `workspace_plan_runs/20261009/{run}.json`；7 个文件总 147,031,510 B | `ManagerResearchJobService.refresh_workspace_plan` 原 store。只读核精确 journals 是否存在、SHA/日期/owner/时间是否有效；没有 receipt 不补造。真实原 API 摘要记录的 body SHA 为 `cf091b2ddf57ecbb3d426de527eecbd42cb7bfe715b117bb0745400c41555861`，16,212 B，原正文未附。 |
| 公告原件 | publication=20261008，plan/target=20261009；catalog、judgment、registered handoff、owner import receipt、available_at | 原 Eastmoney date catalog / announcement agent / `ManagerResearchJobService.import_announcement_analysis`。从原 store 读回和复算，不重猜标题；优先复用现存注册成果。按合法 reference 调原 owner 的导入入口，保留真实首次 availability。 |
| HK security-master | 20261008 精确 snapshot/receipt；不能用 20261009 17:31:16+08 的 693 行快照 | 原 `ops/ensure_hk_security_master.py`，先 `--trade-date 20261008 --reuse-only`；有经过验证的精确源时才用已有 `--verified-source-store-root` 恢复。禁止用当前 capture 回填过去 availability。 |
| HK D1/0.2 合同 | 20261008 provider session finality=NOT_ATTESTED，amount/trade units=NOT_PROVEN；20261009 canonical D1 Top100 receipt=EXPECTED_MISSING | `v35_dispatcher.research_panel_daily_hk`、`domains/manager_research_evidence`、原 `materialize_scheduled_preselection` / Stage preflight。先补可核真实输入，再调原 consumer；没有完整合法源就保留缺口，不能用全市场或 backfill 代替。 |
| Stage 实际执行证据 | 当前 execution module、0925/0935 各自真实 stage_id、run、三件套、actual generated/available time | 原 `StageSelectionConsumer` / `SelectionStore` / `stage_center.execution_evidence` owner。当前 shared reader 固定调用 0935–0940；不得改名成 0925 或 09:30 已知，也不得用文件 mtime、声明 recorded_at 或计划 cutoff 当执行时间。 |
| 超跌原输入 | 目标 session；每 symbol 前 60 个完整交易日 close 与 high-window、当日 volume、前 5 日 volume mean，以及原 artifact/receipt | 原 HK_0_2 rebound screen、`research_attention.build_research_selection_ledger`。在 Mac 输出逐 symbol 缺 session/字段清单，缓存优先；补采前读原 `docs/hk_history_backfill.md`，复用 TDX/tdxpy，不默换 Futu 来源。 |
| 10/12 身份前像 | 保存 run `1e9d511515de47599f05539e43e79b81`、旧/当前 material/projection inputs 和各来源 payload/receipt | 原 workspace identity owner。按同日期、同 cutoff、同原输入重算：先做无关 manifest 变化读回，再逐个改变相关输入确认拒绝。结果核实前不刷新旧计划或改其 SHA。 |

附件中的公告 catalog run `4b69fa03fbfc4c48b1c410239332505e` 与 HK backfill `c44b03fa94115911bc4aaa44d2152712` / `run-6e62af205e5142401ad186b0` 均只作为定位线索；后者绝不能计 H 或 N。完整观测 SHA 见 `evidence/input_evidence_summary.json`。

## 6. Mac 集成、验收与回滚顺序

### 6.1 先核源，再应用

下载固定交接 commit；读取当前 Mac 上位 AGENTS、canonical AGENTS 和相关 owner 文档。保留工作区全部未提交修改，分别核 API、Stage、scheduler 根和实际进程。当前包是源码增量，不能直接当完整 release 启动。

由 Mac Writer 选择从**已核实完整运行源**建立的独立候选工作目录，并设置 `V4_HANDOFF` 为本包目录、`V4_CANDIDATE_ROOT` 为该目录。先执行：

```bash
python3 "$V4_HANDOFF/tools/preflight.py" --source-root "$V4_CANDIDATE_ROOT" --manifest "$V4_HANDOFF/SHA_MANIFEST.json"
git -C "$V4_CANDIDATE_ROOT" apply --check "$V4_HANDOFF/source.patch"
```

只有 preflight 为 `BEFORE_ALL_READY_FOR_APPLY_CHECK` 且 apply check 成功，才在候选上应用：

```bash
git -C "$V4_CANDIDATE_ROOT" apply "$V4_HANDOFF/source.patch"
python3 "$V4_HANDOFF/tools/preflight.py" --source-root "$V4_CANDIDATE_ROOT" --manifest "$V4_HANDOFF/SHA_MANIFEST.json"
```

预期为 `AFTER_ALL_SOURCE_BYTES_MATCH`。任何文件与 active-before 或 after 都不一致、已有同名新文件、混合已应用状态或符号链接，都停在三方审查：使用 `source_before`、Mac 当前字节和 `source_after` 合并，只调整本轮允许的路径。canonical 不同 SHA 不是准许覆盖的依据。

### 6.2 在真实依赖上复跑

使用项目 Python：`/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python`。在候选完整 app 根运行 `evidence/test_commands.md` 的相对路径测试。前端用该完整 app 既有 package manager/lockfile 和原 test/build 入口，不把本轮离线重建的 node_modules 搬入 Mac。

必须补跑配套的现役 Stage consumer、announcement daily owner、HK 原算法与 rebound 原 owner 集成。未取得 execution module 及其真实时间合同前，HK 的 PARTIAL 行为是刻意保守的；仅恢复模块文件并不会让当前投射自动获得时间证明，需沿原 owner 合同补齐读取/校验后再增量审查。

### 6.3 原 owner 执行、归档、API、重载

按第 5 节恢复合法输入，使用已存在的 owner 命令/注册入口。公告已注册成果走原合法 reference 导入；HK 先 exact membership/D1/0.2 preflight，再原 Stage；超跌运行原两门筛选及完整 ledger，再原 workspace plan 保存。每一路记录原 input/run/产物 SHA/receipt 和触发类型，不通过手工编辑 JSON 造成功。

实际集成 release 的生成、激活和回滚遵循 Mac 原部署流程；本轮没有启停授权操作或部署结果。激活后核加载代码 SHA 和静态资源版本，再读 API 与浏览器重载。本包附只读收集器，可分别保存三种口径，不运行 producer：

```bash
python3 "$V4_HANDOFF/tools/collect_readback.py" --date 20261009 --selection-date 20261009 --announcement-date 20261008 --view historical --output-dir "$V4_EVIDENCE_ROOT/history-20261009"
python3 "$V4_HANDOFF/tools/collect_readback.py" --date 20261009 --selection-date 20261009 --announcement-date 20261008 --view dynamic --output-dir "$V4_EVIDENCE_ROOT/review-20261009"
python3 "$V4_HANDOFF/tools/collect_readback.py" --date 20261012 --view auto --output-dir "$V4_EVIDENCE_ROOT/natural-20261012"
```

第三条只有在原交易日历核对、自然时段实际 owner 完成后用于读回；它本身不触发、不证明自然运行。各 output-dir 必须尚不存在，收集器不会覆盖已有证据。原响应 SHA 是 HTTP 字节 SHA，与业务 product SHA 分开。收集器退出 0 只表示 GET/JSON/日期可读，A/H/O/N 仍必须逐路核 receipt 并在真实页面重载核对同一 run/SHA。

浏览器打开原页面 `/manager-selection/?date=20261009&plan_date=20261009` 及显式 `&view=dynamic`；调整公告日、切换模式、刷新并重载。逐路确认名单完整、原因/数量与原 owner 相同，记录未知和有效零，检查原 HK/US 面板仍正常。保存 DOM/页面证据由现场 Reviewer 执行，本包无实际 Mac 截图。

### 6.4 回滚

尚未激活的独立候选可保留取证后退出，不改 canonical 或任何服务。已按原流程激活时，使用原部署工具恢复**此前经独立核实**的 release/pointer 并核加载模块与 8873；不改旧不可变 manifest。若仅撤销候选补丁，先确认所有文件仍等于本包 after SHA，再对同一候选执行 `git apply --reverse --check`，通过后才 reverse。文件有后续变化须人工合并，禁止 reset/clean/整包覆盖。Vibe 8910 全程保持原样。

## 7. 交付与证据范围

本轮同步仅允许 `lexi2016/v4` 新独立交接分支中的 `handoff/manager-three-lane-closure-chat-20261011-r1/` 路径；不 merge、不 force push、不改变旧冻结分支。远端基于已交付 US commit `a1b722e4c82defcb9537d5c05915c6a8072c02d3`，这与本地附件快照基线是不同用途的两个身份。

最终远端 commit 和读回 SHA 见交付时的 `GITHUB_SYNC.json`。该回执在提交后生成，不声称包含在它自己引用的 commit 内。`PACKAGE_SHA256.json` 核包内文件（自身除外）；所有业务前后 SHA 以 `SHA_MANIFEST.json` 为准。

**仍未完成的是实际三路输入与执行、Mac 集成/部署、真实 8873 重载、实际旧计划 I/R 复现和下一自然时段 N。工程测试全部通过的范围已明确列出，没有把它们换算成业务完成。**
