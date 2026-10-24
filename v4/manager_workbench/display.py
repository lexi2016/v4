"""Persisted-only bounded US selection projections, including old saved runs."""
from __future__ import annotations
from .display_read import lane_projection, lane_stock


def canonical_lane_projection(snapshot,lane_name,names,decision=None,q=None):
    lane=next((l for l in snapshot.lanes if l.lane.value==lane_name),None)
    saved=getattr(lane,'selection',None) if lane else None
    if saved is None:return lane_projection(snapshot,lane_name,names,decision,q)
    selection=saved.model_dump(mode='json')
    counts=dict(selected=selection['counts']['selected'],watch=0,unassessed=selection['counts']['pending'],
        not_selected=selection['counts']['rejected']+selection['counts']['qualified_not_selected'],observation_only=0)
    wanted={decision} if decision else {'SELECTED','CONDITIONAL_WATCH'}
    by_symbol={r.get('symbol'):i for i,r in enumerate(lane.rows) if r.get('record_role')=='CANONICAL_SELECTION'}
    stocks=[]
    for candidate in selection['candidates']:
        index=by_symbol.get(candidate['symbol'])
        if index is None:continue
        row=lane_stock(snapshot,lane,index,names)
        if row is None or row['decision'] not in wanted:continue
        if q and q.casefold() not in (row['symbol']+' '+str(row.get('name') or '')).casefold():continue
        stocks.append(row)
    return dict(stocks=stocks,counts=counts,lane_state=lane.state.value,recommendation_projection=dict(
        display_only=True,snapshot_hash_basis='ORIGINAL_SAVED_SNAPSHOT',count_unit='CANONICAL_HK_SELECTION_DECISIONS',
        candidate_stock_count=selection['counts']['candidate_count'],selection_counts=selection['counts']))


def _summary(snapshot):
    ctx=snapshot.context
    return dict(run_id=snapshot.run_id,target_date=ctx.target_date,phase=ctx.phase.value,
        product_sha256=snapshot.product_sha256,cutoff=ctx.cutoff,source_sessions=ctx.source_sessions)


def _short_ref(ref):
    return {key:ref[key] for key in ('owner','sha256','ref','reference','available_at') if key in ref}


def _brief_gate(gate):
    scalar=lambda x:x if x is None or isinstance(x,(str,int,float,bool)) else None
    return dict(gate=gate['gate'],state=gate['state'],actual=scalar(gate.get('actual')),
        threshold=scalar(gate.get('threshold')),reasons=gate.get('reasons',[])[:1])


def _legacy_mapping_summary(lane, *, offset, limit):
    """Keep saved benefit/risk visibility without the full factor diagnostic tree."""
    factor=next((r.get('us_factor_summary') for r in lane.rows if isinstance(r.get('us_factor_summary'),dict)),{})
    original=factor.get('single_day_mapping') or {}
    if not original:return None
    positive=[r for r in original.get('rows',[]) if isinstance(r,dict) and r.get('decision') in {'BENEFIT','RISK'}]
    rows=[]
    for saved in positive[offset:offset+limit]:
        row={key:saved.get(key) for key in ['symbol','name','decision','mapping_grade','primary_proxy','primary_us_symbol',
            'primary_relation_type','primary_signed_return_pct','reason','reasons','source_industry','formal_target_eligibility']}
        matches=[(i,r) for i,r in enumerate(lane.rows) if r.get('symbol')==saved.get('symbol')
            and not r.get('catalog_relation_id') and r.get('record_role')!='CATALOG_OBSERVATION']
        chosen=next(((i,r) for i,r in matches if r.get('us_symbol')==(saved.get('primary_us_symbol') or saved.get('primary_proxy'))),next(iter(matches),None))
        if chosen:row.update(row_id=f'{lane.lane.value}:{chosen[0]}',recommendation_lane=lane.lane.value)
        row['mapping_paths']=[{key:path.get(key) for key in ['grade','us_symbol','proxy_symbol','relation_type','status','reason','gaps',
            'signed_return_pct','source_sha256','source_session']} for path in saved.get('mapping_paths',[]) if isinstance(path,dict)]
        rows.append(row)
    summary={key:original.get(key) for key in ['state','rules_version','mapping_policy_version','mapping_policy_sha256','target_date','source_session',
        'price_session','monthly_observed_scope_count','formal_target_eligibility','historical_pit_verified','strict_v1_status','counts','gaps']}
    summary.update(rows=rows,benefit_rows=[r for r in rows if r['decision']=='BENEFIT'],risk_rows=[r for r in rows if r['decision']=='RISK'],
        pagination=dict(total=len(positive),offset=offset,limit=limit),display_only=True)
    return dict(groups=[],factor_summary=dict(single_day_mapping=summary),display_only=True,gaps=lane.gaps)


def selection_view(snapshot,lane_name,names,*,view,offset,limit,decision=None,q=None,
        symbol=None,relationship_offset=0,relationship_limit=50,projection="focus"):
    lane=next((l for l in snapshot.lanes if l.lane.value==lane_name),None)
    if lane is None:return None
    saved=getattr(lane,'selection',None)
    sources=dict(source_run_id=snapshot.changes.get('phase_lane_sources',{}).get(lane_name,snapshot.run_id),
        input_sha256=snapshot.changes.get('phase_lane_inputs',{}).get(lane_name,lane.input_sha256),
        source_cutoff=snapshot.changes.get('phase_lane_cutoffs',{}).get(lane_name,snapshot.context.scope_refs.get('source_cutoff',snapshot.context.cutoff)),
        source_sessions=snapshot.changes.get('phase_lane_source_sessions',{}).get(lane_name,snapshot.context.source_sessions))
    if saved is None:
        old=lane_projection(snapshot,lane_name,names,decision,q)
        records=old['stocks'] if old else []
        if symbol:records=[r for r in records if r['symbol']==symbol]
        stocks=[]
        for stock in records[offset:offset+limit]:
            brief={k:stock.get(k) for k in ['symbol','name','decision','reasons','evidence_ids','row_id','recommendation_lane','display_only']}
            if view=='diagnostics':
                relations=[{k:r.get(k) for k in ['symbol','us_symbol','relation_type','decision','reason','reasons','quote','source_sha256','source_session','available_at']}
                    for r in lane.rows if r.get('symbol')==stock['symbol']]
                brief.update(relationships=relations[relationship_offset:relationship_offset+relationship_limit],
                    relationship_pagination=dict(total=len(relations),offset=relationship_offset,limit=relationship_limit))
            stocks.append(brief)
        return dict(snapshot=_summary(snapshot),stocks=stocks,counts=old['counts'] if old else None,
            pagination=dict(total=len(records),offset=offset,limit=limit),selection_identity=None,legacy=True,lane_sources=sources,lane_state=lane.state.value,
            recommendation_counts={lane_name:old['counts'] if old else None},
            us_mapping_summary=_legacy_mapping_summary(lane,offset=offset,limit=limit) if lane_name=='US_MAPPING' else None,
            evaluation_complete=None)
    selection=saved.model_dump(mode='json') if hasattr(saved,'model_dump') else saved
    industry_listing=selection.get('listing_mode') in {'INDUSTRY_MATCH','TRIGGERED_FOCUS'}
    focus=selection.get('focus')
    focused={d['symbol']:d for d in focus['decisions']} if focus else {}
    effective_projection=projection if focus else 'catalogue'
    strict={r['symbol']:r for r in selection['strict_decisions']}
    decisions={'SELECTED':'SELECTED','NOT_SELECTED':('QUALIFIED_NOT_SELECTED','REJECTED'),'UNASSESSED':'PENDING','CONDITIONAL_WATCH':None,'OBSERVATION_ONLY':None}
    records=[]
    for candidate in selection['candidates']:
        s=candidate['symbol'];d=strict[s];f=focused.get(s)
        if symbol and symbol!=s:continue
        # The explicit diagnostics route still addresses every saved candidate.
        if view!='diagnostics':
            if focus and projection=='focus' and f['decision']!='SELECTED':continue
            if industry_listing and effective_projection=='catalogue' and not candidate.get('industry_matches'):continue
        if decision:
            wanted=({'SELECTED':'SELECTED','NOT_SELECTED':('CAPPED','NOT_TRIGGERED'),'UNASSESSED':'PENDING'}.get(decision) if focus else decisions.get(decision))
            actual=f['decision'] if focus else d['decision']
            if (isinstance(wanted,tuple) and actual not in wanted) or (not isinstance(wanted,tuple) and actual!=wanted):continue
        if q and q.casefold() not in ' '.join(str(candidate.get(k) or '') for k in ['symbol','name','research_state','direction']).casefold():continue
        records.append((candidate,d))
    if focus and projection=="focus" and view!="diagnostics":records.sort(key=lambda item:focused[item[0]["symbol"]]["rank"])
    stocks=[]
    for c,d in records[offset:offset+limit]:
        row=dict(symbol=c['symbol'],name=c.get('name') or names.get(c['symbol']),research_state=c['research_state'],direction=c['direction'],
            primary_path_id=c['primary_path_id'],strict_state=d['state'],decision=d['decision'],qualified=d['qualified'],rank=d['rank'],
            reasons=list(dict.fromkeys([*d['reasons'],*c['reasons']])),gates=[_brief_gate(g) for g in d['gates']],
            metrics=d['metrics'],path_count=len(c['paths']),source_refs=[_short_ref(r) for r in c['source_refs'][:6]],source_ref_count=len(c['source_refs']))
        if industry_listing:
            row['industry_matches']=c.get('industry_matches') or []
            # Strict facts remain available in same-run diagnostics; the default
            # listing carries their summary as reference, without a gate wall.
            if view!='diagnostics':row.update(gates=[],reasons=[])
        if focus:
            f=focused[c['symbol']]
            row.update(focus_decision=f,strict_decision=d['decision'],decision=f['decision'],rank=f['rank'],
                primary_path_id=f['primary_path_id'],primary_us_symbol=f['primary_us_symbol'],primary_theme=f['primary_theme'],
                primary_return_pct=f['primary_return_pct'],hk_mean_turnover20_hkd=f['hk_mean_turnover20_hkd'],reasons=f['reasons'])
        if view=='diagnostics':
            details=dict(c);paths=details.pop('paths')
            row.update(candidate=details,strict=d,relationships=paths[relationship_offset:relationship_offset+relationship_limit],
                relationship_pagination=dict(total=len(paths),offset=relationship_offset,limit=relationship_limit))
        stocks.append(row)
    lane_context=snapshot.changes.get('phase_lane_contexts',{}).get(lane_name)
    lane_scope=lane_context.get('scope_refs',{}) if lane_context else snapshot.context.scope_refs
    sources.update(decision_input_cutoff=selection['cutoff'],source_session=selection['source_session'],price_session=selection['price_session'],
        source_execution_cutoff=lane_scope.get('source_execution_cutoff'),processing_cutoff=lane_scope.get('processing_cutoff'))
    listing={key:selection[key] for key in ['listing_mode','listing_policy_version','listing_policy_sha256'] if key in selection}
    return dict(snapshot=_summary(snapshot),stocks=stocks,counts=selection['counts'],**listing,
        projection=effective_projection,projection_label='研究聚焦名单' if focus and projection=='focus' else '同行业候选目录（非推荐）',
        focus_counts=focus['counts'] if focus else None,focus_policy={k:focus[k] for k in ['policy_version','policy_sha256']} if focus else None,
        focus_state='PERSISTED' if focus else 'NO_SAVED_FOCUS',
        focus_context={k:focus[k] for k in ['cutoff','source_session']} if focus else None,
        pagination=dict(total=len(records),offset=offset,limit=limit),selection_identity={k:selection[k] for k in ['schema_version','policy_version','policy_sha256','engine_identity']},
        legacy=False,lane_sources=sources,lane_state=lane.state.value,
        evaluation_complete=selection.get('evaluation_complete',False),selection_gaps=selection.get('gaps',[]))
