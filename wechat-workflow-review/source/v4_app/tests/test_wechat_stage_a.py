"""Stage A: synthetic report-only bytes + separate synthetic/security cases.
No provider, OCR, stock pool, Stage producer or V4 business-module replacement.
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

FIXTURE = Path(__file__).parent / 'fixtures/wechat_stage_a'
REPORT_SHA = 'f9921ca25bf4aa9fd5e3e1829f60802f6249fd0a303506b3192560c2d8453236'


def api():
    spec = importlib.util.find_spec('infrastructure.wechat_research_archive')
    assert spec is not None, 'Stage A archive reader is not implemented'
    mod = importlib.import_module('infrastructure.wechat_research_archive')
    command = importlib.import_module('ops.index_wechat_research')
    return mod, command


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return sha(path.read_bytes())


def tree_hash(root):
    return {str(p.relative_to(root)): sha(p.read_bytes()) for p in root.rglob('*') if p.is_file() and not p.is_symlink()}


@pytest.fixture
def env(tmp_path):
    # Resolve pytest's platform temp root once; production rejects symlink components.
    tmp_path = tmp_path.resolve()
    archive, index = tmp_path/'archive', tmp_path/'index'
    shutil.copytree(FIXTURE, archive/'return1')
    m, command = api()
    reader = m.WechatResearchArchive(archive, index)
    return archive, index, reader, command


def register(env, rel='return1/IMPORT_RECEIPT.json', **kwargs):
    archive, _, reader, command = env
    return command.register_return(reader, receipt=rel, receipt_sha256=sha((archive/rel).read_bytes()), **kwargs)


def receipt(env, folder='return1'):
    return json.loads((env[0]/folder/'IMPORT_RECEIPT.json').read_text())


def replace_receipt(env, obj, folder='return1'):
    return write_json(env[0]/folder/'IMPORT_RECEIPT.json', obj)


def new_version(env, folder='return2', body=b'# Synthetic version two\n'):
    archive = env[0]
    (archive/folder).mkdir()
    (archive/folder/'report.md').write_bytes(body)
    rec = receipt(env)
    rec['report_origin'] = 'SYNTHETIC_CONTRACT_TEST'
    rec['received_at'] = '2026-01-04T01:20:03+08:00'
    rec['archived_files']['report'].update(sha256=sha(body), bytes=len(body))
    replace_receipt(env, rec, folder)
    return register(env, f'{folder}/IMPORT_RECEIPT.json')


def test_synthetic_report_only_is_readable_and_unbound(env):
    before = tree_hash(env[0])
    assert sha((FIXTURE/'report.md').read_bytes()) == REPORT_SHA
    result = register(env)
    listed = env[2].list_materials(date='20260102')
    assert listed['total'] == 1
    assert listed['items'][0]['record_id'] == result['record_id']
    detail = env[2].detail(result['record_id'])
    assert detail['report']['content'] == (FIXTURE/'report.md').read_text()
    card = detail['material']
    assert card['missing_artifacts'] == ['coverage.csv', 'mentions.csv', 'unmapped.csv', 'summary.json']
    assert card['states']['archive'] == 'REPORT_ONLY_ARCHIVED'
    assert card['states']['input_binding'] == 'LEGACY_INPUT_UNVERIFIED'
    assert card['states']['structure'] == 'MISSING'
    assert card['states']['research_review'] == 'NOT_EVALUATED_STAGE_A'
    assert card['article']['title'] == 'Synthetic report-only fixture'
    assert card['article']['published_at'] is None and card['article']['account'] is None
    assert card['identity']['return_id'] is None and card['identity']['input_digest'] is None
    assert card['received_at'] == '2026-01-03T16:20:03+08:00'
    assert card['available_at'] is None
    assert all(k not in detail for k in ('events', 'mentions', 'candidates', 'stock_pool'))
    assert tree_hash(env[0]) == before


def test_duplicate_receipt_and_identical_content_do_not_add_version(env):
    first = register(env)
    second = register(env)
    assert second['idempotent'] is True and first['record_id'] == second['record_id']
    shutil.copytree(env[0]/'return1', env[0]/'repeat')
    rec = receipt(env, 'repeat')
    rec['received_at'] = '2026-01-05T16:20:03+08:00'
    replace_receipt(env, rec, 'repeat')
    duplicate = register(env, 'repeat/IMPORT_RECEIPT.json')
    assert duplicate['record_id'] == first['record_id']
    assert env[2].list_materials()['total'] == 1
    assert env[2].detail(first['record_id'])['material']['received_at'] == '2026-01-03T16:20:03+08:00'


def test_new_version_and_pagination_keep_old_bytes(env):
    first = register(env)
    before = tree_hash(env[0]/'return1')
    second = new_version(env)
    assert first['record_id'] != second['record_id']
    page = env[2].list_materials(limit=1)
    assert page['total'] == 2 and len(page['items']) == 1 and page['next_cursor']
    page2 = env[2].list_materials(limit=1, cursor=page['next_cursor'])
    assert page2['items'][0]['record_id'] != page['items'][0]['record_id']
    assert env[2].detail(first['record_id'])['report']['content'].encode() == (FIXTURE/'report.md').read_bytes()
    assert tree_hash(env[0]/'return1') == before


def test_cursor_rejects_changed_query_or_revision(env):
    register(env); new_version(env)
    cursor = env[2].list_materials(limit=1)['next_cursor']
    with pytest.raises(api()[0].ArchiveError, match='CURSOR'):
        env[2].list_materials(limit=1, q='other', cursor=cursor)
    new_version(env, 'return3', b'third')
    with pytest.raises(api()[0].ArchiveError, match='CURSOR'):
        env[2].list_materials(limit=1, cursor=cursor)


def test_dates_are_not_backfilled_and_query_fields_are_validated(env):
    register(env)
    assert env[2].list_materials(date='20260102', date_basis='article')['total'] == 1
    assert env[2].list_materials(date='20260102', date_basis='received')['total'] == 0
    assert env[2].list_materials(date='20260103', date_basis='received')['total'] == 1
    assert env[2].list_materials(q='mp.weixin.qq.com/s/synthetic')['total'] == 1
    for kw in ({'date':'20261340'}, {'date_basis':'available'}, {'limit':0}, {'limit':51}):
        with pytest.raises(api()[0].ArchiveError): env[2].list_materials(**kw)


@pytest.mark.parametrize('field,value', [('received_at','2026-01-03T10:00:00'), ('received_at','<redacted>'), ('published_at','2026-01-02')])
def test_bad_or_naive_time_is_explicitly_unknown(env, field, value):
    rec = receipt(env)
    if field == 'published_at': rec['binding'][field] = value
    else: rec[field] = value
    replace_receipt(env, rec)
    r = register(env)
    card = env[2].detail(r['record_id'])['material']
    target = card['article'] if field == 'published_at' else card
    assert target[field] is None
    assert any(field.upper() in reason for reason in card['cannot_confirm'])
    assert card['available_at'] is None


def test_missing_and_changed_original_report_fail_closed_without_losing_card(env):
    r = register(env)
    p = env[0]/'return1/report.md'
    p.write_bytes(b'tampered')
    d = env[2].detail(r['record_id'])
    assert d['report']['content'] is None and d['report']['status'] == 'HASH_MISMATCH'
    assert d['material']['states']['archive'] == 'REPORT_UNAVAILABLE'
    with pytest.raises(api()[0].ArchiveError, match='HASH_MISMATCH'):
        env[2].artifact(r['record_id'], 'report')
    p.unlink()
    assert env[2].detail(r['record_id'])['report']['status'] == 'SOURCE_MISSING'
    assert env[2].list_materials()['total'] == 1


def test_receipt_tamper_blocks_detail_and_file(env):
    r = register(env)
    rec = receipt(env); rec['binding']['package_id'] = 'other'
    replace_receipt(env, rec)
    d = env[2].detail(r['record_id'])
    assert d['status'] == 'QUARANTINED' and d['report']['content'] is None
    with pytest.raises(api()[0].ArchiveError): env[2].artifact(r['record_id'], 'report')


@pytest.mark.parametrize('bad', ['../secret.md', '/etc/passwd', 'x/../../secret', 'file:///etc/passwd', 'x\\report.md', 'report.md\x00'])
def test_receipt_paths_never_escape_archive(env, bad):
    rec = receipt(env); rec['archived_files']['report']['archived_filename'] = bad
    replace_receipt(env, rec)
    with pytest.raises(api()[0].ArchiveError): register(env)
    assert not env[1].exists()


def test_symlink_leaf_and_parent_are_rejected(env):
    original = env[0]/'return1/report.md'
    outside = env[0].parent/'secret.md'; outside.write_bytes(original.read_bytes())
    original.unlink(); original.symlink_to(outside)
    with pytest.raises(api()[0].ArchiveError): register(env)
    original.unlink(); original.write_bytes(outside.read_bytes())
    r = register(env)
    real = env[0].parent/'moved'; (env[0]/'return1').rename(real)
    (env[0]/'return1').symlink_to(real, target_is_directory=True)
    assert env[2].detail(r['record_id'])['status'] == 'QUARANTINED'


def test_symlink_index_and_source_roots_are_rejected(env):
    link = env[0].parent/'archive_link'; link.symlink_to(env[0], target_is_directory=True)
    m, command = api()
    reader = m.WechatResearchArchive(link, env[1])
    with pytest.raises(m.ArchiveError):
        command.register_return(reader, receipt='return1/IMPORT_RECEIPT.json', receipt_sha256=sha((FIXTURE/'IMPORT_RECEIPT.json').read_bytes()))
    env[1].symlink_to(env[0], target_is_directory=True)
    with pytest.raises(m.ArchiveError): register(env)


def test_wrong_expected_sha_and_unsafe_flags_are_rejected(env):
    with pytest.raises(api()[0].ArchiveError, match='HASH_MISMATCH'):
        env[3].register_return(env[2], receipt='return1/IMPORT_RECEIPT.json', receipt_sha256='0'*64)
    rec = receipt(env); rec['orders_sent'] = True; replace_receipt(env, rec)
    with pytest.raises(api()[0].ArchiveError, match='SAFETY'):
        register(env)


@pytest.mark.parametrize('key', ['package_id', 'input_digest'])
def test_report_header_mixed_input_is_rejected(env, key):
    rec = receipt(env)
    hdr = {'package_id':rec['binding']['package_id'], 'input_digest':None, 'return_id':'r1'}
    hdr[key] = 'different'
    b = ('<!-- wechat-return: '+json.dumps(hdr)+' -->\n# test').encode()
    (env[0]/'return1/report.md').write_bytes(b)
    rec['archived_files']['report'].update(sha256=sha(b),bytes=len(b)); replace_receipt(env,rec)
    with pytest.raises(api()[0].ArchiveError, match='IDENTITY_CONFLICT'): register(env)


def test_unrelated_summary_cannot_supply_return_identity(env):
    rec = receipt(env)
    obj = {'package_id':'different', 'input_digest':'d'*64, 'return_id':'r1', 'url':rec['binding']['article_url']}
    p = env[0]/'return1/summary.json'; dig=write_json(p,obj)
    rec['archived_files']['summary']={'archived_filename':'summary.json','sha256':dig,'bytes':p.stat().st_size}
    replace_receipt(env, rec)
    with pytest.raises(api()[0].ArchiveError, match='IDENTITY_CONFLICT'): register(env)


def bound_manifest(env):
    """Synthetic *real schema*, not a invented runtime provider/stub."""
    rec = receipt(env)
    ident = {'original_url': rec['binding']['article_url'], 'article_id':'synthetic-stage-a-fixture',
             'title':rec['binding']['article_title'],'account':'合成测试公众号', 'biz':'synthetic',
             'published_at':'2026-01-02T22:53:30+08:00', 'article_date':'20260102',
             'content_hash':rec['binding']['content_hash'], 'source_run_id':rec['binding']['source_run_id']}
    sources=[]
    for sid,path,data in [('BODY','BODY.md',b'body'),('OCR_FULL','OCR_FULL.md',b'ocr'),('IMAGE_MANIFEST','manifest.csv',b'idx\n')]:
        p=env[0]/'frozen'/path; p.parent.mkdir(exist_ok=True); p.write_bytes(data)
        sources.append({'source_id':sid, 'path':path,'bytes':len(data),'sha256':sha(data)})
    descriptor={'identity':ident, 'raw_html_sha256':'a'*64, 'sources':sources}
    dig=sha(json.dumps(descriptor, ensure_ascii=False, sort_keys=True,separators=(',',':')).encode())
    manifest={'manifest_version':'chat-materials-ocr-v2','package_id':'synthetic-v2','input_descriptor':descriptor,
              'input_digest':dig, 'total_images':0, **ident}
    p=env[0]/'frozen/manifest.json'; manifest_sha=write_json(p,manifest)
    rec['report_origin'] = 'SYNTHETIC_CONTRACT_TEST'
    rec['binding'].update(package_id='synthetic-v2',input_digest=dig,package_identity_status='VERIFIED',article_id=ident['article_id'],image_count=0)
    replace_receipt(env,rec)
    return manifest_sha, manifest


def test_bound_manifest_supplies_metadata_and_safe_source_access(env):
    dig, _ = bound_manifest(env)
    r = register(env, manifest='frozen/manifest.json', manifest_sha256=dig)
    d = env[2].detail(r['record_id'])
    assert d['material']['article']['account']=='合成测试公众号'
    assert d['material']['article']['published_at']=='2026-01-02T22:53:30+08:00'
    assert d['material']['states']['structure']=='MISSING'
    assert env[2].artifact(r['record_id'], 'source_BODY')[0]==b'body'
    # Source removal does not convert report-only to complete or hide the intact report.
    (env[0]/'frozen/BODY.md').unlink()
    assert env[2].detail(r['record_id'])['report']['content'] is not None
    with pytest.raises(api()[0].ArchiveError,match='SOURCE_MISSING'): env[2].artifact(r['record_id'],'source_BODY')


def test_new_manifest_never_binds_legacy_report_by_same_article(env):
    legacy = receipt(env)
    dig, _ = bound_manifest(env)
    replace_receipt(env, legacy)
    with pytest.raises(api()[0].ArchiveError,match='IDENTITY_CONFLICT'):
        register(env, manifest='frozen/manifest.json', manifest_sha256=dig)


def test_manifest_descriptor_and_published_date_conflict_rejected(env):
    _, mf = bound_manifest(env)
    mf['account']='different'
    dig=write_json(env[0]/'frozen/manifest.json',mf)
    with pytest.raises(api()[0].ArchiveError, match='IDENTITY_CONFLICT'):
        register(env,manifest='frozen/manifest.json',manifest_sha256=dig)


def test_unconfigured_and_missing_index_are_explicit_and_read_only(tmp_path):
    m,_=api()
    root=tmp_path.resolve()/'not_created'
    assert m.WechatResearchArchive(None,root).list_materials()['status']=='NOT_CONFIGURED'
    assert not root.exists()
    archive=tmp_path.resolve()/'archive'; archive.mkdir()
    assert m.WechatResearchArchive(archive,root).list_materials()['status']=='NOT_INDEXED'
    assert not root.exists()


def test_changed_or_corrupt_index_is_not_silently_empty(env):
    r=register(env)
    p=env[1]/'records'/f'{r["record_id"]}.json'
    p.write_bytes(b'bad json')
    with pytest.raises(api()[0].ArchiveError,match='INDEX_INVALID'): env[2].list_materials()


@pytest.fixture
def client(env):
    register(env)
    router_mod=importlib.import_module('apps.api.v35_api.wechat_research_router')
    app=FastAPI()
    # Real new router only. The unavailable full create_app is NOT replaced/mocked.
    app.include_router(router_mod.create_wechat_research_router(env[2]),prefix='/api/v3/research')
    with TestClient(app) as c: yield c


def test_real_sample_asgi_contract_and_download(client, env):
    base='/api/v3/research/wechat/materials'
    before=tree_hash(env[0]),tree_hash(env[1])
    res=client.get(base,params={'date':'20260102'})
    assert res.status_code==200 and res.json()['total']==1
    rid=res.json()['items'][0]['record_id']
    d=client.get(f'{base}/{rid}').json()
    assert d['material']['missing_artifacts']==['coverage.csv','mentions.csv','unmapped.csv','summary.json']
    file=client.get(f'{base}/{rid}/artifacts/report')
    assert file.content==(FIXTURE/'report.md').read_bytes()
    assert file.headers['x-content-type-options']=='nosniff'
    assert 'attachment;' in file.headers['content-disposition']
    assert "sandbox" in file.headers['content-security-policy']
    for payload in (res.json(),d):
        assert payload['production_allowed'] is False
        assert payload['buy_gate_updated'] is False and payload['orders_sent'] is False
    assert 'input_path' not in res.text+d.__str__()
    assert '<LOCAL_HOME>' not in res.text+json.dumps(d,ensure_ascii=False)
    assert before==(tree_hash(env[0]),tree_hash(env[1]))
    assert client.post(base).status_code==405


@pytest.mark.parametrize('params', [{'date':'20260230'},{'date_basis':'available'},{'limit':0},{'limit':51},{'cursor':'bad'},{'q':'x'*501}])
def test_invalid_api_queries_fail_explicitly(client,params):
    assert client.get('/api/v3/research/wechat/materials',params=params).status_code==422


@pytest.mark.parametrize('url', ['/api/v3/research/wechat/materials/not-an-id',
    '/api/v3/research/wechat/materials/'+'a'*64,
    '/api/v3/research/wechat/materials/'+'a'*64+'/artifacts/%2e%2e%2fsecret',])
def test_arbitrary_api_paths_cannot_access_files(client,url):
    assert client.get(url).status_code in (404,422)


def test_executable_text_never_becomes_html_response(client,env):
    payload=b'<script>window.BAD=1</script>\n[bad](javascript:alert(1))\n<img src="file:///etc/passwd">\n{{ window.BAD }}'
    r=new_version(env,body=payload)
    base='/api/v3/research/wechat/materials/'+r['record_id']
    d=client.get(base)
    assert d.headers['content-type'].startswith('application/json')
    assert d.json()['report']['content']==payload.decode()
    file=client.get(base+'/artifacts/report')
    assert file.headers['content-type'].startswith('text/plain')
    assert file.content==payload


def test_no_script_imports_or_mutations_of_pool_or_stage():
    root=Path(__file__).parents[1]
    for rel in ['infrastructure/wechat_research_archive.py','ops/index_wechat_research.py','apps/api/v35_api/wechat_research_router.py']:
        text=(root/rel).read_text()
        for forbidden in ['StageRunner','StageInputProducer','preselection_pool_store','preselection_overlay_store','ensure_selection','requests.','httpx.','subprocess.']:
            assert forbidden not in text


def test_input_manifest_image_count_mismatch_rejected(env):
    dig,_ = bound_manifest(env)
    rec=receipt(env); rec['binding']['image_count']=12; replace_receipt(env,rec)
    with pytest.raises(api()[0].ArchiveError,match='IDENTITY_CONFLICT'):
        register(env,manifest='frozen/manifest.json',manifest_sha256=dig)


def test_same_package_id_cannot_mean_another_article(env):
    register(env)
    shutil.copytree(env[0]/'return1',env[0]/'other')
    rec=receipt(env,'other'); rec['binding']['article_url']='https://mp.weixin.qq.com/s/different'
    replace_receipt(env,rec,'other')
    with pytest.raises(api()[0].ArchiveError,match='PACKAGE_ID_CONFLICT'):
        register(env,'other/IMPORT_RECEIPT.json')


def test_client_return_id_cannot_be_reused_for_different_report(env):
    rec=receipt(env)
    hdr={'package_id':rec['binding']['package_id'],'input_digest':None,'return_id':'same'}
    body=('<!-- wechat-return: '+json.dumps(hdr)+' -->\n# one').encode()
    (env[0]/'return1/report.md').write_bytes(body)
    rec['archived_files']['report'].update(bytes=len(body),sha256=sha(body)); replace_receipt(env,rec)
    register(env)
    with pytest.raises(api()[0].ArchiveError,match='RETURN_ID_CONFLICT'):
        new_version(env,body=body.replace(b'one',b'two'))


def test_return_id_conflict_does_not_depend_on_binding_equality(env):
    rec = receipt(env)
    rec['binding']['package_id'] = 'package-one'
    rec['binding']['source_run_id'] = 'run-one'
    rec['binding']['package_sha256_declared'] = 'a' * 64
    rec['binding']['package_sha256_observed'] = 'a' * 64
    rec['binding']['package_sha256_status'] = 'VERIFIED'
    rec['binding']['package_identity_status'] = 'VERIFIED'
    rec['binding']['input_digest'] = 'b' * 64
    rec['local_acceptance']['input_binding_valid'] = True
    body = ('<!-- wechat-return: ' + json.dumps({'return_id': 'same', 'package_id': 'package-one'}) + ' -->\n# one').encode()
    (env[0] / 'return1/report.md').write_bytes(body)
    rec['archived_files']['report'].update(bytes=len(body), sha256=sha(body))
    replace_receipt(env, rec)
    register(env)

    shutil.copytree(env[0] / 'return1', env[0] / 'different-binding')
    other = receipt(env, 'different-binding')
    body_two = ('<!-- wechat-return: ' + json.dumps({'return_id': 'same', 'package_id': 'package-two',
                                                       'input_digest': 'd' * 64}) + ' -->\n# two').encode()
    (env[0] / 'different-binding/report.md').write_bytes(body_two)
    other['archived_files']['report'].update(bytes=len(body_two), sha256=sha(body_two))
    other['binding']['package_id'] = 'package-two'
    other['binding']['source_run_id'] = 'run-two'
    other['binding']['package_sha256_declared'] = 'c' * 64
    other['binding']['package_sha256_observed'] = 'c' * 64
    other['binding']['input_digest'] = 'd' * 64
    other['binding']['article_title'] = 'different binding'
    replace_receipt(env, other, 'different-binding')
    with pytest.raises(api()[0].ArchiveError, match='RETURN_ID_CONFLICT'):
        register(env, 'different-binding/IMPORT_RECEIPT.json')


def test_source_attachment_path_is_bounded_even_with_trusted_manifest(env):
    _,mf=bound_manifest(env)
    mf['input_descriptor']['sources'][0]['path']='../secret'
    mf['input_digest']=sha(json.dumps(mf['input_descriptor'],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
    rec=receipt(env); rec['binding']['input_digest']=mf['input_digest']; replace_receipt(env,rec)
    dig=write_json(env[0]/'frozen/manifest.json',mf)
    with pytest.raises(api()[0].ArchiveError):
        register(env,manifest='frozen/manifest.json',manifest_sha256=dig)


def test_manifest_changed_after_index_quarantines_even_if_report_intact(env):
    dig,_=bound_manifest(env)
    r=register(env,manifest='frozen/manifest.json',manifest_sha256=dig)
    (env[0]/'frozen/manifest.json').write_bytes(b'{}')
    assert env[2].detail(r['record_id'])['status']=='QUARANTINED'


def test_receipt_missing_does_not_silently_remove_indexed_version(env):
    r=register(env)
    (env[0]/'return1/IMPORT_RECEIPT.json').unlink()
    assert env[2].list_materials()['total']==1
    assert env[2].detail(r['record_id'])['status']=='QUARANTINED'


@pytest.mark.parametrize('url', ['javascript:alert(1)','data:text/html,test','file:///etc/passwd','//evil.test','https://ok.test@evil.test','https://ok.test\\@evil.test','https://ok.test/\n'])
def test_dangerous_original_urls_never_become_clickable(env,url):
    rec=receipt(env); rec['binding']['article_url']=url; replace_receipt(env,rec)
    r=register(env)
    assert env[2].detail(r['record_id'])['material']['article']['url'] is None


def test_index_snapshot_accidental_mutation_detected(env):
    r=register(env)
    p=env[1]/'records'/f'{r["record_id"]}.json'
    reg=json.loads(p.read_text()); reg['snapshot']['received_at']='2000-01-01T00:00:00+08:00'
    write_json(p,reg)
    with pytest.raises(api()[0].ArchiveError,match='INDEX_INVALID'):
        env[2].list_materials()


def test_receipt_self_claim_cannot_promote_report_only_or_research(env):
    rec=receipt(env)
    rec.update(status='REPORT_AND_STRUCTURED_ARCHIVED', structured_validation_status='COMPLETE', available_at='2026-09-17T00:00:00+08:00')
    rec['local_acceptance'].update(semantic_research_accepted=True, independent_review_scope=['self-claim'],structure_valid=True)
    replace_receipt(env,rec)
    r=register(env)
    card=env[2].detail(r['record_id'])['material']
    assert card['states']['archive']=='REPORT_ONLY_ARCHIVED'
    assert card['states']['structure']=='MISSING'
    assert card['states']['research_review']=='NOT_EVALUATED_STAGE_A'
    assert card['available_at'] is None
    assert card['receipt_claims']['semantic_research_accepted'] is True


def test_verified_input_package_does_not_mean_report_is_bound(env):
    dig,_=bound_manifest(env)
    r=register(env,manifest='frozen/manifest.json',manifest_sha256=dig)
    assert env[2].detail(r['record_id'])['material']['states']['input_binding']=='RETURN_UNBOUND'


def test_invalid_utf8_is_not_silently_reconstructed(env):
    rec=receipt(env); data=b'\xff\xfe\x00'
    (env[0]/'return1/report.md').write_bytes(data)
    rec['archived_files']['report'].update(bytes=len(data),sha256=sha(data));replace_receipt(env,rec)
    r=register(env)
    d=env[2].detail(r['record_id'])
    assert d['report']['status']=='TEXT_UNREADABLE' and d['report']['content'] is None
    assert env[2].list_materials()['items'][0]['states']['archive']=='REPORT_UNAVAILABLE'
    assert env[2].artifact(r['record_id'],'report')[0]==data


def test_concurrent_duplicate_registration_creates_one_version(env):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    barrier = Barrier(8)
    def register_concurrently(_):
        barrier.wait()
        return register(env)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results=list(executor.map(register_concurrently,range(8)))
    assert len({r['record_id'] for r in results})==1
    assert sum(not r['idempotent'] for r in results)==1
    assert env[2].list_materials()['total']==1


def test_index_must_not_be_inside_raw_archive(env):
    m,c=api(); reader=m.WechatResearchArchive(env[0],env[0]/'derived')
    with pytest.raises(m.ArchiveError,match='INDEX_MUST_NOT_OVERLAP_ARCHIVE'):
        c.register_return(reader,receipt='return1/IMPORT_RECEIPT.json',receipt_sha256=sha((FIXTURE/'IMPORT_RECEIPT.json').read_bytes()))
    assert not (env[0]/'derived').exists()


def test_json_duplicate_keys_and_huge_artifact_are_rejected(env):
    p=env[0]/'return1/IMPORT_RECEIPT.json'
    p.write_bytes(b'{"binding":{},"binding":{}}')
    with pytest.raises(api()[0].ArchiveError,match='INVALID_RECEIPT'):register(env)
    shutil.copyfile(FIXTURE/'IMPORT_RECEIPT.json',p)
    rec=receipt(env); rec['archived_files']['report']['bytes']=1<<40; replace_receipt(env,rec)
    with pytest.raises(api()[0].ArchiveError,match='INVALID_ARTIFACT_SIZE'):register(env)


def test_frozen_manifest_itself_is_traceable_as_raw_evidence(env):
    dig,_=bound_manifest(env)
    r=register(env,manifest='frozen/manifest.json',manifest_sha256=dig)
    assert env[2].artifact(r['record_id'],'source_INPUT_MANIFEST')[0]==(env[0]/'frozen/manifest.json').read_bytes()


def test_missing_package_ids_do_not_merge_unrelated_legacy_reports(env):
    rec = receipt(env)
    rec['binding']['package_id'] = None
    replace_receipt(env, rec)
    first = register(env)
    shutil.copytree(env[0]/'return1', env[0]/'unrelated')
    other = receipt(env, 'unrelated')
    other['binding']['article_url'] = 'https://mp.weixin.qq.com/s/unrelated'
    other['binding']['article_title'] = 'Unrelated legacy article'
    replace_receipt(env, other, 'unrelated')
    second = register(env, 'unrelated/IMPORT_RECEIPT.json')
    assert first['record_id'] != second['record_id']
    assert env[2].list_materials()['total'] == 2
    assert env[2].detail(second['record_id'])['material']['states']['input_binding'] == 'LEGACY_INPUT_UNVERIFIED'


def test_invalid_summary_json_cannot_display_claimed_complete_structure(env):
    rec = receipt(env)
    for role in ['coverage', 'mentions', 'unmapped', 'summary']:
        data = b'{broken JSON' if role == 'summary' else b'header\n'
        name = role + ('.json' if role == 'summary' else '.csv')
        (env[0]/'return1'/name).write_bytes(data)
        rec['archived_files'][role] = {'archived_filename': name, 'bytes': len(data), 'sha256': sha(data)}
    rec['missing_artifacts'] = []
    rec['status'] = 'REPORT_AND_STRUCTURED_ARCHIVED'
    rec['structured_validation_status'] = 'COMPLETE'
    replace_receipt(env, rec)
    result = register(env)
    card = env[2].detail(result['record_id'])['material']
    assert card['states']['structure'] == 'INVALID_SUMMARY_JSON'
    assert 'SUMMARY_JSON_UNREADABLE' in card['cannot_confirm']
    assert card['receipt_claims']['structure'] == 'COMPLETE'
    assert card['states']['research_review'] == 'NOT_EVALUATED_STAGE_A'


def test_invalid_summary_does_not_downgrade_verified_input_binding(env):
    rec = receipt(env)
    for role in ['coverage', 'mentions', 'unmapped', 'summary']:
        data = b'{broken JSON' if role == 'summary' else b'header\n'
        name = role + ('.json' if role == 'summary' else '.csv')
        (env[0] / 'return1' / name).write_bytes(data)
        rec['archived_files'][role] = {'archived_filename': name, 'bytes': len(data), 'sha256': sha(data)}
    rec['missing_artifacts'] = []
    rec['status'] = 'REPORT_AND_STRUCTURED_ARCHIVED'
    rec['structured_validation_status'] = 'COMPLETE'
    rec['binding'].update(package_id='package-bound', source_run_id='run-bound',
                          package_sha256_declared='a' * 64,
                          package_sha256_observed='a' * 64,
                          package_sha256_status='VERIFIED', input_digest='b' * 64,
                          package_identity_status='VERIFIED')
    rec['local_acceptance']['input_binding_valid'] = True
    replace_receipt(env, rec)
    result = register(env)
    card = env[2].detail(result['record_id'])['material']
    assert card['states']['structure'] == 'INVALID_SUMMARY_JSON'
    assert card['states']['input_binding'] == 'RECEIPT_BOUND'


def test_verified_identity_without_importer_provenance_stays_unbound(env):
    rec = receipt(env)
    rec['missing_artifacts'] = []
    rec['status'] = 'REPORT_AND_STRUCTURED_ARCHIVED'
    rec['structured_validation_status'] = 'COMPLETE'
    rec['binding'].update(package_id=None, source_run_id=None,
                          package_sha256_declared=None,
                          package_sha256_observed=None,
                          package_sha256_status=None, input_digest='b' * 64,
                          package_identity_status='VERIFIED')
    rec['local_acceptance']['input_binding_valid'] = True
    for role in ['coverage', 'mentions', 'unmapped', 'summary']:
        name = role + ('.json' if role == 'summary' else '.csv')
        data = b'{}\n' if role == 'summary' else b'header\n'
        (env[0] / 'return1' / name).write_bytes(data)
        rec['archived_files'][role] = {'archived_filename': name, 'bytes': len(data), 'sha256': sha(data)}
    replace_receipt(env, rec)
    result = register(env)
    card = env[2].detail(result['record_id'])['material']
    assert card['states']['input_binding'] == 'RETURN_UNBOUND'
