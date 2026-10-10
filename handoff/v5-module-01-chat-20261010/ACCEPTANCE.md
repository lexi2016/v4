# M01 · 真实Mac验收与状态

本轮是文档交接，以下均为未来步骤。

## 嘻嘻执行的前像与发布检查
1. 现有Mac确认实际checkout、HEAD、解释器/依赖锁、V4/V5进程与模块活动数据根。逐文件SHA256与候选base对照；不把canonical历史副本当运行字节。
2. 核patch仅含本模块白名单，前像不符暂停该安装并将具体差异回同一Chat；静态候选可继续准备，不强盖。隔离目录应用，记录应用前后SHA256及新增文件。
3. 使用原项目解释器/依赖执行候选指定定向测试和受影响回归，保留成功/失败/跳过/NOT_RUN；fixture只证明对应工程行为。已有未变成功证据只引用，不为增加数字重复跑。
4. 私有输出root核marker/symlink/源输出不重叠，真实输入只在Mac用；不清现役成功、不上传原始敏感数据，不启用交易。共享UI/API/调度/contract改动由统一集成者处理。
5. 实际发布由唯一窗口完成；安装新候选前后查模块身份、API run/SHA、资源构建身份与原页面交互。失败回滚仅本模块，核V4/8910及其他模块可用；服务地址现场核实，不猜端口。

## 模块专项步骤
6. 从现役原流程取得一个真实A交易日的universe、日线/VIPDOC、sync receipt、公式input manifest、generation pointer、selector-ready面板、实际owner/配置SHA；登记活动根。分别验证“源采集”和“公式计算”身份，不能只看CSV存在。
7. 对已有成功先复用并核对前后SHA不变；确缺输入才沿原owner合法取得。原Windows authority不可用时保留具体脚本/调用/错误，不以另一个provider或简化公式替换。
8. 同日原owner与V5包装结果做完整行/列、代码、日期、单位、公式值及来源身份对照；仅预先声明的封装/私有root/metadata差异允许。坏单位/源缺口必须准确拒绝。
9. 将已提交来源binding交M05/M09，独立读回同日来源；来源API完整活动路径未核，不编造端点。统一集成后原页面展示日期/旧成功过期/错误，刷新与返回不触发重采。
10. 下一适用A交易日真实增量接续，并覆盖重启/失败恢复。两个连续适用交易日的自然运行单独留证，手动恢复不可充数。回滚M01不会改变其他模块及V4数据。

## 五层登记
- 代码候选：本包任务书，NOT_CREATED
- Mac工程测试：本轮NOT_RUN；旧报告只标R/原commit
- 真实源→公式→保存/独立读回：本轮NOT_RUN；现役root与authority绑定待核
- API/原页面：本轮NOT_RUN；独立来源API精确地址U
- 自然接续与回滚/完整M01：本轮NOT_RUN；不计完成

反馈：commit/锁/trigger_kind、target/source_date/cutoff、实际取得与运行时间、raw/manifest/receipt/pointer/panel SHA、原owner差异、下游run、API/页面录证、回滚前后身份和精确阻断。

