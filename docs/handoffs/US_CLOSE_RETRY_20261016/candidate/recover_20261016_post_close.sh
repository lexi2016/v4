#!/bin/zsh
set -euo pipefail

APP_ROOT="/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-close-retry-us-20261016-r1/app"
PYTHON="/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python"
DATA_ROOT="/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data"
BASE="/Users/lexi/Desktop/学习/agents调试/V4_US_CLOSE_RETRY_20261016/candidate"
COLLECTOR="$BASE/evidence/collect_us_recovery_receipt.py"
RECEIPT_DIR="$BASE/evidence/recovery_receipts"
CANDIDATE_MANIFEST="/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-close-retry-us-20261016-r1/release-manifest.json"
CANDIDATE_MANIFEST_SHA256="3793d0acb6937828fccc0c6f1a5331be699e7ad62ac448654050a62ab70225a9"
LOCAL_RUNTIME_ROOT="/Users/lexi/Library/Application Support/com.lexi.v4.local"
MANAGER_CONFIG_PATH="$LOCAL_RUNTIME_ROOT/config/manager-workbench-v7.json"
MANAGER_CONFIG_SHA256="65684e5eb7657390747c089db74047d6a2c67d7f5de1bd3fe757a62f120965ca"
US_UNIVERSE_VERSION="US_MAPPING_UNIVERSE_CONTRACT_V3"
US_UNIVERSE_CONTRACT_SHA256="da620de4b1223df678623dcc84958b9dc751c7a4c951e17186df45652d5d50cb"
US_UNIVERSE_SYMBOL_COUNT="48"
TARGET_PAYLOAD="$DATA_ROOT/research/peripherals/20261016/external_finance.json"
TARGET_PAYLOAD_SHA256="e65a6e82e21f7cba1667be19e01957184da6e415c329bbeb9ee5f4f934a3c368"
TARGET_PREIMAGE_UNIVERSE_VERSION="US_MAPPING_UNIVERSE_CONTRACT_V2"
TARGET_PREIMAGE_SYMBOL_COUNT="33"

cd "$APP_ROOT"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1
export PYTHONPATH="$APP_ROOT/upstreams:$APP_ROOT"
# Mirror the identity and root supplied by the loaded US owner. The explicit
# config path is the same path derived from V35_APP_ROOT by the producer.
export V35_APP_ROOT="$APP_ROOT"
export V35_RELEASE_ID="us-close-retry-us-20261016-r1"
export V35_RELEASE_MANIFEST_PATH="$CANDIDATE_MANIFEST"
export V35_RELEASE_MANIFEST_SHA256="$CANDIDATE_MANIFEST_SHA256"
export V4_MANAGER_WORKBENCH_CONFIG_PATH="$MANAGER_CONFIG_PATH"

if ! CONTRACT_PREFLIGHT_JSON="$("$PYTHON" -B - "$APP_ROOT" "$CANDIDATE_MANIFEST" "$MANAGER_CONFIG_PATH" "$DATA_ROOT" <<'PY'
import hashlib
import json
import os
import sys
from pathlib import Path

app_root = Path(sys.argv[1]).resolve()
manifest_path = Path(sys.argv[2]).resolve()
config_path = Path(sys.argv[3]).resolve()
data_root = Path(sys.argv[4]).resolve()

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

expected = {
    "app_root": str(app_root),
    "release_id": "us-close-retry-us-20261016-r1",
    "manifest_path": str(manifest_path),
    "manifest_sha256": "3793d0acb6937828fccc0c6f1a5331be699e7ad62ac448654050a62ab70225a9",
    "config_path": str(config_path),
    "config_sha256": "65684e5eb7657390747c089db74047d6a2c67d7f5de1bd3fe757a62f120965ca",
}
actual = {
    "app_root": os.environ.get("V35_APP_ROOT"),
    "release_id": os.environ.get("V35_RELEASE_ID"),
    "manifest_path": os.environ.get("V35_RELEASE_MANIFEST_PATH"),
    "manifest_sha256": os.environ.get("V35_RELEASE_MANIFEST_SHA256"),
    "config_path": os.environ.get("V4_MANAGER_WORKBENCH_CONFIG_PATH"),
    "config_sha256": digest(config_path) if config_path.is_file() else None,
}
if actual != expected or digest(manifest_path) != expected["manifest_sha256"]:
    raise SystemExit("US_OWNER_CONFIG_OR_RELEASE_IDENTITY_MISMATCH")

from ops.us_market_digest import _configured_us_universe_contract

contract = _configured_us_universe_contract()
if (contract.get("version") != "US_MAPPING_UNIVERSE_CONTRACT_V3"
        or len(contract.get("symbols") or []) != 48
        or contract.get("contract_sha256") != "da620de4b1223df678623dcc84958b9dc751c7a4c951e17186df45652d5d50cb"):
    raise SystemExit("US_OWNER_UNIVERSE_CONTRACT_MISMATCH")

target = data_root / "research/peripherals/20261016/external_finance.json"
if not target.is_file() or digest(target) != "e65a6e82e21f7cba1667be19e01957184da6e415c329bbeb9ee5f4f934a3c368":
    raise SystemExit("US_RECOVERY_TARGET_PREIMAGE_MISMATCH")
payload = json.loads(target.read_text(encoding="utf-8"))
snapshot = payload.get("market_snapshot") or {}
old_contract = snapshot.get("universe_contract") or {}
if (payload.get("trade_date") != "20261016"
        or payload.get("source") != "external_finance"
        or payload.get("status") != "READY"
        or payload.get("market_snapshot_status") != "READY"
        or snapshot.get("capture_session_date") != "20261015"
        or old_contract.get("version") != "US_MAPPING_UNIVERSE_CONTRACT_V2"
        or len(old_contract.get("symbols") or []) != 33
        or snapshot.get("requested_symbol_count") != 33
        or snapshot.get("available_symbol_count") != 33
        or len(snapshot.get("quotes") or []) != 33):
    raise SystemExit("US_RECOVERY_TARGET_PREIMAGE_IDENTITY_MISMATCH")

print(json.dumps({
    "candidate_app_root": str(app_root),
    "candidate_manifest_sha256": actual["manifest_sha256"],
    "manager_config_path": str(config_path),
    "manager_config_sha256": actual["config_sha256"],
    "universe_contract_version": contract["version"],
    "universe_contract_sha256": contract["contract_sha256"],
    "universe_symbol_count": len(contract["symbols"]),
    "target_preimage_status": "REAL_PARTIAL_V2_33_RETAINED",
    "target_preimage_sha256": digest(target),
    "target_preimage_symbol_count": len(old_contract["symbols"]),
}, sort_keys=True))
PY
)"; then
  print -u2 -- "US_RECOVERY_OWNER_CONTRACT_OR_TARGET_PREFLIGHT_FAILED"
  exit 78
fi
printf 'OWNER_PREFLIGHT_JSON=%s\n' "$CONTRACT_PREFLIGHT_JSON"

if [[ "${1:-}" != "--execute" || $# -ne 1 ]]; then
  cat <<'PLAN'
PLAN_ONLY: no capture was run.
To execute after independent review and explicit integration authorization, pass exactly --execute.
The planned command targets research trade date 20261016 and US session 20261015 through the existing US producer.
Owner configuration preflight is read-only; no producer or network capture was run.
The exact V2/33 target preimage is retained; the existing producer's date-keyed replacement path preserves it in history on a successful refresh.
PLAN
  printf 'Proxy: HTTP(S)_PROXY=http://127.0.0.1:7897; NO_PROXY=127.0.0.1,localhost,::1\n'
  printf 'Candidate manifest SHA-256: %s\n' "$CANDIDATE_MANIFEST_SHA256"
  printf 'Manager config path: %s\n' "$MANAGER_CONFIG_PATH"
  printf 'US universe: %s; symbols=%s; contract SHA-256=%s\n' "$US_UNIVERSE_VERSION" "$US_UNIVERSE_SYMBOL_COUNT" "$US_UNIVERSE_CONTRACT_SHA256"
  printf 'Existing target: V2/33 retained; SHA-256=%s\n' "$TARGET_PAYLOAD_SHA256"
  printf 'Collector: %q\n' "$COLLECTOR"
  printf 'Producer: cd %q && %q -B -m ops.us_market_digest --data-root %q --trade-date 20261016 --us-session-date 20261015 --capture-phase POST_CLOSE --allow-late-post-close --manual-late-recovery\n' \
    "$APP_ROOT" "$PYTHON" "$DATA_ROOT"
  exit 0
fi

export RESEARCH_ONLY=1
export PRODUCTION_ALLOWED=false
export BUY_GATE_UPDATED=false
export ORDERS_SENT=false
export HTTP_PROXY="http://127.0.0.1:7897"
export http_proxy="http://127.0.0.1:7897"
export HTTPS_PROXY="http://127.0.0.1:7897"
export https_proxy="http://127.0.0.1:7897"
export NO_PROXY="127.0.0.1,localhost,::1"
export no_proxy="127.0.0.1,localhost,::1"
exec "$PYTHON" "$COLLECTOR" \
  --receipt-dir "$RECEIPT_DIR" \
  --candidate-app-root "$APP_ROOT" \
  --candidate-manifest "$CANDIDATE_MANIFEST" \
  --candidate-manifest-sha256 "$CANDIDATE_MANIFEST_SHA256" \
  --producer-source "$APP_ROOT/ops/us_market_digest.py" \
  -- \
  "$PYTHON" -B -m ops.us_market_digest \
  --data-root "$DATA_ROOT" \
  --trade-date 20261016 \
  --us-session-date 20261015 \
  --capture-phase POST_CLOSE \
  --allow-late-post-close \
  --manual-late-recovery
