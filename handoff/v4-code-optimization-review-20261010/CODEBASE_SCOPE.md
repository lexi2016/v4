# V4代码范围与复用边界

日期：2026-10-10。性质：静态源码审查与优化提案，不是部署报告。

## 版本口径

本包没有一个可以代表全部Mac现役系统的单一HEAD。历史V4源码、V5保存的原owner闭包、10月10日外部候选分别记录，不能拼成“当前运行版本”。所有实际读取文件见各SOURCE_INDEX；每个判断引用其自己的commit/path，不以分支最新值取代。

主要历史入口固定于`f7cb731c384ee6890a87d16c19a5b5a621779477`下`handoff/v4-running-source-20261005/canonical/`。这里的历史副本用于解释职责和依赖，不能证明10月10日Mac部署了同一字节。V5 vendor仅是保存的原实现闭包，不等于新写的V4算法。

## 全范围地图

以下沿用V5总计划01—18作为跨版本对照编号，不声称V4恰好运行18个服务。R=仓库计划描述；S=本轮已读对应源码。未实际深入的部分明确保留范围，不拿经理三策略代替整个系统。

| ID | 职责 | V4原入口/边界 | 本轮深度 |
|---|---|---|---|
|01|A行情/公式面板|macos_research_panel_daily的A采集、原同步/公式authority|S入口，parts未穷尽|
|02|HK行情/主表/资格|同入口HK Futu采集、run_hk_0_2_authority；master/资格不同日期|S入口，真实单位/资格依赖未补|
|03|US来源|run_us_market_slot→us_market_digest→周边存储|S，见STRATEGY_SOURCE_MAP|
|04|研究情报归档|原小时、公众号、正文/OCR、archive owner|R范围；只深读三策略消费涉及部分|
|05|A预选池|materialize_scheduled_preselection→原各池builder→PreselectionPoolStore|S入口与发布|
|06|HK预选池|同入口build_shared_hk_0_2_pool，三日期|S入口与发布；模型未重新评测|
|07|A阶段|run_stage_center_nodes→stage_dispatch→原StageCenterRunner|S入口/调度；算法全闭包未穷尽|
|08|HK阶段|同runner，HK池/日历/恢复独立边界|S同上|
|09|A收盘复盘|原close-review/model/阶段归因|R，未对全模型做新审计|
|10|HK收盘复盘|原HK review core、当日源/模型|R，不能把旧成品读取认作新计算|
|11|盘中研究/研究复盘|run_intraday_research→domains.intraday_research.capture_intraday|S入口；域内部未穷尽|
|12|视频FUPAN|capture_bilibili_fupan及run_v35_close_review_node节点|S入口/节点分发|
|13|公告|目录→正文→Reader/Reviewer→导入→消费|S，见策略报告|
|14|超跌|原行情面板/历史/资格→原strict/near|S，见策略报告|
|15|美股映射|daily种子与行业/显式关系材料两路径|S，见策略报告|
|16|公开资料任务|原job/事件/取消重试|R范围，经理报告所涉及接口除外|
|17|尾盘发现跟踪|原尾盘source/发现与跟踪owner|R范围；不得等同超跌或Stage|
|18|经理账本/计划|日任务→原API owner→保存→普通读回/页面|S，见DELIVERY_PIPELINE_REVIEW|

原总计划参考：`V5/docs/superpowers/plans/2026-10-09-v5-master-delivery.md`。18模块及P0—P5不被本包优化事项替换。8910及独立模型训练边界仍是待核范围，本包不建议删除。

## 本轮额外源码发现与改进点

前缀C=`handoff/v4-running-source-20261005/canonical/`，固定commit见上。

1. **预选池已具备分lane隔离和保护正式键的逻辑，应复用。**
   `C/ops/materialize_scheduled_preselection.py:320—367`分A/HK市场与三日期；`485—532`对正式池EXPECTED_MISSING只记DEFERRED、不写占位占据不可变键；可选池恢复比较旧SHA；冲突逐项记录后统一报错。不要因“简化”改成一次异常全局清空或覆盖旧成功。
   该函数`428—467`直接组装的是六个A产物，CROSS_MARKET另外插入一个HK产物；总计划写“七A来源”不等于这个函数七个A输出。需沿上游聚合查清映射，不把文档计数当代码事实，也不据此直接断言少了一个生产源。

2. **模块拆分已存在，但大量入口只是globals转发外壳。**
   `C/ops/macos_research_panel_daily.py:142—169,453—528`调用parts并转发globals；`run_v35_close_review_node.py:435—460`转node_cli；`_run_stage_center_nodes_parts/stage_dispatch.py:4`依赖_namespace。只复制入口无法复现，必须固定完整闭包/合同/依赖。
   当前历史目录枚举的stage parts只有4文件，直接请求其`_namespace.py`返回404。结论仅为“这份历史快照不能证明依赖完整”，不是Mac现役必然缺模块。Chat应先核原manifest/其他正式闭包，不能现场编一个替代实现。
   改进建议：短期按已有manifest验闭包；中期每次只替换一个parts的显式依赖参数，保留原行为回放，不趁此重写所有模块。

3. **HK updater同步调用的超时边界需审查。**
   `C/ops/macos_research_panel_daily.py:530—539`使用subprocess.run(check=True,capture_output=True)，本函数无timeout，随后严格验证READY和through_date。静态风险是调用者可能被长运行阻塞；是否已被上层deadline保护、是否实际导致延迟，本轮未证。
   建议先查上层预算，再复用已有bounded-process机制；timeout须写attempt结果并查副作用，不能超时后盲重试已发布操作。保留through_date后置条件。

4. **阶段路径已有锁、attempt预算和deadline，不应新建一套通用重试。**
   `C/ops/_run_stage_center_nodes_parts/stage_dispatch.py:390—552`包含重复状态、重试上限、锁内核查和capture_attempt；`deadline_supervision.py:6—20`日历等待最多5秒。源码还含精确20261002恢复授权，仅限该事故，不能变成一般历史重算授权。
   建议按“候选池→阶段行情→原算法→不可变产物→页面”排查首个失败层，不调整slot/cutoff来追赶过期窗口。未录制历史输入不得用当前行情回补。

5. **视频长链已可分节点，ASR成功不等于最终研究成功。**
   `C/ops/capture_bilibili_fupan.py:22—40`命令timeout1800秒；`66—163`按锁定视频采集、音频、ASR，输出ASR_REVIEW_REQUIRED并明确ASR_STOCKDICT_NOT_RUN。`run_v35_close_review_node.py:421—432`已有8节点；其`node_cli.py:47—114`先核可复用receipt再执行和写回。
   建议优先复用节点和成功产物，隔离长任务与普通API；媒体glob与ASR文件存在检查的内容/时间绑定是否充分，需补专项负测，不能未经复现直接判安全漏洞。真实采集、本轮媒体/ASR/OCR测试均NOT_RUN。

6. **盘中入口已保留明确失败与安全字段。**
   `C/ops/run_intraday_research.py:14—44`绑定config SHA及source manifest SHA；领域错误返回2，未知异常也脱敏为INTRADAY_CAPTURE_REFUSED。建议内部日志保留脱敏关联ID/原因层次，UI继续不泄露路径、原provider响应或凭据。不要为方便诊断直接向页面返回整个trace。

## 本轮不做的优化

不重新训练选股模型，不改阈值/排序来制造命中；不新增消息中间件、18个微服务或整套新前端；不合并所有候选分支；不删除来源/PIT/身份校验；不上传真实正文、行情原件或任何凭据。当前包只含GitHub已有源码、审查文档和索引。
