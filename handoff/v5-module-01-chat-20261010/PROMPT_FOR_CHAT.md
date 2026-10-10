# M01编码任务 · 原A源与公式generation接续

你负责原M01一模块方案和具体代码。先核SOURCE_MAP所列固定文件与imports闭包，交最小候选，不重新设计行情或公式算法，不要求你能连Mac。

## 最小工作范围
1. 固定target/source trade date、原A市场日历、cutoff、实际取得时间、universe/源数据/配置/owner摘要。M05前一交易日逻辑由原日历消费，不用HK日历替代，不把休市日期写成READY。
2. 先用原owner核验已成功日线与公式generation，复用其pointer/receipt/manifest；同源不重复抓取。面板、源行情和公式版本需相互绑定，旧日面板不得只改日期用于新日。
3. 新a_source_daily.py只适配原authority流程到V5私有输入副本与输出binding，调用原sync/manifest/formula/readback，不重新算公式/复权/字段单位。原provider/Windows脚本实际不可用时准确阻断该生产步骤，静态候选继续。
4. 保留字段单位、coverage、重复/缺失交易日、增量起止和xdxr证据；原through-date与目标日需一致。源成功而公式失败分别记状态，失败重试不盖旧成功；同输入幂等，输入变化新identity。
5. 依原bounded execution/预算执行，不无限等待或超时盲重试；先读原run/副作用。清楚区分RECORDED_INPUT_REPLAY、MANUAL_RECOVERY、自然运行。
6. M05/M09只读已提交来源binding。你不写它们的算法、池/复盘存储，不改共享UI/API/gateway/调度/contract注册；集成需求给变更单。

## 测试必须包含
原有有效generation复用、错日/旧pointer、raw/manifest/receipt篡改、units异常、源范围缺口、重复日键、输入变化、公式失败保留源与旧成功、中断后接续、窗口外/非交易日、来源输出重叠/越界/符号链接。真实原件只在Mac验收，没原件标NOT_RUN；不能合成一个绿色采集回执。

## 必须交付
1. 唯一固定candidate commit或完整候选包、base ref、donor→现有V5目标映射；已等价实现不改。
2. before/after完整修改文件、runtime.patch、reverse.patch；每文件Git blob SHA、before SHA256、after SHA256，新增文件before=ABSENT，删除说明用途；不编造未来after值。
3. 依赖/私有输出/输入manifest清单，原算法等价用例与失败用例源码，原始测试命令/环境/退出码/日志；没有真实数据时标NOT_RUN。
4. 共享变更单INTEGRATION_REQUEST：共享目标路径、before SHA、调用方、接口与日期/cutoff/失败语义、向后兼容、验收方法；统一集成者实施，Chat不附共享文件覆盖补丁。
5. MAC_APPLY_AND_ACCEPTANCE：前像检查、隔离应用、必要回归、真实输入/独立读回、API/页面、唯一发布窗口及单模块回滚。部署路径/端口未知时列现场核实项，不猜命令。
6. 五层分别报告代码候选、Mac工程测试、真实业务生产/保存/独立读回、API/原页面、自然接续与回滚。历史测试不相加，不冒称本轮运行。
缺当前Mac active前像不阻挡固定f7cb静态候选；嘻嘻安装前核active SHA。不要要求Chat连Mac，也不要向用户索取已有GitHub材料/整库/凭据。保留V4、8910与BUY门，不交易，不扩大安全权限或凭据。

