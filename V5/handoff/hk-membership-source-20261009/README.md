# HK membership source snapshot for V5

Unmodified Mac source snapshot from `manager-us-mapping-daily-20261006-r2/app`. This is a source/contract handoff, not a deployable release, qualification publication, natural-run receipt, or reconstruction of original Git history. Embedded source-head identifiers are retained as original source text; their availability in the destination repository is not asserted.

`manifest.json` records each original/copy/post-copy SHA256. `dependencies.json` records the module-level static local-import closure and separately lists lazy imports. The package contains source text only: no SDK frames, prices, business records, account data, credentials, runtime configuration, or log contents.

## Loading and scope

Add `source/` to the isolated Python import path. `ops` and `domains` are namespace packages. The two existing light package initializers are unchanged. Load `stage_center/hk_universe_preflight.py` with `importlib.util.spec_from_file_location`, as the original owner does; the broad original `stage_center/__init__.py` is intentionally excluded. Pure membership validation/build uses standard library only. Calling `ops.macos_research_panel_daily` CLI or unrelated lazy paths is outside this closure. No live owner, network, scheduler or publisher was executed for this package.

## Exact entry contracts

- `ops/_macos_research_panel_daily_parts/hk_market_capture.py::_collect_hk_futu_rows_body(scope, target_date, *, context_factory, batch_size, minimum_universe_count, required_coverage_ratio, membership_ready_callback=None)` captures original provider evidence. Its injected scope is `vars(ops.macos_research_panel_daily)`. Do not invoke it to repair already captured evidence. The live SDK is an external optional dependency, not vendored.
- `stage_center/hk_universe_preflight.py::validate_captured_hk_connect_membership_v2(capture, *, trade_date=None)` is pure. Requires exact two plates, integer success return codes, columns/rows, frame hashes, aware ordered timestamps, code union/overlap, source/producer identity, acquired_at=max(completed_at), source hash and capture hash. Returns validated membership and lineage; does not validate quotes or valuation eligibility.
- Same file: `build_captured_hk_connect_authority_v2(capture, *, trade_date, producer_owner, contract_owner)` is pure. Returns artifact/capture/manifest/receipt/current bytes and hashes, run_id, paths and publication-relative path. It does not publish.
- `ops/ensure_hk_security_master.py::_publish_captured_hk_connect_authority_v2(*, store_root, trade_date, capture)` writes only to the explicit root, validates immutable bytes, reads each file back, then records actual publication availability. This is a MUTATING owner entry: use a separately authorized V5 private root only. It loads the adjacent pinned contract file by path/SHA.
- `domains/manager_research_evidence.py::read_universe_evidence(root, trade_date, *, as_of=None, clock=..., authority_owner_root=None, authority_owner_sha256=None, require_v2=False)` returns `VerifiedUniverse(codes, source)` after chain/publication/as-of validation. For v2 use `require_v2=True` and explicit owner pins.

## Minimal SDK shape (no real rows)

Outer fields: schema_version, target_date, capture_run_id, producer_owner, plate_responses, status and false safety flags. Each plate response contains requested_plate, serialization_version, columns, rows, return_code/type/ok, requested_at, completed_at, row_count and response_sha256. Frame columns: code:string, lot_size:integer, stock_name:string, stock_owner:string-or-raw-missing-tag, stock_child_type:string-or-raw-missing-tag, stock_type:string, list_time:string, stock_id:integer, main_contract:boolean, last_trade_time:string. A raw missing tag may be `{"$float":"nan"}`; it is evidence encoding, not a business value.

## Serialization/eligibility constraints

The original frame serializer preserves nonfinite values as raw tags. The later security_master_rows projection copies snapshot values directly. The digest helper permits NaN while final `_canonical_capture_bytes` rejects NaN with allow_nan=False. A repair must use a coherent versioned business representation and hash the exact serialized representation. Do not turn missing values into zero or eligibility PASS.

Existing master reader: stock_owner is required; None is rejected, and numeric NaN bypassing the missing test is a defect. Making it optional requires an explicit producer/reader contract change. stock_child_type is nullable. outstanding_shares and circular_market_val allow None/numeric NaN, but reject infinity, dictionary tags, malformed numbers and negative values. Raw tags must not flow unchanged into numeric/text business fields.

The original builder writes FRESH_FUTU_CAPTURED_INPUT and SAME_JOB_CAPTURE_AND_PUBLICATION. An offline recovery must preserve truthful capture/recovery provenance and must not blindly inherit fresh/same-job/natural/preopen claims. Keep original acquired_at and use actual publication available_at. Membership and quote/panel quality are separate. Do not call the separate v1 live helper, which requires a historical fixed universe count.
