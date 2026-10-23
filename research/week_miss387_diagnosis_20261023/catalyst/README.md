# 共同漏选387条：催化证据投影

研究范围为既有5533代码研究池，非认证历史全A，历史资格/别名/PIT仍未认证。

数据只写项目根的 `research/week_miss387_diagnosis_20261023/catalyst`。先有Registrar真实RUN_STARTED，再做只读缓存及新闻查询。没有修改应用、共享缓存、公式、服务或交易状态。

本目录仅保留必要源码和精简统计。原始网页、早报全文、387条完整证据表、查询响应、registry与日志不得上传。代码中的本机路径是已冻结研究合同路径，不是可迁移数据源或第二producer。

运行（项目根，Mac）：

```sh
python3 worktrees/week_miss387_diagnosis_20261023/research/week_miss387_diagnosis_20261023/catalyst/cache_and_plan.py
python3 worktrees/week_miss387_diagnosis_20261023/research/week_miss387_diagnosis_20261023/catalyst/build_evidence.py
python3 worktrees/week_miss387_diagnosis_20261023/research/week_miss387_diagnosis_20261023/catalyst/verify_evidence.py
node --check worktrees/week_miss387_diagnosis_20261023/research/week_miss387_diagnosis_20261023/catalyst/query_orchestration_reference.js
```

`build_evidence.py`、`verify_evidence.py`完全离线，复用已封存响应。`query_orchestration_reference.js`记录Codex只读查询的构造与分批方式，不能作为自动调度器独立运行。查询条件与本次实际响应SHA在本地 `SOURCE_QUERY_LEDGER.json`；不重复已完成的729次股票查询。

“公开报道背景”只代表经原始页面、内容和Unix时间戳核验的行业/题材关联；不代表事件造成收益，也不解释公式漏选。仅有价格或连板事实不会升格。公司PDF日期不替代首次公开时点；例行现金管理、风险提示与候选利好分开。盘中、信号前3交易日已知、后续回溯材料分别映射。

当前为Writer交接；独立Reviewer验收与ROOT同步另行记录。`RESEARCH_ONLY=true`，其余三个交易/生产旗均为false。
