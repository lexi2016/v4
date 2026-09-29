"""V3 consumer of the original HK02/master and original 1530 snapshot.

This is not a collector or history producer. The SAME materializer freezes its
read witness before the original quote fetch. GET checks original bytes and
never reads a newer panel to reconstruct a historical 1530 decision.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, time
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping
from infrastructure.manager_input_attestation import encoded, digest, aware, resolve, atomic_create
from domains.manager_research_evidence import admitted

RULE = '20260921_REBOUND_V3_1530_OBSERVATION_V1'
HISTORY_SCHEMA = 'v4.manager_close.rebound_history_read.v1'
PHASE = 'SNAPSHOT_1530_NOT_FINAL_CLOSE'
PREDICATES = ('amount_100m_lt_le_200m_hkd', 'oversold_le_80pct_prior60_high',
              'volume_ge_1_5_previous5_full_days', 'last_price_ge_1_03_low_so_far', 'final_close_confirmation')
FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
_SEAL = object()


def authority_root(value: Path | None = None) -> Path | None:
    """Only explicit binding; no inference from other V35 roots or cwd."""
    environment = os.environ.get('V4_CLOSE_REBOUND_AUTHORITY_ROOT')
    def selected(raw):
        path = Path(raw).expanduser()
        if not path.is_absolute():
            raise ValueError('REBOUND_HISTORY_AUTHORITY_ROOT_INVALID')
        return path.resolve()
    explicit = selected(value) if value is not None else None
    configured = selected(environment) if environment else None
    if explicit is not None and configured is not None and explicit != configured:
        raise ValueError('REBOUND_HISTORY_AUTHORITY_ROOT_CONFLICT')
    return explicit if explicit is not None else configured


def require_authority_root(value: Path | None = None) -> Path:
    root = authority_root(value)
    if root is None:
        raise ValueError('REBOUND_HISTORY_AUTHORITY_ROOT_NOT_BOUND')
    if not root.is_dir():
        raise ValueError('REBOUND_HISTORY_AUTHORITY_ROOT_INVALID')
    # These are the two EXISTING owner pointers, not new marker files. Native
    # readers still validate contents, hashes, exact date, units and availability.
    for ref in ('assets/hk_0_2/panel_latest.json', 'assets/hk_security_master/latest.json'):
        if not resolve(root, ref).is_file():
            raise ValueError('REBOUND_HISTORY_AUTHORITY_LAYOUT_MISSING')
    return root


def authority_binding(root: Path) -> dict:
    # Identity of the explicit root, not proof of source validity. Do not expose
    # the host path on the API wire. Source bytes retain their own native hashes.
    return dict(schema_version='v4.manager_close.rebound_authority_binding.v1',
                root_sha256=digest(str(require_authority_root(root)).encode()))


def _ref(date: str) -> str:
    from v4.manager_research.workspace_projection import date_token
    date_token(date)
    return f'workbench_research/{date}/inputs/1530_rebound_history.json'


def _code_sha() -> str:
    from v4.manager_research import workspace_plan
    return digest(Path(workspace_plan.__file__).read_bytes())


@dataclass(frozen=True)
class HistoryRead:
    content: bytes
    artifact_ref: str | None
    sha256: str | None
    _seal: object = field(default=None, repr=False, compare=False)


def _missing(date: str, reason: str, root: Path) -> HistoryRead:
    return HistoryRead(encoded(dict(schema_version=HISTORY_SCHEMA, trade_date=date, rule_version=RULE,
        status='CANNOT_CONFIRM', gaps=[reason], symbols={}, sessions=None, source_files=[],
        available_at=None, volume_unit=None, price_currency=None, price_basis=None,
        reader_sha256=_code_sha(), authority_binding=authority_binding(root), **FLAGS)), None, None, _SEAL)


def capture_history(state_root: Path, date: str, codes: list[str], *, root: Path | None,
                    clock: Callable[[], datetime]) -> None:
    """One immutable input witness by existing owner, before its quote request."""
    from v4.manager_research.workspace_plan import read_rebound_history
    from v4.manager_research.workspace_projection import HK
    root = require_authority_root(root)  # Never freeze an unconfigured pending witness.
    path=resolve(state_root,_ref(date))
    if path.exists(): return  # Only read_history may admit it; never overwrite.
    started=clock().astimezone(HK)
    if started.strftime('%Y%m%d')!=date or not time(15,30)<=started.time()<time(15,32):
        return
    body=read_rebound_history(authority_root(root),date,codes,now=started)
    completed=clock().astimezone(HK)
    if completed.strftime('%Y%m%d')!=date or not started<=completed or completed.time()>=time(15,32):
        return  # No retroactive witness, and caller's original window gate remains authoritative.
    body.update(schema_version=HISTORY_SCHEMA,rule_version=RULE,available_at=completed.isoformat(),
                read_started_at=started.isoformat(),reader_sha256=_code_sha(),
                authority_binding=authority_binding(root),**FLAGS)
    raw=encoded(body)
    if not atomic_create(path,raw) and path.read_bytes()!=raw:
        raise ValueError('REBOUND_HISTORY_IMMUTABLE_CONFLICT')


def _verify_history_sources(body: Mapping[str, Any], root: Path | None) -> None:
    """Repeat native master admission and arithmetic from PINNED immutable panel.

    A content hash alone cannot promote a ready history. No replacement latest
    panel is used; a changed master date entry fails closed, never silently swaps.
    """
    from v4.manager_research.workspace_plan import (rebound_history_sessions,
        rebound_history_rows,_screen_security_master_witness,rebound_native_evidence)
    root = require_authority_root(root)
    if body.get('authority_binding') != authority_binding(root):
        raise ValueError('REBOUND_HISTORY_AUTHORITY_BINDING_MISMATCH')
    refs=body.get('source_files') or []
    if not refs:
        if body.get('symbols') or body.get('status')!='CANNOT_CONFIRM':
            raise ValueError('REBOUND_HISTORY_UNATTESTED_VALUES')
        return
    if root is None or len(refs)!=4:raise ValueError('REBOUND_HISTORY_SOURCE_ROOT_OR_CLOSURE_MISSING')
    root=authority_root(root)
    for ref in refs:
        if digest(resolve(root,ref['artifact_ref']).read_bytes())!=ref['sha256']:
            raise ValueError('REBOUND_HISTORY_SOURCE_SHA_MISMATCH')
    sessions=rebound_history_sessions(body['trade_date'])
    if sessions!=body.get('sessions'):raise ValueError('REBOUND_HISTORY_CALENDAR_MISMATCH')
    panel_ref,manifest_ref=refs[1],refs[0]
    manifest=json.loads(resolve(root,manifest_ref['artifact_ref']).read_bytes())
    asset_root=root/'assets/hk_0_2'
    expected_panel=(asset_root/manifest['panel_relative']).relative_to(root).as_posix()
    if (manifest.get('asset_schema_version')!='v3_shared_data.hk_0_2_panel_asset.v2'
        or manifest.get('source_contract')!='tdx_vipdoc_71_day+verified_zero_trade_repairs'
        or manifest.get('panel_max_date')!=sessions['panel_session']
        or expected_panel!=panel_ref['artifact_ref'] or manifest.get('panel_sha256')!=panel_ref['sha256']
        or manifest.get('research_only') is not True
        or any(manifest.get(k) is not False for k in ('production_allowed','buy_gate_updated','orders_sent'))):
        raise ValueError('REBOUND_HISTORY_PANEL_AUTHORITY_INVALID')
    master,_=_screen_security_master_witness(root,body['trade_date'])
    if (master['manifest_sha256']!=refs[2]['sha256'] or master['artifact_sha256']!=refs[3]['sha256']
        or aware(master['captured_at'])>aware(body['available_at'])):
        raise ValueError('REBOUND_HISTORY_MASTER_CHANGED_OR_LATE')
    audit = rebound_native_evidence(manifest, required_session=sessions['panel_session'],
        observed_at=aware(body['read_started_at']), master_captured_at=master.get('captured_at'))
    if any(body.get(key) != audit[key] for key in audit):
        raise ValueError('REBOUND_HISTORY_NATIVE_EVIDENCE_MISMATCH')
    import pandas as pd
    frame=pd.read_parquet(resolve(root,panel_ref['artifact_ref']),columns=['trade_date_compact','code_norm','high','trade'])
    if str(frame['trade_date_compact'].astype(str).max())!=sessions['panel_session']:
        raise ValueError('REBOUND_HISTORY_PANEL_DATE_CONTENT_MISMATCH')
    values=rebound_history_rows(frame,list(body['symbols']),sessions)
    for symbol,value in values.items():
        if symbol not in master['names']:value['gaps'].append('REBOUND_EXACT_SECURITY_MASTER_MISSING')
    if values!=body['symbols']:raise ValueError('REBOUND_HISTORY_DERIVATION_MISMATCH')
    for ref in refs:
        if digest(resolve(root,ref['artifact_ref']).read_bytes())!=ref['sha256']:
            raise ValueError('REBOUND_HISTORY_SOURCE_CHANGED_DURING_READBACK')


def read_history(state_root: Path, date: str, *, as_of: datetime, root: Path | None) -> HistoryRead:
    root = require_authority_root(root)
    path=resolve(state_root,_ref(date))
    if not path.is_file():return _missing(date,'REBOUND_PRECAPTURE_HISTORY_WITNESS_MISSING',root)
    raw=path.read_bytes();body=json.loads(raw)
    if (encoded(body)!=raw or body.get('schema_version')!=HISTORY_SCHEMA
        or body.get('rule_version')!=RULE or body.get('trade_date')!=date
        or body.get('reader_sha256')!=_code_sha()
        or any(body.get(k) is not v for k,v in FLAGS.items())):
        raise ValueError('REBOUND_HISTORY_IDENTITY_INVALID')
    from v4.manager_research.workspace_projection import HK
    start,finish=aware(body.get('read_started_at')),aware(body.get('available_at'))
    if (start.strftime('%Y%m%d')!=date or finish.strftime('%Y%m%d')!=date
        or not time(15,30)<=start.time()<time(15,32) or finish.time()>=time(15,32)
        or not start<=finish<=as_of.astimezone(HK)):
        raise ValueError('REBOUND_HISTORY_AFTER_SNAPSHOT_OR_OUTSIDE_WINDOW')
    _verify_history_sources(body,authority_root(root))
    return HistoryRead(raw,_ref(date),digest(raw),_SEAL)


def rebound_decision(raw: Mapping[str, Any], history: Mapping[str, Any], meta: Mapping[str, Any]) -> dict:
    """Pure projection; only build_payload with native sealed inputs can admit it."""
    from v4.manager_research.workspace_plan import _screen_number, rebound_v3_metrics
    price=_screen_number(raw.get('last_price'),positive=True)
    low=_screen_number(raw.get('low_price'),positive=True)
    high=_screen_number(raw.get('high_price'),positive=True)
    gaps=list(history.get('gaps') or [])+list(meta.get('gaps') or [])
    amount=_screen_number(raw.get('turnover'));volume=_screen_number(raw.get('volume'))
    currency=raw.get('turnover_currency') or raw.get('currency')
    unit=raw.get('turnover_unit') or raw.get('unit')
    aliases=all(not raw.get(a) or not raw.get(b) or raw[a]==raw[b]
                for a,b in (('turnover_currency','currency'),('turnover_unit','unit')))
    hkd=aliases and currency=='HKD' and unit=='HKD'
    if not hkd:gaps.append('REBOUND_SNAPSHOT_TURNOVER_UNIT_UNVERIFIED')
    comparable=(meta.get('volume_unit')=='SHARES' and raw.get('volume_unit')=='SHARES')
    if not comparable:gaps.append('REBOUND_CROSS_OWNER_VOLUME_UNIT_UNVERIFIED')
    price_ok=(meta.get('price_currency')=='HKD' and meta.get('price_basis')=='RAW'
              and raw.get('currency')=='HKD')
    if not price_ok:gaps.append('REBOUND_PRICE_CURRENCY_OR_RAW_BASIS_UNVERIFIED')
    if price is None or low is None or low>price or (high is not None and (high<low or price>high)):
        gaps.append('REBOUND_SNAPSHOT_LAST_LOW_HIGH_INVALID');low=None
    if meta.get('status') not in {'READY','PARTIAL'} or 'REBOUND_EXACT_SECURITY_MASTER_MISSING' in gaps:
        history={};price_ok=False
    metric=rebound_v3_metrics(price=price,low=low,amount=amount if hkd else None,
        volume=volume if comparable else None,previous5_mean=history.get('previous5_mean'),
        prior60_high=history.get('prior60_high') if price_ok else None)
    gates=metric['gates']
    if gates['amount'] is False or gates['oversold'] is False:kind='EXCLUDED'
    elif 'unknown' in gates.values():kind='PENDING_EVIDENCE'
    elif metric['strict']:kind='STRICT_ASOF_OBSERVATION'
    elif metric['near']:kind='NEAR_ASOF_OBSERVATION'
    else:kind='EXCLUDED'
    return dict(rule_version=RULE,approved_rule_version='20260921_REBOUND_V3',phase=PHASE,
        classification=kind,last_price=price,low_so_far=low,final_close=None,
        close_confirmation='unknown',metrics=metric,gaps=sorted(set(gaps)))


def _decorate(candidate: dict, raw: Mapping[str, Any], history: Mapping[str, Any], meta: Mapping[str, Any],
              history_ref: str | None, history_sha: str | None) -> dict:
    decision=rebound_decision(raw,history,meta);metric=decision['metrics'];gate=metric['gates']
    descriptions=[
        '截至快照累计成交额>1亿且≤2亿HKD；不是最终全天金额',
        '当时价≤此前60个HK交易日原始最高价的80%；不是最终收盘超跌确认',
        '累计量÷此前5个完整HK交易日成交量均值≥1.5；不使用供应商volume_ratio',
        '当时价÷截至快照最低价−1≥3%；不是close字段',
        '同日最终收盘价/全天量额/全天低点尚未发生；必须另由原完整日线reader确认']
    candidate['predicates']=[dict(predicate_id=k,value=v,reason=reason,
        input_refs=[history_ref] if history_ref else [],rule_version=RULE)
        for k,v,reason in zip(PREDICATES,[gate['amount'],gate['oversold'],gate['volume'],gate['rebound'],'unknown'],descriptions)]
    candidate['qualified']=False if any(v is False for v in gate.values()) else None
    candidate['data_status']=decision['classification']
    labels={'STRICT_ASOF_OBSERVATION':'15:30四项数值满足，仍待收盘确认',
            'NEAR_ASOF_OBSERVATION':'15:30近条件观察，非严格合格',
            'PENDING_EVIDENCE':'15:30反弹依据待核，不计近条件','EXCLUDED':'反弹硬条件未满足'}
    candidate['attention_reason']=labels[decision['classification']]
    candidate['research_priority'].update(level=decision['classification'],rule_version=RULE,
        change_reason=candidate['attention_reason'],formal_rank_changed=False,buy_gate_changed=False)
    ratio=metric['volume_ratio_5d'] if gate['volume']!='unknown' else None
    candidate['volume_comparison']=dict(state='CUMULATIVE_VS_PREVIOUS5_FULL_DAYS' if ratio is not None else 'unknown',
        ratio=ratio,baseline_as_of=meta.get('available_at') if ratio is not None else None,
        baseline_period=(meta.get('sessions') or {}).get('previous5'),rule_version=RULE,
        source_ref=history_ref,previous5_mean_volume=history.get('previous5_mean'),
        raw_provider_ratio=raw.get('volume_ratio') if isinstance(raw.get('volume_ratio'),(int,float)) else None,
        reason=descriptions[2])
    candidate['position'].update(rebound_v3=decision,historical_rule_version=RULE,
        historical_source_ref=history_ref,historical_baseline_as_of=meta.get('available_at'),
        historical_position_state='KNOWN' if gate['oversold']!='unknown' else 'UNKNOWN',
        prior60_high=history.get('prior60_high'),reason=descriptions[1])
    if history_ref:
        candidate['sources'].append(dict(owner='ops.materialize_manager_close_discovery',
            role='EXISTING_HK02_PRECAPTURE_READ',artifact_ref=history_ref,receipt_ref=None,manifest_ref=None,
            run_id='history-'+str(history_sha)[:24],sha256=history_sha,
            source_date=(meta.get('sessions') or {}).get('panel_session') or candidate['trade_date'],
            market='HK_CONNECT',lane='CLOSE_DISCOVERY',reason='原HK02/证券主表只读证据；快照前真实取得',
            observed_at=meta.get('available_at'),available_at=meta.get('available_at')))
    candidate['observation_plan']=dict(triggers=[candidate['attention_reason'],*descriptions[:4]],
        invalidation_conditions=['资格、原件校验或时点失效即撤下观察；不产生真实订单',
            '收盘累计金额可能超过2亿；当前满足不保证收盘满足，必须按原完整日线另行复核'],
        missing_evidence=[*decision['gaps'],descriptions[4]],phase=PHASE,final_close=None)
    return candidate


def focus_symbols(candidates: list[dict]) -> list[str]:
    """Preserve V3 near-fill display policy, never invent missing candidates."""
    strict=sorted(c['symbol'] for c in candidates if c['data_status']=='STRICT_ASOF_OBSERVATION')
    near=sorted((c for c in candidates if c['data_status']=='NEAR_ASOF_OBSERVATION'),
        key=lambda c:(-(c['position']['rebound_v3']['metrics']['near_failed_ratio'] or 0),c['symbol']))
    return strict+[c['symbol'] for c in near[:max(0,10-len(strict))]]


def build_payload(*, state_root: Path, history_evidence: HistoryRead, **kwargs: Any) -> dict:
    from domains.manager_close_discovery import build_workbench_payload
    if (not isinstance(history_evidence,HistoryRead) or history_evidence._seal is not _SEAL
        or not admitted(kwargs.get('universe_evidence'),kwargs.get('snapshot_evidence'),kwargs['snapshot_rows'])):
        raise ValueError('REBOUND_CURRENT_INPUT_NOT_NATIVE_ADMITTED')
    meta=json.loads(history_evidence.content)
    if meta.get('trade_date')!=kwargs['trade_date']:raise ValueError('REBOUND_HISTORY_WRONG_DATE')
    legacy=build_workbench_payload(**kwargs)
    rows={r['code']:r for r in kwargs['snapshot_rows'] if isinstance(r,Mapping)}
    candidates=[];decisions=[]
    for c in legacy['candidates']:
        history=meta['symbols'].get(c['symbol'],{})
        decorated=_decorate(c,rows[c['symbol']],history,meta,history_evidence.artifact_ref,history_evidence.sha256)
        decisions.append(dict(symbol=c['symbol'],**decorated['position']['rebound_v3']))
        if decorated['data_status']!='EXCLUDED':candidates.append(decorated)
    order={'STRICT_ASOF_OBSERVATION':0,'NEAR_ASOF_OBSERVATION':1,'PENDING_EVIDENCE':2}
    candidates.sort(key=lambda c:(order[c['data_status']],
        -(c['position']['rebound_v3']['metrics']['near_failed_ratio'] or 0),c['symbol']))
    from domains.manager_condition_evidence import _snapshot_binding
    binding=_snapshot_binding(state_root,kwargs['snapshot_evidence'])
    summary={key:[c['symbol'] for c in candidates if c['data_status']==kind] for key,kind in
             [('strict_observation','STRICT_ASOF_OBSERVATION'),('near_observation','NEAR_ASOF_OBSERVATION'),('pending','PENDING_EVIDENCE')]}
    legacy.update(rule_version=RULE,cache_key=f"{kwargs['trade_date']}|HK_CONNECT|1530|{RULE}",
        run_id='rv3-'+digest(encoded(dict(base_run=legacy['run_id'],history=history_evidence.sha256,rule=RULE)))[:24],
        status='PARTIAL',candidates=candidates,
        cannot_confirm=sorted(set([*meta.get('gaps',[]),'FINAL_CLOSE_CONFIRMATION_NOT_YET_AVAILABLE',
            *(['QUOTE_COVERAGE_INCOMPLETE'] if legacy['coverage']['missing_count'] else [])])))
    focus=focus_symbols(candidates)
    legacy['priority_summary']['focus']=[dict(item_id='focus-'+c['candidate_id'],candidate_id=c['candidate_id'],name=c['name'],
        occurred_at=c['observed_at'],reason=c['attention_reason'],evidence_status=c['data_status'],kind=c['data_status'])
        for c in candidates if c['symbol'] in focus]
    legacy['rebound_screen']=dict(rule_version=RULE,phase=PHASE,final_close=None,confirmed_strict_count=0,
        history_ref=history_evidence.artifact_ref,history_sha256=history_evidence.sha256,
        authority_binding=meta['authority_binding'],snapshot_binding=binding,source_rows=decisions,focus_symbols=focus,**summary)
    return legacy


def validate_projection(value: Mapping[str,Any], *, state_root: Path | None,
                        verify_sources: bool, root: Path | None = None) -> dict:
    """Validate V3 phase/decisions; on GET re-read native snapshot and original history."""
    from v4.manager_research.workspace_projection import HK
    screen=value.get('rebound_screen')
    if not isinstance(screen,dict) or screen.get('rule_version')!=RULE or screen.get('phase')!=PHASE:
        raise ValueError('REBOUND_SCREEN_IDENTITY_INVALID')
    if screen.get('final_close') is not None or screen.get('confirmed_strict_count')!=0:
        raise ValueError('REBOUND_1530_IS_NOT_FINAL_CLOSE')
    at=aware(value['as_of']);date=value['trade_date']
    if at.strftime('%Y%m%d')!=date or not time(15,30)<=at.time()<time(15,32):
        raise ValueError('REBOUND_SNAPSHOT_TIME_INVALID')
    actual_rows=None;hist=None
    if verify_sources:
        root = require_authority_root(root)
        if screen.get('authority_binding') != authority_binding(root):
            raise ValueError('REBOUND_HISTORY_AUTHORITY_BINDING_MISMATCH')
        if state_root is None:raise ValueError('REBOUND_READBACK_ROOT_MISSING')
        from domains.manager_condition_evidence import _published_snapshot
        # Native archived snapshot binding is carried with the original envelope.
        binding=screen.get('snapshot_binding')
        if not isinstance(binding,dict):raise ValueError('REBOUND_NATIVE_SNAPSHOT_BINDING_MISSING')
        raw,_=_published_snapshot(state_root,binding,expected_date=date,as_of=at)
        from collections import Counter
        from domains.manager_close_discovery import normalize_hk_code, _quote_time, finite_number
        counts=Counter(r.get('code') for r in raw['rows'])
        # Same row-admission predicates as the original envelope. Foreign or
        # ambiguous bridge returns fail reconciliation, never manufacture rows.
        actual_rows={}
        for row in raw['rows']:
            code=normalize_hk_code(row.get('code'))
            amount=finite_number(row.get('turnover'))
            price=finite_number(row.get('last_price',row.get('price')))
            previous=finite_number(row.get('prev_close_price',row.get('last_close')))
            if (code and counts[code]==1 and _quote_time(row.get('update_time'),date,at) is not None
                and amount is not None and amount>=0 and price is not None and price>0
                and previous is not None and previous>0):
                actual_rows[code]=row
        if value.get('universe')!=raw['universe_source'] or at!=aware(raw['available_at']):
            raise ValueError('REBOUND_READBACK_SNAPSHOT_UNIVERSE_OR_TIME_MISMATCH')
        hist=read_history(state_root,date,as_of=at,root=authority_root(root))
        if hist.artifact_ref!=screen.get('history_ref') or hist.sha256!=screen.get('history_sha256'):
            raise ValueError('REBOUND_READBACK_HISTORY_BINDING_MISMATCH')
    recorded={r['symbol']:r for r in screen.get('source_rows',[])}
    if len(recorded)!=len(screen.get('source_rows',[])):raise ValueError('REBOUND_DUPLICATE_DECISION')
    if actual_rows is not None:
        meta=json.loads(hist.content)
        expected={symbol:dict(symbol=symbol,**rebound_decision(row,meta['symbols'].get(symbol,{}),meta))
                  for symbol,row in actual_rows.items()}
        if recorded!=expected or value['coverage']['covered_count']!=len(expected):
            raise ValueError('REBOUND_READBACK_DECISION_COVERAGE_MISMATCH')
        expected_visible={s for s,d in expected.items() if d['classification']!='EXCLUDED'}
        if {c['symbol'] for c in value['candidates']}!=expected_visible:
            raise ValueError('REBOUND_READBACK_VISIBLE_SET_MISMATCH')
    expected_groups={key:[] for key in ('strict_observation','near_observation','pending')}
    for c in value['candidates']:
        decision=c['position'].get('rebound_v3')
        if not isinstance(decision,dict) or {'symbol':c['symbol'],**decision}!=recorded.get(c['symbol']):
            raise ValueError('REBOUND_DECISION_CANDIDATE_MISMATCH')
        gates=decision['metrics']['gates']
        if (tuple(p['predicate_id'] for p in c['predicates'])!=PREDICATES
            or [p['value'] for p in c['predicates']]!=[gates[k] for k in ('amount','oversold','volume','rebound')]+['unknown']
            or any(p['rule_version']!=RULE for p in c['predicates'])
            or c['qualified'] is not (False if any(v is False for v in gates.values()) else None)
            or decision['final_close'] is not None or decision['phase']!=PHASE
            or c['data_status']!=decision['classification']):
            raise ValueError('REBOUND_PREDICATES_OR_PHASE_INVALID')
        strict=all(v is True for v in gates.values())
        near=(gates['amount'] is True and gates['oversold'] is True
              and all(gates[k]!='unknown' for k in ('volume','rebound'))
              and sum(gates[k] is True for k in ('volume','rebound'))==1)
        classification=('EXCLUDED' if gates['amount'] is False or gates['oversold'] is False
                        else 'PENDING_EVIDENCE' if 'unknown' in gates.values()
                        else 'STRICT_ASOF_OBSERVATION' if strict
                        else 'NEAR_ASOF_OBSERVATION' if near else 'EXCLUDED')
        if (decision['classification']!=classification or decision['metrics']['strict'] is not strict
            or decision['metrics']['near'] is not near):
            raise ValueError('REBOUND_CLASSIFICATION_CONTRADICTS_GATES')
        group={'STRICT_ASOF_OBSERVATION':'strict_observation','NEAR_ASOF_OBSERVATION':'near_observation','PENDING_EVIDENCE':'pending'}.get(c['data_status'])
        if group is None:raise ValueError('REBOUND_INVALID_VISIBLE_GROUP')
        expected_groups[group].append(c['symbol'])
        if actual_rows is not None:
            meta=json.loads(hist.content);raw=actual_rows.get(c['symbol'])
            if raw is None:raise ValueError('REBOUND_CURRENT_QUOTE_MISSING')
            derived=rebound_decision(raw,meta['symbols'].get(c['symbol'],{}),meta)
            if derived!=decision:raise ValueError('REBOUND_READBACK_DERIVATION_MISMATCH')
            from v4.manager_research.workspace_plan import _screen_number
            if c['turnover_amount']['value']!=_screen_number(raw.get('turnover')):
                raise ValueError('REBOUND_TURNOVER_RAW_MISMATCH')
            from copy import deepcopy
            expected_c=_decorate(deepcopy(c),raw,meta['symbols'].get(c['symbol'],{}),meta,hist.artifact_ref,hist.sha256)
            for key in ('predicates','volume_comparison','observation_plan','attention_reason'):
                if c.get(key)!=expected_c[key]:raise ValueError('REBOUND_READBACK_DISPLAY_FIELD_MISMATCH')
            if (c['position']['last_price']!=_screen_number(raw.get('last_price',raw.get('price')))
                or c['position']['prior60_high']!=meta['symbols'].get(c['symbol'],{}).get('prior60_high')):
                raise ValueError('REBOUND_READBACK_POSITION_MISMATCH')
            if (len(c['sources'])<2 or c['sources'][0]!={**value['universe'],'lane':'CLOSE_DISCOVERY'}
                or c['sources'][1].get('sha256')!=screen['snapshot_binding']['artifact_sha256']
                or c['sources'][1].get('artifact_ref')!=screen['snapshot_binding']['artifact_ref']):
                raise ValueError('REBOUND_READBACK_DISPLAY_SOURCE_MISMATCH')
    if any(screen.get(k)!=v for k,v in expected_groups.items()):raise ValueError('REBOUND_GROUP_RECONCILIATION_FAILED')
    expected_focus=focus_symbols(value['candidates'])
    actual_focus=[x.get('candidate_id') for x in value['priority_summary']['focus']]
    expected_ids=[c['candidate_id'] for c in value['candidates'] if c['symbol'] in expected_focus]
    if screen.get('focus_symbols')!=expected_focus or actual_focus!=expected_ids:
        raise ValueError('REBOUND_FOCUS_FILL_MISMATCH')
    return dict(screen)
