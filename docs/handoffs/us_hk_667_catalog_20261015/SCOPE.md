# 本轮范围锁与证据边界

GOAL: 将用户实际回包派生为现有V4经理工作台可查询的只读美股→港股研究目录。
WRITER: /root/mapping_catalog_writer (gpt-6-luna, max)
REVIEWER: 另一identity的独立Luna Max Reviewer，待Writer交接后派发。
ALLOWED_PATHS: v4/manager_workbench/us_mapping_catalog.py、research_data/us_hk_667_catalog_20261015.json、v4/manager_workbench/api.py、现有apps/web/src/manager-workbench内必要最小catalog读取/显示/测试路径、tests/manager_workbench/test_us_mapping_catalog.py、本交付目录。
FORBIDDEN_PATHS: 选择引擎、评分、阶段、BUY、模型/池门禁、行情producer、Vibe 8910、服务和全局配置、其他并行修改。
PASS_SIGNAL: 667原序代码/名称与1003原始边可追溯且无状态晋级；源损坏可诊断拒绝；现有API/页面查询可用；针对性测试及独立Reviewer通过。
STOP_RULE: 输入破坏或超出权限保留具体缺口；已通过冻结范围停止扩展。

输入ZIP SHA256: dac3c820fcd6919fabdccc9c37ee9055b729b200fcde5e48f0dcf527de81bc6d。
原名单SHA256: 9b799c0b74ac5047f4e44a1b3dfd1dfa5ca9ce978fa3b8e7877913c423424c9c。
来源是2026-10-14名单快照和用户上传研究成果；不把它当10月15日最新港股通名单或当日触发结果。
原材料内REVIEWED为来源自述，独立事实核验另列pending；全部预测UNTESTED，historical_PIT=NOT_VALIDATED；旧997边矩阵比较NOT_RUN。

源码身份: /Users/lexi/Desktop/学习/v4_app，codex/system-consolidation-20260912，55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054。本轮前已有大量tracked/untracked修改且未配置Git remote，不能把整份工作区当本轮diff。
运行身份只读观测: pid77916，127.0.0.1:8873，cwd /Users/lexi/Library/Application Support/com.lexi.v4.local/releases/d1-pool-market-api-20261015-r1/app。源码候选不等于已部署版本，本轮不重载8873。
当前owner: /api/v4/manager-workbench，v4/manager_workbench/api.py。旧apps/api/v35_api/manager_workbench_router.py是另一接口，不在本轮改动内。

远端另有codex/us-hk-667-local-canary-20261015，输入是旧问题包0c824c6a…，记录local-model/search失败且bulk未解锁，与本次实际回包dac3c820…不同；不复用为本次关系验收，不重启其任务。

RESEARCH_ONLY=true
production_allowed=false
buy_gate_updated=false
orders_sent=false
