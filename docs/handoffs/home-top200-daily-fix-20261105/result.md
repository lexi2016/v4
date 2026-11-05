# 首页9A读取已完成的新交易日

Writer针对检查PASS、候选准备中；独审、正式API切换/UI与未来自然日更NOT_RUN。基线`c5e3a70ad489894e8860c28c83d48331bfeb4f54`，分支`codex/home-top200-daily-fix-20261105`，仅冻结6路径。Main、Stage、observer、US与Vibe未动。

根因：首页9A只在挂载读取打包的/top200-hit.json，文件生成于11/04、日期列表截至11/04；旧mapper只遍历该列表，没有日更owner调用。D05的同日Top200与全池已存在。现在既有preselection_router提供一个精确date只读投影，复用同一PreselectionPoolService完整分页、已保存Top200/numeric身份和原project_date归因核对；不排行、不运行公式、不写新产物/index/event、不新增producer/timer。

9A按当前props.date读同源API；切日先清旧日数据，schema/requested_date校验前不展示旧响应，serialguard隔离迟响应。已接现有`/api/v4/research/workbench/days/{source_date}/events`的真实`workbench_completed`事件；只接受同source_date且新event_id。打开、切日、focus/visibility也读已保存来源，卸载关闭stream/listeners，无新timer。旧已接受日期仍以精确历史静态快照及原stage引用为输入，明示来源，不用latest替代缺日，也不重跑旧日期系列。

Root保存DTO与已接受Top200核对：D05 200行、全池382、命中32；D04 200行、全池379、命中24，分别完整读取offset0/300。D04原5/7阶段冻结引用保留；D05既有selection_latest未物化0/7，阶段与命中UNKNOWN保留。一个坏stage仅隔离该stage；缺/错日期、池fingerprint/sourceSHA、榜单numeric身份冲突闭合。仍是研究事后交集，非PIT/收益认证。

检查：Python14 PASS；Vue8 PASS（新日/200分页/旧日保持/切日迟响应/错误日期/现有事件与focus去重及卸载）；正常Vite build PASS。首次真实DTO发现pool API的推荐状态合同是WATCH_ONLY_BACKTEST_GATED而非另一API的RESEARCH_ONLY，已修为原精确合同并验证read_only及全false安全字段，失败记录保留，原DTO未改。API clone应只加入现有mapper/原router差异/组件与正常build主入口；原静态JSON作为历史输入保持原字节，候选manifest按actual文件计数、真实commit及non-delta证明绑定。缺于Git基线的router从现役API exactbytes纳入，未复制整树到Git。

证据：`/Users/lexi/Desktop/学习/agents调试/v4_home_top200_daily_fix_20261105`。唯一独审由Root安排，Root负责正式API/UI与回退。未全历史重算、未新增采集、未改Main刚发布的实现、未涉及模型/因子/图形筛选。RESEARCH_ONLY=true，production_allowed=false，buy_gate_updated=false，orders_sent=false。
