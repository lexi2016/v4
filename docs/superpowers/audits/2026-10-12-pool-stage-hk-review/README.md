# R7 逐行审计索引：预选池 → 阶段选股 → 港股收盘复盘

本目录把四份只读源审计整理成可筛选的统一索引，不替代 BASE 中的原始报告和逐行数据。审计基线为 Git HEAD `55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`；各工作树源文件 SHA 是审计时字节，不表示 HEAD 文件、release 文件或当前运行进程相同。索引使用紧凑的源、上下文和理由字典；所有 V1 区间与 UI 副本等价关系都可还原，未丢字段或语义。

## 可机读文件

- [line_actions.csv](line_actions.csv)：每个物理行区间一行，仅含 `audit, source_id, start_line, end_line, action, disposition, reviewed, scope_status, reason_id, context_id`；通过 JSON 字典可按原始路径、SHA、完整理由、证据和测试信息还原。
- [line_actions.json](line_actions.json)：紧凑 UTF-8 JSON。`sources` 保留源路径、root、variant、审计时 SHA、行数及 UI 副本等价关系；`intervals` 用 `source_id` 和 `context_id` 引用短字段；`contexts` 连接 `symbols`、`evidence`、`targets`、`test_ids`、`blockers` 字典；`reasons` 保存每个完整原始理由。
- [COVERAGE_RECEIPT.json](COVERAGE_RECEIPT.json)：生成输入 SHA、审计计数与分区状态。
- [COMPACTION_RECEIPT.json](COMPACTION_RECEIPT.json)：旧区间语义、JSON/CSV 独立解码、UI 等价关系的机器可检查 round-trip SHA 和输出文件 SHA/字节数。
- [DOCUMENTS_RECEIPT.json](DOCUMENTS_RECEIPT.json)：文档自检和每份交付文档的 SHA-256/字节数；源清单 SHA 重算结果在 `COVERAGE_RECEIPT.json`。
- 生成器：[build_bundle.py](build_bundle.py)；原始四件套留存在 `BASE/{pool_audit,ui_audit,stage_audit,close_audit}/`。

当前 compact V2 文件为 JSON 839,294 字节、CSV 113,480 字节。两个格式分别解码为 1,360 个区间，并与原始展开语义的 SHA-256 `249a14de2f7eb5bf4d6dd272fc85d4a4e855f6d4d392ca6c365cf5ea186ecb34` 相同；UI 等价映射保留 11 条关系。明文 JSON/CSV 未使用压缩或 base64。实际文件 SHA 和逐字节长度见 `COMPACTION_RECEIPT.json` 与 `DOCUMENTS_RECEIPT.json`。

## 覆盖和状态

| 审计面 | 文件/路径记录 | 唯一内容或源文件 | 区间 | 映射行 | 已审范围 | 未读范围 |
|---|---:|---:|---:|---:|---:|---:|
| 预选池后端 | 36 | 36 个路径 | 1,009 | 8,661 | 8,661 | 0 |
| UI/TypeScript 主链 | 28 | 17 个 SHA 内容 | 62 | 6,244 | 6,244 | 0 |
| 阶段后端/API/Stage Center | 111 | 111 个路径 | 137 | 31,995 | 27,097 | 4,898（均为明示范围外） |
| 港股收盘后端 | 24 | 24 个源身份 | 152 | 6,620 | 3,420 | 3,200（均为明示范围外；其中1,422行已读但不属于本目标，1,778行未读） |
| **合计** | — | — | **1,360** | **53,520** | **45,422** | **8,098** |

四份原始收据均报告区间连续且无缺口/重叠；本目录生成器再次对每个源身份验证 `1..line_count` 完整覆盖。全域 `in-scope unread = 0`。`DEFER` 不等于未读：预选池 838 个区间（7,271行）、UI 2个区间（363行）、收盘审计13个区间（464行）均为已读后等待版本/owner/消费者对齐或行为实现；Stage 审计无已读待实施 `DEFER`。Stage 的 4,898 行及收盘审计的 1,778 行属于未读的范围外源；收盘审计另有 1,422 行是已读但范围外。CSV/JSON 的 `reviewed` 和 `scope_status` 保留两个独立维度。

这里的 53,520 是四张独立审计表的区间行数之和，并非全仓库唯一物理行数。UI 的 R3、R4、R6 同路径同 SHA 内容已按 SHA 合并，不重复计入；池/Stage 中同字节的不同路径仍各自保留，因为它们是不同模块身份。

## 原始审计输入 SHA-256

确切输入指纹见 `COVERAGE_RECEIPT.json` 的 `input_artifact_sha256`。四个报告 SHA 分别为：pool `556b6bbf89c232f26f0c2fb6040ec68f7918878b2dd512b88c72d3938c14c8c1`；UI `4971b77b3d919ca41c9c5259e1f4da14debda048150042f7c7215fa1dacce7a4`；Stage `a5ade66c2871bc46607750a22d985f255e37f645d18ade53af3dc1318e4b2b1e`；close `47d090a585930c94390e9643de2aa648166728cdf8d03e39a90d3ac48df191c8`。原始 FILE_INVENTORY、LINE_ACTIONS 和 RECEIPT 指纹也一并锁入收据。

父级在四份审计完成后核了 752 个定位索引条目的源 SHA，证据文件 `SOURCE_UNIVERSE_AFTER_AUDITS_R7.json` SHA-256=`d89d0b26efc9411c49cbad3fbf1e408685c9474ab8f38a898743160bc4da3848`，HEAD 未变；3 个 hourly research 文件在审计期间变化，但和四份审计的源清单交集为空。该 752 项是定位索引检查，不是审查覆盖，也不计入本表。变化的文件留在工作树，未覆盖或上传。本轮文档 Writer 没有写入业务源码；本轮未执行业务测试。

## 行为结论与边界

- A 股必须遵守用户已锁定的规则：完整 `a_all_pool_rows` 中任何有效、可追溯的 `market=A` 行都可进入阶段选股，包括 `a_share_baimao_research_map` 和 `wechat_public_account_v3_preselect` 的符合行级合同的数据。审计定位到 `StageInputProducer` 的 `eligible_ids` 与此合同不符；现有 `test_native_producer_reads_independent_graph_pools_and_excludes_research_only_lanes` 是反向断言，须改成接受所有有效汇总 A 行。坏来源仅按明确的 pool-local integrity error 隔离；root/lock/preflight/pending-commit/path-safety 和未分类 I/O 错误 fail closed。缺失、空、partial 子池不全局阻断候选但保留 gap/status，200 行显示上限不截断阶段输入。实现验收必须看到 `StageRunner.ensure` 后的 `read_workbench` 真实 A row `recommendation_status=WATCH_ONLY`，且 `stage.status=PARTIAL_WITH_WATCH_ROWS`、`markets.A.source_status=CANNOT_CONFIRM` 与 partial evidence 缺口不升 READY。
- HK 预选仍是精确 prior-trading-day canonical D-1 Top100 及来源 SHA；阶段采集保持 Futu 观察源和各 stage 自己的时间窗/来源合同，观察数据不因此变成 PIT/formal eligible。
- Native StageStore 和 Stage Center 的 RawStore、SelectionStore、runner receipts 是不同责任面。删去 Stage Center 重复 builder 构造时须保留现有 `tests/test_hk_stage8_v4_recovery.py::test_same_day_route_is_natural_and_historical_route_is_not` 双路由回归：同日自然 Futu 与历史 replay 继续分开；Stage8 仍不进入 HK close 的七阶段 formal union。HK close formal union 仍要求七个固定阶段全部精确且验证通过；partial observed 单列 `PARTIAL_RESEARCH_ONLY`、`NO_BUY`、PIT 未验证。
- Close ReviewStore 的安全验证须按 schema 分支：native `v3_5.close_review.v1` 要求 `RESEARCH_ONLY=true`；既存 imported `v3_5.close_review_reference.v1` 继续按 `reference_snapshot=true` 和既有只读安全旗标读取、可按 expected-SHA 被替换，不因缺 native marker 失效。
- 本目录是源静态审计和计划材料，不是 `TESTED`、`REVIEWED`、`BEHAVIOR_VERIFIED`、`DEPLOYED`、`API_VERIFIED`、`UI_VERIFIED` 或 `NATURAL_VERIFIED`。

## CANNOT_CONFIRM

1. 14:09:45 UTC API 观察到 `research-desk-20261012-r3/app`，该版本源及其 root binding、路由和响应未审；R4 是较早的静态比较点，不能称为当前 API 源。
2. API CWD/PID 不证明用户浏览器加载的 bundle；页面实际 readback 未验证。
3. runtime 快照记录 Stage Center/Futu R4 scheduler 和 HK deadline 旧 R1 scheduler 当时 `NOT_RUNNING`；V3.5 scheduler 记录为 R1/PID 8009，但它的实际行为和最新 workload binding 未确认。这些点时状态不表示当前启动状态；API PID 不能证明 scheduler owner、launch binding 或自然执行。
4. 当前真实 target-date storage root、pool/Stage pair binding、Futu 自然采样 freshness/PIT 资格及 HK close 自然运行结果未核实。
5. R4 精确 20261009 / `STAGE_0930_0935` approved read binding 的底层配对及其当前可读 payload 未核实。
