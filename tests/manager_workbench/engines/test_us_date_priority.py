from copy import deepcopy
import pytest
from test_us_mapping import make_batch
from v4.manager_workbench.engines.us_mapping import run_us_mapping,publication_before_cutoff


def original_date(value='2026-10-10',role='RELATION'):
    return dict(role=role,published_at=value,precision='DATE',source_body_sha256='a'*64)


def native_case(change=1,priority='PRIORITY'):
    b=make_batch();item=b['records'][0];item.update(source_status='CANNOT_CONFIRM',positive_change_required=True,quote={'change_pct':change,'priority':'PRIORITY'})
    r=item['relations'][0];r.update(research_priority=priority,published_at=None,publication_evidence=[original_date()])
    return b


@pytest.mark.parametrize('change,priority,decision,reason',[(1,'PRIORITY','CONDITIONAL_WATCH','US_REVIEWED_RELATION_CONDITIONAL_ONLY'),(-1,'PRIORITY','NOT_SELECTED','US_SOURCE_CHANGE_NOT_POSITIVE'),(0,'PRIORITY','NOT_SELECTED','US_SOURCE_CHANGE_NOT_POSITIVE'),(1,None,'UNASSESSED','US_SESSION_RELATION_OR_CONNECT_UNVERIFIED'),(None,'PRIORITY','UNASSESSED','US_SESSION_RELATION_OR_CONNECT_UNVERIFIED')])
def test_card_priority_and_actual_positive_change(change,priority,decision,reason):
    b=native_case(change,priority);out=run_us_mapping(b['context'],b)
    assert out['rows'][0]['decision']==decision and out['rows'][0]['reason']==reason
    assert all(r['decision']!='SELECTED' for r in out['rows'])


def test_date_upper_bound_and_undated_supplement_not_new_gate():
    b=native_case();r=b['records'][0]['relations'][0];r['publication_evidence']+=[original_date(None)]
    assert publication_before_cutoff(b['context'],r)
    assert r['published_at'] is None and r['publication_evidence'][0]['published_at']=='2026-10-10'
    for value in ['2026-10-13','2026-10-12','2026-13-10','20261010','2026-10-10suffix']:
        other=deepcopy(r);other['publication_evidence']=[original_date(value)]
        assert not publication_before_cutoff(b['context'],other)
    c=dict(b['context'],cutoff='2026-10-13T12:00:00+00:00')
    assert publication_before_cutoff(c,dict(publication_evidence=[original_date('2026-10-12')]))


def test_identity_source_does_not_date_a_relation():
    b=native_case();r=b['records'][0]['relations'][0]
    r['publication_evidence']=[original_date(role='HK_LISTING_IDENTITY'),original_date(None)]
    assert run_us_mapping(b['context'],b)['rows'][0]['decision']=='UNASSESSED'
