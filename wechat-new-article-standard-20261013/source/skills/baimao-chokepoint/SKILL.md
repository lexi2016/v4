---
name: baimao-chokepoint
description: Route research requests that explicitly mention Baimao/白毛/白猫/Serenity/@aleabitoreddit across public-signal capture, chokepoint analysis, attention radar, and an explicitly requested ChatGPT/Gemini webpage audit. For a raw WeChat link, the default is local package → Drive-first grounded article handoff → user return → Codex local archive and Drive mirror; direct files are only a bounded fallback. Explicit LEGACY_FULL_RESEARCH is required for V3 or legacy API/UI delivery; V4 Stage A archive display is a separate authorized read-only route. Do not trigger cross-model audit for an ordinary WeChat link, imitate a person's voice, or create trading instructions. Do not trigger for generic supply-chain research without Baimao context.
---

# Baimao Chokepoint

## Contract

- Answer the user in Chinese.
- Stay `RESEARCH_ONLY / WATCH_ONLY / NO_BUY_GATE`.
- Separate source capture, research method, and radar. Do not load all three by default.
- Treat cross-model webpage review as an optional challenger route only when the user explicitly asks for ChatGPT, Gemini, or a cross-model audit/comparison. It never replaces the local feed/method chain or writes canonical state.
- The cross-model skill's implicit discovery is not external activation: without current explicit audit/comparison intent it returns `ROUTE_NOT_APPLICABLE` and does not inspect tabs, request confirmation, or send.
- For a raw WeChat link in the default route, finish the `baimao-feed` package gate; use the grounded Drive article folder and `START_HERE` handoff first. Direct files are only a bounded fallback. Never use the Baimao shortlist as the public-account all-mentions pool.
- A raw WeChat URL plus an analysis request follows `feed package → Drive-first article handoff → user Chat research → Codex local return/archive and Drive mirror → authorized V4 Stage A exact-date API/UI display`; Chat owns research coverage and unreadable sources remain explicit. If Chat has no Drive write tool, it returns exact files to Codex and must not claim Drive write. V3.5/page delivery is a separate date-matched handoff available only under explicit `LEGACY_FULL_RESEARCH`.
- For future new articles, follow the single command and receipt authority in
  `WORKFLOW_公众号链接固定执行方案.md` and `templates/chat_research_prompt.md`. The feed importer
  preserves the trusted frozen ZIP members with the return; the V4 strict registration validates its
  explicit receipt references. A `PARTIAL` report can be archived without semantic promotion.
- Treat verified facts, evidence-based inferences, and unverified hypotheses as different states.
- Prefer a useful `RESEARCH_MAP` over a forced stock list or a forced `ZERO_PASS`.
- Never claim a formal pool, BUY gate, or trading state was updated unless a separate authorized workflow performed and verified it.

## Route The Request

Use the smallest matching workflow:

| Request | Route |
|---|---|
| Open a WeChat/X link, fetch latest posts, finish OCR/timeouts, normalize entities | Read `../baimao-feed/SKILL.md` |
| Analyze an article, sector, layer, or company with the Baimao method | Read `../baimao-method/SKILL.md` |
| Find rising attention, new entrants, theme rotation, or earlier/smaller candidates | Read `../baimao-radar/SKILL.md`; it requires an archive from the feed |
| Raw WeChat URL with analysis/report | Default: `baimao-feed package → Drive-first article handoff → user Chat → Codex local return/archive + Drive mirror → authorized V4 Stage A exact-date API/UI display`; direct files are only a bounded fallback; do not claim local semantic coverage from Chat self-report |
| Explicit raw WeChat URL with V3/report/page delivery | `baimao-feed → baimao-method → date-matched V3.5` under `LEGACY_FULL_RESEARCH`; do not skip legacy coverage or report chapters |
| Explicit ChatGPT/Gemini/cross-model webpage audit or comparison | Read `../baimao-cross-model-audit/SKILL.md` after local feed/method readiness; this route is optional and does not force external sending |
| Generic "use Baimao to find stocks" | Run method first; use radar only when historical attention data is relevant |
| Explicit research-only dashboard handoff | Finish method state first, then read `references/local-handoff.md` |

For a raw URL plus an analysis request, run package and user handoff first; archive the return, then
complete the separately authorized V4 Stage A archive-display registration and exact article-date
API/UI check. 默认归档后不自动重做研究。Only an explicit request starts bounded review or new analysis with method. A local package may complete without research coverage; a Chat
return with missing/invalid files remains `CHAT_READ_UNVERIFIED`. Run feed through local V3
publication and live verification only after explicit `LEGACY_FULL_RESEARCH` selection AND separate publication authorization. A
latest-five X snapshot is not mandatory unless the user asks for latest posts or the current thesis
depends on current account behavior.

The proportionate-artifact rule for a small question cannot override the complete WeChat
research route. A full URL analysis request still requires source identity, full text/image package
coverage, all-mentions versus research-pool separation, and the complete nine-chapter Chat report;
the local package handoff itself may finish before Chat coverage exists. Date-specific V3.5 delivery
states are required only when `LEGACY_FULL_RESEARCH` is explicit.

## Shared Research Rules

For image-heavy articles, obey the frozen reading mode: FULL_ORIGINAL_REVIEW reads every original; OCR_RISK_REVIEW reads all BODY/OCR and visually checks pivotal, ambiguous, low-text/table sources plus a NO_EVENT sample. Never call OCR-only access visual reading. OCR may index or locate passages, but keyword hits, ticker frequency, and repeated mentions are never selection evidence. Record image coverage and inspect product, customer, qualification, capacity/lead time, substitution difficulty, revenue realization, and counter-evidence in the original image context.

Do not accept `OCR_OK`, an all-mentioned stock pool, or a candidate list as proof that the
analysis is complete. Before final selection, require a one-to-one source coverage ledger,
event-first review, cross-image contradiction pass, abbreviation/unit disambiguation, and
an omission audit. A strong product-level event without a company name must trigger
company-mapping research or an explicit `CANNOT_CONFIRM_COMPANY_MAPPING`; it must never
disappear from the report.

High-value output is not a longer summary or a larger stock list. Apply
`../baimao-method/references/high-value-extraction.md`: prioritize specific, surprising,
causal, issuer-capturable and falsifiable information; downgrade consensus themes,
broker target prices, repeated recommendation lists and price-only cyclicality.

For page acceptance in the explicit legacy route, `UI_VERIFIED` is valid only when the actual
reloaded target page visibly shows the precise article date, the corresponding original article
context, and the matching full report. HTTP 200, a page shell, a file, a Drive upload, or an API
payload alone is not semantic UI evidence; the natural execution slot is a separate
`NATURAL_VERIFIED` state. The default Drive/Chat route leaves legacy V3/API/UI/natural states
`CANNOT_CONFIRM`; the separately authorized V4 Stage A archive-display route has its own exact-date
API/UI verification states and does not update a pool, score, or BUY gate.

1. Map the system change and value-chain layers before naming companies.
2. Locate the smallest layer whose failure can constrain the downstream system.
3. Verify that the company controls or economically captures that exact layer.
4. Look for designed-in, qualification, yield, effective capacity, shipment, pricing, or customer-side traces.
5. Record what the market may miss and one concrete falsifier.
6. Assign one state:
   - `UNVERIFIED`: pivotal evidence is missing.
   - `RESEARCH_MAP`: the bottleneck/company mapping is plausible and worth continued work.
   - `INVESTABLE_CONCLUSION`: moat, financials, valuation, and margin of safety are independently supported. This is still not a BUY instruction.

Crowding is a field, not an automatic veto. Broker coverage, popularity, and strong price action weaken the "undiscovered" claim, but they do not disprove a narrow bottleneck. Conversely, small market cap or obscurity does not prove a chokepoint.

An intake source may merely provide a theme or company clue. External primary evidence may discover the narrower thesis, but label it `RESEARCHER_DERIVED` instead of pretending the source stated it.

## Output

Lead with the operational conclusion and boundary. For each serious candidate show:

- bottleneck layer and downstream consequence;
- company capture mechanism;
- verified evidence, inference, and missing evidence;
- crowding/recognition level;
- falsifier and next research move;
- state: `UNVERIFIED`, `RESEARCH_MAP`, or `INVESTABLE_CONCLUSION`.

For substantial work, keep only proportionate artifacts: normalized signals, claim ledger, research map, and optional research-only handoff. Do not require a large fixed artifact bundle for a small question.

## Compatibility

The pre-split all-in-one implementation is archived outside the active skill tree. Do not revive its mandatory latest-five intake, named-model routing, or binary `PASS/PROBE/FAIL` rules unless the user explicitly asks for the legacy workflow.
