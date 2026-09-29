---
name: baimao-method
description: Apply a Baimao/Serenity-inspired first-principles supply-chain chokepoint method to an article, theme, layer, or company using normalized source evidence or a user-returned Chat package. The default WeChat route consumes the local package and Chat return after a Drive-first handoff and Codex cloud mirror; direct-file handoff is only a bounded fallback. Explicit LEGACY_FULL_RESEARCH is required for local V3 coverage/publication. Do not fetch routine latest posts or issue trading instructions.
---

# Baimao Method

## Contract

- Work from supplied evidence or a `baimao-feed` handoff.
- In the default Drive/Chat route, the package is the frozen source and the returned Chat report is
  a research input with `CHAT_READ_UNVERIFIED` or light-check status until local checks prove more.
  Do not require a local research coverage ledger before package handoff, and do not turn a Chat
  claim into `RESEARCH_VERIFIED` without evidence. After local and Drive archive receipts pass, an
  explicitly authorized V4 Stage A archive-display registration and exact article-date API/UI check
  may follow; it remains a read-only reference and does not enable legacy, candidates, scores, pools,
  or BUY gates.
- Map the system and scarce layer before selecting companies.
- Separate `VERIFIED`, `INFERRED`, and `HYPOTHESIS` claims.
- Default to `RESEARCH_MAP`; do not force a buy/sell answer or a fixed number of stocks.
- Treat narrative heat, broker coverage, market cap, and recent price action as context, not proof of quality.
- For a full WeChat article, retain the complete report contract: every coverage `EVENT` `source_index` receives exactly one of `PROMOTE`, `HOLD`, `REJECT`, or `CANNOT_CONFIRM` in summary `event_dispositions`; every `NO_EVENT` remains `NO_EVENT`; every unreadable source remains `UNREADABLE` with its exact ID/range. The trusted frozen package's `review_contract_version` controls whether this check applies. Time, token, context, or scheduler pressure never authorizes shrinking the report. If a required analysis is unfinished, label it `INCOMPLETE`/`CANNOT_CONFIRM` rather than inventing a conclusion. Structural mapping validity does not prove correct event classification or research semantics.
- New frozen packages declare `review_contract_version=wechat-event-dispositions-v1`; an older v2 package without that field remains under its original return contract and must show the event check as `NOT_RUN_LEGACY_PACKAGE`.
- Keep A/BJ observations and Hong Kong observations (Connect eligibility separately evidenced) in separate tables, and keep the all-mentions pool, Baimao research pool, and any formal pool semantically separate.

## Workflow

1. Read the full ordered source before ranking anything when the source is accessible. For image-heavy sources, reconcile the returned coverage against every image and record `NO_EVENT` for irrelevant images or `UNREADABLE` for inaccessible ones. OCR is an index; inspect the original image when text, units, boundaries, abbreviations, or attribution are ambiguous. If access or Chat return is incomplete, preserve `CANNOT_CONFIRM` instead of claiming full reading.
2. Build event cards before stock cards. Each event card must retain source index, exact claim, product/layer, quantities and units, date, named and unnamed entities, source grade, adjacent context, and contradiction links.
   For conflicting figures, retain each original value, unit, period, and subject, show the arithmetic result, and label an unreconciled difference `CANNOT_CONFIRM`; never guess a correction to force totals to match.
3. Merge only events that share explicit subject continuity. Preserve a short event_chain_id/source-index index in the report; the summary mapping still lists every underlying EVENT source. Never infer that adjacent images refer to the same company. Search later images for corrections or falsifiers before accepting an earlier claim.
4. State the source's actual claim without strengthening it. A product event without a security name remains eligible for research.
5. Translate the market story into a physical, technical, regulatory, or operational system change.
6. Map the value chain and rank layers by scarcity before mapping listed companies.
7. Trigger focused external research when an event combines at least two strong operating signals such as price acceleration, customer queues, allocation, lead-time extension, outage, low yield, qualification scarcity, near-term effective capacity, or stated quarterly earnings impact. Do not stop because the source omitted the company name.
8. Test the proposed bottleneck:
   - downstream customers must have the capability;
   - supply cannot expand or substitute quickly;
   - the company is designed-in, qualified, or otherwise captures the layer;
   - the opportunity is not already fully reflected in expectations and valuation.
9. Disambiguate abbreviations with product vocabulary, price units, physical units, capacity scale, neighboring topics, and primary sources. Preserve `CANNOT_CONFIRM` when these disagree.
10. Map companies only after the layer is understood. Separate source-named companies from `RESEARCHER_DERIVED` mappings and require effective capacity, not planned/nameplate capacity. Company-priority tables list existing company-level evidence separately from evidence still to verify; `PROMOTE` means research priority only.
11. Name the strongest link and weakest link in the thesis.
12. Search for customer-side traces, filings, tenders, certification, capacity/yield, shipments, pricing, financials, and counter-evidence as appropriate.
13. Run an omission audit before ranking: review all event cards marked scarcity, price, capacity, qualification, outage, policy, or falsifier; explain why each was promoted, held, or rejected.
14. Apply the high-value gate in `references/high-value-extraction.md`. Do not rank a
    company from mention frequency, broker recommendation, target market cap, theme heat,
    or price action. Require an issuer-specific capture mechanism and a plausible path into
    volume, price, margin, working capital, or capital intensity.
15. Give a concrete falsifier and the next highest-value research step.

For full WeChat delivery, add a report-level ledger check after the omission audit. In the default
Chat-owned research route, the return should cover each accessible `EVENT` once, list every
`NO_EVENT`, and retain every `UNREADABLE` source with its reason. A missing/invalid return file or
unreadable source lowers the state to `CHAT_READ_UNVERIFIED`/`CANNOT_CONFIRM`; it does not block the
local package stage and it does not justify a fabricated row. In explicit
`LEGACY_FULL_RESEARCH`, the local `N` EVENT rows must be covered once with no missing or duplicate
source reference before V3/API/UI claims. The separately authorized V4 Stage A archive-display API/UI
check is not a V3 claim and follows the frozen archive/receipt boundary. A short question may use
proportionate artifacts, but it cannot override these full-article chapters or their evidence boundary.

Missing one condition does not mechanically erase the company. Downgrade the relevant claim to `UNVERIFIED` or keep it in a `RESEARCH_MAP` with the missing evidence stated.

Broker or social attention raises `crowding_risk`; when the entire thesis is merely a repeated consensus pitch and no narrower independently evidenced layer exists, record `NO_DIFFERENTIATED_EDGE` and keep it out of priority research. This is an edge assessment, not proof that the company or bottleneck is false.

If external research discovers a thesis not present in the intake source, mark it `RESEARCHER_DERIVED`. This is valid discovery, not source attribution.

Read `references/framework.md` for the scorecard and output form.
For WeChat or other image-heavy public-account reports, also read
`references/wechat-report-chain.md` and satisfy its completion gates.
When the user asks for investment value, hidden opportunities, or the best information in
a report, also read `references/high-value-extraction.md`.

## Output

For a small method question, the following five core analytical blocks remain sufficient:

1. `核心论点`: source claim and system change.
2. `小白解释`: what the bottleneck does and why downstream cares.
3. `第一性原理`: layer map, bottleneck test, strongest/weakest links.
4. `公司映射`: capture mechanism, evidence grade, crowding, counter-evidence.
5. `当前结论`: `UNVERIFIED`, `RESEARCH_MAP`, or `INVESTABLE_CONCLUSION`, plus falsifier and next step.

For a complete WeChat report (`微信完整报告强制章节`), those core blocks are embedded in these mandatory chapters:

1. 结论先行：短摘要、研究状态、文章日期与资料边界。
2. 事件地图：按事件链合并同源截图，保留简短event_chain_id与全部来源编号；逐来源EVENT/NO_EVENT/UNREADABLE在coverage.csv，并为每个EVENT来源写唯一summary处置，不重复抄入正文。
3. 高价值事件卡：逐卡写变化、因果、稀缺/替代、公司捕获、财务桥、原文证据、反证、最强链/最弱链和下一验证。
4. 公司捕获与财务桥比较：区分 `SOURCE_NAMED` 与 `RESEARCHER_DERIVED`，并保留订单/交付/验收/收入口径差异。
5. A/BJ 优先级：单独列观察、已有公司级证据、待核公司级证据、升级和失效条件；PROMOTE仅是研究优先级。
6. HK 优先级：单独列观察和公司级证据；资格缺证据则 `CANNOT_CONFIRM`。
7. 反证、降级与遗漏：保留 `REJECT`、匿名主体、未映射名称、同源传闻和矛盾。
8. 下一步验证：按信息价值列一手来源、字段、日期边界和失败条件。
9. 来源覆盖边界：短覆盖摘要和附件索引、原图阅读范围、研究者派生与时点；保持 `RESEARCH_ONLY / WATCH_ONLY / NO_BUY_GATE`。

Never use “只有少数 PROMOTE” as a reason to omit the remaining events or chapters. No
security is required to enter `PROMOTE`; incomplete evidence stays `INCOMPLETE` or
`CANNOT_CONFIRM` and the report remains research-only.

`INVESTABLE_CONCLUSION` requires independently supported moat, financials, valuation, and margin of safety. It remains `RESEARCH_ONLY / NO_BUY_GATE` here.

## v2 return reuse
Default archive does not rerun method. Rewriting a report reuses the exact same-input CSV bytes and updates only report/summary binding. Full field and reading-mode contract: references/wechat-report-chain.md.
