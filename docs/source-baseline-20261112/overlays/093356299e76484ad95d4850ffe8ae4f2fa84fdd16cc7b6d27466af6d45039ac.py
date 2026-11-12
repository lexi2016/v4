"""Read-only research adapter over existing, verified stage artifacts.

No producer, acquisition, lock, publication, or fallback data root is used here.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Callable

from infrastructure.market_time import SHANGHAI, as_shanghai, parse_shanghai, shanghai_now
from stage_center.contracts import EIGHT_STAGES, SAFETY_FLAGS
from stage_center.raw_store import RawStore, canonical_sha, _window_bounds
from stage_center.selection import SelectionStore


def normalize_symbol(value: str) -> tuple[str, str]:
    text = str(value).strip().upper()
    prefix = re.fullmatch(r'(SH|SZ|BJ|HK)\.(\d+)', text)
    if prefix:
        text = f'{prefix[2]}.{prefix[1]}'
    match = re.fullmatch(r'(\d{6})\.(SH|SZ|BJ)|(\d{5})\.(HK)', text)
    if not match:
        raise ValueError('full exchange-qualified security identity required')
    return text, 'HK_CONNECT' if text.endswith('.HK') else 'A_SHARE'


def normalize_date(value: str) -> str:
    text = str(value)
    if not re.fullmatch(r'\d{8}|\d{4}-\d{2}-\d{2}', text):
        raise ValueError('date must use YYYY-MM-DD or YYYYMMDD')
    return datetime.strptime(text.replace('-', ''), '%Y%m%d').date().isoformat()


def _root(value: Path | str | None) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('explicit absolute observation root required')
    for current in (path, *path.parents):
        if current.is_symlink():
            raise ValueError('observation root symlink forbidden')
    return path


def _bytes(root: Path, relative: str) -> bytes:
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts or '\\' in relative:
        raise ValueError('unsafe artifact reference')
    candidate = root / path
    for current in (candidate, *candidate.parents):
        if current.is_symlink():
            raise ValueError('artifact symlink forbidden')
    candidate.resolve().relative_to(root.resolve())
    return candidate.read_bytes()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pointer(root: Path, filename: str) -> dict:
    data = json.loads(_bytes(root,filename))
    if not isinstance(data,dict) or not isinstance(data.get('entries'),dict):
        raise ValueError('invalid stage pointer shape')
    if data.get('owner') != 'stage_center' or any(data.get(key) is not False for key in SAFETY_FLAGS):
        raise ValueError('invalid stage pointer authority')
    return data


def _number(value):
    if value is None or value == '' or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def _row(native: dict, symbol: str) -> dict:
    result = {'native': dict(native), 'symbol': symbol, 'source_symbol': native['code'],
        'quote_time': native.get('update_time') or None,
        'window_start': native.get('window_start') or None,
        'window_end': native.get('window_end') or None,
        'temporal_cutoff_safe': native.get('temporal_cutoff_safe') == 'True', 'missing_fields': {}}
    for field in ('last_price','open_price','high_price','low_price','prev_close_price','turnover','volume','bar_count'):
        result[field] = _number(native.get(field))
        if result[field] is None:
            result['missing_fields'][field] = 'NOT_PROVIDED' if native.get(field) in (None,'') else 'INVALID_NUMBER'
    return result


def _metrics(rows: list[dict]) -> dict:
    # Raw verification has already checked native quote timestamps and dates.
    row = max(rows, key=lambda item: parse_shanghai(item['quote_time'])) if rows else {}
    price, previous = row.get('last_price'), row.get('prev_close_price')
    change = ((price / previous - 1) * 100) if price is not None and previous is not None and previous > 0 else None
    values = {'price':price, 'previous_close':previous, 'change_pct':change,
        'volume':row.get('volume'), 'turnover':row.get('turnover'), 'quote_time':row.get('quote_time')}
    return {**values, 'missing_reasons':[f'{key.upper()}_UNAVAILABLE' for key,value in values.items() if value is None],
        'price_basis':'SOURCE_REPORTED_UNVERIFIED',
        'historical_support_comparison':'UNAVAILABLE_PRICE_BASIS_UNVERIFIED',
        'historical_volume_ratio':None,
        'historical_volume_ratio_reason':'COMPARABLE_HISTORICAL_WINDOW_UNAVAILABLE'}


def _timestamps(manifest: dict, receipt: dict) -> dict:
    # Preserve every declaration. Later fields/evidence cannot erase a late timestamp.
    fields = ('captured_at','collected_at','available_at','received_at')
    declarations,issues = [],[]
    def add(source,key,value):
        item = {'source':source,'field':key,'value':value,'parsed_at':None}
        try:
            stamp = datetime.fromisoformat(str(value).replace('Z','+00:00'))
            if stamp.tzinfo is None:
                issues.append('TIMESTAMP_TIMEZONE_UNCONFIRMED')
            else:
                item['parsed_at'] = as_shanghai(stamp).isoformat()
        except ValueError:
            issues.append('INVALID_TIMESTAMP_DECLARATION')
        declarations.append(item)
    for label,payload in (('manifest',manifest),('receipt',receipt)):
        for key in fields:
            if payload.get(key) is not None:
                add(label,key,payload[key])
        for index,item in enumerate(payload.get('source_evidence',[])):
            key,sep,value = str(item).partition('=')
            if sep and key in fields:
                add(f'{label}.source_evidence[{index}]',key,value)
    summaries = {}
    for label,aliases in (('captured_at',fields[:2]),('available_at',fields[2:])):
        valid = [item for item in declarations if item['field'] in aliases and item['parsed_at']]
        distinct = {item['parsed_at'] for item in valid}
        if len(distinct) > 1:
            issues.append(f'CONFLICTING_{label.upper()}_DECLARATIONS')
        summaries[label] = max(valid,key=lambda item:item['parsed_at'])['value'] if valid else None
    return {**summaries,'timestamp_evidence':declarations,'timestamp_missing_reasons':list(dict.fromkeys(issues))}


def _temporal(raw: dict, rows: list[dict], cutoff: datetime, today) -> tuple[str,str,list[str]]:
    evidence = ' '.join(str(x) for x in [*raw.get('source_evidence',[]),*raw.get('cannot_confirm',[])]).upper()
    afterfact = any(marker in evidence for marker in ('BACKFILL','AFTERFACT','AFTER_TARGET_CUTOFF','NOT_PIT','PIT_SAFE=FALSE','LATE'))
    timestamps = [parse_shanghai(item['parsed_at']) for item in raw['timestamp_evidence'] if item['parsed_at']]
    proof_reasons = []
    proofs = []
    for label in ('manifest','receipt'):
        payload = raw[label]
        proof = payload.get('temporal_cutoff_safe')
        proofs.append(proof)
        if proof is not True:
            state = 'MISSING' if 'temporal_cutoff_safe' not in payload else ('FALSE' if proof is False else 'INVALID')
            proof_reasons.append(f'{label.upper()}_TEMPORAL_PROOF_{state}')
    for row in rows:
        proof = row.get('temporal_cutoff_safe')
        proofs.append(proof)
        if proof is not True:
            proof_reasons.append('ROW_TEMPORAL_PROOF_FALSE' if proof is False else 'ROW_TEMPORAL_PROOF_INVALID')
    if any(proof is True for proof in proofs) and any(proof is False for proof in proofs):
        proof_reasons.append('TEMPORAL_PROOF_CONFLICT')
    proof_reasons = list(dict.fromkeys(proof_reasons))
    unsafe = bool(proof_reasons)
    if any(stamp > cutoff for stamp in timestamps):
        state = 'LATE'
    elif unsafe or afterfact:
        state = 'UNSAFE'
    elif timestamps and not raw['timestamp_missing_reasons'] and all(stamp.date() == cutoff.date() for stamp in timestamps) and all(
            stamp >= parse_shanghai(row['quote_time']) for stamp in timestamps for row in rows):
        state = 'TIMELY'
    else:
        state = 'UNKNOWN'
    mode = 'RETROSPECTIVE' if cutoff.date() < today or afterfact or state in ('LATE','UNSAFE') else ('REALTIME_OBSERVATION' if state == 'TIMELY' else 'UNCONFIRMED')
    return state,mode,proof_reasons


class OpeningObservationService:
    def __init__(self, *, raw_root: Path | str | None = None,
            selection_root: Path | str | None = None, now: Callable[[],datetime] = shanghai_now):
        self.raw_root = _root(raw_root)
        self.selection_root = _root(selection_root)
        self.now = now

    def _raw(self, compact: str, stage_id: str, market: str, symbol: str):
        root = self.raw_root
        latest = _pointer(root,'latest.json')
        if f'{compact}/{stage_id}/{market}' not in latest.get('entries',{}):
            raise FileNotFoundError('raw slot missing')
        verified = RawStore(root).verify_latest(compact,stage_id,market)['verified']
        artifact_bytes = _bytes(root,verified['artifact_relative'])
        manifest_bytes = _bytes(root,verified['manifest_relative'])
        receipt_bytes = _bytes(root,verified['receipt_relative'])
        manifest,receipt = json.loads(manifest_bytes),json.loads(receipt_bytes)
        if (_sha(artifact_bytes) != verified['artifact_sha256'] or canonical_sha(manifest) != verified['manifest_sha256']
                or canonical_sha(receipt) != verified['receipt_sha256']):
            raise ValueError('raw changed during verified read')
        native_rows = list(csv.DictReader(io.StringIO(artifact_bytes.decode('utf-8-sig'),newline='')))
        rows,unresolved = [],[]
        for native in native_rows:
            # The native verifier intentionally projects RAW_FIELDS; enforce CSV identity here.
            if native.get('trade_date') != compact or native.get('bar_time') != native.get('update_time','').split(' ',1)[-1]:
                raise ValueError('raw CSV identity mismatch')
            if market == 'A_SHARE' and re.fullmatch(r'A\.\d{6}',str(native.get('code','')).upper()):
                unresolved.append(native['code'])
                continue
            native_symbol,native_market = normalize_symbol(native.get('code'))
            if native_market != market:
                raise ValueError('raw security market mismatch')
            if native_symbol == symbol:
                rows.append(_row(native,symbol))
        timestamps = _timestamps(manifest,receipt)
        identity = {key:value for key,value in manifest.items()
            if any(token in key.lower() for token in ('pool','revision','signal_date','source_date'))}
        identity['source_evidence'] = [item for item in manifest.get('source_evidence',[])
            if any(token in str(item).lower() for token in ('pool','revision','signal_date','source_date'))]
        native_counts = {key:manifest.get(key) for key in ('requested_rows','source_rows','coverage_ratio')}
        return {**verified,**native_counts,'manifest':manifest,'receipt':receipt,
            'coverage_missing_reasons':[f'{key.upper()}_NOT_PROVIDED' for key,value in native_counts.items() if value is None],
            'manifest_file_sha256':_sha(manifest_bytes),'receipt_file_sha256':_sha(receipt_bytes),
            **timestamps,'pool_identity':identity,
            'unresolved_source_symbols':list(dict.fromkeys(unresolved)),
            'identity_missing_reasons':['AMBIGUOUS_A_SOURCE_IDENTITY','FULL_SECURITY_IDENTITY_UNAVAILABLE'] if unresolved else [],
            'coverage_scope':'VERIFIED_RAW_INPUT_ONLY'}, rows

    def _selection(self,compact: str,stage_id: str,market: str,symbol: str,raw):
        root = self.selection_root
        latest = _pointer(root,'selection_latest.json')
        entry = latest.get('entries',{}).get(f'{compact}/{stage_id}/{market}')
        if not entry:
            raise FileNotFoundError('selection slot missing')
        store = SelectionStore(root)
        envelope = store.read_verified(compact,stage_id,market)
        verified = store._verify_run(compact,stage_id,market,entry['run_id'])
        if envelope != verified['envelope'] or any(entry.get(key) != verified[key] for key in ('manifest_sha256','receipt_sha256')):
            raise ValueError('selection changed during verified read')
        if (envelope.get('trade_date'),envelope.get('stage_id'),envelope.get('market')) != (compact,stage_id,market):
            raise ValueError('selection envelope identity mismatch')
        if any(envelope.get(key) is not False for key in SAFETY_FLAGS):
            raise ValueError('selection envelope unsafe flags')
        selected,unresolved = False,[]
        for row in envelope.get('rows',[]):
            if market == 'A_SHARE' and re.fullmatch(r'A\.\d{6}',str(row.get('code','')).upper()):
                unresolved.append(row['code'])
                continue
            normalized,row_market = normalize_symbol(row.get('code'))
            if row_market != market:
                raise ValueError('selection row market mismatch')
            selected |= normalized == symbol
        binding = (envelope.get('raw_artifact_sha256') == raw['artifact_sha256']) if raw else None
        return {'envelope':envelope,'provenance':{k:v for k,v in verified.items() if k != 'envelope'},
            'coverage_scope':'STAGE_RECOMMENDATIONS_TOP10_ONLY','selected_symbol_present':True if selected else (None if unresolved else False),
            'unresolved_source_symbols':list(dict.fromkeys(unresolved)),
            'raw_binding_matches':binding,'missing_reasons':
                (['SELECTION_RAW_BINDING_MISMATCH'] if binding is False else []) +
                (['AMBIGUOUS_A_SOURCE_IDENTITY','FULL_SECURITY_IDENTITY_UNAVAILABLE'] if unresolved else [])}

    def get(self, *, date: str, symbol: str, candidate_source_date: str | None = None) -> dict:
        target = normalize_date(date)
        symbol,market = normalize_symbol(symbol)
        source = normalize_date(candidate_source_date) if candidate_source_date is not None else None
        if source is not None and source >= target:
            raise ValueError('candidate_source_date must precede target date')
        compact = target.replace('-','')
        now = as_shanghai(self.now())
        stages = []
        for spec in EIGHT_STAGES[:3]:
            # Market-specific observation bound differs from the scheduler for HK auction.
            _start,native_cutoff = _window_bounds(compact,spec.stage_id,market)
            cutoff = native_cutoff.replace(tzinfo=SHANGHAI)
            stage = {'stage_id':spec.stage_id,'window':spec.hk_window if market == 'HK_CONNECT' and spec.hk_window else spec.window,
                'cutoff_at':cutoff.strftime('%H:%M:%S'),'scheduled_cutoff_at':spec.cutoff,'availability':'UNAVAILABLE','missing_reasons':[],
                'source_status':None,'observation_mode':'UNAVAILABLE','temporal_state':'UNAVAILABLE',
                'raw':None,'selection':None,'rows':[],'metrics':_metrics([])}
            if cutoff > now:
                stage['availability'] = 'NOT_DUE'
                stage['missing_reasons'].append('STAGE_NOT_DUE')
                stages.append(stage)
                continue
            if self.raw_root is None:
                stage['availability'] = 'UNCONFIGURED'
                stage['missing_reasons'].append('RAW_ROOT_UNCONFIGURED')
            else:
                try:
                    raw,rows = self._raw(compact,spec.stage_id,market,symbol)
                    stage.update(raw=raw,rows=rows,metrics=_metrics(rows),source_status=raw['source_status'],availability='AVAILABLE')
                    stage['temporal_state'],stage['observation_mode'],proof_reasons = _temporal(raw,rows,cutoff,now.date())
                    stage['missing_reasons'].extend(proof_reasons)
                    stage['missing_reasons'].extend(raw['identity_missing_reasons'])
                    stage['missing_reasons'].extend(raw['timestamp_missing_reasons'])
                    if not rows:
                        stage['missing_reasons'].append('COVERAGE_CANNOT_CONFIRM_IDENTITY_UNRESOLVED' if raw['unresolved_source_symbols'] else 'SYMBOL_NOT_COVERED_BY_RAW')
                except FileNotFoundError:
                    stage['availability'] = 'MISSING'
                    stage['missing_reasons'].append('RAW_ARTIFACT_MISSING')
                except (ValueError,OSError,KeyError,TypeError):
                    stage['availability'] = 'FAILED'
                    stage['missing_reasons'].append('RAW_VERIFICATION_FAILED')
            if self.selection_root is None:
                stage['missing_reasons'].append('SELECTION_ROOT_UNCONFIGURED')
            else:
                try:
                    stage['selection'] = self._selection(compact,spec.stage_id,market,symbol,stage['raw'])
                except FileNotFoundError:
                    stage['missing_reasons'].append('SELECTION_ARTIFACT_MISSING')
                except (ValueError,OSError,KeyError,TypeError):
                    stage['missing_reasons'].append('SELECTION_VERIFICATION_FAILED')
            stages.append(stage)
        count = sum(bool(stage['rows']) for stage in stages)
        return {'schema_version':'research.opening_observation.v1','trade_date':target,'symbol':symbol,'market':market,
            'candidate_context':{'source_date':source,'authority':'CLIENT_CONTEXT_ONLY','stage_input_identity_verified':False},
            'generated_at':now.isoformat(),'status':'AVAILABLE' if count == len(stages) else ('PARTIAL' if count else 'UNAVAILABLE'),
            'stages':stages,'write_performed':False,'RESEARCH_ONLY':True,'research_only':True,**SAFETY_FLAGS}
