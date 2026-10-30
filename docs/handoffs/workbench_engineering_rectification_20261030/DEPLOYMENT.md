# Mac workbench r2 deployment and direct-read SOP

Recorded 2026-10-30 (Asia/Shanghai). The installed API is `workbench-rectification-20261030-r2-api`. Application manifest SHA256: `0d246eaf7f7be970029061b9c024a6857589796d0d5d3dafed016ba6614b9cda`. The final Writer source-freeze SHA256 is `ce296d5f05b99acf073b3833381fe142ae0dc0defe65a49c26aba6bca96ee121`.

The canonical entry is `/research-panel/workbench.html`. Homepage research navigation preserves the current URL date; the old `daily.html` returns307 with the query preserved. An unavailable date stays unavailable. The explicit `legacy-daily.html` alias reads the old fixed `待删除/legacy-daily.html` by SHA. The source HTML and replaced compiled homepage bundle were moved rather than permanently deleted. The original renderer and fixed46 Dot source remain dependencies; the remote48 framework namespace is preserved.

## Classification: import once, read saved data

The Mac's persistent root is `<V4_STATE>/research/classification/`. `current.json` points to an immutable version manifest and read-only SQLite with a checked byte SHA. Version `d9da99e43eba781ff074a2c13a370f47f5fb3116a3ce0ba5da475396333de4bb` stores6511 source rows: A5575, historical HK935 and separate CDR1. Database SHA256: `7026d234a8dd2bffd4e9b69abc9afff32c4616c6ea3ec10d3ef182e70f4a17b3` (60,473,344bytes). Raw classification files, SQLite, private bindings, logs and market data are excluded from this Git delivery.

Runtime GETs do not fetch Drive, call a vendor, import data or compute historical returns. These readonly endpoints consume the saved index:

- `/api/v4/research/workbench/classifications/A_SHARE`
- `/api/v4/research/workbench/classifications/HK_CONNECT`
- `/api/v4/research/workbench/classifications/CDR`
- `/api/v4/research/workbench/days/{source_date}` supplies the exact current symbol/name join.

Current247 result:244 exact symbol/name bindings,3 name conflicts isolated. `689009.SH` joins the separate CDR record. A conflict yields no classification and cannot enter theme filters. Business industry, official major category, raw/normalized themes, roles and catalysts remain separate. Original observations, later lookups, publication dates, gaps and partial status are preserved. HK935 is a historical source collection (667buy records plus268 rule-derived sell-only records;213 unresolved records/136 codes separate), never today's eligible pool.

Only an approved new source version needs another offline import. Existing same-source versions and unchanged markets are reused. Use the verified absolute project Python and the existing CLI, with SHA-bound local source refs:

```sh
"$PANEL_PYTHON" -B -m infrastructure.research_classification_view --source-refs approved-source-refs.json --output "$V4_CLASSIFICATION_ROOT"
```

Do not run an import during page requests, recollect the same raw sources, overwrite immutable versions, infer missing classifications or strip ST/name changes to force a join. A pointer/database identity failure clears labels and reports CANNOT_CONFIRM.

## Verification and updates

New behavior: Writer9 focused tests; independent Reviewer8 tests plus a separate bad-pointer probe; original map2 tests passed. R4 tests/review were reused. Candidate browser checks covered1440/694/390 widths, the real D17 homepage click, D28 old URL, source details and robot/chip union without duplicate rows. Formal8873 transport/UI and SH/SZ/BJ source-parity readback passed. The frontend-build endpoint identifies `main-workbench-entry-8008e8728f18.js` and reportsVERIFIED with the r2 API.

The original Main daily cache hook remains installed and was preserved through the separate SOP Main update. The new observation LaunchAgent has35 calendar slots, no RunAtLoad and no manual natural-run substitution. Natural19:00 acceptance: launchd first run exited0, manual=false,247/247 original close/archive records committed at19:00:03; saved-source reuse flowed throughAPI and an already-open page. Browser navigation/time-origin, selected688816.SH and120-bar view stayed unchanged. Only observation/context/workflow versions changed; list/statistics/classification stayed unchanged. Next slot2026-11-02 08:00+08:00. This verifies an archive-reuse chain, not fresh-provider acquisition or a complete intraday chain. Source-only archive refresh and a complete intraday quote chain must be distinguished.

D30 product publication remains blocked upstream; original generated artifacts are retained. Intraday source-date proof, Japanese automatic HTTP403, material/classification gaps and PIT/current eligibility are not certified by this software delivery. Research figures stay descriptive.

## Rollback and repository handoff

Rollback API only to `workbench-rectification-20261030-r1-api`, using the saved prior plist under the same release lease. First compare the actual current plist SHA to `21976bf4c490c6436e130ffc70ab4d9d415c1494f7eb8edaecb41cd74963433e`; stop if identity changed. Preserve classification, accepted labels/outcomes, raw sources and other Main/scheduler work. The r1 Main directory remains an active dependency of the observation caller.

This source delivery targets `codex/dashboard-framework-collab-20261030`, based on a freshly read branch head with CAS, no force. Unlisted files,48 framework blobs and the parallel SOP fix remain unchanged. The actual commit and byte/tree readback are recorded in Root's local delivery receipt and the commit containing this file.

RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.
