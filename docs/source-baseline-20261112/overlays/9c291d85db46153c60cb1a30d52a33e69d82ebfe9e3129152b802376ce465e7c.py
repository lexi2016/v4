"""Complete missing V192 views through the original rendering/KB owners.

This adapter never selects stocks, changes formulas, acquires prices, or runs
on GET. The existing daily/preselection owners call it after real completion.
"""
from __future__ import annotations
import gzip
import hashlib
import json
import os
from pathlib import Path

from ops import materialize_workbench_score_action as score
from ops import research_panel_daily_product as owner
from ops import render_original_formula_projection as renderer

FLAGS=score.FLAGS
SCHEMA='V4_WORKBENCH_V192_ASSETS_V1'


def original_model_reader(package_root,shared_root,source_date,target_date):
    from infrastructure.isolated_package_loader import load_isolated_package_module
    module=load_isolated_package_module(Path(package_root),package_directory='shared_data',
        module_leaf='v192_selector',namespace_prefix='existing_v192_asset_owner')
    return module.read_verified_v192_pool(shared_root,target_date=str(target_date),expected_signal_date=str(source_date))


def prepare(context,product,numeric_manifest,verified,output_root,*,symbols=None,png_renderer=None):
    """Only missing model views; every existing canonical member is reused."""
    context.unchanged();proof=verified.run.verification;manifest=verified.run.manifest
    if (product['source_identity']!=context.identity or product['source_generation']!=context.generation
            or product['data_date']!=str(context.target)
            or manifest.get('provenance',{}).get('panel_sha256')!=context.identity['selector_artifact_sha256']
            or manifest.get('signal_date')!=str(context.target)
            or proof.get('row_count')!=len(verified.rows)):
        raise ValueError('V192_ASSET_NATIVE_OR_MODEL_SOURCE_CONFLICT')
    model=[row['ts_code'] for row in verified.rows]
    if len(model)!=len(set(model)) or not set(model)<=set(product['row_refs']):raise ValueError('V192_ASSET_PROCESSED_SCOPE_CONFLICT')
    canonical={row['symbol'] for row in product['rows']}
    missing=sorted(set(model)-canonical)
    selected=sorted(symbols if symbols is not None else missing)
    if not set(selected)<=set(missing):raise ValueError('V192_ASSET_COMPUTE_OUTSIDE_MISSING_SCOPE')
    identity=dict(numeric_manifest=numeric_manifest,model_artifact_sha256=proof['artifact_sha256'],
        model_manifest_sha256=proof['manifest_sha256'],selector_sha256=context.identity['selector_artifact_sha256'],
        owner_sha256=owner.sha(Path(__file__)),renderer_sha256=owner.sha(Path(renderer.__file__)),
        score_owner_sha256=owner.sha(Path(score.__file__)),symbols=missing)
    root=Path(output_root).resolve()/str(context.target)/owner.digest(identity)
    root.mkdir(parents=True,exist_ok=True);parts=root/'parts'
    # This is a derived scope, never registered as a numeric daily product.
    subset={**product,'rows':[dict(symbol=symbol) for symbol in missing],
        'row_refs':{symbol:product['row_refs'][symbol] for symbol in missing},
        'processed_universe':missing,'processed_count':len(missing),'unique_count':len(missing),
        'sample_only':True,'scope_role':'V192_EXISTING_SYMBOL_DERIVED',
        'source_numeric_manifest':numeric_manifest,'source_model_artifact_sha256':proof['artifact_sha256']}
    subset.pop('original_charts',None)
    artifact=owner.save(root/'scope/product.json',subset,immutable=True)
    scoped_manifest=owner.save(root/'scope/manifest.json',dict(schema_version='v4.a_share.daily_product_manifest.v1',
        data_date=product['data_date'],source_generation=context.generation,input_sha256=context.identity['input_sha256'],
        artifact=artifact,sample_only=True,scope_role='V192_EXISTING_SYMBOL_DERIVED',source_numeric_manifest=numeric_manifest,**FLAGS),immutable=True)
    progress={};gaps={}
    for symbol in selected:
        retained=parts/'original_retained'/(symbol+'.json.gz')
        if retained.is_file():
            value=json.loads(gzip.decompress(retained.read_bytes()))
            if value.get('identity')!=context.identity or value.get('symbol')!=symbol or value.get('config')!=context.config_ref:
                raise ValueError('V192_RETAINED_IDENTITY_CONFLICT')
            progress[symbol]='REUSED_RETAINED'
            continue
        bars,_=context.read(symbol)
        qualification=context.qualify(symbol)
        if (qualification.get('status')!='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH'
                or not bars or bars[-1]['trade_date']!=context.target):
            gaps[symbol]='V192_SOURCE_NOT_ADMITTED:'+str(qualification.get('reason'));continue
        # Original engine, original full causal prefix; no historical labels,
        # four-group evaluation, pool mutation, or other stock is recomputed.
        result=context.engine().compute(bars,'prefix')
        renderer.retain_owner_result(context,parts,symbol,bars,result)
        progress[symbol]='COMPUTED_MISSING_CHART'
    charts=renderer.finalize_owner_charts(context,parts,subset,scoped_manifest,artifact,gaps=gaps,png_renderer=png_renderer)
    scores=score.materialize(context,product,numeric_manifest,output_root=root/'score_action',symbols=selected,workers=1)
    # Merge only this module's already completed score records. Canonical371
    # remains a different unchanged index and is never rescored by this call.
    score_index=score.checked(scores['index']);prior_file=root/'CURRENT_SCORE_INDEX.json'
    if prior_file.is_file():
        prior=score.checked(json.loads(prior_file.read_bytes()))
        if any(prior.get(k)!=score_index.get(k) for k in ('data_date','source_generation','input_sha256','numeric_manifest','rules')):
            raise ValueError('V192_SCORE_MODULE_IDENTITY_CONFLICT')
        merged={**prior['items'],**score_index['items']};score_index['items']=merged
        score_index['counts']=dict(total=len(merged),materialized=sum(score.checked(ref)['status']=='MATERIALIZED' for ref in merged.values()),unknown=sum(score.checked(ref)['status']=='UNKNOWN' for ref in merged.values()))
    score_ref=score.save(root/'score_indexes',score_index)
    owner.save(prior_file,score_ref)
    scores={**scores,'index':score_ref,'counts':score_index['counts']}
    charts={**charts,'manifest':score.save(root/'chart_receipts',score.checked(charts['manifest'])),'receipt':score.save(root/'chart_receipts',score.checked(charts['receipt']))}
    chart_manifest=score.checked(charts['manifest']);complete=set(chart_manifest['samples'])&set(score_index['items'])
    module=dict(schema=SCHEMA,status='READY' if set(missing)<=complete else 'PARTIAL',
        source_date=owner.iso(context.target),observation_date=owner.iso(manifest['trade_date']),
        data_date=str(context.target),source_generation=context.generation,input_sha256=context.identity['input_sha256'],
        numeric_manifest=numeric_manifest,selector_sha256=context.identity['selector_artifact_sha256'],
        model_source=dict(run_id=proof['run_id'],artifact_sha256=proof['artifact_sha256'],manifest_sha256=proof['manifest_sha256'],receipt_sha256=proof['receipt_sha256']),
        artifact_root=str(root),scope_product=artifact,scope_manifest=scoped_manifest,charts=charts,
        score_action=scores,scope_symbols=missing,completed_symbols=sorted(complete),model_symbols=sorted(model),
        canonical_symbols_sha256=owner.digest(sorted(canonical)),identity=identity,
        historical_PIT=False,**FLAGS)
    context.unchanged()
    owner.save(root/'RUN_PROGRESS.json',dict(progress=progress,gaps=gaps,score_cache=context._score_action_last_run))
    reference=score.save(root/'module_receipts',module)
    return dict(status=module['status'],module=reference,numeric_manifest=numeric_manifest,
        data_date=str(context.target),source_generation=context.generation,input_sha256=context.identity['input_sha256'],
        model_artifact_sha256=proof['artifact_sha256'],**FLAGS)
