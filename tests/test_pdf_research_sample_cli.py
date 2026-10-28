from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from infrastructure import local_document_model, pdf_research
from ops import run_pdf_research_sample as cli


APPROVED_PLAN_SHA = "b35f68e2240ed00585aaab6a80e5d5dec65de9707b9d564734f2a2a3f409db53"
CURRENT_SCHEMA_CONFIGURATION_SHA256 = "0d7f9f7f47c5aa95cdb70d75edd8d42ea207a3fd0dc950c1f6457eb03a6aff78"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _configure_frozen_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "scope"
    root.mkdir()
    scope_path = root / "scope.json"
    manifest_path = root / "sample-manifest-v1.json"
    scope = {
        "status": "FROZEN",
        "phase": "V3_IMPLEMENTATION_OFFLINE_FIRST",
        "approved_plan_sha256": APPROVED_PLAN_SHA,
        "ALLOWED_PATHS": [str(root)],
    }
    source_sha = "a" * 64
    samples = []
    for sample_id in ("S01", "S02"):
        samples.append(
            {
                "sample_id": sample_id,
                "local_pdf_path": f"/Users/lexi/Desktop/学习/知识星球/{sample_id}.pdf",
                "pdf_sha256": source_sha,
                "page_count": 2,
                "cache_path": f"/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/external_sources/zsxq_hourly/{sample_id}.json",
                "cache_sha256": "b" * 64,
                "source": {
                    "source_hash_raw": source_sha,
                    "document_key": f"document-{sample_id}",
                    "original_filename": f"{sample_id}.pdf",
                    "pit_status": "NON_PIT_CURRENT_KNOWLEDGE_SUPPLEMENT",
                },
            }
        )
    manifest = {
        "schema_version": "v4.pdf_research_frozen_sample.v1",
        "status": "FROZEN",
        "first_canary_sample_id": "S01",
        "sample_count": len(samples),
        "max_documents": 20,
        "samples": samples,
    }
    scope_path.write_text(json.dumps(scope), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(cli, "SAMPLE_SCOPE_ROOT", root)
    monkeypatch.setattr(cli, "SCOPE_PATH", scope_path)
    monkeypatch.setattr(cli, "SAMPLE_MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(cli, "EXPECTED_SCOPE_SHA256", _sha(scope_path))
    monkeypatch.setattr(cli, "EXPECTED_SAMPLE_MANIFEST_SHA256", _sha(manifest_path))
    monkeypatch.setattr(cli, "SOURCE_REVIEW_RECEIPT_PATH", root / "source-review-receipt.json")
    monkeypatch.setattr(cli, "CANARY_REVIEW_RECEIPT_PATH", root / "canary-review-receipt.json")
    monkeypatch.setattr(cli, "SAMPLE_ACCEPTANCE_RECEIPT_PATH", root / "sample-acceptance-receipt.json")
    monkeypatch.setattr(cli, "RUNTIME_BINDING_EVIDENCE_PATH", root / "runtime-binding-evidence.json")
    monkeypatch.setattr(cli, "EXECUTION_SCOPE_RECEIPT_PATH", root / "execution-scope-receipt.json")
    monkeypatch.setattr(cli, "FIRST_CHUNK_ACCEPTANCE_RECEIPT_PATH", root / "first-chunk-acceptance-receipt.json")


def _write_execution_authorization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    source_receipt = {
        "schema": "v4.pdf_research_v3.source_review.v1",
        "status": "PASS",
        "reviewer": "independent-reviewer",
        "scope_sha256": cli.EXPECTED_SCOPE_SHA256,
        "reviewed_files": cli._reviewed_files(),
    }
    cli.SOURCE_REVIEW_RECEIPT_PATH.write_text(json.dumps(source_receipt), encoding="utf-8")
    runtime_limits: dict = {}
    request_policy: dict = {}
    evidence_sources = {
        **local_document_model.PINNED_SOURCE_SHA256,
        "v4/manager_workbench/inputs/pdf_pages.py": "ec1d4990277868e42d6d3a7ff93972e80a89e44dcfaa7c9d9f656c32ae07a770",
        "infrastructure/local_document_model.py": "a" * 64,
        "infrastructure/pdf_research.py": "b" * 64,
        "ops/run_pdf_research_sample.py": "c" * 64,
    }
    evidence = {
        "schema": "v4.pdf_research_v3.runtime_binding_evidence.v1",
        "stage": "OFFLINE_IMPLEMENTATION_ONLY",
        "runtime_binding_status": "MATCH",
        "runtime_settings_comparison": "MATCH_PREVIOUS_HASH_ONLY",
        "model_settings_comparison": "MATCH_PREVIOUS_HASH_ONLY",
        "model_id": local_document_model.MODEL_ID,
        "request_profile": local_document_model.PROFILE_NAME,
        "runtime_python": str(local_document_model.RUNTIME_PYTHON.resolve()),
        "required_runtime_python": str(local_document_model.RUNTIME_PYTHON),
        "runtime_settings_path": "/frozen/runtime/settings.json",
        "runtime_settings_sha256": cli.PREVIOUSLY_REVIEWED_RUNTIME_SETTINGS_SHA256,
        "model_settings_path": "/frozen/runtime/model_settings.json",
        "model_settings_sha256": cli.PREVIOUSLY_REVIEWED_MODEL_SETTINGS_SHA256,
        "runtime_limits_sha256": local_document_model.sha256_bytes(local_document_model.canonical_json(runtime_limits)),
        "request_policy_sha256": local_document_model.sha256_bytes(local_document_model.canonical_json(request_policy)),
        "configuration_sha256": "d" * 64,
        "source_sha256": evidence_sources,
        "active_server_memory_settings": "CANNOT_CONFIRM",
    }
    cli.RUNTIME_BINDING_EVIDENCE_PATH.write_text(json.dumps(evidence), encoding="utf-8")
    monkeypatch.setattr(cli, "EXPECTED_RUNTIME_BINDING_EVIDENCE_SHA256", _sha(cli.RUNTIME_BINDING_EVIDENCE_PATH))
    expected_identity = cli._expected_runtime_identity(
        evidence,
        source_receipt,
        scope_configuration_sha256=evidence["configuration_sha256"],
    )
    binding = {
        **expected_identity,
        "runtime_limits": runtime_limits,
        "request_policy": request_policy,
    }
    scope, scope_sha, manifest_sha, documents = cli.load_frozen_documents("CANARY")
    del scope
    execution_scope = {
        "schema": cli.EXECUTION_SCOPE_SCHEMA,
        "status": "FROZEN",
        "authorized_by": cli.EXECUTION_SCOPE_AUTHORIZER,
        "execution_phase": "V3_CANARY_EXECUTION",
        "source_scope_phase": "V3_IMPLEMENTATION_OFFLINE_FIRST",
        "request_phase": "CANARY",
        "scope_sha256": scope_sha,
        "sample_manifest_path": str(cli.SAMPLE_MANIFEST_PATH),
        "sample_manifest_sha256": manifest_sha,
        "selected_document_ids": [document["document_id"] for document in documents],
        "selected_chunk_indices": [1],
        "reusable_chunk_indices": [],
        "first_chunk_acceptance_receipt_sha256": None,
        "source_review_receipt_sha256": _sha(cli.SOURCE_REVIEW_RECEIPT_PATH),
        "runtime_binding_evidence_path": str(cli.RUNTIME_BINDING_EVIDENCE_PATH),
        "runtime_binding_evidence_sha256": _sha(cli.RUNTIME_BINDING_EVIDENCE_PATH),
        "expected_runtime_identity": expected_identity,
        "request_budget": {
            "maximum_model_calls": cli.CANARY_MAX_MODEL_CALLS,
            "max_attempts_per_chunk": 1,
            "max_source_characters_per_chunk": pdf_research.MAX_SOURCE_CHARACTERS_PER_CHUNK,
            "max_serialized_request_envelope_bytes": pdf_research.MAX_SERIALIZED_REQUEST_ENVELOPE_BYTES,
            "automatic_resume": False,
        },
        "write_allowlist": pdf_research.expected_write_allowlist(),
        "shared_model_lock_path": str(pdf_research.GLOBAL_MODEL_LOCK_PATH),
        "independent_queue_root": str(pdf_research.PDF_RESEARCH_STATE_ROOT / "queue"),
        "ocr_allowed": False,
        "download_allowed": False,
        "pdf_lookup_allowed": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    cli.EXECUTION_SCOPE_RECEIPT_PATH.write_text(json.dumps(execution_scope), encoding="utf-8")
    return {"binding": binding, "expected_identity": expected_identity, "evidence": evidence}


def test_canary_plan_is_frozen_single_document_and_has_bounded_write_allowlist(tmp_path, monkeypatch) -> None:
    _configure_frozen_inputs(tmp_path, monkeypatch)
    plan = cli.build_execution_plan("CANARY", execute=False)
    assert plan["selected_document_ids"] == ["S01"]
    assert plan["selected_chunk_indices"] == [1]
    assert plan["selected_document_count"] == 1
    assert plan["maximum_document_count"] == 20
    assert plan["source_manifest_fallthrough"] is False
    assert plan["model_request_enabled"] is False
    assert plan["ocr_invocations_allowed"] is False
    assert plan["download_allowed"] is False
    assert plan["pdf_lookup_allowed"] is False
    assert all("/research/" in path for path in plan["write_allowlist"])


def test_user_prompt_requests_source_unit_ids_without_legacy_character_offsets() -> None:
    page = pdf_research.PageText(1, 1, "Example Energy Co. reported 12 units.", "NATIVE_TEXT", None, "pypdf")
    chunk = pdf_research.build_source_chunks("SYNTH-01", [page])[0]

    user_prompt = pdf_research.build_messages("SYNTH-01", chunk)[1]["content"]

    assert "source_unit_id" in user_prompt
    assert "证据偏移从每个 unit" not in user_prompt
    assert "Unicode 字符计数" not in user_prompt


def test_root_frozen_schema_configuration_digest_matches_actual_binding_before_get(tmp_path, monkeypatch) -> None:
    _configure_frozen_inputs(tmp_path, monkeypatch)
    frozen = _write_execution_authorization(tmp_path, monkeypatch)
    scope = json.loads(cli.EXECUTION_SCOPE_RECEIPT_PATH.read_text(encoding="utf-8"))
    scope["expected_runtime_identity"]["configuration_sha256"] = CURRENT_SCHEMA_CONFIGURATION_SHA256
    cli.EXECUTION_SCOPE_RECEIPT_PATH.write_text(json.dumps(scope), encoding="utf-8")

    binding = deepcopy(frozen["binding"])
    binding["configuration_sha256"] = CURRENT_SCHEMA_CONFIGURATION_SHA256
    monkeypatch.setattr(local_document_model, "require_runtime_python", lambda: None)
    monkeypatch.setattr(local_document_model, "build_request_material", lambda _schema: dict(binding))
    api_checks: list[bool] = []
    monkeypatch.setattr(local_document_model, "inspect_local_api_identity", lambda: api_checks.append(True) or {"status": "MATCH"})
    writes: list[str] = []
    queues: list[bool] = []
    monkeypatch.setattr(pdf_research, "_atomic_private_json", lambda path, *_args, **_kwargs: writes.append(str(path)))
    monkeypatch.setattr(pdf_research, "create_pdf_queue", lambda: queues.append(True) or object())
    monkeypatch.setattr(
        pdf_research,
        "analyze_document",
        lambda document, **_kwargs: {"document_id": document["document_id"]},
    )
    monkeypatch.setattr(pdf_research, "persist_document_result", lambda *_args, **_kwargs: None)

    results = cli.execute_sample("CANARY")

    assert [row["document_id"] for row in results] == ["S01"]
    assert api_checks == [True]
    assert len(writes) == 1
    assert queues == [True]


def test_execution_scope_configuration_digest_must_be_lowercase_sha256_before_binding_read(tmp_path, monkeypatch) -> None:
    _configure_frozen_inputs(tmp_path, monkeypatch)
    _write_execution_authorization(tmp_path, monkeypatch)
    scope = json.loads(cli.EXECUTION_SCOPE_RECEIPT_PATH.read_text(encoding="utf-8"))
    scope["expected_runtime_identity"]["configuration_sha256"] = "Z" * 64
    cli.EXECUTION_SCOPE_RECEIPT_PATH.write_text(json.dumps(scope), encoding="utf-8")
    monkeypatch.setattr(
        local_document_model,
        "build_request_material",
        lambda _schema: pytest.fail("invalid execution-scope digest must fail before binding material construction"),
    )
    monkeypatch.setattr(
        local_document_model,
        "inspect_local_api_identity",
        lambda: pytest.fail("invalid execution-scope digest must fail before API identity inspection"),
    )
    monkeypatch.setattr(
        pdf_research,
        "_atomic_private_json",
        lambda *_args, **_kwargs: pytest.fail("invalid execution-scope digest must fail before source-manifest writes"),
    )
    monkeypatch.setattr(
        pdf_research,
        "create_pdf_queue",
        lambda *_args, **_kwargs: pytest.fail("invalid execution-scope digest must fail before queue creation"),
    )

    with pytest.raises(cli.SampleCliError, match="EXECUTION_SCOPE_CONFIGURATION_HASH_INVALID"):
        cli.execute_sample("CANARY")


def test_sample_plan_requires_canary_review_and_user_acceptance(tmp_path, monkeypatch) -> None:
    _configure_frozen_inputs(tmp_path, monkeypatch)
    manifest_sha = cli.EXPECTED_SAMPLE_MANIFEST_SHA256
    canary_receipt = {
        "schema": "v4.pdf_research_v3.canary_review.v1",
        "status": "PASS",
        "reviewer": "independent-reviewer",
        "sample_id": "S01",
        "sample_manifest_sha256": manifest_sha,
        "result_sha256": "c" * 64,
    }
    cli.CANARY_REVIEW_RECEIPT_PATH.write_text(json.dumps(canary_receipt), encoding="utf-8")
    with pytest.raises(cli.SampleCliError, match="REVIEW_RECEIPT_REQUIRED"):
        cli.build_execution_plan("SAMPLE", execute=False)
    acceptance = {
        "schema": "v4.pdf_research_v3.sample_acceptance.v1",
        "status": "ACCEPTED",
        "decision": "ACCEPTED",
        "sample_manifest_sha256": manifest_sha,
        "canary_result_sha256": canary_receipt["result_sha256"],
    }
    cli.SAMPLE_ACCEPTANCE_RECEIPT_PATH.write_text(json.dumps(acceptance), encoding="utf-8")
    plan = cli.build_execution_plan("SAMPLE", execute=False)
    assert plan["selected_document_ids"] == ["S01", "S02"]
    assert plan["selected_document_count"] == 2


def test_execute_stops_before_model_request_without_source_review_receipt(tmp_path, monkeypatch) -> None:
    _configure_frozen_inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(
        local_document_model,
        "request_document_analysis",
        lambda **_kwargs: pytest.fail("model request reached before source-review gate"),
    )
    with pytest.raises(cli.SampleCliError, match="REVIEW_RECEIPT_REQUIRED"):
        cli.execute_sample("CANARY")


def test_execute_requires_separate_frozen_scope_before_any_research_write(tmp_path, monkeypatch) -> None:
    _configure_frozen_inputs(tmp_path, monkeypatch)
    source_receipt = {
        "schema": "v4.pdf_research_v3.source_review.v1",
        "status": "PASS",
        "reviewer": "independent-reviewer",
        "scope_sha256": cli.EXPECTED_SCOPE_SHA256,
        "reviewed_files": cli._reviewed_files(),
    }
    cli.SOURCE_REVIEW_RECEIPT_PATH.write_text(json.dumps(source_receipt), encoding="utf-8")

    monkeypatch.setattr(local_document_model, "require_runtime_python", lambda: None)
    monkeypatch.setattr(
        local_document_model,
        "build_request_material",
        lambda _schema: {"configuration_sha256": "c" * 64, "request_schema_sha256": "d" * 64},
    )
    monkeypatch.setattr(local_document_model, "inspect_local_api_identity", lambda: {"status": "MATCH"})
    writes: list[str] = []
    queues: list[bool] = []
    monkeypatch.setattr(pdf_research, "_atomic_private_json", lambda path, *_args, **_kwargs: writes.append(str(path)))
    monkeypatch.setattr(pdf_research, "create_pdf_queue", lambda: queues.append(True) or object())
    monkeypatch.setattr(pdf_research, "analyze_document", lambda document, **_kwargs: {"document_id": document["document_id"]})
    monkeypatch.setattr(pdf_research, "persist_document_result", lambda *_args, **_kwargs: None)

    with pytest.raises(cli.SampleCliError, match="EXECUTION_SCOPE_REQUIRED"):
        cli.execute_sample("CANARY")

    assert writes == []
    assert queues == []


def test_frozen_unchanged_identity_allows_only_bounded_s01_path_without_completion(tmp_path, monkeypatch) -> None:
    _configure_frozen_inputs(tmp_path, monkeypatch)
    frozen = _write_execution_authorization(tmp_path, monkeypatch)
    monkeypatch.setattr(local_document_model, "require_runtime_python", lambda: None)
    monkeypatch.setattr(local_document_model, "build_request_material", lambda _schema: dict(frozen["binding"]))
    api_checks: list[bool] = []
    monkeypatch.setattr(local_document_model, "inspect_local_api_identity", lambda: api_checks.append(True) or {"status": "MATCH"})
    research_writes: list[str] = []
    queue_creations: list[bool] = []
    analyzed: list[str] = []
    monkeypatch.setattr(pdf_research, "_atomic_private_json", lambda path, *_args, **_kwargs: research_writes.append(str(path)))
    monkeypatch.setattr(pdf_research, "create_pdf_queue", lambda: queue_creations.append(True) or object())

    def analyze(document, **kwargs):
        kwargs["binding_guard"]()
        assert kwargs["maximum_model_calls"] == cli.CANARY_MAX_MODEL_CALLS
        assert kwargs["selected_chunk_indices"] == [1]
        assert kwargs["accepted_prior_chunks"] == {}
        analyzed.append(document["document_id"])
        return {"document_id": document["document_id"]}

    monkeypatch.setattr(pdf_research, "analyze_document", analyze)
    monkeypatch.setattr(pdf_research, "persist_document_result", lambda *_args, **_kwargs: None)

    results = cli.execute_sample("CANARY")

    assert [row["document_id"] for row in results] == ["S01"]
    assert analyzed == ["S01"]
    assert queue_creations == [True]
    assert len(research_writes) == 1
    assert api_checks == [True]


def test_execution_scope_requires_first_chunk_acceptance_before_continuation(tmp_path, monkeypatch) -> None:
    _configure_frozen_inputs(tmp_path, monkeypatch)
    authorization = _write_execution_authorization(tmp_path, monkeypatch)
    _scope, scope_sha, manifest_sha, documents = cli.load_frozen_documents("CANARY")
    acceptance = {
        "schema": "v4.pdf_research_v3.chunk_acceptance.v1",
        "status": "PASS",
        "reviewer": "independent-reviewer",
        "sample_id": "S01",
        "sample_manifest_sha256": manifest_sha,
        "scope_sha256": scope_sha,
        "source_review_receipt_sha256": _sha(cli.SOURCE_REVIEW_RECEIPT_PATH),
        "runtime_binding_evidence_sha256": _sha(cli.RUNTIME_BINDING_EVIDENCE_PATH),
        "chunk_index": 1,
        "chunk_sha256": "f" * 64,
        "chunk_id": "S01:0001:" + "f" * 64,
        "request_schema_sha256": local_document_model.sha256_bytes(
            local_document_model.canonical_json(pdf_research.V3_OUTPUT_SCHEMA)
        ),
        "source_sha256": documents[0]["pdf_sha256"],
        "idempotency_key": "a" * 64,
        "payload_sha256": "b" * 64,
        "raw_sha256": "c" * 64,
        "validated_sha256": "d" * 64,
    }
    cli.FIRST_CHUNK_ACCEPTANCE_RECEIPT_PATH.write_text(json.dumps(acceptance), encoding="utf-8")
    execution_scope = json.loads(cli.EXECUTION_SCOPE_RECEIPT_PATH.read_text(encoding="utf-8"))
    execution_scope["selected_chunk_indices"] = [2, 3]
    execution_scope["reusable_chunk_indices"] = [1]
    execution_scope["first_chunk_acceptance_receipt_sha256"] = _sha(cli.FIRST_CHUNK_ACCEPTANCE_RECEIPT_PATH)
    cli.EXECUTION_SCOPE_RECEIPT_PATH.write_text(json.dumps(execution_scope), encoding="utf-8")

    monkeypatch.setattr(local_document_model, "require_runtime_python", lambda: None)
    monkeypatch.setattr(local_document_model, "build_request_material", lambda _schema: dict(authorization["binding"]))
    monkeypatch.setattr(local_document_model, "inspect_local_api_identity", lambda: {"status": "MATCH"})
    monkeypatch.setattr(pdf_research, "_atomic_private_json", lambda *_args, **_kwargs: "source-manifest-sha")
    monkeypatch.setattr(pdf_research, "create_pdf_queue", lambda: object())
    captured: dict[str, object] = {}

    def analyze(document, **kwargs):
        captured["document_id"] = document["document_id"]
        captured["selected_chunk_indices"] = kwargs["selected_chunk_indices"]
        captured["accepted_prior_chunks"] = kwargs["accepted_prior_chunks"]
        return {"document_id": document["document_id"]}

    monkeypatch.setattr(pdf_research, "analyze_document", analyze)
    monkeypatch.setattr(pdf_research, "persist_document_result", lambda *_args, **_kwargs: None)

    assert cli.execute_sample("CANARY")[0]["document_id"] == "S01"
    assert captured["selected_chunk_indices"] == [2, 3]
    assert captured["accepted_prior_chunks"] == {1: {key: acceptance[key] for key in (
        "idempotency_key", "payload_sha256", "raw_sha256", "validated_sha256", "chunk_id", "chunk_index",
        "chunk_sha256", "request_schema_sha256", "source_sha256",
    )}}

    acceptance["request_schema_sha256"] = "e" * 64
    cli.FIRST_CHUNK_ACCEPTANCE_RECEIPT_PATH.write_text(json.dumps(acceptance), encoding="utf-8")
    with pytest.raises(cli.SampleCliError, match="FIRST_CHUNK_ACCEPTANCE_RECEIPT_SHA_MISMATCH"):
        cli.execute_sample("CANARY")


@pytest.mark.parametrize(
    "field,subfield",
    [
        ("runtime_settings_path", None),
        ("runtime_settings_sha256", None),
        ("model_settings_path", None),
        ("model_settings_sha256", None),
        ("runtime_limits", "drift_marker"),
        ("request_policy", "drift_marker"),
        ("configuration_sha256", None),
        ("runtime_python", None),
        ("source_sha256", "infrastructure/local_document_model.py"),
        ("source_sha256", "infrastructure/pdf_research.py"),
        ("source_sha256", "ops/run_pdf_research_sample.py"),
        *[("source_sha256", name) for name in local_document_model.PINNED_SOURCE_SHA256],
        ("source_sha256", "v4/manager_workbench/inputs/pdf_pages.py"),
    ],
)
def test_drift_from_frozen_settings_or_source_hash_fails_before_get_or_write(
    tmp_path, monkeypatch, field, subfield
) -> None:
    _configure_frozen_inputs(tmp_path, monkeypatch)
    frozen = _write_execution_authorization(tmp_path, monkeypatch)
    drifted = deepcopy(frozen["binding"])
    if field in {"runtime_limits", "request_policy"}:
        drifted[field][subfield] = "drift"
    elif subfield is None:
        drifted[field] = "f" * 64
    else:
        drifted[field][subfield] = "f" * 64
    monkeypatch.setattr(local_document_model, "require_runtime_python", lambda: None)
    monkeypatch.setattr(local_document_model, "build_request_material", lambda _schema: dict(drifted))
    api_checks: list[bool] = []
    monkeypatch.setattr(local_document_model, "inspect_local_api_identity", lambda: api_checks.append(True) or {"status": "MATCH"})
    writes: list[str] = []
    queues: list[bool] = []
    monkeypatch.setattr(pdf_research, "_atomic_private_json", lambda path, *_args, **_kwargs: writes.append(str(path)))
    monkeypatch.setattr(pdf_research, "create_pdf_queue", lambda: queues.append(True) or object())

    with pytest.raises(cli.SampleCliError, match="FROZEN_RUNTIME_BINDING_MISMATCH"):
        cli.execute_sample("CANARY")

    assert api_checks == []
    assert writes == []
    assert queues == []


def test_runtime_binding_is_rechecked_before_source_manifest_mutation(tmp_path, monkeypatch) -> None:
    _configure_frozen_inputs(tmp_path, monkeypatch)
    frozen = _write_execution_authorization(tmp_path, monkeypatch)
    changed = deepcopy(frozen["binding"])
    changed["model_settings_sha256"] = "f" * 64
    observations = iter((dict(frozen["binding"]), changed))
    monkeypatch.setattr(local_document_model, "require_runtime_python", lambda: None)
    monkeypatch.setattr(local_document_model, "build_request_material", lambda _schema: next(observations))
    monkeypatch.setattr(local_document_model, "inspect_local_api_identity", lambda: {"status": "MATCH"})
    writes: list[str] = []
    queues: list[bool] = []
    monkeypatch.setattr(pdf_research, "_atomic_private_json", lambda path, *_args, **_kwargs: writes.append(str(path)))
    monkeypatch.setattr(pdf_research, "create_pdf_queue", lambda: queues.append(True) or object())

    with pytest.raises(cli.SampleCliError, match="FROZEN_RUNTIME_BINDING_MISMATCH"):
        cli.execute_sample("CANARY")

    assert writes == []
    assert queues == []


def test_runtime_binding_is_rechecked_before_queue_creation(tmp_path, monkeypatch) -> None:
    _configure_frozen_inputs(tmp_path, monkeypatch)
    frozen = _write_execution_authorization(tmp_path, monkeypatch)
    changed = deepcopy(frozen["binding"])
    changed["runtime_settings_sha256"] = "f" * 64
    observations = iter((dict(frozen["binding"]), dict(frozen["binding"]), changed))
    monkeypatch.setattr(local_document_model, "require_runtime_python", lambda: None)
    monkeypatch.setattr(local_document_model, "build_request_material", lambda _schema: next(observations))
    monkeypatch.setattr(local_document_model, "inspect_local_api_identity", lambda: {"status": "MATCH"})
    writes: list[str] = []
    queues: list[bool] = []
    monkeypatch.setattr(pdf_research, "_atomic_private_json", lambda path, *_args, **_kwargs: writes.append(str(path)))
    monkeypatch.setattr(pdf_research, "create_pdf_queue", lambda: queues.append(True) or object())

    with pytest.raises(cli.SampleCliError, match="FROZEN_RUNTIME_BINDING_MISMATCH"):
        cli.execute_sample("CANARY")

    assert writes == [str(pdf_research.PDF_RESEARCH_STATE_ROOT / "source-manifests" / f"{cli.EXPECTED_SAMPLE_MANIFEST_SHA256}.json")]
    assert queues == []


def test_offline_or_runtime_drifted_execution_scope_fails_before_binding_read(tmp_path, monkeypatch) -> None:
    _configure_frozen_inputs(tmp_path, monkeypatch)
    _write_execution_authorization(tmp_path, monkeypatch)
    receipt = json.loads(cli.EXECUTION_SCOPE_RECEIPT_PATH.read_text(encoding="utf-8"))
    receipt["execution_phase"] = "V3_IMPLEMENTATION_OFFLINE_FIRST"
    receipt["expected_runtime_identity"]["runtime_settings_sha256"] = "f" * 64
    cli.EXECUTION_SCOPE_RECEIPT_PATH.write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(
        local_document_model,
        "build_request_material",
        lambda _schema: pytest.fail("invalid execution scope must fail before runtime inspection"),
    )

    with pytest.raises(cli.SampleCliError, match="EXECUTION_SCOPE_MISMATCH"):
        cli.execute_sample("CANARY")


def test_runtime_binding_capture_cannot_replace_accepted_frozen_evidence() -> None:
    with pytest.raises(cli.SampleCliError, match="RUNTIME_BINDING_CAPTURE_DISABLED_AFTER_FREEZE"):
        cli.capture_runtime_binding()

