"""Read exact date/roster-bound formula-group supplement pointers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
HISTORICAL_PIT = False
PINNED_SCORE_RULES_SHA256 = {
    'a_share_kb_action_v1.json': 'f303fb47788e7473a2de250152e029cd42ab8580546e527453ee629a5d884bea',
    'a_share_kb_fields_v1.json': '6e425edbce7751211b289554efc7d1fc17e9da48eec904220313afa881ddf456',
    'a_share_kb_hold_score_v1.json': '64994b81e1a5c35bf162aa85aa3cf461437b67e82f4c4e3fc4b53a27367d7444',
    'a_share_kb_n_structure_v1.json': 'b00de5a156225b4843c18c988e09b8a0b708496cdd61b475fd6d9cb92a26633f',
    'kb_action_authority.py': '0b7a4820a1e387ed4e3496f01d207b20f4f70b423b10f01f8439b3f0d16d583d',
    'kb_hold_score.py': 'ca4195a0af1e7220b4fbf13cf07865f3e307cbf7ed45e0ad76b0c00da07e61cb',
    'kb_n_structure.py': '2284db9740e168e1889b4b6d11e53d8962d38a1527185f6bee971498c8c2f9eb',
    'kb_signal_authority.py': '8b31138e49c7d1395de15bfad91dba65992d1af4c2c9a322abb8136e7f5cf053',
    'materialize_workbench_score_action.py': 'c70c1d8bd6dba9fe2e89dba88d7ded5cff05342ee13ef1516087355b966f52df',
}
PINNED_SCORE_RULES_MAP_SHA256 = 'f369ed1502b4d9feda93d163758335eb8ea8afa7e53d0f9f37ac4b8a4dec9dc6'


def _checked(reference, *, root=None):
    if not isinstance(reference, dict) or not isinstance(reference.get('path'), str):
        raise ValueError('WORKBENCH_FORMULA_SUPPLEMENT_REFERENCE_INVALID')
    path = Path(reference['path'])
    if not path.is_absolute() or path.is_symlink() or path.resolve(strict=True) != path:
        raise ValueError('WORKBENCH_FORMULA_SUPPLEMENT_PATH_INVALID')
    if root is not None and not path.is_relative_to(root):
        raise ValueError('WORKBENCH_FORMULA_SUPPLEMENT_OUTSIDE_DATE_ROOT')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != reference.get('sha256'):
        raise ValueError('WORKBENCH_FORMULA_SUPPLEMENT_SHA_DRIFT')
    return json.loads(raw)


def _canonical_sha(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _aware_timestamp(value):
    from datetime import datetime

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _selected_source_cutoff(source_date):
    from datetime import datetime, time
    from zoneinfo import ZoneInfo
    import re

    compact = str(source_date or '').replace('-', '')
    if not re.fullmatch(r'\d{8}', compact):
        raise ValueError('WORKBENCH_PRIOR_COMPANY_SELECTED_DATE_INVALID')
    return datetime.combine(datetime.strptime(compact, '%Y%m%d').date(), time.max,
        tzinfo=ZoneInfo('Asia/Shanghai'))


def prior_company_snapshot_from_answer(answer, current_product, source_date, observation_date,
        symbol, current_roster_sha256, *, prior_product=None, prior_source_date=None,
        prior_observation_date=None, prior_roster_ref=None, selected_asof_cutoff=None):
    """Validate and project one owner-reader answer as separate prior company data."""
    import copy
    import re

    def compact(value):
        text = str(value or '').replace('-', '')
        return text if re.fullmatch(r'\d{8}', text) else None

    selected = compact(current_product.get('data_date'))
    selected_display = source_date
    selected_cutoff = _selected_source_cutoff(selected)
    if (selected_asof_cutoff is not None
            and _aware_timestamp(selected_asof_cutoff) != selected_cutoff):
        raise ValueError('WORKBENCH_PRIOR_COMPANY_SELECTED_CUTOFF_INVALID')
    observation = compact(observation_date)
    if (selected is None or compact(source_date) != selected or observation is None
            or not isinstance(current_roster_sha256, str) or len(current_roster_sha256) != 64
            or not re.fullmatch(r'[0-9a-f]{64}', current_roster_sha256)
            or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', str(symbol))):
        raise ValueError('WORKBENCH_PRIOR_COMPANY_REQUEST_INVALID')
    if answer.get('status') != 'PARTIAL_RECEIVED':
        return None
    identity = current_product.get('source_identity') or {}
    lifecycle = answer.get('material_lifecycle') or {}
    origin = compact(lifecycle.get('material_source_date'))
    material_identity = lifecycle.get('material_identity') or {}
    current_identity = lifecycle.get('current_candidate_identity') or {}
    received_at = _aware_timestamp(lifecycle.get('received_at'))
    reader_cutoff_raw = lifecycle.get('asof_cutoff')
    reader_cutoff = _aware_timestamp(reader_cutoff_raw) if reader_cutoff_raw is not None else None
    read_date = compact(prior_source_date or selected)
    read_observation = compact(prior_observation_date or observation_date)
    read_product = prior_product or current_product
    read_source_identity = read_product.get('source_identity') or {}
    material_ref = answer.get('material_ref')
    manifest_ref = answer.get('materials_manifest')
    materials = answer.get('materials') or {}
    valid_ref = lambda ref: (isinstance(ref, dict) and isinstance(ref.get('path'), str)
        and isinstance(ref.get('sha256'), str) and re.fullmatch(r'[0-9a-f]{64}', ref['sha256']))
    if (answer.get('symbol') != symbol or answer.get('data_date') != read_date
            or answer.get('source_generation') != read_product.get('source_generation')
            or answer.get('input_sha256') != read_source_identity.get('input_sha256')
            or answer.get('numeric_manifest') != read_product.get('manifest')
            or lifecycle.get('view_mode') not in {'HISTORICAL_ASOF', 'CURRENT_RESEARCH'}
            or lifecycle.get('historical_PIT_safe') is not False
            or not origin or origin >= selected or received_at is None or received_at > selected_cutoff
            or (reader_cutoff_raw is not None and reader_cutoff is None)
            or (reader_cutoff is not None and received_at > reader_cutoff)
            or current_identity.get('data_date') != read_date
            or current_identity.get('source_generation') != read_product.get('source_generation')
            or current_identity.get('input_sha256') != read_source_identity.get('input_sha256')
            or current_identity.get('numeric_manifest') != read_product.get('manifest')
            or material_identity.get('data_date') != origin
            or not material_identity.get('source_generation')
            or not material_identity.get('input_sha256')
            or not valid_ref(material_ref) or not valid_ref(manifest_ref)
            or materials.get('schema_version') != 'v4.a_share.company_materials.v1'
            or materials.get('symbol') != symbol or materials.get('data_date') != origin
            or materials.get('source_generation') != material_identity.get('source_generation')
            or materials.get('input_sha256') != material_identity.get('input_sha256')
            or materials.get('RESEARCH_ONLY') is not True
            or any(materials.get(key) is not False for key in ('production_allowed', 'buy_gate_updated', 'orders_sent'))):
        raise ValueError('WORKBENCH_PRIOR_COMPANY_SOURCE_CONFLICT')
    exact_prior_scope = prior_product is not None
    scope = materials.get('formula_group_scope') or {}
    membership = answer.get('formula_group_membership')
    if exact_prior_scope and (
            not isinstance(prior_roster_ref, dict)
            or scope.get('schema') != 'V4_FORMULA_GROUP_SCOPED_IMPORT_V1'
            or scope.get('source_date') != read_date
            or scope.get('observation_date') != read_observation
            or scope.get('source_generation') != prior_product.get('source_generation')
            or scope.get('input_sha256') != read_source_identity.get('input_sha256')
            or scope.get('numeric_manifest') != prior_product.get('manifest')
            or scope.get('roster_sha256') != prior_roster_ref.get('sha256')
            or membership is None or membership.get('symbol') != symbol
            or membership.get('source_date') != read_date
            or membership.get('observation_date') != read_observation
            or membership.get('roster_sha256') != prior_roster_ref.get('sha256')
            or not valid_ref(membership.get('owner_row_ref'))):
        raise ValueError('WORKBENCH_PRIOR_COMPANY_FORMULA_SCOPE_CONFLICT')
    current_candidate_identity = dict(data_date=selected, source_generation=current_product['source_generation'],
        input_sha256=identity['input_sha256'], numeric_manifest=current_product['manifest'])
    business = copy.deepcopy(materials.get('business_reported'))
    financials = copy.deepcopy(materials.get('financials_reported'))
    if scope.get('schema') == 'V4_FORMULA_GROUP_SCOPED_IMPORT_V1':
        fundamentals = materials.get('received_fundamentals') or {}
        raw = fundamentals.get('received_source_record') or {}
        narrative = raw.get('business_and_profit_sources')
        if isinstance(narrative, str) and narrative.strip() and (
                not isinstance(business, dict) or business.get('value') in (None, '')):
            business = {**(business if isinstance(business, dict) else {}), 'value': narrative}
        period = raw.get('financial_period')
        if isinstance(period, str) and period.strip() and (
                not isinstance(financials, dict) or financials.get('latest_report_period') in (None, '')):
            financials = {**(financials if isinstance(financials, dict) else {}),
                'latest_report_period': period}
    result = dict(schema='V4_FORMULA_PRIOR_COMPANY_SNAPSHOT_V1', status='PRIOR_AVAILABLE',
        symbol=symbol, selected_source_date=selected_display, source_date=origin,
        observation_date=observation_date, received_at=lifecycle['received_at'],
        selected_asof_cutoff=selected_cutoff.isoformat(),
        current_candidate_identity=current_candidate_identity,
        material_identity=copy.deepcopy(material_identity),
        materials_manifest=copy.deepcopy(manifest_ref), material_ref=copy.deepcopy(material_ref),
        business_reported=business,
        financials_reported=financials,
        shareholders_reported=copy.deepcopy(materials.get('shareholders_reported')),
        report_catalog=copy.deepcopy(materials.get('report_catalog') or []),
        material_lifecycle={**{key: lifecycle.get(key) for key in
            ('view_mode', 'asof_cutoff', 'historical_PIT_safe', 'received_time_status',
             'disclosure_time_status', 'freshness_status')},
            'reader_view_mode': lifecycle.get('view_mode'),
            'reader_asof_cutoff': lifecycle.get('asof_cutoff'),
            'selected_asof_cutoff': selected_cutoff.isoformat(),
            'view_mode': 'HISTORICAL_ASOF'}, **FLAGS)
    if exact_prior_scope:
        result['prior_formula_scope'] = dict(source_date=read_date,
            observation_date=read_observation, roster_sha256=prior_roster_ref['sha256'],
            formula_group_ref=copy.deepcopy(prior_roster_ref),
            owner_row_ref=copy.deepcopy(membership['owner_row_ref']))
    return result


def prior_company_snapshot(source, product, source_date, observation_date, symbol, roster_sha256):
    """Read a legacy same-symbol company snapshot as of the selected date."""
    answer = source.read_a_daily_company_materials(product['data_date'], symbol,
        generation=product['source_generation'],
        input_sha256=(product.get('source_identity') or {}).get('input_sha256'),
        allow_processed_symbol=True, formula_roster_sha256=roster_sha256,
        formula_observation_date=str(observation_date).replace('-', ''))
    return prior_company_snapshot_from_answer(answer, product, source_date, observation_date,
        symbol, roster_sha256)


def prior_f10_snapshot(source, current_product, source_date, observation_date, symbol):
    """Read the newest earlier immutable owner F10 row without relabeling it as current."""
    from datetime import datetime, time
    import re
    from zoneinfo import ZoneInfo

    selected = str(current_product.get('data_date') or '')
    if not re.fullmatch(r'\d{8}', selected) or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', str(symbol)):
        raise ValueError('WORKBENCH_PRIOR_F10_REQUEST_INVALID')
    root = source._a_product_root()
    if root is None:
        return None
    index = json.loads((Path(root) / 'index.json').read_bytes())
    references = index.get('f10', {})
    if not isinstance(references, dict):
        raise ValueError('WORKBENCH_PRIOR_F10_INDEX_INVALID')
    selected_cutoff = datetime.combine(datetime.strptime(selected, '%Y%m%d').date(), time.max,
        tzinfo=ZoneInfo('Asia/Shanghai'))
    identity = current_product.get('source_identity') or {}

    def numeric_manifest_ref(receipt, day):
        """Resolve current and legacy F10 receipts to their exact numeric owner ref."""
        direct = receipt.get('numeric_manifest')
        if isinstance(direct, dict):
            return direct
        upstream_ref = receipt.get('upstream_success_receipt')
        if not isinstance(upstream_ref, dict):
            return None
        upstream = source._a_product_reference(upstream_ref)
        upstream_schema = upstream.get('schema')
        shared_day_generation = (upstream.get('data_date') == day
            and upstream.get('source_generation') == receipt.get('source_generation')
            and all(upstream.get(key) is value for key, value in FLAGS.items()))
        if upstream_schema == 'V4_A_DAILY_DERIVATIVES_V1':
            provenance = upstream.get('completed_source_provenance') or {}
            ref = provenance.get('numeric_manifest')
            if (upstream.get('status') != 'COMPLETE_DESCRIPTIVE_NONPIT' or not shared_day_generation
                    or provenance.get('status') not in {'EXACT_COMPLETED_SOURCE',
                        'REVALIDATED_ORIGINAL_COMPLETED_TRANSPORT_PROOF'}
                    or not isinstance(ref, dict)):
                return None
            return ref
        if upstream_schema == 'V4_A_DAILY_F10_SOURCE_READY_V1':
            ref = upstream.get('numeric_manifest')
            source_identity = upstream.get('source_identity') or {}
            if (upstream.get('status') != 'EXACT_DAILY_PRODUCT_READY' or not shared_day_generation
                    or upstream.get('input_sha256') != receipt.get('input_sha256')
                    or upstream.get('selector_sha256') != receipt.get('selector_sha256')
                    or source_identity.get('input_sha256') != receipt.get('input_sha256')
                    or source_identity.get('selector_artifact_sha256') != receipt.get('selector_sha256')
                    or not isinstance(ref, dict) or upstream.get('historical_PIT') is not False):
                return None
            return ref
        return None

    for day in sorted((key for key in references if isinstance(key, str) and re.fullmatch(r'\d{8}', key)), reverse=True):
        if day >= selected:
            continue
        receipt_ref = references[day]
        # One stale, malformed, or older-adapter receipt must not hide a valid
        # earlier observation. Each dated receipt is immutable and independently
        # checked; an unbound date is skipped and remains a gap.
        try:
            receipt = source._a_product_reference(receipt_ref)
            if (receipt.get('schema') != 'v4.a_share.f10_daily_receipt.v1'
                    or receipt.get('data_date') != day or receipt.get('status') not in {'COMPLETE', 'PARTIAL'}
                    or receipt.get('historical_PIT') is not False
                    or any(receipt.get(key) is not value for key, value in FLAGS.items())):
                continue
            generation, input_sha, selector_sha, scope_sha = (receipt.get(key) for key in
                ('source_generation', 'input_sha256', 'selector_sha256', 'scope_sha256'))
            if (not all(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value)
                    for value in (generation, input_sha, selector_sha, scope_sha))):
                continue
            manifest_ref = numeric_manifest_ref(receipt, day)
            if not isinstance(manifest_ref, dict):
                continue
            manifest = source._a_product_reference(manifest_ref)
            product_ref = manifest.get('artifact')
            if not isinstance(product_ref, dict):
                continue
            numeric_product = source._a_product_reference(product_ref)
            if (manifest.get('schema_version') != 'v4.a_share.daily_product_manifest.v1'
                    or manifest.get('data_date') != day or manifest.get('status') not in {'READY', 'PARTIAL_WITH_ROWS'}
                    or manifest.get('sample_only') is not False
                    or manifest.get('source_generation') != generation
                    or manifest.get('input_sha256') != input_sha
                    or numeric_product.get('schema_version') != 'v4.a_share.daily_product.v1'
                    or numeric_product.get('data_date') != day or numeric_product.get('status') != manifest.get('status')
                    or numeric_product.get('sample_only') is not False
                    or numeric_product.get('source_generation') != generation
                    or numeric_product.get('source_identity', {}).get('input_sha256') != input_sha
                    or any(manifest.get(key) is not value for key, value in FLAGS.items())
                    or any(numeric_product.get(key) is not value for key, value in FLAGS.items())):
                continue
            checkpoint = source._a_product_reference(receipt.get('checkpoint'))
            checkpoint_identity = checkpoint.get('identity') or {}
            items = checkpoint.get('items')
            if (checkpoint.get('schema') != 'v4.a_share.f10_checkpoint.v1'
                    or checkpoint_identity.get('data_date') != day
                    or checkpoint_identity.get('source_generation') != generation
                    or checkpoint_identity.get('input_sha256') != input_sha
                    or checkpoint_identity.get('selector_sha256') != selector_sha
                    or checkpoint_identity.get('scope_sha256') != scope_sha
                    or not isinstance(items, dict) or receipt.get('observed') != len(items)
                    or any(checkpoint.get(key) is not value for key, value in FLAGS.items())):
                continue
            # A published checkpoint is read-only here. Validate every indexed
            # row reference and its symbol before considering this date.
            checked_items = {}
            item_refs_valid = True
            for code, item_ref in items.items():
                if not isinstance(code, str) or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', code):
                    item_refs_valid = False
                    break
                item = source._a_product_reference(item_ref)
                if item.get('symbol') != code or item.get('status') != 'OBSERVED':
                    item_refs_valid = False
                    break
                checked_items[code] = (item_ref, item)
            if not item_refs_valid:
                continue
            stock_pair = checked_items.get(symbol)
            if stock_pair is None:
                continue
            stock_ref, stock = stock_pair
            if (stock.get('historical_PIT') is not False
                    or stock.get('exchange') not in {None, symbol.rsplit('.', 1)[1]}
                    or any(stock.get(key) is not value for key, value in FLAGS.items())):
                continue
            captured = stock.get('captured_at')
            if not isinstance(captured, str):
                continue
            try:
                captured_at = datetime.fromisoformat(captured.replace('Z', '+00:00'))
            except ValueError:
                continue
            if captured_at.tzinfo is None or captured_at > selected_cutoff:
                continue
            date_fields = (stock.get('source_updated_date'), stock.get('finance_updated_date'))
            if any(isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)
                   and value.replace('-', '') > selected for value in date_fields):
                continue
            return dict(schema='V4_FORMULA_PRIOR_F10_SNAPSHOT_V1', status='PRIOR_AVAILABLE',
                symbol=symbol, selected_source_date=source_date, source_date=day,
                selected_observation_date=observation_date, receipt=receipt_ref, stock_ref=stock_ref,
                material_identity=dict(data_date=day, source_generation=generation,
                    input_sha256=input_sha, numeric_manifest=manifest_ref),
                current_candidate_identity=dict(data_date=selected,
                    source_generation=current_product.get('source_generation'),
                    input_sha256=identity.get('input_sha256'), numeric_manifest=current_product.get('manifest')),
                f10=dict(symbol=symbol, status='OBSERVED', historical_PIT=False,
                    **{key: stock.get(key) for key in
                        ('captured_at', 'source_updated_date', 'finance_updated_date', 'concepts',
                         'concept_status', 'industry', 'financials', 'source_text_sha256')}, **FLAGS),
                historical_PIT=False, **FLAGS)
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return None


def _f10_roster_readback(binding, source_date, product, symbols):
    """Read F10 checkpoint outcomes for this exact roster without mutation."""
    import re

    reference = binding.get('receipt') if isinstance(binding, dict) else None
    if not isinstance(reference, dict):
        return dict(status='UNATTEMPTED', observed=0, failed=0,
                    remaining=len(symbols), receipt=None)
    receipt = _checked(reference)
    selected = source_date.replace('-', '')
    product_identity = product.get('source_identity') or {}
    if (receipt.get('schema') != 'v4.a_share.f10_daily_receipt.v1'
            or receipt.get('status') not in {'COMPLETE', 'PARTIAL'}
            or receipt.get('data_date') != selected
            or receipt.get('source_generation') != product.get('source_generation')
            or receipt.get('input_sha256') != product_identity.get('input_sha256')
            or receipt.get('selector_sha256') != product_identity.get('selector_artifact_sha256')
            or receipt.get('numeric_manifest') != product.get('manifest')
            or receipt.get('scope', {}).get('kind') != 'ADMITTED_DAILY_UNIVERSE'
            or receipt.get('priority_scope') != dict(symbols=sorted(symbols), count=len(symbols))
            or receipt.get('historical_PIT') is not False
            or not isinstance(receipt.get('scope_sha256'), str)
            or receipt.get('scope', {}).get('count') != receipt.get('requested')
            or any(receipt.get(key) is not value for key, value in FLAGS.items())):
        raise ValueError('WORKBENCH_FORMULA_SUPPLEMENT_F10_RECEIPT_CONFLICT')
    checkpoint_ref = receipt.get('checkpoint')
    checkpoint = _checked(checkpoint_ref)
    identity = checkpoint.get('identity') or {}
    if (checkpoint.get('schema') != 'v4.a_share.f10_checkpoint.v1'
            or identity.get('data_date') != selected
            or identity.get('source_generation') != product.get('source_generation')
            or identity.get('input_sha256') != product_identity.get('input_sha256')
            or identity.get('selector_sha256') != product_identity.get('selector_artifact_sha256')
            or identity.get('scope_sha256') != receipt.get('scope_sha256')
            or checkpoint.get('upstream_success_receipt') != receipt.get('upstream_success_receipt')
            or any(checkpoint.get(key) is not value for key, value in FLAGS.items())):
        raise ValueError('WORKBENCH_FORMULA_SUPPLEMENT_F10_CHECKPOINT_CONFLICT')
    items = checkpoint.get('items')
    failures = receipt.get('failures', {})
    remaining_raw = receipt.get('remaining', [])
    if not isinstance(items, dict) or not isinstance(failures, dict) or not isinstance(remaining_raw, list):
        raise ValueError('WORKBENCH_FORMULA_SUPPLEMENT_F10_PARTITION_INVALID')
    if receipt.get('observed') != len(items):
        raise ValueError('WORKBENCH_FORMULA_SUPPLEMENT_F10_OBSERVED_COUNT_CONFLICT')
    roster = set(symbols)
    observed = set()
    for symbol, item_ref in items.items():
        if not isinstance(symbol, str) or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', symbol):
            raise ValueError('WORKBENCH_FORMULA_SUPPLEMENT_F10_ITEM_SYMBOL_INVALID')
        if symbol not in roster:
            continue
        if (not isinstance(item_ref, dict) or not isinstance(item_ref.get('path'), str)
                or not isinstance(item_ref.get('sha256'), str)
                or not re.fullmatch(r'[0-9a-f]{64}', item_ref['sha256'])):
            raise ValueError('WORKBENCH_FORMULA_SUPPLEMENT_F10_ITEM_REF_INVALID:' + symbol)
        observed.add(symbol)
    if any(not isinstance(symbol, str) or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', symbol)
           for symbol in (*failures.keys(), *remaining_raw)):
        raise ValueError('WORKBENCH_FORMULA_SUPPLEMENT_F10_OUTCOME_SYMBOL_INVALID')
    failed = set(failures) & roster
    if not set(failures) <= roster:
        raise ValueError('WORKBENCH_FORMULA_SUPPLEMENT_F10_FAILURE_OUTSIDE_PRIORITY_SCOPE')
    remaining_set = set(remaining_raw)
    if len(remaining_set) != len(remaining_raw):
        raise ValueError('WORKBENCH_FORMULA_SUPPLEMENT_F10_REMAINING_DUPLICATE')
    remaining = (remaining_set & roster) | (roster - observed - failed)
    if observed & failed or observed & remaining or failed & remaining:
        raise ValueError('WORKBENCH_FORMULA_SUPPLEMENT_F10_OUTCOME_CONFLICT')
    complete = observed == roster and not failed and not remaining
    return dict(status='COMPLETE' if complete else 'PARTIAL', observed=len(observed),
                failed=len(failed), remaining=len(remaining), receipt=reference)


def load(formula_groups_root, source_date, product, formula_ref, observation_date):
    """Return current exact supplement bindings, or an empty map if stale/absent."""
    if _canonical_sha(PINNED_SCORE_RULES_SHA256) != PINNED_SCORE_RULES_MAP_SHA256:
        raise ValueError('WORKBENCH_FORMULA_SUPPLEMENT_SCORE_RULE_PIN_INVALID')
    date_root = Path(formula_groups_root) / source_date
    latest = date_root / 'supplements' / 'latest.json'
    if not latest.exists():
        return {}
    if latest.is_symlink() or latest.resolve(strict=True) != latest:
        raise ValueError('WORKBENCH_FORMULA_SUPPLEMENT_POINTER_PATH_INVALID')
    root = date_root.resolve(strict=True)
    pointer_ref = dict(path=str(latest), sha256=hashlib.sha256(latest.read_bytes()).hexdigest())
    pointer = _checked(pointer_ref, root=root)
    if (pointer.get('schema') != 'V4_WORKBENCH_FORMULA_GROUP_SUPPLEMENT_COMMIT_V1'
            or pointer.get('module') != 'formula_group_supplement'
            or pointer.get('source_date') != source_date
            or any(pointer.get(key) is not value for key, value in FLAGS.items())):
        raise ValueError('WORKBENCH_FORMULA_SUPPLEMENT_POINTER_CONFLICT')

    formula = _checked(formula_ref, root=date_root)
    product_identity = product.get('source_identity') or {}
    symbols = sorted(row.get('symbol') for row in formula.get('rows', []))
    if (formula.get('schema') != 'V4_WORKBENCH_FORMULA_GROUP_OVERRIDE_V1'
            or formula.get('source_date') != source_date
            or formula.get('observation_date') != observation_date
            or formula.get('generation') != product.get('source_generation')
            or formula.get('input_sha256') != product_identity.get('input_sha256')
            or formula.get('numeric_manifest') != product.get('manifest')
            or formula.get('selector_sha256') != product_identity.get('selector_artifact_sha256')
            or not isinstance(symbols, list) or len(symbols) != len(set(symbols))):
        raise ValueError('WORKBENCH_FORMULA_SUPPLEMENT_GROUP_IDENTITY_CONFLICT')
    expected = dict(source_date=source_date, observation_date=observation_date,
        generation=product['source_generation'], input_sha256=product_identity['input_sha256'],
        numeric_manifest=product['manifest'], selector_sha256=product_identity['selector_artifact_sha256'],
        formula_group_sha256=formula_ref['sha256'], roster_symbols_sha256=_canonical_sha(symbols),
        roster_count=len(symbols))
    if any(pointer.get(key) != value for key, value in expected.items()):
        # A valid pointer for an older same-date generation/roster is stale.
        # Ignore it without opening its artifact or receipt bytes.
        return {}

    artifact_ref, receipt_ref = pointer.get('artifact'), pointer.get('receipt')
    artifact = _checked(artifact_ref, root=root)
    receipt = _checked(receipt_ref, root=root)
    if (artifact.get('schema') != 'V4_WORKBENCH_FORMULA_GROUP_SUPPLEMENT_V1'
            or artifact.get('status') not in {'COMPLETE', 'PARTIAL'}
            or any(artifact.get(key) != value for key, value in expected.items())
            or any(artifact.get(key) is not value for key, value in FLAGS.items())
            or receipt.get('schema') != 'V4_WORKBENCH_FORMULA_GROUP_SUPPLEMENT_RECEIPT_V1'
            or receipt.get('status') != 'COMMITTED' or receipt.get('artifact') != artifact_ref
            or any(receipt.get(key) != value for key, value in expected.items())
            or any(receipt.get(key) is not value for key, value in FLAGS.items())):
        raise ValueError('WORKBENCH_FORMULA_SUPPLEMENT_RECEIPT_CONFLICT')

    supplement_status = artifact.get('status')
    result = {'supplement_pointer': pointer_ref, 'supplement_artifact': artifact_ref,
        'supplement_status': supplement_status}
    if supplement_status == 'COMPLETE':
        f10_binding = artifact.get('f10') or {}
        if not symbols:
            f10_coverage = dict(status='COMPLETE', observed=0, failed=0,
                                remaining=0, receipt=None)
        else:
            try:
                f10_coverage = _f10_roster_readback(f10_binding, source_date, product, symbols)
            except (ValueError, OSError, KeyError, TypeError, AttributeError):
                f10_coverage = dict(status='CANNOT_CONFIRM', observed=0, failed=0,
                                    remaining=len(symbols), receipt=f10_binding.get('receipt')
                                    if isinstance(f10_binding, dict) else None)
        result['f10_coverage'] = f10_coverage
        if f10_coverage.get('status') != 'COMPLETE':
            result['supplement_status'] = 'PARTIAL'
    marks_ref = artifact.get('d35c_marks')
    if supplement_status == 'COMPLETE' and symbols and not isinstance(marks_ref, dict):
        # A nonempty roster cannot be complete without its exact chart projection.
        result['supplement_status'] = 'PARTIAL'
    if isinstance(marks_ref, dict):
        bundle = _checked(marks_ref, root=root)
        basis = product_identity.get('basis') or {}
        if (bundle.get('schema') != 'V4_WORKBENCH_ORIGINAL_D35C_MARKS_V1'
                or bundle.get('source_date') != source_date
                or bundle.get('generation') != product['source_generation']
                or bundle.get('input_sha256') != product_identity.get('input_sha256')
                or bundle.get('numeric_manifest') != product.get('manifest')
                or bundle.get('formula_group_sha256') != formula_ref['sha256']
                or bundle.get('roster_symbols_sha256') != expected['roster_symbols_sha256']
                or bundle.get('price_basis') != 'QFQ_ASOF_' + source_date.replace('-', '')
                or bundle.get('volume_basis') != basis.get('volume_basis')
                or bundle.get('historical_PIT') is not False
                or any(bundle.get(key) is not value for key, value in FLAGS.items())
                or set(bundle.get('items', {})) != set(symbols)):
            raise ValueError('WORKBENCH_FORMULA_SUPPLEMENT_D35C_CONFLICT')
        result['d35c_marks'] = marks_ref
        if supplement_status == 'COMPLETE' and symbols:
            items = bundle['items']
            if (artifact.get('d35c_status') != 'READY'
                    or any(not isinstance(items[symbol], dict)
                        or items[symbol].get('status') != 'READY'
                        or type(items[symbol].get('unresolved_conditions')) is not int
                        or items[symbol]['unresolved_conditions'] != 0
                        for symbol in symbols)):
                result['supplement_status'] = 'PARTIAL'

    score_binding = artifact.get('score_action')
    if isinstance(score_binding, dict) and isinstance(score_binding.get('receipt'), dict):
        replay = _checked(score_binding['receipt'], root=root)
        descriptor = replay.get('descriptor') or {}
        statuses = replay.get('statuses')
        if (replay.get('schema') != 'V4_FORMULA_GROUP_SCORE_ACTION_REPLAY_V1'
                or replay.get('status') != 'PREPARED_EXACT_OWNER_REPLAY'
                or replay.get('same_rule_sha') is not True
                or replay.get('source_date') != source_date
                or replay.get('source_generation') != product['source_generation']
                or replay.get('input_sha256') != product_identity.get('input_sha256')
                or replay.get('numeric_manifest') != product.get('manifest')
                or replay.get('formula_group_sha256') != formula_ref['sha256']
                or ((replay.get('score_rules') is None) != (replay.get('price_basis') is None))
                or (replay.get('score_rules') is not None and not isinstance(replay.get('score_rules'), dict))
                or (replay.get('price_basis') is not None and not isinstance(replay.get('price_basis'), dict))
                or (replay.get('score_rules') is not None
                    and replay.get('score_rules') != PINNED_SCORE_RULES_SHA256)
                or (replay.get('score_rules') is not None
                    and replay.get('score_rule_map_sha256') != PINNED_SCORE_RULES_MAP_SHA256)
                or any(replay.get(key) is not value for key, value in FLAGS.items())
                or descriptor.get('status') not in {'READY', 'PARTIAL_WITH_UNKNOWN'}
                or descriptor.get('data_date') != source_date.replace('-', '')
                or descriptor.get('source_generation') != product['source_generation']
                or descriptor.get('input_sha256') != product_identity.get('input_sha256')
                or descriptor.get('numeric_manifest') != product.get('manifest')
                or not isinstance(statuses, dict) or set(statuses) != set(symbols)
                or descriptor.get('counts', {}).get('total') != len(symbols)
                or score_binding.get('artifact_root') is None):
            raise ValueError('WORKBENCH_FORMULA_SUPPLEMENT_SCORE_RECEIPT_CONFLICT')
        score_root = Path(score_binding['artifact_root'])
        if not score_root.is_absolute() or score_root.is_symlink() or score_root.resolve(strict=True) != score_root:
            raise ValueError('WORKBENCH_FORMULA_SUPPLEMENT_SCORE_ROOT_INVALID')
        index = _checked(descriptor['index'], root=score_root)
        if (set(index.get('items', {})) != set(symbols)
                or index.get('numeric_manifest') != product.get('manifest')
                or index.get('source_generation') != product['source_generation']
                or index.get('input_sha256') != product_identity.get('input_sha256')
                or index.get('source_selector_sha256') != product_identity.get('selector_artifact_sha256')
                or (replay.get('score_rules') is not None and replay.get('score_rules') != index.get('rules'))
                or (replay.get('price_basis') is not None and replay.get('price_basis') != index.get('price_basis'))
                or (replay.get('price_basis') is not None
                    and replay.get('price_basis') != product_identity.get('basis'))
                or any(index.get(key) is not value for key, value in FLAGS.items())):
            raise ValueError('WORKBENCH_FORMULA_SUPPLEMENT_SCORE_INDEX_CONFLICT')
        result['score_action'] = score_binding
    return result


__all__ = ['load', 'prior_company_snapshot', 'prior_company_snapshot_from_answer', 'prior_f10_snapshot']
