"""Display-only close references from the already accepted daily selector.

No acquisition, historical calculation, persistent store, or observation snapshot.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import re
import threading

FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)


def _path(value):
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or path.resolve(strict=True) != path:
        raise ValueError('QUOTE_REFERENCE_PATH_INVALID')
    return path


def _stamp(path):
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _number(value, minimum=None):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and (minimum is None or value >= minimum) else None


class SourceCloseReferences:
    """Cache only a small projection keyed by bound source identity and file stats."""
    def __init__(self):
        self._cache = {}
        self._lock = threading.RLock()

    def read(self, product):
        identity = product['source_identity']
        day = product['data_date']
        symbols = tuple(sorted(row['symbol'] for row in product['rows']))
        if not re.fullmatch(r'\d{8}', day) or len(set(symbols)) != len(symbols):
            raise ValueError('QUOTE_REFERENCE_SCOPE_INVALID')
        if identity.get('generation') != product['source_generation'] or str(identity.get('asof')) != day:
            raise ValueError('QUOTE_REFERENCE_PRODUCT_IDENTITY_CONFLICT')
        snapshot_ref = identity['snapshot']
        snapshot_path = _path(snapshot_ref['path'])
        stage_path = _path(snapshot_path.parent / 'stage_status.json')
        stage = json.loads(stage_path.read_bytes())
        selector = _path(stage['selector'])
        expected_sha = identity['selector_artifact_sha256']
        if (not re.fullmatch(r'[a-f0-9]{64}', expected_sha)
                or stage.get('status') != 'READY' or stage.get('selector_pointer_ready') is not True
                or stage.get('generation_id') != product['source_generation']
                or stage.get('input_sha256') != identity['input_sha256']
                or str(stage.get('target_date')) != day
                or stage.get('snapshot_file_sha256') != snapshot_ref['sha256']
                or stage.get('candidate_sha256', {}).get('selector') != expected_sha
                or stage.get('candidates', {}).get('selector') != str(selector)
                or stage.get('market_basis', {}).get('A') != identity.get('basis')
                or any(stage.get(k) != v for k, v in FLAGS.items())):
            raise ValueError('QUOTE_REFERENCE_ACCEPTED_SOURCE_CONFLICT')
        stamps = tuple(_stamp(p) for p in (snapshot_path, stage_path, selector))
        key = (day, product['source_generation'], identity['input_sha256'], expected_sha,
               snapshot_ref['sha256'], product['manifest']['sha256'], str(selector), stamps, symbols)
        with self._lock:
            if key in self._cache:
                return copy.deepcopy(self._cache[key])
            if _sha(snapshot_path) != snapshot_ref['sha256'] or _sha(selector) != expected_sha:
                raise ValueError('QUOTE_REFERENCE_SOURCE_SHA_DRIFT')
            import pyarrow.parquet as pq
            parquet = pq.ParquetFile(selector)
            contract = json.loads((parquet.schema_arrow.metadata or {})[b'a_share_qfq_contract_v1'])
            if (contract.get('generation_id') != product['source_generation']
                    or contract.get('input_sha256') != identity['input_sha256']
                    or str(contract.get('asof_date')) != day
                    or contract.get('snapshot_file_sha256') != snapshot_ref['sha256']
                    or contract.get('market_basis', {}).get('A') != identity.get('basis')
                    or identity.get('basis', {}).get('price_basis') != 'QFQ_ASOF'
                    or identity.get('basis', {}).get('amount_basis') != 'RAW_TURNOVER'):
                raise ValueError('QUOTE_REFERENCE_PARQUET_IDENTITY_CONFLICT')
            values = pq.read_table(selector, columns=['ts_code', 'trade_date', 'close', 'pct_chg', 'amount'],
                                   filters=[('trade_date', '=', day), ('ts_code', 'in', list(symbols))]).to_pylist()
            if stamps != tuple(_stamp(p) for p in (snapshot_path, stage_path, selector)):
                raise ValueError('QUOTE_REFERENCE_SOURCE_MOVED')
            rows = {}
            for row in values:
                symbol = row['ts_code']
                if symbol not in symbols or str(row['trade_date']) != day or symbol in rows:
                    raise ValueError('QUOTE_REFERENCE_ROW_IDENTITY_CONFLICT')
                price = _number(row['close'], 0)
                rows[symbol] = dict(symbol=symbol, price=price if price and price > 0 else None,
                                    change_percent_source=_number(row['pct_chg']), amount_source=_number(row['amount'], 0))
            source_date = f'{day[:4]}-{day[4:6]}-{day[6:]}'
            result = dict(schema='V4_WORKBENCH_SOURCE_CLOSE_REFERENCE_V1', status='BOUND_SOURCE_CLOSE',
                          quote_role='SOURCE_DATE_CLOSE_REFERENCE', source_date=source_date,
                          generation=product['source_generation'], input_sha256=identity['input_sha256'],
                          numeric_manifest=product['manifest'], currency='CNY', source_asof=None,
                          source_asof_precision='DATE_ONLY', price_basis='QFQ_ASOF_' + day,
                          amount_basis='RAW_TURNOVER', historical_PIT=False,
                          selector=dict(path=str(selector), sha256=expected_sha), snapshot=snapshot_ref,
                          scope_count=len(symbols), available_count=len(rows), rows=rows, **FLAGS)
            self._cache[key] = result
            while len(self._cache) > 4:
                self._cache.pop(next(iter(self._cache)))
            return copy.deepcopy(result)
