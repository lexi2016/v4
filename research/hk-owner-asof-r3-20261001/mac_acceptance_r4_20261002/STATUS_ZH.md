# PR20 R4 Mac独立接续｜2026-10-02

固定代码46ff1ef2d86390a3f8a85c7b7d9e245f99f10897，直接父3bcb43884cfa54fecf6eea88b0450279ffd07ab5。29个交付Git blob/字节完整核验；两份运行前像匹配，补丁正向、回退、再次正向均与完整前后像字节一致。仅非活动R3组合副本应用，未改活动源码、配置或数据。未收到作者ZIP，直接从固定GitHub提交取得相同源码文件；不宣称已核ZIP的38成员/SHA。

指定Mac验收一次：当前服务Python3.14.6，原报告7项＋R4新20项，27/27、exit0。真实R9 facade helper重绑定、publisher/shared依赖路径/SHA已核验。真实代码执行，外部quote/源行/membership/subprocess仍为合成替身；实际provider组合全链未验。原两个代码问题在这个范围关闭，canonical全19未重跑。

独立REVIEWED=FAIL_P2_PROVENANCE_GAP，未见P0/P1。反例将eligibility_asof.natural_verified改成true后R9 store与Stage接受，正常shared reader则硬编码false。反例不证明正常producer产出true。完整独立receipt、结果和反例见review目录。

历史缺口的直接采集原因已定位：原9/29的1720三次dispatch回执可见FutuSDK连接ECONNREFUSED，TimeoutExpired/exit124；三个PID对应PENDING capture manifests，原raw文件均不存在。9/28与9/30完成回执READY，9/29无完成回执。stdout为原回执已截断片段，直接可见错误已足以证明连接拒绝，不推断当时OpenD退出原因或首次回归commit。

原最新HK面板9/29=0行；原VIPDOC检查713文件也没有该日记录；资格authority指针和主档索引缺29。普通只读API9/30仍A205/HK0。当前OpenD11111已监听，通过同一原Futu渠道只读取得HK.00005的9/29未复权历史日K一行，保存真实10/2获取时间与SHA，说明历史价格接口可用；未全量采集、未回写原权威数据，未证明历史资格/完整模型输入。

状态：TESTED=PASS（27项限定）；BEHAVIOR_VERIFIED=PASS_SYNTHETIC；REVIEWED=FAIL_P2；ISOLATED_ASSEMBLY完成；活动INTEGRATED/DEPLOYED=false；9/29历史恢复、9/30真实D-1物化、实际Stage/API/UI及自然运行仍未完成。此次API只读仅诊断当前未部署系统，不是R4验收。

后续集中任务见CHAT_NEXT_ZH.md：原历史价格回补与历史资格来源链、P2标记边界；不重开A，不造第二producer。三份原采集/资格代码已附original_source_for_history。真实selection/交易未执行；production_allowed=false、buy_gate_updated=false、orders_sent=false。
