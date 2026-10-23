# V4 五日历史池与固定 Top100 对照

本目录只做离线描述性对照。读取已有 V4 子池/研报实体名单，并另列正式选股缺口，复用已独立通过的 2026-10-16/19/20/21/22 五日研究池 Top100 和原 V192、主图十路完整候选名单；不抓新行情、不重算公式、不建池或训练。

`compare.py` 以冻结合同和 `POOL_INPUT_MANIFEST.json` 为输入，验证全部绑定 SHA，按完整股票×日期去重，输出逐日 H/N precision、H/100 recall、同日期模型比较、每源和独有源贡献、完整 HIT/MISS 名单及原 387 个共同漏选的覆盖表。未知日期保留 GAP。ROOT明确授权的 `RECOVERABLE_A_SUBPOOL_UNION_RETROSPECTIVE` 只对同runtime已保存且SHA/receipt有效的子池按实际canonical A symbol去重、合并来源，缺失子池不全局阻断；该本地研究投影不冒充历史保存的A-all响应，不写live producer。原榜单只覆盖既有 5533 研究代码，未认证历史全 A 股。

只有完整名单与历史内容绑定、带时区 `available_at <= 当日09:25 Asia/Shanghai` 同时成立才进入 `PIT_CONFIRMED`。其他保存或当前回建名单仅列 retrospective overlap，不能据此称盘前胜率提高。汇总/研报池可能含隔夜信息，与前收盘量价模型的信息集不同。

执行前必须由现有 root 官方 registry 真实登记 `RUN_STARTED`；`registry_bridge.py` 复用官方 adapter 的锁、验证与 append/fsync，只向本批中央摘要 key 写最小引用。输出、原始池、行情和 registry 都保留本地，不在源码同步 allowlist 中。

```sh
python3 -m unittest discover -s research/v4_pool_hit_comparison_20261023 -p 'test_compare.py'
python3 research/v4_pool_hit_comparison_20261023/compare.py /absolute/local/COMPARISON_CONTRACT.json /absolute/local/output
```

完整工件索引及独立验收以本地 `research/v4_pool_hit_comparison_20261023/FINAL_ACCEPTANCE.json` 为准。源码、交接、独立验收、远端同步和运行时发布是分别记录的状态；本任务不发布运行时。

`research_only=true` / `production_allowed=false` / `buy_gate_updated=false` / `orders_sent=false`。

`report.py` 只消费比较输出，生成来源汇总、原387新增覆盖名单、中文报告和精简结果。

R2仅修复成员身份/分母：13个有冻结原名ETF证据的实体×日归类NON_STOCK_ETF，排除股票指标但保留完整raw实体表和逐行排除账本；未绑定的身份隔离CANNOT_CONFIRM。R1旧失败/原输出保留。该代码只给可解析股票代码子集统计，不认证完整历史证券主表。
