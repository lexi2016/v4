"""Synthetic public-entry regression; no real grant, collection or deployment."""
import base64
import json

from ops import run_stage_center_nodes as nodes
from stage_center.contracts import SAFETY_FLAGS
from test_issue11_a_auction_recovery import case, DATE, STAGE, NOW


def test_explicit_public_entry_mints_its_own_capability_and_spends_once(case):
    # The older fixture installs this only for private-dispatch tests. The
    # public call below must create the capability itself; do not mock dispatch.
    case.cfg.pop('_issue11_explicit_request', None)
    before = {path: path.read_bytes() for path in case.path.parent.rglob('*.json')
              if path != case.path}
    result = nodes.run_nodes(case.cfg, trade_date=DATE, evaluated_at=NOW,
                             explicit_node=STAGE, runner=case.runner)
    assert result['node_count'] == 1 and result['recovery'] is True
    assert len(case.calls) == 1 and case.calls[0].stage_id == STAGE
    assert '_issue11_explicit_request' not in case.cfg
    node = result['nodes'][0]
    assert node['node_attempt_count'] == 4
    assert node['repair_recovery_original_attempt_count'] == 3
    assert node['repair_recovery_attempt_count'] == 1
    assert node['result_origin'] == 'CODE_REPAIR_RECOVERY'
    assert node['real_time_success'] is False
    assert node['evidence_limit'] == 'L0_HISTORICAL_TRANSACTIONS_NOT_COMPLETE_AUCTION_BOOK'
    saved = json.loads((case.path.parent / 'a_0925_issue11_recovery.json').read_bytes())
    assert saved['candidate_count'] == 205
    assert len(saved['original_attempts']) == 6
    assert base64.b64decode(saved['original_receipt_base64'], validate=True) == case.raw
    assert all(path.read_bytes() == value for path, value in before.items())
    assert all(result[flag] is False and node[flag] is False for flag in SAFETY_FLAGS)
    # A failed synthetic runner result must not reopen the granted recovery.
    again = nodes.run_nodes(case.cfg, trade_date=DATE, evaluated_at=NOW,
                            explicit_node=STAGE, runner=case.runner)
    assert again['status'] == 'RETRY_EXHAUSTED'
    assert again['nodes'][0]['status'] == 'SKIPPED_REPAIR_RECOVERY_CONSUMED'
    assert len(case.calls) == 1
