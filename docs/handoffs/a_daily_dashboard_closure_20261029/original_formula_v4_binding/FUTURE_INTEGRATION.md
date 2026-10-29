# 既有 V4 服务将来集成/恢复清单（尚未安装）

本轮已独审 PASS 的上限是 `BEHAVIOR_VERIFIED_ISOLATED_ONLY`。现役服务、pins、CURRENT、15:40 runtime 均未修改；本清单不表示已部署。

**唯一现有入口。** `apps/api/v4_api/app.py:6225` 的既有 `create_research_router(...)` 调用目前没有传 `original_chart_binding`，默认返回 typed CANNOT_CONFIRM。将来由同一 V4 服务的授权集成批次传该参数；无需新端口、第二 demo 或 producer。`shared_data_root` 必须同时指向当前产品根 `.../dashboard_completion_r1/today_full_r1`（现调用来自 `V4_A_SHARE_HISTORY_DATA_ROOT`），其中 index/product/manifest/row-ref/config 必须继续保持原 SHA 绑定。现有 `research_read_root` 等参数保留原 owner 配置。

**本批固定绑定参数。** 仅服务启动配置传入；API 不接受文件路径查询。artifact_root 必须是共同父目录，因旧三例在 sibling `original_formula_chart_0415`，新244在 `original_formula_charts_247`。

```json
{
  "artifact_root": "/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030",
  "manifest": {
    "path": "/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030/original_formula_charts_247/MANIFEST.json",
    "sha256": "b5744e1f29512235d30261d901d7dcb891552637a32eeb5dfbf147c951565ee9"
  },
  "receipt": {
    "path": "/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030/original_formula_charts_247/COMPLETION_RECEIPT_247.json",
    "sha256": "c413357bed81e2d14050d81d8ac642f2c028956231bea444da935a9d7211cd21"
  }
}
```

**必需字节。** 三个已审源码：`infrastructure/research_lane_source.py`、`apps/api/v4_api/research_router.py`、`research-panel/numeric283-panel.js`。沿用原 V4 router/store/SafeRoot 和既有 daily.html、numeric283-chart.js 等静态资源；不重建 daily.html。同根必须保留上述 MANIFEST、COMPLETION_RECEIPT_247 及其 records 指向的全部247 HTML/PNG/projection（旧3 JSON、新244 gzip），以及已绑定的产品 index/product/manifest/row checkpoints/SOURCE_CONFIG。formula/engine 的配置 SHA 必须仍是 d35c9a30…05ac / ae4243ec…f0d1c；GET 不运行 engine、不读价格做计算。清单外原始行情/引擎不因读取接线而复制为第二源。

**隔离复现与恢复。** 真实已有 helper `docs/handoffs/a_daily_dashboard_closure_20261029/serve_daily_dashboard_demo.py` 仅测试时加 `--daily-product-root <产品根> --panel-root <已有完整静态根> --original-chart-manifest <上述MANIFEST>`；可选 `--report-data-root <已有研报数据根>`。默认报告根为空临时根；此参数不建索引。helper/check.cjs/run_isolated.py 与两测试用于复现，不需要加入正式服务入口。生产集成需单独冻结并验 API/UI；若绑定缺失/漂移即 CANNOT_CONFIRM、旧图清空，不能回落显示别日图。恢复先保留此前服务配置/源码版本和绑定 SHA；在单独授权窗口撤回本批精确 PATCH 或移除本配置后重启原同服务，禁止覆盖其他 dirty；本轮没有执行恢复或服务动作。

**尚未完成。** 原自然日更 owner 保留自己已经算出的51/22、按新 generation 增量写 artifact/manifest/completion 并接现有事件，以及15:40 runtime 的实际参数/发布/自然完成回执均未做。不得为此在 GET 重算、每股重复原式计算、建第二 producer 或每日重建主 HTML。自然日更仍 CANNOT_CONFIRM。研究四旗保持 true/false/false/false。
