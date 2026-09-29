# 研究复盘持续生成 owner（2026-09-12）

本批在 `v4_app` 增加唯一的 V4 生成入口：

```bash
V4_DAILY_REVIEW_ROOT="/absolute/path/to/reviews" \
V4_RESEARCH_REVIEW_SOURCE_ROOT="/absolute/path/to/vibe-astock" \
/Users/lexi/Desktop/学习/runtime/venvs/v3.5-mac/bin/python \
  /Users/lexi/Desktop/学习/v4_app/ops/run_research_review_generation.py \
  --date 2026-09-11
```

日期参数是必填的，支持 `YYYYMMDD` 和 `YYYY-MM-DD`。输出只写
`<V4_DAILY_REVIEW_ROOT>/<YYYY-MM-DD>.json`，使用临时文件加原子替换，默认拒绝覆盖已有同日文件，
也不写 `latest.json`。产物包含已有 `daily_review` envelope、八个 M3 需要的结构化事实块和
`v4_generation` 来源记录；`research_only=true`、`production_allowed=false`、
`buy_gate_updated=false`、`orders_sent=false` 固定保留。

现有调用链已只读核对为：

```text
main.initial_state(date)
  -> reflection.get_past_context(as_of=date)       # 只读历史回看
preflight.check(date)
  -> duanxian.data.{sentiment,emotion,leader,capital,macro,dragon,theme}
review_graph.build_review_graph()
  -> duanxian.config.make_llm(quick/deep)
  -> ROLES 的五个 analyst 节点
  -> synthesizer.create_review_judge
review_store.serialize(final, date, warnings)
  -> V4 exact-date writer
```

生成 owner 通过 `V4_RESEARCH_REVIEW_SOURCE_ROOT` 加载现有 `main.py`、
`duanxian.review_graph`、`duanxian.review_store` 及其纯 Python 依赖。加载边界会阻断
`server`、应用入口、账户/持仓模块和生命周期导入；允许的 `iwencai_client` 只作为现有题材
HTTP provider。不会启动 8910 服务，也不会调用 `server.py` 或账户应用。

provider 与缓存的当前事实如下：

| 层 | 现有来源 | 已有缓存/副作用 | 本批口径 |
| --- | --- | --- | --- |
| 涨停池、涨跌停、龙虎榜 | `akshare` | `duanxian` 事实与指标缓存，部分接口收盘后落盘 | 复用现有函数 |
| 宽度、资金、行情 | Eastmoney/Tencent HTTP 适配 | `breadth`、`market_facts`、`zt_summary` 等按日缓存 | 复用现有函数 |
| 题材串 | Fuyao 或现有 Iwencai HTTP client | `zt_reasons` 按日缓存 | 复用现有函数 |
| 题材外部线索 | Agent-Reach `mcporter` | 无权威日报缓存 | 仍是现有 analyst 的可选输入 |
| 文字收敛 | 现有 `duanxian.config` selector、CLI 或 MiMo | 凭据只读解析，receipt 不写值 | 不新增 provider |
| 历史回看 | `reflection.get_past_context` | 读取已有 `reviews/reflections` | 生成入口不运行回评写入 |

一次入口运行会先将八个高层 `duanxian.data` 函数各调用一次，再让 preflight 和图节点复用
同一日期快照，避免入口体检与图重复调用这些函数。高层函数内部仍各自连接既有行情 provider；
M4 的共享 provider/一次抓取地图尚未接入，本 receipt 以
`CANNOT_CONFIRM_M4_SHARED_PROVIDER_BINDING` 保留该缺口，不能据此声称全市场底层请求已去重。

`reflection.auto_evaluate_prior` 和旧 `review_store.save` 没有在 owner 入口中调用：前者可能读取
次日行情并写 reflection，后者会额外写 `latest.json`。它们属于历史辅助写入，不是当前 M3 日报
所需的最小产物；保留现有历史文件，待全功能地图与状态根迁移方案审查后另行接入。

离线测试使用注入的 mock backend 生成小样本，只证明日期、结构、写入边界和 M3 reader 可消费；
不代表自然行情、LLM、API、UI 或调度已验证。真实生成还需独立 Reviewer 复跑，并在 M4 完成
共享行情 provider 绑定后才可评估持续 owner 是否达到 `INTEGRATED`。

当前状态：生成入口 `IMPLEMENTED`；mock 产物 `TESTED`；真实 LLM/行情生成、M3 的生成 owner
显示、API/UI/natural 层均 `CANNOT_CONFIRM`；本批未启停服务、未改 scheduler/plist/release、
未复制业务数据，也未修改旧 v3.5 源码。
