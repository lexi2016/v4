"""stage_center.selection: store_publication (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _SelectionStore_publish_body(_v4_scope, /, self, envelope, *, market, replace_failed_run_id=None):
    data = _v4_global(_v4_scope, 'dict')(envelope)
    required = {"trade_date", "stage_id", "raw_artifact_sha256", "algorithm_sha256", "rows", "selection_status"}
    if not required.issubset(data):
        raise _v4_global(_v4_scope, 'SelectionError')("selection envelope fields missing")
    trade_date = _v4_global(_v4_scope, '_validate_date')(_v4_global(_v4_scope, 'str')(data["trade_date"]))
    stage_id = _v4_global(_v4_scope, 'str')(data["stage_id"])
    _v4_global(_v4_scope, '_validate_market')(stage_id, market)
    if data.get("market") != market:
        raise _v4_global(_v4_scope, 'SelectionError')("selection envelope market mismatch")
    _v4_global(_v4_scope, '_validate_sha')(_v4_global(_v4_scope, 'str')(data["raw_artifact_sha256"]), "raw_artifact_sha256")
    if data.get("algorithm_id") != _v4_global(_v4_scope, 'SELECTION_ALGORITHM_ID'):
        raise _v4_global(_v4_scope, 'SelectionError')("selection algorithm binding mismatch")
    if _v4_global(_v4_scope, 'any')(data.get(flag) is not False for flag in _v4_global(_v4_scope, 'SAFETY_FLAGS')):
        raise _v4_global(_v4_scope, 'SelectionError')("selection safety flag must be false")
    rows = _v4_global(_v4_scope, 'list')(data.get("rows") or [])
    envelope_schema = _v4_global(_v4_scope, 'str')(data.get("schema_version") or _v4_global(_v4_scope, 'SELECTION_SCHEMA_VERSION'))
    if envelope_schema not in _v4_global(_v4_scope, 'SELECTION_SCHEMA_VERSIONS'):
        raise _v4_global(_v4_scope, 'SelectionError')("selection envelope schema mismatch")
    # New envelopes are explicitly v2, but ``artifact.csv`` stays a
    # fixed v1 projection for the old V3 verifier.  Full card evidence is
    # bound into the manifest/receipt envelope and selection identity.
    artifact_fields = _v4_global(_v4_scope, 'SELECTION_ARTIFACT_FIELDS_V1')
    artifact_rows = _v4_global(_v4_scope, '_artifact_rows')(rows, fields=artifact_fields)
    algorithm_sha = _v4_global(_v4_scope, 'str')(data["algorithm_sha256"])
    if algorithm_sha not in _v4_global(_v4_scope, 'ALGORITHM_SHA_ALLOWLIST'):
        raise _v4_global(_v4_scope, 'SelectionError')("selection algorithm binding mismatch")
    if algorithm_sha in {_v4_global(_v4_scope, 'A_SHARE_LIVE_ALGORITHM_SHA256'), _v4_global(_v4_scope, 'LEGACY_A_SHARE_LIVE_ALGORITHM_SHA256')} and market != "A_SHARE":
        raise _v4_global(_v4_scope, 'SelectionError')("live algorithm is restricted to A_SHARE")
    if algorithm_sha in {_v4_global(_v4_scope, 'A_SHARE_LIVE_ALGORITHM_SHA256'), _v4_global(_v4_scope, 'LEGACY_A_SHARE_LIVE_ALGORITHM_SHA256')} and not _v4_global(_v4_scope, 'any')(
        "formula=windows_v3_live_stage_quality_score" in _v4_global(_v4_scope, 'str')(item)
        for item in data.get("source_evidence") or ()
    ):
        raise _v4_global(_v4_scope, 'SelectionError')("live algorithm evidence missing")
    identity_payload = {
        "identity": self._key(trade_date, stage_id, market),
        "raw_artifact_sha256": data["raw_artifact_sha256"],
        "algorithm_sha256": algorithm_sha,
        "rows": rows,
    }
    authority_hashes = _v4_global(_v4_scope, 'tuple')(
        _v4_global(_v4_scope, 'str')(item)
        for item in data.get("source_evidence") or ()
        if _v4_global(_v4_scope, 'any')(
            _v4_global(_v4_scope, 'str')(item).startswith(prefix)
            for prefix in (
                "a_d1_premarket_pool_sha256=",
                "a_research_panel_receipt_sha256=",
                "a_research_panel_selector_sha256=",
            )
        )
    )
    if authority_hashes:
        identity_payload["authority_source_hashes"] = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys(authority_hashes))
    input_sha = _v4_global(_v4_scope, '_canonical_sha')(identity_payload)
    role = self._role(stage_id, market)
    expected_artifact_id, expected_run_id = _v4_global(_v4_scope, '_selection_identity_ids')(
        trade_date,
        stage_id,
        market,
        _v4_global(_v4_scope, 'str')(data["raw_artifact_sha256"]),
        algorithm_sha,
        rows,
    )
    if data.get("run_id") not in (None, expected_run_id) or data.get("artifact_id") not in (None, expected_artifact_id):
        raise _v4_global(_v4_scope, 'SelectionError')("selection identity mismatch")
    run_id = expected_run_id
    artifact_id = expected_artifact_id
    data["run_id"] = run_id
    data["artifact_id"] = artifact_id
    idem_key = _v4_global(_v4_scope, '_canonical_sha')({"identity": self._key(trade_date, stage_id, market), "raw_artifact_sha256": data["raw_artifact_sha256"], "algorithm_sha256": algorithm_sha, "input_sha256": input_sha})
    data["source_evidence"] = _v4_global(_v4_scope, 'list')(data.get("source_evidence") or [])
    data["cannot_confirm"] = _v4_global(_v4_scope, 'list')(data.get("cannot_confirm") or [])
    prefix = f"selection_runs/{trade_date}/{role}/{run_id}"
    artifact_relative = f"{prefix}/artifact.csv"
    manifest_relative = f"{prefix}/manifest.json"
    receipt_relative = f"{prefix}/receipt.json"
    with self._lock():
        latest = self._latest()
        key = self._key(trade_date, stage_id, market)
        existing = latest["entries"].get(key)
        if _v4_global(_v4_scope, 'isinstance')(existing, _v4_global(_v4_scope, 'Mapping')):
            if existing.get("idempotency_key") != idem_key:
                if not replace_failed_run_id or existing.get("run_id") != replace_failed_run_id:
                    raise _v4_global(_v4_scope, 'SelectionError')(f"selection slot conflict: {key}")
                if stage_id != "STAGE_0925" or market != "HK_CONNECT":
                    raise _v4_global(_v4_scope, 'SelectionError')(f"failed-slot replacement is restricted to 09:25 HK Connect: {key}")
                previous = self._verify_run(trade_date, stage_id, market, _v4_global(_v4_scope, 'str')(existing.get("run_id")))["envelope"]
                if (previous.get("trade_date") != trade_date
                        or previous.get("stage_id") != stage_id
                        or previous.get("market") != market
                        or previous.get("selection_status") != "CANNOT_CONFIRM"
                        or previous.get("source_status") not in {"CANNOT_CONFIRM", "PARTIAL_WITH_ROWS"}
                        or previous.get("rows") != []
                        or previous.get("selected_rows") != 0):
                    raise _v4_global(_v4_scope, 'SelectionError')(f"only a verified zero-row CANNOT_CONFIRM 09:25 slot can be replaced: {key}")
                # The verified failed run remains immutable under its original
                # run path; the latest pointer is atomically advanced below.
            else:
                verified = self._verify_run(trade_date, stage_id, market, _v4_global(_v4_scope, 'str')(existing.get("run_id")))
                if verified["envelope"] != data:
                    raise _v4_global(_v4_scope, 'SelectionError')("selection idempotency payload mismatch")
                return _v4_global(_v4_scope, 'dict')(data)
        run_dir = _v4_global(_v4_scope, '_safe_relative')(self.root, prefix)
        if run_dir.exists():
            raise _v4_global(_v4_scope, 'SelectionError')("immutable selection run path already exists without latest pointer")
        run_dir.mkdir(parents=True, exist_ok=False)
        artifact_path = _v4_global(_v4_scope, '_safe_relative')(self.root, artifact_relative)
        _v4_global(_v4_scope, '_atomic_write_csv')(artifact_path, artifact_rows, fields=artifact_fields)
        artifact_sha = _v4_global(_v4_scope, '_sha_file')(artifact_path)
        manifest = {
            "schema_version": _v4_global(_v4_scope, 'SELECTION_MANIFEST_SCHEMA_VERSION'),
            "owner": "stage_center",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "market": market,
            "role": role,
            "run_id": run_id,
            "artifact_relative": artifact_relative,
            "artifact_sha256": artifact_sha,
            "row_count": _v4_global(_v4_scope, 'len')(rows),
            "selection_status": data["selection_status"],
            "raw_artifact_sha256": data["raw_artifact_sha256"],
            "algorithm_id": _v4_global(_v4_scope, 'SELECTION_ALGORITHM_ID'),
            "algorithm_sha256": algorithm_sha,
            "selection_envelope": data,
            "calendar": _v4_global(_v4_scope, 'calendar_provenance')(),
            **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        }
        receipt = {
            "schema_version": _v4_global(_v4_scope, 'SELECTION_RECEIPT_SCHEMA_VERSION'),
            "owner": "stage_center",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "market": market,
            "role": role,
            "run_id": run_id,
            "artifact_relative": artifact_relative,
            "artifact_sha256": artifact_sha,
            "manifest_sha256": _v4_global(_v4_scope, '_canonical_sha')(manifest),
            "row_count": _v4_global(_v4_scope, 'len')(rows),
            "selection_status": data["selection_status"],
            "raw_artifact_sha256": data["raw_artifact_sha256"],
            "algorithm_id": _v4_global(_v4_scope, 'SELECTION_ALGORITHM_ID'),
            "algorithm_sha256": algorithm_sha,
            "idempotency_key": idem_key,
            "calendar": _v4_global(_v4_scope, 'calendar_provenance')(),
            **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        }
        _v4_global(_v4_scope, '_atomic_write_json')(_v4_global(_v4_scope, '_safe_relative')(self.root, manifest_relative), manifest)
        _v4_global(_v4_scope, '_atomic_write_json')(_v4_global(_v4_scope, '_safe_relative')(self.root, receipt_relative), receipt)
        verified = self._verify_run(trade_date, stage_id, market, run_id)
        entries = _v4_global(_v4_scope, 'dict')(latest.get("entries", {}))
        entries[key] = {
            "owner": "stage_center",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "market": market,
            "role": role,
            "run_id": run_id,
            "artifact_relative": artifact_relative,
            "artifact_sha256": artifact_sha,
            "manifest_sha256": verified["manifest_sha256"],
            "receipt_sha256": verified["receipt_sha256"],
            "idempotency_key": idem_key,
            **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        }
        latest["entries"] = entries
        _v4_global(_v4_scope, '_atomic_write_json')(self.latest_path, latest)
        return _v4_global(_v4_scope, 'dict')(data)

_HK_KLINE_R5_DATE = "20261012"
_HK_KLINE_R5_STAGES = ("STAGE_1300_1315", "STAGE_1445_1500")
_HK_KLINE_R5_MUTABLE_ROW_FIELDS = frozenset(
    {
        "current_change_pct",
        "open_price",
        "last_price",
        "high_price",
        "low_price",
        "support",
        "pressure",
        "invalidation",
        "source_last_bar_time",
        "support_primary_price",
        "pressure_price",
        "invalidation_price",
    }
)
_HK_KLINE_R5_ORIGINAL_FIELDS = frozenset(
    {
        "run_id",
        "artifact_id",
        "artifact_sha256",
        "manifest_sha256",
        "receipt_sha256",
        "manifest_file_sha256",
        "receipt_file_sha256",
        "raw_artifact_sha256",
        "algorithm_sha256",
    }
)


def _SelectionStore_publish_hk_futu_kline_enrichment_pair_body(
    _v4_scope,
    /,
    self,
    candidate_document_bytes,
    *,
    expected_candidate_sha256,
    expected_input_baseline_sha256,
    expected_originals_by_stage,
):
    """Publish only the reviewed 2026-10-12 HK R5 pair using exact CAS inputs.

    The ordinary ``publish`` method deliberately remains immutable per slot.
    This narrow path validates the R5 candidate and both prior run trios, writes
    two new immutable runs, then advances exactly the two latest entries with
    one atomic latest-pointer replacement.
    """
    import hashlib
    import json
    import math
    from collections.abc import Mapping

    def fail(message):
        raise _v4_global(_v4_scope, 'SelectionError')(message)

    def evidence_value(items, key, *, label):
        prefix = f"{key}="
        values = list(
            dict.fromkeys(
                str(item)[len(prefix):]
                for item in items
                if str(item).startswith(prefix)
            )
        )
        if len(values) != 1 or not values[0]:
            fail(f"{label} must contain exactly one {key} value")
        return values[0]

    def finite_number(row, field, *, code, stage_id):
        value = row.get(field)
        if isinstance(value, bool):
            fail(f"{stage_id}/{code} {field} must be a finite number")
        try:
            number = float(value)
        except (TypeError, ValueError):
            fail(f"{stage_id}/{code} {field} must be a finite number")
        if not math.isfinite(number):
            fail(f"{stage_id}/{code} {field} must be a finite number")
        return number

    def validate_sha(value, label):
        try:
            return _v4_global(_v4_scope, '_validate_sha')(str(value), label)
        except _v4_global(_v4_scope, 'SelectionError'):
            raise
        except Exception as error:
            raise _v4_global(_v4_scope, 'SelectionError')(f"{label} is invalid") from error

    if not isinstance(candidate_document_bytes, bytes):
        fail("R5 candidate document must be supplied as exact bytes")
    expected_candidate_sha256 = validate_sha(expected_candidate_sha256, "expected candidate SHA")
    candidate_sha256 = hashlib.sha256(candidate_document_bytes).hexdigest()
    if candidate_sha256 != expected_candidate_sha256:
        fail("R5 candidate SHA does not match the explicit expected SHA")
    expected_input_baseline_sha256 = validate_sha(
        expected_input_baseline_sha256, "expected input baseline SHA"
    )
    if not isinstance(expected_originals_by_stage, Mapping) or set(expected_originals_by_stage) != set(_HK_KLINE_R5_STAGES):
        fail("R5 publication requires exact original identities for both fixed stages")
    originals = {}
    for stage_id in _HK_KLINE_R5_STAGES:
        item = expected_originals_by_stage.get(stage_id)
        if not isinstance(item, Mapping) or set(item) != _HK_KLINE_R5_ORIGINAL_FIELDS:
            fail(f"{stage_id} expected original identity fields are incomplete")
        normalized = {str(key): str(value) for key, value in item.items()}
        for field in ("artifact_sha256", "manifest_sha256", "receipt_sha256", "manifest_file_sha256", "receipt_file_sha256", "raw_artifact_sha256", "algorithm_sha256"):
            normalized[field] = validate_sha(normalized[field], f"{stage_id} expected {field}")
        for field in ("run_id", "artifact_id"):
            if not normalized[field]:
                fail(f"{stage_id} expected {field} is missing")
        originals[stage_id] = normalized

    try:
        candidate = json.loads(candidate_document_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _v4_global(_v4_scope, 'SelectionError')("R5 candidate document is not valid UTF-8 JSON") from error
    if not isinstance(candidate, Mapping):
        fail("R5 candidate document must be a JSON object")
    if (
        candidate.get("schema") != "v4_hk_stage_futu_kline_enrichment_overlay_r5_v1"
        or candidate.get("candidate_status") != "REVIEW_REQUIRED_NOT_FORMALLY_PUBLISHED"
        or candidate.get("candidate_kind") != "DISPLAY_EVIDENCE_OVERLAY_ONLY"
        or candidate.get("trade_date") != _HK_KLINE_R5_DATE
        or candidate.get("market") != "HK_CONNECT"
    ):
        fail("candidate does not match the frozen R5 date, market, or schema")
    source = candidate.get("source")
    provenance = candidate.get("provenance")
    safety = candidate.get("safety")
    stages = candidate.get("stages")
    if not all(isinstance(item, Mapping) for item in (source, provenance, safety, stages)):
        fail("R5 candidate source, provenance, safety, or stages are missing")
    if source.get("input_baseline_sha256") != expected_input_baseline_sha256:
        fail("R5 candidate is not bound to the expected frozen input baseline")
    if source.get("fixed_d1_pool_row_count") != 100:
        fail("R5 candidate does not preserve the fixed 100-row D-1 pool")
    if set(stages) != set(_HK_KLINE_R5_STAGES):
        fail("R5 candidate must contain exactly the two frozen HK stages")
    for field in ("selection_run_ids", "selection_artifact_sha256_by_stage", "fixed_d1_pool_source_sha256_by_stage", "fixed_d1_pool_artifact_sha256_by_stage", "fixed_d1_pool_version_by_stage", "stage_raw_artifact_sha256_by_stage"):
        if not isinstance(source.get(field), Mapping) or set(source[field]) != set(_HK_KLINE_R5_STAGES):
            fail(f"R5 candidate source lineage {field} is incomplete")
    if (
        provenance.get("source_id") != "futu_openapi_get_cur_kline"
        or provenance.get("method") != "get_cur_kline(code,1000,SubType.K_1M,AuType.NONE)"
        or provenance.get("historical_orderbook_status") != "CANNOT_CONFIRM_NO_CUTOFF_BOUND_SNAPSHOT"
        or provenance.get("current_orderbook_queried") is not False
        or provenance.get("provider_subscription_release_receipt_status") != "CANNOT_CONFIRM"
    ):
        fail("R5 candidate provider provenance or unresolved operational receipt is invalid")
    if (
        safety.get("research_only") is not True
        or safety.get("production_allowed") is not False
        or safety.get("buy_gate_updated") is not False
        or safety.get("orders_sent") is not False
        or safety.get("selection_action_boundary") != "NO_BUY"
        or safety.get("pit_safe") is not False
        or safety.get("temporal_cutoff_safe") is not False
        or safety.get("formal_stage_eligibility") != "CANNOT_CONFIRM"
    ):
        fail("R5 candidate safety boundary changed")

    target_code_union = source.get("target_code_union")
    if not isinstance(target_code_union, list) or len(target_code_union) != 11 or len(set(target_code_union)) != 11:
        fail("R5 candidate target code union must contain 11 unique codes")
    if source.get("target_code_count") != 11:
        fail("R5 candidate target code count mismatch")

    row_evidence_by_stage = {}
    new_envelopes = {}
    validated_old_runs = {}
    for stage_id in _HK_KLINE_R5_STAGES:
        old = originals[stage_id]
        stage = stages[stage_id]
        if not isinstance(stage, Mapping):
            fail(f"{stage_id} candidate stage is malformed")
        if (
            stage.get("trade_date") != _HK_KLINE_R5_DATE
            or stage.get("stage_id") != stage_id
            or stage.get("market") != "HK_CONNECT"
            or stage.get("source_selection_run_id") != old["run_id"]
            or stage.get("source_selection_artifact_id") != old["artifact_id"]
            or stage.get("source_selection_artifact_sha256") != old["artifact_sha256"]
            or stage.get("source_selection_manifest_sha256") != old["manifest_file_sha256"]
            or stage.get("source_selection_receipt_sha256") != old["receipt_file_sha256"]
            or stage.get("raw_artifact_sha256") != old["raw_artifact_sha256"]
            or stage.get("algorithm_sha256") != old["algorithm_sha256"]
            or source["selection_run_ids"][stage_id] != old["run_id"]
            or source["selection_artifact_sha256_by_stage"][stage_id] != old["artifact_sha256"]
            or source["stage_raw_artifact_sha256_by_stage"][stage_id] != old["raw_artifact_sha256"]
        ):
            fail(f"{stage_id} candidate source identity differs from the frozen original")
        if (
            stage.get("requested_rows") != 100
            or stage.get("source_rows") != 100
            or stage.get("selected_rows") != 10
            or len(stage.get("rows") or []) != 10
            or stage.get("selection_action_boundary") != "NO_BUY"
            or stage.get("formal_stage_eligibility") != "CANNOT_CONFIRM"
            or stage.get("pit_safe") is not False
            or stage.get("temporal_cutoff_safe") is not False
            or stage.get("historical_orderbook_status") != "CANNOT_CONFIRM_NO_CUTOFF_BOUND_SNAPSHOT"
            or stage.get("current_orderbook_queried") is not False
        ):
            fail(f"{stage_id} candidate row counts or safety boundary changed")
        if stage.get("source_selection_status") not in _v4_global(_v4_scope, 'SELECTION_STATUSES'):
            fail(f"{stage_id} original selection status is invalid")
        if stage.get("algorithm_id") != _v4_global(_v4_scope, 'SELECTION_ALGORITHM_ID'):
            fail(f"{stage_id} algorithm identity changed")
        if stage.get("source_status") is None or not isinstance(stage.get("rows"), list):
            fail(f"{stage_id} candidate source status or rows are missing")

        source_hashes = {
            evidence_value(row.get("d1_source_evidence") or [], "hk_d1_source_sha256", label=f"{stage_id} D-1 row evidence")
            for row in stage["rows"]
        }
        pool_versions = {
            evidence_value(row.get("d1_source_evidence") or [], "hk_d1_pool_version", label=f"{stage_id} D-1 row evidence")
            for row in stage["rows"]
        }
        pool_artifact_sha = evidence_value(stage.get("source_evidence") or [], "hk_d1_json_sha256", label=f"{stage_id} selection source evidence")
        if (
            len(source_hashes) != 1
            or len(pool_versions) != 1
            or source["fixed_d1_pool_source_sha256_by_stage"][stage_id] != next(iter(source_hashes))
            or source["fixed_d1_pool_artifact_sha256_by_stage"][stage_id] != pool_artifact_sha
            or source["fixed_d1_pool_version_by_stage"][stage_id] != next(iter(pool_versions))
        ):
            fail(f"{stage_id} fixed D-1 pool lineage changed")
        if stage_id == "STAGE_1300_1315":
            expected_last_bar = "2026-10-12 13:14:00"
        else:
            expected_last_bar = "2026-10-12 14:59:00"

        # Validate the candidate rows against the immutable original and the
        # narrow set of card fields written by the R5 K_1M enrichment.
        code_order = []
        old_run = None
        for candidate_row in stage["rows"]:
            if not isinstance(candidate_row, Mapping):
                fail(f"{stage_id} candidate row is malformed")
            code = str(candidate_row.get("code") or "").upper()
            code_order.append(code)
        # Current latest/trio validation happens under the store lock below;
        # row checks are completed there against the verified original rows.
        row_evidence_by_stage[stage_id] = (stage, code_order, expected_last_bar)

    candidate_union = sorted({code for _stage, codes, _last in row_evidence_by_stage.values() for code in codes})
    if candidate_union != sorted(str(code).upper() for code in target_code_union):
        fail("R5 candidate target code union differs from the two stage rows")

    with self._lock():
        latest = self._latest()
        latest_entries = latest.get("entries")
        if not isinstance(latest_entries, Mapping):
            fail("selection latest entries missing")
        prepared = {}
        for stage_id in _HK_KLINE_R5_STAGES:
            expected = originals[stage_id]
            key = self._key(_HK_KLINE_R5_DATE, stage_id, "HK_CONNECT")
            entry = latest_entries.get(key)
            if not isinstance(entry, Mapping):
                fail(f"latest original selection entry missing for {stage_id}")
            for field in ("run_id", "artifact_sha256", "manifest_sha256", "receipt_sha256"):
                if field == "run_id" and entry.get(field) != expected["run_id"]:
                    fail(f"latest original run changed for {stage_id}")
                if field != "run_id" and entry.get(field) != expected[field]:
                    fail(f"latest original {field} changed for {stage_id}")
            verified = self._verify_run(_HK_KLINE_R5_DATE, stage_id, "HK_CONNECT", expected["run_id"])
            run_prefix = (
                f"selection_runs/{_HK_KLINE_R5_DATE}/"
                f"{self._role(stage_id, 'HK_CONNECT')}/{expected['run_id']}"
            )
            source_file_shas = {
                "artifact_sha256": _v4_global(_v4_scope, '_sha_file')(
                    _v4_global(_v4_scope, '_safe_relative')(self.root, f"{run_prefix}/artifact.csv")
                ),
                "manifest_file_sha256": _v4_global(_v4_scope, '_sha_file')(
                    _v4_global(_v4_scope, '_safe_relative')(self.root, f"{run_prefix}/manifest.json")
                ),
                "receipt_file_sha256": _v4_global(_v4_scope, '_sha_file')(
                    _v4_global(_v4_scope, '_safe_relative')(self.root, f"{run_prefix}/receipt.json")
                ),
            }
            if (
                verified.get("run_id") != expected["run_id"]
                or verified["envelope"].get("artifact_id") != expected["artifact_id"]
                or verified.get("artifact_sha256") != expected["artifact_sha256"]
                or verified.get("manifest_sha256") != expected["manifest_sha256"]
                or verified.get("receipt_sha256") != expected["receipt_sha256"]
                or source_file_shas["artifact_sha256"] != expected["artifact_sha256"]
                or source_file_shas["manifest_file_sha256"] != expected["manifest_file_sha256"]
                or source_file_shas["receipt_file_sha256"] != expected["receipt_file_sha256"]
                or verified["envelope"].get("raw_artifact_sha256") != expected["raw_artifact_sha256"]
                or verified["envelope"].get("algorithm_sha256") != expected["algorithm_sha256"]
            ):
                fail(f"frozen original selection trio changed for {stage_id}")
            original_envelope = verified["envelope"]
            stage, code_order, expected_last_bar = row_evidence_by_stage[stage_id]
            original_rows = original_envelope.get("rows") or []
            candidate_rows = stage["rows"]
            if (
                original_envelope.get("requested_rows") != 100
                or original_envelope.get("source_rows") != 100
                or original_envelope.get("selected_rows") != 10
                or len(original_rows) != 10
                or stage.get("selection_status", stage.get("source_selection_status")) != original_envelope.get("selection_status")
                or stage.get("source_status") != original_envelope.get("source_status")
                or stage.get("coverage_ratio") != original_envelope.get("coverage_ratio")
                or list(stage.get("missing_symbols") or []) != list(original_envelope.get("missing_symbols") or [])
            ):
                fail(f"{stage_id} source pool or selection envelope metadata changed")
            if [str(row.get("code") or "").upper() for row in original_rows] != code_order:
                fail(f"{stage_id} source row order or membership changed")
            for original_row, candidate_row in zip(original_rows, candidate_rows):
                if set(original_row) != set(candidate_row):
                    fail(f"{stage_id}/{candidate_row.get('code')} candidate row fields changed")
                changed = {
                    field
                    for field in original_row
                    if original_row.get(field) != candidate_row.get(field)
                }
                if not changed.issubset(_HK_KLINE_R5_MUTABLE_ROW_FIELDS):
                    fail(f"{stage_id}/{candidate_row.get('code')} changed a frozen row field")
                code = str(candidate_row.get("code") or "").upper()
                if candidate_row.get("action_level") != "NO_BUY" or original_row.get("action_level") != "NO_BUY":
                    fail(f"{stage_id}/{code} BUY safety boundary changed")
                if candidate_row.get("source_last_bar_time") != expected_last_bar:
                    fail(f"{stage_id}/{code} source last-bar time is outside the frozen K_1M window")
                values = {
                    field: finite_number(candidate_row, field, code=code, stage_id=stage_id)
                    for field in ("open_price", "last_price", "high_price", "low_price", "current_change_pct", "support", "pressure", "invalidation")
                }
                for price_field in ("open_price", "last_price", "high_price", "low_price"):
                    if values[price_field] <= 0:
                        fail(f"{stage_id}/{code} {price_field} must be positive")
                if not (values["low_price"] <= values["open_price"] <= values["high_price"] and values["low_price"] <= values["last_price"] <= values["high_price"]):
                    fail(f"{stage_id}/{code} OHLC relationship is invalid")
                expected_change = round((values["last_price"] / values["open_price"] - 1) * 100, 4)
                if abs(values["current_change_pct"] - expected_change) > 1e-8:
                    fail(f"{stage_id}/{code} stage return formula changed")
                if (
                    values["support"] != values["low_price"]
                    or values["invalidation"] != values["low_price"]
                    or values["pressure"] != values["high_price"]
                    or finite_number(candidate_row, "support_primary_price", code=code, stage_id=stage_id) != values["support"]
                    or finite_number(candidate_row, "pressure_price", code=code, stage_id=stage_id) != values["pressure"]
                    or finite_number(candidate_row, "invalidation_price", code=code, stage_id=stage_id) != values["invalidation"]
                ):
                    fail(f"{stage_id}/{code} stage-card price-level formula changed")

            data = dict(stage)
            data["schema_version"] = _v4_global(_v4_scope, 'SELECTION_SCHEMA_VERSION')
            data["selection_status"] = original_envelope["selection_status"]
            evidence = list(data.get("source_evidence") or [])
            evidence.extend(
                [
                    f"futu_kline_r5_candidate_sha256={candidate_sha256}",
                    f"futu_kline_r5_input_baseline_sha256={expected_input_baseline_sha256}",
                    f"futu_kline_r5_previous_run_id={expected['run_id']}",
                    f"futu_kline_r5_previous_artifact_id={expected['artifact_id']}",
                    f"futu_kline_r5_previous_manifest_sha256={expected['manifest_sha256']}",
                    f"futu_kline_r5_previous_receipt_sha256={expected['receipt_sha256']}",
                    f"futu_kline_r5_previous_manifest_file_sha256={expected['manifest_file_sha256']}",
                    f"futu_kline_r5_previous_receipt_file_sha256={expected['receipt_file_sha256']}",
                    "futu_provider_subscription_release_receipt_status=CANNOT_CONFIRM",
                ]
            )
            data["source_evidence"] = list(dict.fromkeys(str(item) for item in evidence))
            cannot_confirm = list(data.get("cannot_confirm") or [])
            cannot_confirm.append("FUTU_PROVIDER_SUBSCRIPTION_RELEASE_RECEIPT_CANNOT_CONFIRM")
            data["cannot_confirm"] = list(dict.fromkeys(str(item) for item in cannot_confirm))
            rows = list(data.get("rows") or [])
            if any(data.get(flag) is not False for flag in _v4_global(_v4_scope, 'SAFETY_FLAGS')):
                fail(f"{stage_id} selection safety flag must be false")
            if data.get("algorithm_id") != _v4_global(_v4_scope, 'SELECTION_ALGORITHM_ID'):
                fail(f"{stage_id} selection algorithm binding mismatch")
            algorithm_sha = str(data.get("algorithm_sha256") or "")
            if algorithm_sha not in _v4_global(_v4_scope, 'ALGORITHM_SHA_ALLOWLIST'):
                fail(f"{stage_id} selection algorithm SHA is not allowlisted")
            trade_date = _v4_global(_v4_scope, '_validate_date')(str(data["trade_date"]))
            _v4_global(_v4_scope, '_validate_market')(stage_id, "HK_CONNECT")
            artifact_fields = _v4_global(_v4_scope, 'SELECTION_ARTIFACT_FIELDS_V1')
            artifact_rows = _v4_global(_v4_scope, '_artifact_rows')(rows, fields=artifact_fields)
            expected_artifact_id, expected_run_id = _v4_global(_v4_scope, '_selection_identity_ids')(
                trade_date,
                stage_id,
                "HK_CONNECT",
                str(data["raw_artifact_sha256"]),
                algorithm_sha,
                rows,
            )
            data["run_id"] = expected_run_id
            data["artifact_id"] = expected_artifact_id
            identity_payload = {
                "identity": self._key(trade_date, stage_id, "HK_CONNECT"),
                "raw_artifact_sha256": data["raw_artifact_sha256"],
                "algorithm_sha256": algorithm_sha,
                "rows": rows,
            }
            input_sha = _v4_global(_v4_scope, '_canonical_sha')(identity_payload)
            idempotency_key = _v4_global(_v4_scope, '_canonical_sha')(
                {
                    "identity": self._key(trade_date, stage_id, "HK_CONNECT"),
                    "raw_artifact_sha256": data["raw_artifact_sha256"],
                    "algorithm_sha256": algorithm_sha,
                    "input_sha256": input_sha,
                }
            )
            role = self._role(stage_id, "HK_CONNECT")
            run_prefix = f"selection_runs/{trade_date}/{role}/{expected_run_id}"
            artifact_relative = f"{run_prefix}/artifact.csv"
            manifest_relative = f"{run_prefix}/manifest.json"
            receipt_relative = f"{run_prefix}/receipt.json"
            run_dir = _v4_global(_v4_scope, '_safe_relative')(self.root, run_prefix)
            if run_dir.exists():
                fail(f"immutable R5 selection run already exists without a latest pointer for {stage_id}")
            prepared[stage_id] = {
                "data": data,
                "rows": rows,
                "artifact_rows": artifact_rows,
                "artifact_fields": artifact_fields,
                "run_id": expected_run_id,
                "artifact_id": expected_artifact_id,
                "idempotency_key": idempotency_key,
                "role": role,
                "run_prefix": run_prefix,
                "artifact_relative": artifact_relative,
                "manifest_relative": manifest_relative,
                "receipt_relative": receipt_relative,
                "run_dir": run_dir,
                "expected_original": expected,
            }
            validated_old_runs[stage_id] = verified

        entries = dict(latest_entries)
        published = {}
        for stage_id in _HK_KLINE_R5_STAGES:
            item = prepared[stage_id]
            item["run_dir"].mkdir(parents=True, exist_ok=False)
            artifact_path = _v4_global(_v4_scope, '_safe_relative')(self.root, item["artifact_relative"])
            _v4_global(_v4_scope, '_atomic_write_csv')(
                artifact_path,
                item["artifact_rows"],
                fields=item["artifact_fields"],
            )
            artifact_sha = _v4_global(_v4_scope, '_sha_file')(artifact_path)
            manifest = {
                "schema_version": _v4_global(_v4_scope, 'SELECTION_MANIFEST_SCHEMA_VERSION'),
                "owner": "stage_center",
                "trade_date": _HK_KLINE_R5_DATE,
                "stage_id": stage_id,
                "market": "HK_CONNECT",
                "role": item["role"],
                "run_id": item["run_id"],
                "artifact_relative": item["artifact_relative"],
                "artifact_sha256": artifact_sha,
                "row_count": len(item["rows"]),
                "selection_status": item["data"]["selection_status"],
                "raw_artifact_sha256": item["data"]["raw_artifact_sha256"],
                "algorithm_id": _v4_global(_v4_scope, 'SELECTION_ALGORITHM_ID'),
                "algorithm_sha256": item["data"]["algorithm_sha256"],
                "selection_envelope": item["data"],
                "calendar": _v4_global(_v4_scope, 'calendar_provenance')(),
                **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
            }
            receipt = {
                "schema_version": _v4_global(_v4_scope, 'SELECTION_RECEIPT_SCHEMA_VERSION'),
                "owner": "stage_center",
                "trade_date": _HK_KLINE_R5_DATE,
                "stage_id": stage_id,
                "market": "HK_CONNECT",
                "role": item["role"],
                "run_id": item["run_id"],
                "artifact_relative": item["artifact_relative"],
                "artifact_sha256": artifact_sha,
                "manifest_sha256": _v4_global(_v4_scope, '_canonical_sha')(manifest),
                "row_count": len(item["rows"]),
                "selection_status": item["data"]["selection_status"],
                "raw_artifact_sha256": item["data"]["raw_artifact_sha256"],
                "algorithm_id": _v4_global(_v4_scope, 'SELECTION_ALGORITHM_ID'),
                "algorithm_sha256": item["data"]["algorithm_sha256"],
                "idempotency_key": item["idempotency_key"],
                "calendar": _v4_global(_v4_scope, 'calendar_provenance')(),
                **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
            }
            _v4_global(_v4_scope, '_atomic_write_json')(
                _v4_global(_v4_scope, '_safe_relative')(self.root, item["manifest_relative"]),
                manifest,
            )
            _v4_global(_v4_scope, '_atomic_write_json')(
                _v4_global(_v4_scope, '_safe_relative')(self.root, item["receipt_relative"]),
                receipt,
            )
            verified = self._verify_run(_HK_KLINE_R5_DATE, stage_id, "HK_CONNECT", item["run_id"])
            key = self._key(_HK_KLINE_R5_DATE, stage_id, "HK_CONNECT")
            entries[key] = {
                "owner": "stage_center",
                "trade_date": _HK_KLINE_R5_DATE,
                "stage_id": stage_id,
                "market": "HK_CONNECT",
                "role": item["role"],
                "run_id": item["run_id"],
                "artifact_relative": item["artifact_relative"],
                "artifact_sha256": verified["artifact_sha256"],
                "manifest_sha256": verified["manifest_sha256"],
                "receipt_sha256": verified["receipt_sha256"],
                "idempotency_key": item["idempotency_key"],
                **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
            }
            published[stage_id] = {
                "previous_run_id": item["expected_original"]["run_id"],
                "previous_artifact_id": item["expected_original"]["artifact_id"],
                "run_id": verified["run_id"],
                "artifact_id": verified["envelope"]["artifact_id"],
                "artifact_sha256": verified["artifact_sha256"],
                "manifest_sha256": verified["manifest_sha256"],
                "receipt_sha256": verified["receipt_sha256"],
            }

        latest["entries"] = entries
        _v4_global(_v4_scope, '_atomic_write_json')(self.latest_path, latest)
        return {
            "candidate_sha256": candidate_sha256,
            "input_baseline_sha256": expected_input_baseline_sha256,
            "latest_updated_stages": list(_HK_KLINE_R5_STAGES),
            "stage_publications": published,
        }
