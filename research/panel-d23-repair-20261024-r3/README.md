# D23 A-share panel repair R3 source archive

This directory preserves five allowlisted helpers/tests whose current bytes match the independently reviewed R3 source bindings. The R3 review closed two P2 findings: the collector checks selector and backtest target content against the confirmed publication-stage SHA before row loading, and the READY evidence distinguishes historical R1 preflight material from the current R3 `NOT_RUN` state.

The archive is for source review and provenance. It is not a directly deployable program: the helpers depend on the original pinned producer and its local runtime specification, which are intentionally excluded. The earlier A23 TDX14 source archive at commit `cbbf5e84534a23b1e0772b43e134b5f76e53d316` is reused from remote history and is not copied into this directory.

The independent R3 Reviewer recorded the focused regression as 2 passed. The R2 publication-guard suite (10 tests) and R1 source suite (8 tests) were reused by exact SHA and were not repeated during this archive sync. See `verification.json` for the compact review scope and unresolved runtime outcomes, and `source-hashes.json` for each archived file binding.

This source archive does not establish full-run completion, live panel readback, runtime binding, deployment, automatic scheduling, or natural-time recovery. Research and trading safety flags remain `research_only=true`, `production_allowed=false`, `buy_gate_updated=false`, and `orders_sent=false`.
