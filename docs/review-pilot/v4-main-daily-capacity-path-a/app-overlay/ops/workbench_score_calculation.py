"""Pure score projection, normalization and compatible prefix recurrence."""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import math
from pathlib import Path
import textwrap

FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
COLUMNS = ['ts_code','trade_date','open','high','low','close','volume','pre_close','pct_chg','user_v1_sell_signal_daily']


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()



def target_kb(frame, dates):
    """Evaluate the original authority only on missing output dates.

    Its full-prefix indicator cache and the only two loop-carried counters are
    retained. No predicate/expression or default is replaced. Historical KB
    labels are neither regenerated nor overwritten. Default authority remains
    byte-identical to the accepted R5 source.
    """
    from ops import kb_signal_authority as kb
    tree = ast.parse(textwrap.dedent(inspect.getsource(kb.append_kb_signals)))
    fn = tree.body[0]
    loop = next(n for n in fn.body if isinstance(n, ast.For) and ast.unparse(n.target) == '(i, day)')
    # Before the original per-row body: advance exactly its two state updates
    # for skipped output rows. Indicator recurrence is in the original _cache.
    skip = ast.parse('''
if int(day.trade_date) not in _requested_output_dates:
    if close_prefix and n >= 114 and cache['white'][i] > 0 and cache['yellow'][i] > 0:
        valid_line_indices.append(i)
    if n >= 9:
        color = 1 if cache['brick'][i] >= cache['brick'][i-1] else -1
        color_count = color_count + 1 if color == prev_color else 1
        prev_color = color
    for name in names:
        outputs[name].append(None)
    continue
''').body[0]
    # close_prefix and n are assigned before the first conditional.
    index = next(i for i, n in enumerate(loop.body) if isinstance(n, ast.If))
    loop.body.insert(index, skip)
    env = dict(kb.__dict__, _requested_output_dates=set(dates))
    exec(compile(ast.fix_missing_locations(tree), str(Path(kb.__file__)), 'exec'), env)
    return env['append_kb_signals'](frame)


def score_prefix(rows, previous=None):
    """Resume the exact preserved score recurrence, saving only its state."""
    from ops import kb_hold_score as owner
    from types import FunctionType
    tree=ast.parse(textwrap.dedent(inspect.getsource(owner.score_history)))
    fn=tree.body[0]
    # Keep all original rule expressions; supply the validated prefix state.
    loop=next(node for node in fn.body if isinstance(node,ast.For))
    original_init=fn.body[:fn.body.index(loop)]
    init=ast.parse("""
result=[]
closes=list(saved.get('closes', []));highs=list(saved.get('highs', []));lows=list(saved.get('lows', []))
previous_date=saved.get('previous_date', 0)
k=saved.get('k', 50.0);d=saved.get('d', 50.0)
kdj_prefix_valid=saved.get('kdj_prefix_valid', True)
prefix_count=saved.get('count', 0);retained_count=len(closes)
""").body
    fn.body=init+fn.body[fn.body.index(loop):]
    for node in ast.walk(loop):
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id=='n':
            node.value=ast.parse('prefix_count + len(closes) - retained_count',mode='eval').body
    final=fn.body[-1]
    assert isinstance(final,ast.Return)
    final.value=ast.parse("(result, dict(closes=closes[-24:],highs=highs[-9:],lows=lows[-9:],previous_date=previous_date,k=k,d=d,kdj_prefix_valid=kdj_prefix_valid,count=prefix_count+len(rows)))",mode='eval').body
    env=dict(owner.__dict__,saved=previous or {})
    exec(compile(ast.fix_missing_locations(tree),str(Path(owner.__file__)),'exec'),env)
    raw,state=env['score_history'](rows)
    # Run the unchanged original source-to-J validation/supplemental mapping.
    project=FunctionType(owner.project_single_history.__code__,dict(owner.__dict__,score_history=lambda _:raw),owner.project_single_history.__name__,owner.project_single_history.__defaults__)
    project.__kwdefaults__=owner.project_single_history.__kwdefaults__
    return project(rows[0]['ts_code'],rows,scope='ADMITTED_A_SHARE'),state


def plain(value):
    if hasattr(value, 'item'): value = value.item()
    if isinstance(value, float) and not math.isfinite(value): return None
    return value


def valid_writer_provenance(provenance):
    if (not isinstance(provenance, dict) or set(provenance) != {'module', 'sha256'}
            or provenance['module'] != 'materialize_workbench_score_action.py'):
        return False
    checksum = provenance['sha256']
    return (isinstance(checksum, str) and len(checksum) == 64
            and all(c in '0123456789abcdef' for c in checksum))


def normalize_score_input(symbol, rows, target, basis, rules, qualification):
    rows = [{k: plain(v) for k,v in r.items()} for r in rows]
    rows.sort(key=lambda r: int(r['trade_date']))
    prefix = digest(rows)
    # Admission is a real input even when every price byte is unchanged.
    # Bind status/reason explicitly and the complete canonical evidence object
    # (raw refs, acceptance receipts, dates and their SHAs) before cache lookup.
    qualification = qualification if isinstance(qualification, dict) else {
        'status': 'UNKNOWN', 'reason': 'QUALIFICATION_NOT_BOUND'}
    admission = dict(status=qualification.get('status'), reason=qualification.get('reason'),
                     evidence_sha256=digest(qualification))
    identity = dict(symbol=symbol, trade_date=target, price_basis=basis, rules=rules,
                    prefix_sha256=prefix, qualification=admission)
    return rows, qualification, identity


def calculate_score(symbol, rows, target, basis, rules, qualification, identity, prior_records, legacy_rules):
    from ops.kb_hold_score import apply_n_score
    from ops.kb_n_structure import project_n_history, n_prefix_sha256
    from ops.kb_action_authority import project_action
    import pandas as pd

    key = digest(identity)
    prefix = identity['prefix_sha256']
    common = dict(symbol=symbol, trade_date=target, cache_identity=identity, historical_PIT=False, **FLAGS)
    if (qualification.get('status')!='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH'
            or not rows or str(rows[-1]['trade_date']) != str(target)):
        record=dict(status='UNKNOWN', reason=qualification.get('reason') or 'EXACT_TARGET_BAR_UNAVAILABLE',
                    hold_score=None, action=None, **common)
    else:
        frame=pd.DataFrame(rows).rename(columns={'volume':'vol'})
        result=target_kb(frame, {int(target)})
        target_kb_row={k:plain(v) for k,v in result.iloc[-1].to_dict().items() if k.startswith('kb_')}
        # Preserve the original score caller's independent pinned J authority.
        from ops.kb_signal_authority import project_bound_kb_j
        js=project_bound_kb_j(symbol,rows)
        source=[dict(r,volume=r['volume'],kb_b1_j=j['kb_b1_j']) for r,j in zip(rows,js)]
        prior=None;offset=0
        for candidate in prior_records:
            ci = candidate.get('cache_identity', {})
            count = candidate.get('input_rows', 0)
            candidate_rules = ci.get('rules')
            reused_rules = ((candidate_rules == rules and valid_writer_provenance(candidate.get('writer_provenance')))
                            or (candidate.get('writer_provenance') is None
                                and any(candidate_rules == approved for approved in legacy_rules)))
            if (candidate.get('symbol') == symbol and candidate.get('status') == 'MATERIALIZED'
                    and candidate.get('historical_PIT') is False
                    and all(candidate.get(k) is v for k, v in FLAGS.items())
                    and candidate.get('recurrence') and reused_rules
                    and ci.get('symbol') == symbol and ci.get('trade_date') == candidate.get('trade_date')
                    and ci.get('price_basis') == basis
                    and type(count) is int and 0 < count < len(rows) and count > offset
                    and str(candidate.get('trade_date')) < str(target)
                    and digest(rows[:count]) == ci.get('prefix_sha256')):
                prior, offset = candidate, count
        score,score_state=score_prefix(source[offset:],prior['recurrence']['score'] if prior else None)
        nidentity=dict(generation_id='daily-score:'+key,input_sha256=prefix,
            rule_sha256=rules['a_share_kb_n_structure_v1.json'],helper_sha256=rules['kb_n_structure.py'],
            calendar_sha256=None,price_basis_sha256=digest(basis),price_basis='QFQ_ASOF')
        if prior:
            # The unchanged N owner checks the checkpoint integrity and exact
            # current HLC prefix; the new outer record binds the new source.
            old=prior['recurrence']['n']
            nidentity=dict(old['identity'])
            ns,checkpoint=project_n_history(symbol,rows[offset:],identity=nidentity,
                checkpoint=old,expected_prefix_sha256=n_prefix_sha256(symbol,rows[:offset]))
        else:ns,checkpoint=project_n_history(symbol,rows,identity=nidentity)
        score=apply_n_score(symbol,source[offset:],score,ns,rule_sha256=nidentity['rule_sha256'],
                           helper_sha256=nidentity['helper_sha256'],scope='ADMITTED_A_SHARE')
        current_score=score[-1]
        # Action authority consumes the accepted KB state and independent
        # original sell signal; preserve nullable inputs without bool coercion.
        action=project_action(target_kb_row | current_score |
            {'user_v1_sell_signal_daily':rows[-1].get('user_v1_sell_signal_daily')},
            rule_sha256=rules['a_share_kb_action_v1.json'])
        record=dict(status='MATERIALIZED',hold_score=current_score,action=action,kb=target_kb_row,
                    n_structure=ns[-1]['kb_n_structure'],input_rows=len(rows),
                    recurrence=dict(score=score_state,n=checkpoint),incremental_prefix_rows=offset,new_observation_rows=len(rows)-offset,**common)
    return record
