"""infrastructure.stage_acquisition_universe_contracts: strict_artifact (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _validate_strict_stage_acquisition_artifact_body(_v4_scope, /, payload):
    "Validate the immutable artifact's strict physical-pool authority.\n\n    This is intentionally independent of the store implementation so the\n    publication boundary can remain a small call into one pure contract.  A\n    mapping/display artifact may still be built for diagnostics, but it cannot\n    satisfy this validator and therefore cannot create or advance ``current``.\n    "
    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "stage-acquisition artifact must be an object"
        )
    if payload.get("authority") != _v4_global(_v4_scope, 'STRICT_POOL_SNAPSHOT_AUTHORITY'):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "stage-acquisition artifact authority must be "
            f"{_v4_global(_v4_scope, 'STRICT_POOL_SNAPSHOT_AUTHORITY')}"
        )
    trade_date = _v4_global(_v4_scope, 'str')(payload.get("trade_date") or "")
    try:
        trade_date = _v4_global(_v4_scope, '_date')(trade_date)
    except _v4_global(_v4_scope, 'ValueError') as error:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "stage-acquisition artifact trade date is invalid"
        ) from error

    if payload.get("status") != "READY":
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "strict stage-acquisition artifact must be READY"
        )
    if payload.get("source_projection_status") != "READY_WITH_ROWS":
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "strict stage-acquisition projection is not READY_WITH_ROWS"
        )
    cannot_confirm = payload.get("cannot_confirm", [])
    if not _v4_global(_v4_scope, 'isinstance')(cannot_confirm, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'any')(
        not _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'str')) for item in cannot_confirm
    ):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "strict stage-acquisition artifact cannot_confirm is invalid"
        )
    blocking_reasons = payload.get("blocking_reasons", [])
    if not _v4_global(_v4_scope, 'isinstance')(blocking_reasons, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'any')(
        not _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'str')) for item in blocking_reasons
    ) or blocking_reasons:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "strict stage-acquisition artifact blocking_reasons must be empty"
        )
    if payload.get("stage_selection_eligible") is not True:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "strict stage-acquisition artifact stage_selection_eligible must be true"
        )
    notes = payload.get("policy_notes")
    if not _v4_global(_v4_scope, 'isinstance')(notes, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'any')(
        not _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'str')) for item in notes
    ):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "strict stage-acquisition artifact policy_notes are invalid"
        )

    provenance = payload.get("source_pool_provenance")
    if not _v4_global(_v4_scope, 'isinstance')(provenance, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'len')(provenance) != _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'REQUIRED_A_STAGE_POOL_IDS')):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "strict stage-acquisition source pool provenance must contain exactly six pools"
        )

    _b04_validate_strict_provenance_rows(_v4_scope, payload, provenance, trade_date)
    _b04_validate_strict_pool_summary(_v4_scope, payload, provenance, cannot_confirm)
    _b04_validate_strict_code_sources(_v4_scope, payload, provenance)
    return trade_date

def _b04_validate_strict_provenance_rows(_v4_scope, payload, provenance, trade_date):
    expected_paths = {
        pool_id: {
            "artifact_relative_path": f"preselection_pools/{trade_date}/{pool_id}.json",
            "manifest_relative_path": f"preselection_pools/{trade_date}/manifest.json",
            "receipt_relative_path": f"preselection_pools/{trade_date}/receipts/{pool_id}.json",
        }
        for pool_id in _v4_global(_v4_scope, 'REQUIRED_A_STAGE_POOL_IDS')
    }

    for index, (item, expected_pool_id) in _v4_global(_v4_scope, 'enumerate')(
        _v4_global(_v4_scope, 'zip')(provenance, _v4_global(_v4_scope, 'REQUIRED_A_STAGE_POOL_IDS'))
    ):
        if not _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'Mapping')) or item.get("pool_id") != expected_pool_id:
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                "strict stage-acquisition source pool provenance order or identity is invalid"
            )
        expected_status = _v4_global(_v4_scope, 'a_pool_contract')(expected_pool_id)[0]
        available = item.get("available", True)
        if not _v4_global(_v4_scope, 'isinstance')(available, _v4_global(_v4_scope, 'bool')):
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                f"strict stage-acquisition source pool {expected_pool_id} availability is invalid"
            )
        diagnostics = item.get("diagnostics", [])
        if not _v4_global(_v4_scope, 'isinstance')(diagnostics, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'any')(
            not _v4_global(_v4_scope, 'isinstance')(reason, _v4_global(_v4_scope, 'str')) for reason in diagnostics
        ):
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                f"strict stage-acquisition source pool {expected_pool_id} diagnostics are invalid"
            )
        count = item.get("row_count")
        if _v4_global(_v4_scope, 'isinstance')(count, _v4_global(_v4_scope, 'bool')) or not _v4_global(_v4_scope, 'isinstance')(count, _v4_global(_v4_scope, 'int')) or count < 0:
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                f"strict stage-acquisition source pool {expected_pool_id} row_count is invalid"
            )
        empty = item.get("valid_empty", False)
        if not _v4_global(_v4_scope, 'isinstance')(empty, _v4_global(_v4_scope, 'bool')) or (
            available and empty != (count == 0)
        ) or (not available and empty):
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                f"strict stage-acquisition source pool {expected_pool_id} empty marker is invalid"
            )
        if not available:
            if item.get("status") != "UNAVAILABLE" or count != 0 or empty:
                raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                    f"strict stage-acquisition source pool {expected_pool_id} unavailable binding is invalid"
                )
            if item.get("producer_id") != "" or item.get("source_role") != "":
                raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                    f"strict stage-acquisition source pool {expected_pool_id} unavailable identity is invalid"
                )
            if not diagnostics:
                raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                    f"strict stage-acquisition source pool {expected_pool_id} unavailable diagnostic is missing"
                )
            for field in (
                "pool_sha256",
                "artifact_raw_sha256",
                "manifest_raw_sha256",
                "receipt_raw_sha256",
            ):
                if item.get(field) is not None:
                    raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                        f"strict stage-acquisition source pool {expected_pool_id} unavailable {field} must be null"
                    )
        else:
            if count > 0 and item.get("status") != expected_status:
                raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                    f"strict stage-acquisition source pool {expected_pool_id} status is invalid"
                )
            if count == 0 and item.get("status") != expected_status and item.get("status") not in _v4_global(_v4_scope, '_POOL_DIAGNOSTIC_STATUSES'):
                raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                    f"strict stage-acquisition source pool {expected_pool_id} empty status is invalid"
                )
            if count == 0 and not diagnostics:
                raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                    f"strict stage-acquisition source pool {expected_pool_id} empty diagnostic is missing"
                )
            if not _v4_global(_v4_scope, 'isinstance')(item.get("producer_id"), _v4_global(_v4_scope, 'str')) or not item.get("producer_id"):
                raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                    f"strict stage-acquisition source pool {expected_pool_id} producer identity is missing"
                )
            if not _v4_global(_v4_scope, 'isinstance')(item.get("source_role"), _v4_global(_v4_scope, 'str')) or not item.get("source_role"):
                raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                    f"strict stage-acquisition source pool {expected_pool_id} source role is missing"
                )
            for field in (
                "pool_sha256",
                "artifact_raw_sha256",
                "manifest_raw_sha256",
                "receipt_raw_sha256",
            ):
                value = item.get(field)
                if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'str')) or _v4_global(_v4_scope, '_SHA256').fullmatch(value) is None:
                    raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                        f"strict stage-acquisition source pool {expected_pool_id} {field} is invalid"
                    )
        for field, expected in expected_paths[expected_pool_id].items():
            if item.get(field) != expected:
                raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                    f"strict stage-acquisition source pool {expected_pool_id} {field} is not bound"
                )


def _b04_validate_strict_pool_summary(_v4_scope, payload, provenance, cannot_confirm):
    pool_diagnostics = payload.get("pool_diagnostics", {})

    if not _v4_global(_v4_scope, 'isinstance')(pool_diagnostics, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "strict stage-acquisition pool_diagnostics are invalid"
        )

    flattened_diagnostics: list[str] = []

    for pool_id in _v4_global(_v4_scope, 'REQUIRED_A_STAGE_POOL_IDS'):
        reasons = pool_diagnostics.get(pool_id, [])
        if not _v4_global(_v4_scope, 'isinstance')(reasons, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'any')(
            not _v4_global(_v4_scope, 'isinstance')(reason, _v4_global(_v4_scope, 'str')) for reason in reasons
        ):
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                f"strict stage-acquisition pool {pool_id} diagnostics are invalid"
            )
        flattened_diagnostics.extend(f"{pool_id}:{reason}" for reason in reasons)

    if cannot_confirm != flattened_diagnostics:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "strict stage-acquisition diagnostics are not bound to provenance"
        )

    available_ids = payload.get("available_pool_ids")

    expected_available_ids = [
        item["pool_id"]
        for item in provenance
        if item.get("available", True) is True
    ]

    if available_ids is not None and available_ids != expected_available_ids:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "strict stage-acquisition available pool ordering is invalid"
        )

    if payload.get("source_pool_provenance_sha256") != _v4_global(_v4_scope, '_semantic_sha')(provenance):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "strict stage-acquisition source pool provenance SHA mismatch"
        )


def _b04_validate_strict_code_sources(_v4_scope, payload, provenance):
    codes = payload.get("codes")

    if not _v4_global(_v4_scope, 'isinstance')(codes, _v4_global(_v4_scope, 'list')) or not codes:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "strict stage-acquisition codes are missing"
        )

    code_sources = payload.get("code_sources")

    if not _v4_global(_v4_scope, 'isinstance')(code_sources, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(code_sources) != _v4_global(_v4_scope, 'set')(codes):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "strict stage-acquisition code source membership is invalid"
        )

    pool_positions = {
        pool_id: index for index, pool_id in _v4_global(_v4_scope, 'enumerate')(_v4_global(_v4_scope, 'REQUIRED_A_STAGE_POOL_IDS'))
    }

    for code in codes:
        if not _v4_global(_v4_scope, 'isinstance')(code, _v4_global(_v4_scope, 'str')) or _v4_global(_v4_scope, '_A_CODE').fullmatch(code) is None:
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                "strict stage-acquisition code source contains an invalid code"
            )
        sources = code_sources.get(code)
        if not _v4_global(_v4_scope, 'isinstance')(sources, _v4_global(_v4_scope, 'list')) or not sources:
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                f"strict stage-acquisition code {code} has no source pool"
            )
        if _v4_global(_v4_scope, 'any')(source not in pool_positions for source in sources):
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                f"strict stage-acquisition code {code} has an invalid source pool"
            )
        provenance_by_pool = {
            item["pool_id"]: item for item in provenance if _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'Mapping'))
        }
        if _v4_global(_v4_scope, 'any')(
            provenance_by_pool[source].get("available", True) is not True
            or provenance_by_pool[source].get("row_count", 0) <= 0
            for source in sources
        ):
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                f"strict stage-acquisition code {code} has an unavailable source pool"
            )
        if _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'set')(sources)) != _v4_global(_v4_scope, 'len')(sources) or _v4_global(_v4_scope, 'list')(sources) != _v4_global(_v4_scope, 'sorted')(
            sources, key=pool_positions.__getitem__
        ):
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                f"strict stage-acquisition code {code} source pools are not ordered"
            )
