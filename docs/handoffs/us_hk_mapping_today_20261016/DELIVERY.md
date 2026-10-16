# 今日映射研究交付 · 2026-10-16

当前结果：futu_r1/REPORT.md 与 futu_r1/candidate_stocks.csv。基于用户新提供的667只港股/1003条关系库和富途官方市场快照，采集时间2026-10-16 18:27:31–18:27:32香港时间。只生成本次研究派生结果，未部署应用、修改自动任务或写入旧选股计划。

富途请求448个非OTC代码并返回448行，446行通过价格/更新时间检查；45个OTC-only代码隔离为接口不支持，2行时间无效。1003条关系守恒：515正向观察、185非正向、57缺报价、221未闭环、25排除，正向观察去重427只港股。正向定义为快照last_price相对prev_close_price大于零；盘前价单列且不参与排序。这不是全量精确20261015日K，也不证明港股盘前已可得或预测有效。原48报价的腾讯版本保留为前序结果。

独立Luna Max Reviewer对当前固定产物验收：TESTED=PASS；REVIEWED=PASS_WITH_NONBLOCKING_P2；BEHAVIOR_VERIFIED=PASS_OFFLINE_REPLAY。原始快照、请求/响应身份、全部关系字段和输出SHA已复核；CSV与报告离线复算逐字节一致。Reviewer没有再次调用Futu或消耗额度。

剩余限制：映射的事实独立验收/预测/历史PIT没有升级；港股通成员对照采用20261012快照，后续成员变化CANNOT_CONFIRM。独立审查记录一项非阻断P2：日K canary文件缺失或schema变化时，辅助CLI可能再次发起历史请求，schema相同文件的缓存验证也不充分。当前canary经SHA绑定及独立核验成立；本轮不再运行该采集命令。旧版replay摘要锚定P2也保留，当前旧版原始来源与live复核成立。

金融边界：RESEARCH_ONLY=true；production_allowed=false；buy_gate_updated=false；orders_sent=false。

源码根：/Users/lexi/Desktop/学习/v4_app。实际Futu SDK解释器：/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python；OpenD 127.0.0.1:11111。当前工作只写本交付目录，应用现役版本由其他工作更新，不以早前PID代表现役。

GitHub对应独立分支codex/us-hk-today-observation-20261016，基线66a2a8defb9b64591f8c1e0376c667164bb6bfc4；仅同步必要脚本、范围、精简结果与验收。原始行情、全量派生表、catalog快照、ZIP、账户、凭证及运行配置不上传。精确远端读回另见GITHUB_SYNC_RECEIPT.json。

同步范围补充：本次以已独立固定SHA的Futu R1为最终交付；R0生成器和旧writer receipt当前字节未获得对应独立PASS，不纳入本次远端源码同步，也不沿用历史PASS认证它们。R0原始输入与过程文件仅在本地保留。
