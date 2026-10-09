#!/usr/bin/env python3
"""Offline evidence only: real runner/stores, synthetic security and quote I/O."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from pytest import MonkeyPatch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from test_research_runner_chain import prepared


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    with MonkeyPatch.context() as patch:
        owner, decision, _input, calls = prepared(root, patch, count=695)
        result = owner.tick('20261009', datetime(2026, 10, 9, 9, 35, tzinfo=ZoneInfo('Asia/Shanghai')),
                            stage_id=decision.stage_id, historical_backfill=True, _skip_precapture=True)
    assert result['markets']['HK_CONNECT']['selected_rows'] == 10, result
    assert len(calls) == 1 and len(calls[0][2]) == 695
    result_path = root / 'runner_response.json'
    result_path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'status': 'PASS', 'scope': 'OFFLINE_SYNTHETIC_EXTERNAL_IO_REAL_PRODUCTION_RUNNER',
        'output': str(root), 'selected_rows': 10, 'requested_rows': 695,
        'run_id': result['markets']['HK_CONNECT']['run_id'],
        'execution_origin': result['execution_origin'], 'natural_verified': False,
        'RESEARCH_ONLY': True, 'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}))


if __name__ == '__main__':
    main()
