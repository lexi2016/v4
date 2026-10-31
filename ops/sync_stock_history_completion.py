"""Existing-owner publication adapter for completed frozen R2 stock receipts.

No history/formula evaluation. prepare writes only to staging; publish requires
an exact expected-index CAS. watch uses native filesystem events, no timed poll.
"""
from __future__ import annotations
import argparse
import copy
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import select
import sys
import stat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ops.bootstrap_stock_event_history import canonical, load, ref, save, sha

FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
EXCLUDED_ROW = {'statistics', 'historical_coverage'}
DEFAULT_OWNER_LOCK = Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/dispatcher/scheduler_lane_owners/A_LONG.lock')


def without_statistics(row):
    return {key: value for key, value in row.items() if key not in EXCLUDED_ROW}


class Staging:
    def __init__(self, root, stage):
        self.root, self.stage = Path(root).resolve(), Path(stage).resolve()
        self.files = {}

    def save(self, path, value):
        path = Path(path)
        relative = path.relative_to(self.root)
        staged = self.stage / relative
        local = save(staged, value)
        result = dict(path=str(path), sha256=local['sha256'])
        self.files[str(path)] = local
        return result

    def read(self, reference):
        local = self.files.get(reference['path'])
        if local is not None and local['sha256'] != reference['sha256']:
            raise ValueError('STAGED_REF_CONFLICT')
        return load(local or reference)

    def immutable(self, folder, filename, value):
        return self.save(self.root / folder / hashlib.sha256(canonical(value)).hexdigest() / filename, value)


def prepare(batch, root, stage, *, selected=None, owner_lock=DEFAULT_OWNER_LOCK):
    """Validate every changed row once, preserving all non-target refs/fields."""
    lock_info = Path(owner_lock).lstat()
    if Path(owner_lock).is_symlink() or not stat.S_ISREG(lock_info.st_mode):
        raise ValueError('EXISTING_SHARED_OWNER_LOCK_REQUIRED')
    lock_binding = dict(path=str(Path(owner_lock).resolve()), device=lock_info.st_dev, inode=lock_info.st_ino)
    permit = json.loads((batch / 'RUN_AUTHORIZATION_R2.json').read_bytes())
    contract_ref = permit['contract']
    contract = load(contract_ref)
    if permit['status'] != 'ROOT_RUN_STARTED_REGISTERED' or permit['contract_sha256'] != contract_ref['sha256']:
        raise ValueError('REGISTERED_R2_REQUIRED')
    for reference in contract['code']:
        if sha(reference['path']) != reference['sha256']:
            raise ValueError('FROZEN_R2_CODE_DRIFT')
    date = str(contract['config']['target'])
    writer = Staging(root, stage)
    index_ref, event_ref = ref(root / 'index.json'), ref(root / 'events/latest.json')
    index = load(index_ref)
    old_event = load(event_ref)
    manifest_ref = index['dates'][date]
    manifest = load(manifest_ref)
    product = load(manifest['artifact'])
    if (index.get('latest_date') != date or index.get('latest') != manifest_ref or
        old_event.get('data_date') != date or old_event.get('source_generation') != contract['source_generation'] or
        old_event.get('input_sha256') != contract['input_sha256'] or old_event.get('manifest') != manifest_ref or
        old_event.get('artifact') != manifest['artifact']):
        raise ValueError('LATEST_PRODUCT_OR_COMPLETION_EVENT_MOVED')
    original = load(contract['refs']['numeric_product'])
    targets = set(contract['config']['symbols'])
    candidates = set(contract['config'].get('candidate_symbols', contract['config']['symbols']))
    if (product['data_date'] != date or product['source_generation'] != contract['source_generation'] or
        product['source_identity'] != contract['source_identity'] or product['source_config'] != contract['refs']['source_config'] or
        {row['symbol'] for row in product['rows']} != candidates or
        set(product['row_refs']) != set(original['row_refs']) or
        {k:v for k,v in product.items() if k != 'row_refs'} != {k:v for k,v in original.items() if k != 'row_refs'}):
        raise ValueError('CURRENT_PRODUCT_IDENTITY_OR_MEMBERSHIP_DRIFT')
    changed_before = {symbol for symbol in product['row_refs'] if product['row_refs'][symbol] != original['row_refs'][symbol]}
    sync_before = index.get('history_sync', {}).get(date)
    if changed_before and (not sync_before or not changed_before <= set(sync_before['completed_symbols'])):
        raise ValueError('UNOWNED_CURRENT_ROW_CHANGE')
    descriptor = copy.deepcopy(index['original_charts'][date])
    origin_ref = descriptor['chart_origin_manifest'] if 'chart_origin_manifest' in descriptor else contract['refs']['numeric_manifest']
    descriptor['chart_origin_manifest'] = origin_ref
    chart_origin = load(load(origin_ref)['artifact'])
    if (set(chart_origin['row_refs']) != set(product['row_refs']) or
        {k:v for k,v in chart_origin.items() if k != 'row_refs'} != {k:v for k,v in product.items() if k != 'row_refs'}):
        raise ValueError('CHART_ORIGIN_PRODUCT_CONFLICT')
    available = {}
    for symbol in sorted(targets):
        done = batch / 'stocks' / symbol / 'RESULT.json'
        if done.is_file() and (selected is None or symbol in selected):
            result_ref = ref(done)
            result = load(result_ref)
            if result['contract'] != contract_ref or result['symbol'] != symbol or result['status'] != 'COMPLETE_DESCRIPTIVE_NONPIT':
                raise ValueError('STOCK_COMPLETION_CONTRACT_CONFLICT:' + symbol)
            available[symbol] = (result_ref, result)
    precompleted = set()
    for symbol in candidates - targets:
        row = load(product['row_refs'][symbol])
        if row.get('historical_coverage', {}).get('known_full_history') and not row['historical_coverage'].get('missing'):
            precompleted.add(symbol)
    completed = precompleted | changed_before | set(available)
    if sync_before and set(sync_before['completed_symbols']) == completed:
        return dict(status='NO_NEW_COMPLETION', expected_index=index_ref, completed=sorted(completed), **FLAGS)
    updated = copy.deepcopy(product)
    accepted_cases = {}
    result_refs = dict((sync_before or {}).get('stock_results', {}))
    for symbol, (result_ref, result) in available.items():
        if symbol in changed_before:
            if result_refs.get(symbol) != result_ref:
                raise ValueError('PREVIOUSLY_PUBLISHED_STOCK_RECEIPT_DRIFT:' + symbol)
            continue
        row, history, cases = (load(result[key]) for key in ('row', 'history_cache', 'event_cases'))
        entry = contract['entries'][symbol]
        old_row = load(original['row_refs'][symbol])
        if (row['symbol'] != symbol or row['data_date'] != date or without_statistics(row) != without_statistics(old_row) or
            not row['historical_coverage']['known_full_history'] or row['historical_coverage']['missing'] or
            history['source_identity'] != contract['source_identity'] or
            not set(entry.get('prior_entry_reuse', {}).get('dates', [])) <= set(history['evaluations']) or
            history['rule_sha256'] != contract['code'][2]['sha256'] or
            len(history['evaluations']) != entry['rows'] or result['remaining_dates'] or
            cases['symbol'] != symbol or cases['data_date'] != date or cases['contract'] != contract_ref or
            cases['accepted_cache'] != result['history_cache'] or cases['projection'] != entry['projection'] or
            cases['statistics_sha256'] != hashlib.sha256(canonical(row['statistics'])).hexdigest() or
            cases['source_generation'] != contract['source_generation'] or cases['input_sha256'] != contract['input_sha256']):
            raise ValueError('STOCK_HISTORY_OR_NONSTAT_PARITY_FAILED:' + symbol)
        bound_calendar = load(cases['calendar'])['dates']
        dates = bound_calendar[symbol[-2:]] if isinstance(bound_calendar, dict) else bound_calendar
        if dates != load(contract['refs']['calendar'])['dates'][symbol[-2:]]:
            raise ValueError('STOCK_CALENDAR_VALUE_DRIFT:' + symbol)
        for group, horizons in cases['groups'].items():
            events = sorted(str(day) for day, record in history['evaluations'].items() if record['groups'][group] == 'TRUE')
            accepted = next(g for g in row['statistics']['groups'] if g['group_id'] == group)
            for horizon, values in horizons.items():
                if (sorted(case['event_date'].replace('-', '') for case in values['cases']) != events or
                    {k:v for k,v in values.items() if k not in {'cases','conditional'}} !=
                    {k:v for k,v in accepted['horizons'][horizon].items() if k != 'cases'}):
                    raise ValueError('STOCK_CASES_AGGREGATE_COVERAGE_CONFLICT:' + symbol)
        updated['row_refs'][symbol] = writer.immutable(f'history_sync/{date}/rows', symbol+'.json', row)
        accepted_cases[symbol] = cases
        result_refs[symbol] = result_ref
    # Validate all changed rows once before publication, including the accepted
    # pre-existing002003 relative to the immutable original chart origin.
    changed = sorted(symbol for symbol in chart_origin['row_refs'] if chart_origin['row_refs'][symbol] != updated['row_refs'][symbol])
    if not set(changed) <= candidates or not completed <= candidates:
        raise ValueError('UPDATED_SYMBOL_OUTSIDE_FROZEN_CANDIDATES')
    for symbol in changed:
        if updated['row_refs'][symbol] == product['row_refs'][symbol] and symbol in descriptor['history_updated_symbols']:
            continue  # exact prior publication parity is already bound
        if without_statistics(load(chart_origin['row_refs'][symbol])) != without_statistics(writer.read(updated['row_refs'][symbol])):
            raise ValueError('CHART_NONSTAT_ROW_PARITY_FAILED:' + symbol)
    artifact = writer.immutable(f'versions/{date}/{contract["source_generation"]}', 'product.json', updated)
    new_manifest = {**manifest, 'artifact': artifact}
    new_manifest_ref = writer.immutable(f'history_sync/{date}/manifests', 'manifest.json', new_manifest)
    new_index = copy.deepcopy(index)
    new_index['dates'][date] = new_manifest_ref
    if new_index['latest_date'] == date:
        new_index['latest'] = new_manifest_ref
    descriptor.update(numeric_manifest=new_manifest_ref, history_updated_symbols=changed,
                      history_contract=contract_ref)
    new_index['original_charts'][date] = descriptor
    # Display names are a small independent projection; update only its binding.
    names_ref=index.get('display_names',{}).get(date)
    if names_ref:
        names=load(names_ref);names['numeric_manifest']=new_manifest_ref
        new_index['display_names'][date]=writer.immutable(f'display_names/{date}','names.json',names)
    materials_ref=index.get('company_materials',{}).get(date)
    if materials_ref:
        materials=load(materials_ref)
        materials['source_numeric_manifest']=materials.get('source_numeric_manifest',materials['numeric_manifest'])
        materials['numeric_manifest']=new_manifest_ref
        new_index['company_materials'][date]=writer.immutable(f'company_materials/{date}','index.json',materials)
    events = load(index['event_cases'][date])
    origins = events.setdefault('case_numeric_origins', {})
    for symbol, reference in events['items'].items():
        if symbol not in origins:
            origins[symbol] = load(reference)['numeric_manifest']
    for symbol, cases in accepted_cases.items():
        cases = {**cases, 'numeric_manifest':new_manifest_ref}
        events['items'][symbol] = writer.immutable(f'event_cases/{date}', symbol+'.json', cases)
        origins[symbol] = new_manifest_ref
    events['numeric_manifest'] = new_manifest_ref
    new_index['event_cases'][date] = writer.immutable(f'event_cases/{date}', 'index.json', events)
    new_index.setdefault('history_sync', {})[date] = dict(numeric_manifest=new_manifest_ref,
        source_generation=contract['source_generation'], input_sha256=contract['input_sha256'], contract=contract_ref,
        candidate_symbols=sorted(candidates), completed_symbols=sorted(completed), bootstrap_symbols=sorted(targets), preserved_complete_symbols=sorted(precompleted), stock_results=result_refs,
        status='COMPLETE' if completed == candidates else 'RUNNING', **FLAGS)
    top_ref = new_index.get('top200', {}).get(date)
    if top_ref:
        top = load(top_ref)
        if top.get('numeric_manifest') != manifest_ref or top.get('source_generation') != contract['source_generation']:
            raise ValueError('TOP200_PRIOR_NUMERIC_BINDING_DRIFT')
        top['numeric_manifest'] = new_manifest_ref
        new_index['top200'][date] = writer.immutable('top200/'+date, 'top200.json', top)
    event = {**old_event, 'manifest':new_manifest_ref, 'artifact':artifact, 'original_charts':descriptor,
             'event_cases':new_index['event_cases'][date],
             **({'company_materials':new_index['company_materials'][date]} if materials_ref else {}),
             **({'display_names':new_index['display_names'][date]} if names_ref else {}),
             **({'top200':new_index['top200'][date]} if top_ref else {}),
             'event_id':hashlib.sha256(canonical(dict(numeric_manifest=new_manifest_ref, original_charts=descriptor))).hexdigest()}
    staged_index, staged_event = save(stage / 'index.json', new_index), save(stage / 'event.json', event)
    owner_ref = next(reference for reference in contract['code'] if reference['path'].endswith('/ops/research_panel_daily_product.py'))
    plan = dict(status='PREPARED_HISTORY_SYNC', expected_index=index_ref, expected_event=event_ref,
        staged_index=staged_index, staged_event=staged_event, immutable_files=writer.files,
        numeric_manifest=new_manifest_ref, artifact=artifact, completed=sorted(completed), changed=changed,
        owner_publisher=owner_ref, shared_owner_lock=lock_binding, target_root=str(root), stage=str(stage), contract=contract_ref, **FLAGS)
    save(stage / 'PLAN.json', plan)
    return plan


def _inherited_owner_duplicate(shared,date):
    raw=os.environ.get('V4_SCHEDULER_LANE_FD')
    if raw is None:return None
    try:
        fd=int(raw)
        if fd<3 or os.environ.get('V4_SCHEDULER_LANE_NAME')!='A_LONG' or os.environ.get('V4_SCHEDULER_RESOLVED_DATE')!=date or os.environ.get('V4_SCHEDULER_RESOLVED_SLOT')not in {'1540','1610','1640'}:raise ValueError('identity')
        held=os.fstat(fd);current=os.stat(shared['path'],follow_symlinks=False)
        if not stat.S_ISREG(held.st_mode) or (held.st_dev,held.st_ino)!=(shared['device'],shared['inode']) or (current.st_dev,current.st_ino)!=(held.st_dev,held.st_ino):raise ValueError('inode')
        probe=os.open(shared['path'],os.O_RDONLY|os.O_NOFOLLOW)
        try:
            try:fcntl.flock(probe,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:pass
            else:raise ValueError('inherited_lane_not_locked')
        finally:os.close(probe)
        # A different open description on the same inode cannot re-acquire the
        # held lock. This succeeds only for the original inherited lease.
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return os.dup(fd)
    except (ValueError,OSError)as error:raise ValueError('SHARED_INHERITED_OWNER_FD_INVALID:'+str(error))from error


def publish(plan, *, refresh=None):
    """The exact original Main owner's save writes the existing index/event path."""
    owner_ref = plan['owner_publisher']
    path = Path(owner_ref['path'])
    if sha(path) != owner_ref['sha256']:
        raise ValueError('ORIGINAL_OWNER_CODE_DRIFT')
    spec = importlib.util.spec_from_file_location('accepted_history_sync_owner', path)
    owner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner)
    root = Path(plan['target_root'])
    lock = (root / '.stock-history-completion.lock').open('a+b')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    shared = plan['shared_owner_lock']
    inherited = _inherited_owner_duplicate(shared, load(plan['expected_event'])['data_date'])
    shared_fd = inherited if inherited is not None else os.open(shared['path'], os.O_RDONLY | os.O_NOFOLLOW)
    try:
        # The same stable inode is inherited by the actual Main A_LONG lane.
        # Blocking flock waits for that real owner, without a polling/retry loop.
        fcntl.flock(shared_fd, fcntl.LOCK_EX)
        current = os.stat(shared['path'], follow_symlinks=False)
        held = os.fstat(shared_fd)
        if ((held.st_dev, held.st_ino) != (shared['device'], shared['inode']) or
            (current.st_dev, current.st_ino) != (held.st_dev, held.st_ino)):
            raise ValueError('SHARED_OWNER_LOCK_INODE_DRIFT')
        if refresh is not None:
            plan = refresh()  # Reconcile real completed receipts after ownership returns.
            if plan['status'] == 'NO_NEW_COMPLETION':
                return plan
        for key in ('expected_index', 'expected_event'):
            load(plan[key])
        for target, staged in plan['immutable_files'].items():
            value = load(staged)
            if owner.save(Path(target), value, immutable=True)['sha256'] != staged['sha256']:
                raise ValueError('OWNER_SERIALIZATION_DRIFT')
        new_index, new_event = load(plan['staged_index']), load(plan['staged_event'])
        before = dict(index=load(plan['expected_index']), event=load(plan['expected_event']))
        for key in ('expected_index', 'expected_event'):
            load(plan[key])
        after_index = owner.save(root / 'index.json', new_index)
        try:
            after_event = owner.save(root / 'events/latest.json', new_event)
        except Exception:
            if ref(root / 'index.json') == after_index:
                owner.save(root / 'index.json', before['index'])
            raise
        receipt = dict(status='PUBLISHED_TOP200' if plan['status']=='PREPARED_TOP200' else 'PUBLISHED_HISTORY_SYNC', index=after_index, event=after_event,
                       before=before, completed=plan['completed'], **FLAGS)
        save(Path(plan['stage']) / 'PUBLICATION_RECEIPT.json', receipt)
        return receipt
    finally:
        os.close(shared_fd)
        lock.close()


def watch(batch, root, stage_root):
    """Watch atomic RESULT renames using macOS vnode events, never fixed polling."""
    if not hasattr(select, 'kqueue'):
        raise RuntimeError('NATIVE_KQUEUE_REQUIRED_NO_POLLING_FALLBACK')
    stage_root.mkdir(parents=True, exist_ok=True)
    owner_lock = (stage_root / '.watch.lock').open('a+b')
    fcntl.flock(owner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    import resource
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft < 1024:
        resource.setrlimit(resource.RLIMIT_NOFILE, (min(1024, hard), hard))
    watcher = select.kqueue()
    watched = {}
    streams = []
    stocks = batch / 'stocks'
    def add(directory):
        if directory in watched:
            return
        fd = os.open(directory, os.O_RDONLY)
        streams.append(fd)
        watched[directory] = fd
        watcher.control([select.kevent(fd, filter=select.KQ_FILTER_VNODE, flags=select.KQ_EV_ADD|select.KQ_EV_CLEAR,
                                     fflags=select.KQ_NOTE_WRITE|select.KQ_NOTE_RENAME|select.KQ_NOTE_DELETE)], 0)
    def discover():
        add(stocks)
        for directory in stocks.iterdir():
            if directory.is_dir():
                add(directory)
    def sync():
        stage = stage_root / ('completion_' + __import__('uuid').uuid4().hex)
        plan = prepare(batch, root, stage)
        if plan['status'] != 'NO_NEW_COMPLETION':
            receipt = publish(plan, refresh=lambda: prepare(batch, root, stage))
            save(stage_root / 'LATEST.json', dict(plan=ref(stage/'PLAN.json'), receipt=ref(stage/'PUBLICATION_RECEIPT.json'), **FLAGS))
            print(json.dumps(dict(event=receipt['status'],completed=len(receipt['completed']))),flush=True)
    try:
        discover()
        sync()  # startup reconciliation closes the subscribe/start race
        while True:
            watcher.control(None, 256, None)  # blocks on real filesystem events
            discover()
            sync()
    finally:
        for fd in streams:
            os.close(fd)
        watcher.close()
        owner_lock.close()


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch',type=Path)
    parser.add_argument('--root',type=Path)
    parser.add_argument('--stage',type=Path,required=True)
    parser.add_argument('--publish',action='store_true')
    parser.add_argument('--watch',action='store_true')
    args=parser.parse_args()
    if args.watch:
        watch(args.batch,args.root,args.stage)
    elif args.publish:
        print(json.dumps(publish(load(ref(args.stage/'PLAN.json'))),ensure_ascii=False))
    else:
        print(json.dumps(prepare(args.batch,args.root,args.stage),ensure_ascii=False))
