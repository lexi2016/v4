# M03 · US行情来源：独立Chat交接

日期：2026-10-10。只对应原18模块中的M03，P2来源层。Chat负责方案和代码；嘻嘻负责现有Mac落地、独立测试、真实验收与反馈。此包是编码任务书，未修改产品、未执行测试、未采集或部署。

## 目标与边界
复用原US collector/slot及当前V5已存在的48件固定采集闭包，完成精确US session的真实采集、payload/receipt/manifest一致性、私有输出与下游来源引用。最小交付是一条来源生产和独立读回链，不是美股映射业务。
M15另有Chat：行业路径、个股关系路径、reviewed seed、四键映射、经理保存均由M15/M18负责。33只是已有配置/读取样本，不代表全市场；四键保存、读回、页面证据不能计为M03业务完成。

## 固定依据
- [总计划](https://github.com/lexi2016/v4/blob/24c6d60d524f43fcf4209ec8b078ec02cb34417e/V5/docs/superpowers/plans/2026-10-09-v5-master-delivery.md)，沿用01—18/P0—P5
- [迁移执行计划](https://github.com/lexi2016/v4/blob/d1bf034640ca2e5957423de2745a98e159b69af2/V5/docs/superpowers/plans/2026-10-10-v5-migration-execution.md)，M03条目
- [固定V5树](https://github.com/lexi2016/v4/tree/f7cb731c384ee6890a87d16c19a5b5a621779477/V5)，本包静态目标前像；不声称是Mac活动字节
- 既有审查包：[入口](https://github.com/lexi2016/v4/blob/d3578688995c7cf14edb3b771a36688e0558dc2f/handoff/v4-code-optimization-review-20261010/START_HERE.md)，仅作辅助，不替代本包准确源码树

## 已核事实与最小候选
S：V5/src/v5_shadow/cloud_us_collector.py已具完整原采集器装载、SHA核验、fresh-process约束、私有root门禁。V5/contracts/cloud_us_collector_sources.json列48件原件，固定source_commit=164c010c7eaa1659db9bfed0ff5f123c7a39eefc；不要重写provider/日历或将39件映射reader闭包冒作完整collector。
S：原run_us_market_slot.py只收窄运行catalog，沿原dispatcher触发，不拥有第二个producer。current_us_research.py明确“No source acquisition”，不可冒充来源接管。
R：迁移计划报告33只报价读取有证、自然采集未证。本包没有新Mac运行证据。
先核现有collector能否被模块私有入口调用；若缺仅新增us_source_daily.py及独占测试，封装已有原owner、生成精确来源binding。共享接线用变更请求，不能直接改调度、gateway或经理。

## 阅读顺序
1. SOURCE_MAP.md：现有路径、SHA、依赖和可写范围
2. PROMPT_FOR_CHAT.md：直接可粘贴的编码任务与交付要求
3. ACCEPTANCE.md：嘻嘻的Mac落地和五层验收

缺最新active前像不阻挡基于固定f7cb的静态候选；实际安装前必须核验active SHA、路径和发布身份。保留V4、8910、BUY门；不交易，不扩大权限或凭据访问。

