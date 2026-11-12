"""Original panel's explicit Arrow block reader; no collector or global patch.

Ordinary Parquet remains unchanged. Logical anchors fail in unadapted Parquet
readers instead of masquerading as an empty successful panel.
"""
import base64
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as physical

MAGIC = b'V4_LOGICAL_PANEL_V1\n'
SCHEMA = 'v4.original_panel.arrow_blocks.v1'
KEYS = ['ts_code', 'trade_date']
META = b'a_share_qfq_contract_v1'
DISPLAY = {
    'user_v1_hold_yesterday_keyline_display_asof': ['user_v1_hold_yesterday_keyline_daily'],
    'user_v1_break_yesterday_keyline_display_asof': ['user_v1_break_yesterday_keyline_daily'],
    'user_v1_sell_signal_display_asof': ['user_v1_break_yesterday_keyline_daily',
        'user_v1_white_yellow_death_cross', 'user_v1_break_prev_low'],
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stamp(path):
    p = Path(path)
    if not p.is_absolute() or '..' in p.parts or p.resolve() != p or p.is_symlink():
        raise ValueError('LOGICAL_UNSAFE_SOURCE:' + str(p))
    s = p.stat()
    return dict(device=s.st_dev, inode=s.st_ino, size=s.st_size, mtime_ns=s.st_mtime_ns)


def is_logical(path):
    if not isinstance(path, (str, Path)):
        return False
    with Path(path).open('rb') as stream:
        return stream.read(len(MAGIC)) == MAGIC


def anchor_bytes(schema, blocks, *, rows, excluded_symbols=(), projection=None):
    value = dict(schema_version=SCHEMA, arrow_schema=base64.b64encode(schema.serialize()).decode(),
        blocks=blocks, rows=rows, excluded_symbols=sorted(excluded_symbols), projection=projection or {})
    return MAGIC + json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode() + b'\n'


def descriptor(path, *, sha256=None, symbols=None, key_rows=None):
    path = Path(path)
    result = dict(path=str(path), sha256=sha256 or digest(path), stat=stamp(path),
                  rows=physical.ParquetFile(path).metadata.num_rows,
                  row_groups=physical.ParquetFile(path).num_row_groups)
    if symbols is not None:
        result['symbols'] = sorted(symbols)
    if key_rows is not None:
        result['key_rows'] = key_rows
    meta = (physical.read_schema(path).metadata or {}).get(META)
    if meta:
        contract = json.loads(meta)
        result['metadata_refs'] = [dict(path=contract['generation_manifest_path'],
            sha256=digest(contract['generation_manifest_path']))]
        if contract.get('adjustment_snapshot'):
            result['metadata_refs'].append(contract['adjustment_snapshot'])
    return result


def closure(path):
    if not is_logical(path):
        return []
    return LogicalFile(path).blocks


def _key_filters(filters):
    if filters is None or isinstance(filters, ds.Expression):
        return None
    groups = filters if filters and isinstance(filters[0], list) else [filters]
    # Only keys can be pushed ahead of UPSERT resolution. A revised value can
    # fail a business predicate while its superseded old value passes it.
    selected = [[term for term in group if term[0] in KEYS] for group in groups]
    return selected if all(selected) else None


def _keys(table):
    return list(zip(table['ts_code'].to_pylist(), table['trade_date'].to_pylist()))


class LogicalFile:
    def __init__(self, path):
        self.path = Path(path)
        self.anchor_stat = stamp(self.path)
        raw = self.path.read_bytes()
        if not raw.startswith(MAGIC):
            raise ValueError('LOGICAL_MAGIC_REQUIRED')
        self.value = json.loads(raw[len(MAGIC):])
        if self.value.get('schema_version') != SCHEMA:
            raise ValueError('LOGICAL_SCHEMA_UNKNOWN')
        self.schema_arrow = pa.ipc.read_schema(pa.BufferReader(base64.b64decode(self.value['arrow_schema'])))
        self.blocks = self.value['blocks']
        if not self.blocks or len({b['path'] for b in self.blocks}) != len(self.blocks):
            raise ValueError('LOGICAL_BLOCK_SCOPE_INVALID')
        self._files = {}
        self.groups = []
        for index, block in enumerate(self.blocks):
            self.groups.extend((index, group) for group in range(block['row_groups']))
        self.num_row_groups = len(self.groups)
        self.metadata = SimpleNamespace(num_rows=self.value['rows'], num_row_groups=self.num_row_groups,
            metadata=self.schema_arrow.metadata,
            row_group=self._row_group_metadata)
        self.schema = self.schema_arrow

    def _check(self, block):
        if stamp(block['path']) != block['stat'] or stamp(self.path) != self.anchor_stat:
            raise ValueError('LOGICAL_BLOCK_CHANGED:' + block['path'])

    @contextmanager
    def _file(self,index):
        # A request owns this handle. Never cache handles across blocks or
        # close another thread's reader through a shared LRU.
        self._check(self.blocks[index])
        handle=physical.ParquetFile(self.blocks[index]['path'])
        try:
            yield handle
        finally:
            handle.close()
            self._check(self.blocks[index])

    def _row_group_metadata(self,index):
        block,group=self.groups[index]
        with self._file(block) as handle:
            return handle.metadata.row_group(group)

    def _align(self,table,names):
        fields=[self.schema_arrow.field(name) for name in names]
        arrays=[table[name].cast(field.type) if name in table.column_names else pa.nulls(len(table),type=field.type)
                for name,field in zip(names,fields)]
        return pa.Table.from_arrays(arrays,schema=pa.schema(fields,metadata=self.schema_arrow.metadata))

    def _project(self, table):
        schema = self.schema_arrow
        target = self.value.get('projection', {}).get('asof_date')
        if target is not None:
            codes = table['ts_code'].to_pylist()
            dates = table['trade_date'].to_pylist()
            for name, deps in DISPLAY.items():
                if name not in table.column_names or not all(dep in table.column_names for dep in deps):
                    continue
                old = table[name].to_pylist()
                data = {dep: table[dep].to_pylist() for dep in deps}
                values = []
                for i, (code, day) in enumerate(zip(codes, dates)):
                    if (not isinstance(code, str) or not (len(code) == 9 and code[-2:] in {'SZ','SH','BJ'})
                            or code in self.value.get('projection', {}).get('skip_symbols', [])):
                        values.append(old[i]); continue
                    today = int(day) == int(target)
                    first = data[deps[0]][i] == 1
                    value = today and first
                    if name == 'user_v1_sell_signal_display_asof':
                        value = value or data[deps[1]][i] == 1 or data[deps[2]][i] == 1
                    values.append(int(value))
                table = table.set_column(table.schema.get_field_index(name), schema.field(name), pa.array(values, type=schema.field(name).type))
            lineage = self.value.get('projection', {}).get('raw_lineage', {})
            if 'raw_source_ref_sha256' in table.column_names and 'raw_source_role' in table.column_names:
                values = [lineage.get(c, {}).get(r, previous) for c, r, previous in zip(codes,
                    table['raw_source_role'].to_pylist(), table['raw_source_ref_sha256'].to_pylist())]
                name = 'raw_source_ref_sha256'
                table = table.set_column(table.schema.get_field_index(name), schema.field(name), pa.array(values, type=schema.field(name).type))
        return table.replace_schema_metadata(schema.metadata)

    @staticmethod
    def _scope(table, block):
        # symbols is already the block's advertised key scope for pruning.
        # Enforce the same scope for unfiltered and streaming reads as well.
        if block.get('symbols') is not None:
            codes = table['ts_code']
            if pa.types.is_dictionary(codes.type):
                codes = pc.cast(codes, codes.type.value_type)
            table = table.filter(pc.is_in(codes, value_set=pa.array(block['symbols'], type=codes.type)))
        return table

    def _columns(self, columns, filters):
        selected = list(self.schema_arrow.names if columns is None else columns)
        needed = list(dict.fromkeys([*KEYS, *selected]))
        for name in selected:
            needed.extend(d for d in DISPLAY.get(name, []) if d in self.schema_arrow.names and d not in needed)
        if 'raw_source_ref_sha256' in selected and 'raw_source_role' in self.schema_arrow.names:
            needed.append('raw_source_role')
        if filters is not None and not isinstance(filters, ds.Expression):
            groups = filters if isinstance(filters[0], list) else [filters]
            needed.extend(term[0] for group in groups for term in group)
        elif isinstance(filters, ds.Expression):
            # Arrow Expressions do not expose their referenced fields. Explicit
            # consumer projections should use DNF filters to retain pruning.
            needed = list(self.schema_arrow.names)
        for name in list(needed):
            needed.extend(d for d in DISPLAY.get(name, []) if d in self.schema_arrow.names and d not in needed)
        return selected, list(dict.fromkeys(needed))

    def read(self, columns=None, filters=None, **kwargs):
        if isinstance(filters,list) and not filters:filters=None
        selected, needed = self._columns(columns, filters)
        key_filters = _key_filters(filters)
        key_expression = physical.filters_to_expression(key_filters) if key_filters else None
        excluded = set(self.value.get('excluded_symbols', []))
        tables, seen = [], set()
        requested_symbols = None
        if key_filters and len(key_filters) == 1:
            for key, op, value in key_filters[0]:
                if key == 'ts_code' and op in ('=', '==', 'in'):
                    requested_symbols = {value} if op != 'in' else set(value)
        for index in range(len(self.blocks) - 1, -1, -1):
            block = self.blocks[index]
            if requested_symbols is not None and block.get('symbols') is not None and not requested_symbols.intersection(block['symbols']):
                continue
            self._check(block)
            group_ids = None
            if requested_symbols is not None and block.get('key_rows'):
                group_ids = sorted({g for c in requested_symbols for g in block['key_rows'].get(c, [])})
            with self._file(index) as f:
                table = f.read_row_groups(group_ids, columns=needed) if group_ids is not None else f.read(columns=needed)
            table = self._scope(self._align(table,needed), block)
            if key_expression is not None:
                table = table.filter(key_expression)
            keys = _keys(table)
            keep = [key not in seen and key[0] not in excluded for key in keys]
            if len(keys) != len(set(keys)):
                raise ValueError('LOGICAL_DUPLICATE_KEYS_IN_BLOCK:' + block['path'])
            seen.update(keys)
            table = table.filter(pa.array(keep, type=pa.bool_()))
            tables.append(self._project(table))
            self._check(block)
        if not tables:
            return pa.Table.from_batches([], schema=pa.schema([self.schema_arrow.field(c) for c in selected], metadata=self.schema_arrow.metadata))
        table = pa.concat_tables(list(reversed(tables)))
        if filters is not None:
            table = table.filter(physical.filters_to_expression(filters))
        return table.select(selected).replace_schema_metadata(self.schema_arrow.metadata)

    def iter_batches(self, batch_size=65536, columns=None, **kwargs):
        selected, needed = self._columns(columns, None)
        latest = {}
        # Only overlay keys are indexed. The full historical base is streamed
        # once, never reread once per stock or assembled into a full DataFrame.
        for index in range(1,len(self.blocks)):
            with self._file(index) as handle:
                for batch in handle.iter_batches(columns=KEYS,batch_size=batch_size):
                    table=self._scope(pa.Table.from_batches([batch]),self.blocks[index])
                    latest.update((key,index)for key in _keys(table))
        excluded=set(self.value.get('excluded_symbols',[]))
        for index in range(len(self.blocks)):
            with self._file(index) as handle:
                for batch in handle.iter_batches(columns=needed,batch_size=batch_size):
                    table=self._scope(self._align(pa.Table.from_batches([batch]),needed),self.blocks[index])
                    keep=[latest.get(key,index)==index and key[0]not in excluded for key in _keys(table)]
                    table=self._project(table.filter(pa.array(keep,type=pa.bool_()))).select(selected)
                    yield from table.to_batches(max_chunksize=batch_size)


class _Parquet:
    def __init__(self):
        self.cache = {}
    def __getattr__(self, name):
        return getattr(physical, name)
    def ParquetFile(self, source, *args, **kwargs):
        if not is_logical(source):
            return physical.ParquetFile(source, *args, **kwargs)
        path = str(source)
        old = self.cache.get(path)
        if old is None or stamp(source) != old.anchor_stat:
            if len(self.cache) >= 4:
                self.cache.pop(next(iter(self.cache)))
            self.cache[path] = LogicalFile(source)
        return self.cache[path]
    def read_table(self, source, *, columns=None, filters=None, **kwargs):
        if is_logical(source):
            return self.ParquetFile(source).read(columns=columns, filters=filters, **kwargs)
        return physical.read_table(source, columns=columns, filters=filters, **kwargs)
    def read_schema(self, source, **kwargs):
        return self.ParquetFile(source).schema_arrow
    def read_metadata(self, source, **kwargs):
        return self.ParquetFile(source).metadata


parquet = _Parquet()


def read_frame(path, **kwargs):
    if kwargs.get('filters') == []: kwargs['filters'] = None
    return parquet.read_table(path, **kwargs).to_pandas()


def dataset(source, **kwargs):
    if not is_logical(source):
        return ds.dataset(source, **kwargs)
    file = parquet.ParquetFile(source)
    class View:
        schema = file.schema_arrow
        def to_table(self, columns=None, filter=None, **options):
            return file.read(columns=columns, filters=filter)
        def scanner(self, columns=None, filter=None, **options):
            return SimpleNamespace(to_table=lambda: self.to_table(columns=columns, filter=filter),
                to_batches=lambda: self.to_table(columns=columns, filter=filter).to_batches())
    return View()


def validate_closure(path):
    for block in closure(path):
        if stamp(block['path']) != block['stat']:
            raise ValueError('LOGICAL_BLOCK_CHANGED:' + block['path'])
