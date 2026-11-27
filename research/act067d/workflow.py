"""ACT-067D D-only execution and separately authorized user-only PDF."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, deque
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from research.act067b.semantic_shadow import UNKNOWN, as_date, read_json, sha256, through_sessions
from research.act067d.engine import Shadow
from research.act067d.plot import geometry, render


PREFIX = 'ACT067D_JUNDA_002865'
CSV = PREFIX+'_V40_VS_V41_SHADOW_DONLY_20261127.csv'
ZIP = PREFIX+'_D_ONLY_BLIND_PACKAGE_20261127.zip'
PDF = PREFIX+'_USER_REVIEW_ATLAS_DPLUS15_20261127.pdf'
MD = 'ACT067D_JUNDA_SHADOW_SUMMARY_20261127.md'
CONTRACT = 'V4.1_SEMANTIC_SHADOW_CONTRACT_V1_1.json'
CONTRACT_SHA = '5f4782a8c9a5a02ebb6e8af2beb6ab386c091ce68beb1eb7f27fc70e89b674f5'
PRIOR_CSV = 'ACT067B_JUNDA_002865_V40_VS_V41_SHADOW_DONLY_20261127.csv'
PRIOR_CSV_SHA = '29b90ebab58709dd66bdd3f03ce14e0353bd2af22d7be3765e7f37f886ec5154'
MARKET_FIELDS = ('ts_code','date','stock_session_index','source_generation','price_basis','volume_basis','historical_pit',
                 'open_D','high_D','low_D','close_D','volume_D','pct_D','W_D','Y_D','BBI_D','J_D')


def dump(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def write_json(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def read_csv(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))


def write_csv(path,rows):
    with path.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def load_rules(output):
    path=output/CONTRACT
    if sha256(path)!=CONTRACT_SHA:
        raise ValueError('Refusing to evaluate against unregistered contract bytes')
    return read_json(path)


def open_prior(prior):
    csv_path=prior/'output'/PRIOR_CSV
    indicators=prior/'evidence'/'common_indicators_d_only.csv'
    replay_receipt=read_json(prior/'evidence'/'v40_replay_receipt.json')
    if sha256(csv_path)!=PRIOR_CSV_SHA or sha256(indicators)!=replay_receipt['common_indicators_sha256']:
        raise ValueError('Frozen ACT-067B artifacts changed')
    source=read_csv(csv_path)
    if len(source)!=344 or len({row['date'] for row in source})!=len(source) or sum(row['v40_frozen_date_present']=='TRUE' for row in source)!=342:
        raise ValueError('Frozen historical cohort changed')
    return {as_date(row['date']):row for row in source},indicators,replay_receipt


def enum_schema(rules):
    enums=rules['statuses']
    statuses={
        'b1_phase':enums['b1_lifecycle'],'b1_anchor_type':enums['b1_anchor_type'],
        'b1_W_intraday':enums['line_test'],'b1_Y_intraday':enums['line_test'],'m25_t_intraday_y':enums['line_test'],
        'm25_phase':enums['m25_phase'],'m25_onset_disposition':enums['m25_onset_disposition'],
        'm25_previous_event_status':enums['m25_terminal_event'],'candle_shape_proxy':enums['candle_shape'],
        'risk_official_ST_coverage':enums['official_coverage'],'risk_official_delisting_coverage':enums['official_coverage'],
        'historical_pit':enums['official_coverage'],
        'v31_3_structure_status':['QUALIFIED','WATCH','REJECTED'],
        'v40_frozen_entry_status':['QUALIFIED','WATCH','REJECTED','UNKNOWN'],
        'v40_replay_entry_status':['QUALIFIED','WATCH','REJECTED','NO_FORMULA_HIT'],
        'v40_frozen_source_parity':['DIFFERENT_PREPROCESSING_AND_GENERATION_RAW_COUNTS_NOT_PURE_RULE_ATTRIBUTION'],
    }
    tri=('key_k_proxy','risk_clear_shadow','risk_clear_certified','risk_suspected_ST_D','b1_raw','b1_formal_shadow',
         'b1_formal_certified','b1_pullback_real','b1_pullback_shrink','b1_anchor_floor_valid','b1_primary_support','b1_needle_rule',
         'b2_oral_authentic','b2_oral_preceding_base','m25_price_damage_proxy_today','m25_d_damage_today','m25_t_yellow_test_today',
         'm25_c_rebuild_price_today','m25_history_preserved','m25_risk_clear_shadow','m25_risk_clear_certified','m25_original_root_clear_now',
         'm25_rebuild_shadow','m25_rebuild_certified','m25_old_floor_broken_at_damage','m25_old_floor_ever_broken_through_test',
         'm25_old_floor_ever_broken_through_observation','m25_c_reclaimed_W','v31_3_proxy_m25_chain_complete','v40_frozen_date_present')
    statuses.update({field:enums['tristate'] for field in tri})
    for prefix in ('v40_frozen','v40_replay'):
        statuses.update({f'{prefix}_{method}_{stage}':enums['tristate'] for method in ('b1','b2','m25') for stage in ('raw','qualified')})
        statuses[f'{prefix}_m25_chain_complete']=enums['tristate']
    for track in rules['method_20']['tracks']:
        statuses.update({f'{track}_{suffix}':enums['tristate'] for suffix in ('raw','formal_retest_shadow','formal_retest_certified')})
        statuses.update({f'{track}_{suffix}':enums['b2_track_event'] for suffix in ('D0_state','retest_state')})
    return statuses


def evaluate(rules,path,cohort):
    engine=Shadow(rules)
    results={}
    for ix,bar in enumerate(through_sessions(path,max(cohort))):
        state=engine.advance(bar)
        if bar.day in cohort:
            row=cohort[bar.day]
            if int(row['stock_session_index'])!=ix or state['b1_raw']!=row['v40_replay_b1_raw']:
                raise ValueError(f'Session-index or immutable RAW mismatch on {bar.day}')
            inherited={key:value for key,value in row.items()
                       if key in MARKET_FIELDS or key.startswith(('v31_3_','v40_frozen_','v40_replay_'))}
            results[bar.day]={**inherited,**state}
    if len(results)!=len(cohort):
        raise ValueError('Missing historical cohort dates')
    domains=enum_schema(rules)
    for row in results.values():
        bad={key:row.get(key) for key,domain in domains.items() if row.get(key) not in domain}
        if bad:
            raise ValueError(f'Unregistered status on {row["date"]}: {bad}')
    return results,engine.damage_history,domains


def prefix_check(rules,path,result):
    days=list(result)
    check=[days[i] for i in (10,len(days)//2,len(days)-10)]
    for day in check:
        smaller={k:v for k,v in result.items() if k<=day}
        shadow=Shadow(rules)
        for bar in through_sessions(path,day):
            computed=shadow.advance(bar)
            if bar.day in smaller:
                actual=smaller[bar.day]
                if any(actual[key]!=value for key,value in computed.items()):
                    raise AssertionError(f'Prefix mismatch on {bar.day}')
    return [str(day) for day in check]


def sample(rows,rules):
    bars=rules['charts']['left_sessions']
    review=rules['charts']['forward_sessions']
    ceiling=int(rows[-1]['stock_session_index'])
    pool=[row for row in rows if bars-1<=int(row['stock_session_index'])<=ceiling-review]
    selections={}

    def add(predicate,reason):
        candidates=[r for r in pool if r['date'] not in selections and predicate(r)]
        if candidates:
            def score(row):
                ix=int(row['stock_session_index'])
                return min((abs(ix-selected['td_idx']) for selected in selections.values()),default=0),ix
            row=max(candidates,key=score)
            selections[row['date']]={'date':row['date'],'td_idx':int(row['stock_session_index']),'stratum':reason}
    add(lambda r:r['m25_c_rebuild_price_today']=='TRUE' and r['m25_original_root_clear_now']=='FALSE','M25_C_OLD_ROOT_VETO')
    add(lambda r:r['m25_c_rebuild_price_today']=='TRUE' and r['risk_clear_shadow']=='FALSE','M25_C_MARKET_RISK_VETO')
    for field,value,reason in (
        ('b1_formal_shadow','TRUE','B1_FORMAL_SHADOW'),('B2_ORAL_CORE_SHADOW_raw','TRUE','ORAL_SHADOW_D0'),
        ('m25_rebuild_shadow','TRUE','M25_REBUILD_SHADOW'),('m25_c_rebuild_price_today','TRUE','M25_C_TECHNICAL'),
        ('m25_t_yellow_test_today','TRUE','M25_T_YELLOW_TEST'),('m25_d_damage_today','TRUE','M25_D_DAMAGE'),
        ('v40_replay_b2_raw','TRUE','V40_B2_RAW'),('USER_FORMULA_B2_F03_raw','TRUE','V41_F03_RAW'),
        ('b1_raw','TRUE','B1_RAW'),('B2_1006_SCREEN_raw','TRUE','B2_1006_RAW')):
        add(lambda r:r[field]==value,reason)
    while len(selections)<rules['charts']['blind_count']:
        before=len(selections)
        add(lambda r:True,'D_ONLY_SPREAD_FILL')
        if len(selections)==before:
            raise ValueError('Insufficient 35-session chart windows')
    return [{'chart_id':f'A{index:02d}',**row} for index,row in enumerate(sorted(selections.values(),key=lambda r:r['date']),1)]


def chart_slices(path,selected,rules):
    pending={as_date(case['date']):case for case in selected}
    window=deque(maxlen=rules['left_sessions'])
    for bar in through_sessions(path,max(pending)):
        window.append(bar)
        if bar.day in pending:
            yield pending[bar.day],list(window)


def add_bytes(archive,name,content):
    archive.writestr(ZipInfo(name),content,compress_type=ZIP_DEFLATED)
    return hashlib.sha256(content).hexdigest()


def chart_package(path,indicators,chosen,rules):
    manifest={'review_mode':'D_ONLY','calendar_dates_in_manifest_only':True,'x_axis_relative_last':0,
              'chart_count':len(chosen),'contract_sha256':CONTRACT_SHA,'charts':[]}
    lock=[]
    with ZipFile(path,'w',compression=ZIP_DEFLATED) as archive:
        for case,bars in chart_slices(indicators,chosen,rules):
            chart=case['chart_id']
            bounds=geometry(bars,rules)
            png,_=render(bars,bounds,rules)
            d=str(bars[-1].day)
            if d!=case['date'] or any(str(bar.day)>d for bar in bars):
                raise ValueError('D-only chart crosses cutoff')
            name=f'{chart}.png'
            png_sha=add_bytes(archive,name,png)
            witness={'offset_definition':'0=D, prior stock trading sessions negative','rows':[
                {'td':i-len(bars)+1,'open':b.open,'high':b.high,'low':b.low,'close':b.close,'volume':b.volume,
                 'pct_change':b.pct,'W':b.w,'Y':b.y,'BBI':b.bbi,'J':b.j} for i,b in enumerate(bars)]}
            witness_name=f'{chart}_D_ONLY_WINDOW.json'
            witness_sha=add_bytes(archive,witness_name,(dump(witness)+'\n').encode())
            data={'chart_id':chart,'D':case['date'],'max_date_used':d,'ylim_source':'D_ONLY_SLICE','file':name,'sha256':png_sha,
                  'window_file':witness_name,'window_sha256':witness_sha,'bars':len(bars),**bounds}
            manifest['charts'].append(data)
            lock.append({**case,**data})
        add_bytes(archive,'MANIFEST_SHA256.json',(json.dumps(manifest,indent=2)+'\n').encode())
    return lock


def make_summary(rows,hashes,counts,path):
    def stats(key):
        return '/'.join(str(counts[key].get(state,0)) for state in ('TRUE','FALSE','UNKNOWN'))

    def sample_date(field, state='TRUE'):
        matches=[r['date'] for r in rows if r[field]==state]
        return matches[len(matches)//2] if matches else '该队列无命中'

    removals=Counter(row['b2_f03_failed_clauses'] for row in rows
                     if row['v40_replay_b2_raw']=='TRUE' and row['USER_FORMULA_B2_F03_raw']=='FALSE')
    failures={'W_GT_Y':'W > Y','J_LT_13_D_MINUS_2_TO_D':'三根 J 窗口','VOL_GT_1_25_PRIOR4':'四日量均'}
    failure_line='，'.join(f'{"及".join(failures.get(c,c) for c in key.split("|"))} {value} 日' for key,value in removals.most_common())
    w_tol=sum(r['b1_formal_shadow']=='TRUE' and r['b1_W_intraday']=='CLOSE_BREAK' for r in rows)
    lines=['# ACT-067D｜钧达股份 002865.SZ V4.1 语义影子', '',
           '344 个原始信号日覆盖 2017-10-19 至 2026-11-06。两版同源使用 2316 个交易日和同一套冻结指标。归档 V4.0 覆盖 342 个同日，代次差异单列。以下为交易日计数。','',
           '| 规则 | 同源 V4.0 RAW/合格 | V4.1 影子 TRUE/FALSE/UNKNOWN | 示例 D |','|---|---:|---:|---|']
    for label,branch,field in [('#19 RAW','b1','b1_raw'),('#19 Formal','b1','b1_formal_shadow'),('#20 旧 RAW / 口述影子','b2','B2_ORAL_CORE_SHADOW_raw'),
                               ('#20 旧 RAW / F03','b2','USER_FORMULA_B2_F03_raw'),('#25 重建','m25','m25_rebuild_shadow')]:
        lines.append(f'| {label} | {counts[f"v40_replay_{branch}_raw"].get("TRUE",0)}/{counts[f"v40_replay_{branch}_qualified"].get("TRUE",0)} | {stats(field)} | {sample_date(field)} |')
    lines+=['',
        'O/H/L/C、V、P% 分别指开高低收、成交量和当日涨跌幅。MAₙ 为对应观察日前 n 个已完成交易日的量均；实体率按 O，区间比例按 H−L。',
        '',
        f'- **#19** RAW 为 BBI>W>Y、J≤13。取 D 前 1–35 日最近 RAW 或 Key-K（C>O、P≥3%、V/MA5≥1.20、C>W>Y）。从锚至 D−1 找 H 峰，再找其后的 L 谷，须见下降收盘且期间无收盘跌破锚低。回撤 1%–22% 或 J≤20，谷日 V 对前 MA5 与 MA10 均≤0.85；峰日量比单列。D 收盘守 Y，距 W≥−2.5%、|P|≤3.5%，且风险影子清除。{w_tol} 个 Formal 影子收在 W 下但仍在容差内，同日 RAW 无法作本日锚。',
        f'- **#20** 口述影子要求 D 前 1–10 日有 Formal 影子，或有五日新低/并列低、J≤20、V/MA5≤0.85、Y≤C≤W 的基座。D 须 C>O、实体≥3%、实体/区间≥0.50、收盘位置≥0.70、V≥1.20×昨量且≥1.20×MA5。1006 为 P≥4%、J<55；151 为 V>1.20×昨量，各命中 {counts["B2_1006_SCREEN_raw"].get("TRUE",0)}/{counts["B2_151_PREV_VOL_X1_20_raw"].get("TRUE",0)} 日。F03 为 D−2 至 D 至少一个 J<13、V>1.25×MA4、P>4%、J<70、W>Y。第五轨为 UNKNOWN_PLACEHOLDER。各轨后续回踩绑定前 1–10 日独立 D0，低于 D0 收盘≥1%、V/MA5≤0.85，再检 #19 价格支撑与影子风险。F03 移出分布为 {failure_line}。',
        f'- **#25** C<W 且 L≤Y 首日记录价格破坏 D，冻结原 Key-K 低和已用左右各两根确认的前摆动高。1–12 日后 T 要求 L 距 Y −2% 至 +1%、C≥Y、P≥−3.5%、V/MA5≤0.85。T 后 1–10 日 C 须阳实体≥3%、实体/区间≥0.50、收盘位置≥0.70、V≥1.20×MA5 且 ≥1.20×T 量、收复 W 和 T 高，且未低于旧锚并通过独立风险。保留原始破坏及历史跌破。整段回撤为前摆动高至 D–T 最低价，`REPORTING_ONLY`，15%–20% 没有资格硬门。信号队列 D/T/C 为 {counts["m25_d_damage_today"].get("TRUE",0)}/{counts["m25_t_yellow_test_today"].get("TRUE",0)}/{counts["m25_c_rebuild_price_today"].get("TRUE",0)} 日。',
        '- **风险** 近五日任一收盘低于 Y 超 4%、负实体≥5%且 V/MA5≥1.5，或疑似 ST，影子阻断。主板过首五日后检查 4.5%–5.5% 单价线，或当前触及 4.85%–5.25% 收盘极值且近二十日同类≥2 次。官方历史 ST、退市和 PIT 缺证，认证保留 UNKNOWN/CANNOT_CONFIRM。S_FIT=B_FIT=0。图册 D 后仅目视复盘，双侧纵轴由 D 的 35 日窗口固定。','',
        '**包外预期 SHA-256**','',f'- CSV `{hashes[CSV]}`',f'- ZIP `{hashes[ZIP]}`',f'- 合同 `{CONTRACT_SHA}`','']
    path.write_text('\n'.join(lines),encoding='utf-8')


def run_shadow(args):
    rules=load_rules(args.output)
    cohort,indicators,src=open_prior(args.prior)
    result,history,schema=evaluate(rules,indicators,cohort)
    prefix_days=prefix_check(rules,indicators,result)
    rows=list(result.values())
    chosen=sample(rows,rules)
    args.evidence.mkdir(parents=True,exist_ok=True)
    selected=chart_package(args.output/ZIP,indicators,chosen,rules['charts'])
    by_date={case['date']:case['chart_id'] for case in selected}
    # Keep historical episode history quoted in CSV readably and bind the full trace separately.
    joined=[]
    for row in rows:
        current={**row,'blind_chart_id':by_date.get(row['date'],'')}
        record=current['m25_previous_terminal_record']
        current['m25_previous_terminal_record']=dump(record) if record is not None else ''
        joined.append(current)
    write_csv(args.output/CSV,joined)
    out_hashes={filename:sha256(args.output/filename) for filename in (CSV,ZIP)}
    counts={key:dict(Counter(row[key] for row in rows)) for key in schema}
    make_summary(rows,out_hashes,counts,args.output/MD)
    events=args.evidence/'m25_episode_trace_d_only.jsonl'
    events.write_text(''.join(dump(event)+'\n' for event in history),encoding='utf-8')
    contract_hash=sha256(args.output/CONTRACT)
    write_json(args.evidence/'blind_case_lock.json',{'selection_mode':'D_ONLY','source_generation':src['source_generation'],
                'contract_sha256':contract_hash,'cases':selected,'csv_sha256':out_hashes[CSV],'blind_zip_sha256':out_hashes[ZIP]})
    write_json(args.evidence/'shadow_receipt.json',{
        'cohort_rows':len(rows),'source_generation':src['source_generation'],'common_indicators_sha256':src['common_indicators_sha256'],
        'cohort_and_frozen_v40_sha256':PRIOR_CSV_SHA,'contract_sha256':contract_hash,'contract_frozen_at_utc':'2026-11-27T11:10:08Z',
        'common_prefix_equality_dates':prefix_days,'status_fields_validated':len(schema),'unregistered_status_rows':0,
        'status_schema':schema,'status_counts':counts,'m25_trace_events':len(history),'m25_trace_sha256':sha256(events),
        'artifact_sha256':{**out_hashes,MD:sha256(args.output/MD),CONTRACT:contract_hash},
        'RESEARCH_ONLY':True,'S_FIT':0,'B_FIT':0,'production_allowed':False,'orders_sent':False,
    })
    print(json.dumps({'rows':len(rows),'prefix_equal_dates':prefix_days,'status_fields':len(schema),'m25_trace_rows':len(history),
                      'charts':[{k:case[k] for k in ('chart_id','date','stratum','td_idx')} for case in selected]},ensure_ascii=False))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    for action in ('shadow','atlas'):
        sub=commands.add_parser(action)
        for key in ('prior','output','evidence'):
            sub.add_argument(f'--{key}',type=Path,required=True)
        if action=='atlas':
            sub.add_argument('--forward',type=Path,required=True)
            sub.add_argument('--forward-provenance',type=Path,required=True)
    args=parser.parse_args()
    (run_shadow if args.command=='shadow' else run_atlas)(args)


def forward_sessions(path,selected,provenance,expected):
    from research.act067b.semantic_shadow import Session

    cases={case['date']:case for case in selected}
    data={day:[] for day in cases}
    for row in read_csv(path):
        d=row['anchor_D']
        if d not in data:
            raise ValueError('Forward-only volume contains a date outside the lock')
        offset=int(row['offset'])
        daily=data[d]
        if offset!=len(daily)+1 or offset>expected:
            raise ValueError(f'Wrong forward offset {offset} at {d}')
        if 'td_idx' in row and int(row['td_idx'])!=cases[d]['td_idx']+offset:
            raise ValueError('Unexpected stock trading-session offset')
        bar=Session.from_row(row)
        if bar.day<=(daily[-1].day if daily else as_date(d)):
            raise ValueError('A forward date precedes D or its previous offset')
        daily.append(bar)
    if any(len(bars)!=expected for bars in data.values()):
        raise ValueError('Review atlas requires all 15 later sessions per page')
    if {d:[str(bars[0].day),str(bars[-1].day)] for d,bars in data.items()}!=provenance['window_start_end']:
        raise ValueError('Review-only projected dates differ from provenance')
    return data


def run_atlas(args):
    from reportlab.lib.colors import HexColor
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen.canvas import Canvas

    rules=load_rules(args.output)['charts']
    lock_path=args.evidence/'blind_case_lock.json'
    lock=read_json(lock_path)
    cases=lock['cases']
    csv_path=args.output/CSV
    zip_path=args.output/ZIP
    sidecar=read_json(args.forward_provenance)
    prior_provenance=read_json(args.prior/'inputs'/'timeline_provenance.json')
    if (sha256(lock_path)!=sidecar['blind_case_lock_sha256'] or sha256(args.forward)!=sidecar['projection_sha256']
        or sidecar['generation']!=lock['source_generation'] or sidecar['market_basis']!=prior_provenance['market_basis']
        or sidecar['rows']!=len(cases)*rules['forward_sessions'] or sidecar['complete_Dplus15_pages']!=len(cases)
        or sidecar['allowed_in_engine'] is not False or sidecar['allowed_in_redteam'] is not False
        or sidecar['allowed_in_axis_limits'] is not False):
        raise ValueError('Atlas-only input is not bound to D-only lock and same-source scope')
    if lock['csv_sha256']!=sha256(csv_path) or lock['blind_zip_sha256']!=sha256(zip_path) or lock['contract_sha256']!=CONTRACT_SHA:
        raise ValueError('D-only artifacts changed after lock')
    rows={row['date']:row for row in read_csv(csv_path) if row['blind_chart_id']}
    future=forward_sessions(args.forward,cases,sidecar,rules['forward_sessions'])
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    pdf_path=args.output/PDF
    canvas=Canvas(str(pdf_path),pagesize=(1200,724),invariant=True,pageCompression=1)
    canvas.setTitle('ACT-067D 钧达股份 002865.SZ 用户复核图册')
    canvas.setSubject('Separate forward visual observation with all geometry fixed at D')
    canvas.setAuthor('ACT-067D')

    def line(x,y,message,size=15,color='#14263d'):
        canvas.setFont('STSong-Light',size)
        canvas.setFillColor(HexColor(color))
        canvas.drawString(x,y,message)

    pages=[]
    with ZipFile(zip_path) as archive:
        manifest=read_manifest(archive)
        for case in cases:
            identifier,d=case['chart_id'],case['date']
            if rows[d]['blind_chart_id']!=identifier:
                raise ValueError('Locked chart identity mismatch')
            article=manifest[identifier]
            left_png=archive.read(article['file'])
            if hashlib.sha256(left_png).hexdigest()!=case['sha256'] or case['sha256']!=article['sha256']:
                raise ValueError('Blind panel changed after D-only lock')
            keys=('d_close_reference','price_ylim','vol_ylim','j_ylim','right_price_ylim','right_vol_ylim','right_j_ylim')
            bounds={key:case[key] for key in keys}
            if any(bounds[key]!=article[key] for key in keys) or article['ylim_source']!='D_ONLY_SLICE':
                raise ValueError('Forward chart requires locked D-only geometry')
            right_png,clipping=render(future[d],bounds,rules,forward=True)
            r=rows[d]
            last=str(future[d][-1].day)
            canvas.setFillColor(HexColor('#f4f7fb'))
            canvas.rect(0,0,1200,724,stroke=0,fill=1)
            line(28,688,f'{identifier}  钧达股份（002865.SZ）',25)
            line(30,661,f'观察 D  {d}    |    三层表 {r["v31_3_structure_status"]} / {r["v31_3_formula_tags"]}',15,'#405572')
            line(29,620,'左图 / 盲审 D-only 原图',18)
            line(608,620,'D后仅目视复盘区 / 严禁入引擎',18)
            dimensions={'width':564,'height':388}
            canvas.drawImage(ImageReader(BytesIO(left_png)),24,218,**dimensions)
            canvas.drawImage(ImageReader(BytesIO(right_png)),604,218,**dimensions)
            line(29,193,f'V4.0 同源 RAW {r["v40_replay_formula_hit_tags"] or "NONE"}    合格 {r["v40_replay_new_entry_qualified_tags"] or "NONE"}',14)
            line(29,166,f'#19 RAW {r["b1_raw"]}    Formal 影子 {r["b1_formal_shadow"]}    #20 口述影子 {r["B2_ORAL_CORE_SHADOW_raw"]}',14)
            line(29,139,f'#20 1006 / 151 / F03：{r["B2_1006_SCREEN_raw"]} / {r["B2_151_PREV_VOL_X1_20_raw"]} / {r["USER_FORMULA_B2_F03_raw"]}',14)
            line(29,112,f'#25 阶段 {r["m25_phase"]}    重建影子 {r["m25_rebuild_shadow"]}    市场风险影子 {r["risk_clear_shadow"]}',14)
            line(608,193,f'D+1 {future[d][0].day}    |    D+15 {last}    |    共 15 个交易日',14)
            line(608,166,'价格和成交量纵轴由左图 D 截止窗口固定，超界见橙三角。',14)
            line(608,139,f'超界记录   价格 {clipping["price"]}    量 {clipping["volume"]}    J {clipping["j"]}',14)
            line(608,112,'D 日收盘统一为 100。官方历史 ST 和退市身份未确认。',14)
            line(29,45,'ACT-067D    |    RESEARCH_ONLY    |    S_FIT=0    B_FIT=0',12,'#405572')
            canvas.showPage()
            pages.append({'chart_id':identifier,'D':d,'D_plus_1':str(future[d][0].day),'D_plus_15':last,
                          'future_sessions':len(future[d]),'left_png_sha256':case['sha256'],
                          'right_png_sha256':hashlib.sha256(right_png).hexdigest(),'ylim_source':'D_ONLY_SLICE',
                          'geometry':bounds,'clipping':clipping})
    canvas.save()
    receipt={'atlas_sha256':sha256(pdf_path),'lock_sha256':sha256(lock_path),'source_generation':lock['source_generation'],
             'forward_projection_sha256':sidecar['projection_sha256'],'page_count':len(pages),'pages':pages}
    write_json(args.evidence/'atlas_receipt.json',receipt)
    print(json.dumps({k:receipt[k] for k in ('atlas_sha256','page_count')}))


def read_manifest(archive):
    manifest=json.loads(archive.read('MANIFEST_SHA256.json'))
    return {item['chart_id']:item for item in manifest['charts']}


if __name__=='__main__':
    main()
