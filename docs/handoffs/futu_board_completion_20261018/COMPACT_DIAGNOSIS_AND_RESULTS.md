# Futu US board gap: compact diagnosis and result

As observed on 2026-10-18, the `20261017/external_finance.json` artifact (source session `20261016`) has 24 official Futu board rows, 12 `READY` and 12 `CANNOT_CONFIRM`. The 12 unresolved rows are deliberate null entries in the source board map, not missing quote prices. The mapped 12 remain intact: 10 have membership `READY`, two have membership `CANNOT_CONFIRM`. Tencent proxy quotes are a separate lane; its 48/48 coverage is not Futu board coverage.

The local Futu catalog query at `2026-10-18T01:48:36Z` returned 145 industries and 117 concepts. Related names below were not treated as equivalent where they are narrower, split, or thematic proxies. The military board is the only exact, defensible match established in this batch.

| Unresolved label | Catalog evidence / candidate | Result |
|---|---|---|
| AI算力 | `人工智能` US.LIST2136; `AI芯片` US.LIST2548 | No broad exact category; remain `CANNOT_CONFIRM`. |
| CPO | `光通信` US.LIST23979 | Related but broader/different category; remain `CANNOT_CONFIRM`. |
| 商业航天 | `太空概念` US.LIST2556; `SpaceX概念` US.LIST24213 | Thematic/narrower categories; remain `CANNOT_CONFIRM`. |
| 卫星 | `太空概念` US.LIST2556; `SpaceX概念` US.LIST24213 | No exact satellite category established; remain `CANNOT_CONFIRM`. |
| 电网 | `受监管电力` US.LIST2472 | Narrower utility category; remain `CANNOT_CONFIRM`. |
| 军工 | Exact unique `INDUSTRY / 航空航天与国防`, US.LIST2089 | Candidate maps this one label; the other 11 map entries are unchanged. |
| 新能源 | `可再生能源` US.LIST2572 plus hydrogen, EV, and storage categories | No broad exact category; remain `CANNOT_CONFIRM`. |
| 石油 | Catalog divides this across oil/gas subindustries | No single exact broad category; remain `CANNOT_CONFIRM`. |
| 铜/有色 | `铜` US.LIST2510; `其他工业金属与采矿` US.LIST2501 | Copper alone is too narrow and the broader class is not exact; remain `CANNOT_CONFIRM`. |
| 银行金融 | `地区银行` US.LIST2456; `多元化银行` US.LIST2481 | Split banking categories; remain `CANNOT_CONFIRM`. |
| 生物医药 | `生物技术` US.LIST2069; `一般药品制造商` US.LIST2428; `专业与通用药品制造商` US.LIST2513 | Split classifications; remain `CANNOT_CONFIRM`. |
| 消费 | Many separate consumer industries | No single exact broad category; remain `CANNOT_CONFIRM`. |

The saved quote canary for US.LIST2089 returned the exact provider name and `update_time=2026-10-16 16:00:00`; that is catalog/quote evidence only, not historical PIT or membership confirmation. The candidate collector adds a 10 `get_plate_stock` calls per 30-second sliding-window limit; a mocked 13-call run waits 30 seconds once.

Candidate package result: US and API releases are inactive, and the API candidate's sole delta is `ops/_us_market_digest_parts/futu_boards.py`. Source tests pass 9/9; candidate-US mapping/legacy tests pass 7/7. The two API projection assertions fail on the unchanged US release baseline. The same two tests against the active API r3 and API candidate fail before their assertions on the same existing `fetch_futu_boards` unexpected-keyword error; router, store, and producer files are byte-identical across that base and candidate. Active and candidate API `read_exact` return the same current artifact (24 Futu rows, 12 `READY`). Detailed evidence is in `CANDIDATE_VALIDATION_RECEIPT.json` (SHA-256 `495457610384a2fa19682c6c69ad10b442529acd2a408cedd612e5d7b17ddf50`).

**State:** candidate implementation is ready for independent review; no activation, live capture, API/UI verification, or natural-session verification has occurred. The existing artifact remains 12/24 Futu `READY`; the candidate does not retroactively rewrite it. Research-only flags remain `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`.
