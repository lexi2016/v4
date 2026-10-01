# 9/30 HK D-1池为空的直接原因

2026-10-02普通只读接口仍返回A预选205/HK0；HK错误是主档日期索引缺失20260929。V35与V4配置共享根均无此日期主档；V35实际assets/hk_security_master/runs/20260929目录不存在。四个候选权威根的universes/20260929目录也均不存在，详见current_error_readback中的原件存在性receipt。

9/29晚间daily_materialize_receipts/20260929.json确认当天A/HK_CONNECT均FULL_TRADING_DAY，但build_hk_close_review=SOURCE_MISSING，detail=HK connect close snapshot missing；目标20260930的HK池仍0行。这个记录证明当天上游收盘输入缺失，不能证明原publisher具体为何没有产出9/29成员主档，首次回归提交仍CANNOT_CONFIRM。

已找到的9/29 Top100 READY run使用20260928信号/行情和9/28主档，适用于目标9/29；另有9/29盘前50股auction快照。两者均不是9/29收盘完整源或成员全量证据，不能改日期冒充目标9/30的D-1源。未通过调用今日Futu名单回填历史capture。

修复应同时处理历史缺口和今后自然链：恢复9/29原始全量资格证据与价格源后沿原producer形成主档/D-1池；若当地原件未保存，先用既有权威源能提供的真实历史来源恢复并保留实际获取时间。价格信号日按港股交易日；港股通休市期间的资格来源保留真实asof/capture而非跟随价格日期伪造。HKEX官方日历：9/29港股与南向开市；10/2、5、6、7港股开市而南向休市，周末10/3、4均休市。

另有新候选R3的独立集成失败：实际R9池存储器拒绝投影新增historical_provenance等字段；active19项12通过7失败，其中3项合同错误、4项夹具绑定错误。R3尚未部署，此缺陷与当前页面缺9/29原件的错误分别记录。A代码冻结、未重跑A阶段、未selection、未写原件或启停服务。
