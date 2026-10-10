"""Synthetic inputs, real existing builder, product validators and owner routes.

This file does not reproduce the 33 historical securities or claim Mac/live
acceptance. Fixtures reuse the original source-backed handoff test helper.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import selection_reuse_fixture as fixture
from ops import run_manager_daily_announcement as cli
from v4.manager_research import announcement_analysis as analysis
from v4.manager_research import announcement_selection as selection
from v4.manager_research import workspace_announcements as consumer
from v4.manager_research.workspace_projection import FLAGS, digest

TARGET = "20261009"
PUBLICATION = "2026-10-08"
NOW = datetime(2026, 10, 9, 1, tzinfo=timezone.utc)


@pytest.fixture
def source(tmp_path, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(fixture, "NOW", NOW)
    monkeypatch.setattr(fixture.api, "datetime", Clock)
    monkeypatch.setattr(consumer, "_now", lambda: NOW.isoformat())
    service = fixture._FixtureService(tmp_path / "owner-state")
    yield service
    service.close()


def registered_inputs(service, **options):
    product, registration = fixture._fixture(service, target=TARGET,
        publication=PUBLICATION, listing_at="2026-10-08T21:00:00+00:00",
        body_at="2026-10-08T21:01:00+00:00",
        reviewed_at="2026-10-09T00:00:00+00:00", **options)
    evidence = service.store.root / "announcement_agent_runs" / registration["evidence_run_id"] / "evidence"
    receipt = service.store.root / "supplied_review_receipt.json"
    receipt.write_text(json.dumps(product["agent_judgment_receipt"]))
    args = SimpleNamespace(target_date=TARGET, publication_date=PUBLICATION,
        catalog_read=str(evidence / "catalog_read.json"),
        semantic_catalog=str(evidence / "semantic_catalog.json"),
        body_corpus=str(evidence / "body_corpus.json"),
        decisions=None if options.get("no_decisions") else str(evidence / "article_decisions.json"),
        review_receipt=str(receipt), out=str(service.store.root / "rebuilt_candidate.json"))
    args.terminal_capture = consumer.validate_terminal_body_capture(evidence,
        service.catalogs[(TARGET, PUBLICATION)], TARGET, PUBLICATION,
        expected_run_id=registration["evidence_run_id"])
    return product, registration, args


@pytest.mark.parametrize("options,selected,watch,pending", [
    ({}, 1, 0, 0),
    ({"disposition": "CONDITIONAL_WATCH"}, 0, 1, 0),
    ({"disposition": "NOT_SELECTED"}, 0, 0, 0),
    ({"reader_gap": True}, 0, 0, 1),
    ({"no_decisions": True}, None, None, None),
])
def test_reviewed_build_reuses_registered_identity(source, options, selected, watch, pending):
    original, _, args = registered_inputs(source, **options)
    built = cli._build(args, reviewed=True, include_product=True,
        terminal_body_capture=args.terminal_capture)["product"]
    # These are the original production validators, not test replicas.
    projection = selection.read_projection(built)
    analysis.validate_product(built, target_trade_date=TARGET,
        publication_date=PUBLICATION, catalog=source.catalogs[(TARGET, PUBLICATION)]["catalog"])
    consumer.validate_agent_judgment_receipt(built["agent_judgment_receipt"], built)
    assert built == original
    assert projection["selected_stock_count"] == selected
    assert projection["conditional_watch_count"] == watch
    assert projection["not_assessed_stock_count"] == pending
    assert json.loads(Path(args.out).read_text()) == built
    before = Path(args.out).read_bytes()
    assert cli._build(args, reviewed=True,
        terminal_body_capture=args.terminal_capture)["product_sha256"] == built["sha256"]
    assert Path(args.out).read_bytes() == before
    for key, value in FLAGS.items():
        assert built[key] is value


def test_rebuilt_exact_product_survives_original_api_and_repeated_workspace_reads(source):
    original, registration, args = registered_inputs(source)
    built = cli._build(args, reviewed=True, include_product=True,
        terminal_body_capture=args.terminal_capture)["product"]
    # The existing registered handoff remains the authority for import. A
    # build-reviewed file alone cannot bypass the registration/review gate.
    assert built == original
    fixture._fixture(source, run_id="2" * 32)
    historical_root = source.store.root / "announcement_agent_runs" / ("2" * 32)
    before_historical = fixture._snapshot(historical_root)
    assert before_historical
    with fixture._client(source) as client:
        imported = fixture._import(client, registration)
        assert imported["consumption_validation"]["product_sha256"] == built["sha256"]
        before_reads = fixture._snapshot(source.store.root)
        params = {"date": TARGET, "view": "dynamic", "selection_date": TARGET,
            "announcement_date": "20261008"}
        for _ in range(2):
            response = client.get("/api/v4/manager/research/workspace", params=params)
            assert response.status_code == 200, response.text
            value = response.json()
            channel = value["daily_channels"]["channels"][0]
            assert channel["status"] == "READY"
            assert channel["candidate_count"] == 1
            assert channel["product_sha256"] == built["sha256"]
            assert channel["rows"][0]["symbol"] == "HK.01234"
            assert channel["rows"][0]["target_trade_date"] == TARGET
            assert channel["rows"][0]["data_date"] == "20261008"
            assert channel["rows"][0]["reason"] == "Synthetic fixture disposition only."
        assert fixture._snapshot(source.store.root) == before_reads
    assert fixture._snapshot(historical_root) == before_historical


@pytest.mark.parametrize("field,value", [
    ("target_date", "20261008"), ("publication_date", "2026-10-07"),
])
def test_other_date_inputs_rejected_before_output(source, field, value):
    _, _, args = registered_inputs(source)
    setattr(args, field, value)
    with pytest.raises(ValueError, match="ANNOUNCEMENT_DAILY_CATALOG_DATE_OR_READBACK_MISMATCH"):
        cli._build(args, reviewed=True)
    assert not Path(args.out).exists()


def test_resealed_wrong_source_receipt_rejected_before_output(source):
    _, _, args = registered_inputs(source)
    receipt = json.loads(Path(args.review_receipt).read_text())
    receipt["semantic_catalog_sha256"] = "f" * 64
    receipt.pop("sha256")
    receipt["sha256"] = digest(receipt)
    Path(args.review_receipt).write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="ANNOUNCEMENT_AGENT_JUDGMENT_RECEIPT_BINDING_INVALID"):
        cli._build(args, reviewed=True)
    assert not Path(args.out).exists()


def test_different_existing_output_is_not_overwritten(source):
    _, _, args = registered_inputs(source)
    Path(args.out).write_text('{"existing": "preserve"}\n')
    before = Path(args.out).read_bytes()
    with pytest.raises(ValueError, match="ANNOUNCEMENT_CANDIDATE_OUTPUT_EXISTS_WITH_DIFFERENT_CONTENT"):
        cli._build(args, reviewed=True)
    assert Path(args.out).read_bytes() == before
