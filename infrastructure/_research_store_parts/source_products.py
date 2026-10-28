"""infrastructure.research_store: source_products (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _ResearchSelectionStore__verify_product_sources_body(_v4_scope, /, cls, payload, *, _seen_paths):
    refs = payload.get("source_refs")
    if not _v4_global(_v4_scope, 'isinstance')(refs, _v4_global(_v4_scope, 'list')) or not refs:
        if payload.get("status") == "NOT_MATERIALIZED":
            return
        raise _v4_global(_v4_scope, 'ValueError')("selection source refs are required")
    supply_documents, supply_refs, candidate_source_types = _b04_validate_product_candidate_refs(
        _v4_scope, cls, payload
    )
    _b04_validate_product_research_supply(
        _v4_scope, cls, payload, candidate_source_types, supply_documents, supply_refs, _seen_paths
    )
    _b04_validate_product_formal_authority(_v4_scope, cls, payload)

def _b04_validate_product_candidate_refs(_v4_scope, cls, payload):
    supply_documents: list[Mapping[str, Any]] = []

    supply_refs: list[Mapping[str, Any]] = []

    for candidate in payload.get("research_candidates", []):
        candidate_refs = candidate.get("source_refs")
        if not _v4_global(_v4_scope, 'isinstance')(candidate_refs, _v4_global(_v4_scope, 'list')) or not candidate_refs:
            raise _v4_global(_v4_scope, 'ValueError')("selection candidate source refs are missing")
        for ref in candidate_refs:
            verified = cls._verify_source_ref(
                ref,
                expected_target_trade_date=_v4_global(_v4_scope, 'str')(payload["target_trade_date"]),
            )
            if ref.get("type") == _v4_global(_v4_scope, 'RESEARCH_SUPPLY_TYPE'):
                document = verified.get("document")
                if _v4_global(_v4_scope, 'isinstance')(document, _v4_global(_v4_scope, 'Mapping')):
                    supply_documents.append(document)
                    supply_refs.append(ref)
            cls._verify_candidate_source_projection(
                candidate,
                ref,
                verified,
                source_date=_v4_global(_v4_scope, 'str')(payload["source_date"]),
                target_trade_date=_v4_global(_v4_scope, 'str')(payload["target_trade_date"]),
                cutoff_at=_v4_global(_v4_scope, 'str')(payload.get("cutoff_at") or ""),
            )

    candidate_source_types = {
        ref.get("type")
        for candidate in payload.get("research_candidates", [])
        for ref in candidate.get("source_refs", [])
        if _v4_global(_v4_scope, 'isinstance')(ref, _v4_global(_v4_scope, 'Mapping'))
    }
    return supply_documents, supply_refs, candidate_source_types


def _b04_validate_product_research_supply(_v4_scope, cls, payload, candidate_source_types, supply_documents, supply_refs, _seen_paths):
    if candidate_source_types == {_v4_global(_v4_scope, 'RESEARCH_SUPPLY_TYPE')}:
        decision_ref = payload.get("manager_decision_ref")
        snapshot_2200 = payload.get("snapshots", {}).get("2200", {})
        if not supply_documents or not supply_refs:
            raise _v4_global(_v4_scope, 'ValueError')("research supply source envelope is missing")
        supply_document = supply_documents[0]
        supply_run_id = _v4_global(_v4_scope, 'str')(supply_document.get("run_id") or "")
        if _v4_global(_v4_scope, 'any')(
            document.get("run_id") != supply_run_id
            or document.get("source_date") != supply_document.get("source_date")
            or document.get("target_trade_date") != supply_document.get("target_trade_date")
            or document.get("frozen_payload_sha256")
            != supply_document.get("frozen_payload_sha256")
            for document in supply_documents
        ):
            raise _v4_global(_v4_scope, 'ValueError')("research supply source envelopes are mixed")
        if snapshot_2200.get("status") == "READY" and snapshot_2200.get("run_id") != supply_run_id:
            raise _v4_global(_v4_scope, 'ValueError')("research supply 2200 run binding mismatch")
        ready_later = [
            phase
            for phase in ("0830", "0935", "1620")
            if _v4_global(_v4_scope, 'isinstance')(payload.get("snapshots", {}).get(phase), _v4_global(_v4_scope, 'Mapping'))
            and payload["snapshots"][phase].get("status") == "READY"
        ]
        expected_product_run = (
            _v4_global(_v4_scope, 'str')(payload["snapshots"][ready_later[-1]].get("run_id") or "")
            if ready_later
            else supply_run_id
        )
        if payload.get("run_id") != expected_product_run:
            raise _v4_global(_v4_scope, 'ValueError')("research supply product run binding mismatch")
        if snapshot_2200.get("status") == "READY":
            if not _v4_global(_v4_scope, 'isinstance')(decision_ref, _v4_global(_v4_scope, 'Mapping')):
                raise _v4_global(_v4_scope, 'ValueError')("research supply 2200 manager decision reference is missing")
            decision_path_value = decision_ref.get("path")
            if not _v4_global(_v4_scope, 'isinstance')(decision_path_value, _v4_global(_v4_scope, 'str')) or not decision_path_value:
                raise _v4_global(_v4_scope, 'ValueError')("manager decision reference is missing")
            decision_path = _v4_global(_v4_scope, 'Path')(decision_path_value)
            if not decision_path.is_file() or decision_path.is_symlink():
                raise _v4_global(_v4_scope, 'ValueError')("manager decision reference SHA mismatch")
            decision_raw = decision_path.read_bytes()
            if _v4_global(_v4_scope, 'hashlib').sha256(decision_raw).hexdigest() != _v4_global(_v4_scope, 'str')(
                decision_ref.get("raw_sha256") or ""
            ).lower():
                raise _v4_global(_v4_scope, 'ValueError')("manager decision reference SHA mismatch")
            try:
                decision_document = _v4_global(_v4_scope, 'json').loads(decision_raw.decode("utf-8"))
            except (_v4_global(_v4_scope, 'UnicodeDecodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
                raise _v4_global(_v4_scope, 'ValueError')("manager decision document is invalid JSON") from error
            if not _v4_global(_v4_scope, 'isinstance')(decision_document, _v4_global(_v4_scope, 'Mapping')):
                raise _v4_global(_v4_scope, 'ValueError')("manager decision document is not an object")
            _v4_global(_v4_scope, 'validate_manager_research_decision')(
                decision_document,
                candidate_ids=[
                    _v4_global(_v4_scope, 'str')(candidate["candidate_id"])
                    for candidate in payload.get("research_candidates", [])
                ],
                supply_envelope=supply_document,
            )
            projected = {
                _v4_global(_v4_scope, 'str')(candidate["candidate_id"]): candidate["manager_decision"]
                for candidate in payload.get("research_candidates", [])
                if "manager_decision" in candidate
            }
            if projected:
                expected_projection: dict[str, dict[str, Any]] = {}
                for role, field in (("CORE", "core"), ("CONDITIONAL", "conditional")):
                    for order, row in _v4_global(_v4_scope, 'enumerate')(decision_document[field], 1):
                        expected_projection[_v4_global(_v4_scope, 'str')(row["candidate_id"])] = {
                            "schema_version": decision_document["schema_version"],
                            "phase": decision_document["phase"],
                            "decision_state": decision_document["decision_state"],
                            "source_date": decision_document["source_date"],
                            "target_trade_date": decision_document["target_trade_date"],
                            "run_id": decision_document["run_id"],
                            "generated_at": decision_document["generated_at"],
                            "cutoff_at": decision_document["cutoff_at"],
                            "role": role,
                            "order": order,
                            "reason": row["reason"],
                        }
                if _v4_global(_v4_scope, 'set')(projected) != _v4_global(_v4_scope, 'set')(expected_projection):
                    raise _v4_global(_v4_scope, 'ValueError')(
                        "manager decision projection candidate set mismatch"
                    )
                for candidate_id, projection in projected.items():
                    _v4_global(_v4_scope, 'validate_manager_decision_projection')(
                        projection,
                        source_date=_v4_global(_v4_scope, 'str')(payload["source_date"]),
                        target_trade_date=_v4_global(_v4_scope, 'str')(payload["target_trade_date"]),
                        cutoff_at=_v4_global(_v4_scope, 'str')(payload["cutoff_at"]),
                        expected_run_id=_v4_global(_v4_scope, 'str')(decision_document["run_id"]),
                        expected_generated_at=_v4_global(_v4_scope, 'str')(decision_document["generated_at"]),
                    )
                    if _v4_global(_v4_scope, 'dict')(projection) != expected_projection[candidate_id]:
                        raise _v4_global(_v4_scope, 'ValueError')(
                            "manager decision projection does not match decision document"
                        )
            cls._verify_manager_qualification_refs(
                decision_document,
                source_date=_v4_global(_v4_scope, 'str')(payload["source_date"]),
                target_trade_date=_v4_global(_v4_scope, 'str')(payload["target_trade_date"]),
                candidate_ids=[
                    _v4_global(_v4_scope, 'str')(candidate["candidate_id"])
                    for candidate in payload.get("research_candidates", [])
                ],
            )
            source_ref = supply_refs[0]
            source_ref_path = _v4_global(_v4_scope, 'str')(source_ref.get("path") or "")
            if decision_document.get("supply_ref", {}).get("path") != source_ref_path:
                raise _v4_global(_v4_scope, 'ValueError')("manager decision supply path binding mismatch")
            if decision_document.get("supply_ref", {}).get("raw_sha256") != source_ref.get("raw_sha256"):
                raise _v4_global(_v4_scope, 'ValueError')("manager decision supply raw SHA binding mismatch")
            decision_time = _v4_global(_v4_scope, 'str')(decision_document.get("generated_at") or "")
            baseline_ids: set[str] | None = None
            if decision_document.get("baseline_ref") is not None:
                baseline_ids = cls._verify_manager_baseline(
                    decision_document["baseline_ref"],
                    source_date=_v4_global(_v4_scope, 'str')(payload["source_date"]),
                    target_trade_date=_v4_global(_v4_scope, 'str')(payload["target_trade_date"]),
                    decision_generated_at=decision_time,
                    _seen_paths=_seen_paths,
                )
                keep_ids = {row["candidate_id"] for row in decision_document["KEEP"]}
                add_ids = {row["candidate_id"] for row in decision_document["ADD"]}
                remove_ids = {row["candidate_id"] for row in decision_document["REMOVE"]}
                if not keep_ids.issubset(baseline_ids) or remove_ids - baseline_ids:
                    raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline KEEP/REMOVE binding mismatch")
                if add_ids & baseline_ids:
                    raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline ADD binding mismatch")
                expected_decision_ids = _v4_global(_v4_scope, 'sorted')((baseline_ids - remove_ids) | add_ids)
            else:
                expected_decision_ids = _v4_global(_v4_scope, 'sorted')(
                    row["candidate_id"]
                    for row in [
                        *decision_document["core"],
                        *decision_document["conditional"],
                    ]
                )
            decision_core_ids = {
                row["candidate_id"]
                for row in [
                    *decision_document["core"],
                    *decision_document["conditional"],
                ]
            }
            if decision_core_ids != _v4_global(_v4_scope, 'set')(expected_decision_ids):
                raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline action set mismatch")
            expected_decision_ids = _v4_global(_v4_scope, 'sorted')(expected_decision_ids)
            if snapshot_2200.get("candidate_ids") != expected_decision_ids:
                raise _v4_global(_v4_scope, 'ValueError')("manager decision 2200 candidate binding mismatch")
            if snapshot_2200.get("run_id") != decision_document.get("run_id"):
                raise _v4_global(_v4_scope, 'ValueError')("manager decision 2200 run binding mismatch")
            if snapshot_2200.get("event_at") != decision_document.get("generated_at"):
                raise _v4_global(_v4_scope, 'ValueError')("manager decision 2200 event binding mismatch")
            if snapshot_2200.get("artifact_sha256") != decision_ref.get("raw_sha256"):
                raise _v4_global(_v4_scope, 'ValueError')("manager decision 2200 artifact binding mismatch")
        elif decision_ref is not None:
            raise _v4_global(_v4_scope, 'ValueError')("research supply manager decision lacks a READY 2200 snapshot")


def _b04_validate_product_formal_authority(_v4_scope, cls, payload):
    formal = payload.get("formal_authority")
    if (
        _v4_global(_v4_scope, 'isinstance')(formal, _v4_global(_v4_scope, 'Mapping'))
        and formal.get("status") == "READY"
        and payload.get("formal_shortlist")
    ):
        candidate_ids = _v4_global(_v4_scope, 'list')(payload.get("formal_shortlist") or [])
        candidates_by_id = {
            _v4_global(_v4_scope, 'str')(candidate.get("candidate_id")): candidate
            for candidate in payload.get("research_candidates", [])
        }
        source_sha256 = _v4_global(_v4_scope, 'str')(formal.get("source_sha256") or "")
        for ref in formal.get("evidence_refs", []):
            document = cls._verify_auxiliary_ref(
                ref,
                "formal evidence",
                schema_version="v3_5.selection_formal_evidence.v1",
                expected_type="EXACT_DATE_PIT",
                source_date=_v4_global(_v4_scope, 'str')(payload["source_date"]),
                target_trade_date=_v4_global(_v4_scope, 'str')(payload["target_trade_date"]),
                candidate_ids=candidate_ids,
                source_sha256=source_sha256,
                expected_run_id=_v4_global(_v4_scope, 'str')(ref.get("run_id") or ""),
            )
            if (
                not _v4_global(_v4_scope, 'isinstance')(document, _v4_global(_v4_scope, 'Mapping'))
                or document.get("status") != "READY"
                or document.get("pit_status") != "READY"
            ):
                raise _v4_global(_v4_scope, 'ValueError')("formal evidence document is not READY")
            cls._verify_formal_candidate_bindings(
                document,
                candidates_by_id=candidates_by_id,
                candidate_ids=candidate_ids,
                label="formal evidence",
            )
        decision_ref = formal.get("manager_decision_ref")
        decision_document = cls._verify_auxiliary_ref(
            decision_ref,
            "manager decision",
            schema_version="v3_5.selection_manager_decision.v1",
            expected_type="MANAGER_DECISION",
            source_date=_v4_global(_v4_scope, 'str')(payload["source_date"]),
            target_trade_date=_v4_global(_v4_scope, 'str')(payload["target_trade_date"]),
            candidate_ids=candidate_ids,
            source_sha256=source_sha256,
            expected_run_id=_v4_global(_v4_scope, 'str')(decision_ref.get("run_id") or "")
            if _v4_global(_v4_scope, 'isinstance')(decision_ref, _v4_global(_v4_scope, 'Mapping'))
            else None,
        )
        if not _v4_global(_v4_scope, 'isinstance')(decision_document, _v4_global(_v4_scope, 'Mapping')) or decision_document.get("decision") is not True:
            raise _v4_global(_v4_scope, 'ValueError')("manager decision document is not approved")
        cls._verify_formal_candidate_bindings(
            decision_document,
            candidates_by_id=candidates_by_id,
            candidate_ids=candidate_ids,
            label="manager decision",
        )
