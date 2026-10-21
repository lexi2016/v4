"""Bounded archive/cache native candidates. Writes only unique research staging.

Each technical target is independent. Missing/ambiguous inputs are unresolved,
never filled. Completed checkpoints are immutable and are reused on continuation.
"""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
import argparse, base64, concurrent.futures, datetime as dt, fcntl, hashlib, threading
import ipaddress, json, os, pty, re, resource, select, struct, subprocess, time, zipfile

R = Path(__file__).resolve().parents[1]
WT = Path('/Users/lexi/Desktop/学习/因子工厂/worktrees/a_share_quarantine_recovery_20261021')
E = 'A_SHARE_QUARANTINE_SOURCE_CANDIDATE_BATCH_20261021_R2_01'
NETWORK_STOP = threading.Event()
FIELDS = ['date', 'open', 'high', 'low', 'close', 'amount_bits', 'volume_raw', 'reserved']

def digest(b):
    return hashlib.sha256(b).hexdigest()

def sha(p):
    return digest(Path(p).read_bytes())

def save(p, value):
    p = Path(p)
    with p.open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n'); f.flush(); os.fsync(f.fileno())

def write(p, b):
    with Path(p).open('xb') as f:
        f.write(b); f.flush(); os.fsync(f.fileno())

def stat(p):
    s = Path(p).stat()
    return {'inode': s.st_ino, 'mtime_ns': s.st_mtime_ns, 'size': s.st_size}

def decode(b):
    assert b and len(b) % 32 == 0, 'EMPTY_OR_TRUNCATED_NATIVE'
    out = {}; previous = None
    for off in range(0, len(b), 32):
        raw = b[off:off + 32]; words = struct.unpack('<8I', raw); d = words[0]
        dt.datetime.strptime(str(d), '%Y%m%d')
        assert previous is None or previous < d, 'DUPLICATE_OR_UNORDERED_DATE'
        out[d] = {'raw': raw, 'words': words, 'row_index': off // 32, 'row_sha256': digest(raw)}
        previous = d
    return out

def windows_tail(target, stage, host):
    if target.get('saved_windows_tail'):
        x = target['saved_windows_tail']; b = Path(x['path']).read_bytes()
        assert digest(b) == x['sha256']
        return b, {'reuse': x, 'remote_read_performed': False}
    market = target['canonical_code'].split('.')[1].lower(); symbol = target['native_symbol']
    assert re.fullmatch('[0-9]{6}', symbol) and market in ('sh', 'sz', 'bj')
    path = 'C:\\new_tdx_mock\\vipdoc\\' + market + '\\lday\\' + market + symbol + '.day'
    assert not NETWORK_STOP.is_set(), 'HOST_IDENTITY_FAILURE_STOP_ALL_NETWORK'
    assert host, 'CURRENT_MDNS_UNRESOLVED_NO_NETWORK_READ'
    template = (R / 'helpers/windows002225_read.ps1').read_text()
    ps = template.replace('C:\\new_tdx_mock\\vipdoc\\sz\\lday\\sz002225.day', path)
    assert ps != template or symbol == '002225'
    encoded = base64.b64encode(ps.encode('utf-16le')).decode()
    command = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o',
               'ConnectTimeout=5', '-o', 'HostName=' + host, '-o', 'HostKeyAlias=169.254.203.121',
               '-o', 'UserKnownHostsFile=/Users/lexi/.ssh/known_hosts', 'windows-wifi',
               'powershell', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded]
    try:
        run = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=30)
    except subprocess.TimeoutExpired as exc:
        NETWORK_STOP.set()
        save(stage / 'WINDOWS_TRANSPORT.json', {'host': host, 'path': path, 'error': 'SSH_TIMEOUT_NO_RETRY', 'timeout_seconds': 30, 'stdout': str(exc.stdout), 'stderr': str(exc.stderr)})
        raise
    transport = {'host': host, 'path': path, 'returncode': run.returncode,
                 'stdout': run.stdout, 'stderr': run.stderr, 'strict_host_key_checking': True,
                 'host_key_alias': '169.254.203.121', 'script_sha256': digest(ps.encode())}
    save(stage / 'WINDOWS_TRANSPORT.json', transport)
    if run.returncode == 255 or 'HOST IDENTIFICATION HAS CHANGED' in run.stderr or 'Host key verification failed' in run.stderr:
        NETWORK_STOP.set()
    assert run.returncode == 0, 'WINDOWS_CACHE_READ_UNAVAILABLE_NO_RETRY'
    j = json.loads(run.stdout.lstrip('\ufeff'))
    assert j['path'] == path and j['before_length'] == j['after_length']
    assert j['before_mtime_ticks'] == j['after_mtime_ticks']
    assert j['before_sha256'] == j['read_sha256'] == j['after_sha256'], 'WINDOWS_SOURCE_CHANGED'
    b = base64.b64decode(j['tail_base64'], validate=True)
    assert j['tail_offset'] % 32 == 0 and j['tail_offset'] + len(b) == j['before_length']
    write(stage / 'windows_cache_tail.day', b)
    return b, {k: v for k, v in j.items() if k != 'tail_base64'}

def process(target, cfg, host, producer):
    code = target['canonical_code']; checkpoint = R / 'source_candidate_batch' / E / code
    checkpoint.mkdir(mode=0o700, exist_ok=False)
    began = time.monotonic()
    result = {'canonical_code': code, 'reported_primary_reason': target['reported_reason'],
              'status': 'UNRESOLVED', 'canonical_source_writes': 0, 'panel_writes': 0, 'pointer_writes': 0}
    try:
        if target.get('reuse_candidate'):
            for x in target['reuse_candidate']['bindings']:
                assert sha(x['path']) == x['sha256']
            result.update(status='REUSED_INDEPENDENTLY_ACCEPTED_SOURCE_CANDIDATE', reuse=target['reuse_candidate'])
        else:
            source = Path(target['native_path']); before = stat(source); original = source.read_bytes()
            assert stat(source) == before, 'NATIVE_SOURCE_CHANGED_DURING_SNAPSHOT'
            original_sha = digest(original)
            write(checkpoint / 'original_native_backup.day', original)
            result.update(original_sha256=original_sha, original_stat=before)
            assert original_sha == target['reported_source_sha256'], 'ORIGINAL_SOURCE_DRIFT_FROM_FROZEN_CENSUS'
            orig = decode(original)
            member = target.get('archive_member')
            assert member is not None, 'EXACT_ARCHIVE_MEMBER_MISSING_NO_ALIAS_INFERENCE'
            if target.get('saved_archive_member'):
                a = target['saved_archive_member']; archived = Path(a['path']).read_bytes()
                assert digest(archived) == a['sha256'] == member['uncompressed_member_sha256']
            else:
                assert stat(cfg['archive_path']) == cfg['archive_stat'], 'ARCHIVE_STAT_DRIFT'
                with zipfile.ZipFile(cfg['archive_path']) as z:
                    archived = z.read(member['member_name'])  # selected member CRC checked by zipfile
                assert stat(cfg['archive_path']) == cfg['archive_stat'], 'ARCHIVE_CHANGED_DURING_READ'
                assert digest(archived) == member['uncompressed_member_sha256'], 'MEMBER_SHA_DRIFT'
            write(checkpoint / 'archive_member.day', archived)
            archive = decode(archived); first = min(orig)
            assert min(archive) <= first <= max(archive), 'ARCHIVE_DOES_NOT_COVER_ORIGINAL_START'
            canonical = {d: dict(v, source='ARCHIVE_NATIVE', file_sha256=digest(archived))
                         for d, v in archive.items() if first <= d <= cfg['target_date']}
            remote_bytes, remote = windows_tail(target, checkpoint, host)
            window = decode(remote_bytes)
            overlap = sorted(set(archive) & set(window)); assert len(overlap) >= 2, 'INSUFFICIENT_CACHE_ARCHIVE_OVERLAP'
            parity = []
            for d in overlap:
                aw = archive[d]['words']; ww = window[d]['words']
                changes = [i for i in range(8) if aw[i] != ww[i]]
                if changes:
                    parity.append({'date': d, 'field_indices': changes, 'archive_row_sha256': archive[d]['row_sha256'],
                                   'windows_row_sha256': window[d]['row_sha256']})
            # Empirical OHLC and amount bits compatibility, with all volume/reserved differences recorded.
            assert not any(set(x['field_indices']) & {1, 2, 3, 4, 5} for x in parity), 'CACHE_ARCHIVE_PRICE_AMOUNT_CONFLICT'
            latest = max(canonical)
            for d, row in window.items():
                if latest < d <= cfg['target_date']:
                    canonical[d] = dict(row, source='WINDOWS_EXISTING_NATIVE_TAIL', file_sha256=digest(remote_bytes))
            save(checkpoint / 'SOURCE_BINDINGS.json', {'native_source_path': str(source), 'original_sha256': original_sha,
                 'archive_member': member, 'archive_member_sha256': digest(archived), 'windows': remote,
                 'overlap_count': len(overlap), 'all_eight_word_differences': parity,
                 'absolute_adjustment_status': 'CANNOT_CONFIRM; observed price/amount parity only'})
            ledger = []; excluded = []
            for d in sorted(set(orig) | set(canonical)):
                a = orig.get(d); b = canonical.get(d)
                disposition = ('INSERTED' if a is None else 'QUARANTINED_ORIGINAL_NOT_IN_CANONICAL_SOURCE'
                               if b is None else 'RETAINED_BYTE_IDENTICAL' if a['raw'] == b['raw'] else 'REPLACED_WITH_VERIFIED_NATIVE')
                ledger.append({'date': d, 'disposition': disposition,
                    'original_row_index': a['row_index'] if a else None,
                    'original_row_sha256': a['row_sha256'] if a else None,
                    'original_words': list(a['words']) if a else None,
                    'candidate_row_sha256': b['row_sha256'] if b else None,
                    'candidate_words': list(b['words']) if b else None,
                    'source': b['source'] if b else None, 'source_file_sha256': b['file_sha256'] if b else None,
                    'source_row_index': b['row_index'] if b else None,
                    'field_changes': [FIELDS[i] for i in range(8) if a['words'][i] != b['words'][i]] if a and b else None,
                    'excluded_original_semantics': 'CANNOT_CONFIRM; original32B preserved, no halt/bad-value claim' if b is None else None})
                if b is None: excluded.append(a['raw'])
            save(checkpoint / 'ROW_DISPOSITION.json', ledger)
            write(checkpoint / 'quarantined_original_records.day', b''.join(excluded))
            assembled = checkpoint / 'assembled_input.day'
            write(assembled, b''.join(canonical[d]['raw'] for d in sorted(canonical)))
            candidate = checkpoint / ('candidate_' + code + '.day')
            build = producer.build_rebuild_candidate(assembled, [], candidate, expected_source_sha256=sha(assembled),
                        expected_replacement_sha256={}, expected_replacement_dates=[])
            assert sha(candidate) == sha(assembled)
            bars, reason = producer._local_history_status(candidate, cfg['target_date'])
            violations = producer._local_field_signature_violations(candidate, symbol=target['native_symbol'],
                         market=int(target['protocol_market']), run_id=E, recorded_at=dt.datetime.now(dt.timezone.utc).isoformat())
            counts = {k: sum(x['disposition'] == k for x in ledger) for k in
                ('INSERTED', 'QUARANTINED_ORIGINAL_NOT_IN_CANONICAL_SOURCE', 'RETAINED_BYTE_IDENTICAL', 'REPLACED_WITH_VERIFIED_NATIVE')}
            assert len(orig) == counts['QUARANTINED_ORIGINAL_NOT_IN_CANONICAL_SOURCE'] + counts['RETAINED_BYTE_IDENTICAL'] + counts['REPLACED_WITH_VERIFIED_NATIVE']
            assert len(canonical) == counts['INSERTED'] + counts['RETAINED_BYTE_IDENTICAL'] + counts['REPLACED_WITH_VERIFIED_NATIVE']
            assert sha(checkpoint / 'original_native_backup.day') == original_sha
            result.update(candidate_path=str(candidate), candidate_sha256=sha(candidate), original_first_date=first,
                          candidate_last_date=max(canonical), original_rows=len(orig), candidate_rows=len(canonical),
                          disposition_counts=counts, original_validator_reason=reason,
                          signature_violations=violations, cross_ratio_limit=producer.MAX_CROSS_DAY_CLOSE_RATIO, builder_receipt=build)
            result['status'] = ('STAGING_CANDIDATE_ORIGINAL_GUARDS_ACCEPTED' if reason is None and not violations and max(canonical) == cfg['target_date']
                                else 'STAGING_PRESERVED_NOT_ACCEPTED_OR_NO_TARGET_BAR')
    except Exception as exc:
        result.update(error_type=type(exc).__name__, error=repr(exc))
    result['elapsed_seconds'] = time.monotonic() - began
    result['artifacts'] = [{'path': str(p), 'sha256': sha(p)} for p in sorted(checkpoint.iterdir()) if p.is_file()]
    save(checkpoint / 'CHECKPOINT.json', result)
    return result

def main():
    parser = argparse.ArgumentParser(); parser.add_argument('phase', choices=('canary', 'ramp2', 'remaining'))
    args = parser.parse_args(); cfg = json.loads((R / 'SOURCE_CANDIDATE_BATCH_R2_CONTRACT.json').read_text())
    gate = (R / 'registry_receipts/SOURCE_CANDIDATE_BATCH_R2_REGISTRY_START.json').read_text()
    assert E in gate and 'RUN_STARTED' in gate
    for x in cfg['input_bindings']: assert sha(x['path']) == x['sha256'], 'FROZEN_INPUT_DRIFT'
    lock = (R / 'SOURCE_CANDIDATE_BATCH_R2.lock').open('a'); fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    root = R / 'source_candidate_batch' / E; root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.phase != 'canary':
        previous = 'canary' if args.phase == 'ramp2' else 'ramp2'
        receipt = json.loads((root / (previous + '_RECEIPT.json')).read_text())
        assert receipt['safe_to_continue'], 'RESOURCE_OR_INFRASTRUCTURE_STOP'
    assert not (root / (args.phase + '_RECEIPT.json')).exists(), 'PHASE_ALREADY_COMPLETED_DO_NOT_REPEAT'
    sys.path.insert(0, str(WT)); from ops import a_share_daily_sync as producer
    inventory = json.loads((R / 'SOURCE_CANDIDATE_BATCH_TARGETS.json').read_text())
    phase = cfg['phases'][args.phase]; targets = [t for t in inventory['targets'] if t['canonical_code'] in phase['codes']] if phase['codes'] else [t for t in inventory['targets'] if not (root / t['canonical_code'] / 'CHECKPOINT.json').exists()]
    needs_host = any(not t.get('reuse_candidate') and t.get('archive_member') and not t.get('saved_windows_tail') for t in targets)
    host = None
    if needs_host:
        master, slave = pty.openpty()
        resolver = subprocess.Popen(['dns-sd', '-G', 'v4', 'huang1992.local'], stdout=slave, stderr=slave, close_fds=True)
        os.close(slave); captured = bytearray(); deadline = time.monotonic() + 5
        try:
            while time.monotonic() < deadline:
                if select.select([master], [], [], max(0, deadline - time.monotonic()))[0]:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    if not chunk: break
                    captured.extend(chunk)
                    if re.search(rb'Add\s+\d+\s+\d+\s+huang1992\.local\.?\s+[0-9.]+', captured, re.I): break
                if resolver.poll() is not None: break
        finally:
            resolver_deadline_reached = time.monotonic() >= deadline
            if resolver.poll() is None: resolver.terminate()  # only our short resolver, never an existing service
            resolver.wait(timeout=3); os.close(master)
        dnsout = captured.decode('utf-8', errors='replace'); dnserr = 'stderr combined in PTY transcript'
        addresses = re.findall(r'Add\s+\d+\s+\d+\s+huang1992\.local\.?\s+([0-9.]+)', dnsout, re.I)
        addresses = [x for x in addresses if ipaddress.ip_address(x).version == 4]
        host = addresses[0] if addresses else None
        address_source = 'CURRENT_MDNS' if host else 'RECENT_SAME_HOST_SUCCESS_RECEIPT'
        if host is None:
            recent = json.loads((R / 'WINDOWS_CACHE_TAIL002225_TRANSPORT.json').read_text())
            assert recent['returncode'] == 0 and recent['strict_host_key_checking'] and recent['hostkeyalias'] == '169.254.203.121'
            host = recent['hostname']; assert ipaddress.ip_address(host).version == 4
        save(root / (args.phase + '_DNS.json'), {'command': ['dns-sd', '-G', 'v4', 'huang1992.local'], 'stdout': dnsout, 'stderr': dnserr, 'returncode': resolver.returncode, 'deadline_reached': resolver_deadline_reached, 'selected_ipv4': host, 'address_source': address_source, 'source_receipt_sha256': sha(R / 'WINDOWS_CACHE_TAIL002225_TRANSPORT.json') if address_source != 'CURRENT_MDNS' else None, 'scan': False})
    else:
        save(root / (args.phase + '_DNS.json'), {'needed': False, 'reason': 'Saved immutable cache/archive witnesses only; no resolver started'})
    began = time.monotonic(); usage_before = resource.getrusage(resource.RUSAGE_SELF)
    with concurrent.futures.ThreadPoolExecutor(max_workers=phase['workers']) as pool:
        results = list(pool.map(lambda t: process(t, cfg, host, producer), targets))
    usage_after = resource.getrusage(resource.RUSAGE_SELF)
    infra = [x['canonical_code'] for x in results if any(k in x.get('error', '') for k in ('SOURCE_CHANGED', 'SHA_DRIFT', 'FROZEN_', 'SOURCE_DRIFT'))]
    receipt = {'execution_id': E, 'phase': args.phase, 'workers': phase['workers'], 'actual_targets': len(results),
          'elapsed_seconds': time.monotonic() - began, 'process_peak_rss_bytes': usage_after.ru_maxrss,
          'block_input_delta': usage_after.ru_inblock - usage_before.ru_inblock,
          'block_output_delta': usage_after.ru_oublock - usage_before.ru_oublock,
          'status_counts': {s: sum(x['status'] == s for x in results) for s in sorted({x['status'] for x in results})},
          'infrastructure_drift_targets': infra,
          'safe_to_continue': not infra and not NETWORK_STOP.is_set() and (not needs_host or bool(host)) and usage_after.ru_maxrss < cfg['max_process_rss_bytes'],
          'checkpoints': [{'path': str(root / x['canonical_code'] / 'CHECKPOINT.json'), 'sha256': sha(root / x['canonical_code'] / 'CHECKPOINT.json')} for x in results],
          'source_writes': 0, 'panel_writes': 0, 'pointer_writes': 0, 'sdk_quote_fetches': 0,
          'independent_review': 'PENDING; staged candidate, not authority restore'}
    save(root / (args.phase + '_RECEIPT.json'), receipt)
    print(json.dumps({k: v for k, v in receipt.items() if k != 'checkpoints'}))
    if not receipt['safe_to_continue']: raise SystemExit(2)

if __name__ == '__main__':
    main()
