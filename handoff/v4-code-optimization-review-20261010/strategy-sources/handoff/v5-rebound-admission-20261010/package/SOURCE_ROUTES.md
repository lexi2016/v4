# Existing source routes and prerequisites

This is a read-only summary of contracts already present in the frozen source snapshot. It is not an instruction to fetch data. None of the producers below was invoked for this handoff.

## TDX VIPDOC `.day` updater

Frozen source: `V5/vendor/hk_preselection_baseline/upstreams/v3_shared_data/shared_data/hk_0_2.py`, SHA-256 `27da90f0e623e45fa1a27af7dcc3b6e5e1ff2320bae1c61bd903ed82050beb89`.

Relevant functions:

- `_vipdoc_lday_root(tdx_root)` resolves the existing `vipdoc/ds/lday` root (or a direct lday root) containing `71#*.day` files.
- `_read_vipdoc_increment(lday_root, *, after_date, through_date)` reads native 32-byte records and emits dates/codes/OHLC/amount/trade, with source path `vipdoc/ds/lday/71#<code>.day`.
- `_enrich_vipdoc_increment(existing, increment)` applies the frozen enrichment logic.
- `update_hk_0_2_panel_from_vipdoc(asset_root, *, tdx_root, through_date, minimum_code_count=500, minimum_positive_coverage_rate=0.8)` is the ordinary append path. It requires a date increment and market-wide coverage; `through_date <= current_max` can return `already_current` and does not repair an old window gap.

The local repair wrapper source is `V5/src/v5_shadow/rebound_panel_repair.py` (preimage SHA-256 `8c912de834dfaebaa0a0973fbe015cf65d2326e06de2a0677918e00df5a696a8`; date-compat after-image SHA-256 `9f547b8d2307b847b3d284eff2e5914d715283a06eb427044074b34bdc3114da`). Its interfaces are `prepare_internal_gap_repair(module, asset_root, *, tdx_root, request, authority)` and `update_hk_0_2_panel_from_vipdoc(module, asset_root, *, tdx_root, through_date, repair=None, authority=None, **normal_options)`. Explicit repair additionally needs the exact parent pointer/manifest/panel hashes, exact missing `(code,date)` keys, native file SHA bindings, and an independently deployment-bound `OwnerRepairAuthority`. A raw PyTDX repair request is a distinct contract; do not relabel it as VIPDOC. The documented raw repair sample is only one code and does not establish unit or price basis.

Before a future owner run, the actual configured TDX root and exact missing native records must be read-only audited, each source file's SHA and 32-byte record must be bound, and the owner deployment must provide the approved request/capture binding. This package did not read a full raw file or start the updater.

## PyTDX daily sidecar

Frozen source: `V5/vendor/rebound_repair_baseline/hk_daily_supplement.py`, SHA-256 `fa7dcbce4ee026b0a02c47220820d0407af183553d3304afcc5db425dce33cbd`; canonical source manifest identifies `lexi2016/v4` commit `74478a0e62be215c8527ccc9a14b89b51042d014`, with unchanged AST extraction for `_finite`, `_bar_date`, and `_decode_bar`.

- `capture_daily_supplement(authority_root, *, target_date, canary_codes=None, connector=_connect, clock=_clock)` performs provider reads via `api.get_instrument_bars(category=4, market=71, code=<bare code>, start=0, count=6)` and writes a separate immutable sidecar. `requested_sessions(target_date)` is the target plus its previous five full HK sessions, so this producer can provide at most six daily bars per code; it cannot supply the full 60-high plus close lookback. It does not itself attest eligibility; an explicit canary is limited to three codes, stays in `canary_staging`, and is unreadable by the normal consumer.
- `read_verified_daily_supplement(authority_root, *, target_date, requested, research_cutoff, expected_panel, expected_master, expected_codes)` validates target/calendar, panel/master identities, requested sessions, and cutoff.

The source contract records trade at scale 1 and does not prove a SHARES/LOTS unit; six bars also do not prove the complete 67-cell window, a price basis, currency, or session finality. A future source path therefore needs an owner-approved date range/request, full raw request/response/timing evidence, decoder/source binding, explicit quantity and price basis evidence, and product finality support. Do not run the existing request unchanged as a historical repair.

## Existing Futu contract and historical quota receipt

Local source contract: `V5/docs/CAPTURE_MASTER_PLAN.md` (SHA-256 `e854841aaa568affe631ba15f6bba9f92cb9490ae1b6186046220048f1ca6472`). The existing V5 adapter exposes `prepare_futu_master(records, snapshot_receipt, binding)`, `publish_futu_master(prepared, binding)`, and `read_futu_master(reference, binding)` in `V5/src/v5_shadow/capture_master.py` (SHA-256 `03dd0d95d6cb6a1d2aac1470c894cb13c21767336e00f5cc168ed40886191fa6`). `SnapshotRecorder` in `V5/src/v5_shadow/snapshot_recording.py` (SHA-256 `3641e75f7f193f44b1cf781989eb4505c7b8698908ad3a794cb39b098f6f7fbb`) records existing SDK snapshot calls; its receipt explicitly leaves membership unverified and does not create source/owner approval. This snapshot/master route is distinct from historical K-line repair.

An existing historical K-line script is `/Users/lexi/Documents/Codex/2026-10-09/task/rebound-owner-ebe5944e/evidence/capture_five_once.py`, SHA-256 `e5006ec6f1f7e4b327d67e51005123a9ad58caff596854e7d501d413292cc05a`. It has no CLI and hard-codes five codes. Its one-page request calls `request_history_kline(code, start='2026-07-15', end='2026-10-08', ktype=K_DAY, autype=AuType.NONE, fields=[KL_FIELD.ALL], max_count=100, page_req_key=None, extended_time=False, session=Session.NONE)`. The capture marks `run_class=MANUAL_RECOVERY`, `historical_pit=false`, `volume_scale_applied=1`, and `volume_unit=NOT_EXPLICITLY_DOCUMENTED_ON_HISTORY_FIELD_PAGE`; it is not a full-pool source or an owner approval. The script and its SDK output are not included.

The historical recovery contract names `get_history_kl_quota(get_detail=True)` as a bounded read-only quota check and, only if authorized, a canary of at most three codes with one historical daily-bar request per code, explicit `K_DAY` and `AuType.NONE`, bounded dates, and saved raw fields/timestamps. Cross-source volume mixing requires a demonstrated common unit; a Futu request by itself does not establish that TDX historical volume shares the same basis.

Two historical quota snapshots are present and are reported separately. The `capture_five_once.py` run's `evidence/futu-five/quota.json` has SHA-256 `e366010775a428b3bd4d29c62dcd18d6d35fbfbfb5bd168018d81e6e55ad8aae`; it records `2026-10-10T00:59:50.618835Z`–`2026-10-10T00:59:50.623032Z`, `ret=0`, `used=96`, `remaining=4`, and 96 detail entries. A separate receipt summary, SHA-256 `74f9a1e38a01691a0f9942df2fc35b490b3c86fb180cd7506ea45767b5e806fc`, records `2026-10-09T16:33:41.158289Z`–`2026-10-09T16:33:41.165456Z`, `ret=0`, `used=99`, `remaining=1`, 96 details, 93 for the 695 target codes. These are historical snapshots, not current availability or permission; no inference is made about why the values differ. Current quota, current SDK/connection, owner authorization, allowed codes/dates, and matching units are unknown. No quota call or Futu fetch was made for this package.

## Practical resume gate

Resume only inside the configured original owner after it supplies (a) current source authorization and quota/status evidence, (b) exact target and approved bounded request, (c) complete raw source/capture timestamps and stable request/response hashes, (d) independently reviewed source/decoder/unit/price basis/finality contract, and (e) pre-pinned deployment trust and membership/owner-cell attestations. Keep unresolved codes pending; preserve the two-gate rule and `694_BATCH_HOLD`.
