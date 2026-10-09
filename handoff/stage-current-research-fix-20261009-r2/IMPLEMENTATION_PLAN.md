# V4 Stage current-day research R2 Implementation Plan

> For agentic workers: execute the assigned scoped task, RED then GREEN, and record exact source provenance. Root integrates and arranges independent final review. Latest user explicitly authorizes direct implementation; no design approval pause.

**Goal:** produce research selections through the original input -> minute source -> original algorithm -> stored result -> existing API/UI chain, including explicitly opted-in current-day HK research when strict D1 eligibility is missing.

**Architecture:** Keep STRICT default unchanged. One read-only HK adapter binds the four existing source files and carries clearly limited current-day metadata through the existing StageUniverseBinding, collector, selector, stores and receipt. No new producer, authority layer or API modularization.

**Tech stack:** original Python Stage facades/helpers and stores; existing Vue/TypeScript UI. Test the actual archived code interfaces with explicitly synthetic source data; never claim access to Mac-local input files.

**Spec:** latest user instruction in this conversation, 2026-10-09 17:05:26 Asia/Shanghai; fixed parent 0fc3e8304e11700230517616ded0c86f83a4b257.

## Global constraints

- Preserve original algorithm score, weights, sort and Top10; retain 216 A input and single-symbol quote gaps.
- RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.
- Opt-in config `hk_current_day_research_root`; invalid configured research input fails HK locally, never silently becomes D1.
- The authorized input set is 695 security metadata rows captured 2026-10-09T15:38:41+08:00 with universe_as_of=20261008, stale_universe=true and current_connect_eligibility=CANNOT_CONFIRM.
- Security metadata contains no quote/OHLCV/provider_data_time. Original PyTDX minute source supplies quotes; capture and quote cutoff must each be legal for the selected stage.
- Do not rewrite historical data, materialize a second authority pool, change actual Mac files, or coordinate the Mac sessions.
- New files are candidates. Existing source paths with only historical before bytes are clearly listed once and protected by exact SHA on application.

## Shared interface

`stage_center.hk_current_day_research`: `is_current_day_research(binding)` and `research_metadata(binding)`. Binding role is CURRENT_DAY_RESEARCH_ONLY; canonical JSON metadata is also carried in `hk_current_day_research=<JSON>` source evidence and final envelope.hk_current_day_research. Metadata has input_mode, universe_as_of, captured_at, stale_universe, current_connect_eligibility, safety flags, trade_date/stage_id/cutoff_at, input_binding_sha256 and source_files (file and original bytes SHA for four input files).

## Tasks

- [x] HK: add read-only binding module and config/runner/input/slot/node forwarding; RED tests for absent opt-in, exact pins, invalid date, future capture, full codes, strict isolation and manual mode; implement; GREEN.
- [x] Collectors: original HK ExHQ minute path consumes explicit research binding and original four-lane observation scoring without fabricated membership lanes; A auction previous-close propagation; optional research overlay failures isolated at consumer boundary; RED same-symbol and source->builder->real-selector/store cases; implement; GREEN.
- [x] Root receipt: bind research source file bytes to result/input receipts; record source identity tied to actual execution and final archive; retain scoped sibling evidence; RED forgery/mismatch/manual/source-change cases; implement; GREEN.
- [x] API/UI: actual current consumer + existing reader and Vue render original stored result independent of natural-proof status; validate date/stage/market/run/raw/algorithm/research metadata; RED store->consumer->reader->render tests; implement; GREEN.
- [x] Root integration: import assembled candidate, run original real storage chain using synthetic provider data and exact public functions, check after-capture stage and morning rejection; unchanged STRICT and A216, missing optional context, tamper rejection, cold process import; independent review and fix material issues.
- [x] Package: minimal per-owner runtime patches (from restored before and from R1 where appropriate), complete changed after files, exact source map, concise commands/tools, targeted raw test receipts; new branch from 0fc3, commit and remote readback.

## Review focus

1. Explicit research activation must survive every config/facade/helper boundary and Stage8 branch.
2. Partial legitimate results remain visible while core provenance failures still refuse the affected input/result.
3. Research time cannot be before security capture and never implies historical membership or natural triggering.
4. Final selection identity covers metadata and the raw artifact; receipt stores the same run and original hashes.
5. The exact existing source witness error is preserved; a rejected optional overlay contributes no unverified bonus.

## Rulings

- Current user instruction overrides earlier strict-only workflow; optional research mode is the requested new business behavior. Default strict and core candidate/quote checks remain.
- Module-release-isolation package is a source provenance reference only; its r5c logic and workflow are excluded.
- Archived source snapshot omits generic `_namespace.py` helpers in several locations. Tests may load identical verified generic helper bytes as explicit support; these files are not runtime patches and cannot prove full current Mac identity.

## Final code verification

Fresh isolated canaries: actual Stage/API 115 passed and canonical Stage/actual API 115 passed; all candidate code SHA inventories stable. All six patches passed byte-exact forward/reverse verification. See TEST_RESULTS.md for declared archive support and current Mac limits. Fixed parent remains 0fc3; the commit is identified by the containing Git object, avoiding self-referential commit hashing.
