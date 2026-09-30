"""Synthetic missing-receipt regression; reuses the explicit one-shot fixture."""
import pytest
from test_issue11_a_auction_recovery import case, dispatch


@pytest.mark.parametrize('bad_receipt', [None, b'{', b'[]', b'{"trade_date":"20260930","stage_id":"STAGE_0925","status":"NOT_PLANNED"}'])
def test_explicit_repair_cannot_fall_through_to_normal_budget_when_receipt_invalid(case,bad_receipt):
    if bad_receipt is None:case.path.unlink()
    else:case.path.write_bytes(bad_receipt)
    def run(decision):
        case.calls.append(decision)
        return {**case.old, 'write_performed':False}
    case.runner._run_one=run
    dispatch(case)
    assert case.calls == []
    assert not (case.path.parent/'a_0925_issue11_recovery.json').exists()
