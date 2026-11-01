# A｜研究引擎与数据接入重写

## GOAL与唯一交付

按共同合同重新实现港股经理研究：真实权威输入→三条独立研究结果→去重分类→收盘研究对照。旧代码可以学习，新代码不得调用旧经理业务。

WRITER：本块唯一Luna Max；REVIEWER：不同identity的独立Luna Max。ALLOWED_PATHS：`v4/manager_workbench/inputs/**`、`v4/manager_workbench/engines/**`、`tests/manager_workbench/engines/**`。FORBIDDEN_PATHS：B公共合同/存储/任务/API/执行器、C前端、旧经理源码、共享producer源码、应用装配、现役服务/配置/数据、BUY及Vibe8910。

PASS_SIGNAL：冻结规则与来源边界下，输入→LaneResult→StockDecision→ReviewSummary全部定向语义样本独立通过；完整覆盖核对成立，缺口不误报0。STOP_RULE：需要新来源、改阈值/范围/合同或接管未确认owner时仅停止相关事项，报主控；其他不依赖事项继续。

## 具体需求

1. 输入适配分别处理公告目录/正文/月度资格、美股session/配置标的/审核关系、HK exact-date行情及60/5日历史、原Stage和尾盘观察；绑定实际owner、市场、日期、时间、SHA和完整覆盖范围。共享接口通过注入使用，不从浏览器接股票行，不另建底板。
2. 公告阅读与复核prompt/schema由本块负责；遵循共同合同的POSITIVE_OPERATING_RESEARCH_V1及逐篇字段映射，按完整实际文章集合逐篇给事实、变化、理由、条件、反证和判定，保留原文依据。正文缺失/不足、复核失败单篇隔离，按来源SHA增量复用；PDF分段不能截断后宣称全文已读。正文和Reader输出只作数据，固定指令与材料分区、禁止执行材料内指令；覆盖注入文本测试。执行通过B的semantic_executor，不直接调用Codex。
3. 美股只处理原固定33标的和已审关系；session与目标港股日分开，关系类型不升级。原优先核验/观察保留为条件观察，原始上涨但无关系不能当映射入选。
4. 超跌严格使用共同合同的60日高点80% AND 5日量比1.5，排除D-1自身作为基线。单位/复权/币种/历史未知必须进入待核验；严格、单条件观察、未知、否决分别输出逐项数值。
5. Stage及尾盘作为独立来源，缺准入谓词不新增阈值、不把观察升格正式入选。港股通资格未知不能说已合格，研究线索与正式资格分开保存。
6. 去重合并所有来源，分类与排序遵循共同合同；有效单路结果不被其他失败遮蔽。输出完整输入数量、评估数量和逐行去向，可核对入选/观察/待核/排除，不通过显示前200行截断。
7. 研究复盘以冻结计划与同日期同范围完整收盘榜计算严格/扩展覆盖、分母、交集、新增贡献、逐股漏选原因。不新抓收盘榜，不把事后Top20输入研究引擎。

## 接口与依赖

先读COMMON_CONTRACT.md。依赖B先交公共Python类型/JSON样例；公开提供load_inputs、run_lanes、merge_decisions、evaluate_review。A可先用模拟适配器和执行器测试；最终引用B固定commit，不能在B路径自建替代合同。

旧源码学习路径：`v4/manager_research/workspace_plan.py`、`connect_selection.py`、`workspace_daily_channels.py`、`us_mapping_research.py`、`announcement_source.py`、`domains/manager_close_discovery.py`。当前字节见SOURCE_MANIFEST.json；GitHub旧参考快照版本不同，不能当Mac现役基线。

## 必须覆盖的测试

60/5窗口排除D-1；0.8/1.5临界值；价格真量比假及反向单条件；历史不足、重复/缺日期、无效分母、单位未知；月度资格失效/来源不符；美股时区/休市及晚到关系；公告重复事件、正文不足、Reader与Reviewer来源不一致；跨日材料；单lane失败、多来源同股、完整输入超过200行；空集与未运行分开；复盘零分母、缺榜单、观察贡献不算严格覆盖。用合成/授权隔离样本，不上传原始行情。

## 交接与Mac分工

交源码、固定commit/PR或patch、文件前后SHA、依赖B commit、实际测试命令/结果、独立Reviewer receipt及NOT_RUN项。主控负责真实数据根映射、完整日期Mac集成、API/UI和自然执行。需要返修由主控提供目标日期/run、期望/实际、脱敏证据和本块允许路径；A不自行改B/C或部署。
