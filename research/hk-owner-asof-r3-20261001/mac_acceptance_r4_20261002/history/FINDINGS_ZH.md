# 9/29历史来源核查

原配置的最新HK面板含9/28和9/30，9/29精确行数0；原VIPDOC reader检查713文件，9/29记录0。9/29资格reader报HK_CONNECT authority current pointer missing，旧池reader报主档索引缺20260929。原物化命令未生成、未执行。当前普通API仍A205/HK0，只读。

找到原采集层证据：9/28和9/30原HK研究面板完成回执分别READY；9/29没有hk-20260929.json完成回执。当天3条capture manifest停在PENDING，均缺引用的.capture.json。原dispatcher的1720三次失败回执中，SDK stdout明确ECONNREFUSED，随后TimeoutExpired，exit124，子进程PID21510/23959/26157与三条PENDING捕获run精确对应。日志stdout是原回执已截断的片段；可见片段直接证明连接被拒绝，不据此推断OpenD当时为何未监听或首次回归commit。完整源SHA及文件路径随receipt保存。

当前2026-10-02上海时间，原本机OpenD 127.0.0.1:11111已监听。用实际service Python/Futu SDK10.06.6608做一次只读request_history_kline（HK.00005，2026-09-29至同日，K_DAY，AuType.NONE，max_count1），return0，返回1条准确日期日K。保留实际获取时间10/2和原raw SHA。这证明原行情渠道现在可取一个9/29价格样本，不证明全量价格已齐、金额单位/原模型输入合同已验收，也不证明9/29成员资格；原权威数据未改。

下一目标应转到真正的历史恢复入口：原实时snapshot collector只能采当前snapshot；不能将当前snapshot、当前名单或今天capture日期改成9/29。需要沿既有owner/provider读取真实历史价量，并独立恢复可验证的历史资格/asof/原来源链，交原updater与物化器；保留实际获取时间并区分回补研究与原自然阶段。当来源齐备再生成9/30 D-1池，之后才能进行Stage与普通API/UI验收。

代码验收另由独立Reviewer执行，本来源核查不代替其结论。A业务保持冻结。production_allowed=false、buy_gate_updated=false、orders_sent=false。
