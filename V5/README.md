# V5 独立模块迁移

V5 位于私有仓库 `lexi2016/v4` 的 `v5/module-isolation-20261008` 分支，仅修改 V5/，不覆盖 V4。

## 当前可核验状态（2026-10-08）

- 已有版本/输入合同、来源闭包、依赖观测、模块组合、隔离 worker、不可变结果存储、原超跌 reader 适配、命令行和只读本地页面。
- 固定版本 [054782a](https://github.com/lexi2016/v4/commit/054782a08e8eb701b98714eeb0fadbd60153725c) 在 Mac Python 3.14.6 锁定环境完成 10 项审查回归及全套 78 项测试，exit 0；保留 4 条 HTTPError 资源清理警告。
- 后续 [1167ed3](https://github.com/lexi2016/v4/commit/1167ed3ea2aa7e8c8e1b2d79f4e490beec1395fb) 新增 SDK 数据规范化及 11 项测试。该批新增 11/11 与全套 89/89 已在 Mac 持久隔离环境实测通过，exit 0；对应运行证据见验收说明。
- 现有链路证明的是合成数据下的原 reader→独立 worker→提交→读回及重复请求一致性。合成页面结果为严格 1、接近 2、排除 1，没有真实股票推荐含义。
- 浏览器视觉验收、真实 owner 输入准入、真实选股、每日自动运行、独立多模块进程环境及生产切换均未完成。

- 最新已实测候选 [3b32102](https://github.com/lexi2016/v4/commit/3b321022b118e94f828d2f810a622a0a44b23950)：Mac 全套 128/128 PASS，含主表接入 22 项及 SDK 被动记录 17 项；4 条资源警告保留。只证明合成工程路径，不证明实际 SDK 采集。
- A 预选原函数迁移进入候选实现，10 项测试已真实 RED（missing module），候选 GREEN 待 Mac；见 [模块进展](docs/MODULE_PROGRESS.md)。

## 阅读顺序

1. [实际验证与接续](docs/ACCEPTANCE.md)
2. [来源与历史基线](BASELINE.md)
3. [架构与首轮边界](SPEC.md)
4. [首轮实施计划及历史任务说明](PLAN.md)
5. [审查修复说明](docs/REVIEW_FIX_CANDIDATE.md)

用户当前分工：dot 编写代码，原 Mac 测试会话执行独立测试并反馈；不启动新的云端 Codex 编码或测试任务。不因缺真实行情而停止可独立完成的工程实现，也不把合成测试当真实业务验收。

使用 source-only 入口 `python -B run_shadow.py`，具体命令见验收说明。服务未安装；本地页面只能由获准测试显式启动在空闲 loopback 端口，不能接管 V4 的 8873。

不接账户或订单；research_only=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。
