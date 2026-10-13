# 共同合同：MWB_V1_20261013

本合同适用于A/B/C三块。用户锁定的目标与阶段顺序见README。公共类型和规范JSON样例由B唯一写入；A消费公共Python类型，C消费对应JSON类型。变更需要主控协调，不能各自发明同名但不同语义的字段。

## 1. 输入、范围与规则

- 固定市场键HK_CONNECT；A股不进入经理港股列表。证券键market+规范代码，港股代码形如HK.00001。
- 目标港股日、实际行情session、公告日期/窗口、美股session、研究cutoff、采集/可用时间必须分别记录；时区Asia/Hong_Kong。复用各市场日历，不机械减自然日。
- 公告按既有经确认的公告窗口与月度港股通资格版本读取完整已观察集合；官方与镜像来源分列，覆盖未知不能称全市场。不得通过限定少数发行人冒充完整日目录。窗口、资格来源及缺口均随输入保存。
- 美股保留现有固定33个配置标的和已审核关系范围，明确不是全市场扫描；目标session按既有US owner合同读取。关系类别、发布时间和来源证据不互相升级。关系缺失进入待核验。
- 超跌按既有exact-date共享面板、证券主数据和已有历史/补充来源读取完整适用范围，独立记录港股通资格；不改成D-1 Top100扫描，不把证券主数据成员等同目标日Connect资格。价格及成交量可比性、缺历史、停牌、无效分母均需明确。
- Stage保留既有D-1 canonical Top100及阶段合同，输入不受前端分页/显示行数截断；只消费原owner结果，不建新Stage producer。
- 超跌严格入选：close(D-1) <= 0.8 * max(high, D-1之前60个完整交易日)，且volume(D-1) / mean(volume, D-1之前5个完整交易日) >= 1.5。窗口都不包含D-1。量纲未知或任一必要证据缺失为UNASSESSED；只有单条件通过作为CONDITIONAL_WATCH并标明未通过完整AND，不算严格入选。两条件均可评估且未满足完整规则保留逐项值与排除/观察依据。
- 公告判定保留 `POSITIVE_OPERATING_RESEARCH_V1`。精确旧源码谓词及SHA见[学习规则与开发环境](LEARNING_REFERENCE.md)，新模块重新实现以下映射，不导入旧代码。逐篇输出disposition、selection_basis、direction、evidence_sufficiency、reason、risk_notes、原文定位及source/body SHA；Reader与独立Reviewer必须绑定相同正文和身份。
  - SELECTED_EVENT/OPERATING_EVENT或SELECTED_PERFORMANCE/PERFORMANCE_RESEARCH，且direction=POSITIVE、evidence_sufficiency=VERIFIED_EXISTING_FACTS、复核通过、资格/来源/时间证据均有效且不晚于cutoff，才映射SELECTED。逐篇事实、相对已有材料的新变化、影响、确认条件和反证必须有原文依据；标题利好、事项类型或模型肯定语气不能代替这些字段。
  - 完整已复核材料明确为CONDITIONAL_WATCH且条件有依据时映射CONDITIONAL_WATCH，保留未确认条件，不算严格入选。
  - 完整已复核材料明确为NOT_SELECTED时映射NOT_SELECTED并保存否决理由；NEGATIVE/MIXED/NEUTRAL不自动当利好入选。
  - NOT_ASSESSED、direction=UNKNOWN、证据不足、正文/资格/时间缺失、来源SHA不符或复核冲突均映射UNASSESSED；自相矛盾的入选字段不能降格成已核观察。晚到材料保留在后续实际版本，不改盘前记录。
  旧代码没有按标题/金额/增长率自动判定disposition的阈值；首版不新增此类阈值或综合评分。A须把上述证据语义写入prompt和可核验测试，无法证明正文支持时输出UNASSESSED，不能自创准入规则。
- 美股PRIORITY/WATCH仅映射CONDITIONAL_WATCH；首版不存在新增严格SELECTED规则。Stage/尾盘无明确研究入选依据时为OBSERVATION_ONLY；不能因有行就算经理入选。尾盘量能/位置等缺规则保持未知，不补数值阈值。
- 港股通资格与Stage结果、美股映射、资金流彼此分开。本版不新增港股通资金流研究。RESEARCH_ONLY=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。

## 2. 公共数据模型

所有枚举、字段名以下列定义为准，JSON schema_version固定 `v4.manager_workbench.v1`。安全四字段包含在结果与响应外层，不由浏览器传入或改变。

| 类型 | 必要内容 |
|---|---|
| RunContext | market、target_date（YYYYMMDD）、phase（PREOPEN/INTRADAY/NEXT_DAY/RETROSPECTIVE/MANUAL）、cutoff（带时区）、trigger（SCHEDULED/MANUAL）、source_sessions、rules_version、scope_refs |
| EvidenceRef | evidence_id、owner、role、source_date/session、observed_at、captured_at、available_at、sha256、artifact/manifest/receipt引用、原文URL（如有）、验证状态与缺口；没有时间/引用时保留空值及原因 |
| InputBatch | context、lane、universe_ref、records、evidence_refs、input_sha256、scope_description、coverage、gaps；输入快照是可追溯派生产物，不成为新权威源 |
| LaneResult | lane（ANNOUNCEMENT/US_MAPPING/OVERSOLD/STAGE_REFERENCE/CLOSE_REFERENCE）、state、rows、coverage、input_sha256、rules_version、run_id、evidence_refs、gaps |
| StockDecision | market、symbol、name、decision、lane_decisions、reasons、conditions、invalidation_conditions、risks、evidence_ids、资格状态；原策略标签/数值保留在lane_decisions |
| PlanSnapshot | schema_version、context、run_id、input_sha256、product_sha256、generated_at、available_at、lanes、stocks、counts、changes、review_refs、gaps、安全四字段 |
| JobRecord | job_id、run_id、context、state、step、started_at、finished_at、last_progress_at、completed_count、total_count、failed_steps、failure_code、retryable、execution_refs |
| ReviewSummary | target_date、plan_run_id、evaluation_scope_ref、mode、ranking_date、完整Top20行、严格/扩展覆盖、入选分母、各策略新增覆盖、未覆盖原因、gaps |

LaneResult.state固定 NOT_RUN/RUNNING/READY/READY_EMPTY/PARTIAL/INPUT_MISSING/FAILED/NOT_APPLICABLE。JobRecord.state固定 QUEUED/RUNNING/SUCCEEDED/PARTIAL/FAILED/CANCELLED/INTERRUPTED。证据验证状态另列VERIFIED/CANNOT_CONFIRM/INVALID，不混入执行枚举。StockDecision.decision固定 SELECTED/CONDITIONAL_WATCH/UNASSESSED/NOT_SELECTED/OBSERVATION_ONLY；未评估不是未入选。

同股去重分类优先SELECTED，其次CONDITIONAL_WATCH、UNASSESSED；没有策略结论但有阶段/尾盘引用则OBSERVATION_ONLY。只有所有适用研究lane均评估完成且否决才显示全局NOT_SELECTED。不适用lane不造成待评估；来源缺失是UNKNOWN，不能装成不适用。排序按上述分类、该股票已核证据的最新available_at降序、代码升序；同组不合成收益分数。无已核证据时间的行在同组后置。

coverage包含scope_count、observed_count、assessed_count、unassessed_count和缺口；unknown使用null。counts为完整结果的selected/watch/unassessed/observation_only/not_selected计数；来源数量与股票数量分开。查询分页不改变这些计数或实际研究输入。

## 3. A/B进程内交接

B提供 `contracts.py` 的上述类型及schema/sample，先独立提交。A提供：`load_inputs(context, adapters)`、`run_lanes(context, inputs, semantic_executor)`、`merge_decisions(context, lane_results)`、`evaluate_review(plan, close_inputs)`；返回公共类型，不写计划指针，不注册API或启动后台循环。

A拥有公告分析与复核的业务prompt/schema、证据检查及判定解析；B拥有通用 `semantic_executor.execute(task)`。task至少含task_id、role（READER/REVIEWER）、model、reasoning_effort、input_sha256、input_refs、prompt_version、prompt、output_schema。返回实际execution_id、开始结束时间、output、output_sha256及成功/失败证据。两个role必须不同执行identity；Reviewer拿原材料与Reader输出独立核对。B不发明公告判定，A不直接调用CLI或管理任务进程。

公告正文、网页/PDF文字和Reader输出均为不可信数据，必须和固定任务指令分区封装；其中要求访问文件、联网、执行命令、改变规则或泄露凭证的文字不执行。B执行器只提供本次脱敏材料的隔离目录，关闭MCP、网页获取等非模型服务网络工具及无关工具访问，不向模型可访问范围挂载原数据根、凭证目录或其他工作区；既有账户认证仅由CLI宿主处理，不作为材料或工具可读输入。read-only本身不等于隔离；CLI若无法证明此边界，真实执行canary标NOT_RUN/CANNOT_CONFIRM并报Mac主控，不放宽权限。输出只经JSON schema与A语义校验消费，不作为命令或路径执行。Reader/Reviewer均须覆盖正文中恶意指令的合成测试。

A的公告来源适配可实现 `capture_announcements(context, request, cache)`；只能接管本次明确的原唯一owner。由B统一调度，测试使用隔离缓存；未切换前不对权威源并行采集或双写。原owner缺能力时返回明确缺口，不增加另一抓取路径。

## 4. B/C HTTP交接

统一前缀 `/api/v4/manager-workbench`，响应外层包含schema_version、state、data、gaps、安全四字段。

- GET `/days/{date}`：参数phase（可选）、run_id（可选）、offset=0、limit=50（1..200）、decision/lane/q（可选）。读取最新已保存指定phase/version；无phase取该日最新可用计划，同时返回盘前/日内/次日版本索引。返回snapshot元数据、完整counts、当前页stocks及pagination.total/offset/limit。过滤后total和未过滤完整counts分别返回。
- GET `/stocks/{symbol}`：必须提供date、run_id，返回同一计划内个股详情；不能暗中读取另一日期或重新分析。
- GET `/history`：必须提供date，返回当日新旧历史版本索引，origin=NEW/LEGACY；旧记录带original_schema、original_run_id、original_sha256、verification、gaps。由独立适配器读取旧字节，不调用旧业务。
- GET `/reviews/{date}`：必须提供plan_run_id，返回ReviewSummary；无合格收盘数据时明确缺口，不调用其他日期榜单。
- POST `/runs`：JSON为target_date、phase=MANUAL或RETROSPECTIVE、lanes（可选，默认全部适用lane）；返回HTTP202及job_id/run_id/status_url。cutoff由服务器真实时钟确定，浏览器不能提交来源路径、历史时间或股票行。RETROSPECTIVE明确为事后研究，不能变成当时盘前证据。
- GET `/runs/{id}`：读JobRecord；POST `/runs/{id}/retry`只恢复retryable失败步骤；健康活动任务返回现有job，不重复创建。
- GET仅读保存结果或明确未运行状态，无采集/模型/计划写入副作用。有效日期但未运行返回HTTP200+NOT_RUN且data可为空；非法日期/参数422、未知实体404、不可重试/冲突409、通道暂不可用503。部分结果不误报全局错误。

C必须覆盖上述状态与null，不从缺结果推断0；请求换日/换版本立即隔离旧结果，迟到响应不可覆盖新请求。浏览器取消读取只取消请求，不取消后台健康任务。

## 5. 时间、幂等与复盘

09:25只冻结已完成复核且available_at不晚于cutoff的结果，未完成lane进入PARTIAL，不为等待模型推迟或改写盘前版；晚到结果进入后续日内版本。阶段新run且输入SHA变化才更新；16:30下一有效港股交易日草案的cutoff是当日真实时间。非交易日/半日用市场日历明确适用状态，不伪造全日结果。

相同目标日、phase、输入SHA、规则/prompt/模型版本和相关Stage run复用成功结果；失败尝试与成功产物分别保存。进程重启通过实际执行状态恢复或标INTERRUPTED，不能因浏览器超时杀掉健康任务。迟到计划标LATE_CATCHUP/实际时间，不声明自然时段已验收。

新snapshot不可变，保存后必须同run/SHA读回，指针仅指向完整已提交字节。输入快照记录原owner/SHA；旧历史字节不可改写，缺原始来源时展示验证缺口。新增回看另存RETROSPECTIVE，不覆盖旧计划。

复盘使用同日期、同市场、同权威范围完整收盘榜；Top20不进入盘前规则或调参。严格覆盖只计SELECTED，扩展覆盖计SELECTED与CONDITIONAL_WATCH；分母、交集与策略新增贡献分别列出。零分母不填0%，缺完整榜单不报完整Top20覆盖率。A计算，B保存/提供，C展示。
