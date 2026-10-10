# M09 A收盘复盘验收与Mac落地

## M09专项验收

- 完整同日panel的market_summary上涨/下跌/平盘守恒，行业/角色/排序/情景树与原模型逐字段等价；固定概率作为原常量保留，不宣称已校准预测或训练完成。
- 输入日期、代码集合、重复code、行业缺失、NaN/非数/错误量额/收盘位置、SHA变更、采集/可用/cutoff顺序、休市、成员范围不明都有反例；不能静默过滤后把剩余行称全市场。
- 严格区分15:30模型历史标签、真实capture、15:00 PIT和16:05/17:10触发槽；旧标签不能倒填真实时钟。两槽各自证明输入准入/计算或幂等复用/保存/独立读回。
- 新增/迟到M12材料只能按真实available_at进入后槽新run；缺视频/阶段保持独立PARTIAL/CANNOT_CONFIRM，价格模型成功不被研究失败覆盖。M12节点失败不触发M09重写视频链。
- 原正式复盘文件及model、publication、reader、普通API与原ReviewView同run/SHA/目标日。不能以“模型返回200”代替所有正式材料验收。
- 后槽失败、进程中断、并发/重复触发、跨日、晚到材料、回滚场景保持latest_success，A发布/回滚不覆盖M10混合URL结果或V4原资产。
- 现有`test_a_close_review.py`9个test定义仅属S，本轮NOT_RUN；daily_close_plan和runtime catalog是计划/槽定义证据，非scheduler运行证据。历史回放/旧槽成功均属于R，不覆盖当前候选。

## 五层验收与状态口径

本文件是一张待填验收表，不是成功回执。本轮仅制备文档；产品代码改动、产品测试、Mac、部署、自然采集均NOT_RUN。S=固定源码事实；R=已有报告（不是本轮复跑）；U=未核。每层填PASS/FAIL/BLOCKED/NOT_RUN及真实证据；SKIPPED不计PASS。没有证据不计算进度百分比。

1. 代码接入：固定候选、前像SHA、唯一owner、原算法等价、负例和针对性测试。共享变更由唯一集成者合并；完整当前提交回归独立登记。
2. 真实数据通过：来源/成员资格/日期/时点可核；原算法计算→原owner保存→独立读回同run/artifact/SHA。fixture、RECORDED_INPUT_REPLAY、MANUAL_RECOVERY和自然运行分别记账。
3. 页面可用：真实普通API和原UI读同一结果。核日期/阶段/market、刷新、返回、缺数据、超时、重复点击与恢复；错误和过期可见，GET无生产副作用。仅URL或组件存在不计通过。
4. 自动接续：按原活动槽/窗口到时真实触发，输入变更新run；同输入重试不重算，跨日/休眠/重启可恢复，latest_attempt与latest_success分离。错过窗口如实披露。
5. 完整验收：以上四层、当前固定提交回归、单模块升级/回滚、另一市场无回归及连续两个适用交易日自然接续证据齐备。只此层可计“该模块完整完成”；材料包交付不是模块完成。

## Mac前像、应用、独验、回滚

1. 先只读登记Mac活动repo/分支/HEAD、工作树差异、进程源码和配置摘要、实际root、模块active generation、route→generation、原数据摘要、现有测试命令/锁文件。GitHub基线不是Mac前像，目录同名不证明同字节。
2. 校验候选完整清单与SHA、每个被改文件前像；新文件须确认不存在且无另一候选占用。前像漂移立即停止该补丁，输出真实diff给同一Chat重做。不得强套整文件、`reset --hard`、覆盖本地改动或为通过测试升级依赖。
3. 隔离候选目录/工作树及模块私有输入快照、输出root；保留原输入原字节。只在前像匹配后做补丁dry-run，再精确应用白名单，记录应用后SHA。不要直接覆盖V4、生产数据或跨模块输出。
4. 对固定候选按仓库说明运行针对性、原回归和必要整体回归；再真实输入等价、发布前独立读回、普通API和内置浏览器验证。逐命令记录开始/结束/exit、passed/failed/skipped、日志与SHA；任何未跑环节保留NOT_RUN。旧报告不拼成当前测试全过。
5. 唯一发布者采用现有不可变generation与expected-generation/CAS机制只切本模块；若需新worker，验证实际进程代码、root与端口后再切，不能改目录指针假定旧进程已重载。未核活动URL/端口不得猜或占用。
6. 故障立即只回本模块经核旧generation/worker路由，保留失败attempt和候选；独立读回并复验另一市场/API、V4与原数据摘要。回滚展示旧日期/版本，不能把昨日成功称今天完成。

## 统一反馈字段

模块ID、候选commit/包SHA、Mac前像及应用后SHA；目标日/信号日/资格来源日（不适用写N/A）、时区/日历版本、slot/stage、cutoff、source acquired_at/captured_at；输入manifest/SHA、原owner/版本、run/artifact/receipt/generation；触发类型与自然标志；完整命令/日志；原算法逐字段差异；API请求/响应摘要、页面证据；latest_attempt/latest_success；失败trace/最小复现；回滚前后身份；五层结论与剩余缺口。不要传凭据或未经需要的账户资料。
