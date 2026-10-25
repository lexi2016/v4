"""Focused regressions for the five frozen announcement repair findings."""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ops import manager_announcement_body_batch as body_batch
from ops import run_manager_daily_announcement as daily_runner
from v4.manager_research import announcement_analysis, workspace, workspace_announcements
from v4.manager_research.workspace_projection import FLAGS, HK, digest


class _OfflineGate:
    def __init__(self, **_kwargs):
        self.elapsed_seconds = 0.0

    def set_response_limits(self, *, per_response: int, total: int) -> None:
        self.per_response = per_response
        self.total = total

    def snapshot(self) -> dict[str, int | float]:
        return {
            "physical_requests": 0,
            "physical_response_bytes": 0,
            "receipt_cache_hits": 0,
            "material_cache_hits": 0,
        }


def _run_offline_body_capture(monkeypatch, output: Path, *, eligible_documents=(),
                              hkex_eligibility=(), hkex_error: Exception | None = None):
    target, publication = "20261023", "2026-10-23"
    monthly = {
        "source_date": "20261001",
        "capture_cutoff_at": "2026-10-23T08:00:00+08:00",
        "code_count": 1,
        "codes_sha256": "a" * 64,
    }
    readback = {"fixture": "offline HKEX owner readback"}
    api = {
        "MaterialStore": lambda root: SimpleNamespace(root=root),
        "HkexOfficialProvider": lambda **_kwargs: object(),
        "MAX_EASTMONEY_RESPONSE_BYTES": 1024,
        "safe_reason": lambda _exc, fallback: fallback,
        "read_response": lambda *_args: (_ for _ in ()).throw(OSError("offline fixture")),
    }
    monkeypatch.setattr(body_batch, "imports", lambda: dict(api))
    monkeypatch.setattr(body_batch, "_validate_catalog", lambda *_args: [])
    monkeypatch.setattr(body_batch, "_catalog_product", lambda _readback: {
        "run_id": "c" * 32, "sha256": "d" * 64,
    })
    monkeypatch.setattr(body_batch, "_verified_monthly_connect_eligibility",
        lambda *_args: (set(), "e" * 64))
    monkeypatch.setattr(body_batch, "_verified_hkex_directory_readback",
        lambda *_args: ({"f" * 32}, list(eligible_documents)))
    monkeypatch.setattr(body_batch, "_apply_monthly_connect_eligibility",
        lambda *_args: ([], [], list(eligible_documents), list(hkex_eligibility)))
    monkeypatch.setattr(body_batch, "SharedCaptureGate", _OfflineGate)
    if hkex_error is not None:
        def fail_hkex_capture(*_args):
            raise hkex_error
        monkeypatch.setattr(body_batch, "_capture_hkex_variant", fail_hkex_capture)
    return body_batch.run_capture(
        {"catalog": {"run_id": "c" * 32, "sha256": "d" * 64}},
        output.parent / "materials", output, target, publication,
        hkex_directory_readback=readback,
        monthly_connect_eligibility=monthly,
    )


def test_hkex_capture_exception_writes_terminal_receipt_with_publication_date(
        monkeypatch, tmp_path):
    doc = {
        "news_id": "12345678", "symbol": "HK.02665", "title": "Fixture notice",
        "directory_ref": {"fixture": "local-only"}, "source_url": "https://example.invalid/notice",
    }

    result = _run_offline_body_capture(monkeypatch, tmp_path / "hkex-failure",
        eligible_documents=[doc], hkex_error=RuntimeError("fixture capture failure"))

    receipt = body_batch.read_json(tmp_path / "hkex-failure" / "batch_receipt.json")
    variant = receipt["hkex_official_supplement"]["body_status_counts"]
    artifact = body_batch.read_json(tmp_path / "hkex-failure" / "official_variants" / "12345678.json")
    assert result["status"] == "PARTIAL_BODY_MATERIAL_CAPTURE_WITH_TERMINAL_GAPS"
    assert receipt["status"] == result["status"]
    assert variant == {"HKEX_BODY_CAPTURE_FAILED": 1}
    assert artifact["publication_date"] == "2026-10-23"
    assert artifact["body_status"] == "HKEX_BODY_CAPTURE_FAILED"


def test_em_only_complete_reuse_uses_validated_monthly_snapshot(monkeypatch, tmp_path):
    target, publication = "20261023", "2026-10-23"
    source_id, derived_id = "a" * 32, "b" * 32
    state_root = tmp_path / "state"
    source_root = state_root / "announcement_agent_runs" / source_id / "evidence"
    source_root.mkdir(parents=True)
    run_root = state_root / "announcement_agent_runs"

    monthly_source = {
        "market": "HK_CONNECT", "role": "HK_CONNECT_FULL_MARKET_AUTHORITY",
        "source_date": "20261001", "available_at": "2026-10-01T09:00:00+08:00",
        "artifact_ref": "authority/artifact.json", "manifest_ref": "authority/manifest.json",
        "receipt_ref": "authority/receipt.json", "current_ref": "authority/current.json",
        "capture_ref": "authority/capture.json", "publication_ref": "authority/publication.json",
        "sha256": "1" * 64, "capture_sha256": "2" * 64, "source_sha256": "3" * 64,
    }
    refs = ("artifact_ref", "manifest_ref", "receipt_ref", "current_ref", "capture_ref", "publication_ref")
    codes = ["HK.02665"]
    monthly = {
        "schema_version": "v4.manager_research.hk_connect_monthly_eligibility.v1",
        "status": "VERIFIED", "policy": "CALENDAR_MONTH_LATEST_VERIFIED_V2",
        "month": "202610", "target_trade_date": target, "source_date": "20261001",
        "capture_cutoff_at": "2026-10-23T08:00:00+08:00", "source": monthly_source,
        "authority_file_sha256s": {key: "4" * 64 for key in refs},
        "code_count": 1,
        "codes_sha256": hashlib.sha256(json.dumps(codes, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest(),
        "codes": codes, "invalid_newer_candidates": [], **FLAGS,
    }
    monthly["identity_sha256"] = hashlib.sha256(json.dumps(monthly, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    catalog = {"run_id": "c" * 32, "sha256": "d" * 64}
    article_id = "AN202610230001"
    semantic_record = {"art_code": article_id, "classification": "BUSINESS_EVENT"}
    decision_record = {"art_code": article_id, "decision": "REVIEW_PENDING"}
    catalog_read = {"catalog": catalog, "target_trade_date": target, "publication_date": publication}
    body = {
        "rows": [{"art_code": article_id, "source": "EASTMONEY_HK", "title": "Fixture"}],
    }
    body_manifest = {"article_receipts": [{"art_code": article_id,
        "body_status": "COMPLETE_CONTENT_API_BODY"}]}
    capture = {"evidence_run_id": source_id, "target_trade_date": target,
        "publication_date": publication, "catalog_run_id": catalog["run_id"],
        "catalog_product_sha256": catalog["sha256"]}
    batch = {"started_at": "2026-10-23T08:01:00+08:00", "terminal_at": "2026-10-23T08:02:00+08:00"}
    source_documents = {
        "catalog_read.json": catalog_read,
        "body_corpus.json": body,
        "body_corpus_manifest.json": body_manifest,
        "body_batch_receipt.json": batch,
        "capture_receipt.json": capture,
        "monthly_connect_eligibility.json": monthly,
        "hkex_directory_read.json": {"fixture": "unused by EM-only projection"},
    }
    for name, value in source_documents.items():
        (source_root / name).write_text(json.dumps(value), encoding="utf-8")

    review_root = tmp_path / "review-inputs"
    review_root.mkdir()
    semantic_path = review_root / "semantic.json"
    decision_path = review_root / "decisions.json"
    binding_path = review_root / "binding.json"
    semantic = {"records": [semantic_record], "target_trade_date": target,
        "target_notice_date": publication}
    decisions = {"records": [decision_record], "target_trade_date": target,
        "publication_date": publication}
    semantic_path.write_text(json.dumps(semantic), encoding="utf-8")
    decision_path.write_text(json.dumps(decisions), encoding="utf-8")
    semantic_parent = review_root / "semantic-parent.json"
    decision_parent = review_root / "decision-parent.json"
    semantic_parent.write_text(json.dumps(semantic), encoding="utf-8")
    decision_parent.write_text(json.dumps(decisions), encoding="utf-8")
    body_source = source_root / "body_corpus.json"

    def file_sha(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    binding = {
        "schema_version": "v4.manager_research.announcement_em_subset_binding_receipt.v1",
        "status": "DERIVED_REUSED_FACTS_PENDING_SUBSET_REVIEW",
        "scope": {"partition": "EASTMONEY_ONLY", "target_trade_date": target,
            "publication_date": publication, "hkex_records_included": 0},
        "source_inputs": {
            "semantic_catalog_r7": {"path": str(semantic_parent.resolve()),
                "sha256": file_sha(semantic_parent)},
            "decisions_r8": {"path": str(decision_parent.resolve()),
                "sha256": file_sha(decision_parent)},
            "eastmoney_body_corpus": {"path": str(body_source.resolve()),
                "sha256": file_sha(body_source)},
        },
        "output_artifacts": {
            "semantic_subset": {"path": str(semantic_path.resolve()),
                "sha256": file_sha(semantic_path), "record_count": 1},
            "rule_subset": {"path": str(decision_path.resolve()),
                "sha256": file_sha(decision_path), "record_count": 1},
        },
    }
    binding_path.write_text(json.dumps(binding), encoding="utf-8")

    monthly_validated = []
    def validate_source(root, _catalog_read, validated_target, validated_publication,
                        *, expected_run_id=None):
        assert root == source_root
        assert (validated_target, validated_publication, expected_run_id) == (target, publication, source_id)
        loaded_monthly = json.loads((root / "monthly_connect_eligibility.json").read_text())
        body_batch._verified_monthly_connect_eligibility(loaded_monthly, publication)
        monthly_validated.append(loaded_monthly)
        return {
            "article_count": 1,
            "body_status_counts": {"COMPLETE_CONTENT_API_BODY": 1},
            "monthly_connect_eligibility_identity_sha256": loaded_monthly["identity_sha256"],
            "monthly_connect_eligibility": loaded_monthly,
        }

    monkeypatch.setattr(daily_runner, "_assert_catalog_readback", lambda *_args: dict(catalog))
    monkeypatch.setattr(daily_runner, "validate_terminal_body_capture", validate_source)
    args = SimpleNamespace(
        target_date=target, publication_date=publication,
        source_evidence_run_id=source_id, derived_evidence_run_id=derived_id,
        research_state_root=str(state_root), semantic_catalog=str(semantic_path),
        decisions=str(decision_path), subset_binding_receipt=str(binding_path),
    )

    result = daily_runner._prepare_em_only_reuse(args)

    derived_body = run_root / derived_id / "evidence" / "body_corpus.json"
    reused_body = json.loads(derived_body.read_text(encoding="utf-8"))
    assert result["status"] == "SOURCE_REUSE_PREPARED_PENDING_SUBSET_REVIEW"
    assert monthly_validated == [monthly]
    assert reused_body["monthly_connect_eligibility"] == monthly
    assert result["metrics"]["provider_http_requests"] == 0
    assert result["metrics"]["llm_inference_count"] == 0


def test_unresolved_hkex_identity_is_persisted_as_partial_batch_status(monkeypatch, tmp_path):
    result = _run_offline_body_capture(monkeypatch, tmp_path / "unresolved-hkex",
        hkex_eligibility=[{"status": "UNRESOLVED"}])

    persisted = body_batch.read_json(tmp_path / "unresolved-hkex" / "batch_receipt.json")
    assert result["status"] == "PARTIAL_BODY_MATERIAL_CAPTURE_WITH_TERMINAL_GAPS"
    assert persisted["status"] == result["status"]
    assert persisted["hkex_official_supplement"]["unresolved_source_identity_gap"] is True


def test_current_day_auto_include_saved_reuses_matching_sealed_cutoff(monkeypatch, tmp_path):
    target = "20261024"
    publication = "2026-10-23"
    bindings = {"plan_date": target, "selection_date": target, "announcement_date": "20261023"}
    sealed_context = {"plan_trade_date": target,
        "research_cutoff": "2026-10-24T09:30:00+08:00", "market_session": "20261023"}
    saved_workspace = {"target_trade_date": target, "input_identity": "f" * 64,
        "date_bindings": bindings, "plan_context": sealed_context}
    saved = {
        "schema_version": workspace.PLAN_SCHEMA,
        "target_trade_date": target, "run_id": "1" * 32,
        "generated_at": "2026-10-24T01:31:00+00:00",
        "owner": "ManagerResearchJobService.refresh_workspace_plan",
        "input_identity": saved_workspace["input_identity"],
        "workspace": saved_workspace, **FLAGS,
    }
    saved["sha256"] = digest(saved)
    store_root = tmp_path / "store"
    store_root.mkdir()

    class _Store:
        root = store_root

        def _read(self, path):
            return saved if Path(path).name == "latest.json" else None

    service = SimpleNamespace(store=_Store())
    monkeypatch.setattr(announcement_analysis, "previous_hk_session", lambda _date: publication.replace("-", ""))
    monkeypatch.setattr(workspace, "plan_context",
        lambda *_args, **_kwargs: pytest.fail("matched saved plan must not fall back to current time"))
    observed = []

    def compute(_service, date, *, include_saved, context):
        observed.append(dict(context))
        return {"target_trade_date": date, "plan_context": dict(context), "stocks": [], "gaps": []}

    monkeypatch.setattr(workspace, "_compute_workspace", compute)
    monkeypatch.setattr(workspace, "_readback_plan", lambda _store, _date, current, **_kwargs: current)
    monkeypatch.setattr(workspace, "_attach_daily_channels", lambda value: value)

    result = workspace.get_workspace(
        service, target, include_saved=True, view="auto",
        now=datetime(2026, 10, 24, 11, 0, tzinfo=HK),
        selection_date=target, announcement_date=publication,
    )

    assert observed == [sealed_context]
    assert result["date_bindings"] == bindings
    assert result["read_context"]["as_of"] == sealed_context["research_cutoff"]


def _saved_plan_for_workspace(target, bindings, sealed_context):
    saved_workspace = {"target_trade_date": target, "input_identity": "f" * 64,
        "date_bindings": bindings, "plan_context": sealed_context}
    saved = {
        "schema_version": workspace.PLAN_SCHEMA,
        "target_trade_date": target, "run_id": "1" * 32,
        "generated_at": "2026-10-24T01:31:00+00:00",
        "owner": "ManagerResearchJobService.refresh_workspace_plan",
        "input_identity": saved_workspace["input_identity"],
        "workspace": saved_workspace, **FLAGS,
    }
    saved["sha256"] = digest(saved)
    return saved


@pytest.mark.parametrize("saved_bindings,saved_context,case", [
    (
        {"plan_date": "20261024", "selection_date": "20261024", "announcement_date": "20261022"},
        {"plan_trade_date": "20261024", "research_cutoff": "2026-10-24T09:30:00+08:00",
         "market_session": "20261023"},
        "announcement_date_binding_mismatch",
    ),
    (
        {"plan_date": "20261024", "selection_date": "20261024", "announcement_date": "20261023"},
        {"plan_trade_date": "20261024", "research_cutoff": "not-a-timestamp",
         "market_session": "20261023"},
        "invalid_saved_context",
    ),
], ids=lambda value: value if isinstance(value, str) else None)
def test_current_day_auto_include_saved_fails_closed_without_clock_fallback(
        monkeypatch, tmp_path, saved_bindings, saved_context, case):
    target = "20261024"
    publication = "2026-10-23"
    bindings = {"plan_date": target, "selection_date": target,
        "announcement_date": "20261023"}
    saved = _saved_plan_for_workspace(target, saved_bindings, saved_context)
    store_root = tmp_path / case
    store_root.mkdir()

    class _Store:
        root = store_root

        def _read(self, path):
            return saved if Path(path).name == "latest.json" else None

    service = SimpleNamespace(store=_Store())
    monkeypatch.setattr(announcement_analysis, "previous_hk_session",
        lambda _date: publication.replace("-", ""))
    monkeypatch.setattr(workspace, "plan_context",
        lambda *_args, **_kwargs: pytest.fail("must not fall back to current clock"))
    monkeypatch.setattr(workspace, "_compute_workspace",
        lambda *_args, **_kwargs: pytest.fail("must not compute from an unbound context"))
    monkeypatch.setattr(workspace, "_attach_daily_channels", lambda value: value)

    with pytest.raises(ValueError, match="^WORKSPACE_STORED_PLAN_INVALID$"):
        workspace.get_workspace(
            service, target, include_saved=True, view="auto",
            now=datetime(2026, 10, 24, 11, 0, tzinfo=HK),
            selection_date=target, announcement_date=publication,
        )


def test_complete_publication_day_accepts_next_midnight_and_rejects_invalid_bounds():
    date = "20261024"
    start = datetime.strptime(date, "%Y%m%d").replace(tzinfo=HK)
    end = start + timedelta(days=1)

    def product(window_end):
        return {"context": {
            "publication_window_mode": "HK_CALENDAR_DAY_V1",
            "publication_date": date,
            "publication_window_start": start.isoformat(),
            "publication_window_end_exclusive": window_end,
        }}

    assert workspace_announcements._product_covers_publication_day(product(end.isoformat()), date) is True
    assert workspace_announcements._product_covers_publication_day(
        product((end + timedelta(microseconds=1)).isoformat()), date) is False
    assert workspace_announcements._product_covers_publication_day(
        product((start - timedelta(microseconds=1)).isoformat()), date) is False
    assert workspace_announcements._product_covers_publication_day(product(None), date) is False
    assert workspace_announcements._product_covers_publication_day(
        product(end.replace(tzinfo=None).isoformat()), date) is False
