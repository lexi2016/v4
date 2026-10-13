# 20261014 A股次日预选池恢复

2026-10-13 主助手按用户明确要求直接处理，无子智能体、无独立 Reviewer；不声称独立 REVIEWED。源码根 `/Users/lexi/Desktop/学习/v4_app`，本地基线 `55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`，私有同步父提交 `113fd2ded3d9d08fc881d7fd8067caca1f44946f`。保留全部其他工作区修改、HK stage-center 与 Vibe8910。

## 本批结果

| 目标日20261014 | API及8873实页行数 | 状态 |
|---|---:|---|
| A股D-1主预选池 | 82 | V192_CANDIDATE_READY |
| A股D-1 Stage7/分时复盘池 | 10 | STAGE7_TAIL_POOL_READY_DATA_PARTIAL |
| A股D-1复盘继续观察池 | 56 | FUPAN_WATCHLIST_POOL_READY_DATA_PARTIAL |
| A股研究推荐池 | 191 | RESEARCH_RECOMMENDATION_POOL_READY；来源截至20261013 20:00 |

研究池从159更新为177，再随20:00材料到达更新为191。A股完整汇总去重292行；页面每页200行不代表后台输入上限。HK池100行及其SHA保持不变。所有行仅研究观察，production_allowed/buy_gate_updated/orders_sent=false。

## 根因与最小修复

1. 17:00的dispatch claim仍引用已退出PID9316，无完成回执；due判断只检查文件存在，永远跳过，而ExecutionLedger已有原子死进程回收能力。`infrastructure/scheduling/execution_ledger.py:113`增加只读判断，`ops/_run_v35_macos_scheduler_parts/schedule_selection.py`调用它；活进程、损坏记录及完成回执仍阻止重复，真正回收仍由既有claim方法执行。
2. 旧版曾将缺失占位写入正式A池键，后续真实产物遭不可变冲突。`infrastructure/preselection_pool_store.py`及`ops/materialize_scheduled_preselection.py`允许既有CAS恢复方法仅将确切EXPECTED_MISSING占位转为SHARED_VERIFIED_V192；已生成的真实正式A/HK结果仍不可覆盖。
3. 研究池随着小时资料累积发生合法变化，但同日materialize一概拒绝冲突。仅针对既有VERIFIED_HOURLY_RESEARCH producer允许来源小时集合严格扩展；同集合改变、缩减、其他池仍拒绝。复用现有目录锁、旧/新版本归档与事务日志，不新增producer或服务。

## 实际恢复与运行身份

- 使用原17:00调度入口回收死claim，原TDX及公式程序更新指针至20261013。5138只原始日线被接受；面板当日5126行，662只隔离，覆盖88.586%。公式PASS，但上游总体PARTIAL/A_SYNC_AUTHORITY_REBUILD_REQUIRED必须保留。
- 原V192 producer生成82行；原D1 producer从同日公共复盘和Stage7生成56/10行；原scheduled materializer恢复三个占位并更新研究池。
- 从当时现役manager-workbench v12 scheduler复制候选，仅投影本次四处修改；v11→v12并发发布已通过配置SHA变化发现并重基，其他改动保留。运行包与canonical的模块拆分不同，按函数级投影，未用旧运行包覆盖现役。
- 现役scheduler：`/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-next-pool-20261014-r2/app`。
- manifest SHA：`0d5d84c79a17c1f56b2a028f4cc6485abc8758dd52128f3852867df631ebd718`；LaunchAgent SHA：`e587f455e1bcf55ec094125c11bd787d032db5c2689396f009b81d366191b4f2`。
- 只重载com.lexi.v35.scheduler；bootstrap首次临时错误5，第二次成功，launchctl进程running。原A日更3600秒超时保持。
- 18:00实际scheduler固定时段复跑：`preselection_pools=SUCCEEDED`，正式A/HK gate READY，原池安全复用；回执`7da760814c344778919ad89234c360cb`。聚合dispatch仍FAILED，原因是同槽旧hourly_research的HOURLY_RESEARCH_INPUT_NOT_MATERIALIZED，不是预选池失败，不修改该历史失败。
- 17:30手动CLI初次未传入registry所需输入根，保留失败回执；随后使用完整macOS调度入口18:00确认预选池成功。1730运行图仍保留A部分数据与HK部分阶段证据缺口。

## 验证与证据

证据根：`/Users/lexi/Desktop/学习/agents调试/V4_A_NEXT_POOL_20261014`。

- `tests/test_a_next_pool_recovery_20261014.py` + `tests/test_macos_scheduler_hourly_catchup.py`：44 passed；实际发布候选目标回归5 passed。发布重基v12后四个改动文件基线与v11逐字节一致，复用相同回归。
- partial-read、pool-gap、next-day组合12 passed，1个旧mock断言FAILED；去掉本轮registry探查性改动后同测试仍FAIL，`baseline-test.log`保留。该mock返回空stdout而现有formal gate要求实际payload；本轮未扩范围修改。
- 首轮pytest44项完成后默认临时目录清理因旧目录权限报错；改为本批专用basetemp后44 passed正常退出。
- `source-sha.json`记录本轮前后SHA；`panel-summary.json`记录真实覆盖，原始行情及大回执不上传GitHub。
- `pool-publication.log`正式发布结果；`scheduled-replay-r3.log`及原调度receipt记录实际复跑；`api-pools.json`和`ui-pools.txt`显示精确日期与实际行；`ui-pools.png`是8873重新加载实页截图。
- IMPLEMENTED / INTEGRATED / DEPLOYED / API_VERIFIED / UI_VERIFIED。本轮是手动恢复及真实调度入口复跑；NATURAL_SLOT_UNVERIFIED，不能冒充明天按时自动完成。已有本聊天10月14日监控加入A池完整汇总消费及研究池最新材料检查。

## 自然验收

明早核对20261014三个池及更新后的研究推荐池，检查A股阶段实际消费完整汇总（不能限200），保留Stage7/复盘PARTIAL及研究旧材料缺口。固定条数仅为本次基线，不要求后续研究池永远191。若后续并行发布覆盖本批修复，只补本批差异并保留该发布的其他内容。17:00/17:30/18:00未来自然执行尚待真实回执；不得凭当前页面称全部自动化已通过。
