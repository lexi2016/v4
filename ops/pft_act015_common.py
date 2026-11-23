"""Frozen ACT015 identities and bounded V4 projections; no independent data source."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from ops import pft_s_full_ashare as old
from ops.pft_act008_b import panel_columns, verify_source, write_json
from ops.pft_act008_b_features import BASE_FEATURES, BRANCH_FEATURES, FULL_FEATURES, LANES
from ops.pft_s_full_ashare_features import FEATURES as S_FEATURES
from ops.pft_act010_scan import verified_file
from ops.pft_act013_replay import read_gate
from ops.pft_act013_market import FACTOR_NAME
from ops.pft_act008_b_score import scheduled_calendar

START, ASOF = '20220101', '20261120'
GENERATION = '4ed1e1e3ccc2f1045a83527a470f111b81d96771b105ba92e8348bf7f967b268'
PANEL_SHA = '2ce50ea1ec19be7e7011f8326d5daba8f32f6029e33dba6022d650f862c124ec'
FOLDS = {2023: ('20220101', '20221231'), 2024: ('20220101', '20231231'),
         2025: ('20230101', '20241231'), 2026: ('20240101', '20251231')}
IDENTITY = ['canonical_security_id', 'D']
PURE_S = [f'pure_s_{n}' for n in S_FEATURES]
BRANCHES = [f'S_{n}' for n in BRANCH_FEATURES]
NUMERIC = [*BASE_FEATURES, *BRANCHES, *PURE_S]
S_PRESAMPLE_PER_CODE_YEAR = 64
CAPS = {'S_per_class': 4000, 'B_per_class': 5000, 'rank_per_lane': 20000}


def digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def bucket(code, role='OUTER'):
    return int(digest(f'ACT015|{role}|{code}'), 16) % (2 if role == 'OUTER' else 3)


def assert_source(source, frozen):
    verify_source(source, frozen)
    if source['identity']['generation_id'] != GENERATION or source['backtest']['panel_sha256'] != PANEL_SHA:
        raise ValueError('ACT015_FROZEN_SOURCE_DRIFT')


def observed_universe(panel_path, reader):
    """All actual A key scopes, independent of ACT005 held/exposed membership."""
    logical = reader.parquet.ParquetFile(panel_path)
    if not hasattr(logical, 'blocks'):
        raise ValueError('V4_LOGICAL_READER_REQUIRED')
    codes = set()
    for block in logical.blocks:
        if not isinstance(block.get('key_rows'), dict):
            raise ValueError('LOGICAL_KEY_SCOPE_REQUIRED')
        codes.update(c for c in block['key_rows'] if old._is_a_code(c))
    codes -= set(logical.value.get('excluded_symbols', []))
    crosswalk = []
    aliases = {c: c for c in codes}
    rows, _ = old._read_csv(old.CROSSWALK_FILE)
    for row in rows:
        a, b = row.get('old_ts_code', ''), row.get('new_ts_code', '')
        if not a or not b:
            continue
        effective = old._day(row['code_change_effective_date'])
        if not effective:
            raise ValueError('CROSSWALK_EFFECTIVE_DATE_MISSING')
        crosswalk.append(dict(old=a, new=b, effective=effective))
        if a in codes or b in codes:
            aliases[a] = b
            aliases[b] = b
    groups = {}
    for c in sorted(codes):
        groups.setdefault(aliases[c], []).append(c)
    return aliases, groups, crosswalk


def cohorts(groups, size):
    if not 1 <= size <= 384:
        raise ValueError('COHORT_SIZE_OUT_OF_BOUNDS')
    current = []
    for code in sorted(groups):
        group = groups[code]
        if current and len(current) + len(group) > size:
            yield current
            current = []
        current.extend(group)
    if current:
        yield current


def read_cohort(path, schema, mapping, raw_codes, reader, lo=START, hi=ASOF):
    """One Arrow-to-pandas conversion per cohort, no row-wise full-panel dictionary."""
    filters = [[(mapping['trade_date'], '>=', old._date_value(schema, mapping['trade_date'], lo)),
                (mapping['trade_date'], '<=', old._date_value(schema, mapping['trade_date'], hi)),
                (mapping['ts_code'], 'in', raw_codes)]]
    table = reader.parquet.read_table(path, columns=list(dict.fromkeys(mapping.values())), filters=filters)
    frame = table.to_pandas().rename(columns={v: k for k, v in mapping.items()})
    frame['trade_date'] = frame.trade_date.map(old._day)
    if 'market_type' in frame:
        frame = frame[frame.market_type.fillna('').astype(str).str.upper().isin(['', 'A_SHARE', 'BJ'])]
    if 'exchange' in frame:
        accepted = {'SH': {'', 'SH', 'SSE', 'XSHG', 'SHANGHAI'},
                    'SZ': {'', 'SZ', 'SZSE', 'XSHE', 'SHENZHEN'},
                    'BJ': {'', 'BJ', 'BSE', 'XBEI', 'BEIJING'}}
        keep = np.zeros(len(frame), dtype=bool)
        ex = frame.exchange.fillna('').astype(str).str.upper()
        for suffix, names in accepted.items():
            keep |= frame.ts_code.str.endswith('.' + suffix).to_numpy() & ex.isin(names).to_numpy()
        frame = frame.loc[keep]
    if frame.duplicated(['ts_code', 'trade_date']).any():
        raise ValueError('DUPLICATE_V4_KEY')
    return frame


def canonical_history(frame, crosswalk):
    frame = frame.sort_values(['trade_date', 'ts_code']).copy()
    if frame.trade_date.duplicated().any():
        for pair in crosswalk:
            pair_mask = frame.ts_code.isin([pair['old'], pair['new']])
            duplicated = frame.trade_date.duplicated(keep=False)
            desired = np.where(frame.trade_date.lt(pair['effective']), pair['old'], pair['new'])
            frame = frame.loc[~(pair_mask & duplicated & frame.ts_code.ne(desired))]
    if frame.trade_date.duplicated().any():
        raise ValueError('AMBIGUOUS_CANONICAL_DATE')
    return frame.reset_index(drop=True)


def calendar(market_dir, source):
    _, manifest = read_gate(market_dir, source)
    frame = pd.read_csv(market_dir / FACTOR_NAME, dtype={'D': str}).sort_values('D').reset_index(drop=True)
    official, info = scheduled_calendar()
    if info['year'] != 2026:
        raise ValueError('OFFICIAL_CALENDAR_YEAR_DRIFT')
    actual = frame.loc[frame.D.ge('20260101'), 'D'].tolist()
    if actual != [d for d in official if d <= ASOF] or len(actual) != 213:
        raise ValueError('2026_OBSERVED_CALENDAR_MISMATCH')
    return frame, sorted(set(frame.D) | {d for d in official if d > ASOF}), manifest, info


def new_stage(output_dir):
    stage = output_dir.with_name(output_dir.name + '.partial')
    if output_dir.exists() or stage.exists() or output_dir.is_symlink() or stage.is_symlink():
        raise ValueError('OUTPUT_EXISTS:' + str(output_dir))
    stage.mkdir(parents=True)
    return stage


def read_manifest(directory, name):
    m = old._read_json(directory / name)
    if m.get('batch') != 'ACT-015' or m.get('flags') != old.FLAGS:
        raise ValueError('INVALID_ACT015_MANIFEST')
    for rel, sha in m['outputs_sha256'].items():
        verified_file(directory / rel, sha)
    return m


def nullable(value):
    if isinstance(value, dict):
        return {str(k): nullable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [nullable(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def finish_manifest(stage, output_dir, name, value):
    value = {'batch': 'ACT-015', 'flags': old.FLAGS, **value}
    write_json(stage / name, nullable(value))
    stage.rename(output_dir)
    return {'status': 'SEALED', 'output_dir': str(output_dir), 'manifest_sha256': old._sha_file(output_dir / name)}


def cli_failure(exc):
    print(json.dumps({'status': 'FAILED', 'error': str(exc)}), file=sys.stderr, flush=True)
    return 2
