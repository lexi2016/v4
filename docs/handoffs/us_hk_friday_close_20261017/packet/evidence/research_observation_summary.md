# Friday US observation summary

- Target session: US `20261016`; capture was a local Futu after-close snapshot queried 2026-10-17 23:10:34.936–23:10:35.544 HKT, not a verified official daily-close bar or shared owner receipt.
- Snapshot coverage: 448 requested non-OTC symbols; 446 have a valid exact-session after-close timestamp and positive last/previous-close prices; EEX and MIMI remain `CANNOT_CONFIRM` because update timestamps are absent.
- Frozen mapping identity: 667 HK codes / 1,003 unique relations, overlay SHA-256 `3289f0329f0fe2e447a70386341790cb9821df2e76d13a650143fe07f9e9e91c`; relation status totals are 757 `CLOSED_RESEARCH_SCOPE`, 221 `OPEN`, and 25 `CLOSED_EXCLUDED_SCOPE`.
- Snapshot-direction buckets over the 1,003 relations: 270 positive, 430 flat-or-negative, 57 missing, 221 `OPEN`, and 25 excluded. `OPEN`/excluded precedence is preserved. Positive is a source-price observation, not a claim about HK price effect, causality, investment merit or executable return.
- The canonical shared owner payload for Friday US session, official daily close, refreshed selector result, API/page, notification and natural-slot acceptance remain `CANNOT_CONFIRM`.
- Reviewed P2 display limit: `top20_us_observations.csv` builds linked HK codes across all relation statuses, so its list may contain `OPEN` links even though no `OPEN` row enters `candidate_stocks.csv`; use `candidate_stocks.csv` and `positive_relation_observations.csv` for closed-scope positive candidate evidence.
- Reviewed P2 tooling limit: the builder accepts `--verify` but rebuilds/overwrites outputs. Any replay must run from an isolated temporary copy and must not call either capture script. This does not change the frozen result.
- Oil-linked positive source-price movement can be cost pressure for airlines and similar users, not an automatic benefit direction.

The reproducible frozen report is `../../reports/REPORT.md`; machine summary is `../../reports/results.json`. Raw quote capture, full CSV tables and mapping input are intentionally omitted from the issue ZIP.
