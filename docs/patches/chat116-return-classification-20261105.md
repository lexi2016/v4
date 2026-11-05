# Chat116 received research and main-business classification

Baseline: `ec476a8d4e8c2f0a94c70ef3c705c37136e1f80d`, branch
`codex/chat116-return-classification-20261105`.

The received 364-row D20261105 / O20261106 package uses V2 names and includes
four batch-wide source records. The V1-only importer rejected that contract.
The importer now normalizes the explicit V2 aliases, checks those four source
IDs against the original batch manifest, file SHA and symbol scope, and keeps
company-specific sources bound to their own symbol. V1 follows its existing path.

Each company shard retains the complete received research row, original claims
and source IDs, reuse and research dates, original research tier, and a separately
derived research main-business classification. The classification covers 364
companies in 30 broad categories, based on literal received business or chain
descriptions. Three companies have priority for further evidence and four have
secondary observation priority; these are research-resource priorities. The other
357 retain their original research tier without a new priority assignment.

The existing company-information view displays the received business, chain
position, classification, growth, risk, research date and priority. It says
“公司研究已接收，仍有资料待补” and “行业二筛：今天尚未运行”. It retains original
details under expandable sections. Classification is available in company
materials and the classification CSV; the left catalog filter and authoritative
all-market industry directory are outside this change.

All 364 producer statuses remain `PARTIAL`. D20261105 industry secondary screening
remains `NOT_RUN_FOR_20261105_GENERATION`; no earlier themes or six-stock selection
are carried forward. Unknown five-day volume ratios and future D2/D5 values stay
null. A 60-day volume ratio is not substituted for a five-day ratio. Narrative
financial text stays text; reported numeric financial fields remain empty. Reused
research retains its original timestamp. Neither full financial verification,
small-cap qualification, full price-volume qualification nor historical PIT
certification is claimed. The quote-dash issue is a separate queued task.

## Verification and prepared handoff

Use the configured absolute `PANEL_PYTHON` interpreter. Source tests were run with
the unchanged existing publication adapter explicitly bound:

```sh
V4_EXISTING_PUBLICATION_ADAPTER="/Users/lexi/Desktop/学习/v4_app/.task_worktrees/stock-history-catchup-20261030/ops/sync_stock_history_completion.py" \
  "$PANEL_PYTHON" -m pytest -q tests/test_received_company_materials.py --basetemp="$O/_pytest_sol_source_r1"
```

Result: 14 passed. After adding classification safety validation, only the
affected V2 scope was rerun: 2 passed, 12 deselected. Tests cover V1 compatibility,
V2 aliases, shared-source rejection and scope drift, preserved text/dates/nulls,
and the existing publication adapter's CAS and stable lock behavior.

The Node suite was run against both prepared V2 and prior accepted V1 stages,
using the active panel's existing `company-local.mjs` dependency: 7 passed, no
skips. It covers readable V2 rendering, stale classification rejection,
unrun-secondary semantics, no volume substitution, safe source links, repeated
rendering, and stale asynchronous company responses.

The local output root is
`/Users/lexi/Desktop/学习/agents调试/v4_chat116_classification_20261105`.
`STAGED_EXISTING_READER_HOST_CHECK.json` records all 364 staged shards passing the
installed API `ResearchLaneSource`, plus the fixed `300856.SZ`, `603007.SH` and
`920007.BJ` samples passing the installed workbench company projection. Only
reference resolution was redirected to isolated staging; original path, SHA,
identity and safety checks remained active. Shared index/event bytes stayed
unchanged. Content classification is research-derived, not primary certification
of all companies.

`CANDIDATE_STATIC_RECEIPT.json` binds the immutable static candidate. It preserves
all 493 active files, replaces only `workbench-host/received-research.mjs`, and
retains the existing 490-file serving allowlist, leaving three previously
unlisted files unlisted. Existing CSS and market-chain assets retain their SHA.
The proposed API plist changes only `V4_RESEARCH_PANEL_ROOT` and
`V4_RESEARCH_PANEL_ASSET_MANIFEST`.

Writer status: source tested, stage and candidate prepared. Independent review,
shared-root publication, service activation, live API/UI and natural-run
verification are separate steps; this document does not claim them. No service
operation, deployment, merge or quote fix is performed by this patch.

`RESEARCH_ONLY=true`; `production_allowed=false`; `buy_gate_updated=false`;
`orders_sent=false`.
