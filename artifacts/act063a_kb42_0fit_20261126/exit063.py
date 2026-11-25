"""Causal close-observation marks on the exact ACT-061A frozen wave windows."""
from __future__ import annotations

import numpy as np
import pandas as pd

from inputs063 import ACT060_CODE, ACT061_CODE, HOLD, RELAPSE, module

BASELINE = "D20_FIXED"
WHITE = "FIRST_WHITE_DOWNCROSS"
YELLOW = "FIRST_YELLOW_DOWNCROSS"
DOUBLE = "TWO_CLOSES_BELOW_BOTH"
WARNING = "FIRST_WARNING_TWO_SESSIONS_WITHOUT_REPAIR"
RULES = (BASELINE, WHITE, YELLOW, DOUBLE, WARNING)
WARN_SESSIONS = 2


def load(usage):
    usage.pin(ACT061_CODE / "exits061.py")
    # The upstream code exposes pure warning and line support functions. No main() is called.
    context = module("act063_existing_context", ACT060_CODE)
    warnings = module("act063_existing_warnings", ACT061_CODE / "exits061.py")
    return context, warnings


def and_known(values):
    return False if False in values else None if None in values else True


def or_known(values):
    return True if True in values else None if None in values else False


def evaluate_triggers(bars, end, reference):
    """Step the event path forward. Only the current and earlier slots can be used."""
    assert 0 <= end <= 20
    trigger = {}
    unknown = {name:[] for name in RULES[1:]}
    first_warning = None
    first_warning_flags = None
    missing_prior_warnings = []
    line = {}
    for i in range(0,end+1):
        # Previous day's line state is needed to define a downcross at the first step.
        if i == 0:
            for j in (-1,0):
                line[j] = tuple(reference.line_state(bars[j],p) for p in (5,6))
            continue
        line[i] = tuple(reference.line_state(bars[i],p) for p in (5,6))
        prev = line[i-1]
        now = line[i]
        crossing = tuple(None if None in (a,b) else a and not b for a,b in zip(prev,now,strict=True))
        below = and_known(tuple(None if s is None else not s for s in now))
        prior_below = and_known(tuple(None if s is None else not s for s in prev))
        candidates = {WHITE:crossing[0], YELLOW:crossing[1],
                      DOUBLE:and_known((prior_below,below)) if i >= 2 else False}
        if first_warning is None:
            flags = reference.calc_warnings(bars,i,{i: crossing})
            status = or_known(tuple(flags.values()))
            if status is True:
                first_warning = i
                first_warning_flags = "|".join(k for k,v in flags.items() if v)
                unknown[WARNING].extend(missing_prior_warnings)
            elif status is None:
                missing_prior_warnings.append(i)
        if first_warning is not None and i == first_warning + WARN_SESSIONS:
            base_close = bars[first_warning][3]
            rehabilitation = []
            for n in range(first_warning+1,i+1):
                b = bars[n]
                regains_close = None if b is None else b[3] >= base_close
                rehabilitation.append(and_known((*line[n],regains_close)))
            result = or_known(tuple(rehabilitation))
            candidates[WARNING] = None if result is None else not result
        for rule,status in candidates.items():
            if rule in trigger:
                continue
            if status is True:
                trigger[rule]=(i,tuple(unknown[rule]))
            elif status is None:
                unknown[rule].append(i)
    if first_warning is None:
        unknown[WARNING].extend(missing_prior_warnings)
    return trigger, unknown, first_warning, first_warning_flags


def mark_rows(wave, stock, context, reference):
    at = int(wave.D_ordinal)
    assert int(stock.calendar[at]) == wave.D
    anchor = stock.available_rows[at]
    bars = {i:context.clean(stock.get(at+i,anchor)[1]) for i in range(-5,21)}
    assert all(bars[i] is not None and np.isfinite(bars[i][3]) and bars[i][3]>0 for i in range(21))
    close = np.array([bars[i][3] for i in range(21)],dtype=float)
    assert np.isclose(close[0],wave.D_basis_close_verified,rtol=3e-11,atol=3e-12)
    assert np.isclose(close[20],wave.close_ret_D20_close_d_basis,rtol=3e-11,atol=3e-12)
    endpoint = (close[-1]/close[0]-1)*100
    assert np.isclose(endpoint,wave.close_ret_D20_pct,rtol=3e-11,atol=3e-12)
    dd_series = np.minimum.accumulate((close/np.maximum.accumulate(close)-1)*100)
    triggers, unknown, first_warn, flags = evaluate_triggers(bars,20,reference)
    frozen_first = None if pd.isna(wave.warning_first_offset) else int(wave.warning_first_offset)
    assert frozen_first == first_warn, wave.event_id
    identity = dict(row_type="WAVE_RULE",ts_code=wave.security_id,stock_name=wave.name,archetype=wave.archetype,
                    cohort=wave.cohort,event_id=wave.event_id,event_D=wave.D,event_group=wave.event_group,
                    baseline_D20_return_pct=endpoint,baseline_D0_D20_max_close_dd_pct=dd_series[-1])
    observed = []
    for rule in RULES:
        hit = rule in triggers
        point, unchecked = triggers.get(rule,(None,tuple(unknown.get(rule,()))))
        if hit:
            state = "TRIGGERED_EARLIEST_OBSERVED_PRIOR_UNKNOWN" if unchecked else "TRIGGERED"
            mark = point
        elif unchecked:
            state, mark = "CANNOT_CONFIRM_MISSING",None
        elif rule == BASELINE:
            state, mark = "BASELINE_FIXED_END",20
        elif rule == WARNING and first_warn is not None and first_warn+WARN_SESSIONS > 20:
            state, mark = "NOT_TRIGGERED_WARNING_WINDOW_RIGHT_EDGE",20
        else:
            state, mark = "NOT_TRIGGERED",20
        scored_now = first_warn is not None and mark is not None and first_warn <= mark
        point_return = None if mark is None else (close[mark]/close[0]-1)*100
        delta = None if mark is None else point_return-endpoint
        observed.append(identity | dict(
            rule=rule,triggered=hit,rule_status=state,trigger_offset=point,
            trigger_session=None if point is None else int(stock.calendar[at+point]),
            outcome_mark_offset=mark,
            outcome_mark_session=None if mark is None else int(stock.calendar[at+mark]),
            earlier_or_current_unknown_offsets="|".join(map(str,unchecked)),
            first_warning_observed_by_mark_offset=first_warn if scored_now else None,
            warning_trigger_tags_observed_by_mark=flags if scored_now else None,
            mark_return_vs_D0_pct=point_return,mark_minus_D20_pp=delta,
            mark_horizon_max_close_dd_pct=None if mark is None else dd_series[mark],
            mark_minus_D20_max_close_dd_pp=None if mark is None else dd_series[mark]-dd_series[-1],
            protected_relapse_vs_D20=None if delta is None else wave.cohort==RELAPSE and hit and delta>0,
            forfeited_hold_gain_vs_D20=None if delta is None else wave.cohort==HOLD and hit and delta<0,
        ))
    return observed, bars


def summary_rows(data):
    samples = {"ALL": [(None,None)],"ARCHETYPE":[(a,None) for a in "ABCD"],
               "COHORT":[(None,c) for c in (HOLD,RELAPSE)],
               "ARCHETYPE_COHORT":[(a,c) for a in "ABCD" for c in (HOLD,RELAPSE)]}
    out = []
    for group, keys in samples.items():
        for a,c in keys:
            f = data
            if a is not None:
                f = f[f.archetype.eq(a)]
            if c is not None:
                f = f[f.cohort.eq(c)]
            for rule in RULES:
                rows = f[f.rule.eq(rule)]
                hits = rows[rows.triggered]
                n = len(rows)
                known = rows[rows.outcome_mark_offset.notna()]
                relapse = rows[rows.cohort.eq(RELAPSE)]
                hold = rows[rows.cohort.eq(HOLD)]
                out.append(dict(
                    row_type="GROUP_RULE",group_scope=group,archetype=a,cohort=c,rule=rule,
                    waves_n=n,triggered_n=len(hits),trigger_coverage_lower_bound=len(hits)/n if n else None,
                    trigger_earliest_uncertain_n=int(hits.rule_status.eq("TRIGGERED_EARLIEST_OBSERVED_PRIOR_UNKNOWN").sum()),
                    unknown_outcome_n=n-len(known),effect_known_n=len(known),
                    no_trigger_n=int(rows.rule_status.str.startswith("NOT_TRIGGERED").sum()),
                    trigger_offset_median=hits.trigger_offset.median() if len(hits) else None,
                    triggered_mark_return_mean_pct=hits.mark_return_vs_D0_pct.mean() if len(hits) else None,
                    baseline_D20_return_mean_pct=rows.baseline_D20_return_pct.mean() if n else None,
                    mark_return_mean_pct=known.mark_return_vs_D0_pct.mean() if len(known) else None,
                    mark_minus_D20_mean_pp=known.mark_minus_D20_pp.mean() if len(known) else None,
                    triggered_mark_minus_D20_mean_pp=hits.mark_minus_D20_pp.mean() if len(hits) else None,
                    baseline_max_close_dd_mean_pct=rows.baseline_D0_D20_max_close_dd_pct.mean() if n else None,
                    mark_horizon_max_close_dd_mean_pct=known.mark_horizon_max_close_dd_pct.mean() if len(known) else None,
                    paired_mark_minus_D20_max_close_dd_mean_pp=known.mark_minus_D20_max_close_dd_pp.mean() if len(known) else None,
                    relapse_waves_n=len(relapse),relapse_protected_n=int(relapse.protected_relapse_vs_D20.eq(True).sum()),
                    hold_waves_n=len(hold),hold_forfeited_n=int(hold.forfeited_hold_gain_vs_D20.eq(True).sum()),
                ))
    return pd.DataFrame(out)


def check_prefix(bars, reference):
    full = evaluate_triggers(bars,20,reference)
    for cut in range(21):
        prefix = {k:v for k,v in bars.items() if k <= cut}
        physical = evaluate_triggers(prefix,cut,reference)
        expected = {rule:info for rule,info in full[0].items() if info[0] <= cut}
        assert physical[0] == expected
        assert physical[2] == (full[2] if full[2] is not None and full[2] <= cut else None)
        displaced = {k: (None if k > cut else v) for k,v in bars.items()}
        assert evaluate_triggers(displaced,cut,reference) == physical
    return 21


def build(waves, stores, deps, *, canary=False):
    context, reference = deps
    waves = waves[waves.full20].sort_values(["archetype","D","security_id"])
    chosen = set(waves.groupby("archetype").head(1).event_id)
    known_gap = waves.loc[waves.security_id.eq("688621.SH")&waves.D.eq(20250515),"event_id"]
    assert len(known_gap)==1
    checks = chosen | set(known_gap)
    if canary:
        waves = waves[waves.event_id.isin(checks)]
    rows, prefixes = [], 0
    for wave in waves.itertuples(index=False):
        result,bars = mark_rows(wave,stores[wave.security_id],context,reference)
        rows.extend(result)
        if wave.event_id in checks:
            prefixes += check_prefix(bars,reference)
    data = pd.DataFrame(rows)
    assert not data.duplicated(["event_id","rule"]).any()
    assert data.groupby("rule").size().eq(len(waves)).all()
    assert data.loc[data.rule.eq(BASELINE),"mark_minus_D20_pp"].eq(0).all()
    assert data.loc[data.rule.eq(BASELINE),"mark_minus_D20_max_close_dd_pp"].eq(0).all()
    assert data.mark_minus_D20_max_close_dd_pp.dropna().ge(0).all()
    assert data.loc[data.triggered,"outcome_mark_offset"].equals(data.loc[data.triggered,"trigger_offset"])
    assert prefixes==105
    summary = summary_rows(data)
    coverage = dict(waves=len(waves), rules=len(RULES), wave_rule_rows=len(data), group_rule_rows=len(summary),
                    prefix_perturbation_events=len(checks), prefix_tests=prefixes, prefix_event_ids=sorted(checks),
                    scope_counts={k:int(v) for k,v in waves.cohort.value_counts().items()},
                    last_warning_needs_n_followup=WARN_SESSIONS,
                    all_rule_stats=summary.loc[summary.group_scope.eq("ALL")].to_dict(orient="records"),
                    group_rule_stats=summary.loc[summary.group_scope.eq("COHORT")].to_dict(orient="records"))
    if not canary:
        assert len(waves)==562 and coverage["scope_counts"]=={HOLD:411,RELAPSE:151}
    return pd.concat([data,summary],ignore_index=True),coverage
