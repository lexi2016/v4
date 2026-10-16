from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


CANDIDATE = Path(__file__).resolve().parents[1]
SCRIPT = CANDIDATE / "recover_20261016_post_close.sh"
DATA_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data")
CONFIG = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/config/manager-workbench-v7.json")
TARGET = DATA_ROOT / "research/peripherals/20261016/external_finance.json"
RECEIPTS = CANDIDATE / "evidence/recovery_receipts"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_recovery_plan_resolves_actual_candidate_v3_environment_without_capture() -> None:
    target_before = sha256(TARGET)
    receipt_entries_before = sorted(path.name for path in RECEIPTS.iterdir())
    result = subprocess.run(
        ["/bin/zsh", str(SCRIPT)],
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "PLAN_ONLY: no capture was run." in result.stdout
    assert "Owner configuration preflight is read-only; no producer or network capture was run." in result.stdout
    preflight_line = next(line for line in result.stdout.splitlines() if line.startswith("OWNER_PREFLIGHT_JSON="))
    preflight = json.loads(preflight_line.split("=", 1)[1])

    assert preflight["manager_config_path"] == str(CONFIG)
    assert preflight["manager_config_sha256"] == sha256(CONFIG)
    assert preflight["universe_contract_version"] == "US_MAPPING_UNIVERSE_CONTRACT_V3"
    assert preflight["universe_contract_sha256"] == "da620de4b1223df678623dcc84958b9dc751c7a4c951e17186df45652d5d50cb"
    assert preflight["universe_symbol_count"] == 48
    assert preflight["target_preimage_status"] == "REAL_PARTIAL_V2_33_RETAINED"
    assert preflight["target_preimage_sha256"] == target_before
    assert preflight["target_preimage_symbol_count"] == 33
    assert target_before == "e65a6e82e21f7cba1667be19e01957184da6e415c329bbeb9ee5f4f934a3c368"
    assert sorted(path.name for path in RECEIPTS.iterdir()) == receipt_entries_before
    assert sha256(TARGET) == target_before
