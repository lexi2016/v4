# V4会话交接：1112日更交付、研究接入与海外二筛

编写时间：2026-11-12 13:47（Asia/Shanghai）。这是会话交接文档，不是新一轮运行验收。服务身份、任务状态、行情和研究时点各自按下面证据时间解释；本轮只整理文档，未重跑业务、重启服务、导入股票或发布页面。

## 先读结论

- 本批来源交易日 **D=2026-11-11**，观察交易日 **O=2026-11-12**，富途组 **1112**，四组去重 **426只**。
- D11基础研究面板、原owner选股、原图/评分及收盘报价已完成本批针对性验收。不能把这些状态解释为全部历史补齐、所有V4功能通过或11/12盘中行情已同步。
- 富途1112最终回读426只，missing/extras均空；指数/认股证0，全部证券ID非零。**此步已完成，不再重复导入。**
- Chat研究已收取并归档原文件，37个payload文件字节/SHA通过，426只名单和当日行情一致；全部研究状态仍为PARTIAL。
- **新Chat基本面/行业二筛没有接入工作台：NOT_IMPORTED。** 原交接身份字段不兼容；做隔离格式转换后仍发现64个来源的适用股票范围不兼容。不得放宽校验或把旧范围扩大到426。
- 最近一次研究建议：**盛弘股份、苏试试验主观察；固高科技、奕瑞科技备选。** 这是09:21左右盘前研究快照，价格截至11/11，未做11/12开盘或下午确认，未更新到看板。
- 下一步：收取64来源补件 → 保留原件、核范围与差异 → 既有owner接入 → API → 代表UI。**不要从全市场抓取、重算、重新研究426只或新建producer开始。**

## 1. 本批身份与唯一入口

| 项目 | 冻结值 |
|---|---|
| 用户入口 | http://127.0.0.1:8873 |
| 工作台 | http://127.0.0.1:8873/research-panel/workbench.html?source_date=2026-11-11&observation_date=2026-11-12 |
| generation | `270ba879ab1086df0c89a8e130ea6352b332cfb244ab9c125e10a29a15481e45` |
| 原研究package_id | `V4_D20261111_O20261112_G270ba879ab1086df_COMPUTED_1112` |
| 原CANDIDATES.csv SHA/input_digest | `79af9b579c3c88cffe9a7017d4d1d17f136b7065a7b899f21e0a97f7eb41926d` |
| 正式底层数据input_sha256 | `d145c45464e390a36d34c62ac20b26fa43ab6428a8f00fc31e7967b53d7c230a` |
| 正式numeric manifest SHA | `60d98618f2d3a44f3f630a5e9d6cc967f4fd58a73114698ee84c630371f3d8a6` |
| 正式product SHA | `1452d2e4f39bbd7a204c99fabd4e40267c6af338946acf56875437d26021f022` |
| 四组数量 | 导航小K269、原公式44、导航回踩158、导航突破70 |
| 重叠与范围 | 541项组别归属，去重426；SH154/SZ246/BJ26；Top200与v1.9.2对照不混入 |

**名单文件哈希、输入manifest哈希、底层数据input SHA、numeric manifest SHA、product SHA不可互换。** 原先行包的COMPUTED_NOT_PUBLISHED是导出时真实状态；之后同426股票/组别和generation的正式发布已单独对账，不覆盖冻结历史包。

证据根N：
`/Users/lexi/Desktop/学习/agents调试/v4_daily_panel_futu1112_20261111`

正式日包根：
`/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/today_full_r1/daily_products/a_share`

首读：N内 `DELIVERY_D20261111_O20261112_G270ba879ab1086df.json`，再按其引用读需要的证据。原件在 `chat_return_received/raw`，原输入在 `chat_input_prepublication`。

## 2. 已完成验收与保留缺口

| 环节 | 已有证据 | 明确边界 |
|---|---|---|
| 基础历史大表 | selector/backtest各17,200,149行，D11各5541行/证券；同代绑定 | 不要求停牌证券强补D日bar；不等于所有历史条件完整 |
| 原数值计算与候选 | 5809/5809逐项检查，去重426；正式/先行全名单、组别、426计算行SHA一致 | UNKNOWN条件按原回执保留，不当漏选；971不是已通过股数 |
| 原图、五分评分及情境建议 | 426评分物化、426原图描述；三市场直达链接与51变量/22绘图代表验收 | 未逐只视觉复核426只，不重定义公式 |
| 行情显示 | API426/426 D11收盘报价，源日、复权/量单位绑定 | D11收盘参考，DATE_ONLY；不能写成O日盘中 |
| Top200 | D11榜单200只，四组同日描述性命中17/200、17/426 | 非事前PIT或策略前向收益；不要把全池与阶段分母混用 |
| F10 | scope4619/5809；候选352/426，74失败 | 不等于完整基本面或Chat研究 |
| 历史条件覆盖 | 318只、947908标签日缺口保留PARTIAL | 普通日更不自动全历史bootstrap |
| v1.9.2 | 本批当日模型产物缺失，MODEL_NOT_READY | 不等于已重新核实训练是否结束；不擅启训练或替换模型 |
| 七阶段、预选池、自然链 | 运行身份/owner已有部署证据 | 11/12自然回执本轮文档未重查，当前结果CANNOT_CONFIRM；不能沿用凌晨PENDING断言下午仍未执行 |

基础/发布/API/UI入口证据：`FOUNDATION_D11_VERIFIED.json`、`FORMAL_PUBLICATION_MATCH.json`、`INSTALLED_API_QUOTES_AFTER_CONTRACT_FIX.json`、`WORKBENCH_INSTALLED_AFTER_REPAIR.json`、`WORKBENCH_INSTALLED_QUOTES_FIXED.json`。

当前用户DECISION_LOCK继续有效：A所有有效预选池汇总进入阶段筛选，缺失/空/PARTIAL子池仅隔离坏来源；完整输入不按展示200行截断，A/HK分离。此前只物化1/7阶段时的低命中不能解释为完整七阶段效果；后续先查各阶段实际输入/receipt，再讨论漏选原因。

## 3. 富途1112：已经闭环

- 用户手动导入后初读441项：426普通股票+14指数+1马来西亚认股证，目标股票无缺失。
- 随后仅在1112组执行一次MOVE_OUT移出15项误匹配；未对全局自选DEL、未修改其他组。
- 最终426只/426唯一，missing=[]、extras=[]、全部STOCK、stock_id非零；源BJ26只保留原市场身份。OpenD对部分BJ的SH代码映射不能倒改源BJ。
- 全局“全部”1766在本次MOVE_OUT前后不变；更早1909与1766差异不能归给本次操作。
- 21处简称/ST/XD/U/W等差异保留在 `futu1112/name_label_differences.csv`；当前券商简称不能倒填历史风险状态。
- 最终证据：`futu1112/result.json`、`after_group_securities.csv`；初始441的FAIL留在 `readback_result.json`，不覆盖。
- Futu GUI控制已收尾，未保留导入弹窗或按键/拖拽；不把旧锁屏BLOCKED当现在状态。

后续新批按实际A股交易日历计算D/O，组名为O月日。1112只用于本批续行，不能覆盖其他观察日。

## 4. Chat研究回包：完整性通过，研究仍PARTIAL，尚未接入

原ZIP：
`FUTU1112_V4_RESEARCH_RETURN.zip`，12216455字节，
SHA `38f6afb409f1cd794b60789db28348a510aeebec2d96f547b8b1d8465b9cf916`。

用户最新粘贴提到41个交付文件/100项校验；本地实际核的是ZIP38成员，其中37个payload及manifest，16必交文件齐备。外部ZIP、交付回执与校验清单另计，口径不能混成41项内容已逐条独立认证。同SHA附件复用，不重复下载。

- 全426覆盖、重复/缺失/多余为0；D日行情与原输入逐项一致。
- 297只复用、129只新增研究；5573唯一source_id；232事项涉及152股；三层控制人/平台/公司账本1278行。
- 状态：PARTIAL426，COMPLETED/BLOCKED/NOT_STARTED均0。严格全条件认证0只；原报告条件深查2只。
- 内容抽检3个代表：SZ盛弘、SH顺景603007、BJ纬达920001。只核主体、2026Q3期间与指定财务值，未宣称全426财务/全部来源/三层债务已认证。
- 来源范围校验另发现64个ID不兼容，不能被“100项结构检查通过”覆盖。

本地证据：`chat_return_received/RECEIPT_QA.json`、`SOURCE_SCOPE_INCOMPATIBILITIES.json`、`FOLLOWUP_RESULT.md`、`raw/PRIORITY_REVIEW.md`、`raw/NEXT_ACTIONS.md`。

网盘原ID：
- [本批输入目录](https://drive.google.com/drive/folders/1iw_lphXdMyN8UdsgBznrW2rXYSWD-pWM)
- [原研究回传目录](https://drive.google.com/drive/folders/1BaRJSzuZ_4ONqzY5DqJZWgDDSEKFz-j8)
- [完整研究ZIP](https://drive.google.com/file/d/1ilbVVks4-iT0vmkIIpHWmKWbt7hYuYWV/view)
- [原SOURCES.csv](https://drive.google.com/file/d/1HoZ2azaVuHNEDnsDMWsh8aBL2hkn-h8Q/view)

Chat状态：本批由用户转发研究，Codex未新发会话；研究会话URL未绑定，Chat UI会话归档NOT_RUN。**本地文件归档不等于浏览器会话已归档。** 新补件prompt也仅已交用户，未由Codex发送；未安装拉回包守护程序。

## 5. 接入断点与下一动作：只补受影响来源

### 实际断点

现有导入器：
`/Users/lexi/.codex/worktrees/company-materials-lifecycle-20261109/ops/import_received_company_materials.py`
SHA `c37f34baa55da53e40df5c9f34b6e3bac24365d19ec62d8ef833f1e7c8487c8b`。

既有入口为V3 prepare/publish；不直接改index、现役release或签名文件。

1. 原输入先行导出没有V3要求的正式身份列；回包把候选CSV哈希填进底层input_sha256、把INPUT_MANIFEST SHA填成numeric manifest SHA，product身份为未知。第一次本地配置也误用了回包input SHA，失败原样留存；以正式底层SHA修正配置后明确报 `RECEIVED_V3_NUMERIC_MANIFEST_CONFLICT`。
2. 保留冻结原件后，做了本批隔离格式转换：用同426正式行SHA/组别对账补元数据；行业research_status=PARTIAL映射为原接入status，交易排序旗标保持false。没有修改研究事实、选股或校验代码。
3. 随后严格来源核对仍拒绝：`RECEIVED_STOCK_SOURCE_CONFLICT:000035.SZ:R1112_INPUT_CANDIDATES_CSV`。全检64个来源ID存在2998个不兼容“股票引用—适用范围”对；45个ID的列表不是合法JSON。例子包括ALL_426、旧ALL_380、BATCH_MATCHED_SYMBOLS、主题标签及混合单引号/拼接列表。
4. 不能仅把所有范围改成ALL/UNKNOWN/BATCH_OR_METHOD，更不能由“股票引用了来源”反推来源确实支持该股票。ALL_380须回原380股清单确认，不扩大为当前426。
5. 未执行publish，原index/event未由本次导入改写；43,414,728字节可再生、未发布转换CSV已删除，原件/配置/失败日志/转换manifest保留。部分config引用的CSV已不存在，续行需按已记录映射再生，不能直接执行旧config。

补件交付已上传成功：
- [可转发原Chat的补件prompt](https://drive.google.com/file/d/1hDJ1ZmCLt9-kgRxXD5Mp4m9ySTFI637F/view)
- [正式身份与64来源精确问题清单](https://drive.google.com/file/d/1GKX9oNop_2bvH6O_ufw9K4USb1MDUT7b/view)

期望增量回包 `SOURCE_SCOPE_REPAIR.json`、`IMPORT_ALIGNMENT_NOTES.md`，每个source_id给旧值、新范围或null、原批次/日期/原件位置、证据与未确认项。只新增/更新缺件，沿原ID，不重复大主表、PDF和历史。

### 续行顺序及通过条件

1. 先查原回传目录与既有回执，判断补件是否已到；未到保持AWAITING_SCOPE_REPAIR，不重发原426研究。用户要求自行转发时只给prompt；另有明确自动发送授权才按chat-review-loop核同批会话、发一次并记录URL。
2. 补件到后保留原始版本，逐项核64来源原范围、格式、主体与日期。失败只处理受影响部分；未知不改为通过。
3. 复用既有导入器与原公司材料owner，按当前index/event CAS、A_LONG锁及精确代码SHA重新准备。修正格式时保留原字段、原包引用和全部PARTIAL。实际不兼容继续NOT_IMPORTED，不临时建第二数据层或放宽校验；需要业务代码/发布身份变化时另冻结范围。
4. 正式发布必须保留日期/市场/generation/input SHA；晚到研究保存真实received_at，不倒填D日已知或历史PIT安全。先按适用合同完成必要验收，再调用原publish。
5. 核正确API前缀，例如：
   `GET /api/v4/research/workbench/days/2026-11-11/company/300693.SZ`
   替换为本批代表样本，确认真正读到新package_id、材料引用、研究时点、PARTIAL与缺件，再打开原工作台检查主营/财务/行业材料及评分情境展示。HTTP200不等于新研究已接入。
6. 本批正确路由旧材料回读：盛弘、顺景仍读来源日20261109的1110研究包，纬达NOT_MATERIALIZED。证据 `API_EXISTING_MATERIALS_READBACK_CORRECT_ROUTE.json`。初次错误前缀404留存，**它不是已定位的新API故障**。
7. 只有真实导入、API和代表页面通过才更新IMPORTED/API_VERIFIED/UI_VERIFIED；技术评分与BUY安全继续按原规则，不让Chat文字直接改分。
8. 更新原轻量交付总账与SOP记录；不把本次手动接入当每日自然自动运行验收。

## 6. 最新海外行业二筛与推荐快照

分析保存于N的 `overseas_secondary_20261112/`：
`RECOMMENDATION.md`、`SELECTIONS.csv`、`RECEIPT.json`。生成于11/12约09:21；本轮文档未更新下午行情。

- 原Chat截止北京时间11/12 02:35，US只到纽约11/10；Codex后续独立核到了纽约11/11正常收盘：纳指+1.60%、标普+1.31%、费半+5.66%、美光约+11.9%。
- Reuters 11/11 18:10EST报道英伟达盘后曾跌约8%；是报道时点，非最新或最终盘后连续报价，不复述未经独立确认的个人传闻。
- 日本/韩国采用各自11/11已完成收盘：日经+1.31%、KOSPI+2.60%，关注设备测试与存储。11/12日韩盘中未并入该收盘口径。
- 三个观察方向：半导体设备/测试、数据中心光互连、供配电。原426光互连无证据充分的直接对象，因此未扩池凑名字。海外股价不能证明国内公司获订单。

| 分类 | 股票 | D11收盘 | 原关键K低/高 | 主要依据与缺口 |
|---|---|---:|---|---|
| 主观察1 | 盛弘300693.SZ | 33.01 | 32.62 / 35.74 | 9M扣非+37.42%、CFO+44.25%；存货+58.45%，AIDC独立收入/利润未拆 |
| 主观察2 | 苏试300416.SZ | 12.83 | 12.08 / 12.78 | IC验证有收入；9M扣非+9.99%、CFO+68.30%；增长温和、应收与扩建占用 |
| 备选1 | 固高301510.SZ | 30.53 | 28.20 / 31.02 | 9M收入+72.73%、扣非+255.90%；CFO仅905.25万元，现金兑现偏弱 |
| 备选2 | 奕瑞688301.SH | 81.60 | 74.21 / 83.33 | 微焦射线源用于半导体/SMT检测；9M收入+61.41%、扣非+23.16%；主题收入未拆 |

盛弘/苏试近250日价格分位均6.8%，全部历史分别约77%/60%；固高/奕瑞近250日40%/44.4%。**近期低位不升级为上市历史大底，同日小市值未认证。** 建仓波完整路径/换手/新反转K与11/12开盘承接均未完整确认，不强凑十只、不虚构重组概率或内部资金身份。最新价格变化需原来源核验，不沿用此快照当实时建议。

## 7. 运行身份、代码位置和本轮修复

以下是 `FINAL_RUNTIME_API_VERIFICATION.json` 2026-11-12约04:17北京时间快照，**不是13:47重新查到的现役状态**。接管业务前核launchd实际环境、manifest/app/config、owner及新回执；不要依赖旧PID。

| 角色 | 最后验收release | manifest SHA |
|---|---|---|
| Main | v4-daily-result-receipt-20261112-r1-main | 558d313eb3181ae6bf030b95bc552df40c0a052f4e34e413e05f5e94b1817d55 |
| API | v4-workbench-quote-contract-20261112-r1-api | 3cd2e4a36dffb95b6287b3ff3b9879f13d59616ad25005e7c9460d9ac3e72902 |
| Stage | v4-stage-final-owner-repin-20261112-r3-stage | fb3549044197550ae1351fda787f7084250fa8c08a27cebc6dbeef5f497cc5f1 |

Stage current owner绑定上述Main、history10项，原transition保留。Stage为一次性作业，槽间not running/exit0不单独判故障。**更换Main会改变hourly身份，必须同时核Stage owner/transition/historical见证关系。**

实际候选位于：
`/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/`
各role的完整app_root、plist SHA与原验收PID见上述JSON。Main原生data root为V35/state/data，API为V4/state/data，不交换。

源码交付：
- 用户入口canonical：`/Users/lexi/Desktop/学习/v4_app`，当前分支有其他人的并行未提交修改，不覆盖/checkout/reset/stash。
- 已交付修复worktree：`/Users/lexi/.codex/worktrees/d11-functional-closure-20261112/v4_app`，分支 `codex/d11-functional-closure-20261112`。
- Main源码commit `ddab09e32dd18d71234d2c699f00f2805934f1a9`；API源码commit `222776ac76033cd58af848b7f28f114a862d3c08`；最新交付记录基线 `ef42ed533209f02fde03bdac9abedd6177f46d3c` 已push并核远端文件SHA。
- 本交接文档另记其提交，不把文档commit当运行代码身份；未合并canonical业务分支。

已验修复摘要：基础日增量合批/块引用及reader兼容、默认不全历史bootstrap、原图virtual引用、工作台股票直达链接与报价thin-view读取、319KB详细回执超登记预算导致死RUNNING的收尾问题。旧dead claim经原接口恢复READY/预留0，没有重算D11。

保留操作失败：一次预检拒绝后shell换行仍继续切API；原FAIL未抹除，后按限定复核恢复。详见 `QUOTE_CONTRACT_PREFLIGHT_DENIAL.json`、`DAILY_RESULT_RECEIPT_RECOVERY_COMPLETE.json`。不得把中间PASS/手工恢复称自然验收。

未在本轮证明：11/12七阶段全覆盖/漏选修复效果、09:25真实价格就绪、所有预选池完整物化、海外卡片全部日更、模型当前训练/产物状态及17:00自然交付成功。先查本轮真实回执，受影响范围外不顺手扩大改造。

## 8. 存储与清理：避免再次全量增长

D11所测业务范围新增2156.881MB、覆盖文件净变化85.606MB，合计2242.486MB逻辑变化；D10约11.102GB基块复用保留。发布源码当前逻辑总量1.573GB单列，不是APFS独占新增。

已清理本批测试/重复导出/影子254.859MB逻辑字节；研究格式转换试验另清43.415MB。两者分别计，原业务增长快照不因此改写。保留正式行情/日包、原研究、必要失败/恢复证据；未测APFS独占回收。早期已不在baseline的6.4GB旧失败断点不能算本批清理。

增量影子验收5541证券：原Parquet1008.174MB → 新Parquet28.704MB，含checkpoint/封签40.604MB。此为已验后续写入路径比较，**不是D11已回收量，也不是整条日更每天只40MB**。只追加新日、新成熟及受修订影响部分；复用标签与检查点，不为导出重新整历史计算。

## 9. 每日固定顺序与时间检查

完整规范见[日更SOP](../DAILY_RESEARCH_DELIVERY_SOP.md)和[固定Chat模板](../DAILY_CHAT_RESEARCH_PROMPT.md)。北京时间，按实际A股交易日历动态计算D/O：

**基础面板同日验收 → 原owner全范围数值选股 → 优先交清单/逐股当日表现/prompt → 原owner发布评分/原图/看板并核回 → 已授权富途/Chat → 回包兼容导入/API/UI。**

| 节点 | 必查 |
|---|---|
| 04:15/05:15及21:00/22:00独立US摘要槽 | 实际纽约session与指数/行业涨跌；配置不代表当日完成 |
| 09:15 PREP、09:25 A观察/选股 | 同日全池、价格/量额就绪、真实截止与witness；不晚采倒填 |
| 09:35/09:40/09:45/10:30/13:15/15:00 | 其余六阶段receipt及完整输入；逐阶段统计覆盖 |
| 15:40首尝试，16:10/16:40有界重试 | 先CURRENT selector/backtest到D再选股；健康任务等待，复用checkpoint |
| 完成事件 | 原owner更新numeric/index/原图/score_action/statistics/events；不是每次人工复制 |
| 16:50人工检查点 | A主日包争取17:00前就绪；非新增定时器 |
| 17:00既有自动化17 | 触发交付，先核上游真实齐备；prompt先交，非上游必已完成承诺 |
| 17:20 HK、17:30/18:00预选池 | 各自来源与状态，不承诺全部17:00前完成，不改历史阶段 |
| 20:01/次日09:01公众号、21:15 review、21:40物化 | exact-pair/名称/上游证据及实际产物；失败子池单独处理 |
| Chat返回后 | 全名单/来源/时点/缺件 → 兼容原owner → API/代表UI；无固定耗时 |

资源按实时CPU/可用内存/压力与worker RSS选择合理多进程并发，保留系统/前台余量，不固定2/4路或盲目“拉满”；不从零重启已完成计算。本合同已有参考配置，不为文档创建新资源/空间检查任务。

日更流程不能固定11/11、426只或1112组；休市跳过股票导入/新研究，跨年同名组核既有回执。网盘先查后传、原ID复用，上传成功回执/ID即可，不例行下载恢复验证。研究内容持续包括基本面、产业卡点/兑现、量价结构、海外三个行业、实控人意愿/执行、三层债务与重大事项；事实/推断/反证/未知分开。

## 10. 给下一会话的直接指令

> 接续V4现有1112交付，先读取本文及N内交付总账、chat_return_received/RECEIPT_QA.json、SOURCE_SCOPE_INCOMPATIBILITIES.json、FORMAT_TRIAL_CLEANUP.json。保留D=2026-11-11/O=2026-11-12、同generation和原名单SHA。富途426已验收，不重复导入；日更数据已完成本批验收，不重算或重跑全批研究。先到原Chat回传目录查64来源范围补件；已到就核原范围与差异，经既有公司材料owner/锁/CAS准备并接入，保持PARTIAL和真实received_at，再核正确API前缀及代表UI。未到则复用已上传补件prompt，不重复发原研究；不能放宽校验或由股票引用反推来源适用性。新的业务修复另冻结范围并按适用合同验收，不能沿旧快照覆盖现役。11/12自然阶段/当天新日更另按真实日期回执检查，不能把手工日更、文档配置、股票建议或旧PENDING当自然运行结论。

全程：`RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。不查询账户/持仓/资金、不下单、不改公式/模型/BUY门、服务或调度。
