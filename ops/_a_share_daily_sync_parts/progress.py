"""ops.a_share_daily_sync: progress (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


# Historical seed evidence is opt-in and read-only.  It never enters the
# provider-response validator or rewrites a raw price/volume field.
import hashlib
import json
import math
from datetime import datetime
from numbers import Real
from pathlib import Path

_SEED_EVIDENCE_SCHEMA = 'a_share_daily_sync.seed_adjustment_evidence.v1'


def _evidence_bytes(ref, *, limit=128 * 1024 * 1024):
    if not isinstance(ref, dict):
        raise ValueError('missing_reference')
    path = Path(ref.get('path', ''))
    expected = ref.get('sha256')
    if (not path.is_absolute() or not isinstance(expected, str) or
            len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected)):
        raise ValueError('invalid_reference')
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError('reference_shape_or_size')
    data = path.read_bytes()
    if len(data) > limit or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('reference_sha256_mismatch')
    return data


def _evidence_json(ref):
    value = json.loads(_evidence_bytes(ref))
    if not isinstance(value, dict):
        raise ValueError('reference_not_object')
    return value


def _evidence_day(value):
    if isinstance(value, bool) or not isinstance(value, int) or len(str(value)) != 8:
        raise ValueError('date_not_integer')
    datetime.strptime(str(value), '%Y%m%d')
    return value


def _evidence_number(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError('coefficient_not_finite')
    if positive and value <= 0:
        raise ValueError('coefficient_not_positive')
    return float(value)


def _seed_evidence_bundle(context, target_date):
    if 'bundle' in context:
        return context['bundle']
    if 'load_error' in context:
        raise ValueError(context['load_error'])
    # The expected digest is supplied by trusted invocation configuration,
    # never from the self-described evidence chain.  The caller's release
    # manifest/config approval is the trust root; this module only enforces it.
    expected = context.get('expected_sha256')
    if (not isinstance(expected, str) or len(expected) != 64 or
            any(c not in '0123456789abcdef' for c in expected)):
        raise ValueError('external_descriptor_pin_missing_or_malformed')
    path = Path(context['path'])
    if not path.is_absolute() or not path.is_file() or path.stat().st_size > 64 * 1024:
        raise ValueError('descriptor_shape_or_size')
    data = path.read_bytes()
    if len(data) > 64 * 1024:
        raise ValueError('descriptor_shape_or_size')
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('external_descriptor_pin_mismatch')
    descriptor = json.loads(data)
    if descriptor.get('schema_version') != _SEED_EVIDENCE_SCHEMA:
        raise ValueError('descriptor_schema')
    snapshot_ref = descriptor['snapshot']
    snapshot = _evidence_json(snapshot_ref)
    receipt = _evidence_json(descriptor['adoption_receipt'])
    if (receipt.get('schema') != 'ACTUAL_COUPLED_ADOPTION_READBACK_R1' or
            receipt.get('status') != 'COMMITTED_PAIR_AND_FIVE_METADATA_READBACK_MATCH' or
            receipt.get('journal_status') != 'COMMITTED' or
            receipt.get('research_only') is not True or
            any(receipt.get(k) is not False for k in ('production_allowed', 'buy_gate_updated', 'orders_sent'))):
        raise ValueError('adoption_not_committed_research')
    if not any(r.get('sha256') == snapshot_ref['sha256'] and
               Path(r.get('path', '')).name == 'qfq_adjustment_input.json'
               for r in receipt.get('five_metadata', []) if isinstance(r, dict)):
        raise ValueError('snapshot_not_adopted')
    roles = receipt['roles']
    selector, backtest = roles['selector'], roles['backtest']
    if (not selector.get('generation_id') or not selector.get('input_sha256') or
            any(selector.get(k) != backtest.get(k) for k in ('generation_id', 'input_sha256'))):
        raise ValueError('adoption_pair_identity')
    journal = _evidence_json(receipt['journal'])
    if (journal.get('status') != 'COMMITTED' or not any(
            r.get('after', {}).get('sha256') == snapshot_ref['sha256'] and
            Path(r.get('path', '')).name == 'qfq_adjustment_input.json'
            for r in journal.get('metadata', []) if isinstance(r, dict))):
        raise ValueError('journal_snapshot_identity')
    if (snapshot.get('schema') != 'a_share_qfq_adjustment_input_v1' or
            snapshot.get('price_basis') != 'QFQ_ASOF' or
            snapshot.get('convention') != 'FUTU_AFFINE_WITH_EXPLICIT_TDX_UNSUPPORTED_FALLBACK_V1'):
        raise ValueError('snapshot_convention')
    asof = _evidence_day(snapshot['asof_date'])
    coverage = _evidence_day(snapshot['coverage_end_date'])
    if coverage > asof or asof > target_date:
        raise ValueError('snapshot_date_scope')
    checkpoint = _evidence_json(descriptor['factor_cache_checkpoint'])
    if checkpoint.get('asof_date') != asof:
        raise ValueError('provider_asof_mismatch')
    bundle = {'descriptor': descriptor, 'descriptor_sha256': hashlib.sha256(data).hexdigest(),
              'snapshot': snapshot, 'checkpoint': checkpoint, 'coverage': coverage,
              'generation_id': selector['generation_id'], 'symbols': {}}
    context['bundle'] = bundle
    return bundle


def _tdx_seed_events(bundle, item, symbol):
    # The externally pinned descriptor supplies an explicit TDX trust closure.
    # It does not assert Futu equivalence or enter incoming-response validation.
    import struct
    if not symbol.endswith('.BJ'):
        raise ValueError('tdx_symbol_market')
    closure_ref = bundle['descriptor']['tdx_seed_sources'][symbol]
    closure = _evidence_json(closure_ref)
    if (closure.get('schema') != 'TDX_GBBQ_ORIGINAL_WIRE_SINGLE_SYMBOL_CLOSURE_V1' or
            closure.get('symbol') != symbol or closure.get('asof_date') != bundle['snapshot']['asof_date'] or
            closure.get('compute_start_date') != item.get('compute_start_date') or
            closure.get('wire_schema') != '<B7sIBffff' or closure.get('term_encoding') != 'IEEE754_BINARY32' or
            closure.get('source_kind') != 'TDX_GBBQ_CATEGORY1_AFFINE_BJ_V1_NOT_FUTU_EQUIVALENT' or
            closure.get('futu_equivalence') is not False):
        raise ValueError('tdx_source_kind_or_scope')
    refs = closure['source_files']
    if len(refs) != 5 or len({(r['path'], r['sha256']) for r in refs}) != 5:
        raise ValueError('tdx_source_closure')
    if closure['policy'] not in refs or closure['symbol_rows'] not in refs:
        raise ValueError('tdx_source_member_missing')
    proof = _evidence_json(closure['wire_result'])
    wire = _evidence_json(closure['wire_rows'])
    saved = _evidence_json(closure['symbol_rows'])
    policy = _evidence_json(closure['policy'])
    if (proof.get('schema') != 'GENUINE_ORIGINAL_WIRE_SINGLE_SYMBOL_PROOF' or
            proof.get('code') != symbol or closure.get('raw') not in refs or
            closure.get('decoder') not in refs or closure['raw']['path'] == closure['decoder']['path'] or
            closure['raw']['sha256'] == closure['decoder']['sha256'] or
            proof.get('original_raw') != closure['raw'] or
            proof.get('original_decoder') != closure['decoder'] or proof.get('decoder_calls') != 1 or
            proof.get('original_JSON_double_precision15_roundtrip') is not True or
            proof.get('true_price_term_inputs_equal_prior_original_converter') is not True or
            proof.get('event_coefficients_cast') is not False or
            proof.get('original_converter_output_reused') != closure['original_converter'] or
            proof.get('events') != closure.get('events') or
            saved.get('ts_code') != symbol or wire.get('code') != symbol or
            wire.get('rows') != saved.get('rows') or proof.get('wire_rows') != len(saved['rows'])):
        raise ValueError('tdx_genuine_wire_binding')
    if (policy.get('policy_id') != 'TDX_GBBQ_CATEGORY1_AFFINE_BJ_V1' or
            not policy.get('controller') or policy.get('RESEARCH_ONLY') is not True or
            any(policy.get(k) is not False for k in ('production_allowed', 'buy_gate_updated', 'orders_sent'))):
        raise ValueError('tdx_category_policy')
    terms = ('hongli_panqianliutong', 'peigujia_qianzongguben',
             'songgu_qianzongguben', 'peigu_houzongguben')
    witnesses = {}
    for witness in wire['exact_term_evidence']:
        key = (witness['date'], witness['category'], witness['field'])
        if key in witnesses:
            raise ValueError('tdx_duplicate_term_witness')
        witnesses[key] = witness
    compute_start = _evidence_day(item['compute_start_date'])
    events, seen_rows = {}, set()
    for row in saved['rows']:
        day, category = _evidence_day(row['datetime']), row['category']
        if (type(category) is not int or row.get('ts_code') != symbol or
                row.get('code') != symbol.split('.')[0] or row.get('market') != 2 or
                (day, category) in seen_rows):
            raise ValueError('tdx_row_identity')
        seen_rows.add((day, category))
        if not compute_start < day <= bundle['coverage']:
            continue
        action = policy['category_policy'].get(str(category))
        if action == 'CAPITAL_SNAPSHOT_RETAINED_NOT_PRICE_ACTION_IN_THIS_CONVENTION':
            continue
        if category != 1 or action != 'PRICE_ACTION_PER10_CASH_RIGHTS_BONUS_AFFINE':
            raise ValueError('tdx_unexplained_category')
        restored = []
        for field in terms:
            value = _evidence_number(row[field])
            # Restore only original wire term fields, never event coefficients.
            true_value = struct.unpack('<f', struct.pack('<f', value))[0]
            witness = witnesses[(day, category, field)]
            if (witness['stored_JSON'] != row[field] or
                    witness['true_wire_float'] != true_value or
                    witness['true_wire_hex'] != true_value.hex()):
                raise ValueError('tdx_wire_term_parity')
            restored.append(true_value)
        cash, rights_price, bonus, rights = restored
        # Exact arithmetic/order of the accepted original category1 converter.
        denominator = 1 + (bonus + rights) / 10
        if not math.isfinite(denominator) or denominator <= 0 or day in events:
            raise ValueError('tdx_event_denominator_or_duplicate')
        events[day] = (1 / denominator,
                       (-cash / 10 + rights_price * rights / 10) / denominator,
                       denominator)
    accepted = {}
    for row in item['events']:
        day = _evidence_day(row['ex_date'])
        if day in accepted:
            raise ValueError('duplicate_event_date')
        accepted[day] = tuple(_evidence_number(row[k], positive=k != 'b') for k in ('a', 'b', 'volume_a'))
    expected = {d: v for d, v in accepted.items() if compute_start < d <= bundle['coverage']}
    declared = {}
    for event in closure['events']:
        day = _evidence_day(event['ex_date'])
        if day in declared:
            raise ValueError('tdx_duplicate_declared_event')
        declared[day] = (event['a'], event['b'], event['volume_a'])
    if events != expected or events != declared:
        raise ValueError('tdx_adopted_event_conflict')
    return accepted, closure_ref


def _seed_symbol_evidence(scope, bundle, symbol):
    if symbol in bundle['symbols']:
        return bundle['symbols'][symbol]
    item = bundle['snapshot']['symbols'][symbol]
    start = _evidence_day(item['history_start_date'])
    end = _evidence_day(item['history_end_date'])
    if (item.get('event_coverage_complete') is not True or
            item.get('source_method') not in ('FUTU_GET_REHAB_AFFINE', 'TDX_OFFICIAL_TERMS_BOUND_CONVERSION') or
            item.get('raw_resolution') != 'ARCHIVE_PRIMARY_NATIVE_MISSING_AND_TAIL_V2'):
        raise ValueError('symbol_evidence_policy')
    if item['source_method'] == 'TDX_OFFICIAL_TERMS_BOUND_CONVERSION':
        accepted, response_ref = _tdx_seed_events(bundle, item, symbol)
    else:
        cache_item = bundle['checkpoint']['symbols'][symbol]
        if cache_item.get('status') != 'OK' or cache_item.get('asof_date') != bundle['snapshot']['asof_date']:
            raise ValueError('provider_status')
        response_ref = cache_item['response']
        response = _evidence_json(response_ref)
        code, market = symbol.split('.')
        if (response.get('source') != 'Futu OpenD get_rehab' or
                response.get('code') != f'{market}.{code}' or type(response.get('return_code')) is not int or
                response.get('return_code') != 0):
            raise ValueError('provider_identity')

        def event_map(rows, provider=False):
            events = {}
            for row in rows:
                if provider:
                    date_text = row['ex_div_date']
                    if not isinstance(date_text, str):
                        raise ValueError('provider_event_date')
                    day = int(datetime.strptime(date_text[:10], '%Y-%m-%d').strftime('%Y%m%d'))
                    coefficients = (row['forward_adj_factorA'], row['forward_adj_factorB'], row['backward_adj_factorA'])
                else:
                    day = _evidence_day(row['ex_date'])
                    coefficients = (row['a'], row['b'], row['volume_a'])
                if day in events:
                    raise ValueError('duplicate_event_date')
                events[day] = tuple(_evidence_number(v, positive=i != 1) for i, v in enumerate(coefficients))
            return events

        accepted = event_map(item['events'])
        provider = event_map(response['rows'], True)
        # A same-date label is insufficient: all accepted in-coverage coefficients
        # must equal the original provider data, with no missing/extra event.
        in_scope = lambda events: {d: v for d, v in events.items() if start <= d <= bundle['coverage']}
        if in_scope(accepted) != in_scope(provider):
            raise ValueError('provider_event_conflict')
    refs = item['raw_files']
    roles = [r.get('source_role') for r in refs]
    if (not refs or len(set(roles)) != len(roles) or 'archive' not in roles or
            any(role not in ('archive', 'native') for role in roles)):
        raise ValueError('raw_resolution_unsupported')
    selected = {}
    codec = _v4_global(scope, 'DAY_STRUCT')
    # Same accepted whole-row policy: archive wins; native contributes only
    # missing dates.  Never cherry-pick a matching conflicting alternative.
    for ref in sorted(refs, key=lambda r: r['source_role'] != 'archive'):
        data = _evidence_bytes(ref, limit=4 * 1024 * 1024)
        if not data or len(data) % codec.size:
            raise ValueError('raw_source_shape')
        seen = set()
        previous = 0
        floor = ref.get('from_date_exclusive', 0)
        for index, offset in enumerate(range(0, len(data), codec.size)):
            row = data[offset:offset + codec.size]
            day, _o, _h, _l, close, _amount, _volume, _reserved = codec.unpack(row)
            _evidence_day(day)
            if day in seen or day < previous:
                raise ValueError('raw_source_date_order')
            seen.add(day)
            previous = day
            if day > floor and day not in selected:
                selected[day] = {'close': close / 100.0, 'source_ref': dict(ref),
                                 'row_index': index, 'row_sha256': hashlib.sha256(row).hexdigest()}
    evidence = {'start': start, 'end': end, 'events': accepted, 'selected': selected,
                'provider_response': response_ref}
    if item['source_method'] == 'TDX_OFFICIAL_TERMS_BOUND_CONVERSION':
        evidence['source_kind'] = 'TDX_GBBQ_CATEGORY1_AFFINE_BJ_V1_NOT_FUTU_EQUIVALENT'
    bundle['symbols'][symbol] = evidence
    return evidence


def _explain_seed_pair(scope, context, symbol, target_date, previous_date, current_date, previous_close, close):
    record = {'symbol': symbol, 'previous_date': previous_date, 'current_date': current_date,
              'previous_close': previous_close, 'close': close, 'raw_ratio': close / previous_close,
              'status': 'UNEXPLAINED', 'evidence_path': str(context['path']),
              'expected_descriptor_sha256': context.get('expected_sha256') if isinstance(context.get('expected_sha256'), str) else None}
    try:
        try:
            bundle = _seed_evidence_bundle(context, target_date)
        except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError) as error:
            context['load_error'] = str(error)
            raise
        evidence = _seed_symbol_evidence(scope, bundle, symbol)
        if not evidence['start'] <= previous_date < current_date <= min(bundle['coverage'], evidence['end']):
            raise ValueError('pair_coverage_missing')
        selected = evidence['selected']
        if any(d not in selected or selected[d]['close'] != value
               for d, value in ((previous_date, previous_close), (current_date, close))):
            raise ValueError('pair_raw_basis_conflict')
        events = [(day, values) for day, values in sorted(evidence['events'].items())
                  if previous_date < day <= current_date]
        if not events:
            raise ValueError('pair_event_missing')
        denominator = previous_close
        for _day, (a, b, _volume_a) in events:
            denominator = denominator * a + b
            if not math.isfinite(denominator) or denominator <= 0:
                raise ValueError('transformed_close_not_positive_finite')
        ratio = close / denominator
        maximum = _v4_global(scope, 'MAX_CROSS_DAY_CLOSE_RATIO')
        if not math.isfinite(ratio) or not 1.0 / maximum <= ratio <= maximum:
            raise ValueError('transformed_ratio_out_of_bounds')
        record.update(status='EXPLAINED_ACCEPTED_AFFINE', transformed_previous_close=denominator,
                      transformed_ratio=ratio, events=[{'ex_date': d, 'a': v[0], 'b': v[1], 'volume_a': v[2]} for d, v in events],
                      pair_sources=[selected[previous_date], selected[current_date]],
                      provider_response=evidence['provider_response'], generation_id=bundle['generation_id'],
                      descriptor_sha256=bundle['descriptor_sha256'],
                      snapshot=bundle['descriptor']['snapshot'], adoption_receipt=bundle['descriptor']['adoption_receipt'])
        if 'source_kind' in evidence:
            record['source_kind'] = evidence['source_kind']
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError) as error:
        record['reason'] = str(error)
    context.setdefault('records', []).append(record)
    return record['status'] == 'EXPLAINED_ACCEPTED_AFFINE'


# This separate optional method uses retained primary IPO documents and the
# existing calendar.  It never manufactures adjustment events or validates
# provider-response bars, and never changes the original affine method.
def _ipo_docx_paragraphs(ref):
    import io
    import zipfile
    from xml.etree import ElementTree
    try:
        with zipfile.ZipFile(io.BytesIO(_evidence_bytes(ref, limit=4 * 1024 * 1024))) as archive:
            if archive.getinfo('word/document.xml').file_size > 4 * 1024 * 1024:
                raise ValueError('ipo_rule_document_size')
            root = ElementTree.fromstring(archive.read('word/document.xml'))
    except (zipfile.BadZipFile, ElementTree.ParseError, KeyError) as error:
        raise ValueError('ipo_rule_document_invalid') from error
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    return [''.join(t.text or '' for t in p.findall('.//w:t', ns))
            for p in root.findall('.//w:p', ns)]


def _ipo_symbol_evidence(scope, bundle, symbol):
    import re
    import sys
    import types
    from datetime import timedelta
    from html import unescape
    from urllib.parse import parse_qs, urlsplit
    cache = bundle.setdefault('ipo_symbols', {})
    if symbol in cache:
        return cache[symbol]
    spec = bundle['descriptor']['ipo_seed_boundaries'][symbol]
    if spec.get('type') != 'SSE_MAIN_BOARD_FIRST_IPO_FIRST_FIVE_SESSIONS' or not symbol.endswith('.SH'):
        raise ValueError('ipo_type_or_market_unknown')
    code = symbol.split('.')[0]
    listing = _evidence_day(spec['listing_date'])
    metadata_bytes = _evidence_bytes(spec['listing_metadata'])
    metadata = [json.loads(line) for line in metadata_bytes.decode('utf-8').splitlines() if symbol in line]
    metadata = [row for row in metadata if row.get('canonical_fields', {}).get('ts_code') == symbol]
    if len(metadata) != 1:
        raise ValueError('ipo_listing_identity_ambiguous')
    row = metadata[0]
    fields = row['canonical_fields']
    if (row.get('normalization_status') != 'NORMALIZED' or row.get('source_row_id') != spec['source_row_id'] or
            fields.get('security_code') != code or fields.get('listing_date') != str(listing)):
        raise ValueError('ipo_listing_identity_conflict')
    capture = _evidence_json(spec['ipo_index_capture'])
    url = urlsplit(capture['url'])
    query = parse_qs(url.query)
    if (url.scheme != 'https' or url.netloc != 'query.sse.com.cn' or
            url.path != '/security/stock/queryCompanyBulletinNew.do' or
            query.get('SECURITY_CODE') != [code] or query.get('BULLETIN_TYPE') != ['08'] or
            capture.get('http_status') != 200 or capture.get('sha256') != spec['ipo_index']['sha256']):
        raise ValueError('ipo_primary_index_source_conflict')
    raw = _evidence_bytes(spec['ipo_index'], limit=4 * 1024 * 1024).decode('utf-8').strip()
    callback = query.get('jsonCallBack', [''])[0]
    if raw.startswith('{'):
        index = json.loads(raw)
    elif re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', callback) and raw.startswith(callback + '(') and raw.endswith(')'):
        index = json.loads(raw[len(callback) + 1:-1])
    else:
        raise ValueError('ipo_index_envelope_unknown')
    # The original SSE endpoint groups disclosures by date.  Only its explicit
    # issuer code/type/title identifies this class, never symbol prefixes or
    # the recent date in a general company list.
    disclosures = [item for group in index['result'] for item in group]
    if len(disclosures) > 256:
        raise ValueError('ipo_index_scope_too_large')
    matches = [item for item in disclosures if item.get('SECURITY_CODE') == code and
               item.get('BULLETIN_TYPE_DESC') == '首次公开发行' and
               item.get('TITLE', '').endswith('首次公开发行股票主板上市公告书') and
               item.get('URL') == spec['ipo_document_href']]
    if len(matches) != 1:
        raise ValueError('ipo_first_public_offering_identity_unproven')
    publication = int(datetime.strptime(matches[0]['SSEDATE'], '%Y-%m-%d').strftime('%Y%m%d'))
    if publication > listing:
        raise ValueError('ipo_identity_publication_after_listing')
    notice = _evidence_bytes(spec['listing_notice'], limit=2 * 1024 * 1024).decode('utf-8')
    article = re.search(r'<div[^>]*class=[\"\x27]allZoom[\"\x27][^>]*>(.*?)</div>', notice, re.S)
    if article is None:
        raise ValueError('ipo_listing_notice_body_missing')
    text = re.sub(r'\s+', '', unescape(re.sub(r'<[^>]+>', '', article[1])))
    notice_code = re.search(r'证券代码为[\"“]?(\d{6})', text)
    notice_day = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日起上市交易', text)
    if (notice_code is None or notice_code[1] != code or notice_day is None or
            int(notice_day[1]) * 10000 + int(notice_day[2]) * 100 + int(notice_day[3]) != listing):
        raise ValueError('ipo_listing_notice_identity_conflict')
    rule = spec['rule']
    if rule.get('type') != 'SSE_MAIN_BOARD_FIRST_IPO_NO_PRICE_LIMIT' or rule.get('article') != '3.3.13' or rule.get('sessions') != 5:
        raise ValueError('ipo_rule_type_unknown')
    paragraphs = _ipo_docx_paragraphs(rule['document'])
    starts = [i for i, p in enumerate(paragraphs) if p.strip().startswith('3.3.13')]
    ends = [i for i, p in enumerate(paragraphs) if p.strip().startswith('3.3.14')]
    if len(starts) != 1 or len(ends) != 1 or ends[0] <= starts[0]:
        raise ValueError('ipo_rule_article_unknown')
    section = ''.join(paragraphs[starts[0]:ends[0]])
    if ('不实行价格涨跌幅限制' not in section or
            '首次公开发行上市的股票上市后的前5个交易日' not in section or
            '3.3.13' in ''.join(_ipo_docx_paragraphs(rule['deferred_document']))):
        raise ValueError('ipo_rule_exception_unproven_or_deferred')
    effective = re.findall(r'本规则自(\d{4})年(\d{1,2})月(\d{1,2})日起施行', ''.join(paragraphs))
    if len(effective) != 1:
        raise ValueError('ipo_rule_effective_date_unknown')
    effective = int(effective[0][0]) * 10000 + int(effective[0][1]) * 100 + int(effective[0][2])
    if _evidence_day(rule['effective_from']) != effective:
        raise ValueError('ipo_rule_effective_date_conflict')
    through = _evidence_day(rule['verified_through'])
    if not effective <= listing <= through:
        raise ValueError('ipo_rule_not_effective_for_listing')
    calendar_spec = spec['calendar']
    calendar_bytes = _evidence_bytes(calendar_spec['resolver'], limit=1024 * 1024)
    _evidence_bytes(calendar_spec['data'], limit=1024 * 1024)
    # Reuse the exact already-existing, approved calendar implementation in
    # memory.  Compile verified bytes to avoid pycache writes to an immutable
    # app; no new calendar module/file, source download, or SDK is introduced.
    module_name = '_seed_existing_calendar_' + calendar_spec['resolver']['sha256']
    modules = bundle.setdefault('ipo_calendar_modules', {})
    module = modules.get(module_name)
    if module is None:
        module = types.ModuleType(module_name)
        module.__file__ = calendar_spec['resolver']['path']
        previous_module = sys.modules.get(module_name)
        sys.modules[module_name] = module
        try:
            exec(compile(calendar_bytes, module.__file__, 'exec'), module.__dict__)
        except Exception as error:
            raise ValueError('ipo_existing_calendar_unavailable') from error
        finally:
            if previous_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = previous_module
        modules[module_name] = module
    calendar = module.load_market_calendar(Path(calendar_spec['data']['path']))
    _evidence_bytes(calendar_spec['data'], limit=1024 * 1024)
    sessions = []
    cursor = datetime.strptime(str(listing), '%Y%m%d').date()
    for _ in range(40):
        day = cursor.strftime('%Y%m%d')
        state = module.resolve_market_states(calendar, day)['a_share']
        if state == module.TradingDayState.UNKNOWN:
            raise ValueError('ipo_calendar_coverage_unknown')
        if state in (module.TradingDayState.FULL_TRADING_DAY, module.TradingDayState.HALF_TRADING_DAY_AM):
            sessions.append(int(day))
            if len(sessions) == 5:
                break
        cursor += timedelta(days=1)
    if len(sessions) != 5 or sessions[0] != listing:
        raise ValueError('ipo_listing_calendar_boundary_unknown')
    raw_ref = spec['raw_source']
    raw_bytes = _evidence_bytes(raw_ref, limit=4 * 1024 * 1024)
    codec = _v4_global(scope, 'DAY_STRUCT')
    if not raw_bytes or len(raw_bytes) % codec.size:
        raise ValueError('ipo_raw_source_shape')
    selected = {}
    raw_dates = []
    for offset in range(0, len(raw_bytes), codec.size):
        original = raw_bytes[offset:offset + codec.size]
        day, _o, _h, _l, close, _a, _v, _r = codec.unpack(original)
        _evidence_day(day)
        if raw_dates and day <= raw_dates[-1]:
            raise ValueError('ipo_raw_source_date_order')
        raw_dates.append(day)
        selected[day] = {'close': close / 100.0, 'row_index': offset // codec.size,
                         'row_sha256': hashlib.sha256(original).hexdigest(), 'source_ref': raw_ref}
    review = _evidence_json(spec['raw_review'])
    reviewed = review['codes'][symbol]
    if (review.get('schema') != 'REVIEWER_TYPED_SAME_INPUT_PASS_REUSE_R1' or
            review.get('verdict') != 'REVIEWED/PASS_ARCHIVE_ONLY_SOURCE_KEYS_AND_BYTES' or
            review.get('research_only') is not True or
            any(review.get(k) is not False for k in ('production_allowed', 'buy_gate_updated', 'orders_sent')) or
            reviewed.get('raw32_sha256') != raw_ref['sha256'] or reviewed.get('rows') != len(raw_dates) or
            reviewed.get('first_date') != raw_dates[0] or reviewed.get('last_date') != raw_dates[-1] or
            raw_dates[:5] != sessions):
        raise ValueError('ipo_complete_raw_source_unproven')
    evidence = dict(spec=spec, listing=listing, sessions=sessions, selected=selected,
                    effective=effective, through=through, disclosure=matches[0])
    cache[symbol] = evidence
    return evidence


def _explain_historical_seed_pair(scope, context, symbol, target_date, previous_date, current_date,
                                  previous_close, close, seed_bars):
    # Non-IPO descriptors/symbols retain the exact R3 affine implementation.
    try:
        bundle = _seed_evidence_bundle(context, target_date)
        ipo = bundle['descriptor'].get('ipo_seed_boundaries', {})
        if isinstance(ipo, dict) and symbol not in ipo:
            return _explain_seed_pair(scope, context, symbol, target_date, previous_date, current_date, previous_close, close)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return _explain_seed_pair(scope, context, symbol, target_date, previous_date, current_date, previous_close, close)
    record = dict(symbol=symbol, previous_date=previous_date, current_date=current_date,
                  previous_close=previous_close, close=close, raw_ratio=close / previous_close,
                  status='UNEXPLAINED', method='IPO_FIRST_FIVE_EXCHANGE_TRADING_SESSIONS',
                  evidence_path=str(context['path']), expected_descriptor_sha256=context.get('expected_sha256'))
    try:
        if not isinstance(ipo, dict):
            raise ValueError('ipo_boundary_map_not_object')
        evidence = _ipo_symbol_evidence(scope, bundle, symbol)
        sessions = evidence['sessions']
        if (previous_date not in sessions or current_date not in sessions or
                not evidence['effective'] <= previous_date < current_date <= min(evidence['through'], bundle['coverage'])):
            raise ValueError('ipo_pair_outside_first_five_or_rule_coverage')
        prefix = seed_bars[:5]
        dates = [_v4_global(scope, 'day_int')(bar) for bar in prefix]
        if dates != sessions:
            raise ValueError('ipo_seed_truncated_or_missing_session')
        if any(day not in evidence['selected'] or evidence['selected'][day]['close'] != float(bar['close'])
               for day, bar in zip(dates, prefix)):
            raise ValueError('ipo_pair_or_prefix_raw_basis_conflict')
        spec = evidence['spec']
        record.update(status='EXPLAINED_IPO_FIRST_FIVE_SESSIONS', listing_date=evidence['listing'],
                      market_first_five_sessions=sessions, previous_session_ordinal=sessions.index(previous_date) + 1,
                      current_session_ordinal=sessions.index(current_date) + 1,
                      pair_sources=[evidence['selected'][previous_date], evidence['selected'][current_date]],
                      descriptor_sha256=bundle['descriptor_sha256'], ipo_disclosure=evidence['disclosure'],
                      identity_refs={key: spec[key] for key in ('listing_metadata', 'ipo_index', 'ipo_index_capture', 'listing_notice')},
                      rule=spec['rule'], calendar=spec['calendar'], raw_review=spec['raw_review'])
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError) as error:
        record['reason'] = str(error)
    context.setdefault('records', []).append(record)
    return record['status'] == 'EXPLAINED_IPO_FIRST_FIVE_SESSIONS'


def __local_history_status_body(_v4_scope, /, path, target_date, *, seed_evidence=None, symbol=None):
    """Validate existing source bytes before an accepted-only handoff.

    The formula reader currently keeps the last duplicate key.  This gate
    audits the source in its original order first, so a malformed local file
    is quarantined instead of being silently repaired by a downstream reader.
    """
    path_failure = _v4_global(_v4_scope, '_local_path_failure')(path)
    if path_failure is not None:
        return [], path_failure
    if not path.exists():
        return [], None
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size % _v4_global(_v4_scope, 'DAY_STRUCT').size:
            return [], f"{_v4_global(_v4_scope, 'INVALID_BAR')}:source_file_shape"
        bars = _v4_global(_v4_scope, 'read_hq_day_bars')(path)
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'struct').error) as error:
        return [], f"{_v4_global(_v4_scope, 'INVALID_BAR')}:source_read:{error!r}"
    dates: list[int] = []
    previous_close: float | None = None
    for bar in bars:
        valid, reason = _v4_global(_v4_scope, 'valid_hq_bar')(bar)
        if not valid:
            return bars, f"{_v4_global(_v4_scope, 'INVALID_BAR')}:source_{reason}"
        date_value = _v4_global(_v4_scope, 'day_int')(bar)
        if dates and date_value == dates[-1]:
            return bars, _v4_global(_v4_scope, 'DUPLICATE_DATE')
        if dates and date_value < dates[-1]:
            return bars, _v4_global(_v4_scope, 'NON_MONOTONIC_DATE')
        if date_value > target_date:
            return bars, _v4_global(_v4_scope, 'OUT_OF_SCOPE_AFTER_TARGET_DATE')
        close = _v4_global(_v4_scope, 'float')(bar["close"])
        if previous_close is not None:
            ratio = close / previous_close
            if ratio > _v4_global(_v4_scope, 'MAX_CROSS_DAY_CLOSE_RATIO') or ratio < 1.0 / _v4_global(_v4_scope, 'MAX_CROSS_DAY_CLOSE_RATIO'):
                if (seed_evidence is None or symbol is None or not _explain_historical_seed_pair(
                        _v4_scope, seed_evidence, symbol, target_date, dates[-1], date_value, previous_close, close, bars)):
                    return bars, _v4_global(_v4_scope, 'CROSS_DAY_CLOSE_RATIO')
        dates.append(date_value)
        previous_close = close
    return bars, None


def __new_progress_body(_v4_scope, /, target_int, targets, *, dry_run):
    return {
        "schema_version": _v4_global(_v4_scope, 'PROGRESS_SCHEMA_VERSION'),
        "field_rule_id": _v4_global(_v4_scope, 'FIELD_RULE_ID'),
        "field_rule_version": _v4_global(_v4_scope, 'FIELD_RULE_VERSION'),
        "target_date": _v4_global(_v4_scope, 'str')(target_int),
        "target_count": _v4_global(_v4_scope, 'len')(targets),
        "target_fingerprint": _v4_global(_v4_scope, '_target_scope_fingerprint')(targets),
        "dry_run": _v4_global(_v4_scope, 'bool')(dry_run),
        "completed_symbols": [],
        "symbol_progress": {},
        "failed_hosts": [],
        "host_events": [],
        "last_event": None,
    }


def __load_progress_body(_v4_scope, /, path, target_int, targets, *, dry_run):
    expected = _v4_global(_v4_scope, '_new_progress')(target_int, targets, dry_run=dry_run)
    if not path.exists():
        return expected
    try:
        loaded = _v4_global(_v4_scope, 'json').loads(path.read_text(encoding="utf-8"))
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
        raise _v4_global(_v4_scope, 'RuntimeError')(f"A_SYNC_PROGRESS_UNREADABLE:{path}") from error
    if not _v4_global(_v4_scope, 'isinstance')(loaded, _v4_global(_v4_scope, 'dict')):
        raise _v4_global(_v4_scope, 'RuntimeError')(f"A_SYNC_PROGRESS_INVALID:{path}")
    if _v4_global(_v4_scope, 'str')(loaded.get("schema_version")) != _v4_global(_v4_scope, 'PROGRESS_SCHEMA_VERSION'):
        raise _v4_global(_v4_scope, 'RuntimeError')(f"A_SYNC_PROGRESS_SCHEMA_MISMATCH:{path}")
    if _v4_global(_v4_scope, 'str')(loaded.get("target_date")) != _v4_global(_v4_scope, 'str')(target_int):
        raise _v4_global(_v4_scope, 'RuntimeError')(f"A_SYNC_PROGRESS_DATE_MISMATCH:{path}")
    if _v4_global(_v4_scope, 'str')(loaded.get("target_fingerprint")) != expected["target_fingerprint"]:
        raise _v4_global(_v4_scope, 'RuntimeError')(f"A_SYNC_PROGRESS_SCOPE_MISMATCH:{path}")
    if _v4_global(_v4_scope, 'bool')(loaded.get("dry_run", False)) != _v4_global(_v4_scope, 'bool')(dry_run):
        raise _v4_global(_v4_scope, 'RuntimeError')(f"A_SYNC_PROGRESS_MODE_MISMATCH:{path}")
    completed = loaded.get("completed_symbols", [])
    loaded["completed_symbols"] = _v4_global(_v4_scope, 'sorted')({_v4_global(_v4_scope, 'str')(value) for value in completed if _v4_global(_v4_scope, 'str')(value).strip()})
    loaded.setdefault("symbol_progress", {})
    loaded.setdefault("failed_hosts", [])
    loaded.setdefault("host_events", [])
    loaded.setdefault("last_event", None)
    return loaded


def __resume_target_order_body(_v4_scope, /, targets, progress, target_int):
    """Prioritize exact-target local files while preserving all other order.

    The last-date read is only a scheduling hint.  Every target still enters
    the unchanged local history, field, date, continuity, and source-identity
    gates below; a malformed or drifted exact-target file is rejected there.
    ``progress`` remains part of this seam for receipt compatibility, but
    durable pending/retry labels must not starve an already-current file.
    """
    if target_int is None:
        try:
            target_int = _v4_global(_v4_scope, 'int')(progress["target_date"])
        except (_v4_global(_v4_scope, 'KeyError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')):
            return _v4_global(_v4_scope, 'list')(targets)

    current: list[DailyTarget] = []
    remainder: list[DailyTarget] = []
    for target in targets:
        try:
            is_current = _v4_global(_v4_scope, 'read_last_date')(_v4_global(_v4_scope, 'Path')(target.path)) == target_int
        except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'struct').error):
            is_current = False
        (current if is_current else remainder).append(target)
    return current + remainder
