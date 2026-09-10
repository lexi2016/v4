from fastapi.testclient import TestClient

from apps.api.v35_api.app import create_app


EXPECTED_STAGES = [
    "STAGE_0925",
    "STAGE_0930_0935",
    "STAGE_0935_0940",
    "STAGE_0940_0945",
    "STAGE_0945_1030",
    "STAGE_1300_1315",
    "STAGE_1445_1500",
    "STAGE_1545_1555",
]


def test_healthz_is_liveness_only() -> None:
    response = TestClient(create_app()).get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_keeps_all_trading_safety_flags_false() -> None:
    response = TestClient(create_app()).get("/readyz")

    assert response.status_code == 200
    assert response.json()["production_allowed"] is False
    assert response.json()["buy_gate_updated"] is False
    assert response.json()["orders_sent"] is False


def test_stage_metadata_is_exactly_frozen_chronological_sequence() -> None:
    response = TestClient(create_app()).get("/api/v3/meta/stages")

    assert response.status_code == 200
    assert response.json()["stages"] == EXPECTED_STAGES
