"""Prepare the dated two-formula Workbench artifact from accepted V4 results."""
import argparse
from collections import Counter
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from urllib.request import urlopen

FLAGS = {
    'RESEARCH_ONLY': True,
    'production_allowed': False,
    'buy_gate_updated': False,
    'orders_sent': False,
}
FORMULA_SHA256 = {
    'b23_entry': '7834657819023edfbe5c77628e478c0fca996e728689b7dcc609f3a8c3254581',
    'pb2_confirm': 'f7b5f5a543325c2e681671ca23c4039cb9cf6749931eb7c262b36e77d38a2307',
}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(batch, origin):
    result = json.loads((batch / 'RESULT.json').read_bytes())
    names = json.loads((batch / 'NAME_BINDING.json').read_bytes())
    named = batch / 'CANDIDATES_NAMED.csv'
    raw = batch / 'CANDIDATES.csv'
    require(result['status'] == 'RESEARCH_PROJECTION_COMPLETE', 'FORMULA_RESULT_INCOMPLETE')
    require(all(result.get(key) is value for key, value in FLAGS.items()), 'FORMULA_RESULT_SCOPE')
    require(digest(named) == names['candidates_named_sha256'], 'FORMULA_NAMES_HASH')
    require(digest(raw) == names['source_candidates_sha256'] == result['files'][raw.name]['sha256'],
            'FORMULA_CANDIDATES_HASH')
    trade_date = str(result['source_date'])
    source_date = datetime.strptime(trade_date, '%Y%m%d').date().isoformat()
    require(result['identity']['asof'] == result['source_date'], 'FORMULA_RESULT_DATE_MISMATCH')
    formula_refs = result['formula_refs']
    require({key: ref['sha256'] for key, ref in formula_refs.items()} == FORMULA_SHA256,
            'FORMULA_DEFINITIONS_MISMATCH')
    for ref in formula_refs.values():
        require(digest(Path(ref['path'])) == ref['sha256'], 'FORMULA_SOURCE_HASH')
    # Read the canonical product and calendar separately; an earlier group overlay may
    # legitimately lag a replacement of the same day's numeric manifest.
    with urlopen(f'{origin}/api/v4/research/a-share/daily-product?date={trade_date}', timeout=25) as response:
        product = json.load(response)
    with urlopen(f'{origin}/api/v4/research/workbench/workflow-contract?source_date={source_date}', timeout=25) as response:
        workflow = json.load(response)
    identity = product['source_identity']
    keys = ('source_date', 'observation_date', 'generation', 'input_sha256', 'numeric_manifest')
    day = dict(zip(keys, (source_date, workflow['observation_date'], product['source_generation'],
                          identity['input_sha256'], product['manifest'])))
    expected = (source_date, result['observation_date'], result['identity']['generation'],
                result['identity']['input_sha256'], result['numeric_manifest'])
    require(product['data_date'] == trade_date and product['status'] in ('READY', 'PARTIAL_WITH_ROWS')
            and tuple(day[key] for key in keys) == expected, 'FORMULA_CANONICAL_DAY_MISMATCH')
    selector_sha = identity['selector_artifact_sha256']
    require(selector_sha == result['identity']['selector_artifact_sha256'] == names['source_selector_sha256'],
            'FORMULA_CANONICAL_SELECTOR_MISMATCH')
    require(product['processed_count'] == result['universe'], 'FORMULA_UNIVERSE_MISMATCH')
    require(digest(Path(day['numeric_manifest']['path'])) == day['numeric_manifest']['sha256'],
            'FORMULA_CANONICAL_MANIFEST_HASH')
    admitted = set(product['processed_universe']).intersection(product['row_refs'])
    rows = []
    counts = Counter(dict.fromkeys(FORMULA_SHA256, 0))
    with named.open(encoding='utf-8-sig', newline='') as stream:
        for record in csv.DictReader(stream):
            row_identity = (record['source_date'], record['source_observation_date'], record['generation'],
                            record['input_sha256'], record['numeric_manifest_sha256'], record['source_selector_sha256'])
            require(row_identity == (trade_date, day['observation_date'], day['generation'], day['input_sha256'],
                                     day['numeric_manifest']['sha256'], selector_sha), 'FORMULA_ROW_IDENTITY_MISMATCH')
            symbol = record['symbol']
            hits = [key for key in FORMULA_SHA256 if record[key] == 'HIT']
            require(re.fullmatch(r'[0-9]{6}\.(?:SH|SZ|BJ)', symbol) and hits
                    and symbol in admitted and set(hits) == set(record['groups'].split('|')), 'FORMULA_ROW_INVALID')
            states = {'HIT': 'TRUE', 'MISS': 'FALSE', 'UNKNOWN': 'UNKNOWN'}
            row = {'symbol': symbol, 'display_name': record['name'] or None, 'groups': hits}
            results = {key: states[record[key]] for key in FORMULA_SHA256}
            if 'UNKNOWN' in results.values():
                row['group_states'] = results
            rows.append(row)
            counts.update(hits)
    require(len(rows) == len({row['symbol'] for row in rows}) == result['union'], 'FORMULA_UNION_MISMATCH')
    require(counts == result['group_counts'], 'FORMULA_GROUP_COUNT_MISMATCH')
    require(sum(len(row['groups']) == 2 for row in rows) == result['overlap'], 'FORMULA_OVERLAP_MISMATCH')
    return {
        'schema': 'V4_WORKBENCH_FORMULA_GROUP_OVERRIDE_V1',
        **{key: day[key] for key in keys},
        'selector_sha256': selector_sha,
        'formula_sha256': FORMULA_SHA256,
        'group_counts': dict(counts),
        'rows': rows,
        **FLAGS,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--origin', default='http://127.0.0.1:8873')
    args = parser.parse_args()
    payload = prepare(args.batch, args.origin)
    with args.output.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'path': str(args.output.resolve()), 'sha256': digest(args.output)}))
