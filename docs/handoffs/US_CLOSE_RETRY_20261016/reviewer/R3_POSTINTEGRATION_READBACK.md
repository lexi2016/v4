# R3 Post-integration Readback

Date: 2026-10-16  
Reviewer: independent read-only reviewer  
Scope: final R3 manual recovery, current API/UI projection, activated US LaunchAgent identity, and preservation readback. No code edits, producer rerun, service mutation, or activation was performed by the reviewer.

## Verdict

**PASS for the controlled 20261016 recovery and post-integration API/UI behavior.** The final receipt records a successful late POST_CLOSE capture for source session 20261015, and the current API and stable rendered page both show READY with 48/48 quotes and the same capture identity. This does not prove a natural scheduled run. `GOOGLE_NEWS_RSS_DISCOVERY_ONLY` remains `CANNOT_CONFIRM`; the quote market projection is READY.

## Evidence

- Recovery receipt `candidate/evidence/recovery_receipts/20261016T044257Z-7de79788100e4ca6a666e09083ded1ce/receipt.json`, SHA256 `0aa1c911c823d0143f0a00533ca97a3ceb96e652d264b4b7cec03b5a3c3476e8`: `PRODUCER_EXIT_0`, exit 0, target 20261016/source session 20261015, POST_CLOSE, READY, 48 requested/available/quotes, 24 theme rows, capture `78b032efbb6b25a3a8a80693`, run `us-rss:20261015:POST_CLOSE:78b032efbb6b25a3a8a80693`, captured `2026-10-16T04:42:57Z`. Late and original-time capture flags are true; `PRODUCTION_ALLOWED`, `BUY_GATE_UPDATED`, and `ORDERS_SENT` are false.
- Current API evidence `integration/r3-us-market-after.json`, SHA256 `6de0e2f7ec222da78e8d953140bb51a451fff9f6b4ded1337e6d197de6e677aa`, records READY and the same capture ID/run at target date 20261016. The independent direct GET to `/api/v3/research/us-market?research_date=20261016` returned HTTP 200 with the current artifact and bound capture timestamp.
- Stable rendered page readback `integration/r3-ui-readback.json`, SHA256 `4ad6a48f8ab538b8f9c8b846d1be45f4e667ab81493e900a49a4610d2feba62c`, shows the “美股收盘板块涨跌幅” region READY, 48/48, target/snapshot date 20261016, source date 20261015, and captured time 04:42:57Z. It records `natural_run_proven=false`.
- Current canonical artifact SHA256 is `3753d3bb99d7a585587e01bc92c903d2c0920cffbf1c686dc4bea58f76eed4da`. `integration/history-preservation.json`, SHA256 `9db59c98d811e5990fad3680b58c412492b8ef5d3a187e1263d52babef49e6be`, records the content-addressed V2/33 payload `e65a6e82e21f7cba1667be19e01957184da6e415c329bbeb9ee5f4f934a3c368`, the intervening V3/48 payload `3c395a48f7d5d52f49e52cbbe77859bde661719b9bc01dfc1664e53a1f01c8c3`, and supersession links to the final artifact. The historical payload bytes and their hashes were independently verified; each remains available with its capture provenance.
- `integration/r3-activation-readback.json`, SHA256 `c417847ad12de7e7d2e4e51c5e0da35a40adc6d6f20f62b32e563429461b6def`, records launchctl exit 0 and the loaded US LaunchAgent pinned to R3 manifest `592bb39ce93fd9d564d34088403d96fd14213c2380991b239a458e80c72a9139`. The service is idle (`state=not running`, `RunAtLoad=false`, zero runs); this readback does not establish a natural scheduled execution.
- `integration/protected-inputs-final.json`, SHA256 `7625c8f95451675f16727cdb00a263c74ec924b8f9cadb046faf821d4e2a1752`, confirms the prior 20261015 artifact and the 0415/0515 dispatcher receipts are unchanged.

The prior `R3_PRODUCER_API_CAS_REVIEW.md` remains applicable to frozen code and CAS checks. Its P2 same-timestamp/distinct-capture misbinding boundary remains non-blocking for this target: the observed captures have distinct timestamps. Whether a natural tie occurs remains `CANNOT_CONFIRM` and is backlog per scope decision.

## State

`REVIEWED` / `BEHAVIOR_VERIFIED` for the controlled recovery, current API projection, stable UI, and protected-history readback. `NATURAL_VERIFIED` is not claimed.
