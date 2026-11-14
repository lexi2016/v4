"""Apply the weekend US context changes to an isolated exact-role UI copy."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from infrastructure.owned_io import SafeRoot


BASE = {
    'bootstrap.mjs': '6547c8b4db648ad38941f449dc5a4c665fc59a6146abbfeabf9129782c835f02',
    'workbench-us-context.mjs': '64f67efaf8959362d15d878de2d3538454854a1393405b21ff10304282482fcb',
}

SOURCE_CONTEXT_NEW = '''  const read=url=>fetch(url,{method:'GET',credentials:'same-origin',redirect:'error',cache:'no-store'}).then(r=>{if(!r.ok)throw Error('CONTEXT_READ_HTTP_'+r.status);return r.json()});
  return read('/api/v4/research/workbench/days/'+day.source_date+'/context?'+new URLSearchParams({revision:day.generation})).then(async value=>{
    if(!isCurrent())return;
    if(!sameIdentity(value,day))throw Error('SOURCE_CONTEXT_IDENTITY_CONFLICT');
    const dates=value.us_context;
    contextReply={...value,markets:{...value.markets,US:unknownUsContext(dates?.status??'US_SESSION_UNBOUND',dates)}};
    paintContext();
    if(dates?.status!=='SESSION_BOUND'||dates.session_completed!==true||!/^\\d{8}$/.test(dates.capture_research_date??''))return;
    try{
      const result=await read('/api/v4/research/us-market?'+new URLSearchParams({research_date:dates.capture_research_date}));
      if(!isCurrent())return;
      contextReply.markets.US=datedUsMarketContext(result,day,dates);
    }catch(error){if(!isCurrent())return;contextReply.markets.US=unknownUsContext(error.message,dates);}
    paintContext();
  }).catch(error=>{
    if(!isCurrent())return;
    contextReply.markets.US=unknownUsContext(error.message);
    contextReply.markets.JP=unknown('日本当日来源读取失败：'+error.message);
    contextReply.markets.KR=unknown('韩国当日基准/来源待核');
    paintContext();
  });
'''
MARKET_BRANCH = """    if(bound&&market==='US'&&marketObservation.benchmarks){const bench=marketObservation.benchmarks,base=marketObservation.usMarket??originalValue,session=base.native?.rows?.[0]?.session_date;value={...base,benchmarks:session&&bench.us_session_date!==session?null:bench};}"""
MARKET_BRANCH_NEW = """    if(market==='US'){
      const dates=contextReply.us_context;
      const saved=contextReply.us_benchmarks;
      let standalone=null;
      if(saved){
        try{
          const envelope={schema:'OBSERVATION_SNAPSHOT_VIEW_V1',source_date:identity.source_date,observation_date:identity.observation_date,
            source_generation:identity.generation,input_sha256:identity.input_sha256,RESEARCH_ONLY:contextReply.RESEARCH_ONLY,
            production_allowed:contextReply.production_allowed,buy_gate_updated:contextReply.buy_gate_updated,orders_sent:contextReply.orders_sent,
            context:{us_benchmarks:saved}};
          standalone=observationMarketContext(envelope,identity).benchmarks;
        }catch{ /* Conflicting close sources are withheld. */ }
      }
      const observed=bound?marketObservation.benchmarks:null;
      const usable=bench=>bench?.rows?.length&&eligibleUsClose(bench,dates);
      const benchmarks=[standalone,observed].filter(usable).sort((a,b)=>Number(b.complete)-Number(a.complete)
        ||b.rows.length-a.rows.length||Date.parse(b.recorded_at)-Date.parse(a.recorded_at))[0];
      const snapshotNative=bound?marketObservation.usMarket:null;
      const native=originalValue.native?originalValue:
        (snapshotNative&&eligibleUsNative(snapshotNative,dates)?snapshotNative:originalValue);
      value={...native,benchmarks,expected_session:dates?.us_session_date,context_status:dates?.status,
        benchmark_status:dates?.benchmark_status,benchmark_reason:dates?.benchmark_reason};
    }"""

RENDER = """  add(card,'strong',benchmarks?.heading??'昨晚美股：三大指数资料未齐');"""
RENDER_NEW = """  const session=value.expected_session;
  const dateLabel=/^\\d{8}$/.test(session??'')?session.slice(4,6)+'/'+session.slice(6):null;
  const closeLabel=dateLabel?'美股 '+dateLabel+' 收盘':'美股收盘';
  const heading=value.context_status==='WAITING_FOR_EXPECTED_US_CLOSE'?closeLabel+'待到时':closeLabel+'：三大指数资料未齐';
  add(card,'strong',benchmarks?.heading??heading);"""
HELPERS = """
export function eligibleUsClose(benchmarks,dates){
 return dates?.status==='SESSION_BOUND'&&dates.session_completed===true
   &&benchmarks.us_session_date===dates.us_session_date&&benchmarks.session_close_at===dates.session_close_at
   &&benchmarks.market_context_research_date===dates.capture_research_date
   &&Date.parse(benchmarks.recorded_at)>=Date.parse(dates.session_close_at)
   &&Date.parse(benchmarks.recorded_at)<=Date.parse(dates.context_cutoff_at);
}
export function eligibleUsNative(native,dates){
 return dates?.status==='SESSION_BOUND'&&dates.session_completed===true
   &&native.research_date===dates.capture_research_date
   &&native.native?.rows.length>0&&native.native.rows.every(row=>row.session_date===dates.us_session_date)
   &&Date.parse(native.recorded_at)>=Date.parse(dates.session_close_at)
   &&Date.parse(native.available_at??native.recorded_at)<=Date.parse(dates.context_cutoff_at);
}
export function datedUsMarketContext(value,day,dates){
 const view=usMarketContext(value,{...day,observation_date:dates.capture_research_date});
 view.available_at=value.generated_at;
 if(value.capture_phase!=='POST_CLOSE'||value.us_session_date!==dates.us_session_date
   ||!value.generated_at||!eligibleUsNative(view,dates))throw Error('US_CONTEXT_EXPECTED_SESSION_OR_AVAILABILITY_CONFLICT');
 view.artifact_research_date=dates.capture_research_date;
 view.observation_date=day.observation_date;
 view.heading='最近美股收盘 · 纽约 '+dates.us_session_date.slice(4,6)+'/'+dates.us_session_date.slice(6);
 return view;
}
"""


def _replace(source, before, after):
    if source.count(before) != 1:
        raise ValueError('WORKBENCH_US_UI_OVERLAY_SITE_CONFLICT')
    return source.replace(before, after, 1)


def overlay(name, raw):
    if sha256(raw).hexdigest() != BASE[name]:
        raise ValueError('WORKBENCH_US_UI_BASE_SHA_MISMATCH:' + name)
    source = raw.decode()
    if name == 'bootstrap.mjs':
        source = _replace(source, 'import {usMarketContext,unknownUsContext,renderMarketCard,observationMarketContext}',
                          'import {datedUsMarketContext,eligibleUsClose,eligibleUsNative,unknownUsContext,renderMarketCard,observationMarketContext}')
        first = source.index('  let usView=null;')
        last = source.index('\n}', first)
        source = source[:first] + SOURCE_CONTEXT_NEW.rstrip('\n') + source[last:]
        source = _replace(source, MARKET_BRANCH, MARKET_BRANCH_NEW)
    else:
        source = _replace(source, RENDER, RENDER_NEW)
        source = _replace(source, 'result.usMarket.artifact_research_date=captureDate;',
                          'result.usMarket.available_at=us.market_context.generated_at;result.usMarket.artifact_research_date=captureDate;')
        source = _replace(source, '&&Date.parse(row.source_asof)<=Date.parse(row.read_at)',
                          '&&Date.parse(row.source_asof)<=Date.parse(row.read_at)&&Date.parse(row.read_at)<=Date.parse(us.recorded_at)')
        source += HELPERS
    return source.encode()


def prepare(original, output):
    if not output.is_absolute() or output.exists() or output.is_symlink() or output.parent.resolve() != output.parent:
        raise ValueError('WORKBENCH_US_UI_NEW_CANDIDATE_OUTPUT_REQUIRED')
    files = {name: overlay(name, (original / name).read_bytes()) for name in BASE}
    output.mkdir(mode=0o700)
    root = SafeRoot(output)
    for name, raw in files.items():
        root.write_bytes(name, raw, require_absent=True)
    return {name: sha256(raw).hexdigest() for name, raw in files.items()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.original, args.output), sort_keys=True))
