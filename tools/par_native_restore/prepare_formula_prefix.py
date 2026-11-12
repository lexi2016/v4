"""Authenticate an original Par formula prefix and reuse pinned source.normalize.

The output asof comes only from the physical last row. An Oct26 mother prefix
cannot become a Nov9 prefix by changing the context date or filename.
"""
import argparse,gzip,hashlib,importlib.util,json,sys
from pathlib import Path
from native_state import digest
SOURCE_SHA='5f5932db843a723e976dbea26bd79e05b1a2f494228ed2462fd5403c1d6ffe35'


def prepare(par,raw_path,expected_sha,symbol,context,output):
    blob=raw_path.read_bytes()
    if hashlib.sha256(blob).hexdigest()!=expected_sha:raise ValueError('ACTUAL_ORIGINAL_PREFIX_SHA')
    original=json.loads(gzip.decompress(blob) if blob[:2]==b'\x1f\x8b' else blob)
    if original.get('symbol',symbol)!=symbol:raise ValueError('SOURCE_SYMBOL')
    raw=original['rows']
    source=par/'handoff/unified_candidate_20261102/source.py'
    if hashlib.sha256(source.read_bytes()).hexdigest()!=SOURCE_SHA:raise ValueError('NORMALIZER_SOURCE_PIN')
    sys.path.insert(0,str(source.parent));spec=importlib.util.spec_from_file_location('pinned_original_prefix_source',source);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    rows=m.normalize(raw,symbol)
    # Preserve supplied actual original context, changing only its observed date.
    actual_context={**context,'symbol':symbol,'asof':rows[-1]['event_date']}
    doc=dict(rows=rows,context=actual_context,kind='ACTUAL_PAR_SOURCE',source_binding=dict(source_prefix_sha256=expected_sha,source_reference=str(raw_path.resolve()),source_basis=context['basis'],normalized_rows_sha256=digest(rows),source_normalizer_sha256=SOURCE_SHA,physical_asof=rows[-1]['event_date'],source_refs=[dict(path=str(raw_path.resolve()),sha256=expected_sha)]))
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(path=str(output),rows=len(rows),first_date=rows[0]['event_date'],asof=rows[-1]['event_date'],sha256=hashlib.sha256(output.read_bytes()).hexdigest())))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--par',type=Path,required=True);p.add_argument('--raw',type=Path,required=True);p.add_argument('--sha256',required=True);p.add_argument('--symbol',required=True);p.add_argument('--context',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();prepare(a.par,a.raw,a.sha256,a.symbol,json.loads(a.context.read_bytes()),a.output)
