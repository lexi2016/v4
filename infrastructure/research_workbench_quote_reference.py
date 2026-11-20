"""Display-only close references from the already accepted daily selector.

No acquisition, historical calculation, persistent store, or observation snapshot.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import re
import threading

FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
_DAILY_CHART_BARS = 120
_DAILY_CHART_FIELDS = ('open', 'high', 'low', 'close', 'volume')


def _daily_chart_rows(values, symbols, first, day):
    histories = {symbol: {} for symbol in symbols}
    for row in values:
        symbol, date = row['ts_code'], str(row['trade_date'])
        if symbol not in histories or not re.fullmatch(r'\d{8}', date) or not first <= date <= day or date in histories[symbol]:
            raise ValueError('WORKBENCH_DAILY_K_ROW_IDENTITY_CONFLICT')
        bar = {field: _number(row[field], 0 if field == 'volume' else None) for field in _DAILY_CHART_FIELDS}
        if (any(value is None for value in bar.values()) or bar['low'] > min(bar['open'], bar['close'])
                or bar['high'] < max(bar['open'], bar['close'])):
            raise ValueError('WORKBENCH_DAILY_K_BAR_INVALID')
        histories[symbol][date] = dict(trade_date=date, **bar)
    return {symbol: [history[k] for k in sorted(history)[-_DAILY_CHART_BARS:]]
            for symbol, history in histories.items() if day in history}


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


def _bound_row_references(product):
    references = product.get('row_refs')
    if isinstance(references, dict) and references:
        return references
    # The API intentionally exposes a compact numeric view without row_refs.
    # Follow its already-declared signed artifact, never CURRENT or discovery.
    manifest_ref, artifact_ref = product.get('manifest'), product.get('artifact')
    if not isinstance(manifest_ref, dict) or not isinstance(artifact_ref, dict):
        raise ValueError('QUOTE_REFERENCE_PRODUCER_RECEIPT_UNBOUND')
    values = []
    for reference in (manifest_ref, artifact_ref):
        path = _path(reference['path'])
        if _sha(path) != reference['sha256']:
            raise ValueError('QUOTE_REFERENCE_NUMERIC_SOURCE_SHA_DRIFT:' + str(path))
        values.append(json.loads(path.read_bytes()))
    manifest, full = values
    if not all(isinstance(value, dict) for value in values):
        raise ValueError('QUOTE_REFERENCE_NUMERIC_SOURCE_IDENTITY_CONFLICT')
    if (manifest.get('schema_version') != 'v4.a_share.daily_product_manifest.v1'
            or full.get('schema_version') != 'v4.a_share.daily_product.v1'
            or manifest.get('artifact') != artifact_ref
            or manifest.get('data_date') != product['data_date']
            or full.get('data_date') != product['data_date']
            or manifest.get('source_generation') != product['source_generation']
            or full.get('source_generation') != product['source_generation']
            or full.get('source_identity') != product['source_identity']
            or manifest.get('input_sha256') != product['source_identity']['input_sha256']
            or manifest.get('snapshot') != product['source_identity']['snapshot']
            or manifest.get('sample_only') is not False or full.get('sample_only') is not False
            or manifest.get('processed_count') != full.get('processed_count')
            or full.get('source_config') != product.get('source_config')
            or full.get('status') != product.get('status')
            or full.get('processed_count') != product.get('processed_count')
            or full.get('source_universe_count') != product.get('source_universe_count')
            or any(value.get(k) != v for value in values for k, v in FLAGS.items())):
        raise ValueError('QUOTE_REFERENCE_NUMERIC_SOURCE_IDENTITY_CONFLICT')
    references = full.get('row_refs')
    if (not isinstance(references, dict)
            or not {row['symbol'] for row in product['rows']} <= set(references)):
        raise ValueError('QUOTE_REFERENCE_NUMERIC_SCOPE_UNBOUND')
    return references


def _accepted_stage_path(product, snapshot_path):
    """Resolve the existing producer receipt, without a CURRENT/latest fallback.

    Legacy snapshots lived beside stage_status. Immutable shared snapshots do
    not. The signed numeric row already retains the exact producer receipt and
    its SHA, so use that original admission witness for the latter layout.
    """
    legacy = snapshot_path.parent / 'stage_status.json'
    if legacy.is_file():
        return _path(legacy)
    references = _bound_row_references(product)
    for first in product['rows']:
        row_ref = references.get(first['symbol'])
        if not row_ref:
            continue
        row_path = _path(row_ref['path'])
        if _sha(row_path) != row_ref['sha256']:
            raise ValueError('QUOTE_REFERENCE_ADMISSION_ROW_SHA_DRIFT')
        row = json.loads(row_path.read_bytes())
        proof = row.get('qualification') or {}
        identity = product['source_identity']
        if (row.get('symbol') != first['symbol'] or row.get('data_date') != product['data_date']
                or any(row.get(k) != v for k, v in FLAGS.items())):
            raise ValueError('QUOTE_REFERENCE_ADMISSION_ROW_CONFLICT')
        if proof.get('status') != 'CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH':
            continue
        if (proof.get('source_generation') != product['source_generation']
                or proof.get('target_date') != product['data_date']
                or proof.get('snapshot_path') != str(snapshot_path)
                or proof.get('snapshot_sha256') != identity['snapshot']['sha256']
                or any(row.get(k) != v for k, v in FLAGS.items())):
            raise ValueError('QUOTE_REFERENCE_ADMISSION_ROW_CONFLICT')
        receipt_path = _path(proof['producer_receipt_path'])
        if _sha(receipt_path) != proof['producer_receipt_sha256']:
            raise ValueError('QUOTE_REFERENCE_PRODUCER_RECEIPT_SHA_DRIFT')
        receipt = json.loads(receipt_path.read_bytes())
        if (receipt.get('generation_id') != product['source_generation']
                or receipt.get('input_sha256') != identity['input_sha256']
                or receipt.get('adjustment_snapshot') != identity['snapshot']
                or receipt.get('candidate_sha256', {}).get('selector') != identity['selector_artifact_sha256']
                or str(receipt.get('target_date')) != product['data_date']
                or any(receipt.get(k) != v for k, v in FLAGS.items())):
            raise ValueError('QUOTE_REFERENCE_PRODUCER_RECEIPT_CONFLICT')
        return _path(receipt_path.parent / 'stage_status.json')
    raise ValueError('QUOTE_REFERENCE_PRODUCER_RECEIPT_UNBOUND')


def _logical_dependencies(parquet, symbols):
    """Retain the original reader's guards, not its rows or file handles."""
    from ops.research_panel_logical import LogicalFile
    if not isinstance(parquet, LogicalFile):
        return None
    selected = set(symbols)
    blocks = tuple(block for block in parquet.blocks
                   if block.get('symbols') is None or selected.intersection(block['symbols']))
    metadata = {}
    for block in blocks:
        parquet._check(block)
        for reference in block.get('metadata_refs', []):
            path = _path(reference['path'])
            previous = metadata.get(path)
            if previous:
                if previous[0] != reference['sha256']:
                    raise ValueError('QUOTE_REFERENCE_METADATA_IDENTITY_CONFLICT')
                continue
            before = _stamp(path)
            if _sha(path) != reference['sha256']:
                raise ValueError('QUOTE_REFERENCE_METADATA_SHA_DRIFT:' + str(path))
            if _stamp(path) != before:
                raise ValueError('QUOTE_REFERENCE_METADATA_MOVED:' + str(path))
            metadata[path] = (reference['sha256'], before)
    return parquet, blocks, metadata


def _check_logical_dependencies(guard):
    if guard is None:
        return
    parquet, blocks, metadata = guard
    for block in blocks:
        parquet._check(block)
    # Many blocks refer to the same large immutable snapshot. A cold read
    # verifies its SHA once; warm reads check its canonical path/file identity
    # once and never repeatedly hash unchanged metadata or read table rows.
    for path, (expected, before) in metadata.items():
        current = _stamp(_path(path))
        if current != before:
            raise ValueError('QUOTE_REFERENCE_METADATA_CHANGED:' + str(path))


class SourceCloseReferences:
    """Cache a small projection plus the existing logical dependency guards."""
    def __init__(self):
        self._cache = {}
        self._lock = threading.RLock()

    def read(self, product):
        return self._read(product, chart_symbol=None)

    def read_daily_chart(self, product, symbol):
        if symbol not in {row['symbol'] for row in product['rows']}:
            raise KeyError('WORKBENCH_DAILY_K_SYMBOL_NOT_BOUND')
        return self._read(product, chart_symbol=symbol)

    @staticmethod
    def _select_result(result, chart_symbol):
        if chart_symbol is None:
            return copy.deepcopy(result)
        bars = result['rows'].get(chart_symbol)
        if not bars:
            raise KeyError('WORKBENCH_DAILY_K_SOURCE_DAY_NOT_AVAILABLE')
        return copy.deepcopy(dict(result['chart_identity'], symbol=chart_symbol, rows=bars))

    def _read(self, product, *, chart_symbol):
        identity = product['source_identity']
        day = product['data_date']
        scope_symbols = tuple(sorted(row['symbol'] for row in product['rows']))
        if not re.fullmatch(r'\d{8}', day) or len(set(scope_symbols)) != len(scope_symbols):
            raise ValueError('QUOTE_REFERENCE_SCOPE_INVALID')
        if chart_symbol is not None and chart_symbol not in scope_symbols:
            raise KeyError('WORKBENCH_DAILY_K_SYMBOL_NOT_BOUND')
        symbols = (chart_symbol,) if chart_symbol is not None else scope_symbols
        if identity.get('generation') != product['source_generation'] or str(identity.get('asof')) != day:
            raise ValueError('QUOTE_REFERENCE_PRODUCT_IDENTITY_CONFLICT')
        snapshot_ref = identity['snapshot']
        snapshot_path = _path(snapshot_ref['path'])
        stage_path = _accepted_stage_path(product, snapshot_path)
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
               snapshot_ref['sha256'], product['manifest']['sha256'], str(selector), stamps, scope_symbols)
        # Keep a distinct projection per requested symbol. A single-stock
        # chart must not reuse a whole-candidate daily-K projection.
        cache_key = (key, chart_symbol)
        with self._lock:
            if cache_key in self._cache:
                result, guard = self._cache[cache_key]
                _check_logical_dependencies(guard)
                return self._select_result(result, chart_symbol)
            accepted_close = self._cache.get((key, None))
            if accepted_close is None and (_sha(snapshot_path) != snapshot_ref['sha256'] or _sha(selector) != expected_sha):
                raise ValueError('QUOTE_REFERENCE_SOURCE_SHA_DRIFT')
            # This is the same approved physical/logical panel reader used by
            # the daily owner, not a new store or an observation materializer.
            from ops.research_panel_logical import parquet as pq
            parquet = pq.ParquetFile(selector)
            guard = accepted_close[1] if accepted_close is not None else _logical_dependencies(parquet, symbols)
            if accepted_close is not None:
                _check_logical_dependencies(guard)
            contract = json.loads((parquet.schema_arrow.metadata or {})[b'a_share_qfq_contract_v1'])
            if (contract.get('generation_id') != product['source_generation']
                    or contract.get('input_sha256') != identity['input_sha256']
                    or str(contract.get('asof_date')) != day
                    or contract.get('snapshot_file_sha256') != snapshot_ref['sha256']
                    or contract.get('market_basis', {}).get('A') != identity.get('basis')
                    or identity.get('basis', {}).get('price_basis') != 'QFQ_ASOF'
                    or identity.get('basis', {}).get('amount_basis') != 'RAW_TURNOVER'):
                raise ValueError('QUOTE_REFERENCE_PARQUET_IDENTITY_CONFLICT')
            source_date = f'{day[:4]}-{day[4:6]}-{day[6:]}'
            if chart_symbol is not None:
                # Read only recent columns for the already admitted display scope.
                first = (datetime.strptime(day, '%Y%m%d') - timedelta(days=250)).strftime('%Y%m%d')
                values = pq.read_table(selector, columns=['ts_code', 'trade_date', *_DAILY_CHART_FIELDS],
                    filters=[('trade_date', '>=', first), ('trade_date', '<=', day), ('ts_code', '=', chart_symbol)]).to_pylist()
                chart_identity = dict(schema='V4_WORKBENCH_DAILY_K_V1', source_date=source_date,
                    generation=product['source_generation'], input_sha256=identity['input_sha256'],
                    numeric_manifest=product['manifest'], selector=dict(path=str(selector), sha256=expected_sha),
                    snapshot=snapshot_ref, price_basis='QFQ_ASOF_' + day, volume_basis=identity['basis']['volume_basis'],
                    historical_PIT=False, **FLAGS)
                result = dict(chart_identity=chart_identity, rows=_daily_chart_rows(values, symbols, first, day))
            else:
                values = pq.read_table(selector, columns=['ts_code', 'trade_date', 'close', 'pct_chg', 'amount'],
                    filters=[('trade_date', '=', day), ('ts_code', 'in', list(symbols))]).to_pylist()
                rows = {}
                for row in values:
                    symbol = row['ts_code']
                    if symbol not in symbols or str(row['trade_date']) != day or symbol in rows:
                        raise ValueError('QUOTE_REFERENCE_ROW_IDENTITY_CONFLICT')
                    price = _number(row['close'], 0)
                    rows[symbol] = dict(symbol=symbol, price=price if price and price > 0 else None,
                                        change_percent_source=_number(row['pct_chg']), amount_source=_number(row['amount'], 0))
                result = dict(schema='V4_WORKBENCH_SOURCE_CLOSE_REFERENCE_V1', status='BOUND_SOURCE_CLOSE',
                    quote_role='SOURCE_DATE_CLOSE_REFERENCE', source_date=source_date,
                    generation=product['source_generation'], input_sha256=identity['input_sha256'],
                    numeric_manifest=product['manifest'], currency='CNY', source_asof=None,
                    source_asof_precision='DATE_ONLY', price_basis='QFQ_ASOF_' + day,
                    amount_basis='RAW_TURNOVER', historical_PIT=False,
                    selector=dict(path=str(selector), sha256=expected_sha), snapshot=snapshot_ref,
                    scope_count=len(symbols), available_count=len(rows), rows=rows, **FLAGS)
            if stamps != tuple(_stamp(p) for p in (snapshot_path, stage_path, selector)):
                raise ValueError('QUOTE_REFERENCE_SOURCE_MOVED')
            _check_logical_dependencies(guard)
            self._cache[cache_key] = (result, guard)
            while len(self._cache) > 4:
                self._cache.pop(next(iter(self._cache)))
            return self._select_result(result, chart_symbol)
