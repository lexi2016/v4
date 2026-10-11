#!/usr/bin/env python3
"""Final compatibility probe: unchanged synthetic original owner/import gates."""
import json
from pathlib import Path

from reproduce_announcement_full_chain import (
    DEFAULT_CANDIDATE, EARLY, LATE, REVIEW_ROOT, announcement, fixture_clock,
    get_json, load_fixture, source_snapshot, summary,
)


def main():
    out = REVIEW_ROOT / 'acceptance_final_r2' / 'view_probe'
    out.mkdir(parents=True, exist_ok=False)
    before = source_snapshot(DEFAULT_CANDIDATE)
    fixture, _ = load_fixture(DEFAULT_CANDIDATE)
    from v4.manager_research import workspace
    result = {'source_before': before, 'scope': 'REAL_OWNER_OMITTED_EXPLICIT_HISTORICAL_AUTO_COMPATIBILITY'}
    service = fixture._FixtureService(out / 'owner')
    try:
        with fixture_clock(fixture, workspace):
            fixture.NOW = EARLY
            service.refresh_workspace_plan(fixture.TARGET, now=EARLY)
            saved = service.get_workspace(fixture.TARGET)
            cutoff = saved['plan_context']['research_cutoff']
            assert saved['plan_product']['status'] == 'CURRENT'
            sealed = {key: value for key, value in fixture._snapshot(service.store.root).items()
                      if key.startswith(('workspace_plans/', 'workspace_plan_runs/'))}
            fixture.NOW = LATE
            initial = fixture._snapshot(service.store.root)
            omitted = service.get_workspace(fixture.TARGET)
            explicit = service.get_workspace(fixture.TARGET, view='dynamic')
            repeated_omitted = service.get_workspace(fixture.TARGET)
            assert fixture._snapshot(service.store.root) == initial
            for value in (omitted, repeated_omitted):
                assert value['plan_product']['status'] == 'CURRENT'
                assert value['input_identity'] == saved['input_identity']
                assert value['plan_context']['research_cutoff'] == cutoff
                assert value['read_context']['read_basis'] == 'SAVED_PLAN_CUTOFF'
            assert explicit['read_context']['read_basis'] == 'RETROSPECTIVE_CURRENT_TIME'
            assert explicit['read_context']['as_of'] == '2026-10-11T12:00:00+08:00'
            assert explicit['plan_context']['research_cutoff'] == '2026-10-11T12:00:00+08:00'
            result['before_late_import'] = {
                'omitted': omitted['read_context'], 'explicit_dynamic': explicit['read_context'],
                'omitted_after_explicit': repeated_omitted['read_context'],
                'read_modes_isolated': True, 'get_wrote_state': False,
            }
            product, registered = fixture._fixture(service)
            with fixture._client(service) as client:
                imported = fixture._import(client, registered)
                assert imported['consumption_validation']['validation_status'] == 'VERIFIED'
                initial = fixture._snapshot(service.store.root)
                views = {view: get_json(client, '/api/v4/manager/research/workspace',
                         date=fixture.TARGET, view=view) for view in ('dynamic', 'historical', 'auto')}
                views['omitted_internal'] = service.get_workspace(fixture.TARGET)
                final = fixture._snapshot(service.store.root)
                assert final == initial
                assert all(final[key] == value for key, value in sealed.items())
            dynamic, consumed = announcement(views['dynamic'], fixture)
            assert consumed['status'] == 'CONSUMED'
            assert dynamic['candidate_count'] == 1 and dynamic['status'] == 'READY'
            view_results = {}
            for view, value in views.items():
                channel, consumed = announcement(value, fixture)
                if view != 'dynamic':
                    assert value['plan_context']['research_cutoff'] == cutoff
                    assert value['plan_product']['status'] == 'CURRENT'
                    assert consumed['status'] == 'NOT_CONSUMED_AFTER_CUTOFF'
                    assert channel['candidate_count'] is None
                if view in ('historical', 'auto'):
                    assert value['read_context']['mode'] == 'HISTORICAL_AS_OF'
                    assert value['read_context']['reader_compatibility']['status'] == 'VERIFIED'
                view_results[view] = summary(value, fixture)
            result['after_late_import'] = view_results
            result['sealed_plan_and_attempt_hashes'] = sealed
            result['all_gets_read_only'] = True
            result['sealed_plan_bytes_unchanged'] = True
            result['product_sha256'] = product['sha256']
    finally:
        service.close()
        result['source_after'] = source_snapshot(DEFAULT_CANDIDATE)
        result['source_unchanged'] = before == result['source_after']
        (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    assert result['source_unchanged']
    print(json.dumps({key:value for key,value in result.items()
                      if key not in ('source_before','source_after')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
