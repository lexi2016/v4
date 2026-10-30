# STOCK_PANEL_COLLAB_20261030

更新时间：2026-10-30。用途：通过GitHub开发分支向乐熹交接**已完成的个股模块**；不是主分支合并或V4发布指令。

本轮个股完整历史补齐入口及集成边界见
[`stock_history_catchup_20261030/INTEGRATION.md`](stock_history_catchup_20261030/INTEGRATION.md)。
它直接消费已有247份原式历史及研究面板来源缓存；原公式、名单、原图和现役服务不变。
离线补齐、独立验收、代码同步及页面接入分别记录，不把离线结果当成已上线。

## 1. 分工与唯一Writer边界

**本聊天负责个股**：原式个股K线/成交量、缩放/拖动/恢复、指标/历史信号与事件定位、历史总体和同价格分位成功率、基本面、股东变化、研报等逐股内容。

**乐熹负责**：整体框架、全天时间节点、美股/日韩证据、每日冻结名单、十分钟行情、涨幅/成交量排序、行业分类、全局日期切换。此分支不重复实现或修改这些模块。十分钟采集与监测范围由乐熹按用户最新授权处理，本个股模块不启动采集。

只在独立开发分支交接，不强推、不合并主分支；本次同步不再改现役V4、不改原公式、旧pins、凭据或权限。保留其他任务的未提交/未跟踪文件。

## 2. 负责文件与来源

- `research-panel/numeric283-panel.js`：逐股阅读布局、股票选择、原图挂载与缩放/区间控制、双成功率、56/33完整历史事件定位、资料/研报展示与stale防护。
- `research-panel/related-reports.js`：逐股研报查询与正文入口，按需查询，不冒称已遍历全文库。
- `research-panel/daily.html`：当前个股页宿主与本批脚本SHA缓存版本；仅交接现有宿主，乐熹的首页框架另行接入。
- `infrastructure/research_lane_source.py`、`apps/api/v4_api/research_router.py`：只读逐股API/已物化结果及资料白名单读取。
- `domains/research_daily_statistics.py`：保留原统计，新增固定250有效收盘价/五档价格分位的历史事件子集统计；不改原选股公式。
- `ops/render_original_formula_projection.py`：已验收C8原式投影图渲染/交互所需依赖；只消费原结果，不重算公式。
- `ops/render_daily_dashboard_code_map.py`、`research-panel/code-map/`：源码证据图/可搜索行号与架构总览，包含生成viewer的原许可证。
- 对应测试：`tests/test_readable_stock_materials.py`、`tests/test_event_percentile_strata.py`、`tests/test_daily_dashboard_code_map.py`、已验收C8名称和原图交互测试。
- `docs/handoffs/a_daily_dashboard_closure_20261029/readable_stock_materials/`：精简复现、差异与历史发布证据；**其中控制/准备脚本不授权自动执行**。

工作树完整文件与现役只读API profile有已知上下文差异；交接目录中的 `deployed_api/` 两份精确恢复字节、`EXACT_INSTALLED_DELTA.diff`及`SOURCE_PACKAGE_MANIFEST.json`专门记录该角色差异。不要把“工作树版本”和“已装API profile”混成一个虚构版本，也不要直接整文件覆盖现役服务。

本次排除：`infrastructure/zsxq_pdf_ingestion.py`、宏观/调度/Stage相关改动、其他任务的app.py/runtime_router.py/receipts/目录，原始行情/资料/PDF/缓存、plists、认证文件及无用测试草稿。未使用无范围git add/reset/clean/stash。

## 3. 当前入口与已验收版本

- 个股页面：`http://127.0.0.1:8873/research-panel/daily.html?date=2026-10-29&release=30b2c363ff73#dailyNumeric283Panel`
- 开发图谱：`http://127.0.0.1:8873/research-panel/code-map/index.html`
- 既有API版本：`a-daily-chart-first-20261030-r1-api`，manifest SHA256 `30b2c363ff73bb199e9c74d666f04c55ed3212ef3816251c97820045f7c54fba`。
- C9已在本次最新“只同步分支、不改V4”指令之前完成发布与现场API/UI回读；本次交接操作不会再次发布。Main/Stage未因此修改。

图谱是注明生成时间和角色的源码快照，不把静态依赖说成自然运行/PIT/数据认证。

## 4. 输入/输出字段与只读API

统一股票代码 `symbol` 为 `002003.SZ` / `600000.SH` / `920xxx.BJ`，保留六位证券代码和市场后缀。API日期用 `YYYYMMDD`，UI展示可用 `YYYY-MM-DD`。必须同时绑定 `data_date`、`source_generation`、`source_identity.input_sha256`、numeric manifest/artifact 的path+SHA；跨日期/市场/代次不回填。

| API | 输入 | 已有输出/用途 |
|---|---|---|
| `/api/v4/research/a-share/daily-product` | 可选`date`，单股加`symbol` | 当前产品/`row`、`data_date`、`source_generation`、`source_identity`、manifest/artifact、组别及`row.statistics` |
| `/api/v4/research/a-share/original-chart` | `date,symbol,generation,input_sha256` | `READY`、原式身份、`rows,values_per_row,drawings_per_row`、`assets.html.url`；用返回的校验URL显示原图 |
| `/api/v4/research/a-share/event-cases` | `date,symbol,group,horizon`，`group=original/nav_smallk/nav_pullback/nav_breakout`、`horizon=d2/d5` | 全部已接受`cases`及`conditional`；逐例有`event_date,target_date,status,return_pct,price_percentile`；不只保留赢家或最近20例 |
| `/api/v4/research/a-share/company-materials` | `date,symbol,generation,input_sha256` | `PARTIAL_RECEIVED`与`materials`；`business_reported,financials_reported,shareholders_reported,report_catalog,provenance_details`及来源/统计日/披露日 |

缺日期/缺资料/无有效样本/未成熟时保留明确状态，`null`不是0%。正文未取得不等于读过正文。字段名和schema以本分支实现及实际GET为准，接口消费者应先做日期/证券身份校验。

## 5. 如何接入股票代码和研究日期（必须区分已完成与缺口）

**已完成**：当前页侧栏点选已接受名单中的股票后，其图表、统计、资料和研报按同一证券身份更新；旧请求过期不会覆盖新选股。原图descriptor与逐股GET均有日期/代次/SHA约束。

**尚未完成的深链联动**：C9的名单loader仍读取当前 `daily-product`，默认选伟星股份；仅给页面URL的 `date` 或新增 `symbol` 不能声称已完成任意历史日/股票自动定位。首页接入方不得假设该能力已安装。

接入建议：乐熹先从已确认日期产品取得冻结名单和identity；按上述逐股GET读取同date/symbol。当前可沿现个股页侧栏选择股票，或显示descriptor返回的原图HTML。完整“首页选择股票→自动进入指定个股”的UI参数桥接仍是待补项，需双方按此合同对齐后再增量实现，不能复制另一套个股计算逻辑。

全局日期切换由乐熹负责：北京观察日与A股行情/信号日分开，例如观察20261030、收盘数据20261029，不能简单减一个自然日。建议对齐字段 `observation_date`、`data_date`、`symbol`；本交接写的是合同建议，不冒称已发布。显式历史日应钉住，不被其他日期SSE覆盖；不存在该日期/股票时清空旧内容并显示缺项。

## 6. 已执行检查与真实结果

- 固定分位纯函数7项合成测试通过；真实002003仅做一次已登记的56事件投影，复用已接受历史标签/收盘价/同源SZ日历，没有重算公式或完整历史。
- 总体D2 25/55=45.45%，D5 17/54=31.48%；当前近250价分位99.60%，同80–100%档33事件，D2 14/32=43.75%、D5 9/31=29.03%。未成熟、缺价不进有效分母；平收益进分母。这是NONPIT历史频率，不是未来预测。
- 资料/身份/stale/SSE初次挂载等本批7项检查、两份JS语法检查通过；4个真实P2集中修复后分别定向回归通过；独立Reviewer给`REVIEWED_PASS_C9`、P0/P1/P2=0，精确绑定上述API manifest和publication plan。
- Root真实IAB验过首次加载、原Canvas/完整成交量、缩放区间与恢复、56/33案例列表、2016早期事件定位及跨清明D5目标日；基本面/19719户/-3550户/31研报目录真实可见。
- 1440与679个股布局及1440/1600/1920/2048总图检查通过。图谱Archify showcase9/9、零错误/警告；代码图谱源码快照41文件/741符号。
- 本次源码包35项解包回读精确匹配。原式/数值manifest、accepted历史缓存与Main保持。

## 7. 剩余缺口及本轮边界

1. 只有002003的完整历史同买点统计已验收；不冒称全247已完成。候选union247也不是全池审图最终推荐名单。
2. 研报目录元数据、已校验OCR入口和全文库实际命中分开；缺正文保留。基础资料来源状态仍PARTIAL_RECEIVED，不能称全部字段已权威认证。
3. 上述URL日期/股票深链与首页联动未完成；全局框架、日期、十分钟行情和排序均留给乐熹按分工推进。
4. 自然15:40日更触发仍待该实际节点receipt，当前安装/页面通过不等于自然日更已验证。
5. 公共分支只含必要源码/测试/精简证据；大行情、Chat回包、研报PDF、运行缓存及认证信息不随代码上传。

协作保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。本说明供乐熹通过唯一标识 `STOCK_PANEL_COLLAB_20261030` 查找并对齐，不假称已直接发消息给尚未暴露发送入口的Dot。

## 8. 2026-10-30 中断恢复与增量事件缓存交接

R2原合同从已有journal续跑，保留原5个完成结果；retained supervisor PID88464、runner PID88465于13:14:29启动。状态以B10 `RESUME_LIFECYCLE.json`、`BATCH_PROGRESS.json`及`RESOURCE_GUARD_LATEST.json`为准；资源guard只观测/报告，未实现自动停止新增提交。冻结R2 runner SHA保持不变，未改变原式/逐前缀规则。

新增 `domains/research_event_case_cache.py`、`ops/reuse_stock_event_cases.py`及对应测试，提供持久逐事件收益/自身历史分位与真实R2分片导入。代次、合同和asof不单独作废已成熟收益；只对新事件、新成熟、补价和受影响修订调用原收益评价器。确切依赖、可执行命令、完成后机械检查和既有owner增量hook见上述 `INTEGRATION.md`。14项helper测试、真实已完成分片精确parity及零收益调用重复读取通过；全247仍RUNNING，不称全量完成或自动安装。

个股源码另修复已证实组别错配：001328同时属于小K/回踩时，从回踩名单点入会保持回踩统计，卡片标题明确显示组别；全部/不可用组别回落首个自身组。`research-panel/numeric283-panel.js`仅改这一绑定和标题；`tests/test_stock_event_group_binding.py`两项定向检查与JS语法通过。现役页面/API未因此更新，旧异步stale防护保留。冻结范围独立Reviewer已给REVIEWED/PASS：14项缓存、2项组别绑定及JS语法通过；真实8股/32组/2038条horizon cases精确一致，重复收益/分位计算0次。主控按逐项allowlist同步开发分支；现役安装、API/UI及247终态仍待对应证据。

## 9. 网站自动同步已现场闭环；框架接口另行交接

现役个股API已更新为`a-stock-history-auto-sync-20261030-r1-api`，manifest SHA256 `790e1e067123510a0a7da8ed2017fcfd3ebaf0849073eef5017855e5705d3df1`。Retained kqueue消费者只监听既有R2逐股RESULT完成，复用原owner保存与Main既有A_LONG锁；每股完成即绑定新的dated product/事件明细/资料索引并发出原completion，未轮询重算。原图、资料原件、公式、Main/Stage保持。

Root真实Chrome验收：002527在13:50:05仍pending1/3687，页面保持打开且不reload；13:52:03真实完成后，同一选股自动显示回踩D2 54/111、D5 52/109及对应分位统计。000554泰山石油已完成7887/7887日期，图/资料/明细可读；小K只有1个尚未成熟事件、有效样本0，正确保留“数据不足”，不借其他组胜率。B11 `ROOT_LIVE_UI_ACCEPTANCE.json`留存真实回执。此PASS限当前R2批次的自动网站传播，不冒称247终态或未来研究日Main增量hook已安装。

按用户指定框架分支/固定commit新增own namespace `research/stock_panel_collab_20261030`：严格日期/证券/generation/input/manifest/SHA同源GET适配，复用frozen51/22验证器和原renderer的`OriginalFullChart`方法，保留公司null/报告期/单位/来源；独立observation_date不推断。13项接口测试及001328真实861行/265177-byte gzip/单次projection GET兼容验证通过。框架46文件未改；sanitized shell仍缺显式host context交接、实际endpoint配置与外部公司validator，未部署该框架。精确接法与缺口见own README/COMPATIBILITY，按开发分支增量交付，不覆盖框架源码。
