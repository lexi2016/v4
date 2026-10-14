# Flash announcement experimental candidate: archived failures

Source root: /Users/lexi/Desktop/学习/agents调试/助手/qwen_flash_next_20261013/pipeline_canary
Base commit: b75d66d5673245bc8bfbe3d19f45de6c3364875f
Runtime: isolated Python 3.12.13 venv, oMLX 0.7.0, qwen3_8_flash_next, Thinking Off, one article/request.
Canonical V4 and its deployed runtime were not changed. This directory is a candidate handoff, not deployment.

## Status at research pause, 2026-10-14
Offline candidate regression checks were independently rerun (49 checks plus 3 narrow boundary checks passed). Real visible six-article runs did NOT pass independent semantic acceptance. Twenty-nine-article pressure phase NOT_RUN. No grammar dependencies installed and no grammar candidate implementation at pause.

| Profile | Six-article wall seconds | Mechanical results | Independent semantics |
|---|---:|---|---|
| source_bound |225.558|3 pass, 3 quote failures|FAIL|
| source_span |136.171|6 pass|FAIL: evidence ranges did not support compound claims|
| source_range |134.545|5 pass, 1 wire-schema failure|FAIL|
| source_range_single/untrusted-r2 |not summarized|3 pass, 3 failures|FAIL: cumulative buyback/pending cancellation confusion and unsupported disclosure claims|

Last failures: INVALID_JSON, EMPTY_MODEL_OUTPUT, SOURCE_RANGE_WIRE_SCHEMA_INVALID. Exact source citations alone did not prove semantic correctness. Model raw responses and failed attempts remain unedited locally and are intentionally excluded from GitHub. Local runtime logs showed missing xgrammar and response-format fallback; no claim of a tested remedy.

Latest frozen manifest SHA256: 76180ae28e9589449fb6a960a2198e4ecb1764616f91f875249b5887ccc3b47b
Prompt SHA256: 25974f566ed38f85d55186d9ab0d1d87b15e39e7aac2557b2c5611d9c0489716
Six and twenty-nine cohorts overlap once (34 distinct articles). No business data, credentials, raw sources, manifests, model responses or runtime environments included here.

## Files
- batch_runner.py: before Git blob 26304ce5a8027a88efd0f7b2b456d535d967fc43; after SHA256 8c5f611a6c3220a38d7b9876c33e61b257a994ef72a69cfbe35230b060a0500c
- automatic_canary_server.py: before Git blob 6013fd6a977b9320bc216d6a6f4926f9eead594a; after SHA256 c9aa4f42d32ad2d220a09355cede63f9cc05c9b2f9bb5c33285715fe682a7acb
- test_batch_runner.py: before Git blob fca3cf8bc7231bc7711358a5dad0c9a21e9bcbdd; after SHA256 f6a794328b9f4e9d204c6935f9343fbdab64a52bba33368d6c32022977546f5d
- test_automatic_canary_server.py: before Git blob 605a9ee68184c0c7c7f917c3c06741fe54ae49fa; after SHA256 b788407d7c74072fbed0b6612416d77c545a8bb5b24375e6b59490ae35542d84

Research-only: production_allowed=false; buy_gate_updated=false; orders_sent=false. IMPLEMENTED candidate; independent semantic REVIEWED=FAIL; BEHAVIOR_VERIFIED=FAIL; INTEGRATED/DEPLOYED=NO. Subsequent simple-workflow work must use a new evidence root and preserve these failures.
