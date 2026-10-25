# V4可读20日A股二选Top100描述统计

当前冻结结果：140个日期阶段格中134份保留名单、6个真实缺口；1340个实际股票×日期×阶段席位，1291个可评收益，266个参考Top100命中，49个未知。主率h/k=20.6042%；存在未知时整名单率h/n为null，h/n=19.8507%仅是补充观察参考匹配比例。参考集是既有可用研究面板同日QFQ收益Top100，全A历史成分/PIT/自然时点仍CANNOT_CONFIRM。最终独立验收REVIEWED/PASS，统计与生命周期闭环均通过。

每日7阶段数量和率见READABLE_20X7.md、daily_stage_metrics.csv；阶段总表见stage_summary.csv。每日唯一代码与跨阶段重复另见daily_unique_summary.csv。最近5日的340条实际逐票和1个缺口完整留在本地final_results/stock_stage_detail.csv与STOCK_STAGE_DETAIL.md，按要求不上传详细行情；其SHA记录在EVIDENCE_SUMMARY.json。

身份连接保留raw_code与resolve_provenance：generic A.######仅匹配exact-date冻结qualified ts_code唯一键；不按数字首位猜venue，不借收益或排名选票。原15条证券身份冲突保留UNKNOWN；其余29条原qualified-return缺口、5条新增无authority键分别单列。ordinary R2_SHARED已FAST_BIND/A_trio_verified=true且原backfill-only run-match字段为null时按其原验收metadata解释；不把原null伪填成true，显式false/缺trio/缺run-digest拒绝。

`source`执行版本为scripts/analysis_r3c.py，使用原accepted pandas pd.read_csv numeric parser、100*(close/pre_close-1)、收益降序/ts_code升序。原20日严格Top100成员及名次逐日parity全过。CONTRACT_R3C和FREEZE_RECEIPT_R3C记录实际执行路径及SHA，交付副本不重写其执行语义。代码冻结输入文件INPUT_BINDING.json留在原本机研究目录，SHA e754c98745e2c706744b06c8fbcc8323c0a68d326c1173b3936cef315bdb787d；复现需相同已绑定本地文件，交付不携带原始行情/API/trios。

运行顺序（仅在独立新输出目录复现时）：绝对PANEL_PYTHON执行analysis_r3c.py full，再执行project_delivery.py；前者不覆盖既有结果。后者仅移除相同resolve_provenance重复序列化列与明确名称来源文案，不改数值/席位/执行源。delivery/tests/test_final_focused.py将4个已运行focused cases原body合并并指向最终模块，供独立审核复跑，不包含7个未受影响旧测试。

失败历史保留本机：旧R2全UNKNOWN；R3误把ordinary null当false；R3B首次full在Sep18浮点rank parity门停止；R3C恢复原解析后full全通过。一项focused测试额外close断言写错，工具编排未据其退出码停止full，事实已记录；另存修正测试只改为pre_close==7.9，strictcache/rank断言不改且通过，full没有重跑。旧合同/失败测试/canary输入和所有旧统计/恢复/194原字节不改。

四个安全旗：research_only=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。Writer未commit/push，未执行API/UI/服务/Windows/194动作；集成和Git同步由主控负责。

最终登记：本路线route/event/execution/correction=1/26/8/0，8次实际执行全部终态，open=0、unregistered route=0、contract-only=1（旧缺date range登记被拒，无START、不计实际执行）。外部registry持久化CANNOT_CONFIRM。独立最终消息由主控转录，SHA300e74681b78b7a90ff7cdd85c6d7756e13bb55c8f2b1d6c9c548b513d525189；不是Reviewer签名文件。
