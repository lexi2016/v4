"""Bounded display summary of every verified row, with original artifact reference.

No row selection, ranking or formal admission. Full rows remain in the immutable
three-file owner product and are validated before this presentation projection.
"""
import copy
from datetime import datetime, timezone, timedelta
from v5_shadow.digests import sha256_json


def summarize(observation):
    result=copy.deepcopy({key:value for key,value in observation.items() if key!='rows'})
    rows=observation['rows']
    result['row_summary']=None
    result['row_detail_location']='BOUND_OWNER_ARTIFACT_NOT_EMBEDDED_IN_WORKSPACE'
    if rows is None:
        return result
    fields=('close_le_prior60_high_times_0_8','current_to_previous5_ge_1_5')
    comparisons={field:{'true':0,'false':0,'unknown':0} for field in fields}
    missing=set();duplicates=set();gaps=set();incomplete=0
    for row in rows:
        incomplete+=row['numeric_input_status']!='KNOWN'
        for field in fields:
            value=row['native_comparisons'][field]
            comparisons[field]['true' if value is True else 'false' if value is False else 'unknown']+=1
        for field in ('missing_prior60_dates','missing_previous5_dates'):missing.update(row[field])
        for field in ('duplicate_prior60_dates','duplicate_previous5_dates'):duplicates.update(row[field])
        gaps.update(row['input_gaps'])
    result['row_summary']=dict(observed_rows=len(rows),numeric_input_incomplete=incomplete,
        numeric_input_complete=len(rows)-incomplete,native_comparison_counts=comparisons,
        missing_history_dates=sorted(missing),duplicate_history_dates=sorted(duplicates),
        input_gaps=sorted(gaps),all_rows_sha256=sha256_json(rows),
        coverage_basis='ALL_BOUND_PANEL_ROWS_NOT_FULL_MARKET_OR_CANDIDATE_COUNT')
    return result


def current_observation(artifact, *, target_date, market_session, plan_research_cutoff, view):
    """Server wall clock only; neither caller now nor saved-plan cutoff is as_of."""
    from v5_shadow.rebound_observation import manager_observation
    now=datetime.now(timezone.utc)
    as_of=now.isoformat()
    result=manager_observation(artifact,target_date=target_date,market_session=market_session,research_cutoff=as_of)
    result.update(observation_read_as_of=as_of,plan_research_cutoff=plan_research_cutoff,
        time_basis='SERVER_CURRENT_READ_NOT_PLAN_PIT',consumed_by_saved_plan=False)
    # Historical plans must not silently acquire a current-observation section.
    # Today's saved plan can show it, separately labelled and never saved back.
    if view=='historical' or target_date!=now.astimezone(timezone(timedelta(hours=8))).strftime('%Y%m%d'):
        result['rows']=None
        result['reason_codes']=sorted(set([*result['reason_codes'],'OBSERVATION_CURRENT_READ_HIDDEN_FOR_HISTORICAL_VIEW']))
    return result
