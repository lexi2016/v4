"""Bounded display summary of every verified row, with original artifact reference.

No row selection, ranking or formal admission. Full rows remain in the immutable
three-file owner product and are validated before this presentation projection.
"""
import copy
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
