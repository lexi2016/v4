"""One-off CAS integration of reviewed outputs into the original research chain.

No formula, fetching, scheduler or application-lane invocation.  The accepted
snapshot is built by the configured r1 owner's unchanged constructor.  The
transaction journal and exact preimages retain every original byte.
"""
import sys
sys.dont_write_bytecode = True
import argparse, ast, csv, fcntl, hashlib, importlib, json, os, struct, subprocess, time
from datetime import datetime
from pathlib import Path

R = Path(__file__).resolve().parents[1]
E = 'A_SHARE_QUARANTINE_ORIGINAL_CHAIN_PUBLISH_20261021_R2_01'
ACTIVATION_CONTRACT = R / 'ORIGINAL_CHAIN_PUBLISH_R2_CONTRACT.json'

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b''): h.update(b)
    return h.hexdigest()

def stat(path):
    s = Path(path).stat()
    return {'inode': s.st_ino, 'mtime_ns': s.st_mtime_ns, 'size': s.st_size}

def save(path, value):
    path = Path(path)
    with path.open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n'); f.flush(); os.fsync(f.fileno())

def fsync_dir(path):
    fd = os.open(str(path), os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)

def exclusive_bytes(path, data):
    path = Path(path)
    with path.open('xb') as f: f.write(data); f.flush(); os.fsync(f.fileno())
    fsync_dir(path.parent)

def cas_bytes(path, expected, replacement, tag):
    """Compare immediately before rename; callers hold the transaction lock."""
    path = Path(path)
    assert not path.is_symlink(), 'Symlink forbidden: ' + str(path)
    assert sha(path) == expected, 'CAS preimage drift: ' + str(path)
    temp = path.with_name('.' + path.name + '.' + tag + '.tmp')
    exclusive_bytes(temp, replacement)
    assert sha(path) == expected, 'CAS drift during staging: ' + str(path)
    os.replace(temp, path); fsync_dir(path.parent)
    assert sha(path) == hashlib.sha256(replacement).hexdigest()

def active_writers():
    markers = ('a_share_daily_sync.py', 'data_layer_daily_formula_increment_update_v1.py',
               'macos_research_panel_daily_gate.py', 'a_formula_increment.py')
    proc = subprocess.run(['ps', '-axo', 'pid=,command='], capture_output=True, text=True, check=True)
    found = []
    for line in proc.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2: continue
        pid, command = fields
        matched = [x for x in markers if x in command]
        if matched and int(pid) != os.getpid(): found.append({'pid': int(pid), 'matched_script_names': matched})
    return found

def check_inputs(cfg):
    for item in cfg['input_bindings']:
        assert sha(item['path']) == item['sha256'], 'Frozen input drift: ' + item['path']
    for panel in cfg['panels'].values():
        assert stat(panel['old_path']) == panel['old_stat'], 'Original panel stat drift'
        assert sha(panel['pointer_path']) == panel['old_pointer_sha256'], 'Original pointer drift'
        assert Path(panel['pointer_path']).read_text(encoding='utf-8-sig').strip() == panel['old_path']
        assert stat(panel['candidate_path']) == panel['candidate_stat'], 'Reviewed candidate stat drift'

def row_map(data):
    assert data and len(data) % 32 == 0
    rows = {}
    previous = 0
    for pos in range(0, len(data), 32):
        block = data[pos:pos + 32]; day = struct.unpack_from('<I', block)[0]
        assert day > previous, 'Native key order/uniqueness failure'
        rows[day] = block; previous = day
    return rows

def row_ledger(old, new):
    before, after = row_map(old), row_map(new)
    result = []
    for day in sorted(set(before) | set(after)):
        a, b = before.get(day), after.get(day)
        status = ('RETAINED' if a == b else 'REPLACED') if a is not None and b is not None else (
            'INSERTED' if a is None else 'QUARANTINED_ORIGINAL_NOT_IN_CANONICAL_SOURCE')
        result.append({'trade_date': day, 'disposition': status,
                       'original_32b_sha256': hashlib.sha256(a).hexdigest() if a else None,
                       'canonical_32b_sha256': hashlib.sha256(b).hexdigest() if b else None,
                       'changed_word_indices': [i for i in range(8) if a[4*i:4*i+4] != b[4*i:4*i+4]] if a and b else None})
    assert len(before) == sum(x['disposition'] != 'INSERTED' for x in result)
    assert len(after) == sum(x['disposition'] != 'QUARANTINED_ORIGINAL_NOT_IN_CANONICAL_SOURCE' for x in result)
    return result

def transaction_canary(stage):
    """Exercise CAS refusal and conditional pair rollback on local dummy bytes."""
    local = stage / 'transaction_canary'; local.mkdir()
    a, b = local / 'selector.txt', local / 'backtest.txt'
    exclusive_bytes(a, b'old-selector\n'); exclusive_bytes(b, b'old-backtest\n')
    old_a, old_b = sha(a), sha(b)
    cas_bytes(a, old_a, b'new-selector\n', 'canary')
    assert a.read_bytes() == b'new-selector\n'
    refused = False
    try: cas_bytes(b, '0' * 64, b'new-backtest\n', 'canary')
    except AssertionError: refused = True
    assert refused and sha(b) == old_b
    cas_bytes(a, sha(a), b'old-selector\n', 'rollback')
    assert sha(a) == old_a and sha(b) == old_b
    foreign = b'concurrent-owner\n'; cas_bytes(a, old_a, foreign, 'foreign')
    refused = False
    try: cas_bytes(a, hashlib.sha256(b'new-selector\n').hexdigest(), b'old-selector\n', 'rollback')
    except AssertionError: refused = True
    assert refused and a.read_bytes() == foreign
    return {'successful_cas': True, 'second_pointer_refused_then_first_rolled_back': True,
            'foreign_owner_bytes_preserved': True, 'authority_writes': 0}

def original_selector_consumer(cfg):
    """Load only unchanged pure functions, avoiding the daily lane's imports."""
    namespace = {'Path': Path, 'datetime': datetime}
    for filename, name in ((cfg['consumer_date_source'], '_date'),
                           (cfg['consumer_source'], 'resolve_selector_panel')):
        parsed = ast.parse(Path(filename).read_text())
        node = next(x for x in parsed.body if isinstance(x, ast.FunctionDef) and x.name == name)
        unit = ast.Module(body=[node], type_ignores=[])
        exec(compile(ast.fix_missing_locations(unit), filename, 'exec'), namespace)
    return namespace['resolve_selector_panel'](Path(cfg['selector_data_root']), '20261021')

def prepare(cfg, stage):
    check_inputs(cfg)
    assert not active_writers(), 'Active original-chain writer; STOP without mutation'
    stage.mkdir(parents=True, mode=0o700, exist_ok=False)
    (stage / 'raw_backups').mkdir(); (stage / 'alignment12_ledgers').mkdir()
    canary = transaction_canary(stage)
    sources = json.loads(Path(cfg['source_plan_path']).read_text())['sources']
    records = []
    for item in sources:
        Path(item['path']).relative_to(Path(cfg['tdx_root']))
        assert sha(item['stock_checkpoint']['path']) == item['stock_checkpoint']['sha256'], 'Prior validation checkpoint drift'
        assert sha(item['path']) == item['old_sha256'], 'Canonical raw drift: ' + item['canonical_code']
        assert sha(item['replacement_path']) == item['new_sha256'], 'Reviewed native drift'
        old = Path(item['path']).read_bytes(); new = Path(item['replacement_path']).read_bytes()
        assert hashlib.sha256(old).hexdigest() == item['old_sha256']
        backup = stage / 'raw_backups' / (item['canonical_code'] + '.day')
        exclusive_bytes(backup, old)
        record = dict(item, backup_path=str(backup), backup_sha256=sha(backup), old_stat=stat(item['path']))
        if item['class'] == 'ACCEPTED_SOURCE_ALIGNMENT12':
            ledger = stage / 'alignment12_ledgers' / (item['canonical_code'] + '.json')
            rows = row_ledger(old, new)
            save(ledger, {'canonical_code': item['canonical_code'], 'class': item['class'],
                          'old_sha256': item['old_sha256'], 'new_sha256': item['new_sha256'],
                          'original_backup': str(backup), 'rows': rows,
                          'original_guard': 'REUSED_EXACT_BYTES_BULK_STOCK_CHECKPOINT',
                          'panel_input_checkpoint': item['stock_checkpoint']})
            record['alignment_ledger'] = {'path': str(ledger), 'sha256': sha(ledger)}
        records.append(record)
    for role, panel in cfg['panels'].items():
        exclusive_bytes(stage / (role + '_pointer_preimage.txt'), Path(panel['pointer_path']).read_bytes())
    # Preserve the old producer ledger; only this new execution's disposition
    # changes.  The unchanged constructor below recognises this exact tuple.
    csv.field_size_limit(64 * 1024 * 1024)
    with Path(cfg['old_results_csv']).open(newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f); fields = reader.fieldnames; rows = list(reader)
    plans = {x['path']: x for x in records}; seen = set()
    for row in rows:
        item = plans.get(row['path'])
        if not item: continue
        assert row['path'] not in seen; seen.add(row['path'])
        row.update(status='TRUSTED_CAS_CURRENT', fetch_status='TRUSTED_CAS_REUSE', classification='ACCEPTED',
                   quarantine='False', reason_code=item['class'], target_date_ready='True', last_date_after='20261021',
                   source_sha256_before=item['old_sha256'], source_sha256_after=item['new_sha256'],
                   run_id=E, field_violations='[]', retained_quarantine='False', error='')
    assert seen == set(plans)
    result_csv = stage / 'file_results.csv'
    with result_csv.open('x', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
        f.flush(); os.fsync(f.fileno())
    # Binding all accepted exact bytes allows the original constructor to reuse
    # prior validation rather than silently changing or rerunning its threshold.
    old_manifest = json.loads(Path(cfg['old_accepted_manifest']).read_text())
    proof = {x['path']: {'sha256': x['sha256'], 'validation_receipt': cfg['old_accepted_manifest']} for x in old_manifest['files']}
    for item in records:
        proof[item['path']] = {'sha256': item['new_sha256'], 'validation_receipt': item['stock_checkpoint'], 'class': item['class']}
    assert len(proof) == 5495
    save(stage / 'accepted_validation_proofs.json', proof)
    save(stage / 'PREPARE_RECEIPT.json', {'execution_id': E, 'status': 'PREPARED_NO_AUTHORITY_WRITES',
         'sources': records, 'source_restore_count': 354, 'accepted_source_alignment_count': 12,
         'accepted_count': 5495, 'excluded_count': 305,
         'prepared_csv': {'path': str(result_csv), 'sha256': sha(result_csv)},
         'proofs': {'path': str(stage / 'accepted_validation_proofs.json'), 'sha256': sha(stage / 'accepted_validation_proofs.json')},
         'transaction_canary': canary, 'active_writer_observation': [], 'authority_writes': 0, 'pointer_writes': 0})

def verify_publish_gate(gate, cfg, stage, activation):
    # Binding the unchanged original config also binds both panel destinations
    # and all native allowlisted paths; a prepared ledger alone cannot do this.
    assert gate['allow_publish'] is True and gate['execution_id'] == E
    original = Path(activation['original_contract']['path'])
    assert sha(original) == activation['original_contract']['sha256'], 'Original approved contract drift'
    assert cfg == json.loads(original.read_text()), 'Runtime config differs from original approved contract'
    assert sha(cfg['source_plan_path']) == activation['source_plan']['sha256'], 'Source plan drift'
    assert str(Path(cfg['source_plan_path']).resolve()) == str(Path(activation['source_plan']['path']).resolve())
    expected = {'activation_contract_sha256': sha(ACTIVATION_CONTRACT),
                'helper_sha256': sha(__file__), 'original_contract_sha256': sha(original),
                'source_plan_sha256': sha(cfg['source_plan_path']),
                'prepare_receipt_sha256': sha(stage / 'PREPARE_RECEIPT.json')}
    for key, value in expected.items(): assert gate[key] == value, 'Publish gate identity drift: ' + key
    assert activation['helper_sha256'] == sha(__file__), 'Activation helper drift'
    assert expected['prepare_receipt_sha256'] == activation['prepared_receipt']['sha256'], 'Prepared identity drift'
    for item in activation['input_bindings']: assert sha(item['path']) == item['sha256'], 'Activation input drift'
    review = gate['independent_review_receipt']
    assert sha(review['path']) == review['sha256'], 'Approved independent review receipt drift'

def publish(cfg, stage):
    # The controller supplies this frozen independently reviewed gate only after
    # PREPARE and batch admission.  A contract or Writer status is insufficient.
    activation = json.loads(Path(ACTIVATION_CONTRACT).read_text())
    gate = json.loads(Path(activation['publish_gate_path']).read_text())
    verify_publish_gate(gate, cfg, stage, activation)
    check_inputs(cfg)
    prepared = json.loads((stage / 'PREPARE_RECEIPT.json').read_text())
    assert sha(prepared['prepared_csv']['path']) == prepared['prepared_csv']['sha256']
    assert sha(prepared['proofs']['path']) == prepared['proofs']['sha256']
    lock = Path(cfg['lock_path'])
    lock.parent.mkdir(parents=True, exist_ok=True)
    journal_path = stage / 'TRANSACTION_JOURNAL.jsonl'
    raw_written, pointer_written = [], []
    def journal(event, **data):
        with journal_path.open('a') as f:
            f.write(json.dumps({'event': event, 'time_ns': time.time_ns(), **data}, ensure_ascii=False) + '\n')
            f.flush(); os.fsync(f.fileno())
    with lock.open('a+') as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            assert not active_writers(), 'Active original-chain writer; STOP'
            check_inputs(cfg)
            for item in prepared['sources']:
                assert sha(item['path']) == item['old_sha256']
                assert sha(item['replacement_path']) == item['new_sha256']
                assert sha(item['backup_path']) == item['old_sha256']
            journal('BEGIN', prepare_receipt_sha256=sha(stage / 'PREPARE_RECEIPT.json'), lock_scope=cfg['lock_scope'])
            # New versioned original-producer outputs; never overwrite prior
            # generations. Hard-link exact reviewed bytes, no new computation.
            for role, panel in cfg['panels'].items():
                dest = Path(panel['new_path']); dest.parent.mkdir(parents=True, exist_ok=False)
                os.link(panel['candidate_path'], dest); fsync_dir(dest.parent)
                assert stat(dest)['inode'] == panel['candidate_stat']['inode']
                journal('PANEL_TARGET_CREATED', role=role, path=str(dest), sha256=panel['new_sha256'])
            assert not active_writers(), 'Concurrent A writer appeared before source CAS'
            for item in prepared['sources']:
                journal('SOURCE_CAS_INTENT', path=item['path'], before=item['old_sha256'], after=item['new_sha256'], backup=item['backup_path'])
                raw_written.append(item)
                cas_bytes(item['path'], item['old_sha256'], Path(item['replacement_path']).read_bytes(), E)
                journal('SOURCE_CAS_COMPLETE', path=item['path'], source_class=item['class'])
            # Original owner, same schema, accepted-only content-addressed tree.
            sys.path.insert(0, cfg['original_app_root'])
            authority = importlib.import_module('ops.macos_research_panel_daily_authority')
            run_dir = Path(cfg['new_source_run_dir']); run_dir.mkdir(parents=True, exist_ok=False)
            exclusive_bytes(run_dir / 'file_results.csv', Path(prepared['prepared_csv']['path']).read_bytes())
            proof = json.loads(Path(prepared['proofs']['path']).read_text())
            def receipt_bound_history(source, target):
                assert target == 20261021
                bound = proof.get(str(source)); assert bound is not None, 'No prior exact-byte validation receipt'
                assert sha(source) == bound['sha256'], 'Previously validated bytes drifted'
                return [], None
            with Path(prepared['prepared_csv']['path']).open(newline='', encoding='utf-8') as f:
                targets = [Path(row['path']) for row in csv.DictReader(f)]
            snapshot = authority._accepted_formula_input_root(Path(cfg['tdx_root']), 20261021,
                Path(cfg['receipt_root']), run_dir, target_files=targets, authority_status='REBUILD_REQUIRED',
                _history_status=receipt_bound_history)
            assert snapshot['accepted_target_date_file_count'] == 5495 and snapshot['excluded_rebuild_candidate_count'] == 305
            journal('ORIGINAL_OWNER_SNAPSHOT_COMPLETE', **snapshot)
            assert not active_writers(), 'Concurrent A writer appeared before pointer CAS'
            for panel in cfg['panels'].values(): assert sha(panel['pointer_path']) == panel['old_pointer_sha256']
            for role, panel in cfg['panels'].items():
                new_bytes = (panel['new_path'] + '\n').encode('utf-8')
                journal('POINTER_CAS_INTENT', role=role, path=panel['pointer_path'], old_sha256=panel['old_pointer_sha256'], new_sha256=hashlib.sha256(new_bytes).hexdigest())
                pointer_written.append((role, panel, hashlib.sha256(new_bytes).hexdigest()))
                cas_bytes(panel['pointer_path'], panel['old_pointer_sha256'], new_bytes, E)
                journal('POINTER_CAS_COMPLETE', role=role)
            for item in prepared['sources']: assert sha(item['path']) == item['new_sha256']
            for role, panel, digest in pointer_written:
                assert sha(panel['pointer_path']) == digest
                assert Path(panel['pointer_path']).read_text().strip() == panel['new_path']
                assert stat(panel['new_path'])['size'] == panel['candidate_stat']['size']
            # Invoke the actual r1 legacy selector consumer, not the unrelated
            # V4 selection ledger or the unused September native pointer.
            selected = original_selector_consumer(cfg)
            assert str(selected) == cfg['panels']['legacy_selector']['new_path']
            result = {'execution_id': E, 'status': 'ORIGINAL_CHAIN_PUBLISHED_AND_CONSUMER_READBACK',
                'source_restore_count': 354, 'accepted_source_alignment_count': 12, 'physical_source_cas_count': len(raw_written),
                'accepted_target_date_count': 5495, 'excluded_target_count': 305, 'snapshot': snapshot,
                'selector_consumer_path': str(selected), 'roles': cfg['panels'],
                'provenance': {'panel_sha256': cfg['panels']['legacy_selector']['new_sha256']},
                'selector_output': cfg['panels']['legacy_selector']['new_path'],
                'full_schema_ready': False, 'existing_schema_policy': 'PREEXISTING_FAIL_NOT_CHANGED',
                'runtime_reload': False, 'scheduler_changed': False, 'network_calls': 0,
                'research_only': True, 'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}
            save(stage / 'PUBLISH_RECEIPT.json', result); journal('COMMIT', receipt_sha256=sha(stage / 'PUBLISH_RECEIPT.json'))
        except BaseException as exc:
            # Logging is best effort during rollback. A full/read-only/failing
            # journal must never prevent attempts to restore every owned path.
            log_failures = []
            def rollback_journal(event, **data):
                try: journal(event, **data)
                except BaseException as error:
                    log_failures.append({'event': event, 'error_type': type(error).__name__, 'error': str(error)})
            rollback_journal('FAILURE', error_type=type(exc).__name__, error=str(exc))
            conflicts = []
            for role, panel, digest in reversed(pointer_written):
                try:
                    if sha(panel['pointer_path']) != panel['old_pointer_sha256']:
                        cas_bytes(panel['pointer_path'], digest, (stage / (role + '_pointer_preimage.txt')).read_bytes(), E + '.rollback')
                except BaseException as error: conflicts.append({'path': panel['pointer_path'], 'error': str(error)})
                else: rollback_journal('POINTER_ROLLBACK_COMPLETE', role=role)
            for item in reversed(raw_written):
                try:
                    if sha(item['path']) != item['old_sha256']:
                        cas_bytes(item['path'], item['new_sha256'], Path(item['backup_path']).read_bytes(), E + '.rollback')
                except BaseException as error: conflicts.append({'path': item['path'], 'error': str(error)})
                else: rollback_journal('SOURCE_ROLLBACK_COMPLETE', path=item['path'])
            failure = {'execution_id': E, 'status': 'FAILED_ROLLBACK_CONFLICT' if conflicts else 'FAILED_ROLLED_BACK',
                 'error_type': type(exc).__name__, 'error': str(exc), 'rollback_conflicts': conflicts,
                 'rollback_journal_failures': log_failures,
                 'raw_cas_completed_before_failure': len(raw_written), 'pointer_cas_completed_before_failure': len(pointer_written)}
            try: save(stage / 'PUBLISH_FAILURE_RECEIPT.json', failure)
            except BaseException as reporting_error:
                # Reporting may fail on the same device, after rollback has
                # already been attempted for every tracked source/pointer.
                print(json.dumps({'rollback_report_write_error': str(reporting_error), **failure}), file=sys.stderr)
            raise
        finally: fcntl.flock(held.fileno(), fcntl.LOCK_UN)

def main():
    parser = argparse.ArgumentParser(); parser.add_argument('phase', choices=('canary', 'publish')); args = parser.parse_args()
    activation = json.loads(Path(ACTIVATION_CONTRACT).read_text())
    assert sha(__file__) == activation['helper_sha256']
    for item in activation['input_bindings']: assert sha(item['path']) == item['sha256']
    csv.field_size_limit(64 * 1024 * 1024)
    start = json.loads(Path(activation['registry_start_path']).read_text())
    assert start['execution_id'] == E and start['event_type'] == 'RUN_STARTED'
    if args.phase == 'canary':
        test_path = Path(activation['test_path'])
        spec = __import__('importlib.util', fromlist=['spec_from_file_location']).spec_from_file_location('publish_fault_canary', test_path)
        module = __import__('importlib.util', fromlist=['module_from_spec']).module_from_spec(spec)
        spec.loader.exec_module(module)
        module.run(sys.modules[__name__], activation)
    else:
        cfg = json.loads(Path(activation['original_contract']['path']).read_text())
        publish(cfg, Path(cfg['stage']))
    print(json.dumps({'execution_id': E, 'phase': args.phase, 'status': 'COMPLETE'}))

if __name__ == '__main__': main()
