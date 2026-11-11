"""Materialized original-chart rows: immutable old rows plus exact revisions.

This is the existing daily owner's rendering sidecar, never a formula engine.
Reads only join already computed rows and verify every referenced byte.
"""
import gzip
import hashlib
import json
from pathlib import Path

VERSION = 'v4.original_chart.row_blocks.v1'
FLAGS = dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
LIMIT = 64*1024*1024


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def ref(path):
    path=Path(path).resolve(strict=True)
    return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def checked(reference, read=None):
    if read is not None:
        return read(reference)
    p=Path(reference['path'])
    if not p.is_absolute() or p.is_symlink() or p.resolve(strict=True)!=p:
        raise ValueError('CHART_BLOCK_PATH_INVALID')
    raw=p.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=reference['sha256']:
        raise ValueError('CHART_BLOCK_SHA_DRIFT')
    return raw


def decode(raw):
    import io
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        value=stream.read(LIMIT+1)
    if len(value)>LIMIT:raise ValueError('CHART_BLOCK_SIZE_LIMIT')
    return json.loads(value)


def retained(reference, read=None):
    """Flat chain, last-write-wins by original trade date; no numerical compute."""
    current=decode(checked(reference,read))
    if current.get('storage_schema')!=VERSION:return current
    rows={}
    refs=current['history_blocks']
    if len({r['path'] for r in refs})!=len(refs) or reference['path'] in {r['path'] for r in refs}:
        raise ValueError('CHART_BLOCK_REFERENCE_CYCLE')
    for previous in refs:
        block=decode(checked(previous,read))
        if (block['symbol']!=current['symbol'] or block['config']!=current['config']
                or block['formula_result']['formula_sha256']!=current['formula_result']['formula_sha256']):
            raise ValueError('CHART_BLOCK_IDENTITY_CONFLICT')
        for row in block['formula_result']['rows']:rows[row['trade_date']]=row
    for row in current['formula_result']['rows']:rows[row['trade_date']]=row
    if sorted(rows)!=current['bar_dates']:raise ValueError('CHART_BLOCK_DATE_COVERAGE')
    names=[item['name'] for item in current['inventory']['assignments']]
    ordered=[]
    for day in sorted(rows):
        row=rows[day]
        if set(row['values'])!=set(names):raise ValueError('CHART_BLOCK_VALUE_INVENTORY')
        ordered.append({**row,'values':{name:row['values'][name] for name in names}})
    current['formula_result']={**current['formula_result'],'rows':ordered}
    return current


def previous_cache(context,symbol):
    # Only the original owner's registered index; never directory discovery.
    if not hasattr(context,'_chart_prior_samples'):
        samples={};index_path=context.root/'index.json'
        if index_path.is_file():
            index=json.loads(index_path.read_bytes())
            dates=sorted((d for d in index.get('original_charts',{}) if d<str(context.target)),reverse=True)
            for day in dates[:1]:
                descriptor=index['original_charts'][day]
                manifest=json.loads(checked(descriptor['manifest']))
                if manifest.get('RESEARCH_ONLY') is not True:raise ValueError('CHART_PRIOR_SAFETY')
                samples=manifest.get('samples',{})
        context._chart_prior_samples=samples
    sample=context._chart_prior_samples.get(symbol)
    if not sample:return None
    candidate=sample['source_cache'];value=retained(candidate)
    if value['symbol']!=symbol or value['config']!=context.config_ref:return None
    return candidate,value


def retain_owner_result(context,parts,symbol,bars,result):
    inventory=context.engine().inventory()
    ready=context.engine().json_ready(result)
    prior=previous_cache(context,symbol)
    blocks=[];rows=ready['rows']
    if prior:
        old_ref,old=prior
        before={r['trade_date']:r for r in old['formula_result']['rows']}
        if not set(before).issubset(r['trade_date'] for r in rows):raise ValueError('CHART_OLD_KEYS_LOST')
        rows=[r for r in rows if before.get(r['trade_date'])!=r]
        blocks=list(old.get('history_blocks',[]))+[dict(path=old_ref['path'],sha256=old_ref['sha256'])]
    payload=dict(storage_schema=VERSION,symbol=symbol,data_date=str(context.target),identity=context.identity,
        config=context.config_ref,bars_sha256=hashlib.sha256(canonical(bars)).hexdigest(),
        bar_dates=[b['trade_date'] for b in bars],calendar=context.calendars[symbol[-2:]],inventory=inventory,
        formula_result={**ready,'rows':rows},history_blocks=blocks,**FLAGS)
    path=Path(parts)/'original_retained'/(symbol+'.json.gz');path.parent.mkdir(parents=True,exist_ok=True)
    raw=gzip.compress(canonical(payload),mtime=0)
    if path.exists():
        if path.read_bytes()!=raw:raise ValueError('CHART_RETAINED_IMMUTABLE_CONFLICT')
    else:
        temporary=path.with_name('.'+path.name+'.pending');temporary.write_bytes(raw);temporary.replace(path)


def projection_payload(spec,read=None):
    if spec.get('storage_schema')!=VERSION:raise ValueError('CHART_SPEC_SCHEMA_UNKNOWN')
    source=retained(spec['source_cache'],read)
    if (source['symbol']!=spec['symbol'] or source['data_date']!=spec['data_date']
            or source['identity']!=spec['source_identity'] or source['config']!=spec['lineage']['config']):
        raise ValueError('CHART_SPEC_RETAINED_IDENTITY')
    projection={k:v for k,v in spec.items() if k not in {'storage_schema','source_identity'}}
    projection.update(inventory=source['inventory'],formula_result=source['formula_result'])
    return projection


def projection_bytes(reference,read=None):
    spec=json.loads(checked(reference['spec'],read))
    raw=gzip.compress(canonical(projection_payload(spec,read)),mtime=0)
    if len(raw)!=reference['bytes'] or hashlib.sha256(raw).hexdigest()!=reference['sha256']:
        raise ValueError('CHART_VIRTUAL_PROJECTION_SHA_DRIFT')
    return raw


def shared_html(renderer_raw):
    from ops.render_original_formula_projection import chart_html
    # Reuse the installed R19 glyph/table/interaction code. Only its bound
    # transport is replaced; all financial rows arrive from a verified GET.
    sample=dict(symbol='000000.SZ',data_date='20000101',unsupported_drawings=[],source=dict(
        adjustment_convention='BOUND_ORIGINAL_OWNER_QFQ',price_basis='qfq',volume_basis='bound'),
        formula_result=dict(rows=[dict(trade_date=20000101)]))
    html=chart_html(renderer_raw,sample,{},compress_payload=False)
    start=html.index('<script>const projectedReady=')
    end=html.index('</script>',start)+len('</script>')
    loader=r'''<script>
const originalFetch=window.fetch.bind(window),q=new URLSearchParams(location.search);
const projectedReady=(async()=>{const query=new URLSearchParams();for(const k of ['date','symbol','generation','input_sha256']){if(!q.get(k))throw Error('CHART_BINDING_MISSING');query.set(k,q.get(k));}
let metadataURL='/api/v4/research/a-share/original-chart?'+query;if(location.pathname.includes('/v192-assets/')&&location.pathname.endsWith('/html')){const scoped=new URL(location.href);scoped.pathname=scoped.pathname.slice(0,-5);scoped.searchParams.delete('sha256');metadataURL=scoped.href;}
const meta=await originalFetch(metadataURL,{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('CHART_METADATA');return r.json()});
if(meta.status!=='READY'||meta.symbol!==q.get('symbol')||meta.data_date!==q.get('date')||meta.source_generation!==q.get('generation')||meta.input_sha256!==q.get('input_sha256'))throw Error('CHART_METADATA_IDENTITY');
const asset=meta.assets.projection,u=new URL(asset.url,location.href);if(u.origin!==location.origin)throw Error('CHART_ORIGIN');
const response=await originalFetch(u,{cache:'no-store'});if(!response.ok)throw Error('CHART_PROJECTION');const bytes=new Uint8Array(await response.arrayBuffer());if(bytes.length>8*1024*1024||bytes.length!==asset.bytes)throw Error('CHART_SIZE');
const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');if(digest!==asset.sha256)throw Error('CHART_SHA');
const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip')),reader=stream.getReader();let size=0,parts=[];for(;;){const r=await reader.read();if(r.done)break;size+=r.value.length;if(size>64*1024*1024){await reader.cancel();throw Error('CHART_DECOMPRESSED_LIMIT');}parts.push(r.value);}const p=JSON.parse(await new Blob(parts).text());
if(p.symbol!==meta.symbol||p.data_date!==meta.data_date||p.source.generation_id!==meta.source_generation||p.source.source_input_sha256!==meta.input_sha256||p.RESEARCH_ONLY!==true||p.production_allowed!==false||p.orders_sent!==false||p.buy_gate_updated!==false)throw Error('CHART_PROJECTION_IDENTITY');
const rows=p.formula_result.rows;return {payload:{status:'READY',symbol:p.symbol,target_date:p.data_date,rows,total_rows:rows.length,first_date:rows[0].trade_date,last_date:rows.at(-1).trade_date,source_vendor:'EXISTING_BOUND_QFQ_CACHE',source_kind:p.source.adjustment_convention,projection_source_label:p.source.price_basis+' / '+p.source.volume_basis+'；历史非PIT',projection_lineage:p.lineage,RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false},registry:{entry_count:1,available_count:1,no_target_bar_count:0,pending_count:0,entries:[{symbol:p.symbol,rows:rows.length,source_vendor:'BOUND_CACHE_DERIVATIVE'}]}};})();
window.fetch=async function(url){const p=await projectedReady,u=new URL(url,location.href);if(u.origin!==location.origin)return new Response('',{status:404});if(u.pathname==='/v1/registry')return new Response(JSON.stringify(p.registry));if(u.pathname==='/v1/research'&&u.searchParams.get('symbol')===p.payload.symbol&&u.searchParams.get('date')===p.payload.target_date)return new Response(JSON.stringify(p.payload));return new Response('',{status:404});};
</script>'''
    html=html[:start]+loader+html[end:]
    # The existing renderer's date input must use the bound source day.
    html=html.replace("(async()=>{try{const response=await fetch('/v1/registry'", "(async()=>{try{document.querySelectorAll('input[type=date]').forEach(x=>{const d=q.get('date');x.value=d.slice(0,4)+'-'+d.slice(4,6)+'-'+d.slice(6);});const response=await fetch('/v1/registry'",1)
    export="""<script>const exportButton=document.createElement('button');exportButton.type='button';exportButton.textContent='导出当前图 PNG';exportButton.onclick=()=>{const canvas=document.querySelector('#chart');if(!document.documentElement.dataset.loaded)return;const a=document.createElement('a');a.download=q.get('symbol')+'-'+q.get('date')+'.png';a.href=canvas.toDataURL('image/png');a.click();};document.querySelector('header').append(exportButton);</script>"""
    return html.replace('</body>',export+'</body>')
