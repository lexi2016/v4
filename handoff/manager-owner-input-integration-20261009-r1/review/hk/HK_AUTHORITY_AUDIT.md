# HK Connect / Oversold authority 接入独立审查

## 当前结论

冻结的两个失败不是已证明的 reader 接线缺陷：

- `HK_CONNECT_TARGET_AUTHORITY_ROOT_NOT_BOUND` 来自 `connect_selection.read_scope` 在读取任何证券工件之前发现未配置 `V4_MANAGER_UNIVERSE_ROOT`。当前 R2 具有完整的目标日 V2 authority reader，显式绑定合格的同根字节链后可读取 `OWNER_VERIFIED` membership。
- `SCREEN_SECURITY_MASTER_READ_FAILED:HK_SECURITY_MASTER_EXACT_DATE_ENTRY_MISSING` 表明当前读取的 security-master 索引缺少请求日 `20261008`；与缺索引、损坏 metadata、SHA 不符有独立诊断。当前 R2 已通过 `create_app` 配置把 screen authority root 接入 service，再传给 `read_rebound_screen`。不得由“20261009 entry 存在”推断“20261008 可用”。
- 补齐 master/panel 不等于完成 Oversold 选股。当前成交量 provenance 合同明确保持 `NOT_PROVEN`，完整数值也须进入 pending。要获得严格候选或证据完整的空选股结果，需原 owner 提供被正式 reader 合同支持的全六日单位/scale 证明；现有源码没有接受任意额外 manifest 字段的升级路径。

没有为这两项冻结失败改写生产源码；环境绑定与真实输入必须由原 owner 确认。另一个跨 HK/Plan 的问题已由 Plan reviewer 独立复现：`filter_cards` 的 `membership_source` 保留 `read_at`，会污染材料 input identity；该 reviewer 复用本审查的完整 synthetic V2 字节 fixture、真实原 master writer 和 ResearchArchiveStore，在 source bytes 与 scope identity 不变、只变读取时钟时观察到 HTTP GET 从 CURRENT 变为 STALE。修复与独立回归由根任务及 Plan reviewer 管理，HK 审查没有修改该生产文件。这不证明本包所报 `ROOT_NOT_BOUND` 或 `EXACT_DATE_ENTRY_MISSING` 是代码错误。

## 源码身份与执行边界

- 固定基线 commit：`a7f5d09fb19de10564925757207977aadc080cc1`。
- 固定 R2 release manifest SHA-256：`f6385dd23e9fda4d2169f20d6dc68b6e1e519b2b1a35e1ceb0bfd3111a079ad5`。
- 附件 R2 source root 的原始身份：`/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_THREE_CHANNEL_DEPLOY_20261009/candidate/three_channel_release_r2/app`。这是固定候选身份，不是本机活跃进程。
- 本次执行根：`/workspace/scratch/0e089a11ee60/four_function_gaps/work/baseline/app`。20 个附件 R2 文件覆盖在逐 Git blob 核验的 a7f5d09 依赖快照上；具体来源由根任务 `work/support_provenance.json` 记录。
- 逐文件 SHA 见 `source_sha256.json`。本审查没有改这些生产文件。
- 实际 Mac owner state、真实证券数据、部署进程、API 网络端口、浏览器和自然时段均未访问，保持 `CANNOT_CONFIRM / NOT_RUN`。
- 独立实验只写 pytest 临时目录；测试脚本对 socket connect、DNS、create_connection 禁止联网，并在读取前后核验 synthetic authority 文件 SHA 不变。

## 已有接线合同

| 入口/配置 | R2 实际解析顺序 | 消费位置与用途 |
|---|---|---|
| `V4_MANAGER_UNIVERSE_ROOT` | 必须显式设置；不回退到 master、Stage 或 `shared_data_root` | `connect_selection.py:73–106`；读取 `universes/20261009/HK_CONNECT_FULL_MARKET.json` 与同根 V2 authority 链 |
| `V4_MANAGER_UNIVERSE_OWNER_ROOT`、`V4_MANAGER_UNIVERSE_OWNER_SHA256` | 两项都必需，绝对原 owner 根与 `stage_center/hk_universe_preflight.py` 的 SHA 必须匹配 | `connect_selection.py:86–106` → `domains/manager_research_evidence.py:52–105,279–301` |
| `V4_MANAGER_SECURITY_MASTER_ROOT` | 此环境值优先，否则 `create_app(shared_data_root=...)`，再否则 `None` | `app.py:5253–5255` → `service.py:327,350`；用于既有 material/master/close 链 |
| `V4_MANAGER_SCREEN_AUTHORITY_ROOT` | 此环境值优先，否则 `V4_MANAGER_SECURITY_MASTER_ROOT`，否则 `shared_data_root` | `app.py:5256–5260` → `service.py:328,351` → `workspace.py:724–727`；同一 root 读取精确日 panel 和 master |
| `V4_MANAGER_HK_CAPTURE_RECEIPT_ROOT`、`V4_MANAGER_HK_DISPATCH_RECEIPT_ROOT` | 可选，target V2 读取失败后作为上一完整 session 的来源证据读取 | `connect_selection.py:130–140`；结果只挂到 `previous_session_capture`，不授予目标日资格 |

设置 HK master root 不会顺带设置目标日 universe root；两者属不同合同，禁止通过猜测进行跨合同根回退。screen root 可以显式不同于通用 master root，但一个 screen 调用仍从其自己 root 读取 panel 和 exact-date master，不能拼装未经 owner 确认的跨根来源。

## HK Connect：owner 到 daily channel

1. 原 producer 身份是 `v35_dispatcher.research_panel_daily_hk`，capture 代码合同指向 `ops/_macos_research_panel_daily_parts/hk_market_capture.py`；原纯合同 owner 为 `stage_center/hk_universe_preflight.py` 中 `validate_captured_hk_connect_membership_v2`（602）及 `build_captured_hk_connect_authority_v2`（765）。本次没有调用采集器。
2. V2 reader 在 `domains/manager_research_evidence.py:136–276` 读取并逐字节核验 artifact、manifest、receipt、current、capture 和 publication；目标日期、market、full-market scope、双板 capture、producer forward-source hashes、contract owner SHA、run id 和链身份都须一致。
3. reader 检查 acquired/publication 时间同目标日且 available 不早于 acquired，也不晚于真实读取时钟（252–262）。`connect_selection.read_scope` 再检查 acquired 和 available 都不晚于 plan 的 `research_cutoff`（108–114）；不把 plan cutoff 注入为假采集时钟。
4. `scope.identity = digest([target_date,codes,source.sha256])`（118–121）。`_scope_error`（144–166）重新验证 exact-date V2 语义和 identity；`filter_cards`（169–193）只保留该 authority 中的 HK symbols。
5. `workspace.get_workspace` 通过原 `read_scope`（698）→ filter/gate（706–768）→ `selection_diagnostics`（844–845）接入工作台。`build_daily_channels`（140–169）仅投影原 focus stock，不会由全市场 member list 自动制造候选。
6. 即使 membership 已验证，缺少原 focus 输入仍是 `PARTIAL`；成员数量为正不是选股完成。无来源且零行必须保持未知计数，不能 `READY_EMPTY`。

`connect_capture_adapter.read_d1_scope`（160–357）验证同日 capture/master/dispatch 原链，保留真正 `source_date=context.market_session`。R2 `read_scope` 没有把它升级为 target authority；`_scope_error`（160–161）明确拒绝 `EXACT_PREVIOUS_FULL_SESSION_CAPTURED_CONNECT_CODES`。旧 `tests/test_manager_connect_capture_adapter_r4.py:183–208` 的 D1 替代 target-V2 期望属于旧合同，不可据此修改 R2 生产行为。

## Oversold：date / master / panel / volume

`workspace_plan.plan_context`（18–99）按原 HK securities 日历选 planning price session。`screen_context`（101–155）另按 cutoff 求已完成的完整 HK session；盘前/盘中使用已完成前一日，目标日收盘后才可前移到目标日；半日不冒充完整成交量比较日。`verified_session` 是该要求读取日，在失败 envelope 中不能解释为数据已被验证。

`read_rebound_screen`（977–1052）顺序为：screen context → required 60/5 session 校验 → exact-date HK02 panel witness → exact-date master → master cutoff → volume evidence → 数值读取和原两道筛选。

### Panel

`_read_hk02_panel_witness`（217–557）从 `assets/hk_0_2` 验证 `panel_max_date`、v2 schema、source_contract、安全 flags、路径、panel SHA 和 `manifest_prepared_at<=cutoff`。`panel_latest.json` 可以已指向后续交易日；reader 仍只选择请求目标日的唯一已验证 immutable revision。相同目标日 recovery 必须有 parent digest、所需 history session 和 cutoff 证据；多个 eligible revision、篡改或未来准备时间均不选。此逻辑不是“latest 日期回退”。

### Master

`_screen_security_master_witness`（633–640）明确导入附件的 `upstreams.v3_shared_data.shared_data.hk_security_master`，避免另一个同名 shadow package。

`load_verified_hk_security_master_snapshot`（289–391）一次读取 `assets/hk_security_master/latest.json`，严格索引 `entries[requested_trade_date]`；此文件名称虽叫 latest，却是按日 entry 的索引。不存在目标 entry 时在 328–329 直接报 `HK_SECURITY_MASTER_EXACT_DATE_ENTRY_MISSING`，不遍历其它日期或 runs。之后验证 manifest/receipt schema、同日/run/safety、artifact bytes SHA、manifest canonical SHA 和行数；witness 保留同一批已验证 bytes 的路径与 SHA。screen 再在 1035–1041 验证 master captured_at 不晚于 cutoff。

既有 owner 支持 `publish_hk_security_master`（96）及 `restore_verified_hk_security_master`（198）。后者只能由 owner 在其已确认迁移/恢复范围内复用同一精确日、同一不可变 bytes，不能改日、不采集、目标日存在冲突 run 就拒绝。首选绑定已有权威 root；Chat 本次没有执行业务发布或恢复。

### Volume 的真正剩余能力缺口

`rebound_native_evidence`（766–849）接受的 native observation v1 只证明原始字段和增量读取时间，明确声明单位与继承 history scale 为 `NOT_PROVEN`。`_screen_panel_volume_evidence`（920–962）与 `_screen_supplement_volume_evidence`（965–974）都返回 `status=NOT_PROVEN`；代码 953–955 指明未来原 owner attestation 需要显式 reader-contract 改动，任意额外 manifest 字段无效。

因此本次合成的完整 master、61 session panel，数值恰好达到两道阈值时，仍只能到 `READY_WITH_GAPS`、一条 pending、零个 strict/near，不能宣称完成选股。`read_rebound_screen:1207,1295–1298` 只有 `OWNER_VERIFIED` volume evidence 才允许 volume gate 成为已知值。`workspace_daily_channels:172–195` 保留 pending→PARTIAL、候选计数未知。没有原 owner 的正式新证明合同，不应为了获得绿灯放宽此门槛。

`hk_d1_evidence.read_verified_hk_d1_evidence`（14–75）读取另一条历史 D-1 change map；R2 manager `read_rebound_screen` 没有调用它。它的 latest/prior-date 逻辑不能借来替换严格 screen master/panel 的日界。

## 行为验证记录

脚本：`test_hk_authority_app_wiring.py`。所有 frame、来源摘要和股票代码都是明确的 synthetic fixture；调用的是原 V2 纯序列化合同与实际 domains/read_scope reader，不 mock authority 结果。

第一轮旧 runtime 的 pytest 初始化被缺少 Starlette 阻断；用 `-c /dev/null` 运行纯 reader/day-channel 子集得到 25 PASS。这是隔离实验环境诊断，不是生产失败。

冻结 runtime：`/workspace/scratch/0e089a11ee60/four_function_gaps/runtime_locked/bin/python`。根任务已逐项核验 31 项 uv.lock 依赖；Python 3.12.14 与项目 `>=3.14` 的差异保留为验收限制。

首轮合并运行记录：`hk_authority_initial_test_result.json` 与 `hk_authority_initial_pytest.log`。33 PASS；4 FAIL 均在 `create_app` 导入前触发 `ModuleNotFoundError: stage_center._selection_parts._namespace`，属于离线依赖 snapshot closure 缺项。根任务随后把通用原 `_namespace` helper 按原 bytes 置入缺失 import 位置，另补原 `ops/daily_materialize.py`；`work/import_support_adaptation.json` 明确标为 `ISOLATED_TEST_IMPORT_SUPPORT`，不是生产 diff 或 Mac 源码身份认定。

第二轮运行记录：`hk_authority_appwired_test_result.json` 与 `hk_authority_appwired_pytest.log`。仍为 33 PASS、4 FAIL，失败前移到 `app.py:5165`：附件 `create_app` 传入 `create_review_router(hk_close_root=...)`，但补充的 Git 基线非 Manager `review_router` 签名不接受该参数。这是附件 app 与离线支撑文件的不兼容，不是 HK authority bug。HK 审查未替换此 router，也未修改生产源码；原错误完整保留。

根任务随后从同一固定 commit 取回对应 `review_router`、API `research_attention` 与原 manager package initializer；三个文件均按 Git blob/文件 SHA 验证，记录于 `work/api_support_alignment.json`。未 wrapper/stub router、Stage、owner 或 manager reader。支撑对齐仅供隔离测试使用，不宣称 Mac 此刻使用同样的组合。

**最终对齐运行：37 PASS，2.89 秒，exit code 0。** 原始输出为 `hk_authority_aligned_pytest.log`；完整命令、cwd、环境、测试源码 SHA 与支撑 provenance 为 `hk_authority_aligned_test_result.json`。11 个被审查生产文件在运行后 SHA 与 `source_sha256.json` 一致，无 HK 源码改动。

其中 3 项通过 `create_app` 实际构造的 service 验证 root precedence；第 4 项在实际 `_v4_manager_research_runtime.service.ManagerResearchJobService` 上运行 `get_workspace`，消费真实 reader 验证的 synthetic V2 六工件和 exact master/panel。它验证 app 注入路径及 workspace/channel 行为，没有监听服务端口、没有浏览器，也不是 Mac 真实 API/UI 或自然时段验收。

已通过的行为包括：

- 精确目标日完整 V2 六工件链读取为 `OWNER_VERIFIED`；原 focus 经同一 membership gate 进入 daily channel，仍保持所有研究安全 flags。
- 未绑定根、只存在上一日工件、缺 owner SHA、错误 owner SHA、缺 publication SHA、改动 manifest、publication 晚于 cutoff 均拒绝，零行保持未知，工件 SHA 读取前后不变。
- 精确 `20261008` master 与较新 `20261009` entry 共存时，reader 使用前者的 exact run；缺前者时不回退；同日 index 移动时 witness 保留一次读取的 bytes。
- 正确 master/panel 抵达原 screen，但缺成交量证明保留 pending；错误 receipt date/safety/checksum 与晚于 cutoff 的 master 不被消费。
- Daily channel 不把无数据的零行标成成功空结果，不继承不相关 US attention gaps，且不能用不完整 attempt 宣称自然时段成功。
- 实际 `create_app → service.get_workspace` 中，已验证目标 membership 为 `OWNER_VERIFIED`；20261008 的 exact master run 被读取，20261009 较新 entry 未替代；screen 为 `READY_WITH_GAPS`，pending=1，strict/near 仍空；daily HK 为缺原 focus 的 `PARTIAL`，OVERSOLD 为缺单位证明的 `PARTIAL`，`candidate_count=None`。全部 authority 工件 SHA 前后不变。

## Mac 原 owner 最小接续

1. 确认实际 V4 API 源根、运行身份及该进程的上述环境配置；不能以附件候选根或本机实验根替代现役身份。
2. HK Connect owner 明确目标日 `20261009` 的 V2 authority root，以及 contract owner root/SHA；原六工件和 capture/publication 时间须可重读且都满足研究 cutoff。已有合格输入直接绑定原 reader，无需新 collector。
3. Oversold owner 在已确认 screen root 中确认 `20261008` 的 master entry、原 manifest/receipt/artifact 与对应 panel、60/5 日历史；没有则由既有 owner 补来源。保留 provenance，无 latest 回退、重贴 D-1 标签或跨市场混用。
4. 单独解决 volume attestation 的原 owner 能力/合同缺口。只有 exact master 的修复不能记作严格选股完成；当前应继续 `PARTIAL` 或 `CANNOT_CONFIRM`。
5. 输入固定后由既有 `ManagerResearchJobService.refresh_workspace_plan` 原 owner 重建；通过同一个 `create_app` 注入实例 GET readback，核对 target/date pair、run/product/input SHA。输入变动继续 stale，不能绕过 identity guard。

候选代码、独立 synthetic 回归、实际 owner 输入、集成/部署、真实 API/UI 与自然时段验收应分别记录。
