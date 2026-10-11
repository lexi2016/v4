# 三路本地修复发布与页面验收

已按执行方案发布8873并实际重载页面。已部署release-candidate-20261011-r1，manifest SHA f2940d02d408b52bde35258b2366e32a4b7e3ad59193b313b243677d590eae1d。实际PID3299/cwd/8873监听与清单一致。保留1033个非增量文件。未改scheduler/Vibe8910/交易门禁。

## 20261009页面实际结果（公告日20261008）

| 路线 | 页面结果 | 例子 | 限制 |
|---|---|---|---|
| 公告 | PARTIAL：55研究候选、32观察、73未评估 | 弘海高新资源00065、保利置业集团00119、江苏宁沪高速00177、协合新能源00182、东岳集团00189 | owner回执已核；事后研究，不能证明盘前可得 |
| 港股通 | CANNOT_CONFIRM，暂无可核验名单 | 无 | 原Stage日期/市场不匹配，目标权威D-1池缺失 |
| 超跌 | PARTIAL：214研究候选、286观察、34待核 | 吉利汽车00175、新濠国际发展00200、华润啤酒00291、潼关黄金00340、敏实集团00425 | 缺量纲及完整历史证据；run/product身份缺失；不是正式Stage |

55与214数量在部署前已存在，不是本轮新产生。完整研究名单CSV和页面截图留在本地。formal/focus均未产生可核验名单。

历史视图仍SOURCE_FAILED，错误由HISTORY_RUN_BYTES_BOUND_EXCEEDED变为HISTORY_SOURCE_VALIDATION_FAILED；动态旧计划仍STALE_INPUTS_CHANGED/consumed=false。本轮不宣称三路目标完成。剩余问题及复现验收要求已提交 https://github.com/lexi2016/v4/issues/34 （关联#29/#32）。自动计划仍引用旧发布根，自然时段未验收。

## 验证和源码边界

独立验收：Python97 passed/1 skipped；公告TS7/7；Vite构建输出与发布产物一致。Vitest58 passed/1 failed，失败同断言在基线复现，不归为本批新增。发布前修正版本身份、Python依赖路径，正式发布复用现役v2 flock/CAS；初次旧存在式锁在写入前失败，未改服务。

canonical本批29个变化路径已做有限语义合入并记录前后SHA，但完整集成仍CANNOT_CONFIRM：缺owner_plan_readback导致部分测试无法导入，另attention卡片测试失败归因未确认。runtime_source为实际独立通过并已部署代码；canonical_source只保存与它不同的本地修改，不得混称完整验收的同一源码。未在范围外扩修。

状态：候选IMPLEMENTED/TESTED/REVIEWED，实际DEPLOYED/API_VERIFIED/UI_VERIFIED（仅证明所列状态和研究名单）；三路业务目标PARTIAL/CANNOT_CONFIRM，NATURAL_SLOT_UNVERIFIED。RESEARCH_ONLY=true；production_allowed=false；buy_gate_updated=false；orders_sent=false。
