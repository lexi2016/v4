"""Bind the existing verified research archives to the same catalyst owner.

Not a collector. Snapshot replays use only sealed date/slot/source bindings;
new files cannot silently become historical inputs. Bad article clocks are
isolated, but a changed committed source or native identity fails readback.
"""
from __future__ import annotations
from copy import deepcopy
from typing import Any, Mapping
import re
from .existing_materials import _read_archive, MAX_ARTIFACTS
from .workspace_discovery import read_material_discovery
from .workspace_projection import date_token, timestamp
from .evidence_identity import acquisition_is_within_window

SCHEMA='v4.manager_research.archive_catalyst_inputs.v1'
_ERRORS=(ImportError,OSError,ValueError,TypeError,KeyError,RuntimeError)


def _clock_error(row,context):
    raw=row.get('source_row') if isinstance(row.get('source_row'),Mapping) else {}
    start=timestamp(context.get('focus_window_start'));cutoff=timestamp(context.get('research_cutoff'))
    published=timestamp(raw.get('published_at'))
    if start is None or cutoff is None or published is None or not start<=published<=cutoff:
        return 'ARCHIVE_PUBLICATION_OUTSIDE_FROZEN_WINDOW'
    if timestamp(raw.get('available_at')) is None or timestamp(raw.get('retrieved_at')) is None:
        return 'ARCHIVE_EXPLICIT_ACQUISITION_TIME_REQUIRED'
    if not acquisition_is_within_window(raw,start,cutoff) or not acquisition_is_within_window(row,start,cutoff):
        return 'ARCHIVE_ACQUISITION_TIME_OUTSIDE_FROZEN_WINDOW'
    return None


def project_archive_catalysts(source: Any, context: Mapping[str,Any], master_root, *, frozen=None) -> dict:
    ctx=deepcopy(dict(context));date_token(str(ctx.get('plan_trade_date')))
    dates=ctx.get('source_dates')
    if not isinstance(dates,list) or len(dates)>31 or len(set(dates))!=len(dates):raise ValueError('ARCHIVE_CATALYST_DATE_SCOPE_INVALID')
    for day in dates:date_token(day)
    if timestamp(ctx.get('research_cutoff')) is None:raise ValueError('ARCHIVE_CATALYST_CUTOFF_INVALID')
    if frozen is not None:
        if (not isinstance(frozen,Mapping) or frozen.get('schema')!=SCHEMA or frozen.get('context')!=ctx
                or not isinstance(frozen.get('selections'),list) or len(frozen['selections'])>MAX_ARTIFACTS):
            raise ValueError('ARCHIVE_CATALYST_SNAPSHOT_INVALID')
    gaps=[];selections=[];rows=[]
    if source is None:
        if frozen and frozen['selections']:raise ValueError('ARCHIVE_CATALYST_SOURCE_BINDING_LOST')
        gaps.append('RESEARCH_ARCHIVE_READER_NOT_BOUND');keys=[]
    elif frozen is not None:
        keys=[(s['date'],s['slot']) for s in frozen['selections']]
    else:
        keys=[]
        for day in dates:
            try:
                slots=source.hourly_store.list_slots(day,mode='LIVE')
                if not isinstance(slots,list) or any(not isinstance(s,str) or not re.fullmatch(r'\d{4}',s) for s in slots):
                    raise ValueError('ARCHIVE_SLOT_LIST_INVALID')
                if len(set(slots))!=len(slots):raise ValueError('ARCHIVE_SLOT_LIST_DUPLICATE')
            except _ERRORS as exc:
                slots=[];gaps.append('ARCHIVE_SLOT_ENUMERATION_FAILED:'+day+':'+type(exc).__name__)
            keys.extend((day,slot) for slot in ['',*sorted(slots)])
        if len(keys)>MAX_ARTIFACTS:raise ValueError('ARCHIVE_CATALYST_ARTIFACT_LIMIT')
    if len(keys)!=len(set(keys)):raise ValueError('ARCHIVE_CATALYST_DUPLICATE_SELECTION')
    for index,(day,slot) in enumerate(keys):
        if day not in dates or (slot and not re.fullmatch(r'\d{4}',slot)):raise ValueError('ARCHIVE_CATALYST_SELECTION_OUTSIDE_SCOPE')
        try:
            items,missing,binding=_read_archive(source,day,slot)
            selected={'date':day,'slot':slot,'binding':deepcopy(binding),'error':None}
        except _ERRORS as exc:
            selected={'date':day,'slot':slot,'binding':None,'error':type(exc).__name__};items=[];missing=['ARCHIVE_ARTIFACT_READ_FAILED:'+day+':'+(slot or 'daily')+':'+type(exc).__name__]
        if frozen is not None and selected!=frozen['selections'][index]:raise ValueError('ARCHIVE_CATALYST_SOURCE_CHANGED')
        selections.append(selected);rows.extend(items);gaps.extend(missing)
    valid=[];rejected=[]
    for row in rows:
        error=_clock_error(row,ctx)
        if error:rejected.append({'material_id':row.get('material_id'),'article_id':row.get('original_article_id'),
            'reason':error,'source_refs':deepcopy(row.get('source_refs') or [])})
        else:valid.append(row)
    projected=read_material_discovery(valid,ctx,master_root) if valid else {'cards':[],'gaps':[],'identity_witness':None,'rejected_relations':[]}
    witness=projected.get('identity_witness')
    if frozen is not None and witness!=frozen.get('identity_witness'):raise ValueError('ARCHIVE_CATALYST_IDENTITY_CHANGED')
    cards=deepcopy(projected['cards'])
    for card in cards:
        card.update(research_role='ARCHIVE_ISSUER_RESEARCH_OBSERVATION_ONLY',captured_at_target=False,
          temporal_classification='EXPLICIT_ARCHIVE_PIT_RESEARCH_NOT_NATURAL_CAPTURE')
    gaps.extend(projected.get('gaps') or [])
    if rejected:gaps.append('ARCHIVE_CATALYST_INVALID_CLOCK_ROWS_ISOLATED:'+str(len(rejected)))
    # Enumeration failures are capture diagnostics, not a recomputable assertion
    # about later directory contents. Freeze them separately, never as sources.
    enum_gaps=[g for g in gaps if g.startswith('ARCHIVE_SLOT_ENUMERATION_FAILED:')]
    if frozen is not None:enum_gaps=list(frozen.get('enumeration_gaps') or [])
    gaps=[g for g in gaps if not g.startswith('ARCHIVE_SLOT_ENUMERATION_FAILED:')]+enum_gaps
    snapshot={'schema':SCHEMA,'context':ctx,'selections':selections,'identity_witness':witness,'enumeration_gaps':enum_gaps}
    return {'cards':cards,'snapshot':snapshot,'gaps':sorted(set(gaps)),'rejected_materials':rejected,
      'rejected_relations':projected.get('rejected_relations') or [],
      'coverage':{'read_material_count':len(rows),'clock_admitted_material_count':len(valid),
      'rejected_material_count':len(rejected),'native_issuer_card_count':len(cards),
      'archive_artifact_count':sum(s['binding'] is not None for s in selections),
      'no_network_or_stage_called':True}}
