# 给原Chat的集中接续

请接续PR20。先读本目录STATUS_ZH.md、review/REVIEW_RECEIPT.json、history/FINDINGS_ZH.md及original_source_for_history/SOURCE_BINDINGS.json。Mac已独立验证46ff1ef固定代码的原7失败＋新增20项：27/27，exit0；原R9字段与facade helper问题在限定合成链关闭，不再反复改这两处。

现在集中解决真实历史恢复：9/29原Futu采集三次ECONNREFUSED、TimeoutExpired/124，只有PENDING，没有raw或完成回执。当前11111恢复、单股request_history_kline(HK.00005,start=end=2026-09-29,K_DAY,AuType.NONE)已真实取得1行。原snapshot collector只取当前快照，不能直接重跑改日期填过去。请在既有owner/provider/updater中补齐真实历史读取/回补入口，保持价格单位、复权、日期和原模型合同；记录真实获取时间10/2，不能伪造9/29 capture。原配置面板及VIPDOC都缺9/29。

独立恢复9/29成员资格：优先验证原9/28完整capture和官方生效变更记录是否足以形成9/29可追溯资格链，沿既有恢复机制；否则明确具体尚缺的官方/原始证据及唯一获取入口，不用今日名单、9/28 Top100或盘前50股冒充。保留真实asof/capture、manifest/run/SHA与不可变产物边界，不越过旧key覆盖。区分历史研究回补与自然运行，来源齐备后Mac再执行原物化，读回9/30池与Stage/API/UI。

另有可复现P2：人为把eligibility_asof.natural_verified=true，R9 store和Stage接受；当前来源reader明确false。请核对该producer合同后最小修复这个不一致，并给负例；不得把它扩成新来源/授权/BUY机制，也不能声称正常producer已经产出true。

代码由本Chat完成，Mac负责交付与独立测试。返回固定commit、精确前后像及patch/rollback、限定验收脚本和原入口的历史恢复命令。新变更只复验受影响范围；A保持冻结，不重跑A/全仓库，不部署或真实selection，不创建第二producer/面板。若历史资格仍无法证明，明确唯一缺件和owner，不把接口样本或27项通过写成数据已恢复。
