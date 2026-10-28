# V4 canonical scheduler / research panel 接管候选审查与实施报告

## 0. 裁决

**交付最小源码候选，结论 PARTIAL_CANDIDATE / HOLD。** 已修改当前 worktree 的局部接线并实测：persistent daemon → 原 runner/due → 原 registry → 真实 subprocess 公开入口 → 真实 A sync → 合成日文件、同步摘要、逐文件结果、lane receipt 和 dispatch receipt。HK 公开入口亦到达现有 shared updater。由于真实 A formula 输入、HK frozen assets、trusted CAS 及跨 stage/research-day 闭包没有本轮授权验收所需的完整证据，**没有取得正向 artifact/manifest 的完整接管通过**；失败仍为 FAILED，不是 READY。不得据此停旧服务。

本轮没有启动本机自然服务、连接账户/8910、执行 launchctl/systemctl、改 plist、改正式数据或回退用户当前前端改动。测试中的 daemon 为有限步 fixture 进程内调用，不是部署后的常驻实例。

## 1. 唯一基线与证据时代

- 输入：`v4-scheduler-research-panel-chat-handoff-20260913.zip`；实算 SHA256 与用户给定值完全相同：`75c161e48874dc6f973d79c421110f1b7c1d0f9399119db7e670241be3f9013f`。
- 已完整读取根 PROMPT/README/allowlist/exclusions/source-manifest/config bindings，以及四份 evidence 文档。737 个 source entry、751 个 package entry 的字节数及 SHA 均匹配。ZIP 含 752 个普通文件项；source/package 两种统计口径不可相加。
- canonical HEAD：`55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`；分支 `codex/system-consolidation-20260912`。基线是该包**当前工作树字节**，不是 clean HEAD，不是此前旧 ZIP。
- canonical 共 672 个普通文件。v16 57 个参考闭包文件对当前 canonical：**17 同字节、22 不同、18 缺失**。
- 旧 dependency closure 的 `canonical_daemon=MISSING` 已不适用于本次包：当前 daemon 显式包含且与 v16 同字节，SHA `c5a922e5f5dc71bd5df61a1ee72eb7fceb0d8347142c5297981242f207b226d9`。本轮没有再造 daemon。
- A sync 当前 SHA `312c9647c61fe2a7ce5d12b59fb06f10ba3f51e72be9b3be4b4e147fdb8a6174` 与 sync-increment-budget final review 对应字节一致，并在交付中不变。该旧 review 的通过不能替代本轮动态公开入口实测。
- 包内只记录外部 symlink 元数据，没有解引用补齐旧工程。reference_runtime/external 未复制进 canonical；canonical 原有 shared_data 包保留为单一 authority。

### M3 review 后的当前 SHA 漂移（特别报告）

| 路径 | 旧 review SHA256 | 当前 worktree / 本候选 SHA256 | 字节变化 |
|---|---|---|---|
| `apps/web/src/App.vue` | `1e47c2c50913a8ce3efa0ed61d51b2e5151adfbc040b881171b33b1884e48684` | `97febba244f280ba50facf8fdece1162c3c450c65ad0837fae11fb328ca5e751` | 50,750 → 51,480，+730 |
| `apps/web/src/App.spec.ts` | `89aab091d833bc66bd3967f5f038b7440bda034343413f810a032a78e0034e6a` | `5dd88d5096cafae78b6e6c14c01b40ca4fa76fe8ff77c4df038a376a583154d9` | 56,908 → 59,369，+2,461 |

M3 receipt 的其他 9 个路径仍匹配；本候选对这 11 个路径全部零修改。**旧 review 的 all_11_hashes_match 是当时事实，不是当前事实。** 旧 App 两个文件的历史完整字节未包含，不能仅凭 SHA/bytes 定位其语义改动行号；本轮不猜测、不回退、更不声称旧前端测试已覆盖漂移后的代码。可复核表见 `m3_sha_drift.json`。

## 2. 实际 allowlist、首个差异与回退点

### 既有文件仅 4 个发生变化

| 路径 | 首个 diff：原/新行 | 业务改动位置 | 回退点 |
|---|---:|---|---|
| `ops/macos_research_panel_daily.py` | 15/15（新增 import） | 原 loader 566–578；候选 `_load_authority_module` 570–591；ensure 764–895；`_public_envelope` 1317 起；main 1351 起 | 同 ZIP canonical 原字节，先核对 preimage SHA |
| `infrastructure/scheduling/executor_registry.py` | 11/11（新增 import） | `_hk_0_2_runtime_error` 367–412；`_research_panel_daily` 1270–1372 | 同上；不得覆盖 0.2 及其他本地 hunk |
| `ops/run_v35_macos_scheduler.py` | 271/271 | `resolve_due_slot` 内既有 post-close 槽排序 | 同上；不替换 runner 全文件 |
| `tests/test_scheduler_workload_integration.py` | 3/3（新增 import） | 原有 2 个参数化 panel runner fixture 增加 exact receipt | 同上；原断言保留并增加 receipt_verified |

生产源码改动只有前三个文件。以完整 diff 为准，沒有新 scheduler / panel / producer 模块。`a_share_daily_sync.py`、daemon、launcher、runtime catalog、日期/市场/池合同、模型、安全守卫、manager、M3、shared updater 和账户路径均零修改。

### 新增文件（首差异均为第 1 行；回退仅删除 SHA 与本交付一致的新增文件）

`tests/test_v16_panel_takeover_candidate.py`、`tests/test_v16_due_candidate.py`、`tests/test_v16_public_chain_fixture.py`、`tests/test_v16_reader_daemon_candidate.py`；
`verification/scheduler_candidate/fixture_support.py`、`check_preimage.py`、`run_checks.py`；
`README_SCHEDULER_CANDIDATE_ZH.md`、本报告。

新增真实链路及 M3/daemon 测试文件是为完成 PROMPT 的验证要求，属于测试 allowlist 扩展，不扩展生产代码范围。每个文件的 before/after SHA、bytes、首个 hunk 和完整新增清单在 `CANDIDATE_CHANGE_MANIFEST.json`；全量基线在 `BASELINE_FILES.json`。

## 3. 已复现并实施的最小修复

### P1-01：真实动态导入先于 sync 就失败 — 已修复

原 loader `module_from_spec → exec_module` 未先将模块放入 `sys.modules`。真实 canonical A sync 带 postponed annotations 的 dataclass 在本轮 Python 3.13.5 上触发 `NoneType has no attribute __dict__`，没有生成同步摘要。该失败由真实 `python -m ops.macos_research_panel_daily` 复现，不是模拟 updater 的返回值。

仅移入 v16 `macos_research_panel_daily_authority.py:29–49` 的登记/失败恢复语义；不移入整个分拆 authority 文件。正常导入登记实际模块，失败恢复原同名模块/删除半初始化模块。新增真实 dataclass import 和失败恢复用例。此修复没有改 sync 核心、host 轮换、field/history/date 门禁。

### P1-02：公开入口 stdout 混入大同步摘要，被 registry 2,048 字符截断 — 已修复

真实 sync 会打印完整 summary。原 panel 随后再打印大结果；registry `_run` 先截取 stdout 头部，再 `json.loads`，因此成功/失败证据均可能无法识别。

保持原 producer 调用，仅把 authority stdout 送 stderr；公开 stdout 改为单一 compact envelope，保留 v16 header `schema_version/status/overall_status/target_date/lane`，并加 exact receipt bytes/SHA。完整同步结果、错误、文件行和上游细节继续保存在既有 dated receipt；没有截掉磁盘 artifact 来缩小结果。返回码保持 canonical 对 READY/PARTIAL/FAILED 的原有映射，不照抄 v16 将 PARTIAL 返回 0 的行为。

### P1-03：只凭 stdout READY 即认成功 — 已修复

registry 独立用现有 `SafeRoot` 读 `<receipt-root>/<lane>-YYYYMMDD.json`，校验 envelope 日期/请求 lane/安全旗，磁盘字节数/SHA，receipt schema/date/lane/status/三个 false 旗。缺文件、软链接、篡改、错日期/市场、状态或安全旗不符全部失败关闭。没有新增/弱化 owned-path 守卫。

这是**接线层的 exact receipt 绑定**，不是替代 formula/frozen-model/manifest 验证。旧 full-stdout 子进程不能单独与新 registry 混配；必须成对发布并清点其他 stdout 消费者。完整 v16 capture/security-master 绑定仍未验收。

### P1-04：单 lane 被另一市场配置、预算或 backoff 阻塞 — 已修复

panel/registry 按 A 或 HK 要求本 lane 的显式路径。A 的配置、预算和 host 仍使用既有解析和门禁；HK 不解析 A 的预算，也不读取 A selector。显式 A/HK ensure 使用各自 attempt marker；ALL/旧隐式调用的原 marker 兼容保留。A 的 selector/backtest 和 HK exact receipt 校验规则不放宽。

marker 格式变化：显式单 lane 由共享 `after_1700_ensure/YYYYMMDD.json` 改用 `YYYYMMDD-a.json` / `YYYYMMDD-hk.json`。这是兼容性事项；旧 marker 不删除。源码回退时不能假设旧版本识别新增 marker。

### P1-05：HK panel 忽略 launcher 的 `.invalid` 运行时结果 — 已修复

registry 的 panel 路径现在优先沿用显式的 `--hk-0-2-python`/既有绑定（包括 `.invalid`），在任何收集前复用既有 `_hk_0_2_runtime_error`，仍要求精确 3.13.12。没有修改该版本门禁或伪造本环境版本。A lane 不被 HK runtime 缺失连带阻塞。

### P2-01：到期未尝试的 post-close 工作被较早重试挤占 — 有界修复

在已有 `POST_CLOSE_CATCHUP_SLOTS` 内稳定排序：未尝试先于已尝试；各组保留原序，所有 existing claim/backoff/date/calendar 条件仍由原 gate 判定。槽集合未扩展，0415/0515 未加入。该 hunk 只关闭“首次执行被重试挤占”的反例，不宣称复刻 v16 全部 retry-release/fingerprint/fairness 逻辑。

## 4. 实测范围、命令与退出码

环境：Linux / Python **3.13.5**；目标主环境 3.14、HK 3.13.12 均未本机验收。真实 pytdx / pyarrow / futu 未安装；真实资产未包含。临时 SDK fixture 只给子进程供应响应，不是安装真实 SDK，也不会让继承测试的缺依赖案例变绿。

| 验证 | 结果 | 退出码 | 证据 |
|---|---|---:|---|
| 原始 canonical 8 文件基线 | 97 passed / 2 failed | 1 | `baseline.log/.xml/.json` |
| 首批新反例（改动前） | 16 failed / 1 passed | 1 | `red.*` |
| HK runtime 接线反例（改动前） | 1 failed | 1 | `runtime-red.*` |
| 动态 dataclass 导入（修复前） | 1 failed / 1 passed | 1 | `loader-red.*` |
| v16 envelope header 回归（修复前） | 1 failed | 1 | `envelope-header-red.*` |
| 交付新增测试 | **35 passed** | **0** | 最终 portable/replay new 日志 |
| 继承 8 文件复跑 | **97 passed / 2 failed** | **1** | `after-existing.*` |
| portable combined | **132 passed / 2 failed** | **1** | `portable-final/result.json/results.xml` |
| Python AST | 477 文件、零解析错误 | 0 | `static_validation.json`；不等于 3.14 兼容验收 |
| launcher `bash -n` | 通过 | 0 | `static_validation.json` |
| 当前 M3 前端 3 spec | vitest 不存在 | 127 | `frontend-tests.log` |
| 当前前端 typecheck | vue-tsc 不存在 | 127 | `frontend-typecheck.log` |
| 当前前端 build | vite 不存在 | 127 | `frontend-build.log` |

原有 99 个案例 ID 和状态逐项一致。仅修改两个既有参数化 fixture，使模拟子进程除 stdout 外实际写 exact dated receipt；没有删断言、删失败、加 skip 或放宽门禁。两项遗留失败均为 `tests/test_a_share_daily_sync.py` 对真实 `pytdx.errors.TdxFunctionCallError` 的导入失败（原行 280、323）。

最终可复制入口：

```bash
cd <独立候选 v4_app>
python3.14 verification/scheduler_candidate/run_checks.py --suite new --output <全新证据目录>
python3.14 verification/scheduler_candidate/run_checks.py --suite combined --output <另一全新证据目录>
cd apps/web
npm run test -- src/App.spec.ts src/components/review/DailyResearchReviewPanel.spec.ts src/views/ReviewView.spec.ts
npm run typecheck
npm run build
```

runner 使用 `-p no:cacheprovider -o 'addopts=-W error'`，只避开本环境不存在的 Starlette 告警类配置并保留 warnings-as-errors。完整实际 pytest 参数、Python、耗时、退出码均记录在 JSON；没有用 shell 最后一个 echo 的 0 代替测试返回码。

## 5. 集成证据：哪些是真实链路，哪些不是

### A：真实子进程 public → sync → 同步 artifact/receipt，随后因缺 formula 输入失败

`tests/test_v16_public_chain_fixture.py` 运行实际 `python -m ops.macos_research_panel_daily`，动态加载实际 canonical sync，走真实 `run → run_sync → codec/write → file_results.csv/summary.json → a_sync_authority.json`。唯一外部替身是临时 pytdx 响应 fixture；没有替换 panel.main、sync.run、run_sync、写入器或公式 gate。

一个合成文件的既有 9 月 9 日字节保持，追加 9 月 10/11 日两条；重跑时不新增 SDK 请求。未来行、畸形字段和 0.005 秒协作预算耗尽反例均保持原文件，未生成 authority READY 回执。budget 反例 sync exit=124，但公开 panel 把失败映射为 exit=1；二者分别记录。

因 formula/seed 输入未包含，实际 formula wrapper 停止，lane receipt=FAILED，公开 entry exit=1。**file_results.csv 是逐文件同步结果，不冒充 formula panel manifest。** 正向最终 artifact/manifest 验收仍 CANNOT_CONFIRM。

### persistent：真实 daemon → runner/due → registry → 上述子进程 → dispatch receipt

冻结时钟、有限 stop event，原 daemon 连续三次同分钟检查只调度一次；调用真实 runner main、due、catalog、ExecutionLedger、registry 和 subprocess。为隔离本题之外的 hourly 网络工作，在临时 ledger 以原 claim API 预占 sibling；没有更改正式 catalog。

原 A 最小 5,000 文件约束保持：5,000 个合成文件中 4,999 已 current，仅 1 个需要增量；实际 sync reported PASS、updated_count=1、budget=30 秒、fixture.invalid:7710，真实 exact receipt 被 registry 验证。formula 输入缺失导致 scheduler cycle exit=1、dispatch FAILED；daemon 自身生命周期 exit=0 只表示有限循环正常结束，不能当作业务成功。

### HK：真实 public → 现有 collector/pack → 现有 shared updater，缺 frozen assets 失败

临时 Futu fixture 返回 600 个不同代码，原 collector 完成两次 plate union、三批 snapshot，原 pack 写 600 个合成 fixture 文件；实际 shared updater 脚本和 `shared_data.hk_0_2` 被执行。缺少真实冻结模型/面板资产，未发布正式 panel/manifest；HK lane FAILED、entry exit=1。用的是真实当前 3.13.5 解释器加测试审计 wrapper，**不是 HK 3.13.12 环境证明**。registry 的真实 3.13.12 门禁未绕过；直接 public 负向测试与 registry runtime 测试分开解释。

### M3：实际路由的进程内 HTTP 读取，不是 live API / UI

仅装配 read-only review router 的 FastAPI/TestClient，不装配账户 app/lifespan。合成 exact-date JSON 经 `/api/v3/review?date=20260911` 返回 200；8 个必需 section 全等，breadth 14 字段、feedback 35 行、themes 10、events 19（11/5/3）、focus 5 字段、嵌套 receipt 和 CANNOT_CONFIRM 均保留，源文件字节零变化，原 A/H envelope 仍在。缺文件、latest-only、错日期、坏 JSON 均失败关闭。

这不是旧 75,324 字节真实 artifact 的重新验收，更不是浏览器全展开测试。`research_review_generation` 仍 **UNREVIEWED / REFERENCE_ONLY / NOT_INCLUDED**；generator owner 保持 CANNOT_CONFIRM，不接入写者，不停止旧生成器。

## 6. 未关闭的缺口与明确停点

1. v16 `ops/daily_materialize.py` 的首个跨 stage/research-day 依赖 `ops/materialize_research_day.py` 未独立审查，canonical 无该文件。紧接的 strict `stage_acquisition_universe_contracts.py`、`stage_acquisition_universe_commit.py` 等也未纳入。不能通过拷贝旧树“解决 import”而默认批准其行为。
2. 本候选未迁移/放宽 v16 accepted-only、trusted-CAS、HK capture/security-master 与 panel 字节绑定等完整行为闭包。canonical 的原 gates 保持，不等于已证明与 v16 等价。全量 producer takeover 仍不放行。
3. A formula、本机 selector/backtest seed 与指针、frozen HK assets、formal manifest 和真实共享数据根 NOT_INCLUDED。无从验证最终正向 artifact/manifest、公式兼容或真实来源历史，不制造这些证据。
4. HK 缺上游后重试的 capture 复用、所有旧 stdout 消费者、新旧 producer 所有权仍需实际盘点；本轮不能据单次 fixture“没有重复取数”外推所有故障恢复场景无重复抓取。
5. 旧 owner/worker 的崩溃恢复、真实 wake/natural slot、macOS kernel/解释器、真实 SDK 服务行为没有本轮证据。预算验证仅为协作式传参和有限响应下不再写入；不声称能硬杀不可中断线程或整个子进程树。
6. M3 两个当前前端 SHA 漂移且依赖缺失；当前前端 test/typecheck/build 以及 live API/UI 均 CANNOT_CONFIRM。不得沿用历史 38 tests/build PASS。

| 层级 | 本轮状态 |
|---|---|
| IMPLEMENTED | 本报告 allowlist 内最小 hunk 已实现 |
| TESTED | 新增 35 通过；继承缺 SDK 的 2 项失败保留 |
| REVIEWED | 本轮源码/差异/反例复核；不冒称独立第二审核人验收或全系统通过 |
| INTEGRATED | PARTIAL：真实链路参与的离线负向回归；正向完整 artifact/manifest CANNOT_CONFIRM |
| DEPLOYED | CANNOT_CONFIRM / NOT_PERFORMED |
| API_VERIFIED | live CANNOT_CONFIRM；仅进程内路由 fixture 200 |
| UI_VERIFIED | CANNOT_CONFIRM |
| NATURAL_VERIFIED | CANNOT_CONFIRM |
| 旧服务退役 | NOT_AUTHORIZED / NOT_PERFORMED |

## 7. 停旧服务的全部前置条件（本轮均不执行停服）

必须先冻结并复核新 immutable release 的源码、依赖、真实运行参数与 source/dist/manifest SHA；当前 App SHA 要重新前端测试、构建、浏览器完整展开验收。不能把本候选源码包当作已经完成的 release manifest。

随后在独立可写验证根，使用真实被授权的只读输入，取得 A/HK **正向** public → authority → exact artifact/manifest/receipt 全链及失败恢复证据，保留日期/池/strict protocol/field/history/CAS 门禁。主解释器 3.14 和 HK 3.13.12、host、预算、外部公式/field contract/updater 的代码哈希必须绑定到同一配置；不得混用老 mutable 脚本。

闭合本报告第 6 节的跨 stage 缺口并审查全部旧 producer/消费者；证明只有一个 scheduler owner、每个数据产品只有一个 producer/shared authority，新旧无并行写入、无重复抓取。当前 `research_review_generation` 未验收，**其旧 generator 不在可退役名单**；账户/8910 也不属于本次退役范围。

最后才可由用户另行授权操作：记录旧 PID/子进程、在途任务、锁、调度回执和各根/指针状态，等待安全排空并冻结旧服务绑定；完成真实 wake、重启、重复分钟与 missed-slot 验证后才裁决停旧/启新。任一步缺证据，保持旧 owner，不让本候选并行写正式根。

## 8. 回退绑定与方法

配置证据记录的旧 release 是 `20260913-a-panel-entrypoint-fix-v16`，release manifest SHA `87e9a37c2b216133d879c679de90287fcd63b55978fd632d750c93e03cebf070`，scheduler plist SHA `799d5529a017e17eb7790070e37b76d13244367d27274f3ac1956deb05db80bf`。这些仅是交接时观察值，操作前必须重新核对，不能据此声称现在活动状态相同。

源码回退：先以 `check_preimage.py --mode after` 确認没有用户后续改动，再 `git apply --reverse --check`；通过后才在**隔离工作树**逆向应用。新增文件仅在 SHA 与交付一致时删除。不得整包覆盖 App，也不得改写旧已审 receipt 的 expected SHA。

运行回退（仅未来经另行授权）：先停新 owner 并确认无在途写入/子进程，再恢复经复核的旧 immutable release、旧完整 env/plist/解释器/共享根及 manifest 绑定，最后恢复旧唯一 owner。不要让两个 scheduler 并行；不要批量覆盖或删除新生成的 artifact、失败 receipt、lane attempt marker。旧版不认识新单-lane marker，须以 authority 的实际 exact-date 后置条件和归档回执对账，不可假设删 marker 就安全。

本轮没有操作任何运行服务或正式数据，因而实际需要的回退仅是候选源码补丁逆向验证。补丁正/反回放及逐文件比较证据随包提供。
