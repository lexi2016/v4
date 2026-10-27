# 00068 2026-10-27 bounded research collection

Scope B: one stock, one trading date, quote-only Futu OpenD on localhost:11111,
plus public HKEX CCASS / DI. No UI, screen capture, order, amendment or trade-unlock API.
This is a batch export, not a new panel, authority data layer or long-lived service.

- Baseline commit: 55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054.
- Branch: codex/qunhe-watch-20261027; other worktrees and modifications preserved.
- Source: scripts/qunhe_20261027_watch.py; tests: tests/test_qunhe_20261027_watch.py.
- Interpreter: /Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python.
- Output: /Users/lexi/.codex/exports/qunhe_00068_watch_20261027.
- RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.
- Acquisition: every minute 09:15–12:01 and 13:00–16:10, plus 16:10:30.
- Reporting: user confirmed 09:30–10:30 every five minutes, thereafter every ten minutes during trading; fixed nodes 10:30/12:00/14:30/16:00/16:10.
- Source validation: days_before=0, true real-time flag, today's row dates. Deltas require fresh consecutive timestamps, continuous top-10 visibility and monotonic cumulative gross fields.
- Dropped seats retain last known gross values and signed top-10 bounds; missing is never zero.
- CAS: save 16:00 baseline; final market confirmation requires an auction print and market update after 16:08. Broker CAS completeness has a separate status.
- Post-close: bounded hourly CCASS/DI requests starting 18:30, ending next morning 07:30. Actual returned date must equal 27 October. Total balance change is observed, not forced to zero.
- T+2 residual is not proven SI: Friday baseline lacks CAS and execution-to-clearing/beneficial-owner mapping is incomplete.
- Gross sell price is not identifiable from bidirectional turnover; report all-side VWAP with explicit scope. Intraday short-volume source is unconfirmed, not zero.
- Singleton output lock, resumable frame/last-known state, atomic JSON writes. Three consecutive source failures stop collection for diagnosis and retain evidence.

Verification sample: gross/delta arithmetic; false historical rows and signed dropped-seat boundaries; CAS evidence and schedule boundaries. Pass requires no stale row promoted to today's flow, no zero-filled missing seats, and no clock-only CAS confirmation. One live pre-open sample verifies SDK connectivity; it does not certify natural intraday or CAS coverage. Actual start, latest status, errors and coverage are recorded under the output directory.

Only source, tests and this compact record are eligible for GitHub sync. Raw quotes, CCASS response data, logs, account/position information and environment files are excluded.
