# 公告原 owner 链路候选修复

## 结论与证据边界

已完成两个可复现的原链路代码断点修复，以及正式 Reader／Reviewer 身份校验缺口修复。新增的 20 个 synthetic regression 全部通过；最终连同独立审阅者的两项公告边界复现为 **22 PASS**。此前在新增 19 项版本并行运行原有公告 parity 文件后的真实结果为 **57 PASS、1 FAIL**；这个 FAIL 在未修改的组装基线上也可复现，完整保留，没有改断言、加 skip、加 xfail 或降低 pytest 默认校验。

实际业务日期为 target trade date `20261009`、publication date `20261008`。问题包 `../reference/problem/evidence/announcement_projection.json` 仍是本轮真实历史结论：已检查证据中未见 original capture、正式 Reader、不同 identity 的正式 Reviewer、imported product；历史 first break 仍为 **CANNOT_CONFIRM**，不能将下面的源码缺陷认定为该历史运行的已证首因。该 projection 引用的原 evidence SHA 为 `9ec9d0f6357b081702567dc3ba481602edc3f0d5764a68e14de5d6965024fe85`。

未部署，未启动或重启服务，未修改计划任务、binding、业务 state 或交易门禁，未采集或导入真实公告，未制作任何真实 Reader／Reviewer 结论。所有测试材料和 fixture reviewer 都明确为 synthetic，并仅存在于本轮临时目录。

## 源码身份

- 问题包运输源：`lexi2016/v4`，固定 commit `b19eb112bd641ca97cac1246af7c81d8873641f4`。
- 包中要求的冻结 R3 candidate ref：`ca01c4d0260fecf7aae3c89e96899f36901bf8f7`。
- 本轮测试副本：`/workspace/scratch/21926b793c00/three_channel/app`。
- 本地组装比较 HEAD：`7ca0190a721a7fd0fc0c88b79a872889867d111f`。这是本地比较身份，不是部署身份，也不等同于把上述运输 commit 当作现役源码。
- 本轮公告修改只涉及下表三个路径。没有修改 cycle、service、页面、A/HK owner、BUY、Stage 或 Vibe。

| 路径 | before SHA-256 | after SHA-256 |
|---|---|---|
| `ops/run_manager_daily_announcement.py` | `bfb853fb982e0b2da1024fa942ae9dc5d67fa88a8d112f46054608641129c1ee` | `aee0e5c31f30b296864a7ad81263fbc748b65cb9b4d443f83a756019cbc94a38` |
| `v4/manager_research/workspace_announcements.py` | `ea259666727b71c78760d666f3fe7f90350829bdce5f2b55745927528546af04` | `82187a190f2a308cc193473a9583f0c8edb82782ce45217a1dce8c866f172f0b` |
| `tests/test_manager_announcement_handoff_20261009.py` | 新增，无 before | `dd38c69af5230927d59f4c10ec375b41506999663a623da278a76c14a101dfe2` |

运行时为 Python `3.14.6`，pytest `9.1.1`、FastAPI `0.141.1`、Starlette `1.6.0`、httpx `0.28.1`。具体解释器为 `/workspace/scratch/a154a3323e32/test_env/bin/python`。新增测试复用未修改的既有 synthetic helper `tests/test_manager_announcement_parity_20261008.py`，其 SHA 为 `22fccef9d1904c2ea0f52f645e4810cef876574bb8574722109fa37f0a29b4ed`。

跨通道用例另复用 `tests/test_manager_us_mapping_three_channel_20261009.py` 的 synthetic `owner` fixture。该 US 测试文件最终交付版本包含 11 个参数化用例，SHA 为 `9f7f1a3f73a539b470ba18a1ec029360c77734de21015895d73bc03cdcc1fd2a`。此处核对的是最终依赖版本；US 文件自身的 11 项不计入公告 20 项及两项独立公告边界复现的 22 项结果。

## 原链路逐段定位

| 原链路阶段 | 源码和本轮结论 |
|---|---|
| Trigger | `ops/run_manager_announcement_cycle.py` 中既有 worker 调用 `service.refresh_announcements(..., schedule=...)`，属于原公告增量 owner；文件清单包含 daily bridge 不等于它已被执行。独立 daily bridge 的 `capture` 子命令显式 POST 原 date-catalog API，再 GET 精确日期目录。问题包没有该历史 trigger／capture 证据，是否实际触发仍 CANNOT_CONFIRM。本轮未增设 trigger 或第二 producer。 |
| Capture | `ops/run_manager_daily_announcement.py::_capture` 调用原 `ops.manager_announcement_body_batch.run_capture`，后者在原 MaterialStore 和证据目录写入 source-bound 正文。已证 JSON 重排会破坏其字节绑定，见缺陷 1。 |
| 正式 Reader | 原入口要求外部 Reader 提供 `semantic_catalog`，原注册器把其原始字节保存为 `semantic_catalog.json` 和 `reader_output.json`，不自动生成语义判断。已补齐非空 Reader identity 校验。 |
| 不同正式 Reviewer | 原入口要求单独 `reviewer_output`，已有 schema、PASS、日期、run、decision SHA、catalog／semantic／body SHA 核对。本轮补上首尾空白等价 identity 的拒绝，保留原始标签和大小写。字节绑定仍只证明 declared lineage，不证明平台账户认证。 |
| Handoff／import | 原 `_register_handoff`、`validate_registered_handoff`、原 analysis import API、原 owner receipt 持续使用既有完整合同。缺 capture、Reader 或 Reviewer 文件时，CLI 在 owner POST 前拒绝。既有完整产品 import validator 未放宽。 |
| Workspace 消费与 CLI readback | 原 API 和 workspace 都通过 `read_analysis_consumption` 重新验证完整 artifact 链；此路径在 synthetic exact-pair fixture 下已验证。另已修复 CLI 把摘要冒当完整产品校验的错误，见缺陷 2。没有修改 workspace 布局或消费者算法。 |

## 缺陷 1：fresh capture 重排正文 JSON，破坏原 producer SHA

原 body producer 的 `json_bytes` 用 compact JSON（`separators=(",", ":")` 加换行）保存 `body_corpus.json`、`body_corpus_manifest.json`、`batch_receipt.json`。其中 batch 保存正文和 manifest 的原文件 SHA，正文也保存 manifest SHA。原 daily `_capture` 读取这些 JSON 后用 `_write_exclusive` 以 `indent=2` 重新序列化到固定 evidence 路径，导致 JSON 值相同但文件字节和 SHA 不同。

未修改源码的实际 synthetic capture 已产生这种不一致：`red01.log` 的第一项在字节相等断言处失败；针对同一 fixture 调用原 terminal validator，得到 `ANNOUNCEMENT_BODY_CAPTURE_RECEIPT_BINDING_INVALID`。原 producer SHA 和转存后 SHA 完整保存于 `red01_terminal.json`。

最小修复是 `_capture` 复用已有 `_copy_json_bytes`，按原固定文件名复制这三个文件的原字节。没有替换原 capture owner，也没有改写 producer manifest、重算来源身份或放宽 validator。原 resume 代码已经采用字节保留策略，因此未改动 resume。

修复后，新测试使用真实 owner catalog 路由、真实 catalog/body producer、真实 MaterialStore、真实注册器、真实 import 路由和真实 workspace 消费者。仅底层 transport 和时钟是 synthetic。总计三个 synthetic source response：目录第 1 页、terminal empty page、正文第 1 页。随后正式 fixture Reader 和不同 fixture Reviewer 绑定该精确输入；import 与 workspace 的 product SHA、handoff SHA 一致，workspace 状态为 `CONSUMED`，研究引用为 fixture `HK.01234`。所有 GET 前后目录文件 SHA 快照相同，未新增采集。

## 缺陷 2：CLI readback 把 analysis 摘要传给完整 product receipt validator

原 `_readback` 仅组装 `target_trade_date`、`publication_date` 和 `sha256` 三个字段，然后调用 `validate_owner_analysis_import_receipt`。新的合法 owner receipt 含 `source_manifest_sha256`、`evidence_run_id`、`handoff_manifest_sha256`、`agent_judgment_receipt_sha256`，完整 product validator 必须对照真实 `agent_judgment_receipt`。API 的 analysis 是投影，不含这个原始 judgment，因此一个成功导入且完整消费链已通过的结果仍会报 `ANNOUNCEMENT_OWNER_IMPORT_RECEIPT_HANDOFF_BINDING_INVALID`。`red01.log` 第二项完整保存了该失败。

修复新增专用 `validate_owner_analysis_readback`，要求 API 返回的 `consumption_validation` 已通过完整链路检查，并把它与原 owner receipt、日期、product、source manifest、catalog/source run、evidence run、handoff、judgment、owner receipt SHA 逐项绑定。仍检查 receipt digest、时间、owner、父任务字段和研究安全 flags。CLI 不再伪造一个不完整的 product；原 full-product import validator 原样保留其完整绑定要求。

八个篡改／缺失分支测试验证：缺 consumption、consumption 不可确认、product SHA、source manifest SHA、evidence run、handoff SHA、judgment SHA、owner receipt SHA 不一致均拒绝。合法新 receipt 通过；合法 legacy receipt 在当前 handoff 已被原消费者验证的条件下通过，并保持磁盘字节不变。

独立审阅另复现了 legacy 投影缺 catalog SHA／run 时 `None == None` 可错误通过的问题。补充最小修复要求原 API 的 consumption schema，并验证 catalog／handoff／judgment SHA64 和 source／evidence run32 的完整形状；其 RED 保留于 `../independent_review/boundary_checks.log`，原复现 `test_cli_rejects_verified_projection_without_catalog_run_and_digest` 在最终版本通过。关闭检查另发现对 identifier 使用 `str(...)` 会允许数值类型的 64 位 catalog SHA 通过；`../independent_review/boundary_closure_checks.log` 保留此 FAIL。最终五个新 chain identifier 均先要求原生字符串类型，再执行正则校验，不做类型强转；真实 API fixture 的数值 catalog 反例 `test_legacy_readback_rejects_numeric_catalog_identity` 也已通过。完整 import validator 未改动。

## 缺陷 3：Reader identity 空值或仅首尾空白不同可通过独立审阅检查

原 judgment validator 对 Reviewer identity 做非空字符串校验，却未把 Reader identity 加入同一校验。`None`、空字符串和纯空白 Reader 标签都能进入原始成功分支。两个 validator 原来又仅比较原字符串，所以 `synthetic-reader` 和 ` synthetic-reader ` 可以注册成“不同”Reader／Reviewer；此问题由实际注册器和保存 judgment 两个路径分别复现，保存在 `red_whitespace01.log`。

修复要求两者是非空字符串，并只在判断是否相同时对首尾空白作 `strip()`。注册器和消费校验同步拒绝空白等价 identity；未做 case folding、未更改已有输出标签、未假装获得平台 identity 认证。所有真实独立 Reader／Reviewer 的存在性与执行仍须本机取证。

## 定向验证的实际结果

完整命令、cwd、退出码、计数和日志名在 `test_commands.json`。默认 `pyproject.toml` pytest warning policy 保持不变。

| 记录 | 实际结果 | 用途 |
|---|---|---|
| `red01.log` | 2 FAIL | 修改前：fresh capture 字节破坏；合法 bound receipt readback 失败。 |
| `red02.log` | 13 FAIL | 修改前：上述两项、8 个完整链路错误分类、3 个缺 Reader identity。 |
| `red01_terminal.json` | 原 terminal validator 明确拒绝 | 独立记录原字节 SHA 不一致及 binding 错误。 |
| `green_capture01.log` | 1 PASS | 仅 capture 字节修复后，原 capture→handoff→import→workspace 全链 synthetic 成功。 |
| `green01.log` | 13 PASS | readback 与非空 Reader identity 修复后。 |
| `red_whitespace01.log` | 2 FAIL、17 deselected | 首尾空白等价 identity 修复前，实际 register 与 saved judgment 两条路径均错误通过。 |
| `new_final01.log` / XML | 19 PASS，退出 0 | 跨通道复验加入前的新增测试版本。 |
| `cross_channel01.log` | 1 FAIL，退出 1 | 首个跨通道 fixture 未提供 US reviewed／registry JSON，实际 US preparation 为 FAILED，未改断言为成功。 |
| `new_final02.log` / XML | 1 collection ERROR，退出 2 | 直接导入 US fixture 触发缺失的 eager scheduling 闭包；不是业务回归结果。 |
| `new_final03.log` / XML | **20 PASS**，退出 0 | 复用 US synthetic fixture 和既有 scoped namespace runner 后，包含 US 缺输入时公告仍可消费。 |
| `new_final04.log` / XML | 21 PASS，退出 0 | 20 项新增测试加第一项独立公告边界复现。 |
| `new_final05.log` / XML | **22 PASS**，退出 0 | 最终 20 项新增测试加两项独立公告边界复现；涵盖 schema、缺失和数值类型 identifier。 |
| `scoped_final02.log` / XML | **57 PASS、1 FAIL**，退出 1 | 当时的新增 19 项及原有 parity 39 项；保留既有失败，不能把该旧计数冒称最终 20 项版本的完整 companion 运行。 |
| `baseline_failure01.log` | **1 FAIL**，退出 1 | 从未修改的比较 HEAD archive 重现同一既有失败。 |

最终跨通道测试复用 `tests/test_manager_us_mapping_three_channel_20261009.py` 的真实 schema synthetic reviewed／registry 文件和原缺输入 read adapter，不补造 runtime JSON；固定两边时钟后，POST `/workspace/refresh` 明确记录 US `INPUT_MISSING`，同时公告仍 `CONSUMED`，ANNOUNCEMENT 通道 `READY`、candidate_count 1，原 product／handoff SHA 写入保存计划，原 evidence／product 字节不变且没有追加 source 调用。

在直接导入该 US fixture 时，现有源码闭包的 `infrastructure.scheduling` eager import 触达未导出的 `ops.daily_materialize`，产生 `new_final02.log` collection ERROR。最终沿用既有 `tests/r3_scoped_loader.py`，仅注册真实目录的 namespace 并补齐正常 parent attributes，再执行 pytest；不提供任何缺失 implementation。这是 scoped source verification，不是完整 Mac 原生 import 验收。默认 pytest warning policy 保留，最终 runner 显式关闭第三方 plugin autoload。

每次 pytest 运行均有 1 条环境既有 `StarletteDeprecationWarning`（Starlette 1.6 的 httpx TestClient deprecation）；未安装替代库、未屏蔽项目未屏蔽的 warning。

保留的既有 FAIL 为 `tests/test_manager_announcement_parity_20261008.py::test_missing_original_archive_is_not_empty_connect_selection`：期望 `selection_diagnostics.status == READY`，实际 `PARTIAL`。未修改的组装 baseline 上实际 diagnostics 包含 `ANNOUNCEMENT_INPUT_NOT_READY`、`US_MARKET_MAPPING_INPUT_NOT_READY`；fixture 中 formal Connect calendar 也为 `HK_CONNECT_CALENDAR_UNVERIFIED`。完整只读诊断在 `baseline_failure_diagnostic.json`。本轮没有为得到 READY 而改写该断言、合并通道成功语义或放宽 Connect／BUY 条件。

## NOT_RUN 与 CANNOT_CONFIRM

- 全项目／历史业务 suite：NOT_RUN；只运行上述 scoped synthetic 测试。
- Mac 本机临时副本复验：NOT_RUN；最终集成交付统一入口为包根目录的 `HOST_HANDOFF.md`。
- 真实 capture、正式 Reader、不同正式 Reviewer、真实 handoff/import：NOT_RUN；当前包内历史链仍 CANNOT_CONFIRM。
- 历史 trigger 的实际执行身份、执行次数、first break：CANNOT_CONFIRM。
- 现役 API/UI、网页重载、生产集成、部署、服务重启、计划任务或 binding 变更、自然时段运行：NOT_RUN。
- 真实公告的原始 PIT 可得性、HKEX 首次发布时间、Connect 资格及买入许可没有因本轮 synthetic 测试而获得证明。

## 交付文件

`after/` 是上述三个路径的完整 after；`before/` 保存两个修改文件的精确前像；`announcement.patch` 含源码和新增测试的完整 patch；`source_identity.json` 给出 before/after SHA 和实际环境。报告、精简日志、JSON/XML 是交接证据。`baseline_app/`、`pytest-*` 和诊断 fixture 目录仅为本轮临时执行材料，不应加入代码交付或业务上传。

## 集成交付位置

本报告保留分工阶段的完整证据；其 `before/`、`after/` 和 `announcement.patch` 描述对应分工工作目录。最终完整源码和可应用补丁只以包根 [source_manifest.json](../source_manifest.json)、[patches](../patches) 为准，本机统一入口为 [HOST_HANDOFF.md](../HOST_HANDOFF.md)。分工目录的源码/补丁副本未重复打包。
