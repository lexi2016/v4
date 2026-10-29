"""Mechanical output verification only; no engine, pricing or rendering calls."""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import base64
import gzip
import hashlib
import json
import multiprocessing
import re
import struct
import sys
import time
import zlib

OUT = Path(sys.argv[1]).resolve()
CONTEXT = None


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def checked(ref):
    raw = Path(ref['path']).read_bytes()
    assert sha(raw) == ref['sha256'], ('SHA_DRIFT', ref['path'])
    return raw


def png_check(path):
    raw = Path(path).read_bytes()
    assert raw[:8] == b'\x89PNG\r\n\x1a\n'
    offset, data, dimensions = 8, [], None
    while offset < len(raw):
        length = struct.unpack('>I', raw[offset:offset + 4])[0]
        kind = raw[offset + 4:offset + 8]
        body = raw[offset + 8:offset + 8 + length]
        crc = struct.unpack('>I', raw[offset + 8 + length:offset + 12 + length])[0]
        assert zlib.crc32(kind + body) & 0xffffffff == crc, 'PNG_CRC'
        if kind == b'IHDR':
            w, h, depth, color, _, _, _ = struct.unpack('>IIBBBBB', body)
            assert depth == 8 and color in (2, 6)
            dimensions = [w, h]
        if kind == b'IDAT':
            data.append(body)
        offset += length + 12
        if kind == b'IEND':
            assert offset == len(raw)
            break
    pixels = zlib.decompress(b''.join(data))
    assert len(pixels) == dimensions[1] * (1 + dimensions[0] * (3 if color == 2 else 4))
    return {'path': str(path), 'sha256': sha(raw), 'bytes': len(raw), 'pixels': dimensions, 'PNG_CRC_AND_DEFLATE': 'PASS'}


def verify(symbol):
    manifest, items, frozen, render, old_result, canary = CONTEXT
    item = manifest['samples'][symbol]
    packed = checked(item['projection'])
    raw = gzip.decompress(packed) if item['projection']['path'].endswith('.gz') else packed
    projection = json.loads(raw)
    html_raw = checked(item['html'])
    html = html_raw.decode()
    assert projection['symbol'] == symbol and projection['data_date'] == '20261029'
    assert projection['RESEARCH_ONLY'] is True and all(projection[k] is False for k in ('production_allowed', 'buy_gate_updated', 'orders_sent'))
    assert projection['source_cache'] == items[symbol]['source_cache'] and projection['product_row_ref'] == items[symbol]['product_row_ref']
    assert projection['source']['generation_id'] == items[symbol]['generation_id']
    assert projection['source']['source_input_sha256'] == items[symbol]['source_input_sha256']
    for key in ('formula', 'engine', 'product', 'manifest', 'config', 'renderer'):
        assert projection['lineage'][key] == frozen[key]
    formula = projection['formula_result']
    assert formula['formula_sha256'] == items[symbol]['formula_source_sha256'] and formula['mode'] == 'prefix'
    assert formula['rows'][-1]['trade_date'] == 20261029 and len(formula['rows']) == item['rows'] == items[symbol]['source_cache']['rows']
    assert formula['field_count'] == 51 and formula['drawing_count'] == 22 and not projection['unsupported_drawings']
    old = item.get('status') == 'REUSED_INDEPENDENT_PASS'
    if old:
        png_path = old_result['samples'][symbol]['screenshot']['path']
        status = 'REUSED_OLD3_INDEPENDENT_PASS_SHA_VERIFIED'
        per_row = 'REUSED_MATCHING_INDEPENDENT_PASS'
    else:
        names = {entry['name'] for entry in projection['inventory']['assignments']}
        definitions = projection['inventory']['drawings']
        for row in formula['rows']:
            assert set(row['values']) == names and len(names) == 51 and len(row['drawings']) == 22
            for drawing, definition in zip(row['drawings'], definitions):
                assert all(drawing[k] == definition[k] for k in ('id', 'kind', 'styles'))
        encoded = re.search(r"const projectionGzip='([^']+)'", html).group(1)
        payload = json.loads(gzip.decompress(base64.b64decode(encoded)))['payload']
        assert payload['rows'] == formula['rows'] and payload['symbol'] == symbol and payload['target_date'] == '20261029'
        observed = canary if symbol == '600814.SH' else render['samples'][symbol]
        assert observed['total_rows'] == item['rows'] and observed['last_date'] == 20261029
        assert observed['variable_table_rows'] == 51 and observed['drawing_table_rows'] == 22 and not observed['errors']
        png_path = observed['screenshot']
        status = 'REUSED_NEW_CANARY_PASS_SHA_VERIFIED' if symbol == '600814.SH' else 'MECHANICAL_HEADLESS_OUTPUT_PASS'
        per_row = 'ALL_OUTPUT_ROWS_MECHANICALLY_VERIFIED'
    original = Path(frozen['renderer']['path']).read_text()
    for name, end in [('choose', 'function paint('), ('paint', 'async function load(')]:
        assert original.split('function ' + name + '(', 1)[1].split(end, 1)[0] == html.split('function ' + name + '(', 1)[1].split(end, 1)[0]
    return {'symbol': symbol, 'data_date': '20261029', 'source_generation': items[symbol]['generation_id'],
        'source_input_sha256': items[symbol]['source_input_sha256'], 'formula_sha256': formula['formula_sha256'],
        'rows': item['rows'], 'values_per_row': 51, 'drawings_per_row': 22, 'per_row_check': per_row,
        'status': status, 'projection': {**item['projection'], 'bytes': len(packed)},
        'html': {**item['html'], 'bytes': len(html_raw)}, 'PNG': png_check(png_path),
        'stock_semantic_review': 'SEPARATE_ROOT_OWNED; NO_STOCK_PASS_INFERRED'}


def main():
    global CONTEXT
    started = time.monotonic()
    manifest = json.loads((OUT / 'MANIFEST.json').read_text())
    frozen = json.loads((OUT / 'INPUT_BINDING.json').read_text())
    coverage = json.loads(checked(frozen['coverage']))
    expected = set(frozen['scope_symbols'])
    items = {row['symbol']: row for row in coverage['items']}
    assert len(expected) == 247 and expected == set(manifest['samples']) == set(items)
    render = json.loads((OUT / 'BATCH_RENDER_READBACK.json').read_text())
    assert render['browser_closed'] and render['temporary_profile_removed'] and not render['errors']
    old_root = OUT.parent / 'original_formula_chart_0415'
    old_result = json.loads((old_root / 'RESULT.json').read_text())
    canary = json.loads((OUT / 'ACTUAL_RENDER_READBACK.json').read_text())['samples'][0]
    CONTEXT = manifest, items, frozen, render, old_result, canary
    errors, records = [], []
    with ProcessPoolExecutor(max_workers=14, mp_context=multiprocessing.get_context('fork')) as pool:
        work = {pool.submit(verify, symbol): symbol for symbol in sorted(expected)}
        for future, symbol in work.items():
            try:
                records.append(future.result())
            except Exception as error:
                errors.append({'symbol': symbol, 'reason': type(error).__name__ + ':' + str(error)})
    actual_new = {p.stem for p in OUT.glob('*.html')}
    expected_new = {s.replace('.', '_') for s in expected - {'600025.SH', '000410.SZ', '920454.BJ'}}
    assert actual_new == expected_new
    assert {p.name.removesuffix('.projection.json.gz') for p in OUT.glob('*.projection.json.gz')} == expected_new
    assert len({row['symbol'] for row in records}) == len(records)
    result = {'status': 'MECHANICAL_247_DELIVERY_PASS' if not errors and len(records) == 247 else 'CANNOT_CONFIRM',
        'expected': 247, 'verified': len(records), 'missing': sorted(expected - {r['symbol'] for r in records}),
        'extra': sorted(actual_new - expected_new), 'errors': errors, 'records': records,
        'verification_wall_seconds': time.monotonic() - started,
        'batch_execution': json.loads((OUT / 'BATCH_EXECUTION_RESULT.json').read_text()),
        'renderer_concurrency_changes': render['concurrency_changes'], 'source_independent_PASS_reused': True,
        'old3_and_new_canary_not_recomputed_or_rerendered': True, 'engine_or_source_calculations_in_this_verifier': 0,
        'stock_semantic_review': 'NOT_PART_OF_MECHANICAL_EXPORT; ROOT_FINAL_DELIVERY_CHECK_PENDING',
        'RESEARCH_ONLY': True, 'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}
    (OUT / 'COMPLETION_RECEIPT_247.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('records', 'batch_execution', 'renderer_concurrency_changes')}))


if __name__ == '__main__':
    main()
