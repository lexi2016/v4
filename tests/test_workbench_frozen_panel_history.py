"""Exact frozen selector reads through the existing workbench HTTP router."""

import importlib.util
import json
import os
from pathlib import Path
import sys
from types import ModuleType

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pyarrow as pa
import pytest

from infrastructure import research_workbench_host as workbench
from ops import research_panel_logical as logical
from ops import research_storage_retention as retention


GEN17, GEN18 = "a" * 64, "b" * 64
ASOF, DAY = "2026-10-30", "2026-10-29"
SSE, BSE, UNKNOWN = "600809.SH", "920156.BJ", "920201.BJ"
PATH = f"/workbench/days/{ASOF}/single-research/{SSE}/archived-selector"


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return {"path": str(path), "sha256": retention.digest(path)}


def _write_panel(path, number, generation):
    previous_receipt = str(path.parent / f"unavailable_original_receipt_{number}.json")
    scope_ref = {"path": "/frozen/top200.json", "sha256": "c" * 64}
    scoped = dict(scope="TOP200_PARTIAL", scope_ref=scope_ref, source_generation="d" * 64)
    contract = dict(schema="a_share_qfq_panel_v1", generation_id=generation, asof_date=20261030,
        generation_manifest_path=previous_receipt, kb_scoped_upgrade=scoped, input_sha256="e" * 64,
        historical_PIT=False, market_basis={"A": {"asof_date": 20261030, "price_basis": "QFQ_ASOF",
        "volume_basis": "QFQ_EVENT_VOLUME", "amount_basis": "RAW_TURNOVER"}}, **workbench.FLAGS)
    table = pa.table({
        "ts_code": [SSE, BSE, SSE, UNKNOWN],
        "trade_date": (
            ["20261029", "20261029", "20261030", "20261029"] if number == 17
            else [20261029, 20261029, 20261030, 20261029]
        ),
        "market_type": ["A_SHARE", "BJ", "A_SHARE", "BJ"],
        "close": [126.27 if number == 17 else 120.15, 37.46, 128.44, 1.0],
        "kb_b1": pa.array([True, None, False, None], type=pa.bool_()),
    }).replace_schema_metadata({logical.META: json.dumps(contract).encode()})
    logical.physical.write_table(table, path, compression="NONE")
    return table, previous_receipt, scoped


@pytest.fixture
def archive(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    roster = [dict(symbol=SSE, status="REUSED", first_date=19940106),
              dict(symbol=BSE, status="UPDATED", first_date=20240101),
              dict(symbol=UNKNOWN, status="UNKNOWN", reason="TARGET_DIRECTORY_OMISSION_PENDING_SOURCE_ADMISSION")]
    roster.extend(dict(symbol=f"{index:06d}.SZ", status="UPDATED", first_date=20251001) for index in range(195))
    roster.extend(dict(symbol=symbol, status="UNKNOWN", reason="FIXTURE_UNKNOWN") for symbol in ("920196.BJ", "920298.BJ"))
    entries, tables = [], {}
    for number, generation in ((17, GEN17), (18, GEN18)):
        path = root / f"archived_selector_{number}.parquet"
        tables[number], planned_receipt, scoped = _write_panel(path, number, generation)
        digest = retention.digest(path)
        receipt = _write_json(root / f"receipt_{number}.json", dict(
            schema=f"qfq_scoped_kb_candidate.v{3 if number == 17 else 2}",
            generation_id=generation, historical_PIT=False,
            planned_receipt=planned_receipt, per_symbol=roster, candidate_sha256={"selector": digest},
            **scoped, **workbench.FLAGS))
        entries.append(dict(number=number, generation=generation, sha256=digest, bytes=path.stat().st_size,
                            retention_path=str(path), receipt=receipt))
    manifest = _write_json(root / "archive.json", dict(schema="v4.panel_retirement_batch.v1",
        status="EXACT_COLD_ARCHIVE_VERIFIED_ORIGINALS_RETAINED", source=entries))
    binding = _write_json(root / "binding.json", dict(schema="V4_MAC_WORKBENCH_BINDING_V1",
        top200_frozen_selector_archive=manifest, **workbench.FLAGS))
    monkeypatch.setenv("V4_WORKBENCH_HOST_BINDING", binding["path"])
    monkeypatch.setenv("V4_WORKBENCH_HOST_BINDING_SHA256", binding["sha256"])
    return entries, tables, manifest


@pytest.fixture
def client(archive, monkeypatch):
    # Classification is an unrelated release overlay absent from the git tree.
    name = "infrastructure.research_classification_view"
    if importlib.util.find_spec(name) is None:
        overlay = ModuleType(name)

        class UnusedClassificationStore:
            def __init__(self, root):
                assert root is None

            def close(self):
                pass

        overlay.ReceivedClassificationStore = UnusedClassificationStore
        monkeypatch.setitem(sys.modules, name, overlay)
    app = FastAPI()
    app.include_router(workbench.create_workbench_router(None))
    with TestClient(app) as client:
        yield client


def _get(client, *, generation=GEN17, day=DAY, path=PATH, columns="close,kb_b1", **extra):
    return client.get(path, params=dict(generation=generation, trade_date=day, columns=columns, **extra))


@pytest.mark.parametrize(("generation", "number", "close"), [(GEN17, 17, 126.27), (GEN18, 18, 120.15)])
def test_exact_generation_returns_only_matching_row(client, archive, generation, number, close):
    entries, _, manifest = archive
    entry = entries[number - 17]
    result = _get(client, generation=generation)
    assert result.status_code == 200, result.text
    value = result.json()
    assert all(value[key] == expected for key, expected in workbench.FLAGS.items())
    assert value["status"] == "READY" and value["historical_PIT"] is False
    assert value["generation"] == generation
    assert value["row"] == {"trade_date": "20261029", "ts_code": SSE, "market_type": "A_SHARE",
                            "close": close, "kb_b1": True}
    assert value["source"]["archive_number"] == number
    assert value["source"]["artifact_sha256"] == entry["sha256"]
    assert value["source"]["artifact_bytes"] == entry["bytes"]
    assert value["source"]["archive_manifest_sha256"] == manifest["sha256"]
    assert value["source"]["producer_receipt_sha256"] == entry["receipt"]["sha256"]


def test_preserves_market_nulls_and_unknown_scope(client):
    bj = _get(client, path=PATH.replace(SSE, BSE)).json()
    assert bj["row"]["market_type"] == "BJ" and bj["row"]["kb_b1"] is None
    unknown = _get(client, path=PATH.replace(SSE, UNKNOWN)).json()
    assert unknown["status"] == "CANNOT_CONFIRM" and unknown["row"] is None
    assert unknown["reason"] == "TARGET_DIRECTORY_OMISSION_PENDING_SOURCE_ADMISSION"
    assert _get(client, path=PATH.replace(SSE, "600001.SH")).status_code == 404
    assert _get(client, path=PATH.replace(SSE, "00005.HK")).status_code == 409


def test_rejects_unlisted_generation_and_invalid_coordinates(client):
    assert _get(client, generation="0" * 64).status_code == 404
    assert _get(client, day="2026-10-31").status_code == 409
    assert _get(client, day="1994-01-05").status_code == 409
    assert _get(client, columns="close,close").status_code == 409
    assert _get(client, columns="arbitrary_column").status_code == 409
    assert _get(client, path=PATH.replace(ASOF, "2026-11-02")).status_code == 404
    missing = _get(client, day="2026-10-28").json()
    assert missing["status"] == "CANNOT_CONFIRM" and missing["row"] is None


def test_rejects_changed_archive_even_with_same_size_and_mtime(client, archive):
    entries, tables, _ = archive
    assert _get(client).status_code == 200
    path = Path(entries[0]["retention_path"])
    before = path.stat()
    table = tables[17].set_column(3, "close", pa.array([11.0, 22.0, 33.0, 44.0]))
    logical.physical.write_table(table, path, compression="NONE")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_size == before.st_size
    response = _get(client, path_override=entries[1]["retention_path"])
    assert response.status_code == 409
    assert response.json()["detail"] == "ARCHIVED_SELECTOR_ARTIFACT_IDENTITY_CONFLICT"


@pytest.mark.parametrize("reference", ["manifest", "receipt", "parquet"])
def test_missing_archive_reference_fails_closed(client, archive, reference):
    entries, _, manifest = archive
    path = {"manifest": manifest["path"], "receipt": entries[0]["receipt"]["path"],
            "parquet": entries[0]["retention_path"]}[reference]
    Path(path).rename(Path(path).with_suffix(".missing"))
    assert _get(client, path_override=entries[1]["retention_path"]).status_code == 409


def test_default_single_research_route_is_unchanged(client, monkeypatch):
    def read_default(self, source_date, symbol, revision):
        return {"source_date": source_date, "symbol": symbol, "revision": revision}

    monkeypatch.setattr(workbench.ResearchWorkbenchHost, "daily_score_action", read_default)
    date = "2026-11-11"
    response = client.get(f"/workbench/days/{date}/single-research/{SSE}", params={"revision": "daily"})
    assert response.status_code == 200
    assert response.json() == {"source_date": date, "symbol": SSE, "revision": "daily"}
