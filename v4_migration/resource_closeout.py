from __future__ import annotations
from typing import Any

def build_long_file_batches(evidence: dict[str,Any]) -> dict[str,Any]:
    batches={'stage':[],'data_store_scheduler':[],'api':[],'other_ops':[]}
    for row in evidence.get('violations',[]):
        p=row['path']
        if p.startswith('stage_center/') or p=='ops/run_stage_center_nodes.py': batches['stage'].append(p)
        elif p.startswith('infrastructure/'): batches['data_store_scheduler'].append(p)
        elif p.startswith('apps/api/'): batches['api'].append(p)
        else: batches['other_ops'].append(p)
    return {'schema':'v4_migration.long_file_closeout.v1','batches':batches,'baseline_refresh_allowed':False,'manager_files_modified':False}

def measure_resource_delta(before: dict[str,int],after: dict[str,int]) -> dict[str,Any]:
    out={'schema':'v4_migration.resource_delta.v1','measured_only':True}
    for key in ('disk_bytes','rss_bytes'):
        if key in before and key in after: out[key+'_saved']=before[key]-after[key]
    return out
