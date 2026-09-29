from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "migration" / "runtime_review_batch_contract.json"
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def test_runtime_review_batch_contract_is_frozen() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    assert contract["schema_version"] == "runtime_review_batch_contract.v1"
    assert contract["bug_ids"] == ["037", "045", "046", "047", "048", "049"]
    assert contract["run_policy"] == "A_OR_HK_CONNECT_TRADE_DAY"
    assert contract["frozen_dates"] == {
        "weekend": "20260725",
        "weekend_after_cadence_change": "20260726",
        "trading_day": "20260730",
    }
    assert contract["baseline"] == {
        "branch": "codex/v3-5-full-rebuild-20260730",
        "head": "6413467698d86696683d2ce95dad872729444b48",
        "python_tests_passed": 123,
        "web_tests_passed": 15,
        "vue_typecheck_passed": True,
    }
    assert contract["safety"] == {
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def test_dirty_file_baseline_uses_raw_byte_sha256() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    dirty_files = contract["dirty_files"]

    assert contract["dirty_path_policy"] == {
        "sha256_mode": "RAW_BYTES",
        "scope": "PRE_EXISTING_GIT_DIRTY_FILES_ONLY",
        "generated_and_ignored_paths_excluded": True,
        "pre_edit_sha_must_match": True,
    }
    assert len(dirty_files) == 25
    assert len({row["path"] for row in dirty_files}) == len(dirty_files)
    assert all(row["status"] in {"M", "??"} for row in dirty_files)
    assert all(SHA256.fullmatch(row["sha256"]) for row in dirty_files)
    assert not any(
        part in row["path"]
        for row in dirty_files
        for part in (".git/", ".pytest_cache/", "__pycache__/", ".runtime/")
    )


def test_phase_a_allowed_paths_are_exact_and_safe() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    allowed = contract["allowed_paths"]
    assert allowed == sorted(set(allowed))
    assert "apps/api/v35_api/app.py" in allowed
    assert "apps/web/src/App.vue" in allowed
    assert "contracts/market_calendar_2026.json" in allowed
    assert "ops/run_dispatcher.py" in allowed
    assert all("v3_system" not in path for path in allowed)
    assert all(not Path(path).is_absolute() for path in allowed)
