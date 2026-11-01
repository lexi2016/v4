"""Rebind UI source bytes to the same computed single-stock values; no recalculation."""
from pathlib import Path
import gzip
import json
import pyarrow as pa
import pyarrow.parquet as pq
from ops import research_panel_qfq as q
from ops import render_original_formula_projection as renderer
from ops.junda_feedback_candidate import immutable,write_json,same

E=Path(__file__).resolve().parent;REPO=Path(q.__file__).resolve().parents[1]
prior_ref={'path':str(E/'EDAN_CANDIDATE_1cf5bf8c85418b31.json'),
           'sha256':'a44cbf93fa95fb41686395ac6fc8ee274a1600653410e1b7e80893d9c074482f'}
old=json.loads(q._source(prior_ref,owner='navigation prior candidate').read_text())
binding=json.loads(q._source(old['binding'],owner='navigation prior binding').read_text())
identity=dict(binding['candidate_identity']);sources=dict(identity['source_sha256'])
changed={'research-panel/workbench-host/kb-single-stock.mjs'}
for name,digest in sources.items():
    if name not in changed and q.sha(REPO/name)!=digest:raise ValueError('UNRELATED_SOURCE_CHANGED:'+name)
new_sha={name:q.sha(REPO/name) for name in changed}
if any(sources[name]==digest for name,digest in new_sha.items()):raise ValueError('VERSION_SOURCE_NOT_CHANGED')
sources.update(new_sha)
identity.update(source_sha256=sources,navigation_prior_candidate_sha256=prior_ref['sha256'],
                navigation_rebind_ref={'path':str(Path(__file__)),'sha256':q.sha(__file__)})
generation=q.canonical_sha(identity);short=generation[:16]
side=pq.read_table(q._source(binding['confirmed_gap']['diagnostics'],owner='prior sidecar'))
meta=json.loads((side.schema.metadata or {})[b'v4.a_share.kb_gap_diagnostics.v1'])
assert meta['candidate_generation']==old['candidate_generation'];meta['candidate_generation']=generation
rebound=side.replace_schema_metadata({b'v4.a_share.kb_gap_diagnostics.v1':json.dumps(meta,sort_keys=True).encode()})
sink=pa.BufferOutputStream();pq.write_table(rebound,sink,compression='zstd')
side_ref=immutable(E/f'EDAN_DIAGNOSTICS_{short}.parquet',sink.getvalue().to_pybytes())
outputs={};display_roles={};unchanged={}
for role,reference in old['outputs'].items():
    table=pq.read_table(q._source(reference,owner='prior full role'))
    m=dict(table.schema.metadata or {});provenance=json.loads(m[b'kb_single_candidate_v1'])
    assert provenance['candidate_generation']==old['candidate_generation'];provenance['candidate_generation']=generation
    m[b'kb_single_candidate_v1']=json.dumps(provenance,sort_keys=True).encode()
    candidate=table.replace_schema_metadata(m);sink=pa.BufferOutputStream();pq.write_table(candidate,sink,compression='zstd')
    output=immutable(E/f'EDAN_{role.upper()}_FULL_{short}.parquet',sink.getvalue().to_pybytes())
    reread=pq.read_table(q._source(output,owner='navigation full role'))
    assert table.column_names==reread.column_names and all(same(table[x],reread[x]) for x in table.column_names)
    outputs[role]={**output,'rows':len(reread),'all_data_columns_unchanged':True};unchanged[role]=len(table.column_names)
    item=binding['display_projection']['roles'][role]
    display=pq.read_table(q._source(item['artifact'],owner='prior display'))
    context=json.loads((display.schema.metadata or {})[b'a_share_single_display_projection_v1'])
    assert context['candidate_generation']==old['candidate_generation']
    context.update(candidate_generation=generation,source_full_sha256=output['sha256'])
    candidate_display=display.replace_schema_metadata({b'a_share_single_display_projection_v1':json.dumps(context,sort_keys=True).encode()})
    sink=pa.BufferOutputStream();pq.write_table(candidate_display,sink,compression='zstd')
    projected=immutable(E/f'EDAN_{role.upper()}_DISPLAY_{short}.parquet',sink.getvalue().to_pybytes())
    display_readback=pq.read_table(q._source(projected,owner='navigation display'))
    assert all(same(display[x],display_readback[x]) for x in display.column_names)
    display_roles[role]={**item,'artifact':projected,'source_full':output}
view=json.loads(gzip.decompress(q._source(binding['assets']['kb'],owner='prior view').read_bytes()))
view.update(candidate_generation=generation,candidate_identity_sha256=generation,
            selector_candidate_sha256=outputs['selector']['sha256'],confirmed_gap_diagnostics_sha256=side_ref['sha256'])
raw=json.dumps(view,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode();assert len(raw)<32*1024*1024
kb=immutable(E/f'EDAN_VIEW_{short}.json.gz',gzip.compress(raw,mtime=0));kb.update(encoding='gzip',decoded_bytes=len(raw))
projection=json.loads(gzip.decompress(q._source(binding['assets']['projection'],owner='prior chart').read_bytes()))
projection.update(candidate_generation=generation);projection['lineage']['candidate_generation']=generation
projection['lineage']['selector_candidate']=outputs['selector']
raw=(json.dumps(projection,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
proj=immutable(E/f'EDAN_PROJECTION_{short}.json.gz',gzip.compress(raw,mtime=0))
proj.update(encoding='gzip',decoded_bytes=len(raw),row_count=len(view['rows']),formula_sha256=renderer.FORMULA_SHA)
html=renderer.chart_html(Path(renderer.OWNER_RENDERER['path']).read_bytes(),projection,projection['lineage'],compress_payload=True)
html=html.replace('候选派生投影','单股研究投影').replace('候选原式派生投影','单股原式研究投影')
chart=immutable(E/f'EDAN_CHART_{short}.html',html.encode())
gap={**binding['confirmed_gap'],'diagnostics':side_ref}
display={**binding['display_projection'],'roles':display_roles}
assets={**binding['assets'],'kb':kb,'projection':proj,'html':chart}
binding.update(candidate_identity=identity,candidate_generation=generation,confirmed_gap=gap,
               display_projection=display,assets=assets)
br=write_json(E/f'EDAN_BINDING_{short}.json',binding)
result={**old,'candidate_generation':generation,'candidate_identity':identity,'outputs':outputs,'binding':br,
        'assets':assets,'confirmed_gap':gap,'display_projection':display,'navigation_rebound_from':prior_ref,
        'status':'PREPARED_PENDING_INCREMENTAL_REVIEW'}
cr=write_json(E/f'EDAN_CANDIDATE_{short}.json',result)
proof=write_json(E/'EDAN_SAME_STOCK_REBIND_R4.json',{'status':'PASS_IDENTITY_REBIND_NO_RECALC',
    'prior':prior_ref,'candidate':cr,'binding':br,'generation':generation,'rows':len(view['rows']),
    'full_columns_unchanged':unchanged,'source_changes':sorted(changed),'new_source_sha256':new_sha,
    'sidecar_rows_unchanged':len(side),'formula_and_kb_rows_reused':True,**q.FLAGS})
print(json.dumps({'generation':generation,'candidate':cr,'binding':br,'proof':proof},ensure_ascii=False))
