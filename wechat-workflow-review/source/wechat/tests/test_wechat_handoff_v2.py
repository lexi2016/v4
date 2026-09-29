"""Offline adversarial regressions. No network, OCR, or production state."""
from __future__ import annotations
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import wechat_chat_handoff as h
from wechat_common import article_body_text
from test_wechat_chat_handoff import _make_run, _write_json, _rewrite_zip


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_csv(path, fields, rows):
    with path.open('w', encoding='utf-8', newline='') as out:
        w = csv.DictWriter(out, fieldnames=fields, lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


def real_run(tmp_path, fmt='JPEG'):
    run = _make_run(tmp_path)
    rows = list(csv.DictReader((run/'wechat_article_image_manifest.csv').read_text().splitlines()))
    records = json.loads((run/'windows_ocr_results.json').read_text())
    for idx, row in enumerate(rows, 1):
        old = run/'wechat_article_images'/f'img_{idx:02d}.jpg'
        suffix = {'JPEG':'.jpg', 'PNG':'.png', 'WEBP':'.webp'}[fmt]
        image = old.with_suffix(suffix)
        if old != image:
            old.unlink()
        Image.new('RGB', (10,20), (idx,0,0)).save(image, format=fmt)
        data = image.read_bytes()
        row.update(local_path=str(image), sha256=sha(data), image_sha256=sha(data), bytes=str(len(data)))
        records[idx-1].update(path=str(image), name=image.name, image_sha256=sha(data))
    write_csv(run/'wechat_article_image_manifest.csv', list(rows[0]), rows)
    _write_json(run/'windows_ocr_results.json', records)
    return run


def pack(tmp, run, package_id='fixture_package_v1', suffix='package'):
    out = tmp/suffix
    receipt = h.package_run(run, out, package_id)
    return out/receipt['zip']['path'], receipt


def import_args(tmp, run, z, receipt):
    p = tmp/'report.md'
    p.write_text('original user report\n', encoding='utf-8')
    return dict(source_run_value=run, package_id_value=receipt['package_id'],
                package_zip_value=z, package_sha_value=sha(z.read_bytes()),
                report_value=p, coverage_value='', mentions_value='', unmapped_value='',
                summary_value='', out_dir_value=tmp/'returns')


def complete_return(tmp, receipt):
    """One occurrence per (source, issuer, listing); count metadata is explicit."""
    paths = {k:tmp/(k+('.json' if k=='summary' else '.md' if k=='report' else '.csv'))
             for k in ('report','coverage','mentions','unmapped','summary')}
    digest = receipt.get('input_digest', receipt['manifest_sha256'])
    header = {'input_digest':digest, 'return_id':'ret_001', 'package_id':receipt['package_id']}
    paths['report'].write_text('<!-- wechat-return: '+json.dumps(header)+' -->\n# Research\nEvidence and limitations.\n',encoding='utf-8')
    coverage = []
    for s in ['BODY','IMAGE001','IMAGE002','IMAGE003']:
        coverage.append(dict(source_index=s,event='EVENT' if s=='IMAGE001' else 'NO_EVENT',subject='Fixture',claim='read',date='',number='',unit='',source_grade='UNKNOWN',uncertainty='',original_checked='false',original_scope='NOT_APPLICABLE' if s=='BODY' else 'NONE',text_read='true'))
    write_csv(paths['coverage'], list(coverage[0]), coverage)
    mention = dict(market='A',code='000001.SZ',name='Fixture Co',source_index='IMAGE001',mapping_status='CONFIRMED',source_named_or_derived='SOURCE_NAMED',claim_context='fixture',entity_id='issuer_001',source_name='Fixture',listing_origin='NAME_RESOLVED')
    write_csv(paths['mentions'], list(mention), [mention])
    write_csv(paths['unmapped'], ['name','reason','source_index'], [])
    summary = dict(schema_version=2,url='https://mp.weixin.qq.com/s/fixture-token',package_id=receipt['package_id'],manifest_sha256=receipt['manifest_sha256'],input_digest=digest,return_id='ret_001',reading_mode='OCR_RISK_REVIEW',article_date='20260917',image_count=3,coverage_counts={'total':4,'EVENT':1,'NO_EVENT':3,'UNREADABLE':0},mentions_counts={'total':1,'A':1,'BJ':0,'HK':0,'entities':1,'source_named_entities':1,'supplemental_listing_rows':0},status='COMPLETE_WITH_ALL_SOURCES',missing_inputs=[],production_allowed=False,buy_gate_updated=False,orders_sent=False)
    if receipt.get('review_contract_version'):
        summary['review_contract_version'] = receipt['review_contract_version']
        summary['event_dispositions'] = {
            row['source_index']: 'PROMOTE' for row in coverage if row['event'] == 'EVENT'
        }
    summary['artifact_sha256'] = {paths[k].name:sha(paths[k].read_bytes()) for k in ('report','coverage','mentions','unmapped')}
    _write_json(paths['summary'], summary)
    return paths


def reseal(paths):
    value=json.loads(paths['summary'].read_text())
    value['artifact_sha256']={paths[k].name:sha(paths[k].read_bytes()) for k in ('report','coverage','mentions','unmapped')}
    _write_json(paths['summary'],value)


def full_import(tmp, run, z, receipt, paths):
    return h.import_chat_return(source_run_value=run,package_id_value=receipt['package_id'],package_zip_value=z,package_sha_value=sha(z.read_bytes()),report_value=paths['report'],coverage_value=paths['coverage'],mentions_value=paths['mentions'],unmapped_value=paths['unmapped'],summary_value=paths['summary'],out_dir_value=tmp/'returns')


@pytest.mark.parametrize('void', ['<img src="x">', '<img src="x"/>', '<br>', '<hr>', '<input>'])
def test_common_parser_excludes_header_and_footer(void):
    text=article_body_text('HEADER<div id="js_content"><p>first</p>'+void+'<p>second</p></div>OUTSIDE_TICKER')
    assert 'HEADER' not in text and 'OUTSIDE_TICKER' not in text
    assert 'first\n' in text


def test_handoff_parser_does_not_leak_after_bare_img():
    p=h._BodyWithImageMarkers({'x':[1]})
    p.feed('<div id="js_content"><p>first</p><img src="x"><p>second</p></div>OUTSIDE_TICKER')
    assert 'OUTSIDE_TICKER' not in p.text()
    assert p.text().count('[IMAGE001]')==1
    assert '\n' in p.text()


@pytest.mark.parametrize('mutation',['no_time','naive_time','invalid_date','time_date_mismatch'])
def test_package_rejects_unreliable_publication_identity(tmp_path,mutation):
    run=real_run(tmp_path)
    path=run/'wechat_article_intake_summary.json'
    obj=json.loads(path.read_text())
    if mutation=='no_time': obj.pop('raw_publish_time')
    elif mutation=='naive_time': obj['published_at']='2026-09-17T22:53:30'
    elif mutation=='invalid_date': obj['article_date']='20261340'
    else: obj['published_at']='2026-09-16T22:53:30+08:00'
    _write_json(path,obj)
    with pytest.raises(h.HandoffError): pack(tmp_path,run)


@pytest.mark.parametrize('fmt',['PNG','WEBP'])
def test_package_preserves_original_image_format(tmp_path,fmt):
    run=real_run(tmp_path,fmt)
    z,r=pack(tmp_path,run)
    with zipfile.ZipFile(z) as f:
        m=json.loads(f.read('manifest.json'))
        assert m['images'][0]['format']==fmt
        assert f.read(m['images'][0]['path'])==(run/'wechat_article_images'/('img_01.'+fmt.lower())).read_bytes()


def test_fake_jpeg_is_not_decodable(tmp_path):
    run=_make_run(tmp_path)
    image=run/'wechat_article_images/img_01.jpg';image.write_bytes(b"\xff\xd8fake")
    mp=run/'wechat_article_image_manifest.csv';rows=list(csv.DictReader(mp.read_text().splitlines()))
    rows[0].update(sha256=sha(image.read_bytes()), image_sha256=sha(image.read_bytes()), bytes=str(image.stat().st_size))
    write_csv(mp,list(rows[0]),rows)
    with pytest.raises(h.HandoffError,match='decode|image|JPEG'): pack(tmp_path,run)


@pytest.mark.parametrize('changed',['BODY','OCR'])
def test_input_digest_covers_text_and_ocr_not_only_image_manifest(tmp_path,changed):
    run=real_run(tmp_path)
    _,a=pack(tmp_path,run,suffix='a')
    if changed=='BODY':
        p=run/'wechat_article_raw.html';p.write_text(p.read_text().replace('fixture body','different body'))
    else:
        p=run/'windows_ocr_results.json';v=json.loads(p.read_text());v[0]['text']='new corrected OCR';v[0]['text_length']=len(v[0]['text']);_write_json(p,v)
    _,b=pack(tmp_path,run,suffix='b')
    assert a.get('input_digest',a['manifest_sha256'])!=b.get('input_digest',b['manifest_sha256'])


@pytest.mark.parametrize('mode',['deleted','modified'])
def test_zip_body_is_required_and_bound(tmp_path,mode):
    run=real_run(tmp_path);z,r=pack(tmp_path,run)
    kw=import_args(tmp_path,run,z,r)
    with zipfile.ZipFile(z) as f: entries={n:f.read(n) for n in f.namelist()}
    if mode=='deleted': entries.pop('BODY.md')
    else: entries['BODY.md']=b'forged body'
    other=tmp_path/'modified.zip';_rewrite_zip(other,entries)
    with pytest.raises(h.HandoffError):
        h.import_chat_return(**{**kw,'package_zip_value':other,'package_sha_value':sha(other.read_bytes())})


def test_old_frozen_package_survives_mutable_ocr_change(tmp_path):
    run=real_run(tmp_path);z,r=pack(tmp_path,run)
    kw=import_args(tmp_path,run,z,r)
    p=run/'windows_ocr_results.json';v=json.loads(p.read_text());v[0]['text']='later OCR';v[0]['text_length']=9;_write_json(p,v)
    result=h.import_chat_return(**kw)
    assert result['binding']['package_identity_status']=='VERIFIED'
    assert result['status']=='REPORT_ONLY_ARCHIVED'


def test_old_frozen_package_rejects_current_article_identity_change(tmp_path):
    run=real_run(tmp_path);z,r=pack(tmp_path,run)
    intake_path=run/'wechat_article_intake_summary.json'
    intake=json.loads(intake_path.read_text())
    intake.update(
        canonical_url='https://mp.weixin.qq.com/s/another-article',
        title='Another article',
        article_date='20260918',
        published_at='2026-09-18T10:00:00+08:00',
    )
    _write_json(intake_path,intake)
    with pytest.raises(h.HandoffError,match='immutable article identity'):
        h.import_chat_return(**import_args(tmp_path,run,z,r))


def test_v2_package_requires_nonempty_source_run_id_in_both_bindings(tmp_path):
    run=real_run(tmp_path);z,r=pack(tmp_path,run)
    with zipfile.ZipFile(z) as archive:
        entries={name:archive.read(name) for name in archive.namelist()}
    manifest=json.loads(entries['manifest.json'])
    manifest['input_descriptor']['identity'].pop('source_run_id',None)
    manifest.pop('source_run_id',None)
    manifest['input_digest']=sha(h._canonical_json(manifest['input_descriptor']))
    entries['manifest.json']=(json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
    tampered=tmp_path/'missing-source-run-id.zip'
    _rewrite_zip(tampered,entries)
    with pytest.raises(h.HandoffError,match='source_run_id'):
        h.import_chat_return(**{**import_args(tmp_path,run,z,r),
                                'package_zip_value':tampered,
                                'package_sha_value':sha(tampered.read_bytes())})


def test_input_digest_covers_declared_content_hash(tmp_path):
    run=real_run(tmp_path)
    _,first=pack(tmp_path,run,package_id='fixture_content_hash_same',suffix='content-a')
    intake_path=run/'wechat_article_intake_summary.json'
    intake=json.loads(intake_path.read_text())
    intake['content_hash']='changed-declared-content-hash'
    _write_json(intake_path,intake)
    _,second=pack(tmp_path,run,package_id='fixture_content_hash_same',suffix='content-b')
    assert first['input_digest']!=second['input_digest']


def test_v2_complete_positive_and_idempotency(tmp_path):
    run=real_run(tmp_path);z,r=pack(tmp_path,run);paths=complete_return(tmp_path,r)
    first=full_import(tmp_path,run,z,r,paths);second=full_import(tmp_path,run,z,r,paths)
    assert first['status']=='REPORT_AND_STRUCTURED_ARCHIVED'
    assert first==second
    assert first['local_acceptance'].get('input_binding_valid') is True
    assert first['event_dispositions_contract_status']=='PASS'
    assert first['local_acceptance']['semantic_research_accepted'] is False


def test_new_review_contract_is_frozen_and_identity_metadata_comes_from_verified_manifest(tmp_path):
    run=real_run(tmp_path);z,r=pack(tmp_path,run);paths=complete_return(tmp_path,r)
    with zipfile.ZipFile(z) as archive:
        manifest_bytes=archive.read('manifest.json')
        manifest=json.loads(manifest_bytes)
        prompt=archive.read('PROMPT.md').decode('utf-8')
    assert manifest['review_contract_version']==h._REVIEW_CONTRACT_VERSION
    assert manifest['input_descriptor']['review_contract_version']==h._REVIEW_CONTRACT_VERSION
    assert sha(h._canonical_json(manifest['input_descriptor']))==manifest['input_digest']==r['input_digest']
    assert h._REVIEW_CONTRACT_VERSION in prompt
    imported=full_import(tmp_path,run,z,r,paths)
    binding=imported['binding']
    assert binding['account']=='fixture account'
    assert binding['biz']=='fixture-biz'
    assert binding['published_at']==manifest['published_at']
    assert binding['frozen_manifest_member']=='manifest.json'
    assert binding['frozen_manifest_sha256_observed']==sha(manifest_bytes)
    assert binding['frozen_identity_metadata_status']=='VERIFIED_FROM_TRUSTED_FROZEN_MANIFEST'


@pytest.mark.parametrize('bad',['missing_entry','duplicate_key','unknown_index','no_event_index','unreadable_index','invalid_disposition','missing_version','downgraded_version'])
def test_event_dispositions_contract_rejects_incomplete_duplicate_or_downgraded_returns(tmp_path,bad):
    run=real_run(tmp_path);z,r=pack(tmp_path,run);paths=complete_return(tmp_path,r)
    summary=json.loads(paths['summary'].read_text())
    if bad=='missing_entry': summary['event_dispositions'].pop('IMAGE001')
    if bad=='duplicate_key':
        raw=paths['summary'].read_text()
        raw=raw.replace('"event_dispositions": {', '"event_dispositions": {"IMAGE001": "HOLD",', 1)
        assert raw!=paths['summary'].read_text()
        paths['summary'].write_text(raw,encoding='utf-8')
    if bad=='unknown_index': summary['event_dispositions']['IMAGE999']='HOLD'
    if bad=='no_event_index': summary['event_dispositions']['BODY']='HOLD'
    if bad=='unreadable_index':
        coverage=paths['coverage'];rows=list(csv.DictReader(coverage.read_text().splitlines()));fields=list(rows[0])
        rows[3].update(event='UNREADABLE',uncertainty='source unavailable',original_checked='unreadable',original_scope='NONE',text_read='false')
        write_csv(coverage,fields,rows)
        summary['coverage_counts']={'total':4,'EVENT':1,'NO_EVENT':2,'UNREADABLE':1}
        summary['status']='PARTIAL_WITH_UNREADABLE'
        summary['missing_inputs']=['IMAGE003']
        summary['event_dispositions']['IMAGE003']='CANNOT_CONFIRM'
        _write_json(paths['summary'],summary)
        reseal(paths)
    if bad=='invalid_disposition': summary['event_dispositions']['IMAGE001']='NO_EVENT'
    if bad=='missing_version': summary.pop('review_contract_version')
    if bad=='downgraded_version': summary['review_contract_version']='legacy-v2'
    if bad not in {'duplicate_key','unreadable_index'}:
        _write_json(paths['summary'],summary)
    result=full_import(tmp_path,run,z,r,paths)
    assert result['status']=='REPORT_AND_STRUCTURED_INVALID'
    assert 'summary.json' in result['invalid_artifacts']
    assert result['event_dispositions_contract_status']=='INVALID'


def test_old_v2_frozen_package_imports_without_claiming_new_event_check(tmp_path):
    run=real_run(tmp_path);z,r=pack(tmp_path,run)
    with zipfile.ZipFile(z) as archive:
        entries={name:archive.read(name) for name in archive.namelist()}
    manifest=json.loads(entries['manifest.json'])
    manifest.pop('review_contract_version')
    manifest['input_descriptor'].pop('review_contract_version')
    manifest['input_digest']=sha(h._canonical_json(manifest['input_descriptor']))
    entries['manifest.json']=(json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
    entries['PROMPT.md']=b'legacy v2 prompt\n'
    legacy_zip=tmp_path/'legacy-v2.zip';_rewrite_zip(legacy_zip,entries)
    legacy_receipt=dict(r,input_digest=manifest['input_digest'])
    legacy_receipt.pop('review_contract_version')
    paths=complete_return(tmp_path,legacy_receipt)
    result=full_import(tmp_path,run,legacy_zip,legacy_receipt,paths)
    assert result['status']=='REPORT_AND_STRUCTURED_ARCHIVED'
    assert result['event_dispositions_contract_status']=='NOT_RUN_LEGACY_PACKAGE'
    assert result['binding']['review_contract_version']==''


@pytest.mark.parametrize('bad',['missing_cell','empty_checked','invalid_scope','unknown_source','unreadable_no_reason'])
def test_bad_coverage_is_rejected(tmp_path,bad):
    run=real_run(tmp_path);z,r=pack(tmp_path,run);paths=complete_return(tmp_path,r)
    p=paths['coverage'];rows=list(csv.DictReader(p.read_text().splitlines()));fields=list(rows[0])
    if bad=='missing_cell':
        lines=p.read_text().splitlines();lines[2]=lines[2].rsplit(',',1)[0];p.write_text('\n'.join(lines)+'\n')
    else:
        if bad=='empty_checked': rows[1]['original_checked']=''
        if bad=='invalid_scope': rows[1]['original_scope']='FULL'
        if bad=='unknown_source': rows[1]['source_index']='IMAGE999'
        if bad=='unreadable_no_reason': rows[1].update(event='UNREADABLE',text_read='false',original_checked='unreadable')
        write_csv(p,fields,rows)
    reseal(paths)
    result=full_import(tmp_path,run,z,r,paths)
    assert 'coverage.csv' in result['invalid_artifacts']


@pytest.mark.parametrize('bad',['counts','report_mix','csv_mix','digest','header','safety','full_visual_lie','unmapped_no_source','bad_market','bad_code'])
def test_return_binding_and_semantic_claim_limits(tmp_path,bad):
    run=real_run(tmp_path);z,r=pack(tmp_path,run);paths=complete_return(tmp_path,r)
    s=json.loads(paths['summary'].read_text())
    if bad=='counts': s['coverage_counts']['EVENT']=999
    if bad=='digest': s['input_digest']='f'*64
    if bad=='safety': s['orders_sent']=True
    if bad=='full_visual_lie': s['reading_mode']='FULL_ORIGINAL_REVIEW'
    _write_json(paths['summary'],s)
    if bad=='report_mix': paths['report'].write_text('unrelated report')
    if bad=='csv_mix': paths['coverage'].write_text(paths['coverage'].read_text().replace('read','other claim'))
    if bad=='header':
        paths['report'].write_text(paths['report'].read_text().replace('ret_001','ret_wrong'));reseal(paths)
    if bad=='unmapped_no_source':
        paths['unmapped'].write_text('name,reason,source_index\nUnknown,ambiguous,\n');reseal(paths)
    if bad in ('bad_market','bad_code'):
        p=paths['mentions'];rows=list(csv.DictReader(p.read_text().splitlines()));rows[0]['market' if bad=='bad_market' else 'code']='港股通' if bad=='bad_market' else ''
        write_csv(p,list(rows[0]),rows);reseal(paths)
    result=full_import(tmp_path,run,z,r,paths)
    assert result['status']!='REPORT_AND_STRUCTURED_ARCHIVED'
    assert result['local_acceptance']['semantic_research_accepted'] is False


def test_without_trusted_zip_hash_not_fully_bound(tmp_path):
    run=real_run(tmp_path);z,r=pack(tmp_path,run);paths=complete_return(tmp_path,r)
    kw=import_args(tmp_path,run,z,r)
    paths=complete_return(tmp_path,r)
    result=h.import_chat_return(**{**kw,'package_sha_value':'',**{k+'_value':v for k,v in paths.items()}})
    assert result['status']!='REPORT_AND_STRUCTURED_ARCHIVED'
    assert result['binding']['frozen_identity_metadata_status']=='UNTRUSTED_NO_TRUSTED_ZIP_SHA'
    assert not any(key in result['binding'] for key in ('account','biz','published_at'))


def test_old_summary_cannot_bind_updated_ocr(tmp_path):
    run=real_run(tmp_path);z,r=pack(tmp_path,run,suffix='old');paths=complete_return(tmp_path,r)
    p=run/'windows_ocr_results.json';v=json.loads(p.read_text());v[0]['text']='updated OCR';v[0]['text_length']=11;_write_json(p,v)
    new_z,new_r=pack(tmp_path,run,suffix='new')
    result=full_import(tmp_path,run,new_z,new_r,paths)
    assert result['status']!='REPORT_AND_STRUCTURED_ARCHIVED'
