"""Focused regression for read-only historical source rechecks."""
from datetime import datetime, timedelta, timezone

from v4.manager_research import workspace
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore

DATE = '20260924'
HK = timezone(timedelta(hours=8))
CUTOFF = datetime(2026, 9, 24, 9, 27, 0, tzinfo=HK)
NOW = datetime(2026, 9, 25, 10, 20, 0, tzinfo=HK)
FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)


class ExactSessionReader:
    def __init__(self, expected_session: str, captured_at: str):
        self.expected_session = expected_session
        self.captured_at = captured_at
        self.calls: list[str] = []

    def read_exact_session(self, session_date: str):
        self.calls.append(session_date)
        rows = [
            dict(label='AI算力' if i == 0 else f'proxy-{i}', group='GLOBAL_INDUSTRY',
                 mapping_type='stock_basket_proxy', pct_change=3.5 if i == 0 else -0.5,
                 status='READY', proxy_symbols=['NVDA'], available_symbols=['NVDA'],
                 coverage={'available': 1, 'requested': 1})
            for i in range(24)
        ]
        payload = dict(market_snapshot=dict(
            schema_version='v3_5.us_market_snapshot.v1',
            mapping_version='v3_5.global_industry_proxy_map.v1',
            capture_phase='POST_CLOSE', capture_session_date=self.expected_session,
            provider_session_dates=[self.expected_session], status='READY',
            captured_at=self.captured_at, provider='SIMULATED_OWNER',
            source_response_sha256='d' * 64, rows=rows,
            requested_symbol_count=33, available_symbol_count=1,
            quotes=[dict(symbol='NVDA', change_pct=2.1,
                         session_date=self.expected_session, session_time='16:00:00')],
            **FLAGS,
        ))
        lineage = dict(status='VERIFIED', payload_sha256='a' * 64,
                       receipt_sha256='b' * 64, manifest_sha256='c' * 64)
        return payload, lineage


def _save_plan(service, monkeypatch):
    original = workspace.plan_context
    with monkeypatch.context() as m:
        m.setattr(workspace, 'plan_context', lambda date, **_kw: original(date, now=CUTOFF))
        m.setattr(workspace, '_now', lambda: CUTOFF.isoformat())
        return service.refresh_workspace_plan(DATE)


def test_failed_historical_replay_surfaces_exact_cutoff_us_recheck_without_mutating_plan(
    tmp_path, monkeypatch,
):
    service = ManagerResearchJobService(ManagerResearchStore(tmp_path / 'manager'), None, None)
    try:
        saved_product = _save_plan(service, monkeypatch)
        saved_path = service.store.root / 'workspace_plans' / DATE / 'latest.json'
        before = saved_path.read_bytes()
        saved_row = service.store._read(saved_path)
        assert saved_row['workspace']['us_market_attention']['status'] == 'INPUT_MISSING'

        from contracts.us_equity_calendar import latest_completed_session
        session = latest_completed_session(CUTOFF)
        reader = ExactSessionReader(
            session.session_date,
            (session.close_at + timedelta(minutes=15)).isoformat(),
        )
        service._workspace_us_market_reader = reader

        def failed_replay(*_args, **_kwargs):
            raise ValueError('HISTORY_SOURCE_INPUTS_CHANGED')

        monkeypatch.setattr(workspace, '_compute_workspace', failed_replay)
        result = service.get_workspace(DATE, view='historical', now=NOW)

        assert result['read_context']['status'] == 'SOURCE_FAILED'
        assert result['read_context']['as_of'] == CUTOFF.isoformat()
        assert result['plan_product']['run_id'] == saved_product['plan_product']['run_id']
        assert result['plan_product']['sha256'] == saved_product['plan_product']['sha256']
        assert result['plan_product']['consumed'] is False
        assert result['stocks'] == []
        assert result['us_market_attention']['status'] == 'READY'
        assert result['us_market_attention']['expected_us_session'] == session.session_date
        assert len(result['us_market_attention']['raw_industry_up']) == 1
        assert len(result['us_market_attention']['raw_individual_up']) == 1
        assert result['historical_source_rechecks']['us_market']['research_cutoff'] == CUTOFF.isoformat()
        assert result['historical_source_rechecks']['us_market']['saved_plan_run_id'] == saved_product['plan_product']['run_id']
        assert result['historical_source_rechecks']['us_market']['saved_plan_modified'] is False
        assert result['historical_source_rechecks']['us_market']['selected_stock_verdict_modified'] is False
        assert reader.calls == [session.session_date]
        assert saved_path.read_bytes() == before
    finally:
        service.close()
