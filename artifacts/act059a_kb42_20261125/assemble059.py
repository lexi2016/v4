"""Assemble the ACT-059A research-only delivery from the three reviewed modules."""
import csv
import hashlib
import io
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / 'evidence'
OUT = ROOT / 'delivery'
NAMES = ('ACT059A_REPORT.md', 'ACT059A_KB42_METRIC_AND_CONTROL_STATS.csv',
         'ACT059A_108_WAVES_SUPPLEMENT.csv', 'ACT059A_14CASE_LIGHT_PACK.zip')
RECEIPT = 'ACT059A_0FIT_RECEIPT.json'
HARD_BYTES = 9_500_000
GOVERNANCE = dict(RESEARCH_ONLY=True, STRICT_PIT=0, TRAIN_ADMITTED=0, NO_GO_BLOCKED=True,
                  production_allowed=False, orders_sent=False, buy_gate_updated=False,
                  knowledge_base_training_complete=False, cross_project_read_only=True,
                  FIT=0, model_load=0, predict=0, tune=0, simulate=0, order=0,
                  cumulative_research_FIT=291, frozen_flagship='DUAL_5_5_E4B_E4C')


def identity(path):
    with path.open('rb') as f:
        digest = hashlib.file_digest(f, 'sha256').hexdigest()
    return {'name': path.name, 'bytes': path.stat().st_size, 'sha256': digest}


def put_json(path, value):
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')


def join_stats(replace_sha=None):
    started = time.perf_counter()
    rows, columns, sections = [], ['section'], {}
    for file in ('metric_stats.csv', 'wave_control_stats.csv'):
        with (EVIDENCE / file).open(encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames and 'section' in reader.fieldnames
            columns.extend(k for k in reader.fieldnames if k not in columns)
            for row in reader:
                assert None not in row and row['section']
                rows.append(row)
                sections[row['section']] = sections.get(row['section'], 0) + 1
    regular, pair = set(), set()
    for row in rows:
        active = pair if row['section'] == 'wave_matched_pair' else regular
        active.update(k for k, v in row.items() if v)
    pair_columns = {'event_id', 'event_D', 'event_D_ordinal', 'event_group', 'control_id', 'control_D',
                    'control_D_ordinal', 'control_distance_sessions', 'control_signed_distance_sessions',
                    'matching_status', 'event_frozen_forward_status', 'control_frozen_forward_status',
                    'control_frozen_forward_families'}
    pair_columns.update(k for k in pair if ('close_ret_D5' in k or 'min_low_D1_D5' in k)
                        and not k.endswith('_reason'))
    nested = [k for k in columns if k in pair - regular - pair_columns]
    assert nested and 'pair_context_json' not in columns
    columns = [k for k in columns if k in (regular | pair) - set(nested)] + ['pair_context_json']
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator='\n')
    packed = lambda value: json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    writer.writeheader()
    schema_name = 'wave_matched_pair_context_schema'
    writer.writerow({'section': schema_name, 'pair_context_json': packed(nested)})
    for row in rows:
        out = {k: row[k] for k in columns if k in row}
        if row['section'] == 'wave_matched_pair':
            out['pair_context_json'] = packed([row.get(key, '') for key in nested])
        writer.writerow(out)
    payload = buffer.getvalue().encode('utf-8-sig')
    assert len(payload) <= 2_000_000
    check = list(csv.DictReader(io.StringIO(payload.decode('utf-8-sig'))))
    assert check[0]['section'] == schema_name and json.loads(check[0]['pair_context_json']) == nested
    for out, original in zip(check[1:], rows, strict=True):
        given = out.pop('pair_context_json')
        if out['section'] == 'wave_matched_pair':
            out.update(zip(nested, json.loads(given), strict=True))
        assert all(out.get(k, '') == (v or '') for k, v in original.items())
    target = OUT / NAMES[1]
    if replace_sha is None:
        with target.open('xb') as f:
            f.write(payload)
    else:
        assert identity(target)['sha256'] == replace_sha
        target.write_bytes(payload)
    sections[schema_name] = 1
    print(json.dumps({'manifest': identity(target), 'row_count': len(rows) + 1, 'sections': sections,
                      'seconds': time.perf_counter() - started}, ensure_ascii=False))


def no_temp():
    assert not (ROOT / 'scratch').exists()
    assert not any(p.is_file() and p.suffix in {'.pyc', '.tmp', '.part', '.partial'} for p in ROOT.rglob('*'))


def check_uploads(remote, names):
    assert {r['name'] for r in remote} == set(names) and len(remote) == len({r['id'] for r in remote})
    verified = []
    for row in remote:
        content = identity(OUT / row['name'])
        assert 0 < content['bytes'] == row['bytes'] <= HARD_BYTES
        assert row['sha256'] == content['sha256'] and row['metadata_verified']
        verified.append(content | {'id': row['id'], 'url': row['url'], 'metadata_verified': True})
    return verified


def seal(params):
    assert {p.name for p in OUT.iterdir()} == set(NAMES)
    assert params['review']['status'] == 'PASS'
    verified = check_uploads(params['uploaded_payloads'], NAMES)
    no_temp()
    receipts = {}
    for stage in ('metric', 'wave', 'case'):
        p = EVIDENCE / f'{stage}_receipt.json'
        receipts[stage] = {'manifest': identity(p), 'evidence': json.loads(p.read_text())}
    result = {
        'action': 'ACT-059A', 'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'governance': GOVERNANCE, 'work_status': 'READY_FOR_CHAT_ACCEPTANCE',
        'accepted_upstream': {'ACT-057-LOCAL': 'ACCEPTED_0FIT', 'ACT-058A': 'ACCEPTED_0FIT_WITH_2_OPEN_METRICS'},
        'master_source_files': json.loads((ROOT / 'inputs/source_manifest.json').read_text()),
        'input_output_evidence': receipts, 'scope': params['scope'], 'phases': params['phases'],
        'independent_review': params['review'], 'visual_check': params['visual_check'],
        'cleanup': params['cleanup'], 'source_sync': params['source_sync'],
        'return_directory': params['folder'], 'outputs': verified,
        'receipt_self_sha256': 'The final delivery witness records this receipt hash, bytes and Drive link.',
    }
    put_json(OUT / RECEIPT, result)
    local = identity(OUT / RECEIPT)
    assert 0 < local['bytes'] <= HARD_BYTES
    print(json.dumps({'outputs': verified, 'receipt': local}, ensure_ascii=False))


def final(params):
    assert {p.name for p in OUT.iterdir()} == set(NAMES) | {RECEIPT}
    verified = check_uploads(params['outputs'], (*NAMES, RECEIPT))
    no_temp()
    params['outputs'] = verified
    put_json(ROOT / 'ACT059A_FINAL_DELIVERY_VERIFIED.json', params)
    print(json.dumps({'files': len(verified), 'bytes': sum(r['bytes'] for r in verified),
                      'phases': params['phases']}, ensure_ascii=False))


if __name__ == '__main__':
    command = sys.argv[1]
    if command == 'stats':
        join_stats(sys.argv[2] if len(sys.argv) == 3 else None)
    elif command == 'seal':
        seal(json.load(sys.stdin))
    elif command == 'final':
        final(json.load(sys.stdin))
    else:
        raise SystemExit('Expected stats, seal or final')
