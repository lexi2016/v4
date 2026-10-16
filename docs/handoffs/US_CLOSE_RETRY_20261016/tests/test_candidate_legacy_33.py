from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

APP = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-close-retry-us-20261016-r1/app")


def test_candidate_unconfigured_producer_keeps_legacy_33_ready_path() -> None:
    code = r'''
import json
from ops.us_market_digest import GLOBAL_INDUSTRY_PROXY_MAP, _configured_us_universe_contract, build_us_market_phase_payload
contract = _configured_us_universe_contract()
quotes = {symbol: {"last": 101, "previous_close": 100, "session_date": "20261014", "session_time": "16:00:01"}
          for row in GLOBAL_INDUSTRY_PROXY_MAP for symbol in row["proxy_symbols"]}
quotes["NVDA"]["session_time"] = "16:04:36"
payload = build_us_market_phase_payload("20261015", us_session_date="20261014", capture_phase="POST_CLOSE",
    fetched_at="2026-10-15T06:09:12Z", now="2026-10-15T06:09:12Z", allow_late_post_close=True,
    fetch_rss=lambda *args: b"<rss><channel></channel></rss>", fetch_quotes=lambda *args: quotes)
print(json.dumps({"version": contract["version"], "symbol_count": len(contract["symbols"]),
    "status": payload["market_snapshot"]["status"], "quote_count": len(payload["market_snapshot"]["quotes"])}, sort_keys=True))
'''
    env = dict(os.environ)
    env.pop("V35_APP_ROOT", None)
    env.pop("V4_MANAGER_WORKBENCH_CONFIG_PATH", None)
    env["PYTHONPATH"] = f"{APP}/upstreams:{APP}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run([sys.executable, "-c", code], cwd=APP, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "version": "US_MAPPING_UNIVERSE_CONTRACT_V2",
        "symbol_count": 33,
        "status": "READY",
        "quote_count": 33,
    }
