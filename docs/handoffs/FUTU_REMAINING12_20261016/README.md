# Futu US remaining 12 board matches

## Disposition

**Final disposition: ADD_ZERO.** The independent reviewer returned `REVIEWED_PASS_WITH_NONBLOCKING_P2` for `PASS_ADD_ZERO_RETAIN_ALL_12_UNMATCHED` (P0=0, P1=0). No mapping was added; all 12 remain unmatched. This outcome relies on the independent receipt, not a writer self-review. The review did not modify `FUTU_BOARD_MAP`, tests, runtime services, API, or UI.

The complete live Futu US directory returned 145 `INDUSTRY` boards and 117 `CONCEPT` boards. No exact-name board was present for the 12 topics. The candidate member lists below show why the nearest boards have a broader, narrower, or different membership scope.

| Topic | Nearest official board(s) and observed membership | Recommendation and reason |
|---|---|---|
| AI算力 | `US.LIST2548 AI芯片` (16; includes AMD, NVDA, Amazon, Tesla); `US.LIST2521 IDC概念` (9; includes DLR, EQIX, GDS, AMD, NVDA); `US.LIST2136 人工智能` (50) | **REJECTED.** AI chips and data-center stocks are separate slices; general AI also includes software and industrial names. No single board covers AI computing infrastructure. |
| CPO | `US.LIST23979 光通信` (21; includes AAOI, CIEN, COHR, FN, LITE, POET) | **REJECTED.** Optical communications covers more than co-packaged optics, and no CPO board appears in the directory. |
| 商业航天 | `US.LIST2556 太空概念` (31; includes ASTS, BA, GSAT, LMT, RKLB); `US.LIST2089 航空航天与国防` (98) | **REJECTED.** The space board mixes satellite, launch, defense, and other space companies; aerospace and defense also includes civil aviation and military companies. |
| 卫星 | `US.LIST2556 太空概念` (31; includes ASTS, GSAT, IRDM, VSAT, plus BA and LMT); `US.LIST24213 SpaceX概念` (13) | **REJECTED.** The space board includes launch and defense companies; the SpaceX board is an association list, not a satellite-industry grouping. |
| 电网 | `US.LIST2472 受监管电力` (45; includes AEP, DUK, NEE); `US.LIST2493 电气设备及零件` (54; includes battery and power-equipment names) | **REJECTED.** One board groups regulated utilities and the other groups electrical equipment. Neither represents the grid as a whole. |
| 军工 | `US.LIST2089 航空航天与国防` (98; includes BA, LMT, RKLB and other civil/space/defense names); `US.LIST2654 美国国防航空` (9) | **REJECTED.** The first board is broader than military/defense; the second is a narrow defense-aerospace subset. |
| 新能源 | `US.LIST2572 可再生能源` (6); `US.LIST2461 可再生能源公用事业` (23); `US.LIST2047 太阳能` (22); `US.LIST23939 储能概念股` (8); `US.LIST2552 锂电池` (12); `US.LIST2568 新能源汽车` (12) | **REJECTED.** Futu splits utilities, solar, storage, batteries, and electric vehicles into separate boards; no one board has the umbrella scope. |
| 石油 | `US.LIST2058 油气勘探与开发` (80); `US.LIST2060 油气炼制与销售` (19); `US.LIST2224 综合油气` (20); `US.LIST2585 页岩油` (13) | **REJECTED.** Candidates combine oil with gas, cover only a supply-chain segment, or are limited to shale oil. |
| 铜/有色 | `US.LIST2510 铜` (8; includes ERO, FCX, SCCO); `US.LIST22865 铜概念` (10; includes BHP and RIO); `US.LIST2501 其他工业金属与采矿` (61); `US.LIST2211 铝` (4) | **REJECTED.** Copper-specific boards do not cover non-ferrous metals generally; other metals and aluminum are separate boards. |
| 银行金融 | `US.LIST2481 多元化银行` (20; includes BAC, C, JPM); `US.LIST2495 金融集团` (8); `US.LIST2260 资本市场` (99) | **REJECTED.** Banks, financial groups, and capital markets have separate membership; no single board covers banking and finance. |
| 生物医药 | `US.LIST2069 生物技术` (598); `US.LIST2428 一般药品制造商` (21; includes ABBV, AMGN, LLY); `US.LIST2513 专业与通用药品制造商` (84) | **REJECTED.** Biotechnology and drug manufacturers are separate categories; mapping one category would omit part of the theme. |
| 消费 | `US.LIST2003 家庭和个人用品` (31); `US.LIST2502 专业零售` (47); `US.LIST2157 美国知名零售商` (16; includes AMZN, COST, WMT) | **REJECTED.** These are product, retail, or selected-retailer groups, not a full consumer-sector board. |

Counts are the member rows returned by `get_plate_stock` at capture time. Full directory and member responses are kept outside Git at:

`/Users/lexi/Desktop/学习/agents调试/FUTU_REMAINING12_20261016/`

The raw files and their SHA256 values are recorded in [receipt.json](receipt.json). No raw board or constituent data are included in this handoff directory.

The independent report is [independent_review.json](independent_review.json), SHA256 `3b60128db4087f885cdd186b674b24c6010e6c531bf04e72e87ccd5bce129840`; it is byte-identical to the source receipt at `/Users/lexi/Desktop/学习/agents调试/FUTU_REMAINING12_20261016/reviewer_receipt.json`. The reviewer returned `REVIEWED_PASS_WITH_NONBLOCKING_P2`, decision `PASS_ADD_ZERO_RETAIN_ALL_12_UNMATCHED`, with P0=0, P1=0, and one nonblocking P2. The report reviewed the then-current README and receipt hashes recorded in its `reviewed_files`; this final README/receipt revision records that verdict and narrows the JSON-integrity claim, and those final documentation hashes were not independently re-reviewed.

## Capture and limits

- Directory queried: US `INDUSTRY` and `CONCEPT` via local Futu OpenD, Python SDK `10.06.6608`.
- Full-directory query time: `2026-10-16T09:39:29.308891Z`; 33 nearest-candidate membership queries all returned `ret=0` between `09:40:17Z` and `09:46:26Z`.
- Official API references: [Get Plate List](https://openapi.futunn.com/futu-api-doc/quote/get-plate-list.html) and [Get the List of Stocks in the Plate](https://openapi.futunn.com/futu-api-doc/quote/get-plate-stock.html).
- The API supplies board names and membership; it does not publish formal business definitions for these Chinese topic labels. The recommendations are a semantic comparison of those names and observed constituents, not a Futu-issued taxonomy ruling.
- The independent reviewer found bare `NaN` values in all four raw candidate membership files. Python's default `json.loads` accepts these values, but strict JSON parsers reject them. The prior validation therefore establishes permissive Python parsing plus code/name/count binding; it does not establish strict JSON validity. This P2 does not change the zero-mapping conclusion because these fields were not used to select or match boards.
- No boards were combined to approximate a topic. ETF/reference baskets, new historical bars, market-snapshot refreshes, and A/HK relation expansion were outside this review.
- This evidence-only handoff has no behavior change. Tests were not run. Independent review is `REVIEWED_PASS_WITH_NONBLOCKING_P2`; no runtime or UI behavior was tested or claimed.
