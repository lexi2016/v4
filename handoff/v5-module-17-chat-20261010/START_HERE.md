# M17：尾盘量价发现与持续跟踪

日期：2026-10-10。原总计划M17/P4；早期盘点编号16，不能与原M16公开资料job互换。Chat负责具体代码；嘻嘻在真实Mac独立验收与V5预览接线，失败回原Chat修唯一实现。本包仅文档。

## 范围与依赖

保留原尾盘窗口发现、独立观察产物、已验证prior lineage与后续跟踪/失效条件。依赖M02原HK行情/master/资格和历史面板、M04已提交催化材料；late recapture原路径另依赖精确D1池（M06）。M18只读消费。M17与M14超跌daily、M07/M08阶段选股独立；源码名manager_close_rebound不代表可用M14结果冒充15:30观察。

原首次观察与持续更新必须一起交付，不能只有“尾盘tab能读旧输入”。候选是否符合仍按原owner规则/量纲/未知条件；不扩股票范围、不调整阈值、不升级BUY。

## 已核现状与必须分开的两条原路径

固定f7cb731c384ee6890a87d16c19a5b5a621779477完整树无close_discovery_daily.py。原canonical有materialize_manager_close_discovery.py、manager_close_discovery/rebound/catalyst_tracking、独立reader及executor；V5的workspace_discovery/manager_panel_observation是别的已存在投影，不能当本模块新生产。

1. 原1530现场路径：prepare_universe是15:00依赖准备，不产生1530快照。materialize仅当前日期、原HK Connect整日；15:30前pending，缺快照且到15:32即窗口错过，实际返回时间也必须早于15:32。恢复只能复用当时snapshot及pre-capture历史witness，不能拿新面板回造过去。
2. 原PYTDX_LATE_OBSERVATION模式：原executor明确禁1530 Futu capture及1500准备，1555阶段后接recapture；取15:45—15:55原分钟窗口并单列close_recapture产物。此产物不是15:30现场，也不是最终收盘；币种/量纲未核等限制保留。当前Mac模式必须先查，不同时启动两套采集，也不自行改运行模式。

原持续跟踪只接受经完整validator证明的prior产物，不接受松散symbol JSON。保留first_seen、last_seen、新催化变化、失效条件和证据。原R2中放量/历史位置缺authority仍unknown；原V3观察门使用自己的rule与phase，不改成M14 daily结果。

迁移报告称完整owner尚未接入、历史首次窗口receipt缺口；本包已进一步静态定位donor，但不等于活动Mac完整闭包或生产通过。

## 独占写入根

拟新增V5/src/v5_shadow/close_discovery_daily.py、V5/src/v5_shadow/close_discovery/（确需拆分）、V5/tests/test_close_discovery_daily.py、V5/contracts/close_discovery_source_manifest.json、V5/vendor/close_discovery_baseline/。先核闭包和源SHA；这些不是现有服务。

运行仅M17私有workbench_research/输入/receipt/attempt/跟踪产物与版本引用。M14/M16/M18写根和冻结共享vendor禁止改写；可只读消费源副本。前端、gateway、scheduler、共享reader绑定由统一集成者串行修改，本Chat只交接口请求。保留V4/8910、不交易、不改安全/凭据访问。

活动mode未知不阻挡静态适配候选：按两条固定原路径交代码及契约测试。生产入口必须显式绑定已核mode，unknown拒绝执行，不默认选择、不同时双采；实际mode由Mac部署前核实绑定。
