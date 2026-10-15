"""Deterministically project the supplied ZIP; never execute archive scripts."""
from __future__ import annotations
import csv
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[3]
ZIP_SHA = 'e623b55d2443dedf6298f05680bd6f658482d8ec122d072b852a072dec873d94'
BASE_SHA = '3d7e1c3931a66a6844f4cb5c0d35030ed0e615e3e8246bc0b22caddc61dbb671'
OUTPUT = ROOT / 'v4/manager_workbench/research_data/us_hk_667_review_overlay_20261015.json'
# Exact source states only. These are research-use routing labels, never fact acceptance.
BACKGROUND = {
 'CONTEXT_ONLY_NO_DIRECT_ECONOMIC_LINK_PROVEN', 'CONTEXT_ONLY_NO_DIRECT_LINK_CONFIRMED',
 'BACKGROUND_MACRO_ONLY_NO_DIRECT_RELATION_VERIFIED', 'CONTEXT_ONLY_CURRENT_SEGMENT_COMPARISON',
 'CONTEXT_ONLY_MACRO_NET_SENSITIVITY_UNCONFIRMED', 'CONTEXT_ONLY_CURRENT_PROPERTY_COMPARISON',
 'LIMITED_CONTEXT_AFTER_ASSET_DISPOSAL', 'WEAK_MACRO_CONTEXT_ONLY',
}
EXCLUDED = {'EXCLUDED_CURRENT_OLD_SECURITY', 'EXCLUDED_CURRENT_HISTORICAL_ADS',
 'EXCLUDED_CURRENT_HISTORICAL_ADR', 'ORIGINAL_49_PERCENT_EQUITY_BRIDGE_ENDED_2026_07_30'}
CONDITIONAL = {'CURRENT_DOCUMENTARY_MAPPING_SUPPORTED_EXECUTABILITY_PENDING',
 'CONDITIONAL_MACRO_OBSERVATION_ONLY',
 'SUPPORTED_AT_2026_H1_CURRENT_WEBSITE_CORROBORATED_PRECISE_OCTOBER_CAPITAL_PENDING'}

def build(zip_path: Path) -> dict:
    if hashlib.sha256(zip_path.read_bytes()).hexdigest() != ZIP_SHA:
        raise ValueError('source ZIP SHA mismatch')
    base_path = ROOT/'v4/manager_workbench/research_data/us_hk_667_catalog_20261015.json'
    if hashlib.sha256(base_path.read_bytes()).hexdigest() != BASE_SHA:
        raise ValueError('base catalog SHA mismatch')
    base = json.loads(base_path.read_bytes())
    prefix = 'deliverable_batch2/'
    with ZipFile(zip_path) as z:
        if z.testzip() is not None: raise ValueError('ZIP CRC failed')
        names=z.namelist()
        if len(names)!=len(set(names)): raise ValueError('duplicate ZIP member')
        manifest=json.loads(z.read(prefix+'DELIVERABLE_MANIFEST.json'))
        if {prefix+r['file'] for r in manifest['files']} != set(names)-{prefix+'DELIVERABLE_MANIFEST.json'}:
            raise ValueError('manifest member set mismatch')
        for entry in manifest['files']:
            raw=z.read(prefix+entry['file'])
            if len(raw)!=entry['bytes'] or hashlib.sha256(raw).hexdigest()!=entry['sha256']:
                raise ValueError('manifest member identity mismatch')
        def rows(name): return list(csv.DictReader(io.StringIO(z.read(prefix+name).decode('utf-8-sig'))))
        revised=rows('01B_full_1003_original_plus_revision.csv')
        if len(revised)!=1003: raise ValueError('relation count mismatch')
        for old,new in zip(base['relations'],revised):
            if any(new.get(k)!=v for k,v in old['source_record'].items()):
                raise ValueError('original relation field changed')
        main=rows('01A_full_667_original_plus_revision.csv')
        if len(main)!=667 or any(any(new.get(k)!=v for k,v in old['source_record'].items()) for old,new in zip(base['stocks'],main)):
            raise ValueError('original stock field changed')
        processed=rows('04_cumulative_results.csv')
        evidence=rows('03_evidence_by_url.csv')
        records=[]
        for row in processed:
            rid=row['关系编号']; ordinal=int(rid[1:]); original=base['relations'][ordinal-1]
            if original['source_record']['关系编号']!=rid or original['hk_code']!=row['code'] or original['us_symbol']!=row['asset_code']:
                raise ValueError('review relation identity mismatch')
            if row != revised[ordinal-1]: raise ValueError('cumulative revision differs from full table')
            current=row['revision_current_applicability_state']
            use=('EXCLUDED_CURRENT' if current in EXCLUDED else 'BACKGROUND_HISTORICAL' if current in BACKGROUND else 'CONDITIONAL_OBSERVATION' if current in CONDITIONAL else 'PENDING_REVIEW')
            revision={k:json.loads(v) if k.endswith('_json') else v for k,v in row.items() if k.startswith('revision_')}
            ids=set(revision['revision_evidence_ids_json'])
            linked=[e for e in evidence if e['evidence_id'] in ids and rid in json.loads(e['relation_ids_json'])]
            if ids != {e['evidence_id'] for e in linked}: raise ValueError('missing referenced review evidence')
            records.append({'relation_id':rid,'source_row':ordinal,'hk_code':row['code'],'us_symbol':row['asset_code'],
                'source_review_status':'SOURCE_REVIEWED','independent_verification':'NOT_RUN',
                'research_use':use,'use_rule':'exact_current_state_v1','source_current_state':current,
                'revision':revision,'evidence':linked})
        if len(records)!=40 or len({r['relation_id'] for r in records})!=40: raise ValueError('review coverage mismatch')
        records.sort(key=lambda r:r['source_row'])
        result={'schema_version':'v4.us_hk_mapping_review_overlay.v1','source_package_sha256':ZIP_SHA,
            'base_catalog_sha256':BASE_SHA,'source_generated_at_utc':manifest['generated_at_utc'],
            'manifest_sha256':hashlib.sha256(z.read(prefix+'DELIVERABLE_MANIFEST.json')).hexdigest(),
            'source_members':{e['file']:e['sha256'] for e in manifest['files']},
            'projection_rule':{'id':'exact_current_state_v1','meaning':'Research use only; source states are not independent acceptance.',
                'BACKGROUND_HISTORICAL':sorted(BACKGROUND),'EXCLUDED_CURRENT':sorted(EXCLUDED),
                'CONDITIONAL_OBSERVATION':sorted(CONDITIONAL),'default':'PENDING_REVIEW'},
            'records':records}
        result['integrity_sha256']=hashlib.sha256(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        return result

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--zip',type=Path,default=Path('/Users/lexi/Downloads/US_HK_667_batch2_cumulative40_review_20261015.zip'))
    args=parser.parse_args();data=build(args.zip)
    OUTPUT.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'records':len(data['records']),'stocks':len({r['hk_code'] for r in data['records']}),'sha256':hashlib.sha256(OUTPUT.read_bytes()).hexdigest()}))
