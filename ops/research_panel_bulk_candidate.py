"""Bounded isolated invocation of the existing QFQ research candidate owner.

The wrapper supplies already frozen inputs and a per-invocation checkpoint
budget. It owns no market data, producer, scheduler, or publication pointer.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
import traceback
from pathlib import Path

from ops import research_panel_qfq as q


def _ref(path: Path) -> dict:
    return {'path':str(path), 'sha256':q.sha(path)}


def run(*, identity_ref: dict, label: str, max_new: int, workers: int,
        backend: str, sdk_site: Path, min_free_gib: int = 40) -> dict:
    if (not re.fullmatch(r'[a-z0-9_-]{1,32}', label) or type(max_new) is not int or max_new < 1
            or type(workers) is not int or not 1 <= workers <= 4 or backend not in {'thread','process'}
            or type(min_free_gib) is not int or min_free_gib < 40):
        raise ValueError('BULK_BATCH_ARGUMENT_INVALID')
    frozen = json.loads(q._source(identity_ref, owner='bulk frozen owner identity').read_text())
    if (frozen.get('schema') != 'a_share_bulk_owner_frozen_identity_v1'
            or frozen.get('status') != 'FROZEN_AFTER_OWNER_AND_RESUME_CANARY'
            or any(frozen.get(k) != v for k,v in q.FLAGS.items())):
        raise ValueError('BULK_FROZEN_IDENTITY_INVALID')
    root = Path(frozen['root'])
    if not root.is_absolute() or root.is_symlink() or root.resolve(strict=True) != root:
        raise ValueError('BULK_ISOLATED_ROOT_INVALID')
    receipts = root / 'batch_receipts'; receipts.mkdir(exist_ok=True)
    destination = receipts / (label + '.json')
    if destination.exists():
        raise ValueError('BULK_BATCH_RECEIPT_ALREADY_EXISTS')
    start = time.monotonic()
    record = dict(schema='a_share_bulk_owner_batch_v1',status='RUNNING',label=label,
                  expected_generation=frozen['generation_id'],identity=identity_ref,
                  max_new=max_new,workers=workers,backend=backend,**q.FLAGS)
    try:
        for name, reference in frozen['source_refs'].items():
            q._source(reference, owner='bulk frozen source '+name)
        for key in ('first_receipt','resume_receipt','inputs'):
            q._source(frozen[key], owner='bulk '+key)
        inputs = json.loads(Path(frozen['inputs']['path']).read_text())
        if (inputs['qfq_source']['sha256'] != q.sha(q.__file__)
                or inputs['full_research_contract']['sha256'] != frozen['source_refs']['contracts/a_share_kb_full_research_v1.json']['sha256']):
            raise ValueError('BULK_OWNER_OR_CONTRACT_DRIFT')
        for name in ('snapshot','lifecycle_additions','source_relocation','full_research_contract',
                     'materialized_reuse','spool_reuse','driver','formula','contract_csv'):
            q._source(inputs[name], owner='bulk source '+name)
        if (not sdk_site.is_absolute() or not sdk_site.is_dir() or sdk_site.is_symlink()
                or sdk_site.resolve(strict=True) != sdk_site):
            raise ValueError('BULK_SDK_SITE_INVALID')
        if str(sdk_site) not in sys.path:
            sys.path.append(str(sdk_site))
        free = shutil.disk_usage(root).free
        if free < min_free_gib * 1024**3:
            raise ValueError('BULK_DISK_RESERVE_UNAVAILABLE')
        record.update(free_bytes_before=free, wrapper_source=_ref(Path(__file__).resolve()))
        result = q.run_daily_rebuild(driver_path=Path(inputs['driver']['path']),
            formula_path=Path(inputs['formula']['path']), tdx_root=Path(inputs['tdx_root']),
            data_root=root/'data', pointers={role:root/'pointers'/(role+'.txt') for role in ('selector','backtest')},
            contract_csv=Path(inputs['contract_csv']['path']),return_root=root/'runs',target=20261030,
            publish=False,workers=workers,refresh_inputs=False,compute_backend=backend,
            archive_additions=inputs['lifecycle_additions'],source_relocation_ref=inputs['source_relocation'],
            full_research_contract_ref=inputs['full_research_contract'],full_research_isolation_root=root,
            materialized_reuse_ref=inputs['materialized_reuse'],full_research_batch_limit=max_new,
            full_research_spool_reuse_ref=inputs['spool_reuse'])
        generation = result.get('generation_id') or result.get('authority',{}).get('generation_id')
        if generation != frozen['generation_id']:
            raise ValueError('BULK_OWNER_GENERATION_DRIFT')
        record.update(status=result['status'],generation_id=generation,owner_result=result,
                      free_bytes_after=shutil.disk_usage(root).free,historical_PIT=False)
    except Exception as exc:
        record.update(status='FAIL',error=repr(exc),traceback=traceback.format_exc())
    record['seconds']=round(time.monotonic()-start,2)
    with destination.open('x',encoding='utf-8') as stream:
        json.dump(record,stream,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)
        stream.write('\n')
    if record['status'] == 'FAIL':
        raise RuntimeError('BULK_BATCH_FAILED:'+str(destination)+':'+record['error'])
    return dict(status=record['status'],generation_id=record.get('generation_id'),receipt=_ref(destination))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--identity',required=True,type=Path)
    parser.add_argument('--identity-sha256',required=True)
    parser.add_argument('--label',required=True)
    parser.add_argument('--max-new',required=True,type=int)
    parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--backend',choices=('thread','process'),default='process')
    parser.add_argument('--sdk-site',required=True,type=Path)
    args=parser.parse_args()
    result=run(identity_ref={'path':str(args.identity),'sha256':args.identity_sha256},label=args.label,
               max_new=args.max_new,workers=args.workers,backend=args.backend,sdk_site=args.sdk_site)
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
