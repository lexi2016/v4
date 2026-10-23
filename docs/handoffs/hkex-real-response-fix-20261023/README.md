# HKEX 两处真实 P1 修复交付

两处P1在冻结范围通过独立验收：174/174测试，原82项全部保留；旧前像对真实HTML的拒绝已复现。源码复用2026-09-28既有候选，本批未重写业务代码。

2026-10-23仅执行一次HK.00002原窗口历史协议查询。真实session shell、四个空ALL POST、完整sentinel回显及sentinel GET均通过；实际目录HTTP200，1页0行、0正文，非空正文验收未通过。原store/query只读回验通过。没有重试，也未扩大公司、日期或预算。新抓取时间不能证明9/28 cutoff前可得。

结论：两P1协议修复已TESTED/REVIEWED/BEHAVIOR_VERIFIED；未证明非空正文或经理台采用，未集成到活动运行时、未部署、未做API/UI/natural验收。详细机器结果见RESULT.json。

- 独立离线receipt：`/Users/lexi/Desktop/学习/agents调试/HKEX_REAL_FAILURES_REPAIR_20261023/reviewer/VERDICT.json`，SHA `4747e5f51ac5d4220b42f44d2e97063401e4a31e0a4f737c0409ffaed863e685`。
- 独立线上只读receipt：`/Users/lexi/Desktop/学习/agents调试/HKEX_REAL_FAILURES_REPAIR_20261023/reviewer/ONLINE_READBACK.json`，SHA `48bc427c54c750d9b2996f39f648925783581d2a5113806731c6dd68df51abfb`。
- 完整本地依赖快照：`/Users/lexi/Desktop/学习/agents调试/HKEX_REAL_FAILURES_REPAIR_20261023/candidate`；库存文件SHA `f22b7d4dae8e9cde0cc8221ede3c60956fa72894d414c5206c31ac763d97cc75`。
- 本地before/after、最小patch、回退说明和测试日志：`/Users/lexi/Desktop/学习/agents调试/HKEX_REAL_FAILURES_REPAIR_20261023`。

工作树只保存3份必要源码/测试及精简索引/结果。原始响应、fixture和MaterialStore不进入远端allowlist。测试需使用完整本地快照；本地交付ZIP附必要HKEX fixtures和实际查询证据，但不包含完整历史runtime依赖，外部依赖详见RESULT.json/EXTERNAL_FIXTURES.json。

实际Reviewer执行命令（详见reviewer/EXECUTION.json）：

```sh
env -u PYTHONPATH PYTHONDONTWRITEBYTECODE=1 '/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' -B '/Users/lexi/Desktop/学习/agents调试/HKEX_REAL_FAILURES_REPAIR_20261023/reviewer/run_review.py'
```

源码SHA和适用前像见SOURCE_PINS.json。本地Git基线55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054缺少这些历史模块；patch仅适用于问题包current_source，不直接覆盖canonical。GitHub同步由主控独立完成，本文不冒称已同步。

安全旗：RESEARCH_ONLY=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。
