# 原日更链的有界提速与Top200失败隔离

Writer已完成针对性检查与Main候选准备，独审、安装、正式身份及未来交易日17:00自然验收均NOT_RUN。基线`c9a46c1138eb212051be0160083ac84715c1c54c`；独立分支`codex/daily-before1700-20261105`。仅5路径。3个ops模块在Git基线缺失，因此从现役Main精确字节纳入，再做最小差异；运行依赖来自实际Main克隆，未向Git补旧源码树。实际父本差异与SHA在本批ACTUAL_PARENT_SOURCE.diff/SCOPE_CAPSULE.json。

日包资源规划保留每worker4GiB估计，最多14worker/28pending；作业guard为min(80GiB,物理RAM的5/8)，在当前128GiB机器为80GiB。仍按实际可用内存减24GiB系统余量、实际父子RSS选择并发，内存降低自动降级，运行中超guard或低余量停止提交并排空、保存checkpoint。依据D04/D05的18核128GiB、初始93–94%可用及38.5–49.2GB累计RSS；本轮当前82%可用。没有减少每worker预算或绕过原压力检查；公式原4worker硬门不动。

原PNG owner仍用一个headless browser/context，最多2pages并发；原symbol/date/行数/51变量/22绘图/可见canvas/错误检查逐张保留，finally关闭page/browser。3市场代表600007.SH、000035.SZ、920007.BJ，新旧实拍PNG与已接受D05原PNG逐字节SHA一致。基线→候选→候选→基线交叉小批，平均1.7926秒→1.2300秒，观察缩短31.38%。只代表此3图样本；14worker整日吞吐未实测，不宣称已保证17:00。

历史回执generation/input/snapshot/selectorSHA验证后，旧Parquet缺失才抛typed `HistoryPriorPanelUnavailable`。只有这个失败被隔离，原当日Top200 build/stage/publish继续；整体derivatives保持CANNOT_CONFIRM并保留history原因，history_view不伪造完成，F10不因此晋级执行，原immutable失败attempt保留。其他未知输入缺失、身份漂移及history partial仍按原路径阻断。正常完整history/F10路径回归通过。公式、排序、收益、日期与未知口径不改；D05已有141完整/223部分和970UNKNOWN未重算或改写。

实际Main解释器`runtime/retirement-main-20261028/venvs/v4-mac/bin/python -B -S`，使用实际Main clone依赖，8条针对回归PASS：资源/降级/pressure drain与checkpoint保留、typed缺件/身份冲突/非typed错误、正常F10。未重跑D05整批、未网络采集、未改canonical数据。候选从现役1017实际文件APFS克隆，仅3源码delta，1014非delta字节保留；Main拟议plist及原字节rollback已备。原slots15:40/16:10/16:40、14400秒外层timeout、1800秒源预算保持；API/Stage/observer/US/Vibe未动。

产物目录：`/Users/lexi/Desktop/学习/agents调试/v4_daily_before1700_20261105`。独审由Root安排；Root负责idle/原锁下Main安装、身份与自然运行验收。未来交易日按17:00目标记录实际结果，源未就绪或未完成仍如实CANNOT_CONFIRM。RESEARCH_ONLY=true，production_allowed=false，buy_gate_updated=false，orders_sent=false。
