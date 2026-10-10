# M11验收与回滚

本清单未执行。状态统一为：代码接入、真实数据通过、页面可用、自动接续、完整验收。五项分别登记；工程测试单列证据，不替代真实数据、页面或自然自动接续。

## 原回归与新增门

- 原tests/test_v4_intraday_research.py：六slot原聚合parity与API、8分钟边界、并发单写、FAILED_NO_REQUEST可重试、已请求失败不重采、旧/坏marker不重采、错slot不fallback、当前daily cache不冒盘中、stale cohort拒绝、跨进程、源漂移、symlink、publication中断、auction只读前日精确总结。
- 原tests/test_research_review_generation.py：精确日期/section、已有产物无显式replace不覆写、输出根不与external source重叠、原来源审计。
- 原tests/test_daily_research_review.py：精确日不latest、declared provenance不冒verified、缺配置/日期不符/symlink拒绝、只读API。
- 在完整原闭包根使用既有Mac解释器运行上述pytest文件，禁止在不完整单文件快照强跑；新V5测试名test_research_review_daily.py为拟新增。每批命令/退出码/日志单独留存，不把历史225或零散批相加。
- 新增GET前后state/cache/locks/job数量不变、模块重启与跨日、改input/config另身份、来源late截止排除、前成功保留、M09/M10复盘字段兼容。

## 真实Mac业务

1. 记录活动source/config/profile摘要、已有非秘密provider绑定、明确state/cache路径；实际秘密不进入补丁、日志或交接包。核V4及其他模块资产前后摘要不变。
2. 一个真实有效slot先贯通原输入→原聚合→artifact/manifest/receipt→独立reader；再按原六slot范围逐项证明。不可在周末或错过窗口用当前行情补造。
3. 保留真实请求发生状态；允许的无请求重试及成功复用不额外请求provider；未知必须阻断。失败不改已成功slot。
4. 日总结独立证明原模型/研究sections、真实市场时点、材料引用与精确日产物；公开读取同SHA，声明来源与验证来源不混。
5. 真实V5浏览器进入研究复盘/全天研究指挥台，切日、切slot、刷新、返回、缺slot、慢任务、重复点击；GET绝不生成。页面字段与API同run/SHA，记录真实URL、截图、代码版本。
6. 盘中下一适用slot/交易日自动触发按原合同验；日总结按实际授权触发，不强制新日任务。自然、手动、恢复各自标明。完整范围未齐不能签M11完成。

## 回滚与回传

唯一发布者保存M11旧/新代码与generation，通过平台expected-generation机制仅切本模块。失败只恢复M11指针/绑定/独立进程，保留尝试和新不可变证据；不删除marker重抓，不回写V4，不回滚其他模块。回滚后核已成功slot/总结sha及M04/M09/M10/M18接口保持。

回同一Chat：固定commit/patch SHA、原source与config身份、日期slot和attempt状态、输入/产物SHA、命令退出码完整错误、API/UI证据、前后根摘要与回滚结果。权限或真实绑定阻断明确写BLOCKED；未执行写NOT_RUN。
