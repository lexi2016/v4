"""Single read-only HK field/window admission contract owned by hk_0_2.

Original market files are never changed. A missing, stale or tampered contract
fails closed. Current C native representation admission is separate from B units.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import math
import os
import re
from pathlib import Path
from datetime import datetime
from typing import Any

FIELDS = ('open', 'high', 'low', 'close', 'amount', 'trade')
SCHEMA = 'hk_history_resolution.v1'
RULE = 'HK_HISTORY_AUTHORITY_V1'
CORRECTION_RULE = 'TDXPY_EVENT_DOUBLE_ANCHOR_OHLC_AMOUNT_V1'
CORRECTION_FIELDS = ('open','high','low','close','amount')
_LEDGERS: dict[tuple[str, str, str], dict] = {}


class ResolutionError(ValueError):
    """Public-safe failure code; never includes a host path."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def symbol(value):
    value = str(value).strip().upper()
    if value.startswith('HK.'):
        value = value[3:]
    elif value.endswith('.HK'):
        value = value[:-3]
    if not value.isdigit() or not 1 <= int(value) <= 99999:
        raise ResolutionError('HK_HISTORY_RESOLUTION_SYMBOL_INVALID')
    return 'HK.' + str(int(value)).zfill(5)


def day(value):
    value = str(value).replace('-', '')[:8]
    if re.fullmatch(r'\d{8}', value) is None:
        raise ResolutionError('HK_HISTORY_RESOLUTION_DATE_INVALID')
    return value


def fields(values):
    values = tuple(dict.fromkeys(values))
    if not values or any(value not in FIELDS for value in values):
        raise ResolutionError('HK_HISTORY_RESOLUTION_FIELDS_INVALID')
    return values


def continuity_edge(previous_date, current_date, previous_close, current_close):
    """Existing VIPDOC producer continuity rules, applied to the effective view."""
    gap = (datetime.strptime(current_date,'%Y%m%d')-datetime.strptime(previous_date,'%Y%m%d')).days
    ratio = current_close / previous_close if previous_close > 0 else math.inf
    reason = 'long_calendar_gap' if gap > 14 else 'cross_day_close_ratio' if ratio > 1.5 or ratio < 1/1.5 else ''
    return (None if reason else previous_close),reason


def regular(root, relative):
    rel = Path(str(relative))
    if rel.is_absolute() or not rel.parts or any(part in ('.', '..') for part in rel.parts):
        raise ResolutionError('HK_HISTORY_RESOLUTION_PATH_INVALID')
    path = root
    for part in rel.parts:
        path = path / part
        if path.is_symlink():
            raise ResolutionError('HK_HISTORY_RESOLUTION_SYMLINK_DENIED')
    if not path.is_file() or not path.resolve().is_relative_to(root):
        raise ResolutionError('HK_HISTORY_RESOLUTION_FILE_MISSING')
    return path


def root_for_source(source):
    path = Path(source).resolve(strict=True)
    for parent in path.parents:
        if parent.name == 'hk_0_2':
            return parent
    raise ResolutionError('HK_HISTORY_RESOLUTION_OWNER_REQUIRED')


def verify_append_frames(baseline, current, *, baseline_max, B_max):
    """Exact all-column, all-key prefix proof; never compare only conflict keys."""
    keys = ['code_norm','trade_date_compact']
    if list(baseline.columns) != list(current.columns) or any(baseline[c].dtype != current[c].dtype for c in baseline.columns):
        raise ResolutionError('HK_HISTORY_RESOLUTION_APPEND_SCHEMA_CHANGED')
    if baseline.duplicated(keys).any() or current.duplicated(keys).any():
        raise ResolutionError('HK_HISTORY_RESOLUTION_APPEND_DUPLICATE_KEY')
    dates = current['trade_date_compact'].map(day)
    old = current.loc[dates <= baseline_max]
    new = current.loc[dates > baseline_max]
    left = baseline.sort_values(keys).reset_index(drop=True)
    right = old.sort_values(keys).reset_index(drop=True)
    if not left.equals(right):
        raise ResolutionError('HK_HISTORY_RESOLUTION_APPEND_OLD_KEYS_OR_VALUES_CHANGED')
    if new.empty or any(day(date) <= max(baseline_max,B_max) for date in new['trade_date_compact']):
        raise ResolutionError('HK_HISTORY_RESOLUTION_APPEND_DATES_INVALID')
    return dict(status='APPEND_ONLY_COMPATIBLE',baseline_rows=len(baseline),current_rows=len(current),
                new_rows=len(new),all_original_columns_and_keys_exact=True)


class ResolutionPolicy:
    def __init__(self, owner_root, *, pointer_path=None):
        self.root = Path(owner_root).resolve(strict=True)
        if self.root.name != 'hk_0_2':
            raise ResolutionError('HK_HISTORY_RESOLUTION_OWNER_INVALID')
        # Operator-only candidate injection; HTTP parameters cannot select a pointer.
        selected = pointer_path or os.environ.get('V4_HK_HISTORY_RESOLUTION_POINTER')
        pointer_path = Path(selected) if selected else regular(self.root, 'history_resolution_latest.json')
        self._pointer_path = pointer_path
        self._score_admissions = {}
        if pointer_path.is_symlink() or not pointer_path.is_file():
            raise ResolutionError('HK_HISTORY_RESOLUTION_POINTER_MISSING')
        try:
            pointer = json.loads(pointer_path.read_bytes())
            manifest_path = regular(self.root, pointer['manifest_relative'])
            manifest_raw = manifest_path.read_bytes()
            if sha(manifest_raw) != pointer['manifest_sha256']:
                raise ResolutionError('HK_HISTORY_RESOLUTION_MANIFEST_SHA_MISMATCH')
            manifest = json.loads(manifest_raw)
            if manifest['schema_version'] != SCHEMA or manifest['rule_version'] != RULE:
                raise ResolutionError('HK_HISTORY_RESOLUTION_SCHEMA_INVALID')
            if manifest['resolver_sha256'] != sha(Path(__file__).read_bytes()):
                raise ResolutionError('HK_HISTORY_RESOLUTION_READER_SHA_MISMATCH')
            if (manifest.get('research_only') is not True or
                    any(manifest.get(k) is not False for k in ('production_allowed','buy_gate_updated','orders_sent'))):
                raise ResolutionError('HK_HISTORY_RESOLUTION_SAFETY_INVALID')
            self.manifest, self.manifest_sha256 = manifest, sha(manifest_raw)
            bindings = manifest['bindings']
            for path_key, hash_key in [('descriptor_relative','descriptor_sha256'),
                    ('B_relative','B_sha256'),('C_panel_relative','C_panel_sha256'),
                    ('C_manifest_relative','C_manifest_sha256')]:
                if sha(regular(self.root, bindings[path_key]).read_bytes()) != bindings[hash_key]:
                    raise ResolutionError('HK_HISTORY_RESOLUTION_SOURCE_SHA_MISMATCH')
            current_pointer = json.loads(regular(self.root, 'panel_latest.json').read_bytes())
            current_manifest_path = regular(self.root, current_pointer['manifest_relative'])
            current_raw = current_manifest_path.read_bytes()
            self.current_manifest = json.loads(current_raw)
            self.current_manifest_sha256 = sha(current_raw)
            self.current_panel_sha256 = self.current_manifest['panel_sha256']
            self.append_proof = dict(status='EXACT_BASELINE')
            if (self.current_manifest_sha256 != bindings['C_manifest_sha256'] or
                    self.current_panel_sha256 != bindings['C_panel_sha256']):
                if manifest.get('append_policy') != 'ALL_KEYS_ALL_COLUMNS_EXACT':
                    raise ResolutionError('HK_HISTORY_RESOLUTION_STALE_C_BINDING')
                baseline_manifest = json.loads(regular(self.root, bindings['C_manifest_relative']).read_bytes())
                if (self.current_manifest.get('increment_contract') != baseline_manifest.get('increment_contract')
                        or not baseline_manifest.get('increment_contract')
                        or self.current_manifest.get('source_contract') != baseline_manifest.get('source_contract')
                        or self.current_manifest.get('research_only') is not True
                        or any(self.current_manifest.get(k) is not False for k in ('production_allowed','buy_gate_updated','orders_sent'))):
                    raise ResolutionError('HK_HISTORY_RESOLUTION_APPEND_CONTRACT_INVALID')
                current_panel = regular(self.root,self.current_manifest['panel_relative'])
                if sha(current_panel.read_bytes()) != self.current_panel_sha256:
                    raise ResolutionError('HK_HISTORY_RESOLUTION_APPEND_SOURCE_SHA_MISMATCH')
                import pandas as pd
                baseline = pd.read_parquet(regular(self.root,bindings['C_panel_relative']))
                current = pd.read_parquet(current_panel)
                self.append_proof = verify_append_frames(baseline,current,
                    baseline_max=manifest['baseline_C_max_date'],B_max=manifest['B_max_date'])
                if len(current) != self.current_manifest['panel_rows']:
                    raise ResolutionError('HK_HISTORY_RESOLUTION_APPEND_ROW_COUNT_MISMATCH')
            ledger_path = regular(self.root, manifest['decisions_relative'])
            compressed = ledger_path.read_bytes()
            ledger_sha = sha(compressed)
            if ledger_sha != manifest['decisions_sha256']:
                raise ResolutionError('HK_HISTORY_RESOLUTION_LEDGER_SHA_MISMATCH')
            ledger_cache_key = (ledger_sha, bindings['B_sha256'], bindings['C_panel_sha256'])
            if ledger_cache_key not in _LEDGERS:
                indexed = {}
                for line in gzip.decompress(compressed).splitlines():
                    record = json.loads(line)
                    key = (symbol(record['symbol']), day(record['date']))
                    if key in indexed or set(record['field_decisions']) != set(FIELDS):
                        raise ResolutionError('HK_HISTORY_RESOLUTION_LEDGER_KEY_INVALID')
                    for decision in record['field_decisions'].values():
                        if decision['disposition'] not in ('CONFIRMED_KEEP_C','QUARANTINED','UNDISPUTED_KEEP_C_EXISTING_POLICY'):
                            raise ResolutionError('HK_HISTORY_RESOLUTION_DISPOSITION_INVALID')
                    if record['B_source_sha256'] != bindings['B_sha256'] or record['C_source_sha256'] != bindings['C_panel_sha256']:
                        raise ResolutionError('HK_HISTORY_RESOLUTION_LEDGER_SOURCE_MISMATCH')
                    indexed[key] = record
                if len(indexed) != manifest['decision_key_count']:
                    raise ResolutionError('HK_HISTORY_RESOLUTION_LEDGER_COUNT_MISMATCH')
                _LEDGERS.clear()
                _LEDGERS[ledger_cache_key] = indexed
            self.decisions = _LEDGERS[ledger_cache_key]
            self.ledger_sha256 = ledger_sha
            self.corrections = {}
            self.corrections_sha256 = None
            if manifest.get('corrections_relative'):
                compressed = regular(self.root,manifest['corrections_relative']).read_bytes()
                self.corrections_sha256 = sha(compressed)
                if (self.corrections_sha256 != manifest['corrections_sha256']
                        or manifest.get('correction_rule_version') != CORRECTION_RULE):
                    raise ResolutionError('HK_HISTORY_CORRECTION_SHA_OR_RULE_INVALID')
                evidence_raw = regular(self.root,manifest['correction_evidence_relative']).read_bytes()
                if sha(evidence_raw) != manifest['correction_evidence_sha256']:
                    raise ResolutionError('HK_HISTORY_CORRECTION_EVIDENCE_SHA_INVALID')
                evidence = json.loads(evidence_raw)
                pins = {pin['raw_relative']:pin for pin in evidence['sources']}
                for pin in pins.values():
                    if (sha(regular(self.root,pin['raw_relative']).read_bytes()) != pin['raw_sha256']
                            or sha(regular(self.root,pin['manifest_relative']).read_bytes()) != pin['manifest_sha256']):
                        raise ResolutionError('HK_HISTORY_CORRECTION_RAW_SOURCE_CHANGED')
                for line in gzip.decompress(compressed).splitlines():
                    record = json.loads(line)
                    key = (symbol(record['symbol']),day(record['date']))
                    original = self.decisions.get(key)
                    if (key in self.corrections or original is None
                            or record['C_row_sha256'] != original['C_row_sha256']
                            or record['B_row_sha256'] != original['B_row_sha256']
                            or record['B_source_sha256'] != bindings['B_sha256']
                            or record['C_source_sha256'] != bindings['C_panel_sha256']
                            or set(record['values']) != set(CORRECTION_FIELDS)
                            or record['rule_version'] != CORRECTION_RULE
                            or record['channel'] != 'TDX_PROTOCOL_PARAM1_FIXED'):
                        raise ResolutionError('HK_HISTORY_CORRECTION_BINDING_INVALID')
                    values = record['values']
                    if (any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in values.values())
                            or min(values[f] for f in CORRECTION_FIELDS[:4]) <= 0 or values['amount'] < 0
                            or values['high'] < max(values[f] for f in CORRECTION_FIELDS[:4])
                            or values['low'] > min(values[f] for f in CORRECTION_FIELDS[:4])):
                        raise ResolutionError('HK_HISTORY_CORRECTION_BAR_INVALID')
                    expected_anchors = {'20260706':('20260703','20260707'),
                                        '20260722':('20260721','20260723')}.get(key[1])
                    if (not expected_anchors or tuple(a['date'] for a in record['anchors']) != expected_anchors
                            or any(a['C_values'] != a['TDX_values'] or set(a['C_values']) != set(CORRECTION_FIELDS) for a in record['anchors'])):
                        raise ResolutionError('HK_HISTORY_CORRECTION_ANCHORS_INVALID')
                    closure = record['closure']
                    event_pre,event_break = continuity_edge(expected_anchors[0],key[1],record['anchors'][0]['C_values']['close'],values['close'])
                    next_pre,next_break = continuity_edge(key[1],expected_anchors[1],values['close'],record['anchors'][1]['C_values']['close'])
                    if (closure['previous_date'] != expected_anchors[0] or closure['next_date'] != expected_anchors[1]
                            or closure['event_pre_close'] != event_pre or closure['next_pre_close'] != next_pre
                            or closure.get('event_break','') != event_break or closure.get('next_break','') != next_break
                            or closure['continuity_segment_equal'] is not True):
                        raise ResolutionError('HK_HISTORY_CORRECTION_CLOSURE_INVALID')
                    if not record['evidence_refs'] or any(not a['evidence_refs'] for a in record['anchors']):
                        raise ResolutionError('HK_HISTORY_CORRECTION_SOURCE_IDENTITY_INVALID')
                    for ref in record['evidence_refs'] + [r for a in record['anchors'] for r in a['evidence_refs']]:
                        pin = pins.get(ref['raw_relative'])
                        if (pin is None or ref['raw_sha256'] != pin['raw_sha256']
                                or key[1] >= day(ref['captured_at'])
                                or any(re.fullmatch(r'[0-9a-f]{64}',ref[name]) is None for name in ('request_sha256','response_sha256','catalogue_sha256'))):
                            raise ResolutionError('HK_HISTORY_CORRECTION_SOURCE_IDENTITY_INVALID')
                    self.corrections[key] = record
                if len(self.corrections) != manifest['correction_key_count']:
                    raise ResolutionError('HK_HISTORY_CORRECTION_COUNT_INVALID')
        except ResolutionError:
            raise
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ResolutionError('HK_HISTORY_RESOLUTION_CONTRACT_INVALID') from error

    def check_panel(self, expected_sha):
        if expected_sha != self.current_panel_sha256:
            raise ResolutionError('HK_HISTORY_RESOLUTION_UNBOUND_PANEL')

    def held_fields(self, code, date, required_fields=FIELDS, *, source='C'):
        required_fields = fields(required_fields)
        record = self.decisions.get((symbol(code),day(date)))
        if record is None:
            return []
        if source == 'B':
            return list(required_fields)  # every disputed B variant is audit-only
        corrected = self.corrections.get((symbol(code),day(date)),{}).get('values',{})
        return [field for field in required_fields
                if field not in corrected and record['field_decisions'][field]['disposition'] == 'QUARANTINED']

    def field_admission(self, code, date, field):
        key = (symbol(code),day(date))
        if field in self.corrections.get(key,{}).get('values',{}):
            return 'CORRECTED_TDX_RETROSPECTIVE_CHANNEL'
        record = self.decisions.get(key)
        return record['field_decisions'][field]['disposition'] if record else 'UNDISPUTED_KEEP_C_EXISTING_POLICY'

    def effective_values(self, code, date, values, *, source='C'):
        result = dict(values)
        if source == 'C':
            corrected = self.corrections.get((symbol(code),day(date)),{}).get('values',{})
            result.update({key:value for key,value in corrected.items() if key in result})
        return result

    def project_frame(self, frame, *, code_column='code_norm', date_column='trade_date_compact', source='C'):
        """Apply sparse C values and explicit subset-safe same-segment closure."""
        if source != 'C' or not self.corrections or frame.empty:
            return frame
        previous_view = frame.attrs.get('hk_history_effective_view')
        if previous_view:
            if previous_view != self.manifest_sha256:
                raise ResolutionError('HK_HISTORY_CORRECTION_PROJECTED_VIEW_STALE')
            return frame
        result = frame.copy()
        lookup = {(symbol(c),day(d)):index for index,c,d in zip(result.index,result[code_column],result[date_column])}
        derived = set()
        breaks = {}
        for key,record in self.corrections.items():
            index = lookup.get(key)
            if index is not None:
                for field,value in record['values'].items():
                    if field in result.columns:result.at[index,field] = value
                if 'pre_close' in result.columns:result.at[index,'pre_close'] = record['closure']['event_pre_close']
                if 'continuity_break' in result.columns:result.at[index,'continuity_break'] = record['closure'].get('event_break','')
                derived.add(index)
            successor = lookup.get((key[0],record['closure']['next_date']))
            if successor is not None:
                if 'pre_close' in result.columns:result.at[successor,'pre_close'] = record['closure']['next_pre_close']
                if 'continuity_break' in result.columns:result.at[successor,'continuity_break'] = record['closure'].get('next_break','')
                derived.add(successor)
            for date,reason in [(key[1],record['closure'].get('event_break','')),
                                (record['closure']['next_date'],record['closure'].get('next_break',''))]:
                if reason:breaks.setdefault(key[0],set()).add(date)
        if 'continuity_segment_id' in result.columns:
            for (code,date),index in lookup.items():
                offset = sum(date >= start for start in breaks.get(code,()))
                if offset:result.at[index,'continuity_segment_id'] += offset
        if 'pre_close' in result.columns:
            for index in derived:
                previous = result.at[index,'pre_close']
                for output,left,right in [('pct_chg','close',None),('amplitude_pct','high','low'),('intraday_high_pct','high',None)]:
                    if output in result.columns and left in result.columns and (right is None or right in result.columns):
                        numerator = result.at[index,left] - (result.at[index,right] if right else previous)
                        result.at[index,output] = numerator / previous * 100.0 if previous > 0 else float('nan')
        result.attrs['hk_history_effective_view'] = self.manifest_sha256
        return result

    def proof(self, *, required_fields, start, end, consumer, allowed_codes=(), excluded_codes=(), score_coverage=None):
        binding = self.manifest['bindings']
        proof = dict(resolution_schema_version=SCHEMA,resolution_rule_version=RULE,
            resolution_manifest_sha256=self.manifest_sha256,resolution_ledger_sha256=self.ledger_sha256,
            source_descriptor_sha256=binding['descriptor_sha256'],B_source_sha256=binding['B_sha256'],
            C_panel_sha256=self.current_panel_sha256,C_manifest_sha256=self.current_manifest_sha256,
            resolver_sha256=self.manifest['resolver_sha256'],required_fields=list(fields(required_fields)),
            dependency_start=day(start),dependency_end=day(end),dependency_rule_version=consumer,
            allowed_codes=sorted(set(allowed_codes)),excluded_codes=sorted(set(excluded_codes)),
            excluded_code_count=len(set(excluded_codes)),admission='FIELD_WINDOW_VERIFIED')
        if self.corrections_sha256:
            proof.update(corrections_sha256=self.corrections_sha256,correction_rule_version=CORRECTION_RULE)
        if score_coverage is not None:
            proof['score_coverage'] = score_coverage
            _check_score_coverage(proof)
        return proof

    def encode_proof(self, proof):
        return 'b64url.' + base64.urlsafe_b64encode(canonical(proof)).decode('ascii')

    def verify_proof(self, token, *, required_fields=FIELDS, end=None, consumer=None, codes=()):
        try:
            if not isinstance(token,str) or not token.startswith('b64url.'):
                raise ResolutionError('HK_HISTORY_RESOLUTION_CACHE_PROOF_MISSING')
            proof = json.loads(base64.b64decode(token[7:],altchars=b'-_',validate=True))
            expected = self.proof(required_fields=required_fields,start=proof['dependency_start'],
                end=end or proof['dependency_end'],consumer=consumer or proof['dependency_rule_version'],
                allowed_codes=proof['allowed_codes'],excluded_codes=proof['excluded_codes'],
                score_coverage=proof.get('score_coverage'))
            if proof != expected or not {symbol(code) for code in codes}.issubset(set(proof['allowed_codes'])):
                raise ResolutionError('HK_HISTORY_RESOLUTION_CACHE_PROOF_STALE')
            if expected['dependency_rule_version'] == 'HK_FROZEN_SCORE_PRICE121_TRADE_CURRENT_V1':
                self._validate_score_admission(proof)
            return proof
        except ResolutionError:
            raise
        except (ValueError, KeyError, TypeError, OSError, ImportError) as error:
            raise ResolutionError('HK_HISTORY_RESOLUTION_CACHE_PROOF_INVALID') from error

    def _trusted_score_proof(self, signal_date):
        """Recompute admission from owned keys/holds and the existing verified master.

        Token code lists never select this computation or populate its cache.
        The same helper also runs when imported standalone by legacy consumers.
        """
        import importlib.util
        import sys
        import types
        import pandas as pd
        signal_date = day(signal_date)
        pointer = json.loads(self._pointer_path.read_bytes())
        latest = json.loads(regular(self.root,'panel_latest.json').read_bytes())
        current_raw = regular(self.root,latest['manifest_relative']).read_bytes()
        panel = regular(self.root,self.current_manifest['panel_relative'])
        if (pointer.get('manifest_sha256') != self.manifest_sha256
                or sha(regular(self.root,pointer['manifest_relative']).read_bytes()) != self.manifest_sha256
                or sha(current_raw) != self.current_manifest_sha256
                or sha(panel.read_bytes()) != self.current_panel_sha256
                or sha(regular(self.root,self.manifest['decisions_relative']).read_bytes()) != self.ledger_sha256
                or (self.corrections_sha256 and sha(regular(self.root,self.manifest['corrections_relative']).read_bytes()) != self.corrections_sha256)):
            raise ResolutionError('HK_HISTORY_RESOLUTION_SCORE_SOURCE_STALE')
        if __package__:
            from .hk_security_master import load_verified_hk_security_master
            load_master = load_verified_hk_security_master
        else:
            # Do not change sys.path or the process's shared_data namespace.
            directory = Path(__file__).resolve().parent
            namespace = '_hk_resolution_reference_' + sha(str(directory).encode())[:16]
            if namespace not in sys.modules:
                package = types.ModuleType(namespace);package.__path__ = [str(directory)]
                sys.modules[namespace] = package
            module_name = namespace + '.hk_security_master'
            if module_name not in sys.modules:
                spec = importlib.util.spec_from_file_location(module_name,directory/'hk_security_master.py')
                if spec is None or spec.loader is None:
                    raise ResolutionError('HK_HISTORY_RESOLUTION_SCORE_MASTER_MODULE_MISSING')
                reference = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = reference
                try:
                    spec.loader.exec_module(reference)
                except BaseException:
                    sys.modules.pop(module_name,None)
                    raise
            load_master = sys.modules[module_name].load_verified_hk_security_master
        try:
            master, master_manifest = load_master(self.root.parent.parent,signal_date)
        except Exception as error:
            raise ResolutionError('HK_HISTORY_RESOLUTION_SCORE_MASTER_UNVERIFIED') from error
        cache_key = (signal_date,sha(canonical(master_manifest)))
        if cache_key not in self._score_admissions:
            source = pd.read_parquet(panel,columns=['code_norm','trade_date_compact'])
            source['code_norm'] = source['code_norm'].map(symbol)
            source['trade_date_compact'] = source['trade_date_compact'].map(day)
            source = source.loc[source['trade_date_compact'].le(signal_date)].copy()
            if source.duplicated(['code_norm','trade_date_compact']).any():
                raise ResolutionError('HK_HISTORY_RESOLUTION_SCORE_SOURCE_DUPLICATE')
            guarded = guard_score_frame(source,self,signal_date)
            base = guarded.attrs['history_resolution_proof']
            eligible = {symbol(code) for code in master}
            original = set(source.loc[source['trade_date_compact'].eq(signal_date),'code_norm'])
            scoreable = eligible & original & set(base['allowed_codes'])
            quarantined = eligible & original & set(base['excluded_codes'])
            coverage = dict(eligible_codes=sorted(eligible),original_signal_codes=sorted(original),
                scoreable_signal_codes=sorted(scoreable),quality_quarantined_codes=sorted(quarantined),
                missing_signal_codes=sorted(eligible-scoreable-quarantined))
            base['score_coverage'] = coverage
            _check_score_coverage(base,eligible_codes=master)
            self._score_admissions[cache_key] = base
        return self._score_admissions[cache_key]

    def _validate_score_admission(self, proof):
        if proof != self._trusted_score_proof(proof['dependency_end']):
            raise ResolutionError('HK_HISTORY_RESOLUTION_SCORE_ADMISSION_MISMATCH')

    def guard_frame(self, frame, *, required_fields=FIELDS, code_column='code_norm',
                    date_column='trade_date_compact', start=None, end=None,
                    lookback=None, predecessors=0, source='C', consumer='HK_HISTORY_FULL_SERIES'):
        """Exclude an affected code's complete sequence before any calculation.

        The dependency selection is used only for the hold check. The returned
        frame retains every original row of clean codes, so no gaps are bridged.
        None lookback guards the entire supplied history, including proxy memory.
        """
        requested = fields(required_fields)
        frame = self.project_frame(frame,code_column=code_column,date_column=date_column,source=source)
        if frame.empty:
            result = frame.copy()
            result.attrs['history_resolution_proof'] = self.proof(required_fields=requested,
                start=start or '19000101',end=end or '99991231',consumer=consumer)
            result.attrs['history_resolution_holds'] = {}
            return result
        all_dates = frame[date_column].map(day)
        start, end = day(start or all_dates.min()), day(end or all_dates.max())
        excluded, allowed = set(), set()
        reasons = {}
        for raw_code, group in frame.groupby(code_column, sort=False):
            code = symbol(raw_code)
            dates = sorted({day(value) for value in group[date_column] if day(value) <= end})
            if lookback is not None:
                dependency = dates[-(lookback+predecessors):]
            else:
                eligible = [i for i,value in enumerate(dates) if start <= value <= end]
                dependency = dates[max(0,eligible[0]-predecessors):eligible[-1]+1] if eligible else []
            holds = [(date,self.held_fields(code,date,requested,source=source)) for date in dependency]
            holds = [(date,held) for date,held in holds if held]
            if holds:
                excluded.add(code)
                reasons[code] = [{'date':date,'fields':held,'reason':'HK_HISTORY_FIELD_QUARANTINED'} for date,held in holds]
            else:
                allowed.add(code)
        result = frame.loc[~frame[code_column].map(symbol).isin(excluded)].copy()
        result.attrs['history_resolution_proof'] = self.proof(required_fields=requested,start=start,end=end,
            consumer=consumer,allowed_codes=allowed,excluded_codes=excluded)
        result.attrs['history_resolution_holds'] = reasons
        return result


def policy_for_shared(shared_root):
    return ResolutionPolicy(Path(shared_root)/'assets/hk_0_2')


def verify_pool_quality(shared_root, provenance, signal_date, codes):
    """Validate the exact already-verified run, never substitute a latest run."""
    policy = policy_for_shared(shared_root)
    policy.check_panel(provenance.get('panel_sha256'))
    return policy.verify_proof(provenance.get('history_resolution_proof'), end=signal_date,
        consumer='HK_FROZEN_SCORE_PRICE121_TRADE_CURRENT_V1', codes=codes)


def guarded_frame(frame, shared_root, *, panel_sha256, **kwargs):
    policy = policy_for_shared(shared_root)
    policy.check_panel(panel_sha256)
    return policy.guard_frame(frame, **kwargs)


def guard_rebound_frame(frame, shared_root, *, panel_sha256, sessions, current_day=None):
    policy = policy_for_shared(shared_root)
    policy.check_panel(panel_sha256)
    proofs = []
    held = {}
    specifications = [(('high',),min(sessions['prior60']),max(sessions['prior60']),'HK_REBOUND_HIGH60_V1'),
                      (('trade',),min(sessions['previous5']),current_day or max(sessions['previous5']),'HK_REBOUND_VOLUME5_V1')]
    if current_day:
        specifications.append((('open','high','low','close','amount'),current_day,current_day,'HK_REBOUND_CURRENT_BAR_V1'))
    for requested,start,end,consumer in specifications:
        frame = policy.guard_frame(frame,required_fields=requested,start=start,end=end,consumer=consumer)
        proofs.append(policy.encode_proof(frame.attrs['history_resolution_proof']))
        held.update(frame.attrs['history_resolution_holds'])
    frame.attrs['history_resolution_proofs'] = proofs
    frame.attrs['history_resolution_holds'] = held
    return frame


def _check_score_coverage(proof, *, eligible_codes=None, selected_codes=()):
    """Structural check used while constructing a proof, never an admission gate."""
    coverage = proof.get('score_coverage')
    keys = {'eligible_codes','original_signal_codes','scoreable_signal_codes',
            'quality_quarantined_codes','missing_signal_codes'}
    if not isinstance(coverage,dict) or set(coverage) != keys:
        raise ResolutionError('HK_HISTORY_RESOLUTION_SCORE_COVERAGE_MISSING')
    sets = {}
    for name,value in coverage.items():
        if not isinstance(value,list) or value != sorted({symbol(code) for code in value}):
            raise ResolutionError('HK_HISTORY_RESOLUTION_SCORE_COVERAGE_INVALID')
        sets[name] = set(value)
    eligible,original = sets['eligible_codes'],sets['original_signal_codes']
    allowed,excluded = set(proof['allowed_codes']),set(proof['excluded_codes'])
    scoreable,quarantined = eligible & original & allowed,eligible & original & excluded
    if (allowed & excluded or sets['scoreable_signal_codes'] != scoreable
            or sets['quality_quarantined_codes'] != quarantined
            or sets['missing_signal_codes'] != eligible-scoreable-quarantined
            or (eligible_codes is not None and eligible != {symbol(c) for c in eligible_codes})
            or not {symbol(c) for c in selected_codes}.issubset(scoreable)):
        raise ResolutionError('HK_HISTORY_RESOLUTION_SCORE_COVERAGE_INVALID')
    return coverage


def validate_score_coverage(proof, *, policy, eligible_codes=None, selected_codes=()):
    """Consumer admission requires independent current-source recomputation."""
    policy._validate_score_admission(proof)
    return _check_score_coverage(proof,eligible_codes=eligible_codes,selected_codes=selected_codes)


def guard_score_frame(frame, policy, signal_date):
    """Actual model dependency: price/amount 120 plus shift predecessor; trade today.

    Proxy labels use high/close/pre_close/amount, and proxy memory uses at most
    120 market dates. Trade is a raw model feature only on the predicted day.
    Exclude a held code's full sequence before cross-sectional proxy labels;
    retain all original observations of clean codes, including listing age.
    """
    original_codes = {symbol(code) for code in frame['code_norm']}
    frame = policy.guard_frame(frame, required_fields=('open','high','low','close','amount'),
        end=signal_date,lookback=121,consumer='HK_SCORE_PRICE_AMOUNT_121_V1')
    price_holds = dict(frame.attrs['history_resolution_holds'])
    frame = policy.guard_frame(frame, required_fields=('trade',),start=signal_date,end=signal_date,
        consumer='HK_SCORE_CURRENT_TRADE_V1')
    holds = {**price_holds,**frame.attrs['history_resolution_holds']}
    allowed = {symbol(code) for code in frame['code_norm']}
    dates = frame['trade_date_compact'].map(day)
    proof = policy.proof(required_fields=FIELDS,start=dates.min() if not dates.empty else signal_date,
        end=signal_date,consumer='HK_FROZEN_SCORE_PRICE121_TRADE_CURRENT_V1',
        allowed_codes=allowed,excluded_codes=original_codes-allowed)
    frame.attrs['history_resolution_proof'] = proof
    frame.attrs['history_resolution_holds'] = holds
    return frame
