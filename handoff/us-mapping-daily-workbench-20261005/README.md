# Manager workbench US → HK research and daily workflow

The existing manager workbench now displays five independently reviewed 2026-09-30 retrospective relationships, with source links, US moves, product maturity, priority, and eligibility/PIT limits. The original failed preopen plan remains visible. Changing target dates never reuses those historical cards as a daily result.

The existing preopen Manager owner now refreshes a date-scoped mapping artifact using the prior complete US session and the reviewed relation registry. The existing US capture job retains its four local slots and accepts default launches up to 15 minutes late. Explicit slot arguments remain strict and actual capture timestamps are unchanged. Missing/partial inputs remain unknown; this is neither a full-market scan nor automatic discovery of new relationships.

Deployed locally as `manager-us-mapping-daily-20261006-r2`, manifest `430b774a0157b5bf78c34c1abdd4770df2deb61577642ec8fe3a5c537d74b956`. It retains the parallel R18 HK changes. The final real-state owner POST/GET and actual run.py HTTP readback agree on a CURRENT saved manual plan (PARTIAL overall). The historical live browser and current-date final-release preview passed. Existing job and binding configuration are installed. The actual-clock hook returned NOT_DUE without network requests or state writes. Natural capture and preopen execution remain NATURAL_SLOT_UNVERIFIED.

See `PAGE_DELIVERY.json` for the earlier page milestone and `DAILY_DELIVERY.json` for final runtime, source hashes, independent tests, retained failures and limitations. `canonical/` preserves canonical files and pre-existing edits; `release_delta/` records the scoped deployed overlays. They are deliberately distinguished. `operators/` contains the narrowly reviewed owner-binding helper and its isolated regression test. Tests were executed with the existing Python 3.14 service environment; no new environment was installed.

Research only: production_allowed=false, buy_gate_updated=false, orders_sent=false. No credentials, environment dumps, plists, raw owner responses, market data or built frontend bundles are included.
