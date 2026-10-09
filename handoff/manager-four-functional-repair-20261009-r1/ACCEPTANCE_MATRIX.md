# 四功能修复与分层验收矩阵

## 1. 当前结论

**4 个运行文件的最小接入修复已实现；57 项新增离线回归通过。真实 Mac 四功能完成状态尚不能确认。** 新增回归包括实际 `create_app` 注入测试；其中所有源数据、时间和 Reader/Reviewer 输出均是明确标注的隔离 fixture。没有执行真实抓取、Mac owner、部署、live API/UI 或自然时段任务。[E1][E2]

固定输入为 `lexi2016/v4@74478a0e62be215c8527ccc9a14b89b51042d014`。目标是该 commit 内的 R2 snapshot；独立冻结支持依赖记录在 `provenance/offline_source_assembly.json`，不将离线组装树称为完整 Mac release 重建。[S1][E3]

## 2. 四个问题分别验收

| 问题 | 原现场观察 | 本次源码结论与处理 | 离线验收已证明 | Mac 必须补交的通过证据 / 缺口处理 |
|---|---|---|---|---|
| Announcement 未导入目标日选股 | `ANNOUNCEMENT_ANALYSIS_NOT_IMPORTED`；review `NOT_RUN`；0 rows。 | 原 R2 consumer 在完整工件下可用，未改公告源码。复用原 capture → Reader → 独立 Reviewer → register/import。 | 8 项在原 R2 与 after 均通过：exact pair 可消费 selected 或明确 not-selected；缺工件、错日期、迟到 import、原输出变动与同一 reviewer 身份均不被放行。 | `target=20261009/publication=20261008` 的真实 catalog/body、Reader/Reviewer 原始输出、身份和 SHA、capture/handoff/import run 与 receipt；实际 app GET 消费结果。缺任何原证据继续 `CANNOT_CONFIRM` / `NOT_RUN`；不能将0 rows改成有效空。 |
| HK Connect 目标 membership 未验证 | `HK_CONNECT_TARGET_AUTHORITY_ROOT_NOT_BOUND`、`TARGET_HK_CONNECT_MEMBERSHIP_UNVERIFIED`。 | 增加 app/service 实例绑定并传给原 `read_scope`；显式空/错配置不回环境；拒绝非规范或 symlink ancestor root。没有新 universe producer。 | 原 V2 双板 capture/artifact/manifest/receipt/current/publication 全链经真 owner builder/reader；正确 root/date/pin 可读；错 root/SHA/date/PIT、损坏或跨根被拒绝。 | 真实目标日 V2 authority、源 root/source pin/run/SHA、持久化 acquired/available 不晚于实际 cutoff；实际注入 reader 的 membership/count。D-1 capture、native HK 名录和 US mapping 不能替代目标日 membership。 |
| Oversold 缺精确日期 master | `SCREEN_SECURITY_MASTER_READ_FAILED:HK_SECURITY_MASTER_EXACT_DATE_ENTRY_MISSING`，session `20261008`。 | 这是原 owner exact-date 输入缺口，未改 master/HK02 reader 或筛选规则，不做 latest fallback。 | 原 publisher 生成的精确日 master可读，manifest/receipt/artifact/run SHA可追溯；错日/损坏/迟到被拒绝。真实 screen 可读取 master+HK02+历史；volume provenance `NOT_PROVEN` 继续 pending/partial。 | 同 root/cutoff 的 `20261008` master index entry、snapshot/manifest/receipt、HK02 exact panel和所需历史、成交量单位/尺度来源证明。数值齐全但 provenance 未证实不能升级为 qualified 或 coverage-backed empty。 |
| Plan 保存与当前 identity 不同 | `STALE_INPUTS_CHANGED`；`consumed=false`；saved `5df99128…`、current `7c5d9f18…`。 | 保留 stale 比较。修复 V2 card 元数据：排除观察 `read_at`，保留持久化 `available_at`；workspace转发实例 binding。 | 同 store/readers 的原 mapping→plan→GET run/product/attempt/input SHA相符。稳定输入、非空卡片仅观察钟前进仍 `CURRENT`；真实来源/authority/日期/持久化可用时间改变仍 stale；重跑原 owner 后可 `CURRENT`。 | 使用实际 `create_app` 原 POST 保存，再 GET dynamic，同一 manager store/source readers、精确日期与cutoff、product/attempt/readback SHA可验证。现场旧identity变化原因仍 `CANNOT_CONFIRM`，不能把离线 `read_at` 缺陷直接定为10/09事故根因。 |

四行原观察与最小接受条件来自冻结问题矩阵。原现场三通道不可用、0 stocks 不构成完整选股，也不构成全市场有效空。[S1]

## 3. 输入到消费的验收链

| 验收边界 | 必须核对 | 失败时的保留行为 |
|---|---|---|
| 原工件 → 原 reader | 日期/市场/角色、source root与owner source pin、manifest/receipt/run/SHA、acquired/available与cutoff。 | 不回退 latest/邻日，不创建替代工件。缺输入、非法输入和PIT失败保持原诊断。 |
| `create_app` → service | `data_root`为US原peripheral输入根；`manager_research_state_root`为唯一manager store；master/screen按实际root；保留原archive `research_data_root`；Connect五键在构造期绑定。 | `{}`保持未绑定；显式错值不回环境；不借另一个service/store成功结果。 |
| service → workspace | 原 US、公告、HK、screen reader被该实例调用；同一源身份进入各channel与plan。 | 各通道独立暴露缺口，US映射不替代HK/oversold，公告分析不替代capture或review。 |
| 原 plan owner → 保存 | 原product schema/date/input identity/安全标志、不可混淆的product canonical SHA和文件SHA；exact run terminal attempt及SHA。 | 写入或readback失败不报告成功；历史run、attempt、旧product继续保留。 |
| 保存 → GET | exact full date binding、原cutoff下重读当前输入、相同semantic/input identity、exact attempt验证；GET无producer/写入。 | 来源变化保持`STALE_INPUTS_CHANGED`；产品/attempt损坏不消费；不同日期不借旧产品。 |
| GET → 真实业务验收 | 每个channel证据、覆盖范围、实际UI显示与独立自然运行receipt。 | `CURRENT`、200、0行或手动成功都不独自代表四功能完成、BUY或自然时段通过。 |

具体参数优先级、五键映射、原CLI模板及POST/GET命令见 [HOST_HANDOFF.md](HOST_HANDOFF.md)。

## 4. 新回归与旧门禁分开记账

### 新增 57 项

| 新测试文件 | 数量 | 本轮结果 | 验证层 |
|---|---:|---|---|
| `tests/test_manager_four_announcement_integration.py` | 8 | PASS；原 R2 对照同样8 PASS | 实际 `create_app` + 原CLI/register/import/consumer，外部transport与时钟使用fixture。 |
| `tests/test_manager_four_hk_readers.py` | 30 | PASS | 原V2 owner/reader、精确日master/HK02、root/PIT/SHA、非空card identity。 |
| `tests/test_manager_four_plan_owner_readback.py` | 13 | PASS | 原source stores、mapping/plan owners与router GET；包含真实archive/master/classifier的非空卡片。不是独立create_app测试。 |
| `tests/test_manager_four_app_wiring.py` | 6 | PASS | 实际`create_app`构造、实例binding/root/store/reader与原HTTP行为。 |
| **本组总计** | **57** | **57 passed，退出0；1条现有Starlette警告；5.87秒** | **Linux隔离合同回归，不是Mac数据/部署验收。** |

环境：Python 3.14.8、FastAPI 0.143.0、Starlette 1.7.0、pytest 9.1.1、httpx 0.28.1、pyarrow 24.0.0。结果见 `evidence/new_regression_57.log` / `evidence/new_regression_57.xml`；弃用警告原样保留。[E1][E2]

### 原有相关测试与工程门禁

| 组别 | 固定 R2 对照 / 本轮 | 解释 |
|---|---|---|
| 原HK相关5个测试文件 | 对照39 PASS、16 FAIL；本轮同一组39 PASS、16 FAIL | 16个failure nodeid一致，详见`evidence/hk_report.json`与两份原始日志。没有据此宣称旧HK组全绿。 |
| 新HK30 + 原HK组组合命令 | 69 PASS、16 FAIL | 已含上方新HK30，不能再计入57形成“126项新增”。 |
| 全工程 `python -m pytest -q --maxfail=1` | **COLLECTION_BLOCKED；退出1；1条警告、1个收集错误；0.85秒** | `tests/test_hk_expected_missing_recovery.py` 无法从 `infrastructure.preselection_pool_store` 导入 `HK_EXPECTED_MISSING_SOURCE_SHA256`。该支持模块不在4个运行文件改动内，未扩修；全工程未通过，也没有完成全量测试收集。 |
| 原R2离线组装树的全工程对照 | **COLLECTION_BLOCKED；退出1；1条警告、1个收集错误；1.38秒** | 四个运行文件均核验为精确before SHA后，执行同一pytest门禁，仅加 `-p no:cacheprovider`。首个测试文件、缺少的导出与候选树相同。这是此离线assembly的对照，不是完整Mac源码门禁结论。 |
| 独立审查复跑同57项 | 57 PASS、0 FAIL、0 SKIP；退出0；5.71秒 | 同一组复跑，不另计新增数量；4个运行文件在审查前后字节不变。 |
| 独立审查新增边界探针 | 10 PASS、0 FAIL、0 SKIP；退出0；2.68秒 | 实际app晚改环境、六种非法binding、非空dynamic GET跨午夜、损坏authority撤销CURRENT、真实原公告register/import使旧plan stale后原POST恢复CURRENT。探针仍是隔离fixture，不替代Mac。 |

全工程原始日志与XML见 `evidence/project_gate_collection_error.log` / `.xml`；原R2离线对照及SHA/命令记录见 `evidence/project_gate_r2_baseline.log`、`.xml`、`evidence/project_gate_r2_baseline_receipt.json`。独立审查为 `PASS_WITH_EXPLICIT_OFFLINE_SCOPE`，未复现P0/P1/P2问题；这只限定于所审查差异和离线探针。独立审查证据见 `review/independent_review_receipt.json`、`review/rerun_57.log`、`review/edge_probes_10.log`。本组文档只整理已有记录，未重新执行测试。[E4]

## 5. 独立状态表

| 状态维度 | 当前状态 | 升级条件 |
|---|---|---|
| `IMPLEMENTED` | **YES — 4个运行文件最小补丁** | before/after SHA与允许路径校验一致。 |
| `TESTED` | **NEW_REGRESSION_PASS — 57/57**；旧组/全工程按第4节单列 | 新测试证据可重跑；旧失败不隐藏，不把范围外gate合并计算。 |
| `LINUX_APP_CONTRACT` | **PASS_SYNTHETIC** | 已有实际create_app/TestClient合同证据；继续明确仅fixture source/clock。 |
| `MAC` | **NOT_RUN / CANNOT_CONFIRM** | Mac实际源码/依赖/配置/工件/进程身份可核对。 |
| `INTEGRATED` | **NOT_RUN_ON_MAC** | 目标Mac实际app从原root读取各owner，原POST保存→GET精确回读通过；Linux合同不替代此项。 |
| `DEPLOYED` | **NOT_RUN** | 独立、已有授权的部署与release/process receipt；本包不自动部署或启停。 |
| `API` | **LIVE_NOT_RUN** | 实际目标服务的请求/响应与source/run/SHA readback证据。 |
| `UI` | **NOT_RUN** | 统一V4入口真实页面消费同一API及正确channel状态/rows/gaps的证据。 |
| `NATURAL` | **NOT_RUN** | 原调度器在真实自然时段执行，独立trigger/process/API/UI链及cutoff证明。手动、late catchup、回看不替代。 |

Mac执行者按实际证据逐行更新，不把这些状态压成一个总PASS。状态中的 `CURRENT` 仍允许原owner `PARTIAL`，并不抹除缺来源、覆盖不足或其他原依赖gap。

## 6. 必须保留的历史和安全结论

- 用户报告9/30曾有独立单日入口成功。本包未定位该receipt，不能证明也不能否定该独立成功；已检查的4个workspace计划为partial，只限定其自身范围。
- 9/30 09:53记录只证明US attention READY的24 industry proxies + 33 configured symbols范围；不证明同一完整计划中公告、HK/oversold成功。
- 10/7 publication → 10/8的529行、33 selected、54 watch、75 pending记录证明公告子链已被消费；channel仍partial，HK/oversold未完成、plan未物化，非9/30 receipt。
- 10/9 isolated mapping `VALID_EMPTY`只覆盖reviewed 4/33，`full_market_coverage=false`；同根plan仍partial。不能扩成全市场无候选或四功能完成。
- 现场`5df99128… → 7c5d9f18…`是原stale guard正确拒绝的证据；本轮只证明隔离R2代码中存在`read_at`漂移缺陷，不重写现场根因。
- 保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`；不更改BUY、Stage、Vibe8910，不删除历史产品、run、receipt或旧SHA。[S1][S2]

## 来源与证据索引

- [S1：固定四问题矩阵](https://github.com/lexi2016/v4/blob/74478a0e62be215c8527ccc9a14b89b51042d014/handoff/manager-four-functional-gaps-20261009/package/FOUR_ISSUE_MATRIX.md)。
- [S2：固定单日owner/历史证据说明](https://github.com/lexi2016/v4/blob/74478a0e62be215c8527ccc9a14b89b51042d014/handoff/manager-four-functional-gaps-20261009/package/DAY_RUN_REUSE_AND_INTEGRATION.md)；同目录`evidence/`四份JSON。
- E1：本轮`evidence/new_regression_57.log`、`evidence/new_regression_57.xml`、`evidence/app_wiring_red.log`、`evidence/app_wiring_green.log`。
- E2：`evidence/announcement_test_summary.json`（原R2/after各8项）、`evidence/hk_report.json`（30新项、旧16同基线）、`evidence/plan_result.json`（13项及SHA）、`evidence/PLAN_INVESTIGATION.md`、相关红/绿日志。
- E3：`provenance/offline_source_assembly.json`；区分R2精确目标与固定仓库支持依赖。CLI支持版本SHA为`aee0e5c31f30b296864a7ad81263fbc748b65cb9b4d443f83a756019cbc94a38`，不在4文件运行补丁内。
- E4：`evidence/project_gate_collection_error.log`、`evidence/project_gate_collection_error.xml`、`evidence/project_gate_r2_baseline.log`、`evidence/project_gate_r2_baseline.xml`、`evidence/project_gate_r2_baseline_receipt.json`、`review/independent_review_receipt.json`、`review/INDEPENDENT_REVIEW.md`、`review/rerun_57.log`、`review/edge_probes_10.log`。
