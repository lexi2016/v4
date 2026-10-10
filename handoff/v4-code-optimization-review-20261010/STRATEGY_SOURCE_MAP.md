# V4 公告、美股、超跌：源码能力与最小优化路线

审查日期：2026-10-10。仅通过 GitHub connector 读取固定源码并静态分析；没有导入业务模块、运行测试、采集市场数据、操作 Mac、修改业务代码或部署。本文的“已有”指固定源码包含该能力，**不代表本机现役服务已经加载或完成真实运行**。建议均未实施。

## 1. 固定证据与阅读方式

- 主源码快照 F：`lexi2016/v4@f7cb731c384ee6890a87d16c19a5b5a621779477`，来自 V5 预览分支中的冻结 V4 vendor/canonical 源码及 V5 适配层。
- 四功能交接 Q：`74478a0e62be215c8527ccc9a14b89b51042d014`。
- 超跌准入交接 R：`40084ee76acf1c43b2d8768d538d7c91052437dd`。
- `STRATEGY_SOURCES_READ.json` 是实际读取清单，含 commit、原路径、Git blob SHA、随包快照位置、字节数、SHA-256 与 blob 核对结果。`strategy-sources/` 为必要源码切片集，保留原始 UTF-8 字节；不是独立可运行的完整依赖闭包。
- 下文简写 A=`V5/vendor/announcement_offline_baseline`；U=`V5/vendor/us_mapping_baseline`；M=`V5/vendor/manager_plan_baseline`；B=`V5/vendor/rebound_baseline`；C=`handoff/v4-running-source-20261005/canonical`。除标注 Q/R 外，路径和行号均指 F；不能跨版本移植行号。

## 2. 核心判断

1. 这三条链都不是从零开始。既有采集、原始资料存储、日期/身份核验、算法、产品存储和读回接口，应先补精确输入与绑定，再讨论算法改写。
2. 公告“目录齐全”“正文读取成功”“语义判断完成”“经独立复核的选股”“经理消费”是不同阶段。离线 importer 不等于自动 Reader/Reviewer。
3. 美股有两类关系消费：4 键 reviewed seed 日常 join，以及原生港股发行人正文命题驱动的行业/显式美股关系。4 键不能代表全部能力；目前行情上游仍是固定 24 个行业代理、33 个配置代码，正涨幅阈值为 >0，不是全美股或“大涨”筛选。
4. 超跌当前主筛选是两个准入门槛，不能把同文件中另一条并存四项算术函数当成当前主筛选。历史数据完整、单位/价格基础、成员资格和 same-run 消费证据不能用“算出数字”替代。

## 3. 公告：真实采集 → 正文 → 语义产品 → 存储/读回

### 3.1 已有链路与可复用能力

- **HKEX 原始链**：A/`v4/manager_research/hkex_provider.py:445-597` 的 `HkexOfficialProvider` 提供受限 HTTP transport；A/`v4/manager_research/announcement_source.py:399-487` 的 `collect_batch` 先读 active-stock mapping，按发行人查目录，保存 prime/directory/body 引用，再用原 PDF parser 解析。支持有限批次、预算中断、pending documents、同文档原始引用复用，未把标题正面筛选当成全量公告采集。
- **东方财富发行人小批次**：同文件 `collect_eastmoney_hk_batch:614-778` 验证 116/H 市场和代码、article/title/date/分页正文身份、PDF 字节与解析，保存原始响应和派生文本 SHA。源码明确 `ONE_PAGE_OBSERVED_NOT_EXHAUSTIVE`、`MASTER_OWNED_BOUNDED_HK_ISSUERS_NOT_FULL_MARKET`，不可宣传为全市场目录。
- **另有按公告日期分页的目录 owner**：A/`v4/manager_research/announcement_catalog.py:210-409`，`collect_date_scoped_catalog` 使用动态 total_hits、每页行数、unique art_code 和 terminal-empty page 核验；原引用可离线恢复；每页有 attempt/receipt 钩子。`COMPLETE_EMPTY` 与失败/部分不同。其完整性仅对应东方财富指定日镜像目录，输出仍写明 HKEX first-publication 未验证、正文尚未请求、语义分析未运行、Connect 未评估。不能遗漏此链，仅批评小批次接口不全量。
- **内容寻址资料存储**：A/`v4/manager_research/materials.py:57-98,128-204`，`MaterialStore.fetch` 按 source key 加 kernel lock，同源 miss 串行；raw body SHA 作为 blob key，index 保存 URL、SHA、retrieved_at、content_type；支持 TTL/immutable cache。`parsed:206-237` 为派生结果缓存。
- **语义产品已具备严格装配逻辑**：A/`v4/manager_research/announcement_analysis.py:969-1122`，`build_product` 把 exact-date catalog、semantic catalog、body corpus、原始与 canonical hashes、发行人/文章集合、terminal body failures 逐项绑定，再生成 analysis records。不是调用模型自行完成语义理解。产物明确 `OFFLINE_REVIEWED_SEMANTIC_CATALOG_IMPORT`，PIT/首次发布时间/历史新颖性仍 CANNOT_CONFIRM。
- **导入与读回**：同文件 `import_product:1125-1155`，事务内检查已有产品，字节一致为 ALREADY_IMPORTED，不同产品拒绝覆盖；原 owner 原子写入后必须读回 VERIFIED。`read:1158+` 区分 NOT_IMPORTED。A/`v4/manager_research/store.py:97-153,380-443` 提供事务/原子写与提交回执基础。
- **日常 bridge 的真实职责**：A/`ops/run_manager_daily_announcement.py:1-8,27-39` 明示 capture/reading 由既有 operator 与人/agent Reader 执行；命令负责精确工件验证、analysis projection、owner import、readback。应复用它作为后半段，而不是重新造另一套 importer。

### 3.2 真正缺口与优化

- **前半段执行契约**：实际私有 V5 source-run 绑定、Reader 任务提交/返回、独立 Reviewer 提交/返回及 identities/hashes，不能以放几个 JSON 文件冒充已启用队列。F/`V5/docs/US_ORIGINAL_OWNER_RECONNECTION_20261010.md` 对原 supervisor/cycle 与此缺口有清晰交接；本文未独立读取当前运行队列或证明它可用。
- **不要将既有 guards 当 bug**：Q 的 `FOUR_ISSUE_MATRIX.md` 报告固定 R2 的 ANNOUNCEMENT_ANALYSIS_NOT_IMPORTED；须先提供 target/publication 精确 capture、Reader、Reviewer、import receipt 才能区分缺输入还是代码问题。这是当时 app-wired 记录，不是本轮运行结果。
- **最小改进顺序**：先统一 run/catalog/body/reader/reviewer/selection 产品身份与每阶段状态；再补既有任务入口绑定；然后只在真实失败的最小契约点修复。新采集字节必须使旧语义/复核失效，保留内容不足为未评估。
- **验收**：指定一真实目标日，提交同链所有 SHA/实际时钟/独立复核身份；原 owner import 后 exact-date GET 返回相同 row/issuer 决策及 input identity；目录缺页、正文残缺、issuer 不匹配、旧复核、变更输入均 fail closed；有证据完整的零结果才可明确标空。

## 4. 美股：行情样本与两条关系链分开审查

### 4.1 行情采集、算术与存储

- U/`ops/us_market_digest.py:52-136` 定义 Tencent endpoint、24-theme proxy map、PRE_OPEN/POST_CLOSE 时窗和受控迟到恢复；使用美东 ZoneInfo，不用手写夏令时月份切换。
- U/`ops/_us_market_digest_parts/market_snapshot.py:66-148` 的 `_build_us_market_snapshot_body` 只有 POST_CLOSE 才读取行情；从配置集合生成请求，保存 raw response SHA/provider receipt，调用 `parse_tencent_quotes_diagnostic` 校验每条行情。此文件后续 `:150-277` 汇总代码覆盖、代理均值和失败原因；缺行情保留未知/部分，不用零补。
- C/`ops/_us_market_digest_parts/phase_publication.py` 是既有 phase materialization/merge 路径；U/`ops/us_market_digest.py:679-718` 为其入口封装。
- C/`infrastructure/_research_peripheral_store_parts/publish_read.py:105-144` 的 publish 将 payload、receipt、manifest 绑定，冲突或 orphan 拒绝；`:147-170` 的 exact read 再验 payload/receipt/manifest。是可以复用的采集产品完整性链。
- U/`v4/manager_research/us_market_bridge.py:239-384` 的 `project_us_market` 选择 cutoff 前最近完成官方美股 session，要求 exact reader、lineage、POST_CLOSE、唯一 provider date、capture<=cutoff、安全标志；构造 `raw_industry_up`、`raw_individual_up`，硬失败不准入。`:360-367` 明确覆盖与筛选语义：24 行业代理/33 配置代码、涨幅>0，不是全市场大涨股。

### 4.2 路线一：reviewed seed 的有限每日 join

U/`v4/manager_research/us_mapping_research.py`：

- `_read_reviewed:42-55` 验证固定研究卡 artifact；`_relation_index:141-150` 只从 daily_match_symbols 建索引。
- `_relation_available_at:153-185` 独立验证 seed/report/registry/release/deployment 与 application available_at，不能把 retrospective reviewed_at 当原始获取时钟。
- `build_daily_run:188-277` 只有 bridge READY 且关系在 cutoff 前可用才用 raw_individual_up join；COMPLETE+关系可用+零匹配才 VALID_EMPTY。其 scope 明确 FOUR_REVIEWED_US_TICKER_RELATIONS_WITHIN_FIXED_33_CONFIGURED_SYMBOL_SAMPLE_NOT_FULL_MARKET。
- `persist_daily_run:280-303` 写 `us_mapping_research/<date>/runs/<run_id>.json` 与 latest pointer，读回 artifact SHA。
- 原始四键是 LITE/COHR/AVGO/CIEN；卡含 peer 与特定组件供应等不同关系。不能把 peer 写成供应商证明，也不能把另外两张无 daily_match_symbols 的主题卡当漏读。

### 4.3 路线二：原生发行人正文的行业与显式关系

- M/`v4/manager_research/issuer_us_relations.py:81-114` 的 `extract_issuer_business_relations` 从已认可的发行人主体/action/span 提取业务分类和显式 ticker；20 类 taxonomy 是词汇，不是股票映射表。
- 同文件 `_card_errors:117-146` 要求 native identity、source refs、available/retrieved/publication 时钟；`_standing_contract:149-184` 仅允许原 source owner 已提供的有限有效期关系契约，校验源/body/span/quote hashes，不回填历史获取时间；`material_us_relations:201-237` 输出行业/显式关系与拒绝审计。
- M/`v4/manager_research/research_evidence.py:336-403` 的 `us_mappings` 分别 join raw_industry_up 和 raw_individual_up，并要求独立港股原生关系来源；`:528-595` 的 `collect_attention_evidence` 实际调用 material_us_relations、us_mappings、diagnostics。因此 wider chain 不是仅文档愿景。

### 4.4 真正缺口与最小优化

1. 明确产品范围：保留原 24/33/4 键的 coverage 标签与 native-material 链，不能直接改成“全市场”或“高涨幅”而没有新获批目标/数据覆盖。
2. 先确认 native security-master root、真实正文关系及采集时钟是否绑定。F 的 reconnection 交接说明曾修过 `_workspace_security_master_root=None` 导致提前返回的问题；这份修复说明不等于当前服务已经部署通过。
3. 输出可诊断的漏斗：行情可用数→上涨数→有关系数→time/identity admission→manager 消费数；区分零上涨、有限seed零匹配、没有材料、材料因时钟/身份被拒绝。
4. 验收固定一 exact-session 原行情工件与独立原生港股材料，通过两类真实 join；改变 source SHA、晚于cutoff、缺master、peer冒充供应、seed未到available_at都必须拒绝；记录真实 zero 原因。没有实时 prices/quotes 时不推断四键各自为何未命中。

## 5. 超跌：原生 panel 来源与双门槛

### 5.1 来源与存储能力

- F/`V5/vendor/hk_preselection_baseline/upstreams/v3_shared_data/shared_data/hk_0_2.py:479-529` 的 `_read_vipdoc_increment` 按本地 `71#*.day` 32-byte record 读取 date/OHLC/amount/trade，不作股/手推测性转换。
- 同文件 `update_hk_0_2_panel_from_vipdoc:576-696` 是增量 append：日期前进、最少500代码、正volume/amount覆盖至少0.8，immutable parquet→manifest→panel_latest。`through_date<=current_max` 可以 already_current，**不会补内部历史缺口**；完整当前日期不能证明滚动窗口完整。
- C/`upstreams/v3_shared_data/shared_data/hk_daily_supplement.py:75-95,247-455` 已有 PyTDX sidecar：target+此前5完整港股session、`get_instrument_bars(category=4,market=71,start=0,count=6)`、保存 raw/manifest，canary 另存；`:458-627` reader 验身份、日期、scope、cutoff。仅6根，不能独自补60根最高价窗口。
- V5/`src/v5_shadow/rebound_panel_repair.py:263-315,316-425,573-696` 有日期表示兼容和明确旧窗口修复封装。它要求 parent/SHA/missing cells/source file/独立 owner authority；储存dtype修复不能当市场单位转换授权。

### 5.2 主算法必须准确区分

- B/`v4/manager_research/workspace_plan.py:622-670` 的 `rebound_history_sessions/rebound_history_rows` 使用港股官方日历：此前60个session高点（包含原定义下的半日session），此前5个完整日成交量。缺日期/重复日期不能用最近可用行替代。
- 同文件 `read_rebound_screen:827-1129` 是当前读取主筛选：close≤0.8×prior60 high，并且当日量÷前5完整日均量≥1.5 为 strict；恰一门未过且值已知为 near；未知为 pending；双门未过有明确 exclusions。`:888-970` 对精确日期、duplicates、null、zero mean 检查；`:1037-1126` 输出严格/接近/待补/排除/未解、逐行守恒 coverage 与 input/decision identity。
- 成交额、低点反弹、20日背景量、近期涨幅是观察字段，**不是本主筛选额外门槛**。
- 同文件 `rebound_v3_metrics:576-619` 仍存在另一条 amount+oversold+volume+rebound 四项算术语义，C/`domains/manager_close_rebound.py:186-220` 使用自己的 close/condition lane。优化必须先标定调用者/phase，不能全局替换成同一 gate 函数而改变已约定规则。

### 5.3 算术输出不等于准入

- B/`workspace_plan.py:673-756` 的 `rebound_native_evidence` 已明确 trade scale=1 不等于已证股/手，price currency、history units、finality 可未证。原筛选输出内部分字段存在较强 legacy assertions。
- V5/`src/v5_shadow/rebound_owner.py:322-352` 的 `research_projection` 保留数字分组，去掉未证单位/Connect/session/assertion，降为 CANNOT_CONFIRM；`:355-397` 在私有快照、固定源、写/网络防护后调用原 reader；`:546-562` 的 `manager_projection` 只可输出研究观察，eligible_screen=None，不能宣称正式选股。
- R/`MINIMAL_ISSUE.md` 的历史证据：一个原始样本的67个必需cells有56缺失、两项trade不一致；698 target membership与695 panel之间有3缺码；没有已建立的 deployment-pinned trust/owner-cell/rebound-membership attestations；`694_BATCH_HOLD` 未解除。其日期、数量只属于交接记录，非当前数据断言。logical digest与raw-byte SHA不同已被交接撤回为阻塞，勿再次当损坏。

### 5.4 最小优化顺序与验收

1. 原 owner 生成每code/date/field缺口表；明确 actual target、signal、cutoff、membership scope。原日期窗口/两门槛保持。
2. 复用已有源核对缺失cells，先确定同价格基础、币种、trade单位/scale、产品finality；不得凭100倍近似关系自动缩放，也不能用六根sidecar代替完整窗口。
3. 在受信 source/owner/capture 绑定下只补已批准 missing cells，保持原行原字节/值；dtype兼容仅影响新增表示。
4. 同一目标成员逐code核验67 cells、membership及availability，然后 observation→selection commit→独立ledger readback→manager exact input identity。同次链闭合后才判已消费。
5. 验收包含精确阈值、日历/半日处理、缺/重复日期、NaN/zero mean、错误dtype、错单位/调整基础、改SHA、越cutoff、缺成员、旧selection等反例；unknown必须pending，不能充入near或VALID_EMPTY。现阶段保持694 hold。

## 6. 横向优先级：交给 Chat 的具体审查问题

优先1（先做）：给每个目标日期列现役绑定证据与源码 commit/blob、owner根、exact input SHA、run id、cutoff，区分 SOURCE_MISSING、NOT_RUN、PARTIAL、VALID_EMPTY、STALE、CANNOT_CONFIRM。只在已授权后由现有环境验证，本文未做运行判断。

优先2：复用原采集/资料/owner store，将断点修在 producer→artifact→reader→consumer 的最短路径；先公告Reader/Reviewer真实入口、native master绑定和超跌输入证据。不要先新增采集系统或放宽规则。

优先3：固定 immutable输入重放，建立同输入同结果、变输入旧产品stale、row accounting、错误样本fail-closed回归；证据齐备后再做same-run app/HTTP/UI验证，静态或synthetic通过不写自然运行成功。

优先4：性能优化先测再改。现有公告已有内容缓存、解析缓存与预算，超跌已有groupby索引；仅从源码不能证明瓶颈。可测网络/PDF/hash/parquet/groupby耗时、请求数、缓存命中和峰值内存，再决定是否批量化/缓存；任何缓存必须绑定准确输入SHA/日历/规则版本，不复用过期身份。

### 不应要求 Chat 做的事

- 不凭研究候选生成交易，不修改BUY或权限/凭据，不移除V4。
- 不将GitHub vendor、canonical、api、stage和Mac现役混为一份源码；优先保留差异证据再决定patch目标。
- 不把四功能交接全部称为四个已确认代码bug：其原记录包含输入/authority缺失和正确的stale guard。
- 不把行业词汇、peer、4键种子或raw报价上涨当完整港股受益证明。
- 不把历史恢复/合成实验/进程exit 0当PIT、正式准入或经理已消费。

## 7. 固定链接

- [主源码F](https://github.com/lexi2016/v4/tree/f7cb731c384ee6890a87d16c19a5b5a621779477)
- [公告目录owner](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/announcement_offline_baseline/v4/manager_research/announcement_catalog.py#L210-L409)
- [美股两源关系consumer](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/manager_plan_baseline/v4/manager_research/research_evidence.py#L336-L403)
- [超跌主双门槛reader](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/rebound_baseline/v4/manager_research/workspace_plan.py#L827-L1129)
- [固定四功能矩阵Q](https://github.com/lexi2016/v4/blob/74478a0e62be215c8527ccc9a14b89b51042d014/handoff/manager-four-functional-gaps-20261009/package/FOUR_ISSUE_MATRIX.md)
- [准入缺口R](https://github.com/lexi2016/v4/blob/40084ee76acf1c43b2d8768d538d7c91052437dd/handoff/v5-rebound-admission-20261010/package/MINIMAL_ISSUE.md)
