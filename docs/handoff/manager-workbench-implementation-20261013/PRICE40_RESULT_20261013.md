# 超跌价格门槛改为低40%：V13正式验收

用户明确把低20%改为低40%。新规则：前一交易日收盘价不高于此前60个完整交易日最高价的60%，并且前一交易日成交量不低于此前5个完整交易日均量的1.5倍。两个窗口均排除被测日自身。未增加上涨、止跌形态、资金流或评分条件。

## 正式结果

- 20261013目标日、20261012行情；RETROSPECTIVE事后回看，非自然盘前。
- 新规则版本POSITIVE_OPERATING_RESEARCH_V1_OVERSOLD_PRICE40_V2。
- 新run3756008d713a4505be362d288ab9d504，product SHA ea861110156f5a2c3dc8249d145e09ebc94b310f165d4cac81c4e015b10b00aa。
- 超跌692只范围，662已评、30缺口；20入选、277观察、365未通过。相同输入原20%版115入选，改40%后20入选。
- 赛力斯HK09927：收盘38.92，新价格门槛48.98×0.6=29.388，价格条件未满足而量比满足，转为条件观察。旧run84eafbbb71ba4767a591d1a4286fe061仍保留0.8门槛39.184及原入选判断。
- 美股保存结果不变：33来源标的，0入选、0观察、4未通过、29待核。
- 汇总693只完整GET四页200/200/200/93。汇总20/277/395/0/1为入选/观察/待评估/仅观察/未入选；汇总待评估395与超跌行情缺口30不是同一口径。

[本机正式新结果](http://127.0.0.1:8873/manager-selection/?date=20261013&phase=RETROSPECTIVE&run_id=3756008d713a4505be362d288ab9d504)

## 工程、部署与证据

- 源码根/开发根：/Users/lexi/Desktop/学习/v4_app；/Users/lexi/.codex/worktrees/manager-workbench-rewrite-mac/v4_app。
- 远端基线924e90dcc2110a66a71f829192919c1933a07872，分支codex/manager-workbench-data-closure-20261013。
- 4源+3测试前后SHA见price40-implementation-r1.json。独立Writer/Reviewer为不同identity的gpt-6.1-sol/high。
- Python3.14.6/pytest9.1.1；独立13后端测试、3前端测试与类型检查；覆盖0.6及1.5临界、AND、排除D1、未知版本、缺历史和新旧显示。实际命令/日志/环境见独立收据。
- 实现独立receipt SHA adacd35dcc207e3229e8f9db085e13478624aff6a32ed81602887344e422ff98；两版原始输入records及evidence refs一致，仅价格ratio更改，新662逐行验证，旧快照保持。
- 包装独立receipt SHA a6ea2aaa0907ea0c021e9261e01e86b35f27feaff83d45a0f536cd62d711befe；两包装测试、演练及固定兼容拒绝反例通过。固定plan df76503b951a23f8a4040d9365b4c1b859a69f1c9da0bce723f889cb22a42f51。
- 并行Scheduler已发布a-next-pool-20261014-r2。以实际当前文件为基线，保留840项非delta，只换本次3后端源。原manifest有3目录被声明symlink，包装采用固定root/plist/manifest及130条实际SHA/mode/size指纹兼容；其他字节严格匹配，不改现役旧manifest或通用校验。API6delta，1176项非delta保留。配置仅改新规则版本。
- 正式API40755/scheduler40759，7afterSHA及资源闭包匹配；新保存结果全部股票/策略行逐字匹配已审候选。正式独立receipt SHA b7cec9147073e61aa4048d8ae42dd923000035f9384a09c53467c420c1357d0f。
- 真实浏览器打开新run、严格筛选20条全页、名称与60%门槛直接可见，控制台错误0。UI receipt SHA b646afbc0a9822bd5bbf3e83da15a59a373cd08c47fc4204567917220c8889c8。
- IMPLEMENTED/TESTED/REVIEWED/INTEGRATED/DEPLOYED/API_VERIFIED/UI_VERIFIED/BEHAVIOR_VERIFIED；NATURAL_SLOT_UNVERIFIED。

## 保留边界

原20%版本和更早历史字节不变。未新增采集、模型调用或额度使用；不改美股、公告暂停、交易门禁及Vibe8910。首次离线保存后的OwnedIO大文件读回失败留存，只作确切产物readback修正，未放宽业务IO限制或重复提交；并行发布导致的第一次包装失败留存并精确重建。原始行情、完整计划/输入/响应、凭证和dist不上传；Mac证据依赖测试不声称远端CI可独立运行。工程通过不代表反弹或研究收益已经验证。
