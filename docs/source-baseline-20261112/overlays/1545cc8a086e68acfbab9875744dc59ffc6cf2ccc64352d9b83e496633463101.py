"""Read-only v1.9.2 group over the existing Main/shared candidate authority.

No selector, producer, quote acquisition, score calculation, or publication.
The four-group numeric product is never modified by this projection.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re

GROUP_ID='v192'
ROLE='A_SHARE_V192_PREMARKET_POOL_V3'
RANK_BOUNDARY='RANK_FOR_REVIEW_ONLY_NOT_BUY_PRIORITY'
FLAGS=dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
GROUPS=('nav_smallk','original','nav_pullback','nav_breakout')


def _sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def configured_reader():
    """Load the exact existing Main reader, with an explicit byte binding."""
    from infrastructure.isolated_package_loader import load_isolated_package_module
    root=os.environ.get('V4_WORKBENCH_V192_SHARED_ROOT')
    package=os.environ.get('V4_WORKBENCH_V192_SHARED_PACKAGE_ROOT')
    expected=os.environ.get('V4_WORKBENCH_V192_READER_SHA256')
    if not root or not package or not expected:raise ValueError('V192_READER_BINDING_NOT_CONFIGURED')
    path=Path(package)/'shared_data/v192_selector.py'
    if _sha(path)!=expected:raise ValueError('V192_READER_SHA_CONFLICT')
    owner=load_isolated_package_module(Path(package),package_directory='shared_data',
        module_leaf='v192_selector',namespace_prefix='workbench_existing_v192')
    if Path(owner.__file__).resolve()!=path.resolve():raise ValueError('V192_READER_PATH_CONFLICT')
    return owner.read_verified_v192_pool,Path(root),dict(path=str(path.resolve()),sha256=expected)


def version(observation_date):
    """Existing SSE invalidation hint: metadata only, never read/evaluate rows."""
    root=os.environ.get('V4_WORKBENCH_V192_SHARED_ROOT')
    if not root:return dict(status='V192_READER_BINDING_NOT_CONFIGURED')
    day=observation_date.replace('-','')
    if not re.fullmatch(r'\d{8}',day):raise ValueError('V192_TARGET_DATE_INVALID')
    root=Path(root).resolve();path=root/'latest.json'
    if not path.is_file():return dict(status='NOT_MATERIALIZED')
    entry=json.loads(path.read_bytes()).get('entries',{}).get(day+'/'+ROLE)
    if not entry:return dict(status='NOT_MATERIALIZED')
    run_id=entry.get('run_id')
    if not isinstance(run_id,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+',run_id) or run_id in {'.','..'}:
        raise ValueError('V192_RUN_ID_INVALID')
    stamps={}
    for name in ('manifest.json','receipt.json','artifact.csv'):
        asset=root/'runs'/day/ROLE/run_id/name
        if asset.is_symlink() or asset.resolve(strict=True)!=asset or not asset.is_relative_to(root):
            raise ValueError('V192_METADATA_PATH_CONFLICT')
        st=asset.stat();stamps[name]=[st.st_size,st.st_mtime_ns,st.st_ino]
    return dict(status='SOURCE_METADATA_PRESENT',entry=entry,stamps=stamps,
        reader_sha256=os.environ.get('V4_WORKBENCH_V192_READER_SHA256'))


def project(source,product,source_date,observation_date,*,binding_reader=configured_reader):
    common=dict(schema='V4_WORKBENCH_V192_GROUP_V1',group_id=GROUP_ID,label='v1.9.2候选',
        source_date=source_date,observation_date=observation_date,generation=product['source_generation'],
        input_sha256=product['source_identity']['input_sha256'],numeric_manifest=product['manifest'],
        selector_sha256=product['source_identity']['selector_artifact_sha256'],
        rank_usage_boundary=RANK_BOUNDARY,statistics_status='V192_SAME_DEFINITION_NOT_MATERIALIZED',
        historical_PIT=False,**FLAGS)
    try:
        reader,root,reader_ref=binding_reader()
        verified=reader(root,target_date=observation_date.replace('-',''),expected_signal_date=source_date.replace('-',''))
        run=verified.run;manifest=run.manifest;proof=run.verification
        if (manifest.get('provenance',{}).get('panel_sha256')!=common['selector_sha256']
                or manifest.get('signal_date')!=source_date.replace('-','')
                or manifest.get('trade_date')!=observation_date.replace('-','')
                or proof.get('row_count')!=len(verified.rows)
                or proof.get('artifact_sha256')!=manifest.get('artifact_sha256')):
            raise ValueError('V192_WORKBENCH_SOURCE_IDENTITY_CONFLICT')
        rows=[];excluded=[];seen=set()
        processed=set(product.get('processed_universe',[]));refs=product.get('row_refs',{})
        for candidate in verified.rows:
            symbol=candidate.get('ts_code')
            if (not isinstance(symbol,str) or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)',symbol)
                    or symbol in seen or symbol not in processed or symbol not in refs
                    or candidate.get('signal_date')!=source_date.replace('-','')
                    or candidate.get('target_date')!=observation_date.replace('-','')):
                raise ValueError('V192_PROCESSED_SYMBOL_IDENTITY_CONFLICT')
            seen.add(symbol)
            # Only its bound existing checkpoint is read. Historical groups,
            # returns and evaluations are not copied into the API response.
            detail=None
            try:
                detail=source._a_product_reference(refs[symbol])
                if detail.get('symbol')!=symbol or detail.get('data_date')!=product['data_date']:
                    raise ValueError('V192_CHECKPOINT_DATE_OR_SYMBOL_CONFLICT')
                try:source._a_daily_checkpoint_binding(detail,product,symbol,product['data_date'])
                except (OSError,KeyError,TypeError) as error:
                    raise ValueError('A_DAILY_SYMBOL_DETAIL_FORMULA_SOURCE_UNAVAILABLE:'+str(error)) from error
                hits=set(filter(None,detail.get('groups','').split('|')))
                pending=set(filter(None,detail.get('pending_groups','').split('|')))
                if not hits<=set(GROUPS) or not pending<=set(GROUPS) or hits&pending:
                    raise ValueError('V192_CHECKPOINT_GROUP_CONFLICT')
            except (ValueError,OSError,KeyError,TypeError) as error:
                # Formula/config identity is shared by the entire product, so
                # these failures must still close the whole projection.
                if str(error).startswith('A_DAILY_SYMBOL_DETAIL_FORMULA_'):
                    raise
                qualification=detail.get('qualification',{}) if isinstance(detail,dict) else {}
                excluded.append(dict(symbol=symbol,status='CANNOT_CONFIRM',reason=str(error),
                    qualification_reason=qualification.get('reason'),
                    source_checkpoint=refs[symbol]))
                continue
            rows.append(dict(symbol=symbol,enriched_display_name=detail.get('display_name') or candidate.get('stock_name'),
                group_states={g:'TRUE' if g in hits else 'UNKNOWN' if g in pending else 'FALSE' for g in GROUPS},
                eligible_candidate=bool(hits),in_fifth=bool(pending),v192_member=True,history_rates={},
                v192={key:candidate.get(key) for key in ('selector_version','multi_head_final_role','entry_pool',
                    'final_score','premarket_pool_score','primary_buy_signal','secondary_buy_signal')},
                source_checkpoint=refs[symbol],checkpoint_status='BOUND_SAME_GENERATION',
                source_row={key:detail.get(key) for key in ('symbol','data_date','groups','pending_groups','risk_clear','reasons')}))
        return dict(status='PARTIAL' if excluded else 'READY' if rows else 'READY_EMPTY',
            rows=rows,count=len(rows),source_count=len(verified.rows),valid_count=len(rows),
            pending_count=len(excluded),excluded_count=len(excluded),excluded_rows=excluded,
            source_run_id=proof['run_id'],source_artifact_sha256=proof['artifact_sha256'],
            source_manifest_sha256=proof['manifest_sha256'],source_receipt_sha256=proof['receipt_sha256'],
            reader_source=reader_ref,**common)
    except (ValueError,OSError,KeyError,TypeError) as error:
        return dict(status='CANNOT_CONFIRM',reason=str(error),rows=[],count=0,source_count=None,valid_count=None,
            pending_count=None,excluded_count=None,excluded_rows=[],**common)
    except Exception as error:
        # The original strict reader's StoreError is intentionally not replaced
        # with an empty READY group or a stale/latest candidate artifact.
        return dict(status='CANNOT_CONFIRM',reason=type(error).__name__+':'+str(error),rows=[],count=0,source_count=None,valid_count=None,
            pending_count=None,excluded_count=None,excluded_rows=[],**common)
