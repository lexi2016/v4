# D16 legacy NAV suffix adapter

## Scope and implementation

For same-day A-share rows already admitted on the canonical QFQ prefix, recover only `nav_pullback` / `nav_breakout` stage and anchor inputs when the unchanged census returns `UNKNOWN_NONPOSITIVE_OR_INVALID_PRICE`. The fallback validates the ordered full prefix, formula outputs, aligned finite OHLCV, the clean positive-price suffix, OHLC geometry, and the original anchor before accepting a stage from the unchanged census. Other formula outputs and gates remain unchanged.

- Source: `ops/research_panel_daily_product.py::source_inputs`
- Focused tests: `tests/test_d16_legacy_nav_suffix.py`
- Base commit: `4642d7096`
- Sealed candidate overlay SHA-256: `ae078459f7ddbb13f2966e09ff5f9bd37c69c5e1c9dfe8102cd7e9fc03b4ba48`
- Patched `source_inputs` SHA-256: `43ae6b13ad6c98f39d2b350205cdf0558a7a6f2a9cc1755cd184688663eb9e75`

## Verification and state

- Focused tests: `python -m pytest -q tests/test_d16_legacy_nav_suffix.py` — `3 passed` in the project's configured Python environment.
- Independent overlay review: `PASS` for four real cases plus focused review; receipt SHA-256 `1011cfe3d7e07debd1820d232b83ec37d31120f6f82a858defb234fd38723a33`.
- Separate bounded 244-row business run: independently targeted 187 fully resolved symbols and 30 additional candidate symbols. Exact computation SHA-256 `aa6784c616a43a7367d317cd2742f1a81db9b4af25e90e98e739ec1ec5bc7563`; derivative publication is pending.
- Candidate remains sealed and unapplied. Integration, deployment, API/UI verification, and natural-run verification: `NOT_RUN`.

Research safety flags remain `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`.
