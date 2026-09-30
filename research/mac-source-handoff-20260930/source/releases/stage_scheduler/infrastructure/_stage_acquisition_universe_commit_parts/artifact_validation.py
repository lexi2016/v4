"""infrastructure.stage_acquisition_universe_commit: artifact_validation (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __reject_unsafe_strict_fields_body(_v4_scope, /, value, path):
    """Reject unsafe extension keys recursively before strict normalization.

    ``_validate_physical_input`` validates the six source pools, while this
    boundary validates the caller's aggregate proposal.  Both initial and
    successor publication call it before the proposal is normalized, so an
    unknown nested field cannot disappear silently and become an apparently
    authoritative artifact.
    """

    if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')):
        for key, nested in value.items():
            folded = _v4_global(_v4_scope, 'str')(key).casefold().replace("-", "_")
            if folded in _v4_global(_v4_scope, '_STRICT_SAFE_FLAG_KEYS'):
                # The strict artifact requires these flags and checks their
                # value separately.  They are not executable action fields.
                _v4_global(_v4_scope, '_reject_unsafe_strict_fields')(nested, f"{path}.{key}")
                continue
            if folded in _v4_global(_v4_scope, '_STRICT_ACTION_KEYS') or (
                folded != "trade_date"
                and (
                    folded.startswith(("buy_", "sell_", "order_", "trade_"))
                    or folded.endswith(("_buy", "_sell", "_order", "_trade"))
                )
            ):
                raise _v4_global(_v4_scope, 'StrictCommitError')(f"strict artifact unsafe action field: {path}.{key}")
            if (
                folded in _v4_global(_v4_scope, '_STRICT_OUTCOME_KEYS')
                or folded.startswith("future_")
                or folded.startswith("post_event_")
                or folded.startswith("label_")
                or folded.startswith("target_")
                or folded.endswith("_future")
                or folded.endswith("_outcome")
                or folded.endswith("_label")
                or "post_event" in folded
                or "postevent" in folded
                or "future" in folded
                or "label" in folded
                or "outcome" in folded
                or "prediction" in folded
            ):
                raise _v4_global(_v4_scope, 'StrictCommitError')(
                    f"strict artifact unsafe outcome field: {path}.{key}"
                )
            _v4_global(_v4_scope, '_reject_unsafe_strict_fields')(nested, f"{path}.{key}")
    elif _v4_global(_v4_scope, 'isinstance')(value, (_v4_global(_v4_scope, 'list'), _v4_global(_v4_scope, 'tuple'))):
        for index, nested in _v4_global(_v4_scope, 'enumerate')(value):
            _v4_global(_v4_scope, '_reject_unsafe_strict_fields')(nested, f"{path}[{index}]")


def __validate_physical_input_body(_v4_scope, /, payload, snapshot):
    """Bind the caller's V2/V3 projection to a fresh physical six-pool read.

    The Gate2 builder emits a V2-shaped object even when its source is a strict
    physical snapshot.  Validate that object before adding V3 identity fields;
    then validate every physical provenance field explicitly so optional V3
    extensions cannot be silently substituted while calling the shared pure
    contract validator.
    """

    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')("stage-acquisition artifact is not an object")
    expected = _v4_global(_v4_scope, '_physical_pool_provenance')(snapshot)
    actual = payload.get("source_pool_provenance")
    if not _v4_global(_v4_scope, 'isinstance')(actual, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'len')(actual) != _v4_global(_v4_scope, 'len')(expected):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')("stage-acquisition source pool provenance is incomplete")
    for index, (item, expected_item) in _v4_global(_v4_scope, 'enumerate')(_v4_global(_v4_scope, 'zip')(actual, expected)):
        if not _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')("stage-acquisition source pool provenance is invalid")
        for field in _v4_global(_v4_scope, '_POOL_BINDING_FIELDS'):
            if item.get(field) != expected_item[field]:
                raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                    f"stage-acquisition source pool {expected_item['pool_id']} {field} binding mismatch"
                )
        for field in ("producer_id", "source_role", "valid_empty"):
            if field in item and item.get(field) != expected_item[field]:
                raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                    f"stage-acquisition source pool {expected_item['pool_id']} {field} binding mismatch"
                )

    # The shared validator is the authority for the aggregate codes, source
    # order, exact-date and policy bindings.  Strip only optional provenance
    # extensions because Gate2's V2 physical artifact does not carry them.
    comparison = _v4_global(_v4_scope, 'dict')(payload)
    comparison["source_pool_provenance"] = [
        {field: item[field] for field in _v4_global(_v4_scope, '_POOL_BINDING_FIELDS')}
        for item in actual
    ]
    comparison["source_pool_provenance_sha256"] = _v4_global(_v4_scope, '_canonical_sha')(
        comparison["source_pool_provenance"]
    )
    _v4_global(_v4_scope, 'validate_artifact_against_snapshot')(comparison, snapshot)


def __normalize_strict_artifact_body(_v4_scope, /, payload, snapshot, identity):
    """Copy a verified Gate2 artifact into the strict V3 wire schema."""

    artifact = _v4_global(_v4_scope, 'dict')(payload)
    if artifact.get("trade_date") != snapshot.trade_date:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact trade_date mismatch")
    accepted = {
        "schema_version": {"A_SHARE_STAGE_ACQUISITION_UNIVERSE_V2", _v4_global(_v4_scope, 'STRICT_ARTIFACT_SCHEMA')},
        "artifact_role": {"A_SHARE_STAGE_ACQUISITION_UNIVERSE_V2", _v4_global(_v4_scope, 'STRICT_ROLE')},
        "artifact_version": {"V2", _v4_global(_v4_scope, 'STRICT_ARTIFACT_VERSION')},
        "source_merge_role": {"STAGE_ACQUISITION_INPUT"},
    }
    for field, values in accepted.items():
        if field in artifact and artifact[field] not in values:
            raise _v4_global(_v4_scope, 'StrictCommitError')(f"strict artifact {field} mismatch")
    if "stage_selection_eligible" in artifact and artifact["stage_selection_eligible"] is not True:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact stage role is invalid")
    expected_identity = _v4_global(_v4_scope, '_identity_fields')(identity)
    if _v4_global(_v4_scope, 'any')(
        field in artifact and artifact[field] != value
        for field, value in expected_identity.items()
    ):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact evidence identity mismatch")
    artifact.update(
        {
            "schema_version": _v4_global(_v4_scope, 'STRICT_ARTIFACT_SCHEMA'),
            "artifact_role": _v4_global(_v4_scope, 'STRICT_ROLE'),
            "artifact_version": _v4_global(_v4_scope, 'STRICT_ARTIFACT_VERSION'),
            "authority": "STRICT_PHYSICAL_POOL_SNAPSHOT",
            **expected_identity,
        }
    )
    artifact["source_pool_provenance"] = _v4_global(_v4_scope, '_physical_pool_provenance')(snapshot)
    artifact["source_pool_provenance_sha256"] = _v4_global(_v4_scope, '_canonical_sha')(
        artifact["source_pool_provenance"]
    )
    artifact["cannot_confirm"] = _v4_global(_v4_scope, 'list')(snapshot.diagnostic_reasons)
    artifact["blocking_reasons"] = []
    artifact["pool_diagnostics"] = {
        pool_id: _v4_global(_v4_scope, 'list')(reasons)
        for pool_id, reasons in snapshot.pool_diagnostics.items()
    }
    artifact["known_pool_ids"] = _v4_global(_v4_scope, 'list')(snapshot.known_pool_ids)
    artifact["available_pool_ids"] = _v4_global(_v4_scope, 'list')(snapshot.pool_ids)
    return artifact


def __validate_artifact_body(_v4_scope, /, payload, trade_date, identity):
    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact must be an object")
    if payload.get("schema_version") != _v4_global(_v4_scope, 'STRICT_ARTIFACT_SCHEMA') or payload.get("artifact_role") != _v4_global(_v4_scope, 'STRICT_ROLE'):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact schema or role mismatch")
    if payload.get("artifact_version") != _v4_global(_v4_scope, 'STRICT_ARTIFACT_VERSION'):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact version mismatch")
    if payload.get("authority") != "STRICT_PHYSICAL_POOL_SNAPSHOT":
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact authority mismatch")
    if payload.get("trade_date") != trade_date:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact trade_date mismatch")
    if payload.get("status") not in {"READY", "READY_EMPTY"}:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact status is not ready")
    _v4_global(_v4_scope, '_check_identity')(payload, identity, "strict artifact")
    _v4_global(_v4_scope, '_false_flags')(payload, "strict artifact")
    if payload.get("source_merge_role") != "STAGE_ACQUISITION_INPUT" or payload.get("stage_selection_eligible") is not True:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact stage role is invalid")
    cannot_confirm = payload.get("cannot_confirm", [])
    if not _v4_global(_v4_scope, 'isinstance')(cannot_confirm, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'any')(
        not _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'str')) for item in cannot_confirm
    ):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact cannot_confirm is invalid")
    blocking_reasons = payload.get("blocking_reasons", [])
    if not _v4_global(_v4_scope, 'isinstance')(blocking_reasons, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'any')(
        not _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'str')) for item in blocking_reasons
    ) or blocking_reasons:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact blocking_reasons must be empty")
    pool_diagnostics = payload.get("pool_diagnostics", {})
    if not _v4_global(_v4_scope, 'isinstance')(pool_diagnostics, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact pool_diagnostics is invalid")
    flattened_diagnostics: list[str] = []
    for pool_id in _v4_global(_v4_scope, 'REQUIRED_A_STAGE_POOL_IDS'):
        reasons = pool_diagnostics.get(pool_id, [])
        if not _v4_global(_v4_scope, 'isinstance')(reasons, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'any')(
            not _v4_global(_v4_scope, 'isinstance')(reason, _v4_global(_v4_scope, 'str')) for reason in reasons
        ):
            raise _v4_global(_v4_scope, 'StrictCommitError')(
                f"strict artifact pool {pool_id} diagnostics are invalid"
            )
        flattened_diagnostics.extend(f"{pool_id}:{reason}" for reason in reasons)
    if cannot_confirm != flattened_diagnostics:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact diagnostics are not bound")
    notes = payload.get("policy_notes")
    if not _v4_global(_v4_scope, 'isinstance')(notes, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'any')(not _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'str')) for item in notes):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact policy_notes are invalid")

    codes = payload.get("codes")
    if not _v4_global(_v4_scope, 'isinstance')(codes, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'any')(not _v4_global(_v4_scope, 'isinstance')(code, _v4_global(_v4_scope, 'str')) or _v4_global(_v4_scope, '_CODE').fullmatch(code) is None for code in codes):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact codes are invalid")
    if _v4_global(_v4_scope, 'len')(codes) != _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'set')(codes)):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact codes contain duplicates")
    if payload["status"] == "READY" and not codes:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict READY artifact has no codes")
    if payload["status"] == "READY_EMPTY" and codes:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict READY_EMPTY artifact has codes")
    if payload.get("row_count") != _v4_global(_v4_scope, 'len')(codes) or _v4_global(_v4_scope, 'isinstance')(payload.get("row_count"), _v4_global(_v4_scope, 'bool')):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact row_count mismatch")
    if payload.get("codes_sha256") != _v4_global(_v4_scope, '_canonical_sha')(codes):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact codes SHA mismatch")
    _v4_global(_v4_scope, '_require_sha')(payload.get("source_projection_sha256"), "strict artifact source_projection_sha256")
    if payload.get("source_projection_row_count") != _v4_global(_v4_scope, 'len')(codes):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact source row_count mismatch")
    if payload.get("source_projection_status") not in {"READY_WITH_ROWS", "READY_EMPTY"}:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact source status mismatch")

    provenance = payload.get("source_pool_provenance")
    if not _v4_global(_v4_scope, 'isinstance')(provenance, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'tuple')(item.get("pool_id") if _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'Mapping')) else None for item in provenance) != _v4_global(_v4_scope, 'REQUIRED_A_STAGE_POOL_IDS'):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact source-pool set mismatch")
    for item in provenance:
        if not _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact source-pool provenance is invalid")
        pool_id = item["pool_id"]
        available = item.get("available", True)
        if not _v4_global(_v4_scope, 'isinstance')(available, _v4_global(_v4_scope, 'bool')):
            raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact source-pool availability is invalid")
        count = item.get("row_count")
        if _v4_global(_v4_scope, 'isinstance')(count, _v4_global(_v4_scope, 'bool')) or not _v4_global(_v4_scope, 'isinstance')(count, _v4_global(_v4_scope, 'int')) or count < 0:
            raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact source-pool row_count is invalid")
        empty = item.get("valid_empty", False)
        if not _v4_global(_v4_scope, 'isinstance')(empty, _v4_global(_v4_scope, 'bool')) or (
            available and empty != (count == 0)
        ) or (not available and empty):
            raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact source-pool empty marker is invalid")
        diagnostics = item.get("diagnostics", [])
        if not _v4_global(_v4_scope, 'isinstance')(diagnostics, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'any')(
            not _v4_global(_v4_scope, 'isinstance')(reason, _v4_global(_v4_scope, 'str')) for reason in diagnostics
        ):
            raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact source-pool diagnostics are invalid")
        if not available:
            if item.get("status") != "UNAVAILABLE" or count != 0 or empty:
                raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact unavailable source-pool binding is invalid")
            if item.get("producer_id") != "" or item.get("source_role") != "":
                raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact unavailable source-pool identity is invalid")
            if not diagnostics:
                raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact unavailable source-pool diagnostic is missing")
            for name in ("pool_sha256", "artifact_raw_sha256", "manifest_raw_sha256", "receipt_raw_sha256"):
                if item.get(name) is not None:
                    raise _v4_global(_v4_scope, 'StrictCommitError')(
                        f"strict artifact unavailable source-pool {pool_id} {name} must be null"
                    )
        else:
            expected_status = _v4_global(_v4_scope, 'a_pool_contract')(pool_id)[0]
            diagnostic_statuses = {
                "CANNOT_CONFIRM", "MISSING", "VALID_EMPTY", "FAILED",
                "SOURCE_MISSING", "NOT_MATERIALIZED", "UNAVAILABLE",
            }
            if count > 0 and item.get("status") != expected_status:
                raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact source-pool status is invalid")
            if count == 0 and item.get("status") != expected_status and item.get("status") not in diagnostic_statuses:
                raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact empty source-pool status is invalid")
            if count == 0 and not diagnostics:
                raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact empty source-pool diagnostic is missing")
            if not _v4_global(_v4_scope, 'isinstance')(item.get("source_role", ""), _v4_global(_v4_scope, 'str')) or not item.get("source_role", ""):
                raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact source-pool source_role is missing")
            if not _v4_global(_v4_scope, 'isinstance')(item.get("producer_id", ""), _v4_global(_v4_scope, 'str')) or not item.get("producer_id", ""):
                raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact source-pool producer_id is missing")
            for name, alias in (("artifact_bytes_sha256", "artifact_raw_sha256"), ("manifest_bytes_sha256", "manifest_raw_sha256"), ("receipt_bytes_sha256", "receipt_raw_sha256"), ("pool_sha256", "semantic_sha256")):
                _v4_global(_v4_scope, '_pool_value')(item, name, alias, f"strict artifact source-pool {pool_id} {name}")
        expected = {
            "artifact_relative_path": f"preselection_pools/{trade_date}/{pool_id}.json",
            "manifest_relative_path": f"preselection_pools/{trade_date}/manifest.json",
            "receipt_relative_path": f"preselection_pools/{trade_date}/receipts/{pool_id}.json",
        }
        if _v4_global(_v4_scope, 'any')(item.get(name) != path for name, path in expected.items()):
            raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact source-pool path mismatch")
    available_ids = payload.get("available_pool_ids")
    expected_available_ids = [
        item["pool_id"]
        for item in provenance
        if item.get("available", True) is True
    ]
    if available_ids is not None and available_ids != expected_available_ids:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact available pool ordering mismatch")
    _v4_global(_v4_scope, '_require_sha')(payload.get("source_pool_provenance_sha256"), "strict artifact source_pool_provenance_sha256")
    if payload["source_pool_provenance_sha256"] != _v4_global(_v4_scope, '_canonical_sha')(provenance):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact source-pool provenance SHA mismatch")
    sources = payload.get("code_sources")
    if not _v4_global(_v4_scope, 'isinstance')(sources, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(sources) != _v4_global(_v4_scope, 'set')(codes):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact code source membership mismatch")
    for code in codes:
        values = sources.get(code)
        if not _v4_global(_v4_scope, 'isinstance')(values, _v4_global(_v4_scope, 'list')) or not values or _v4_global(_v4_scope, 'any')(pool_id not in _v4_global(_v4_scope, 'REQUIRED_A_STAGE_POOL_IDS') for pool_id in values) or _v4_global(_v4_scope, 'len')(values) != _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'set')(values)):
            raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact code source membership mismatch")
        provenance_by_pool = {
            item["pool_id"]: item for item in provenance if _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'Mapping'))
        }
        if _v4_global(_v4_scope, 'any')(
            provenance_by_pool[pool_id].get("available", True) is not True
            or provenance_by_pool[pool_id].get("row_count", 0) <= 0
            for pool_id in values
        ):
            raise _v4_global(_v4_scope, 'StrictCommitError')("strict artifact code source is unavailable")


def __revalidate_physical_snapshot_body(_v4_scope, /, root, trade_date, expected, *, lock_lease):
    """Refuse publication if physical pool evidence changed before the lock.

    The first snapshot is needed to build the caller's proposal.  A fresh
    snapshot inside the import lock is the publication gate: pool writers use
    that same lock, so the verified source cannot change between this check and
    the commit writes.
    """

    try:
        current = _v4_global(_v4_scope, 'read_strict_a_preselection_snapshot')(
            root, trade_date, lock_lease=lock_lease
        )
    except (_v4_global(_v4_scope, 'StageAcquisitionContractError'), _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError')) as error:
        raise _v4_global(_v4_scope, 'StrictCommitError')(
            f"required A pool strict physical snapshot cannot be confirmed while locked: {error}"
        ) from error
    if current != expected:
        raise _v4_global(_v4_scope, 'StrictCommitError')(
            "strict physical pool snapshot changed before publication"
        )
