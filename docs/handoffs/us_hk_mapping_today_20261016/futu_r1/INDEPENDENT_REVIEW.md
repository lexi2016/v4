# Futu R1 独立验收

**Verdict:** `TESTED=PASS`、`REVIEWED=PASS_WITH_NONBLOCKING_P2`、`BEHAVIOR_VERIFIED=PASS`。没有 P0/P1。R1 的当前离线产物满足冻结 PASS；报告仍是描述性关联观察，不构成 PIT、预测、因果或 BUY 结论。

本 reviewer 与 Writer 身份不同，仅审查 `futu_r1` 冻结范围。按授权没有调用 Futu/OpenD，也没有调用本地 V4 API；API 来源的新鲜度以 Writer 保存的 raw 响应和 receipt 为证，独立实时重查状态为 `CANNOT_CONFIRM`。Reviewer 的重建副本、基线副本和输出均位于 `reviewer_replay/`。

## P2（非阻断）

**Canary replay 在缺少可信缓存时会回退到 live historical-K 请求。** [capture_futu_daily.py:335-341](capture_futu_daily.py) 只在现有 `canary.json` 的 `schema_version` 等于 `futu-r1-canary-v1` 时直接返回；否则继续到 `fetch_catalog_pages`，再在 [capture_futu_daily.py:353-360](capture_futu_daily.py) 创建 `OpenQuoteContext` 并对三只标的调用 `request_history_kline`。同时，schema 匹配时不验证目标日期、三只代码、返回行或 checks；[capture_futu_daily.py:406-426](capture_futu_daily.py) 会按缓存中的 `status` 决定退出码。`SCOPE_R1.md:16` 明确本批不得再请求 daily-K。当前缓存有效，文件 SHA 与 Writer receipt 一致，离线 `--canary` 重放返回 `replayed_saved_canary=true`，所以此问题不影响本次已保存结果。若缓存丢失/换 schema 后仍运行同一命令，它会再次查询三只历史 K 线；若存在 schema 匹配但内容不一致的缓存，命令可能直接报 `TESTED`。本 reviewer 未触发该 live 分支。建议缺少缓存时 fail closed，并在缓存重放时验证确切代码、日期、请求合同和结果状态。

## PASS 证据

- Writer receipt 中 15 项 artifact SHA 全部与磁盘一致；顶层 report SHA 也匹配。核心绑定为冻结 mapping snapshot SHA `3228f28fdc34cfe36202fa7e5bce1720fe34115a334b77bc6a4468a6013eb1cc`、其文件 SHA `f819ca2f036953d0989a2a28127072d41ac7e051f209087a38953299251a0df3`、catalog projection integrity SHA `fd362d817032f4f0a8f6f033c44df64435232382ea514dc31beee7b285deb0c5`、snapshot raw SHA `873e136a1b68ea85d2e3d5ab3f3d1bbb17e85cd091551e7807ee39aa8636674a`、canary SHA `6e9c5f4871493c19a732a8420eaaaf1a782ba97bcc86ab9d33e57d5d8a749d38`，以及初次 OTC 混合批次 SHA `a4e720a44694f5bef6c1b59d216bc67daeef609d3d85995241b16efd10b00161`。
- 原目录 `capture_futu_snapshot.py --verify` 返回 `PASS`。独立 `reviewer_replay/` 副本从已保存的 catalog projection、canary 和 snapshot raw 执行 `--rebuild`，返回 `BUILT`；随后 `--verify` 返回 `PASS`。重建后的六份 CSV 和 `REPORT.md` 与 Writer 输出逐字节相同；`results.json` 除重建时间 `created_at_utc` 外相同。副本只将 frozen baseline 路径改为 `reviewer_replay/mapping_input_snapshot.json`，业务逻辑和原始输入未改。
- 原目录及隔离副本的 `capture_futu_daily.py --canary` 均从已保存 canary 重放并返回 `TESTED`；`replayed_saved_canary=true`。canary 保存的请求严格为 `US.DASH`、`US.NTES`、`US.UBER`，三者均 `ret=0`，各有唯一 `2026-10-15` K_DAY 行，close 为正且历史额度记录为 96/4 至 99/1。Reviewer 没有重复请求这些历史 K。
- Catalog projection 记录 667 股票、1,003 个唯一关系、518 个唯一美股/相关符号；与冻结关系输入逐关系比较，21 个源字段（包括 relation ID、关系类型、范围、研究状态、证据、缺口和来源行）均零差异。关系覆盖表同样保留全部 21 个字段，无缺列、无值差异。
- Snapshot raw 请求 448 个非 OTC 代码，返回 448 个唯一匹配代码；两批请求大小为 400 和 48。逐 attempt 检查未发现响应 code 超出该次 request、重复 response code 或 raw-key/code 不匹配。初次混合 OTC 失败 artifact 保存了原错误及 128 次有界拆分（两 root 各最多 64 次，最大深度 9）；最终 45 个 OTC-only 代码明确隔离，其他 448 个均返回。446 行通过价格与时间字段检查，EEX、MIMI 两行因 update_time 缺失而进入 missing，不参与正负分类。
- 离线复算得到关系桶 `positive=515`、`flat-negative=185`、`missing=57`、`open=221`、`excluded=25`，合计 1,003；候选按港股代码去重为 427 只。正涨关系只进入 `CLOSED_RESEARCH_SCOPE`，OPEN/排除优先级正确；公式只用 `(last_price / prev_close_price - 1) * 100`，`pre_price` 保持独立字段。Exact daily-K 三行没有混入 snapshot 排序。
- Top-15 展示含 10 个不同美股代码；raw snapshot 对这 10 个代码均记录 `suspension=false`、`sec_status=NORMAL` 且成交量为正，未见停牌或状态异常导致的顶榜证据。Futu 文档说明美股 `update_time` 使用美东时间，并有 20:00–04:00 ET 的 overnight 时段；VYX 的 `2026-10-15 23:52` 更新时间和 `overnight_price=last_price=7.56` 与 overnight 观察相符（这是基于 raw 和文档的解释，不是独立上市状态核验）。[Futu 快照文档](https://openapi.futunn.com/futu-api-doc/quote/get-market-snapshot.html)、[Futu 美股时段说明](https://openapi.futunn.com/futu-api-doc/en/qa/quote.html)
- `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false` 与冻结 scope 一致。报告明示当前快照不是精确的 2026-10-15 session return，也不证明在 2026-10-16 港股开盘前可得；没有把当前涨幅说成预测、因果或 BUY。

## CANNOT_CONFIRM

- 本 reviewer 未重新读取 V4 live catalog 或 Futu/OpenD；live endpoint 当时是否仍与保存的 catalog projection 一致不能由本次独立实时查询确认。保存的 projection、raw 响应和 Writer receipt 的来源 SHA/关系绑定均通过离线检查。
- 当前映射关系的经济真实性、因果传导、预测能力、历史 PIT 与 2026-10-16 港股开盘前可得性均未验证；R1 产物未声称这些结论。
- Futu snapshot 的状态字段显示上述 Top-15 代码正常且未停牌，但未做独立交易所挂牌/退市数据核验；若将 R1 用于更严格的交易可用性判断，仍需另行授权且超出本批范围。
- 未运行现存的 `--capture` live 路径，也未对缺失/损坏 canary 人为触发 fallback，因为这会打开不被授权的 API 路径。仓库没有发现 futu_r1 专属单元测试；本次行为验证由 receipt 校验、canary 缓存重放及原始输入隔离重建构成。

## Reviewer 命令

```sh
python3 docs/handoffs/us_hk_mapping_today_20261016/futu_r1/capture_futu_snapshot.py --verify
python3 docs/handoffs/us_hk_mapping_today_20261016/futu_r1/capture_futu_daily.py --canary
python3 docs/handoffs/us_hk_mapping_today_20261016/futu_r1/reviewer_replay/capture_futu_snapshot.py --rebuild
python3 docs/handoffs/us_hk_mapping_today_20261016/futu_r1/reviewer_replay/capture_futu_snapshot.py --verify
python3 docs/handoffs/us_hk_mapping_today_20261016/futu_r1/reviewer_replay/capture_futu_daily.py --canary
```

没有运行 `--capture`，没有调用任何 Futu/OpenD 或本地 V4 API；也没有请求全量 daily-K、修改业务代码/服务或触碰 R0 产物。
