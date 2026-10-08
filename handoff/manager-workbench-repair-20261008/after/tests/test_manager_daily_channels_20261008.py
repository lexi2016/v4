"""Three read-only presentation channels, preserving original owner decisions."""
from copy import deepcopy

from v4.manager_research.workspace_projection import FLAGS, digest


def view():
    return dict(target_trade_date='20261008',input_identity='a'*64,stocks=[],focus_symbols=[],gaps=[],
        date_bindings=dict(selection_date='20261007',announcement_date='20261007',plan_date='20261008'),
        plan_context=dict(market_session='20261007',research_cutoff='2026-10-08T08:00:00+08:00'),
        owner_chain=dict(focus_inputs=dict(status='READY',gaps=[])),
        announcement_reviewed_analysis=dict(status='PARTIAL',products=[
            dict(status='CONSUMED',target_trade_date='20261008',publication_date='2026-10-07',
                 selection_status='VERIFIED',not_assessed_stock_count=0,
                 selected_stock_count=1,conditional_watch_count=0,
                 product_sha256='b'*64,source_manifest_sha256='c'*64,evidence_run_id='d'*32,
                 reviewed_at='2026-10-08T07:00:00+08:00',owner_available_at='2026-10-08T07:05:00+08:00'),
            dict(status='NOT_CONSUMED_INVALID',target_trade_date='20261007',publication_date='2026-10-06',gaps=['LEGACY_JUDGMENT_MISSING'])],
            research_references=[dict(stock_code='HK.00001',stock_name='Synthetic issuer',research_status='SELECTED',
                target_trade_date='20261008',publication_date='2026-10-07',product_sha256='b'*64,
                source_manifest_sha256='c'*64,article_refs=[dict(reason='The original reviewed contract expanded capacity.',title='Original synthetic title')])]),
        selection_diagnostics=dict(membership=dict(status='CANNOT_CONFIRM',gaps=['HK_UNIVERSE_V2_ARTIFACT_MISSING'])),
        market_screen=dict(status='CANNOT_CONFIRM',verified_session='20261007',strict=[],near=[],pending=[],
                           gaps=['SCREEN_PANEL_AUTHORITY_UNVERIFIED'],coverage={}), **FLAGS)


def project(value):
    from v4.manager_research.workspace_daily_channels import build_daily_channels
    return build_daily_channels(value)


def target_scope():
    codes=['HK.00001','HK.00002']
    return dict(status='OWNER_VERIFIED',gaps=[],codes=codes,
        source=dict(market='HK_CONNECT',role='HK_CONNECT_FULL_MARKET_AUTHORITY',
                    source_date='20261008',sha256='f'*64),
        identity=digest(['20261008',codes,'f'*64]),
        membership_semantics='TARGET_DATE_CAPTURED_HK_CONNECT_AUTHORITY_V2',target_trade_date='20261008')


def test_current_announcement_survives_other_channel_and_old_product_gaps():
    source=view();before=deepcopy(source);result=project(source)
    channels={c['channel']:c for c in result['channels']}
    assert channels['ANNOUNCEMENT']['status']=='READY'
    row=channels['ANNOUNCEMENT']['rows'][0]
    assert row['symbol']=='HK.00001'
    assert row['reason']=='The original reviewed contract expanded capacity.'
    assert row['product_sha256']=='b'*64
    assert row['run_id']=='d'*32
    assert channels['HK_CONNECT']['candidate_count'] is None
    assert channels['OVERSOLD']['candidate_count'] is None
    assert source==before


def test_unknown_is_not_a_successful_empty_result():
    source=view();source['announcement_reviewed_analysis']={}
    result=project(source)
    assert all(c['candidate_count'] is None for c in result['channels'])
    assert all(c['natural_run_verified'] is False for c in result['channels'])
    assert all(c['status']=='CANNOT_CONFIRM' for c in result['channels'])


def test_other_publication_cannot_be_relabelled_as_selected_publication():
    source=view();source['date_bindings']['announcement_date']='20261006'
    result=project(source)
    announcement=result['channels'][0]
    assert announcement['rows']==[]
    assert announcement['candidate_count'] is None


def test_connect_rows_are_original_focus_and_exact_target_authority_only():
    source=view();source['selection_diagnostics']['membership']=target_scope()
    source['stocks']=[dict(symbol='HK.00001',name='Focus',why_watch=['Existing focus decision'],
                          connect_eligibility='VERIFIED_TARGET_UNIVERSE'),
                      dict(symbol='HK.00002',name='Background',why_watch=['Existing background'],
                          connect_eligibility='VERIFIED_TARGET_UNIVERSE')]
    source['focus_symbols']=['HK.00001']
    result=project(source)['channels'][1]
    assert [r['symbol'] for r in result['rows']]==['HK.00001']
    assert result['rows'][0]['reason']=='Existing focus decision'


def test_connect_rejects_wrong_source_date_or_identity_and_outside_code():
    source=view();source['selection_diagnostics']['membership']=target_scope()
    source['stocks']=[dict(symbol='HK.00003',why_watch=['Outside actual authority'],
                          connect_eligibility='VERIFIED_TARGET_UNIVERSE')]
    source['focus_symbols']=['HK.00003']
    assert project(source)['channels'][1]['rows']==[]
    source['selection_diagnostics']['membership']['source']['source_date']='20261007'
    assert project(source)['channels'][1]['status']=='CANNOT_CONFIRM'
    source['selection_diagnostics']['membership']=target_scope()
    source['selection_diagnostics']['membership']['identity']='0'*64
    assert project(source)['channels'][1]['status']=='CANNOT_CONFIRM'


def test_connect_does_not_inherit_independent_us_mapping_gap():
    source=view();source['selection_diagnostics']['membership']=target_scope()
    source['selection_diagnostics'].update(status='READY',gaps=[])
    source['gaps']=['US_MAPPING_READER_UNAVAILABLE:ImportError']
    source['stocks']=[dict(symbol='HK.00001',why_watch=['Original independent focus'],
                          connect_eligibility='VERIFIED_TARGET_UNIVERSE')]
    source['focus_symbols']=['HK.00001']
    channel=project(source)['channels'][1]
    assert channel['status']=='READY'
    assert channel['gaps']==[]


def test_connect_requires_its_original_focus_inputs_before_claiming_empty():
    source=view();source['selection_diagnostics']=dict(status='READY',gaps=[],membership=target_scope())
    source['owner_chain']['focus_inputs']=dict(status='PARTIAL',gaps=['RESEARCH_ARCHIVE_READER_NOT_BOUND'])
    channel=project(source)['channels'][1]
    assert channel['status']=='PARTIAL'
    assert channel['candidate_count'] is None
    assert 'RESEARCH_ARCHIVE_READER_NOT_BOUND' in channel['gaps']
    source['owner_chain']['focus_inputs']=dict(status='READY',gaps=[])
    channel=project(source)['channels'][1]
    assert channel['status']=='READY_EMPTY' and channel['candidate_count']==0


def test_oversold_pending_volume_never_appears_as_selected():
    source=view();source['market_screen'].update(status='READY_WITH_GAPS',input_identity='9'*64,
        pending=[{'code':'HK.00001','volume_unit_status':'NOT_PROVEN'}],coverage={'input_candidate_count':1})
    channel=project(source)['channels'][2]
    assert channel['status']=='PARTIAL'
    assert channel['candidate_count'] is None
    assert channel['pending_count']==1
    assert channel['rows']==[]


def test_mismatched_attempt_cannot_authorize_scheduled_or_natural_claim():
    source=view();source['plan_product']=dict(status='CURRENT',run_id='1'*32,execution_kind='SCHEDULED_PREOPEN',sha256='2'*64)
    source['workspace_plan_attempt']=dict(run_id='3'*32,execution_kind='SCHEDULED_PREOPEN',state='SUCCEEDED')
    result=project(source)
    assert all(c['natural_run_verified'] is False for c in result['channels'])
    assert result['channels'][1]['execution_kind']=='READ_ONLY_EXISTING_OWNER_REPLAY'


def test_unsealed_attempt_cannot_authorize_scheduled_run():
    source=view();source['plan_product']=dict(status='CURRENT',run_id='1'*32,
        execution_kind='SCHEDULED_PREOPEN',sha256='2'*64,consumed=True,
        original_owner='ManagerResearchJobService.refresh_workspace_plan')
    source['workspace_plan_attempt']=dict(run_id='1'*32,execution_kind='SCHEDULED_PREOPEN',
        target_trade_date='20261008',owner='ManagerResearchJobService.refresh_workspace_plan',state='SUCCEEDED')
    assert project(source)['channels'][1]['execution_kind']=='READ_ONLY_EXISTING_OWNER_REPLAY'


def test_oversold_keeps_original_group_reason():
    source=view();source['market_screen'].update(status='READY',input_identity='9'*64,gaps=[],
        strict=[dict(code='HK.00001',name='Synthetic',reason_for_group='Original two verified gates')])
    assert project(source)['channels'][2]['rows'][0]['reason']=='Original two verified gates'


def test_daily_projection_does_not_duplicate_source_bodies_or_product_rows():
    source=view();body='SYNTHETIC_BODY_'*10000
    reference=source['announcement_reviewed_analysis']['research_references'][0]
    reference['article_refs'][0]['body']=body
    source['announcement_reviewed_analysis']['products'][0]['research_references']=[deepcopy(reference)]
    source['selection_diagnostics']['membership']=target_scope()
    source['stocks']=[dict(symbol='HK.00001',why_watch=['Original focus'],connect_eligibility='VERIFIED_TARGET_UNIVERSE',
        evidence=[dict(card_id='original-id',body=body,source_sha256='7'*64)])]
    source['focus_symbols']=['HK.00001']
    import json
    result=project(source)
    assert body not in json.dumps(result)
    assert result['channels'][1]['rows'][0]['source_refs'][0]['source_sha256']=='7'*64
