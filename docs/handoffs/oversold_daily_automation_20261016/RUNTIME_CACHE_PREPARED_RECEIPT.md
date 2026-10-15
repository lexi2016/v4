# OVERSOLD cache-first scheduler candidate preparation

Status: PREPARED_NOT_ACTIVATED; source repair review PASS; independent runtime release review is pending.

Candidate oversold-daily-cache-20261016-r1 manifest SHA-256: 03f1c61fe881039b286bd4d0d9acbcb29d32593747e7c0119b8e3c261237bfb2.
Staged plist SHA-256: 12fec20f665af3ce0a20ffd2c989684ff580c36ae2d932fdc285bb798e93d137.
Fresh active base zsxq-pdf-ocr-scheduler-20261016-r4 manifest SHA-256: 4710696eb61e60ac5dbd1ea56aa2e7a3762d9c1f9170d206b4dc0beac4769e91.
Active plist preimage SHA-256: e347c7a08037948a1d1a40e392f8ad95ce28a2555306a94dcb17513346a82d72; saved at /Users/lexi/Desktop/学习/v4_app/docs/handoffs/oversold_daily_automation_20261016/active_scheduler_plist_cache.preimage.
Manager-v7 config SHA-256: 65684e5eb7657390747c089db74047d6a2c67d7f5de1bd3fe757a62f120965ca; existing config binding is unchanged.
Only these app paths differ: upstreams/v3_shared_data/shared_data/hk_daily_supplement.py, v4/manager_workbench/oversold_daily.py.
Non-delta entries preserved byte-for-byte and mode-for-mode: 1027, inventory SHA-256 f7f36aafc7bd7d48d06e63b16d6f700a2b7b2da850ecc5970de057a6dc35a44f.
The configured scheduler interpreter imported 7 modules from the isolated candidate app root.
The staged plist preserves the existing manager-v7 config path, schedule, external roots, launch policy, and false research safety flags.
CAS plan: /Users/lexi/Desktop/学习/v4_app/docs/handoffs/oversold_daily_automation_20261016/SCHEDULER_CACHE_CUTOVER_PLAN.json.

Source repair review PASS: CACHE_FIRST_INDEPENDENT_REVIEW.md SHA-256 fcd4541507fd76baa3b49de27d150f01f902e3eb611a78c6a9504786d617cab8.
CANNOT_CONFIRM: independent runtime release review; activation or live recovery; live TDX behavior; API/UI readback; natural scheduled output.
No active plist/config, service, cursor, old plan, API, or UI was changed.
Research safety remains RESEARCH_ONLY=true, PRODUCTION_ALLOWED=false, BUY_GATE_UPDATED=false, ORDERS_SENT=false.
Preparation note: the first attempt stopped after the existing staging renderer reported a colon-delimited PYTHONPATH as a missing rebound path. The already-created candidate was resumed without recopying or repatching after exact source, manifest, inventory, runtime import, and staged-plist checks passed.
