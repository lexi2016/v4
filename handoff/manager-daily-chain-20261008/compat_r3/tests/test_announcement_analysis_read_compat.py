from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_APP = ROOT / "candidate_app"
R2_APP = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/manager-daily-chain-20261008-r2-api/app")
sys.path.insert(0, str(R2_APP))
sys.path.insert(0, str(CANDIDATE_APP))

from apps.api.v35_api.manager_research_router import create_manager_research_router  # noqa: E402
from v4.manager_research import announcement_analysis as analysis  # noqa: E402
from v4.manager_research import announcement_selection as selection  # noqa: E402
from v4.manager_research.workspace_projection import digest  # noqa: E402

FIXTURES = ROOT / "preimage" / "fixtures"
LEGACY_PRODUCT_PATH = FIXTURES / "legacy_analysis_20261007_20261006.json"
LEGACY_CATALOG_PATH = FIXTURES / "legacy_catalog_20261007_20261006.json"
LEGACY_PRODUCT_SHA256 = "7b27fe7d40e9c12db3d56751cc789c6eb84515bb2392fc1b00a3bc4a5fd38278"
LEGACY_PRODUCT_FILE_SHA256 = "4f3a44b730a6476482f4a85402c9d9ee830b0e32f21b31a6d1e72abacce2d485"
LEGACY_CATALOG_FILE_SHA256 = "f89ac52a93c54771722a78ef52169f1405814c54d5ed91da2842fcbc748a1123"
TARGET = "20261007"
PUBLICATION = "2026-10-06"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _legacy_product() -> dict[str, Any]:
    raw = LEGACY_PRODUCT_PATH.read_bytes()
    assert _sha(raw) == LEGACY_PRODUCT_FILE_SHA256
    product = json.loads(raw)
    assert product["sha256"] == LEGACY_PRODUCT_SHA256
    return product


def _catalog_read() -> dict[str, Any]:
    raw = LEGACY_CATALOG_PATH.read_bytes()
    assert _sha(raw) == LEGACY_CATALOG_FILE_SHA256
    catalog = json.loads(raw)
    return {
        "schema_version": "v4.manager_research.eastmoney_hk_date_catalog_read.v1",
        "target_trade_date": TARGET,
        "publication_date": PUBLICATION,
        "source_scope": "EASTMONEY_HK_DATE_CATALOG",
        "status": "COMPLETE",
        "readback_status": "VERIFIED",
        "catalog": catalog,
        "gaps": catalog.get("gaps", []),
    }


class _Store:
    root = Path("/read-only/manager-research-test")

    def __init__(self, product: dict[str, Any]):
        self.product = product

    def _read(self, path: Path) -> dict[str, Any] | None:
        if path.name == "analysis.v1.json":
            return deepcopy(self.product)
        return None


class _Service:
    def __init__(self, product: dict[str, Any]):
        self.store = _Store(product)
        self.catalog = _catalog_read()

    def get_announcement_date_catalog(self, target: str, publication: str):
        if (target, publication) == (TARGET, PUBLICATION):
            return self.catalog
        return {"status": "NOT_RUN", "readback_status": "NOT_RUN", "catalog": None, "gaps": []}

    def get_announcement_analysis(self, target: str, publication: str | None = None):
        return analysis.read(self, target, publication)


def _with_selection_extension(product: dict[str, Any], *, agent_receipt: bool,
                              row_markers: bool, selected_gap: bool = False) -> dict[str, Any]:
    base = deepcopy(product)
    old_extension = base.pop("stock_selection")
    decisions = deepcopy(old_extension["article_decisions"])
    base.pop("sha256")
    if agent_receipt:
        # Presence is the generation boundary checked by this validator; route
        # handoff validation separately verifies the signed receipt contents.
        base["agent_judgment_receipt"] = {"schema_version": "fixture.agent_judgment_receipt.v1"}
    if row_markers:
        for record in base["records"]:
            if analysis.has_reader_declared_content_gap(record):
                record["selection_status"] = "NOT_ASSESSED"
    if selected_gap:
        gap_code = next(record["art_code"] for record in base["records"]
                        if analysis.has_reader_declared_content_gap(record))
        decision = next(row for row in decisions if row["art_code"] == gap_code)
        decision["disposition"] = "SELECTED_EVENT"
        decision["selection_basis"] = "OPERATING_EVENT"
        decision["reason"] = "Deliberately invalid test disposition for reader-gap article."
    base["sha256"] = digest(base)
    extension = selection.make_extension(base, decisions)
    return selection.attach_extension(base, extension)


def test_old_product_api_readback_preserves_original_product_identity_and_decisions():
    raw_before = LEGACY_PRODUCT_PATH.read_bytes()
    product = _legacy_product()
    service = _Service(product)
    app = FastAPI()
    app.include_router(create_manager_research_router(service))

    with TestClient(app) as client:
        response = client.get(
            "/api/v4/manager/research/announcements/analysis",
            params={"date": TARGET, "publication_date": PUBLICATION},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["analysis"]["status"] == "VERIFIED"
    assert body["analysis"]["product_sha256"] == LEGACY_PRODUCT_SHA256
    assert body["owner_import_receipt"] is None
    assert len(body["analysis"]["records"]) == 580
    gaps = [row for row in body["analysis"]["records"]
            if analysis.has_reader_declared_content_gap(row)]
    assert len(gaps) == 40
    decisions = {row["art_code"]: row["disposition"]
                 for row in body["analysis"]["stock_selection"]["article_decisions"]}
    assert all(decisions[row["art_code"]] == "NOT_ASSESSED" for row in gaps)
    assert LEGACY_PRODUCT_PATH.read_bytes() == raw_before
    assert _sha(raw_before) == LEGACY_PRODUCT_FILE_SHA256


def test_new_agent_judged_gap_product_still_requires_row_level_marker():
    product = _with_selection_extension(_legacy_product(), agent_receipt=True, row_markers=False)
    with pytest.raises(ValueError, match="ANNOUNCEMENT_ANALYSIS_READER_CONTENT_GAP_PROJECTION_INVALID"):
        analysis.validate_product(product, target_trade_date=TARGET,
                                  publication_date=PUBLICATION, catalog=_catalog_read()["catalog"])


def test_new_agent_judged_gap_product_with_marker_remains_valid():
    product = _with_selection_extension(_legacy_product(), agent_receipt=True, row_markers=True)
    checked = analysis.validate_product(product, target_trade_date=TARGET,
                                         publication_date=PUBLICATION, catalog=_catalog_read()["catalog"])
    assert checked["sha256"] == product["sha256"]
    assert all(row["selection_status"] == "NOT_ASSESSED" for row in checked["records"]
               if analysis.has_reader_declared_content_gap(row))


def test_legacy_compatibility_does_not_allow_selected_reader_gap():
    product = _with_selection_extension(_legacy_product(), agent_receipt=False,
                                        row_markers=False, selected_gap=True)
    with pytest.raises(ValueError,
                       match="ANNOUNCEMENT_ANALYSIS_UNASSESSED_CONTENT_SELECTION_MUST_BE_NOT_ASSESSED"):
        analysis.validate_product(product, target_trade_date=TARGET,
                                  publication_date=PUBLICATION, catalog=_catalog_read()["catalog"])
