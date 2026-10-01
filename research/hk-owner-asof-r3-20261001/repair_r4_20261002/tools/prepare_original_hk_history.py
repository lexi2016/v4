"""Read genuine existing HK source roots and prepare the ORIGINAL owner command.

No capture, restoration, inference, selection, provider/network call or source
write occurs here. Missing files are evidence gaps, not permission to relabel
an old pool or synthesize authority. Multiple roots must be explicitly named
from the existing owner's configuration/receipts; no disk-wide/latest search.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shlex
import sys

FLAGS=dict(production_allowed=False,buy_gate_updated=False,orders_sent=False)


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1<<20),b''):h.update(block)
    return h.hexdigest()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root',type=Path,required=True)
    parser.add_argument('--shared-package-root',type=Path,required=True)
    parser.add_argument('--shared-root',type=Path,action='append',required=True)
    parser.add_argument('--universe-root',type=Path,action='append',required=True)
    parser.add_argument('--asset-root',type=Path,action='append',required=True)
    parser.add_argument('--tdx-root',type=Path,action='append',default=[])
    parser.add_argument('--hk-python',required=True,help='Existing HK model interpreter, used only in the emitted command')
    parser.add_argument('--signal-date',default='20260929')
    parser.add_argument('--target-date',default='20260930')
    args=parser.parse_args(argv)
    sys.dont_write_bytecode=True
    app=args.app_root.expanduser().resolve(strict=True)
    package=args.shared_package_root.expanduser().resolve(strict=True)
    sys.path.insert(0,str(app))
    from contracts.trading_calendar import load_market_calendar,previous_session
    from infrastructure.isolated_package_loader import load_isolated_package_module
    expected=previous_session(load_market_calendar(),args.target_date,market='hk_securities')
    if args.signal_date!=expected:raise ValueError('price date is not previous HK securities session')
    def load(name):
        return load_isolated_package_module(package,package_directory='shared_data',
            module_leaf=name,namespace_prefix='hk_original_history_readonly')
    master=load('hk_security_master');hk=load('hk_0_2')
    source_errors=(OSError,ValueError,RuntimeError,KeyError,TypeError,master.StoreError,hk.StoreError)
    result=dict(schema_version='v4.hk_original_history_preflight.v1',
        signal_date=args.signal_date,target_date=args.target_date,
        inspected_at=datetime.now(timezone.utc).isoformat(),
        scope='EXPLICIT_EXISTING_OWNER_ROOTS_ONLY',write_performed=False,
        collection_performed=False,pool_generated=False,natural_verified=False,
        source_pairs=[],price_assets=[],native_prices=[],existing_pools=[],
        existing_owner_commands=[],**FLAGS)
    result['module_sha256']={str(m.__file__):digest(m.__file__) for m in (master,hk)}
    valid_pairs=[];valid_assets=[]
    for shared in args.shared_root:
        shared=shared.expanduser().resolve()
        for universe in args.universe_root:
            universe=universe.expanduser().resolve()
            entry=dict(shared_root=str(shared),universe_root=str(universe))
            try:
                qualification=master.read_verified_hk_eligibility_asof(shared,args.signal_date,universe_root=universe)
                # Original reader owns capture, full membership, metadata and
                # chain validation. No get_plate_stock or fake `now` fallback.
                entry.update(status='VERIFIED_SOURCE',qualification=qualification)
                valid_pairs.append((shared,universe))
            except source_errors as error:
                entry.update(status='CANNOT_CONFIRM',error=f'{type(error).__name__}:{error}')
            result['source_pairs'].append(entry)
            check=dict(shared_root=str(shared),universe_root=str(universe))
            try:
                pool=hk.read_verified_hk_0_2_pool(shared,target_date=args.target_date,
                    expected_signal_date=args.signal_date,expected_eligibility_source_date=args.signal_date,
                    eligibility_universe_root=universe)
                check.update(status='VERIFIED_EXISTING_POOL',verification=dict(pool.run.verification))
            except source_errors as error:
                check.update(status='CANNOT_CONFIRM',error=f'{type(error).__name__}:{error}')
            result['existing_pools'].append(check)
    for asset in args.asset_root:
        asset=asset.expanduser().resolve();entry={'asset_root':str(asset)}
        try:
            frozen=hk.load_frozen_hk_0_2_assets(asset)
            import pandas as pd
            # Original asset loader checks panel/model SHA. Reading one date
            # here is NOT full frozen-model feature/coverage acceptance.
            frame=pd.read_parquet(frozen.panel_path,columns=['trade_date_compact','code_norm','close'])
            day=frame.loc[frame['trade_date_compact'].astype(str).eq(args.signal_date)]
            duplicate=bool(day['code_norm'].duplicated().any())
            if day.empty or duplicate:raise ValueError('exact price day absent or duplicate codes')
            entry.update(status='EXACT_PRICE_DAY_PRESENT',panel_path=str(frozen.panel_path),
                panel_sha256=digest(frozen.panel_path),row_count=len(day),unique_codes=int(day['code_norm'].nunique()),
                source_signal_date=args.signal_date,full_feature_acceptance=False)
            valid_assets.append(asset)
        except source_errors as error:
            entry.update(status='CANNOT_CONFIRM',error=f'{type(error).__name__}:{error}')
        result['price_assets'].append(entry)
    # Only explicitly supplied original VIPDOC roots are inspected. The row
    # timestamp in each native record remains its original historical date.
    prior=(datetime.strptime(args.signal_date,'%Y%m%d')-timedelta(days=1)).strftime('%Y%m%d')
    for tdx in args.tdx_root:
        entry={'tdx_root':str(tdx.expanduser().resolve())}
        try:
            lday=hk._vipdoc_lday_root(tdx.expanduser())
            observation={}
            rows,count=hk._read_vipdoc_increment(lday,after_date=prior,
                through_date=args.signal_date,evidence=observation)
            entry.update(status='EXACT_NATIVE_ROWS_PRESENT' if rows else 'CANNOT_CONFIRM',
                source_files_scanned=count,rows=len(rows),unique_codes=len({r['code_norm'] for r in rows}),
                native_observation=observation,eligibility_proven=False,model_input_ready=False)
        except source_errors as error:
            entry.update(status='CANNOT_CONFIRM',error=f'{type(error).__name__}:{error}')
        result['native_prices'].append(entry)
    for shared,universe in valid_pairs:
        for asset in valid_assets:
            command=[args.hk_python,'-B',str(package/'scripts/materialize_hk_0_2.py'),
                '--store-root',str(shared),'--asset-root',str(asset),
                '--signal-date',args.signal_date,'--target-date',args.target_date,
                '--eligibility-source-date',args.signal_date,'--eligibility-universe-root',str(universe)]
            result['existing_owner_commands'].append(dict(argv=command,shell=shlex.join(command),
                executed=False,requires_mac_approval=True,remaining_owner_gates='Original model/coverage/immutable-slot checks'))
    result['status']='SOURCE_PAIR_AVAILABLE_FOR_EXISTING_OWNER' if result['existing_owner_commands'] else 'CANNOT_CONFIRM'
    # Availability is not a new source authority, a generated pool, or approval.
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2))
    return 0 if result['existing_owner_commands'] else 2


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,RuntimeError,ImportError) as error:
        print(json.dumps(dict(status='CANNOT_CONFIRM',error=f'{type(error).__name__}:{error}',
            write_performed=False,pool_generated=False,**FLAGS),ensure_ascii=False))
        raise SystemExit(2)
