# Futu R1 scope

```text
GOAL: Add a read-only Futu OpenAPI current-snapshot observation for every uniquely mapped, parseable active US-listed symbol in the current V4 catalog as quota-free snapshot coverage permits; preserve each field's update time and keep pre-market price separate; retain the 2026-10-15 exact daily K-line result for the three canary symbols as a separately labeled date-bound subset; regenerate descriptive HK observation coverage and point the top-level report to this R1 result.
WRITER: /root/today_mapping_observation_writer
REVIEWER: Independent Luna Max reviewer; pending
ALLOWED_PATHS: docs/handoffs/us_hk_mapping_today_20261016/futu_r1/** and docs/handoffs/us_hk_mapping_today_20261016/REPORT.md only
FORBIDDEN_PATHS: Frozen R0 outputs and review receipts; application source/config/services/schedulers; old producers; Futu watchlists/reminders/trading; unrelated paths.
PASS_SIGNAL: Live V4 catalog identity matches the frozen relation set; the three Futu daily-K canaries return exactly the requested date and establish read-only access/quota; snapshot requests and responses bind by requested code, failed batches use bounded splitting, current-snapshot metrics never use pre_price, the output conserves all 1,003 relations, and source/request/response/SHA/receipt evidence is recorded.
STOP_RULE: Stop the affected capture path on catalog identity drift, OpenD/API authorization failure, date mismatch, or response ambiguity. Preserve original errors and coverage gaps; do not infer no data from failure or switch silently to Tencent. Do not spend additional historical-K-line quota beyond the three canaries.
```

## Fixed request

- Provider: official Futu OpenAPI Python SDK through the existing local OpenD at `127.0.0.1:11111` using the installed V4 runtime. Read-only `OpenQuoteContext` only.
- Exact-date subset only: `request_history_kline(code, start="2026-10-15", end="2026-10-15", ktype=KLType.K_DAY, autype=AuType.NONE, extended_time=False)` for DASH, NTES, and UBER. Returned `time_key`, `close`, `last_close`, and `change_rate` are retained and checked against the derived percentage. The historical quota reported only one request remaining after canary capture, so no more daily-K requests are authorized in this batch.
- Broad observation: read-only `get_market_snapshot` for eligible catalog securities in chunks of at most 400 (the documented per-request limit); failed batches split deterministically with a finite attempt/depth bound. Main ranking metric is `(last_price / prev_close_price - 1) * 100`, labeled `snapshot last price versus API previous close` and paired with `update_time`. `pre_price` is preserved as a separate field and never used in the ranking metric.
- Market eligibility comes from each catalog relation's actual `source_record.exchange` and `asset_class`. A `US.` Futu code is formed only after an active US securities exchange is explicitly present. Commodity futures, macro series, historical/delisted securities, unknown exchanges, and conflicting market identities are isolated individually. Futu returned a market-wide OTC unsupported error (`暂不提供美股 OTC 市场行情 AAGIY`) for the initial mixed batch; the full response/split evidence is retained in `snapshot_capture_initial_otc_batch_attempt.json`. The 45 OTC-only catalog symbols are therefore explicitly marked provider-unsupported, while the other 448 active symbols are queried.
- The snapshot request is a late 2026-10-16 Asia/Hong Kong research capture. It does not establish availability before the 2026-10-16 Hong Kong session. A current snapshot metric is not a verified 2026-10-15 session return. The 3-symbol daily-K subset remains separately date-bound. Results remain descriptive, research-only, and do not assert a causal link, forecast, or BUY signal.

## Documentation

Futu documents that `start`/`end` accept exact `yyyy-MM-dd` dates; US K-line `time_key` uses Eastern time; daily K-lines expose `close`, `change_rate`, and `last_close`; pre/post-market K-lines are limited to minute intervals. See [Futu: Request History K-line](https://openapi.futunn.com/futu-api-doc/quote/request-history-kline.html).

Futu's snapshot endpoint is [Get Market Snapshot](https://openapi.futunn.com/futu-api-doc/quote/get-market-snapshot.html). Snapshot capture preserves `update_time`, `last_price`, `prev_close_price`, and separate `pre_price`. The derived metric is a current snapshot comparison and is not relabeled as an exact historical-session return.

## Reproduction

- Snapshot capture and output build: `'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' docs/handoffs/us_hk_mapping_today_20261016/futu_r1/capture_futu_snapshot.py --capture`
- Rebuild from the saved raw snapshot response: use the same command with `--rebuild`.
- Verify hashes, coverage conservation, metric formula, and safety: use the same command with `--verify`.
- `capture_futu_daily.py` exposes only the three-symbol exact 2026-10-15 K-line canary; it does not expose further historical-K batch capture in this R1 scope.
