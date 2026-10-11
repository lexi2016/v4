#!/usr/bin/env python3
"""Supplemental original-gate integration review, all writes in fresh review state."""
from contextlib import contextmanager
import inspect
import json
from pathlib import Path

from reproduce_announcement_full_chain import (
    DEFAULT_CANDIDATE, EARLY, LATE, REVIEW_ROOT, announcement, fixture_clock,
    get_json, load_fixture, source_snapshot,
)


@contextmanager
def mixed_source_with_risk(fixture):
    """Change synthetic generator INPUTS before hashes/build/review/import."""
    original_generator = fixture._write_complete_evidence
    original_fixture = fixture._fixture
    generator = inspect.getsource(original_generator)
    assert generator.count('[issuer]') == 3
    assert generator.count('    listing = {') == 1
    assert generator.count('"manager_source_identity_count": 1') == 1
    assert generator.count('"manager_source_codes": [issuer["code"]]') == 1
    generator = generator.replace('    listing = {',
        '    source_issuers = [issuer, {"code": "H5354", "source_stock_code": "H5354", '
        '"market_code": "116", "ann_type": "H", "name": "Synthetic applicant"}]\n'
        '    listing = {')
    generator = generator.replace('[issuer]', 'source_issuers')
    generator = generator.replace('"manager_source_identity_count": 1',
                                   '"manager_source_identity_count": len(source_issuers)')
    generator = generator.replace('"manager_source_codes": [issuer["code"]]',
                                   '"manager_source_codes": sorted(row["code"] for row in source_issuers)')
    fixture_input = inspect.getsource(original_fixture)
    assert fixture_input.count("'risk_notes': []") == 1
    fixture_input = fixture_input.replace("'risk_notes': []",
                                         "'risk_notes': ['Synthetic source-bound reviewed risk']")
    try:
        exec(compile(generator, '<synthetic-two-issuer-generator>', 'exec'), fixture.__dict__)
        exec(compile(fixture_input, '<synthetic-reviewed-risk-input>', 'exec'), fixture.__dict__)
        yield
    finally:
        fixture._write_complete_evidence = original_generator
        fixture._fixture = original_fixture


def mixed(fixture, out):
    fixture.NOW = EARLY
    service = fixture._FixtureService(out / 'mixed_issuer_owner')
    try:
        with mixed_source_with_risk(fixture):
            product, registered = fixture._fixture(service)
        with fixture._client(service) as client:
            imported = fixture._import(client, registered)
            before = fixture._snapshot(service.store.root)
            readback = get_json(client, '/api/v4/manager/research/announcements/analysis',
                               date=fixture.TARGET, publication_date=fixture.PUBLICATION)
            value = get_json(client, '/api/v4/manager/research/workspace',
                             date=fixture.TARGET, view='dynamic', announcement_date='20261007')
            assert fixture._snapshot(service.store.root) == before
        channel, consumed = announcement(value, fixture)
        selection = readback['analysis']['stock_selection']
        assert imported['consumption_validation']['validation_status'] == 'VERIFIED'
        assert selection['status'] == 'VERIFIED' and selection['selected_stock_count'] == 2
        assert consumed['status'] == 'CONSUMED'
        assert channel['status'] == 'PARTIAL' and channel['candidate_count'] == 1
        assert len(channel['rows']) == 1 and channel['rows'][0]['symbol'] == 'HK.01234'
        assert channel['rows'][0]['risk_notes'] == ['Synthetic source-bound reviewed risk']
        assert len(channel['unmapped_references']) == 1
        assert channel['unmapped_references'][0]['stock_code'] == 'H5354'
        assert channel['unmapped_references'][0]['risk_notes'] == ['Synthetic source-bound reviewed risk']
        assert channel['unmapped_references'][0]['product_sha256'] == product['sha256']
        assert readback['analysis']['point_in_time_status'] == 'CANNOT_CONFIRM'
        for result in (value, readback, imported):
            assert result['RESEARCH_ONLY'] is True
            assert result['production_allowed'] is False
            assert result['buy_gate_updated'] is False
            assert result['orders_sent'] is False
        (out / 'mixed_issuer_workspace.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        return dict(status='PASS', selected_stock_count=2, projected_selected_count=1,
            unmapped_count=1, candidate_status=channel['status'], candidate_count=channel['candidate_count'],
            mapped_and_unmapped_risks_preserved=True, point_in_time_status=readback['analysis']['point_in_time_status'],
            product_sha256=product['sha256'], accounting=channel['reference_accounting'],
            get_wrote_state=False)
    finally:
        service.close()


def valid_zero(fixture, out):
    fixture.NOW = EARLY
    service = fixture._FixtureService(out / 'explicit_not_selected_owner')
    try:
        product, registered = fixture._fixture(service, disposition='NOT_SELECTED')
        with fixture._client(service) as client:
            imported = fixture._import(client, registered)
            before = fixture._snapshot(service.store.root)
            value = get_json(client, '/api/v4/manager/research/workspace',
                             date=fixture.TARGET, view='dynamic', announcement_date='20261007')
            assert fixture._snapshot(service.store.root) == before
        channel, consumed = announcement(value, fixture)
        checks = imported['consumption_validation']
        assert checks['validation_status'] == 'VERIFIED'
        assert checks['stock_count'] == 1 and checks['not_selected_stock_count'] == 1
        assert checks['selected_stock_count'] == 0
        assert consumed['status'] == 'CONSUMED'
        assert channel['status'] == 'READY_EMPTY' and channel['candidate_count'] == 0
        assert channel['pending_count'] == 0 and channel['gaps'] == []
        return dict(status='PASS', original_stock_count=checks['stock_count'],
            original_not_selected_count=checks['not_selected_stock_count'],
            candidate_status=channel['status'], candidate_count=channel['candidate_count'],
            product_sha256=product['sha256'], get_wrote_state=False)
    finally:
        service.close()


def historical(fixture, out):
    fixture.NOW = EARLY
    service = fixture._FixtureService(out / 'historical_late_import_owner')
    try:
        service.refresh_workspace_plan(fixture.TARGET, now=EARLY)
        early = service.get_workspace(fixture.TARGET, view='dynamic')
        assert early['plan_product']['status'] == 'CURRENT'
        cutoff = early['plan_context']['research_cutoff']
        sealed_plan_hashes = {key: value for key, value in fixture._snapshot(service.store.root).items()
                              if key.startswith(('workspace_plans/', 'workspace_plan_runs/'))}
        assert sealed_plan_hashes
        fixture.NOW = LATE
        product, registered = fixture._fixture(service)
        with fixture._client(service) as client:
            imported = fixture._import(client, registered)
            assert imported['consumption_validation']['validation_status'] == 'VERIFIED'
            before = fixture._snapshot(service.store.root)
            views = {view: get_json(client, '/api/v4/manager/research/workspace',
                     date=fixture.TARGET, view=view) for view in ('dynamic', 'historical', 'auto')}
            after = fixture._snapshot(service.store.root)
            assert after == before
            assert all(after[key] == value for key, value in sealed_plan_hashes.items())
        dynamic_channel, dynamic_consumed = announcement(views['dynamic'], fixture)
        assert dynamic_consumed['status'] == 'CONSUMED'
        assert dynamic_channel['status'] == 'READY' and dynamic_channel['candidate_count'] == 1
        results = {}
        for view in ('historical', 'auto'):
            value = views[view]
            channel = value['daily_channels']['channels'][0]
            assert value['read_context']['mode'] == 'HISTORICAL_AS_OF'
            assert value['read_context']['as_of'] == cutoff
            assert channel['candidate_count'] is None
            products = value.get('announcement_reviewed_analysis', {}).get('products', [])
            assert not any(row.get('product_sha256') == product['sha256'] and row.get('status') == 'CONSUMED'
                           for row in products)
            results[view] = dict(read_context=value['read_context'],
                plan_product_status=(value.get('plan_product') or {}).get('status'),
                candidate_status=channel['status'], candidate_count=channel['candidate_count'],
                late_product_consumed=False, gaps=channel['gaps'], workspace_gaps=value.get('gaps'))
            (out / (view + '_late_import_workspace.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        return dict(status='PASS', original_cutoff=cutoff, current_clock=LATE.isoformat(),
            dynamic_read_basis=views['dynamic']['read_context'].get('read_basis'),
            dynamic_consumption_status=dynamic_consumed['status'], views=results,
            sealed_plan_and_attempt_hashes=sealed_plan_hashes,
            sealed_plan_bytes_unchanged=True, get_wrote_state=False)
    finally:
        service.close()


def main():
    out = REVIEW_ROOT / 'acceptance_frozen_r2' / 'supplemental'
    out.mkdir(parents=True, exist_ok=False)
    before = source_snapshot(DEFAULT_CANDIDATE)
    fixture, fixture_path = load_fixture(DEFAULT_CANDIDATE)
    from v4.manager_research import workspace
    result = dict(scope='SYNTHETIC_FULL_ORIGINAL_GATES_SUPPLEMENTAL', fixture=str(fixture_path),
                  source_before=before)
    try:
        with fixture_clock(fixture, workspace):
            result['mixed_issuer'] = mixed(fixture, out)
            result['explicit_not_selected'] = valid_zero(fixture, out)
            result['historical_after_late_import'] = historical(fixture, out)
    finally:
        result['source_after'] = source_snapshot(DEFAULT_CANDIDATE)
        result['source_unchanged'] = result['source_before'] == result['source_after']
        (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    assert result['source_unchanged']
    print(json.dumps({key:value for key,value in result.items() if key not in ('source_before','source_after')},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
