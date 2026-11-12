"""Frozen monthly development-set analysis. No model fitting or external collection."""
from pathlib import Path
import json, csv, hashlib, time, sys
ROOT=Path('/Users/lexi/Desktop/学习/agents调试/Z哥方法论/monthly_top200_events_20261012_20261111')
P=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/today_full_r1/daily_products/a_share')
def read(p): return json.loads(Path(p).read_text())
def save(n,x): (ROOT/'analysis'/n).write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str))
if __name__=='__main__':
    save('CONFIG.json',{'new_fit':0,'window':'20261012..20261111','features':'<=D','outcomes_end':'20261111','all_month':'DEVELOPMENT_SET','sealed_set_opened':False})

import pandas as pd, numpy as np, importlib.util, collections
csv.field_size_limit(100_000_000)
APP=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-workbench-quote-contract-20261112-r1/api/app')
sys.path.insert(0,str(APP))
from ops.research_panel_logical import parquet
PAIRROOT=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/storage_governance_v2/paired')
CLASS=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030/workbench_engineering_rectification_20261030/classification_sources/ALL_MARKET_CODE_SOURCES_QA/delivery/all_a_classification.json')
PRE=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/preselection_inputs')
R3=Path('/Users/lexi/Desktop/学习/Z哥方法论/PULLBACK_EVENT_R3_WORKTREE/05_EXPERIMENTS/PULLBACK_EVENT_R3/event_r3_v1_1.py')
METHODS=Path('/Users/lexi/Desktop/学习/agents调试/Z哥方法论/top200_yesterday_20261111/skill_review/TOP200_D11_34_METHOD_STATES.csv')
def read(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def csvout(n,rows):
    z=rows if isinstance(rows,pd.DataFrame) else pd.DataFrame(rows)
    z.to_csv(ROOT/'analysis'/n,index=False,encoding='utf-8-sig');return z

def canon(s):
    s=str(s).upper().strip()
    if s.startswith('A.'): s=s[2:]
    if len(s)==6 and s.isdigit():return s+('.SZ' if s.startswith(('00','30')) else '.SH' if s.startswith(('60','68')) else '.BJ')
    return s if s.endswith(('.SZ','.SH','.BJ')) else None

def prepare():
    cfg={'new_fit':0,'all_month':'DEVELOPMENT_SET','feature_dates':'<=D','outcome_end':20261111,'price_basis':'QFQ_ASOF_D11_NONPIT',
        'ranking':'published artifact preferred; else pct_chg descending then ts_code ascending, positive finite close/volume; qualified members of fixed 20261028 A-share classification directory only',
        'reconstruction':'RECONSTRUCTED_CURRENT_FIXED_RULE_NOT_ACTUAL_HISTORICAL_SELECTION; current directory survivorship and nonPIT',
        'control_signature':['direction_white_yellow','close_vs_BBI','J_bin','user_v1_B1','user_v1_B2'],
        'control_selection':'for each D signature represented in O Top200 choose first 3 lexicographic qualified exact-D non-O-Top200 symbols; no outcome used',
        'episode_identity':'R3 fixed original anchor; current event bound only if exactly one unbroken supported origin AND it is latest discovered origin. Otherwise CURRENT_EVENT_UNKNOWN or NO_ACTIVE_PROXY_ORIGIN. Current binding is engineering proxy, not manual truth.',
        'history_start':20260803,'sparse_extension':'if no origin at earliest requested D extend that affected stock to 20260105, retaining left censoring',
        'outcomes':{'horizons':[1,3,5,10],'return':'close_exact_target/close_D-1','MFE':'max(high over exact next h calendar sessions)/close_D-1','MAE':'min(low over same sessions)/close_D-1','missing_or_unmatured':'null PENDING or DATA_GAP; never zero','interpretation':'descriptive adjusted price path, not executable PnL'},
        'descriptive_path_class':'5-session observed close sign (>0, <0, =0), PENDING or UNKNOWN; never success label',
        'market_state':'cross-sectional qualified exact-D pct_chg breadth: >60%up BROAD_UP, <40%up BROAD_DOWN, else MIXED; descriptive nonPIT, not index regime',
        'methods':'34 existing method names; reused raw materialized field contexts, NOT full SOP and NOT human labels; no automatic positive/negative truth',
        'fit_or_transform_calls':0,'sealed_set_opened':False,'manual_chart_review':'NOT_RUN','RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    save('FROZEN_ANALYSIS_CONFIG.json',cfg);save('CONFIG_HASH.json',{'sha256':sha(ROOT/'analysis/FROZEN_ANALYSIS_CONFIG.json')})
    cal=pd.read_csv(ROOT/'coordination/OBSERVATION_CALENDAR.csv',dtype=str)
    pair=read(ROOT/'analysis/PAIR_BINDING.json') if (ROOT/'analysis/PAIR_BINDING.json').exists() else read(read(PAIRROOT/'current.json')['current']['path']);save('PAIR_BINDING.json',pair)
    panel=pair['roles']['selector']['path'];schema=parquet.read_schema(panel)
    save('SOURCE_READ_IDENTITY.json',{'app_root':APP,'reader_sha256':sha(APP/'ops/research_panel_logical.py'),'panel_path':panel,'stat':dict(size=Path(panel).stat().st_size,mtime_ns=Path(panel).stat().st_mtime_ns),'declared_sha256':pair['roles']['selector']['sha256'],'generation':pair['identity']['generation_id'],'schema_fields':schema.names,'classification':{'path':CLASS,'sha256':sha(CLASS)},'R3':{'path':R3,'sha256':sha(R3)},'calendar':read(ROOT/'coordination/CALENDAR_BINDING.json')})
    qp=ROOT/'analysis/SOURCE_QUALIFICATION_PROJECTION.json'
    if qp.exists():q=read(qp)
    elif (ROOT/'analysis/SOURCE_QUALIFICATION_COMPACT.json').exists():
        refs=read(ROOT/'analysis/SOURCE_QUALIFICATION_REFERENCES.json');q={}
        for sym,v in read(ROOT/'analysis/SOURCE_QUALIFICATION_COMPACT.json').items():q[sym]={**v,'accepted_evidence':[refs[k] for k in v['accepted_evidence_ids']]}
    else:
        snap=read(pair['identity']['adjustment_snapshot']['path']);q={sym:{k:v for k,v in z.items() if k in ['accepted_evidence','publish_roles','warmup','source_policy','status','quarantine_reasons']} for sym,z in snap['symbols'].items() if sym.endswith(('.SZ','.SH','.BJ'))}
    qualified={s for s,v in q.items() if v.get('accepted_evidence') and 'selector' in v.get('publish_roles',[])}
    # Deduplicate repeated evidence references while retaining exact per-symbol source identity.
    refs={};compact={}
    for s,v in q.items():
        ids=[]
        for e in v.get('accepted_evidence',[]):
            k=e.get('sha256') or str(e);refs[k]=e;ids.append(k)
        compact[s]={k:val for k,val in v.items() if k!='accepted_evidence'};compact[s]['accepted_evidence_ids']=ids
    save('SOURCE_QUALIFICATION_REFERENCES.json',refs);save('SOURCE_QUALIFICATION_COMPACT.json',compact)
    cls=read(CLASS);directory={r['symbol']:r for r in cls['classifications'] if r.get('instrument_type')=='A_SHARE'}
    idx=read(P/'index.json');month=pd.read_parquet(ROOT/'analysis/MONTH_PRICE_INDEX.parquet');month.trade_date=month.trade_date.astype(str)
    tops=[];candidates=[];coverage=[];sources=[];gaps=[]
    for r in cal.to_dict('records'):
        O,D=r['observation_date_O'],r['judgement_date_D'];kind='PUBLISHED_TOP200' if O in idx['top200'] else 'RECONSTRUCTED_CURRENT_FIXED_RULE_NONPIT'
        if O in idx['top200']:
            ref=idx['top200'][O];ob=read(ref['path']);assert sha(ref['path'])==ref['sha256'];tr=ob['top200'];sources.append(dict(kind='TOP200',date=O,**ref))
        else:
            a=month[(month.trade_date==O)&month.ts_code.isin(qualified&directory.keys())].copy()
            # exact-D bar volume is checked from the shared projection below; thin index is prices only.
            a=a[np.isfinite(a.pct_chg)&(a.close>0)].sort_values(['pct_chg','ts_code'],ascending=[False,True]).head(200)
            tr=[{'symbol':x.ts_code,'rank':j+1,'change_pct':x.pct_chg,'name':directory[x.ts_code].get('name')} for j,x in enumerate(a.itertuples())]
        for t in tr: tops.append(dict(O=O,D=D,symbol=t['symbol'],rank=t['rank'],O_change_pct=t.get('change_pct'),top200_identity=kind,name=t.get('name',''),top200_historical_availability='CANNOT_CONFIRM' if kind!='PUBLISHED_TOP200' else 'STORED_PUBLICATION_NOT_EVIDENCE_OF_PRE_O_SELECTION'))
        pc=0
        if D in idx['dates']:
            mr=idx['dates'][D];m=read(mr['path']);ar=m.get('artifact',{});prod=read(ar['path']) if ar.get('path') else {};sources.append(dict(kind='CANDIDATE_PRODUCT',date=D,**mr))
            for z in prod.get('rows',[]):
                s=canon(z.get('symbol'));groups=z.get('groups','')
                if s and groups:
                    candidates.append(dict(O=O,D=D,symbol=s,candidate_origin='ARCHIVED_DAILY_FORMULA_RESULT',groups=groups,source_path=ar['path'],source_sha256=ar.get('sha256'),first_saved_at='UNKNOWN',declared_generated_at='UNKNOWN',availability_before_O='CANNOT_CONFIRM',producer_identity=prod.get('schema_version','UNKNOWN'),signal_date=D));pc+=1
        for folder in sorted(PRE.iterdir()):
            if not folder.is_dir() or folder.name>O:continue
            for lane in ['fupan','stage7']:
                mp=folder/(lane+'.manifest.json');cp=folder/(lane+'.csv')
                if not mp.exists() or not cp.exists():continue
                m=read(mp);sd=str(m.get('signal_date') or m.get('data_date') or '')
                if sd!=D: continue
                rr=list(csv.DictReader(cp.open(encoding='utf-8-sig')));sources.append(dict(kind='ARCHIVED_PRESELECTION',date=D,path=str(cp),sha256=sha(cp),manifest_path=str(mp),manifest_sha256=sha(mp)))
                for z in rr:
                    s=canon(z.get('ts_code') or z.get('symbol') or z.get('code') or z.get('stock_code'))
                    if s: candidates.append(dict(O=O,D=D,symbol=s,candidate_origin='ARCHIVED_PRESELECTION_'+lane.upper(),groups=lane,source_path=str(cp),source_sha256=sha(cp),first_saved_at='UNKNOWN',declared_generated_at=m.get('generated_at','UNKNOWN'),availability_before_O='CANNOT_CONFIRM',producer_identity=m.get('source_role',m.get('schema_version','UNKNOWN')),signal_date=sd));pc+=bool(s)
        if not pc:gaps.append(dict(O=O,D=D,symbol='*',gap='ORIGINAL_CANDIDATE_ARCHIVE_NOT_LOCATED_FOR_D',implication='NO_FALSE_NEGATIVE_ASSUMPTION'))
        coverage.append(dict(O=O,D=D,top200_rows=len(tr),top200_identity=kind,candidate_membership_rows=pc,candidate_status='AVAILABLE_ARCHIVED_RESULT_AVAILABILITY_UNKNOWN' if pc else 'CANNOT_CONFIRM'))
    csvout('TOP200_SEED.csv',tops);csvout('CANDIDATE_MEMBERSHIPS.csv',candidates);csvout('SOURCE_COVERAGE.csv',coverage);csvout('GAPS_INITIAL.csv',gaps);save('SOURCE_REFERENCES.json',sources)
    save('CURRENT_STATE.json',{'state':'FIRST_ROWS_SAVED','top200_stock_days':len(tops),'candidate_memberships':len(candidates),'source_sessions':23,'new_fit':0})
    print('SEEDS',len(tops),len(candidates),len(qualified),flush=True)
    return cfg,cal,pair,qualified,directory

if __name__=='__main__' and '--prepare' in sys.argv: prepare()

FIELDS=['ts_code','trade_date','market_type','open','high','low','close','volume','pct_chg','pre_close','BBI','zge_white_line','zge_yellow_line','J','ma5','ma10','ma20','ma30','ma60','macd_dif','macd_dea','macd_hist','brick_type_value','brick_short','brick_long','brick_red_length','brick_resonance','breakout','plry_volume_burst','strong_volume_up','single_needle_under20','three_quarter_yin_volume_line','formula_source','field_contract_version']+['user_v1_'+x for x in ['B1','B2','B3','breakout','breakout_cross_star','single_needle_under20','break_prev_low','under_yellow','white_yellow_death_cross','macd_below_zero_second_gold','macd_above_zero_second_gold','three_quarter_yin_volume_line','hold_yesterday_keyline_daily','break_yesterday_keyline_daily','sell_signal_daily']]

def direction(r):
    w,y=r.get('zge_white_line'),r.get('zge_yellow_line')
    if pd.isna(w) or pd.isna(y):return 'UNKNOWN'
    return 'WHITE_ABOVE_YELLOW' if w>y else 'WHITE_BELOW_YELLOW' if w<y else 'WHITE_EQUAL_YELLOW'
def signature(r):
    def flag(k):return 'UNKNOWN' if pd.isna(r.get(k)) else str(int(r[k]))
    j=r.get('J');b=r.get('BBI');c=r.get('close')
    return '|'.join([direction(r),'UNKNOWN' if pd.isna(b) or pd.isna(c) else 'ABOVE_BBI' if c>=b else 'BELOW_BBI','UNKNOWN' if pd.isna(j) else 'J_LOW' if j<=13 else 'J_MID' if j<=80 else 'J_HIGH',flag('user_v1_B1'),flag('user_v1_B2')])

def projection():
    pair=read(ROOT/'analysis/PAIR_BINDING.json');p=pair['roles']['selector']['path'];cfg=read(ROOT/'analysis/FROZEN_ANALYSIS_CONFIG.json')
    q=read(ROOT/'analysis/SOURCE_QUALIFICATION_COMPACT.json');qualified={s for s,v in q.items() if v['accepted_evidence_ids'] and 'selector' in v.get('publish_roles',[])}
    directory={x['symbol']:x for x in read(CLASS)['classifications'] if x.get('instrument_type')=='A_SHARE'}
    t=time.time()
    cache=ROOT/'analysis/MONTH_MATERIALIZED_FIELDS.parquet'
    if cache.exists():f=pd.read_parquet(cache)
    else:
        f=parquet.read_table(p,columns=FIELDS,filters=[('trade_date','>=','20261009'),('trade_date','<=','20261111')]).to_pandas();f.trade_date=f.trade_date.astype(str);f=f[f.ts_code.isin(qualified)].copy();f['signature']=f.apply(signature,axis=1);f.to_parquet(cache,index=False)
    top=pd.read_csv(ROOT/'analysis/TOP200_SEED.csv',dtype={'O':str,'D':str});mem=pd.read_csv(ROOT/'analysis/CANDIDATE_MEMBERSHIPS.csv',dtype={'O':str,'D':str,'signal_date':str});cal=pd.read_csv(ROOT/'coordination/OBSERVATION_CALENDAR.csv',dtype=str)
    # Apply frozen positive-volume filter before finalizing reconstructed rankings.
    corrections=[]
    for O,g in top.groupby('O'):
        if g.iloc[0].top200_identity=='PUBLISHED_TOP200':continue
        d=g.iloc[0].D;pool=f[(f.trade_date==O)&f.ts_code.isin(directory)&(f.close>0)&(f.volume>0)&np.isfinite(f.pct_chg)].sort_values(['pct_chg','ts_code'],ascending=[False,True]).head(200)
        corrections.extend(dict(O=O,D=d,symbol=x.ts_code,rank=j+1,O_change_pct=x.pct_chg,top200_identity='RECONSTRUCTED_CURRENT_FIXED_RULE_NONPIT',name=directory[x.ts_code].get('name',''),top200_historical_availability='CANNOT_CONFIRM') for j,x in enumerate(pool.itertuples()))
    top=pd.concat([top[top.top200_identity=='PUBLISHED_TOP200'],pd.DataFrame(corrections)],ignore_index=True).sort_values(['O','rank']);csvout('TOP200_SEED.csv',top)
    controls=[];market=[]
    for r in cal.to_dict('records'):
        O,D=r['observation_date_O'],r['judgement_date_D'];dg=f[(f.trade_date==D)&f.ts_code.isin(directory)].copy();tg=top[top.O==O];ss=set(tg.symbol);sigs=set(dg[dg.ts_code.isin(ss)].signature)
        for sig,g in dg[(~dg.ts_code.isin(ss))&dg.signature.isin(sigs)&(dg.volume>0)].groupby('signature'):
            for x in g.sort_values('ts_code').head(3).itertuples():controls.append(dict(O=O,D=D,symbol=x.ts_code,control_signature=sig,selection='LEXICOGRAPHIC_3_PER_TOP200_D_SIGNATURE_NO_FUTURE_OUTCOME'))
        valid=dg[np.isfinite(dg.pct_chg)];up=(valid.pct_chg>0).mean() if len(valid) else None
        market.append(dict(D=D,market_qualified_bars=len(valid),market_up_share=up,market_state='UNKNOWN' if up is None else 'BROAD_UP' if up>.6 else 'BROAD_DOWN' if up<.4 else 'MIXED'))
    ctrl=csvout('CONTROL_SEED.csv',controls);csvout('MARKET_STATE.csv',market)
    cand=mem.groupby(['O','D','symbol'],as_index=False).agg(candidate_origin=('candidate_origin',lambda x:'|'.join(sorted(set(x)))),groups=('groups',lambda x:'|'.join(sorted(set(x)))),availability_before_O=('availability_before_O','first'),first_saved_at=('first_saved_at','first'))
    csvout('CANDIDATE_UNION_SEED.csv',cand)
    target=pd.concat([top[['O','D','symbol']],cand[['O','D','symbol']],ctrl[['O','D','symbol']]]).drop_duplicates().sort_values(['symbol','D']);csvout('TARGET_STOCK_DAYS.csv',target)
    symbols=sorted(set(target.symbol)&qualified);t=time.time();hp=ROOT/'analysis/HISTORY_TARGET_PROJECTION.parquet'
    hist=pd.read_parquet(hp) if hp.exists() else pd.DataFrame(columns=FIELDS)
    missing=sorted(set(symbols)-set(hist.ts_code))
    if missing:
        inc=parquet.read_table(p,columns=FIELDS,filters=[('ts_code','in',missing),('trade_date','>=','20260803'),('trade_date','<=','20261111')]).to_pandas();hist=pd.concat([hist,inc],ignore_index=True)
    hist.trade_date=hist.trade_date.astype(int);hist=hist.sort_values(['ts_code','trade_date']);hist.to_parquet(hp,index=False)
    save('PROJECTION_RECEIPT.json',{'month_rows':len(f),'target_stock_days':len(target),'target_symbols':target.symbol.nunique(),'qualified_target_symbols':len(symbols),'history_rows':len(hist),'history_read_seconds':time.time()-t,'candidate_union_stock_days':len(cand),'control_stock_days':len(ctrl),'new_fit':0})
    print('PROJECTION',len(target),len(symbols),len(hist),len(cand),len(ctrl),flush=True)

if __name__=='__main__' and '--project' in sys.argv: projection()

def engine():
    global E
    if 'E' not in globals():
        sp=importlib.util.spec_from_file_location('frozen_r3',R3);E=importlib.util.module_from_spec(sp);sp.loader.exec_module(E)
    return E
R3CFG={'sweep_previous_bars':5,'weakness_compare_bars':5,'weakness_breakout_high_bars':3,'attack_breakout_high_bars':3,'prior_structure_low_bars':20}

def first_qualifications(g,evs,attacks):
    rows=g.to_dict('records');out={};eng=engine();bydate={r['trade_date']:i for i,r in enumerate(rows)}
    for e in evs:
        ori=e['origin_date'];i=bydate[ori];peak=rows[i]['close'];origin_first=None;attack_first=None;touch_first=None;restore_first=None;support_unknown=False
        ats=sorted([a for a in attacks if a['origin_date']==ori],key=lambda a:a['attack_date']);latest=None;ai=0
        unknown_attacks=[int(float(x)) for x in str(e.get('unknown_attack_dates','')).split('|') if x and x!='nan']
        for j in range(i+1,len(rows)):
            r=rows[j];d=r['trade_date']
            while ai<len(ats) and ats[ai]['attack_date']<=d:latest=ats[ai];ai+=1
            if e.get('first_close_breach_date') and d>=e['first_close_breach_date']:break
            if not eng.price_valid(r):support_unknown=True;continue
            v=eng.num(r.get('vol'));ov=e['origin_volume'];good=v is not None and v>0 and not support_unknown
            if good and ov and ov>0 and r['close']<=peak and r['low']<=e['origin_high'] and r['close']>=e['origin_low'] and v<ov:
                if origin_first is None:origin_first=d
                if touch_first is None:touch_first=d
            if good and latest and latest['attack_date']<d and not any(latest['attack_date']<u<=d for u in unknown_attacks) and latest['attack_volume'] and r['close']<=peak and r['low']<=latest['attack_high'] and r['close']>=latest['attack_low'] and v<latest['attack_volume']:
                if attack_first is None:attack_first=d
                if touch_first is None:touch_first=d
            if touch_first and d>touch_first and latest and latest['attack_date']==d:restore_first=d if restore_first is None else restore_first
            # Recovery means later confirmed attack after a qualifying pullback; current-day attack is in ats.
            if touch_first and d>touch_first and any(a['attack_date']==d for a in ats):restore_first=d if restore_first is None else restore_first
            peak=max(peak,r['close'])
        out[ori]=dict(first_origin_qualification=origin_first,first_attack_qualification=attack_first,first_any_qualification=min([x for x in [origin_first,attack_first] if x is not None],default=None),first_pullback_recovered_attack=restore_first)
    return out

def analyze_symbol(task):
    symbol,g,days=task;g=g.copy();g['vol']=g.volume;g['bbi']=g.BBI;eng=engine();observations=[]
    maxD=max(days);end=eng.evaluate(g,maxD,R3CFG);fq=first_qualifications(g[g.trade_date<=maxD],end['events'],end['attacks'])
    for D in days:
        r=end if D==maxD else eng.evaluate(g,D,R3CFG);ss=r['stock'];ev=r['events'];live=[e for e in ev if e['first_close_breach_date'] is None and e['support_state']!='UNKNOWN']
        current=None
        if not ss.get('exact_asof'):state='SOURCE_OR_EXACT_D_GAP'
        elif len(live)==1 and ev and live[0]['origin_date']==ev[-1]['origin_date']:state='SINGLE_LATEST_LIVE_PROXY_ORIGIN';current=live[0]
        elif live:state='CURRENT_EVENT_UNKNOWN'
        elif ev:state='ALL_PROXY_ORIGINS_INVALIDATED'
        else:state='NO_DISCOVERED_PROXY_ORIGIN'
        obs=dict(symbol=symbol,D=str(D),feature_max_date=ss.get('actual_last_date'),history_first_date=ss.get('history_first_date'),history_rows=ss.get('history_rows'),current_event_state=state,live_origin_count=len(live),discovered_origin_count=len(ev),current_event_id=f'{symbol}|UP_REVERSAL_PROXY|{current["origin_date"]}' if current else None,unresolved_origin_dates='|'.join(str(e['origin_date']) for e in live) if state=='CURRENT_EVENT_UNKNOWN' else '',origin_any_proxy=ss.get('origin_any'),attack_any_proxy=ss.get('attack_any'),combined_any_proxy=ss.get('combined_any'),asof_volume_state=ss.get('asof_volume_state'),origin_date=current.get('origin_date') if current else None,management_date=current.get('management_date') if current else None,origin_retest_proxy=current.get('origin_retest_status') if current else 'UNKNOWN',attack_retest_proxy=current.get('attack_retest_status') if current else 'UNKNOWN',origin_retest_reason=current.get('origin_retest_reason') if current else state,first_qualification_date=fq[current['origin_date']]['first_any_qualification'] if current and fq[current['origin_date']]['first_any_qualification'] and fq[current['origin_date']]['first_any_qualification']<=D else None,origin_volume=current.get('origin_volume') if current else None,management_volume=current.get('management_volume') if current else None,volume_numerator_D=ss.get('asof_volume'),volume_vs_origin=current.get('asof_volume_vs_origin') if current else None,volume_vs_management=current.get('asof_volume_vs_management') if current else None,first_intraday_breach_date=current.get('first_intraday_breach_date') if current else None,first_close_breach_date=current.get('first_close_breach_date') if current else None,first_recovery_date=current.get('first_recovery_date') if current else None,known_at=f'{D}T15:00:00+08:00' if ss.get('exact_asof') else None,first_saved_at='UNKNOWN',event_direction='UP_REVERSAL_ENGINEERING_PROXY',left_censored=True,historical_PIT=False)
        observations.append(obs)
    events=[]
    for e in end['events']:
        events.append(dict(symbol=symbol,event_id=f'{symbol}|UP_REVERSAL_PROXY|{e["origin_date"]}',event_record_type='IMMUTABLE_ORIGIN_PROXY_NOT_CONFIRMED_INDEPENDENT_OPPORTUNITY',feature_asof=maxD,**e,**fq[e['origin_date']]))
    attacks=[dict(symbol=symbol,**a) for a in end['attacks']]
    return observations,events,attacks

def run_events():
    import concurrent.futures,resource
    target=pd.read_csv(ROOT/'analysis/TARGET_STOCK_DAYS.csv',dtype={'D':str,'O':str});hist=pd.read_parquet(ROOT/'analysis/HISTORY_TARGET_PROJECTION.parquet');group={s:g for s,g in hist.groupby('ts_code',sort=False)}
    tasks=[(s,group[s],sorted(set(int(x) for x in dg.D))) for s,dg in target.groupby('symbol') if s in group]
    # Reuse completed symbols; recompute only symbols whose requested D coverage changed.
    prior=[]
    op=ROOT/'analysis/EVENT_OBSERVATIONS.csv'
    if op.exists():
        oo=pd.read_csv(op,dtype={'D':str});ee=pd.read_csv(ROOT/'analysis/EVENTS.csv');aa=pd.read_csv(ROOT/'analysis/ATTACK_MANAGEMENT_K.csv')
        completed={(s,str(d)) for s,d in zip(oo.symbol,oo.D)}
        affected={t[0] for t in tasks if any((t[0],str(d)) not in completed for d in t[2])}
        for sym,gg in oo[~oo.symbol.isin(affected)].groupby('symbol'):prior.append((gg.to_dict('records'),ee[ee.symbol==sym].to_dict('records'),aa[aa.symbol==sym].to_dict('records')))
        tasks=[t for t in tasks if t[0] in affected]
    # Three deterministic representatives: SH, SZ, BJ; benchmark results are retained, not repeated.
    chosen=[]
    for suffix in ['.SH','.SZ','.BJ']:
        for t in tasks:
            if t[0].endswith(suffix):chosen.append(t);break
    start=time.time();results=[analyze_symbol(t) for t in chosen];seconds=time.time()-start
    save('BENCHMARK.json',{'symbols':[t[0] for t in chosen],'seconds':seconds,'maxrss':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'workers':10,'queue_limit':20,'reason':'shared thin projection, retained representative results; 18cores/128GiB frozen resource reading','new_fit':0})
    selected={t[0] for t in chosen};todo=[t for t in tasks if t[0] not in selected]
    with concurrent.futures.ProcessPoolExecutor(max_workers=10) as ex:
        pending={};it=iter(todo);done=0
        while True:
            while len(pending)<20:
                try:t=next(it)
                except StopIteration:break
                pending[ex.submit(analyze_symbol,t)]=t[0]
            if not pending:break
            completed,_=concurrent.futures.wait(pending,return_when=concurrent.futures.FIRST_COMPLETED)
            for fu in completed:
                symbol=pending.pop(fu);results.append(fu.result());done+=1
            if done%100==0:
                save('CURRENT_STATE.json',{'state':'EVENTS_RUNNING','symbols_completed':done+len(chosen),'symbols_total':len(tasks),'elapsed_seconds':time.time()-start,'new_fit':0});print('EVENT_PROGRESS',done,len(tasks),round(time.time()-start,1),flush=True)
    sparse=[]
    for res in results:
        if res[0] and min(res[0],key=lambda x:x['D'])['discovered_origin_count']==0:sparse.append(res[0][0]['symbol'])
    save('SPARSE_HISTORY_EXTENSION.json',{'symbols':sparse,'from':20260105,'reason':'no discovered origin at earliest requested D; earlier qualified history only for affected symbols'})
    if sparse:
        panel=read(ROOT/'analysis/PAIR_BINDING.json')['roles']['selector']['path']
        earlier=parquet.read_table(panel,columns=FIELDS,filters=[('ts_code','in',sparse),('trade_date','>=','20260105'),('trade_date','<','20260803')]).to_pandas();earlier.trade_date=earlier.trade_date.astype(int)
        ep=ROOT/'analysis/SPARSE_EARLIER_HISTORY.parquet'
        if ep.exists():earlier=pd.concat([pd.read_parquet(ep),earlier],ignore_index=True).drop_duplicates(['ts_code','trade_date'])
        earlier.to_parquet(ep,index=False)
        results=[r for r in results if not r[0] or r[0][0]['symbol'] not in sparse]
        for sym in sparse:
            hg=pd.concat([earlier[earlier.ts_code==sym],group[sym]],ignore_index=True).sort_values('trade_date')
            ds=sorted(set(int(x) for x in target[target.symbol==sym].D));results.append(analyze_symbol((sym,hg,ds)))
    results=prior+results
    obs=[v for r in results for v in r[0]];events=[v for r in results for v in r[1]];attacks=[v for r in results for v in r[2]]
    csvout('EVENT_OBSERVATIONS.csv',obs);csvout('EVENTS.csv',events);csvout('ATTACK_MANAGEMENT_K.csv',attacks)
    save('EVENT_COMPUTE_RECEIPT.json',{'symbols':len(tasks),'observations':len(obs),'origin_records':len(events),'attack_origin_pairs':len(attacks),'seconds':time.time()-start,'new_fit':0,'independent_opportunity_truth':'CANNOT_CONFIRM_PROXY_ORIGINS_ONLY'})
    print('EVENTS_DONE',len(obs),len(events),flush=True)

if __name__=='__main__' and '--events' in sys.argv: run_events()

def supplement_stage():
    stage=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/selection');cal=pd.read_csv(ROOT/'coordination/OBSERVATION_CALENDAR.csv',dtype=str);new=[];audit=[]
    for r in cal.to_dict('records'):
        O,D=r['observation_date_O'],r['judgement_date_D'];runroot=stage/'selection_runs'/D
        files=sorted(runroot.glob('A_SHARE_SELECTION_STAGE_*/*/manifest.json')) if runroot.exists() else []
        for mp in files:
            m=read(mp);cp=mp.parent/'artifact.csv'
            if str(m.get('trade_date'))!=D or not cp.exists():continue
            datahash=sha(cp)
            if datahash!=m.get('artifact_sha256'):audit.append(dict(O=O,D=D,path=str(cp),status='SOURCE_SHA_MISMATCH'));continue
            env=m.get('selection_envelope',{});rr=list(csv.DictReader(cp.open(encoding='utf-8-sig')))
            audit.append(dict(O=O,D=D,path=str(cp),status='ARCHIVED_STAGE_RESULT_TIME_UNKNOWN',rows=len(rr),sha256=datahash))
            for x in rr:
                code=x.get('code') or x.get('symbol') or x.get('ts_code') or ''
                if code.startswith(('SZ.','SH.','BJ.')):code=code[3:]+'.'+code[:2]
                s=canon(code)
                if s:new.append(dict(O=O,D=D,symbol=s,candidate_origin='ARCHIVED_STAGE_SELECTION_RESULT',groups=m.get('stage_id',m.get('role','UNKNOWN')),source_path=str(cp),source_sha256=datahash,first_saved_at='UNKNOWN',declared_generated_at=env.get('generated_at',env.get('observed_at','UNKNOWN')),availability_before_O='CANNOT_CONFIRM',producer_identity=m.get('algorithm_id','UNKNOWN'),signal_date=D))
        # Recovery/observation snapshots are kept separate from original selection membership.
        recovery=stage/'snapshot_recovery/current'/D
        for pp in sorted(recovery.glob('*/A_SHARE.json')) if recovery.exists() else []:
            z=read(pp);ap=stage/z['artifact_relative'];a=read(ap)
            audit.append(dict(O=O,D=D,path=str(ap),status='SNAPSHOT_RECOVERY_NOT_ORIGINAL_SELECTION',rows=a.get('observed_rows'),sha256=z.get('artifact_sha256'),captured_at=a.get('captured_at')))
    csvout('STAGE_ARCHIVE_AUDIT.csv',audit)
    old=pd.read_csv(ROOT/'analysis/CANDIDATE_MEMBERSHIPS.csv',dtype=str);out=pd.concat([old,pd.DataFrame(new)],ignore_index=True).drop_duplicates(['O','D','symbol','source_path','candidate_origin'])
    csvout('CANDIDATE_MEMBERSHIPS.csv',out);save('STAGE_SUPPLEMENT_RECEIPT.json',{'added_memberships':len(out)-len(old),'total_memberships':len(out),'actual_availability':'CANNOT_CONFIRM','recovery_not_mixed':True})
    print('STAGE_MEMBERSHIPS',len(new),len(out),flush=True)

if __name__=='__main__' and '--stages' in sys.argv: supplement_stage()

def trading_sessions():
    from datetime import date,timedelta
    binding=read(ROOT/'coordination/CALENDAR_BINDING.json');sp=importlib.util.spec_from_file_location('monthly_frozen_calendar',binding['adapter_path']);mod=importlib.util.module_from_spec(sp);sys.modules[sp.name]=mod;sp.loader.exec_module(mod);c=mod.load_market_calendar(Path(binding['path']))
    a=date(2026,1,1);out=[]
    while a.year==2026:
        if mod.direct_market_state(a,c.markets['a_share'])==mod.TradingDayState.FULL_TRADING_DAY:out.append(a.strftime('%Y%m%d'))
        a+=timedelta(days=1)
    return out

def build_outputs():
    target=pd.read_csv(ROOT/'analysis/TARGET_STOCK_DAYS.csv',dtype={'D':str,'O':str});fields=pd.read_parquet(ROOT/'analysis/MONTH_MATERIALIZED_FIELDS.parquet');fields.trade_date=fields.trade_date.astype(str)
    evobs=pd.read_csv(ROOT/'analysis/EVENT_OBSERVATIONS.csv',dtype={'D':str});events=pd.read_csv(ROOT/'analysis/EVENTS.csv');top=pd.read_csv(ROOT/'analysis/TOP200_SEED.csv',dtype={'D':str,'O':str});cand=pd.read_csv(ROOT/'analysis/CANDIDATE_UNION_SEED.csv',dtype={'D':str,'O':str});ctrl=pd.read_csv(ROOT/'analysis/CONTROL_SEED.csv',dtype={'D':str,'O':str});market=pd.read_csv(ROOT/'analysis/MARKET_STATE.csv',dtype={'D':str})
    fs=fields.rename(columns={'ts_code':'symbol','trade_date':'D'});assert not fs.duplicated(['symbol','D']).any()
    f=target.merge(fs,on=['symbol','D'],how='left',validate='many_to_one').merge(evobs,on=['symbol','D'],how='left',validate='one_to_one').merge(market,on='D',how='left',validate='many_to_one')
    cls={x['symbol']:x for x in read(CLASS)['classifications']};f['industry']=f.symbol.map(lambda s:(cls.get(s,{}).get('official_industry') or {}).get('major_name','UNKNOWN') or 'UNKNOWN');f['industry_reference_date']='20261028_NONPIT';f['direction_white_yellow']=f.apply(direction,axis=1);f['source_state']=np.where(f.close.notna(),'QUALIFIED_EXACT_D','SOURCE_OR_EXACT_D_GAP');f['current_event_state']=f.current_event_state.fillna('SOURCE_OR_EXACT_D_GAP');f['historical_PIT']=False;f['price_basis']='QFQ_ASOF_D11_NONPIT';f['full_method_or_human_label']='NOT_ASSIGNED'
    # Past-only stock history strata: existing observed origins strictly before D.
    byevents={s:g for s,g in events.groupby('symbol')};histcounts=[]
    for x in f[['symbol','D']].itertuples():
        eg=byevents.get(x.symbol);n=int((eg.origin_date<int(x.D)).sum()) if eg is not None else None;histcounts.append(n)
    f['prior_proxy_origin_count']=histcounts;f['stock_history_stratum']=f.prior_proxy_origin_count.map(lambda n:'UNKNOWN' if pd.isna(n) else 'ONE_OR_FEWER_OBSERVED_ORIGINS' if n<=1 else 'MULTIPLE_OBSERVED_PROXY_ORIGINS_NOT_STABLE_HABIT')
    f['structure_state_D']=np.select([f.current_event_state.eq('SOURCE_OR_EXACT_D_GAP'),f.current_event_state.eq('CURRENT_EVENT_UNKNOWN'),f.current_event_state.eq('ALL_PROXY_ORIGINS_INVALIDATED'),f.origin_retest_proxy.eq('TRUE')|f.attack_retest_proxy.eq('TRUE')],['UNKNOWN_SOURCE','CURRENT_EVENT_UNKNOWN','INVALIDATED_ORIGIN_HISTORY','PULLBACK_PROXY_SATISFIED'],default='WAIT_OR_OTHER_STRUCTURE')
    f['feature_cutoff_D']=f.D;csvout('FEATURES_ASOF_D.csv',f)
    sessions=trading_sessions();loc={s:i for i,s in enumerate(sessions)};prices={(s,d):r for s,d,r in [(x.ts_code,str(x.trade_date),x) for x in fields.itertuples()]};out=[]
    for x in target.itertuples():
        base=prices.get((x.symbol,x.D));row=dict(O=x.O,D=x.D,symbol=x.symbol,outcome_asof='20261111',price_basis='QFQ_ASOF_D11_NONPIT',outcome_interpretation='DESCRIPTIVE_PATH_NOT_EXECUTABLE_PNL',success_label='NOT_ASSIGNED')
        for h in [1,3,5,10]:
            ds=sessions[loc[x.D]+1:loc[x.D]+h+1];targetdate=ds[-1] if len(ds)==h else None;row[f'future_{h}s_target_date']=targetdate;row[f'future_{h}s_available_sessions']=sum(d<='20261111' for d in ds);row[f'future_{h}s_close_change']=None;row[f'future_{h}s_MFE']=None;row[f'future_{h}s_MAE']=None
            if targetdate is None or targetdate>'20261111':status='PENDING_RIGHT_CENSORED'
            elif base is None or not np.isfinite(base.close) or base.close<=0:status='UNKNOWN_BASE_PRICE'
            else:
                rr=[prices.get((x.symbol,d)) for d in ds]
                if any(z is None or not all(np.isfinite(v) and v>0 for v in [z.close,z.high,z.low]) for z in rr):status='UNKNOWN_MISSING_EXACT_SESSION'
                else:status='OBSERVED';row[f'future_{h}s_close_change']=rr[-1].close/base.close-1;row[f'future_{h}s_MFE']=max(z.high for z in rr)/base.close-1;row[f'future_{h}s_MAE']=min(z.low for z in rr)/base.close-1
            row[f'future_{h}s_status']=status
        status=row['future_5s_status'];r=row['future_5s_close_change'];row['future_descriptive_5s_path']='PENDING' if status.startswith('PENDING') else 'UNKNOWN' if status!='OBSERVED' else 'CLOSE_HIGHER' if r>0 else 'CLOSE_LOWER' if r<0 else 'CLOSE_FLAT';out.append(row)
    outcomes=csvout('OUTCOMES_AFTER_D.csv',out);base=f.merge(outcomes,on=['O','D','symbol'],suffixes=('','_outcome'),validate='one_to_one')
    topout=top.merge(base,on=['O','D','symbol'],how='left',validate='one_to_one');csvout('TOP200_STOCK_DAYS.csv',topout)
    candid=cand.merge(base,on=['O','D','symbol'],how='left',validate='one_to_one');topkeys={(x.O,x.symbol) for x in top.itertuples()};candid['future_in_O_Top200']=[(x.O,x.symbol) in topkeys for x in candid.itertuples()];csvout('ALL_CANDIDATE_PATHS.csv',candid)
    controls=ctrl.merge(base,on=['O','D','symbol'],how='left',validate='one_to_one');controls['control_status_D']=controls.structure_state_D;csvout('SIMILAR_STRUCTURE_CONTROLS.csv',controls)
    gaps=[]
    for x in base.itertuples():
        if x.source_state!='QUALIFIED_EXACT_D':gaps.append(dict(O=x.O,D=x.D,symbol=x.symbol,gap='QUALIFIED_EXACT_D_PANEL_ROW_UNAVAILABLE',detail='NO_IMPUTATION_NOT_NEGATIVE'))
        if x.current_event_state=='CURRENT_EVENT_UNKNOWN':gaps.append(dict(O=x.O,D=x.D,symbol=x.symbol,gap='CURRENT_EVENT_UNKNOWN',detail=f'live_origins={x.live_origin_count}; candidates={x.unresolved_origin_dates}'))
    for x in pd.read_csv(ROOT/'analysis/SOURCE_COVERAGE.csv',dtype=str).itertuples():
        dmem=cand[cand.D==x.D]
        if dmem.empty:gaps.append(dict(O=x.O,D=x.D,symbol='*',gap='ORIGINAL_CANDIDATE_LIST_UNAVAILABLE',detail='NO_EVIDENCE_NO_NEGATIVE_ASSUMPTION'))
        if x.top200_identity!='PUBLISHED_TOP200':gaps.append(dict(O=x.O,D=x.D,symbol='*',gap='TOP200_ORIGINAL_PUBLICATION_NOT_LOCATED',detail='FIXED_CURRENT_DIRECTORY_RECONSTRUCTION_NONPIT'))
        if x.D not in read(P/'index.json')['dates']:gaps.append(dict(O=x.O,D=x.D,symbol='*',gap='DAILY_FOUR_FORMULA_PRODUCT_UNAVAILABLE',detail='OTHER_AVAILABLE_ARCHIVES_RETAINED; TOTAL_HISTORICAL_UNIVERSE_CANNOT_CONFIRM'))
    csvout('GAPS.csv',gaps)
    # Event summary: stable immutable origins are not counted as confirmed independent opportunities.
    resolved=base[base.current_event_id.notna()].groupby('current_event_id',as_index=False).agg(first_observed_D=('D','min'),last_observed_D=('D','max'),observation_stock_days=('D','size'),distinct_D=('D','nunique'))
    eres=events.merge(resolved,left_on='event_id',right_on='current_event_id',how='left',validate='one_to_one');csvout('EVENTS.csv',eres)
    failure=[]
    for cohort,data in [('TOP200',topout),('ORIGINAL_CANDIDATE',candid),('SIMILAR_CONTROL',controls)]:
        for x in data.itertuples():
            failure.append(dict(O=x.O,D=x.D,symbol=x.symbol,cohort=cohort,structural_state_D=x.structure_state_D,omission_state=('HIT_AVAILABLE_ARCHIVED_CANDIDATE' if (x.O,x.D,x.symbol) in set(map(tuple,cand[['O','D','symbol']].values)) else 'NOT_IN_AVAILABLE_ARCHIVES_COVERAGE_PARTIAL') if cohort=='TOP200' else 'NOT_APPLICABLE',future_5s_path=x.future_descriptive_5s_path,current_event_id=x.current_event_id,truth_label='UNKNOWN_NOT_SYNTHESIZED'))
    csvout('FAILURES_AND_OMISSIONS.csv',failure)
    summary=[]
    for r in pd.read_csv(ROOT/'coordination/OBSERVATION_CALENDAR.csv',dtype=str).to_dict('records'):
        O,D=r['observation_date_O'],r['judgement_date_D'];tt=topout[topout.O==O];cc=candid[candid.O==O];ct=controls[controls.O==O]
        summary.append(dict(O=O,D=D,top200_stock_days=len(tt),top200_unique_stocks=tt.symbol.nunique(),top200_identity=tt.top200_identity.iloc[0],candidate_stock_days=len(cc),candidate_unique_stocks=cc.symbol.nunique(),candidate_source_memberships=int((pd.read_csv(ROOT/'analysis/CANDIDATE_MEMBERSHIPS.csv',dtype={'O':str}).O==O).sum()),candidate_top200_overlap=int(cc.future_in_O_Top200.sum()),candidate_total_original_coverage='CANNOT_CONFIRM_INCOMPLETE_POOL_HISTORY',controls=len(ct),top200_exactD_gaps=int((tt.source_state!='QUALIFIED_EXACT_D').sum()),top200_current_event_unknown=int((tt.current_event_state=='CURRENT_EVENT_UNKNOWN').sum()),top200_resolved_proxy_event_ids=tt.current_event_id.nunique(),top200_5s_observed=int((tt.future_5s_status=='OBSERVED').sum()),candidate_5s_observed=int((cc.future_5s_status=='OBSERVED').sum()),candidate_5s_pending=int(cc.future_5s_status.str.startswith('PENDING').sum()),candidate_5s_mean_descriptive_change=cc.future_5s_close_change.mean(),original_list_availability_before_O='CANNOT_CONFIRM'))
    csvout('MONTHLY_DAILY_SUMMARY.csv',summary)
    strata=[]
    for cohort,data in [('TOP200',topout),('ORIGINAL_CANDIDATE',candid),('SIMILAR_CONTROL',controls)]:
        for axis in ['market_state','industry','stock_history_stratum','structure_state_D','direction_white_yellow']:
            for key,g in data.groupby(axis,dropna=False):strata.append(dict(cohort=cohort,axis=axis,stratum=key,stock_days=len(g),unique_stocks=g.symbol.nunique(),resolved_proxy_event_ids=g.current_event_id.nunique(),outcome_5s_observed=g.future_5s_close_change.notna().sum(),outcome_5s_mean=g.future_5s_close_change.mean(),outcome_5s_median=g.future_5s_close_change.median(),outcome_5s_pending=g.future_5s_status.str.startswith('PENDING').sum(),scope='DESCRIPTIVE_DEPENDENT_STOCK_DAYS_NO_CAUSAL_OR_STABILITY_CLAIM'))
    csvout('STRATA.csv',strata)
    metrics={'top200_stock_days':len(topout),'top200_unique_stocks':topout.symbol.nunique(),'candidate_stock_days':len(candid),'candidate_unique_stocks':candid.symbol.nunique(),'control_stock_days':len(controls),'control_unique_stocks':controls.symbol.nunique(),'total_target_stock_days':len(base),'origin_proxy_records':len(events),'resolved_current_proxy_event_ids':base.current_event_id.nunique(),'resolved_current_proxy_stock_days':int(base.current_event_id.notna().sum()),'unresolved_current_event_stock_days':int((base.current_event_state=='CURRENT_EVENT_UNKNOWN').sum()),'source_gap_stock_days':int((base.source_state!='QUALIFIED_EXACT_D').sum()),'true_independent_opportunity_count':'CANNOT_CONFIRM_ENGINEERING_ORIGINS_NOT_HUMAN_LABELS','new_fit':0}
    save('MONTHLY_METRICS.json',metrics);print('OUTPUTS',metrics,flush=True)

if __name__=='__main__' and '--outputs' in sys.argv: build_outputs()

METHOD_FIELD_MAP={1:['brick_type_value','user_v1_B2'],2:['user_v1_breakout','brick_type_value'],3:['brick_type_value','brick_red_length'],4:[],5:['user_v1_single_needle_under20','brick_short','brick_long'],6:['brick_short','brick_long'],7:['close','zge_white_line','zge_yellow_line'],8:['volume','close','zge_white_line','zge_yellow_line'],9:['user_v1_break_prev_low'],10:['brick_type_value','brick_red_length'],11:['close','high','low'],12:['open','high','low','close'],13:['user_v1_B1','BBI','J','user_v1_sell_signal_daily'],14:['plry_volume_burst','volume','J'],15:['ma5','ma10','ma20','ma30','ma60'],16:['pct_chg','strong_volume_up','plry_volume_burst'],17:['macd_hist','user_v1_breakout'],18:[],19:['user_v1_B1','BBI','J','zge_white_line','zge_yellow_line'],20:['user_v1_B2'],21:['user_v1_B3'],22:['user_v1_B1','user_v1_B2','user_v1_B3','J','volume'],23:['user_v1_break_prev_low','user_v1_B1','open','close'],24:['volume','open','close'],25:['user_v1_B2','zge_white_line','zge_yellow_line'],26:['user_v1_B2','user_v1_breakout','volume'],27:['user_v1_B1','J','brick_type_value'],28:['volume','high','close'],29:['origin_retest_proxy','attack_retest_proxy','current_event_state','origin_date','management_date','volume_vs_origin','volume_vs_management'],30:['user_v1_three_quarter_yin_volume_line'],31:['user_v1_macd_above_zero_second_gold','macd_dif','macd_dea'],32:['user_v1_macd_below_zero_second_gold','macd_dif','macd_dea'],33:['brick_resonance','brick_type_value','macd_dif','macd_dea'],34:['brick_red_length','user_v1_sell_signal_daily','user_v1_break_yesterday_keyline_daily']}

def methods_and_report():
    f=pd.read_csv(ROOT/'analysis/FEATURES_ASOF_D.csv',dtype={'D':str,'O':str},low_memory=False);o=pd.read_csv(ROOT/'analysis/OUTCOMES_AFTER_D.csv',dtype={'D':str,'O':str},low_memory=False);top=pd.read_csv(ROOT/'analysis/TOP200_STOCK_DAYS.csv',dtype={'D':str,'O':str},low_memory=False);cand=pd.read_csv(ROOT/'analysis/ALL_CANDIDATE_PATHS.csv',dtype={'D':str,'O':str},low_memory=False);ctrl=pd.read_csv(ROOT/'analysis/SIMILAR_STRUCTURE_CONTROLS.csv',dtype={'D':str,'O':str},low_memory=False);events=pd.read_csv(ROOT/'analysis/EVENTS.csv',low_memory=False)
    nameframe=pd.read_csv(METHODS,usecols=['方法编号','战法或形态']).drop_duplicates();names=dict(zip(nameframe['方法编号'],nameframe['战法或形态']));save('METHOD_CONTEXT_CONFIG.json',{'name_source':str(METHODS),'name_source_sha256':sha(METHODS),'field_map':METHOD_FIELD_MAP,'judgement':'UNKNOWN_FULL_METHOD_NOT_CERTIFIED','meaning':'Raw field values and chronological event context only. Canonical, user_v1 and AI engineering proxy namespaces remain distinct. FALSE raw flag is not negative training truth.'})
    keys=set(map(tuple,top[['O','D','symbol']].values))|set(map(tuple,cand[['O','D','symbol']].values));selected=f[[tuple(x) in keys for x in f[['O','D','symbol']].values]]
    rows=[]
    for r in selected.to_dict('records'):
        for i in range(1,35):
            vals={k:(None if pd.isna(r.get(k)) else r[k]) for k in METHOD_FIELD_MAP[i]};flags={k:v for k,v in vals.items() if k.startswith('user_v1_')}
            if r['source_state']!='QUALIFIED_EXACT_D':state='SOURCE_GAP'
            elif i==18:state='UNKNOWN_OPENING_MINUTE_INPUT_NOT_READ'
            elif i==4:state='UNKNOWN_PORTFOLIO_CONTEXT_NOT_READ'
            elif any(v is None for v in vals.values()):state='PARTIAL_RAW_CONTEXT'
            elif flags:state='RAW_FLAG_PRESENT' if any(v==1 for v in flags.values()) else 'RAW_FLAG_ABSENT'
            else:state='NUMERIC_CONTEXT_ONLY'
            rows.append(dict(O=r['O'],D=r['D'],symbol=r['symbol'],method_id=i,method_name=names[i],context_state=state,raw_context_json=json.dumps(vals,ensure_ascii=False,allow_nan=False),full_method_verdict='UNKNOWN_NOT_CERTIFIED',human_label='NOT_ASSIGNED',evidence_known_at=r.get('known_at'),formula_source=r.get('formula_source'),field_contract_version=r.get('field_contract_version'),current_event_state=r['current_event_state'],context_is_not_truth=True))
    csvout('34_METHOD_CONTEXTS.csv',rows)
    first=f[f.current_event_id.notna()].sort_values(['D','symbol']).drop_duplicates('current_event_id');ep=first[['O','D','symbol','current_event_id','first_qualification_date','structure_state_D']].merge(o,on=['O','D','symbol'],validate='one_to_one');ep['event_path_reference']='FIRST_MONTHLY_RESOLVED_OBSERVATION_D_NOT_ENTRY_PNL';csvout('EVENT_LEVEL_PATHS.csv',ep)
    # Add explicit known-at dates to event facts without promoting retrospective save time.
    for k in ['first_origin_qualification','first_attack_qualification','first_any_qualification','first_pullback_recovered_attack']:
        events[k+'_known_at']=events[k].map(lambda v:f'{int(v)}T15:00:00+08:00' if pd.notna(v) else None)
    events['first_saved_at']='UNKNOWN';events['historical_PIT']=False;csvout('EVENTS.csv',events)
    examples=[]
    categories=[('候选后续收盘上行_非成功标签',cand[cand.future_5s_close_change>0]),('候选后续收盘下行_非失败真值',cand[cand.future_5s_close_change<0]),('原锚已失效的反证',cand[cand.structure_state_D=='INVALIDATED_ORIGIN_HISTORY']),('相似结构后续收盘下行',ctrl[ctrl.future_5s_close_change<0]),('未成熟等待',cand[cand.future_5s_status.str.startswith('PENDING')]),('当前多锚归属不明',top[top.current_event_state=='CURRENT_EVENT_UNKNOWN']),('同代来源或精确日缺件',top[top.source_state!='QUALIFIED_EXACT_D'])]
    for category,g in categories:
        for r in g.sort_values(['D','symbol']).drop_duplicates('symbol').head(3).to_dict('records'):
            cols=['O','D','symbol','origin_date','management_date','current_event_state','structure_state_D','first_qualification_date','volume_numerator_D','origin_volume','management_volume','volume_vs_origin','volume_vs_management','user_v1_B1','user_v1_B2','user_v1_B3','direction_white_yellow','future_5s_target_date','future_5s_status','future_5s_close_change','future_5s_MFE','future_5s_MAE','industry'];examples.append(dict(category=category,**{k:r.get(k) for k in cols},label='DESCRIPTIVE_EXAMPLE_NO_VISUAL_REVIEW_NO_TRUTH_LABEL'))
    csvout('REPRESENTATIVE_CASES.csv',examples)
    m=read(ROOT/'analysis/MONTHLY_METRICS.json');daily=pd.read_csv(ROOT/'analysis/MONTHLY_DAILY_SUMMARY.csv');gap=pd.read_csv(ROOT/'analysis/GAPS.csv');gapcounts=gap.gap.value_counts().to_dict();source_coverage=read(ROOT/'analysis/PROJECTION_RECEIPT.json')
    def pct(a,b):return round(a/b*100,2) if b else None
    sections=[]
    for label,data in [('原候选',cand),('同结构对照',ctrl),('Top200事后榜单',top)]:
        observed=data[data.future_5s_status=='OBSERVED'];sections.append(f'|{label}|{len(data)}|{data.symbol.nunique()}|{len(observed)}|{int(data.future_5s_status.str.startswith("PENDING").sum())}|{int((observed.future_5s_close_change>0).sum())}|{observed.future_5s_close_change.mean():.4%}|')
    lines=[
        '# 近一个月Top200战法与事件研究（开发集；零训练）','',
        '本批已经完成月度数据与事件研究产物。全月是 DEVELOPMENT_SET；新增 fit=0，没有打开封存测试集，没有训练模型、填补器、标准化器、校准器或融合器。研究结果不能作为盲测效果、胜率或交易授权。','',
        '## 已完成范围','',
        f'观察日O为2026-10-12至2026-11-11，共23个交易日；判断日D为前一交易日2026-10-09至2026-11-10。Top200合计{m["top200_stock_days"]:,}股票日、{m["top200_unique_stocks"]:,}只股票。7日复用已发布榜单，16日以固定2026-10-28目录、同代合格既有历史pct_chg、正成交量及价格重建，逐日保留身份，不能说成当时已经选出。排名并非全历史时点证券目录认证，存在目录幸存者及NONPIT限制。','',
        f'已找到全部来源成员{len(pd.read_csv(ROOT/"analysis/CANDIDATE_MEMBERSHIPS.csv")):,}条，按O/D/股票去重得到原候选{m["candidate_stock_days"]:,}股票日、{m["candidate_unique_stocks"]:,}只。其后续路径全部纳入；没有只保留与Top200相交部分。可找到名单不等于历史全池完整：早期四组公式产品及部分池档案缺件，历史候选总母体与first_saved_at仍CANNOT_CONFIRM。阶段恢复观察快照单列于STAGE_ARCHIVE_AUDIT，不冒充原始选出。','',
        f'同结构对照{m["control_stock_days"]:,}股票日、{m["control_unique_stocks"]:,}只。对照按D白黄线方向、收盘相对BBI、J区间、user_v1 B1/B2原值精确分层，在同O非Top200中按代码固定取每层最多3只，“同O非Top200”身份本身使用O收盘后才知道的排名，因此对照是事后分层；“未用后续涨跌”仅指没有再按1/3/5/10日路径二次挑选，不是完全事前对照。它是开发集匹配描述，不能推导总体因果或预测收益。','',
        '## 时序、原锚和事件单位','',
        'FEATURES_ASOF_D与EVENT_OBSERVATIONS只使用<=D，后续价格单列OUTCOMES_AFTER_D。历史价格与物化标签采用QFQ_ASOF_20261111，因此NONPIT；行业采用20261028参考分类，也不是历史时点行业认证。原producer、calendar、source generation及声明SHA保存在PAIR_BINDING、SOURCE_READ_IDENTITY与SOURCE_REFERENCES。','',
        f'本批共{m["origin_proxy_records"]:,}条不可变原锚代理记录。仅“一个有效原锚且它也是最新发现原锚”可绑定当前代理事件：{m["resolved_current_proxy_stock_days"]:,}股票日归到{m["resolved_current_proxy_event_ids"]:,}个稳定事件ID，重复日不会重复计作事件。{m["unresolved_current_event_stock_days"]:,}股票日保留CURRENT_EVENT_UNKNOWN；不能把任意旧锚未破当成当前轮成立。代理原锚总数、已解析ID数和真实独立交易机会是三个口径，真实机会数CANNOT_CONFIRM，不提供虚构精确上下界。','',
        '原反转K、后续攻击K和管理K分离；收盘首次破原低后资格永久终止，盘中破低收回另记，之后修复也不恢复原资格。首次资格及恢复攻击保留date/known_at，first_saved_at仍UNKNOWN。5根/3根规则是原R3.1工程代理，不是知识库正式公式，也不充当所有战法的统一门。当前轮歧义不妨碍独立保留B1/B2/B3等既有字段。','',
        '量比分子是精确D日同代复权成交量；分母明确为原锚日或当时管理K日成交量，并列相应日期。日线量比不能代替18号量比战法所需开盘分钟量比。34_METHOD_CONTEXTS逐行保留34项名称、字段namespace及原值、来源版本和缺证；full_method_verdict全为UNKNOWN_NOT_CERTIFIED。TRUE不是人工正例，FALSE不是人工负例。','',
        '## 后续路径（描述统计，不能执行的PnL）','',
        '基准为D收盘；1/3/5/10个精确交易日收盘变化，MFE为下一h个交易日最高价相对D收盘，MAE为最低价相对D收盘。任何缺日不跳过，未成熟PENDING_RIGHT_CENSORED，缺价UNKNOWN，均不补0。末日11/10的1日结果可以成熟，3/5/10日仍未成熟。未建success标签。','',
        '|队列|股票日|股票数|5日成熟|5日未成熟|5日收盘较D高的股票日|5日描述性均值|','|---|---:|---:|---:|---:|---:|---:|',*sections,'',
        '这些均值含同股多日、同事件重复观察、行业与市场状态重叠，未作独立样本推断；Top200本身由O结果选择，不能与原候选均值比较来证明战法有效。EVENT_LEVEL_PATHS对可解析当前事件只保留首个本月观察D作为参考，不把多个提示累计成功。','',
        '## 分层与反例','',
        'STRATA按市场广度、行业、个股已观察历史原锚数、当前结构、白黄线方向汇总。市场状态是当日合格目录股票涨跌广度，不等于指数、资金或宏观政体；行业分布仅为构成，不称共振。历史原锚多仍不代表稳定习惯。事件稀少的6只按冻结规则向20260105扩展既有合格历史，仍保留左截断；没有重跑全市场公式。','',
        'REPRESENTATIVE_CASES列出原候选后续上行、后续下行、D时原锚已失效、同结构下行、未成熟、多锚不明及源缺口，每类最多3只，按日期/代码选例，逐例给原锚/管理K、量比分母、方向、标签原值和后续路径。本次未做人工看图；“收盘上行/下行”是事实描述，不能自动变成人工成功/失败标签。FAILURES_AND_OMISSIONS把D结构失效、缺证、未在可得历史名单与后续下行分列，缺名单不会误报真实漏选。','',
        '## 缺口','',*['- '+str(k)+'：'+str(v) for k,v in gapcounts.items()],
        '', '全月来源资格不是历史PIT首次认证。部分Top200或候选缺少合格精确D行，逐股逐日保留；没有用其他代次旧行情替换。原名单可用时点、原全池覆盖、完整方法SOP/主线/分钟执行及人工独立真标签仍CANNOT_CONFIRM。','',
        '## 最多三个待检验训练假设（本批不训练）','',
        '1. 当前轮归属可解析且未收盘破原低的回踩，是否比“任意旧锚仍有效”减少混轮？待人工逐事件标签后，以封存未来样本核验；不能直接以本批代理当标签。',
        '2. 同一D结构在不同市场广度和行业中，后续路径是否存在可重复差异？先按独立事件去重、控制行业重叠及多重比较，再设计未来验证；行业构成不能当共振。',
        '3. 原候选未进入O榜单的后续下行、等待、缺证，能否改善反例和拒绝原因的标注覆盖？先补原名单时点与人工标签，再决定是否训练；不以Top200身份生成success。','',
        '## 入口及完成边界','',
        '- MONTHLY_DAILY_SUMMARY.csv：23日覆盖、榜单身份、原候选全部去向与成熟度。',
        '- TOP200_STOCK_DAYS.csv、ALL_CANDIDATE_PATHS.csv、SIMILAR_STRUCTURE_CONTROLS.csv：逐股票日完整结果。',
        '- EVENTS.csv、EVENT_OBSERVATIONS.csv、ATTACK_MANAGEMENT_K.csv、EVENT_LEVEL_PATHS.csv：不可变原锚、当前归属及去重。',
        '- 34_METHOD_CONTEXTS.csv、STRATA.csv、FAILURES_AND_OMISSIONS.csv、REPRESENTATIVE_CASES.csv、GAPS.csv：上下文、分层、反例和缺证。','',
        'Writer产物完成不等于独立验收。最终状态由主控安排的一次只读Reviewer给出。未修改V4源码、权威数据、模型、服务或交易门禁；未提交、推送、上传、抓取新行情或发布面板。',
        '', 'RESEARCH_ONLY=true；production_allowed=false；buy_gate_updated=false；orders_sent=false。']
    (ROOT/'reports/近一个月Top200战法与事件研究.md').write_text('\n'.join(lines),encoding='utf-8')
    save('CURRENT_STATE.json',{'state':'WRITER_OUTPUTS_READY_FOR_TARGETED_CHECKS','new_fit':0,**m,'method_context_rows':len(rows)})
    print('METHODS_REPORT_DONE',len(rows),len(ep),len(examples),flush=True)

if __name__=='__main__' and '--report' in sys.argv: methods_and_report()

def finalize_facts():
    events=pd.read_csv(ROOT/'analysis/EVENTS.csv',low_memory=False);attacks=pd.read_csv(ROOT/'analysis/ATTACK_MANAGEMENT_K.csv',low_memory=False);hist=pd.read_parquet(ROOT/'analysis/HISTORY_TARGET_PROJECTION.parquet');sp=ROOT/'analysis/SPARSE_EARLIER_HISTORY.parquet'
    if sp.exists():hist=pd.concat([pd.read_parquet(sp),hist],ignore_index=True)
    have=set(zip(hist.ts_code,hist.trade_date.astype(int)))
    missing_earlier=sorted({e.symbol for e in events.itertuples() if (e.symbol,int(e.origin_date)) not in have})
    if missing_earlier:
        panel=read(ROOT/'analysis/PAIR_BINDING.json')['roles']['selector']['path']
        extra=parquet.read_table(panel,columns=FIELDS,filters=[('ts_code','in',missing_earlier),('trade_date','>=','20260105'),('trade_date','<','20260803')]).to_pandas();extra.trade_date=extra.trade_date.astype(int)
        hist=pd.concat([hist,extra],ignore_index=True).drop_duplicates(['ts_code','trade_date']).sort_values(['ts_code','trade_date'])
        hist[hist.trade_date<20260803].to_parquet(sp,index=False)
    egroup={s:g for s,g in events.groupby('symbol')};agroup={s:g for s,g in attacks.groupby('symbol')};updated=[];changed=[]
    for s,g in hist.groupby('ts_code'):
        if s not in egroup:continue
        eg=egroup[s];g=g.copy();g['vol']=g.volume;g['bbi']=g.BBI;g=g[g.trade_date<=eg.feature_asof.max()]
        fq=first_qualifications(g,eg.to_dict('records'),agroup.get(s,pd.DataFrame()).to_dict('records'))
        for e in eg.to_dict('records'):
            vals=fq[e['origin_date']]
            for k,v in vals.items():
                old=e.get(k)
                if not ((pd.isna(old) and v is None) or old==v):changed.append(dict(event_id=e['event_id'],field=k,old=old,new=v))
                e[k]=v;e[k+'_known_at']=f'{int(v)}T15:00:00+08:00' if v is not None else None
            updated.append(e)
    csvout('EVENTS.csv',updated);save('FIRST_QUALIFICATION_CONTEXT_AUDIT.json',{'fix':'Unknown later attack comparison prevents claiming attack-retest qualification until next confirmed attack. No threshold changes.','changed_event_fields':changed,'changed_count':len(changed)})
    # Update only first qualification date in stock-day tables; earlier stock state and outcomes stay unchanged.
    look={e['event_id']:e['first_any_qualification'] for e in updated}
    names=['EVENT_OBSERVATIONS.csv','FEATURES_ASOF_D.csv','TOP200_STOCK_DAYS.csv','ALL_CANDIDATE_PATHS.csv','SIMILAR_STRUCTURE_CONTROLS.csv','EVENT_LEVEL_PATHS.csv']
    for n in names:
        a=pd.read_csv(ROOT/'analysis'/n,dtype={'D':str,'O':str},low_memory=False)
        if 'current_event_id' in a:
            a['first_qualification_date']=[look.get(r.current_event_id) if look.get(r.current_event_id) is not None and look[r.current_event_id]<=int(r.D) else None for r in a.itertuples()]
        csvout(n,a)
    obs=pd.read_csv(ROOT/'analysis/EVENT_OBSERVATIONS.csv',dtype={'D':str},low_memory=False);resolved=set(obs.current_event_id.dropna());possible=set(resolved)
    for r in obs[obs.current_event_state=='CURRENT_EVENT_UNKNOWN'].itertuples():
        for d in str(r.unresolved_origin_dates).split('|'):
            if d and d!='nan':possible.add(f'{r.symbol}|UP_REVERSAL_PROXY|{int(float(d))}')
    bounds={'unit':'POTENTIAL_DISTINCT_IMMUTABLE_PROXY_ORIGIN_IDS_REPRESENTED_IN_MONTH_NOT_TRUE_TRADE_OPPORTUNITIES','resolved_proxy_ID_lower':len(resolved),'union_of_resolved_and_ambiguous_possible_ID_upper':len(possible),'ambiguous_stock_days':int((obs.current_event_state=='CURRENT_EVENT_UNKNOWN').sum()),'true_independent_opportunity_bounds':'CANNOT_CONFIRM_NO_HUMAN_EPISODE_GROUND_TRUTH','attack_management_not_independent':True};save('EVENT_IDENTITY_BOUNDS.json',bounds)
    gaps=pd.read_csv(ROOT/'analysis/GAPS.csv');sourcegaps=gaps[gaps.gap=='QUALIFIED_EXACT_D_PANEL_ROW_UNAVAILABLE'];assert len(sourcegaps)>0
    # Source coverage reflects final supplemented membership and keeps missing individual pools explicit.
    coverage=pd.read_csv(ROOT/'analysis/SOURCE_COVERAGE.csv',dtype={'O':str,'D':str});mem=pd.read_csv(ROOT/'analysis/CANDIDATE_MEMBERSHIPS.csv',dtype={'O':str,'D':str});coverage['candidate_membership_rows']=[int((mem.O==x.O).sum()) for x in coverage.itertuples()];coverage['candidate_status']=np.where(coverage.candidate_membership_rows>0,'AVAILABLE_ARCHIVED_RESULT_AVAILABILITY_UNKNOWN','CANNOT_CONFIRM');csvout('SOURCE_COVERAGE.csv',coverage)
    report=ROOT/'reports/近一个月Top200战法与事件研究.md';s=report.read_text();s=s.replace('真实机会数CANNOT_CONFIRM，不提供虚构精确上下界。',f'真实机会数CANNOT_CONFIRM。仅就本月可能涉及的不可变代理原锚ID，已解析下界为{len(resolved):,}、把歧义候选全部展开的集合上界为{len(possible):,}（EVENT_IDENTITY_BOUNDS）；这不是人工真实机会数的区间。');report.write_text(s)
    save('ERROR_AND_RECOVERY_NOTES.json',{'preserved_failures':[{'error':'ArrowInvalid magic footer','resolution':'Existing V4_LOGICAL_PANEL_V1 reader used; source unchanged'},{'error':'ImportError pq alias','resolution':'Correct existing exported parquet alias'},{'error':'String/int trade_date comparison','resolution':'Read filter matches actual string schema; integer only local engine projection'},{'error':'CSV field exceeds default limit','resolution':'Raise one-time csv parser limit; content preserved'},{'error':'Industry source official_industry null','resolution':'Keep UNKNOWN; no invented industry'},{'error':'23-session targeted check failed solely due CSV calendar columns inferred int','resolution':'Verifier normalizes dates; first failed receipt preserved'}],'not_run':['fit','training','sealed_test_access','new_market_collection','manual_chart_review','UI_API_deployment','commit_push_external_upload'],'new_fit':0})
    print('FINAL_FACTS',bounds,'qualification_changes',len(changed),flush=True)

if __name__=='__main__' and '--finalize-facts' in sys.argv: finalize_facts()
