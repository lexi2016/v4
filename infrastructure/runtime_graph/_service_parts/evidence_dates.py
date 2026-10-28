"""infrastructure.runtime_graph.service: evidence_dates (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _RuntimeGraphService__validate_evidence_date_body(_v4_scope, /, self, value, business_date, *, matches_business_date):
    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'str')) or _v4_global(_v4_scope, '_DATE_RE').fullmatch(value) is None:
        raise self._semantic_error()
    try:
        _v4_global(_v4_scope, 'datetime').strptime(value, '%Y%m%d')
    except _v4_global(_v4_scope, 'ValueError'):
        raise self._semantic_error() from None
    if matches_business_date and value != business_date:
        raise self._semantic_error()


def _RuntimeGraphService__validate_evidence_dates_body(_v4_scope, /, self, evidence, descriptor, business_date, target_date):
    layer = evidence.get('layer')
    details = evidence.get('details')
    if not _v4_global(_v4_scope, 'isinstance')(details, _v4_global(_v4_scope, 'Mapping')):
        return
    # FAIL evidence may intentionally carry a previous-date receipt,
    # artifact, API payload, or page receipt to prove staleness.  Its date
    # shape remains strict, but equality with the snapshot date is a PASS
    # invariant rather than a requirement for recording the failure.
    require_business_date_match = (
        evidence.get('status') != _v4_global(_v4_scope, 'GraphStatus').FAIL.value
    )

    if layer == _v4_global(_v4_scope, 'EvidenceLayer').CALENDAR.value:
        if 'business_date' in details:
            self._validate_evidence_date(
                details['business_date'], business_date, matches_business_date=True
            )
        return

    if layer == _v4_global(_v4_scope, 'EvidenceLayer').EXECUTION.value:
        date_fields = self._declared_date_fields(
            descriptor.get('receipt_date_fields'), _v4_global(_v4_scope, '_DEFAULT_RECEIPT_DATE_FIELDS')
        )
        records = details.get('receipts')
        if not _v4_global(_v4_scope, 'isinstance')(records, _v4_global(_v4_scope, 'list')):
            return
        for record in records:
            if not _v4_global(_v4_scope, 'isinstance')(record, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, 'isinstance')(record.get('receipt'), _v4_global(_v4_scope, 'Mapping')):
                continue
            receipt = record['receipt']
            for field in date_fields:
                target_role = descriptor.get('node_id') in {"ashare_v193_slot_selector_premarket", "hkconnect_d1_top100_prob_active"} and field in {"trade_date", "target_date"}
                if field in receipt:
                    self._validate_evidence_date(
                        receipt[field],
                        target_date if target_role and target_date is not None else business_date,
                        matches_business_date=require_business_date_match,
                    )
        return

    if layer == _v4_global(_v4_scope, 'EvidenceLayer').ARTIFACT.value:
        declarations = descriptor.get('status_sources')
        sources = details.get('sources')
        if not _v4_global(_v4_scope, 'isinstance')(sources, _v4_global(_v4_scope, 'list')):
            return
        for source in sources:
            if not _v4_global(_v4_scope, 'isinstance')(source, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, 'isinstance')(source.get('semantic_fields'), _v4_global(_v4_scope, 'Mapping')):
                continue
            alias = source.get('semantic_alias')
            semantic_fields = source['semantic_fields']
            declared_date_fields: set[str] = _v4_global(_v4_scope, 'set')()
            if _v4_global(_v4_scope, 'isinstance')(declarations, _v4_global(_v4_scope, 'list')):
                for declaration in declarations:
                    if not _v4_global(_v4_scope, 'isinstance')(declaration, _v4_global(_v4_scope, 'Mapping')) or declaration.get('semantic_alias') != alias:
                        continue
                    declared_date_fields.update(
                        self._declared_date_fields(declaration.get('date_fields'))
                    )
                    semantic_declaration = declaration.get('semantic_fields')
                    if _v4_global(_v4_scope, 'isinstance')(semantic_declaration, _v4_global(_v4_scope, 'Mapping')):
                        for name, path in semantic_declaration.items():
                            if not _v4_global(_v4_scope, 'isinstance')(name, _v4_global(_v4_scope, 'str')):
                                continue
                            if _v4_global(_v4_scope, '_is_semantic_date_field')(
                                name
                            ) or _v4_global(_v4_scope, '_is_semantic_date_field')(path):
                                declared_date_fields.add(name)
            required_business_date_fields = (
                _v4_global(_v4_scope, '_SEMANTIC_BUSINESS_DATE_FIELDS').get(alias, _v4_global(_v4_scope, 'frozenset')())
                if _v4_global(_v4_scope, 'isinstance')(alias, _v4_global(_v4_scope, 'str'))
                else _v4_global(_v4_scope, 'frozenset')()
            )
            for name, value in semantic_fields.items():
                if not _v4_global(_v4_scope, 'isinstance')(name, _v4_global(_v4_scope, 'str')) or (
                    name not in declared_date_fields
                    and not _v4_global(_v4_scope, '_is_semantic_date_field')(name)
                ):
                    continue
                target_role = alias in _v4_global(_v4_scope, '_SEMANTIC_TARGET_DATE_ALIASES') and name in {"trade_date", "target_date"}
                expected_date = target_date if target_role and target_date is not None else business_date
                self._validate_evidence_date(
                    value,
                    expected_date,
                    matches_business_date=(
                        require_business_date_match
                        and (
                            target_role
                            or name in _v4_global(_v4_scope, '_BASE_DATE_FIELDS')
                            or name in required_business_date_fields
                        )
                    ),
                )
        return

    if layer == _v4_global(_v4_scope, 'EvidenceLayer').API.value:
        probes = details.get('probes')
        if _v4_global(_v4_scope, 'isinstance')(probes, _v4_global(_v4_scope, 'list')):
            if not probes:
                raise self._semantic_error()
            for record in probes:
                if not _v4_global(_v4_scope, 'isinstance')(record, _v4_global(_v4_scope, 'Mapping')):
                    raise self._semantic_error()
                role = record.get('date_role', 'business_date')
                if role not in {'business_date', 'target_date'}:
                    raise self._semantic_error()
                values = record.get('date_values')
                if values is None and record.get('status') != _v4_global(_v4_scope, 'GraphStatus').PASS.value:
                    continue
                if not _v4_global(_v4_scope, 'isinstance')(values, _v4_global(_v4_scope, 'list')) or (record.get('status') == _v4_global(_v4_scope, 'GraphStatus').PASS.value and not values):
                    raise self._semantic_error()
                expected = target_date if role == 'target_date' and target_date is not None else business_date
                for value in values:
                    self._validate_evidence_date(
                        value,
                        expected,
                        matches_business_date=require_business_date_match,
                    )
            return
        payload = details.get('payload')
        if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')):
            return
        # A collector must be able to persist negative evidence for an
        # out-of-date API response.  Requiring an API_MISMATCH payload to
        # equal the snapshot date makes the collector's own fail-closed
        # snapshot impossible to load.  PASS evidence remains strict;
        # negative evidence still has to contain well-formed dates.
        declared = descriptor.get('api_date_fields')
        date_fields = (
            self._declared_date_fields(declared)
            if _v4_global(_v4_scope, 'isinstance')(declared, _v4_global(_v4_scope, 'list') | _v4_global(_v4_scope, 'tuple'))
            else _v4_global(_v4_scope, '_DEFAULT_API_DATE_FIELDS')
        )
        for field in date_fields:
            if field in payload:
                self._validate_evidence_date(
                    payload[field],
                    business_date,
                    matches_business_date=require_business_date_match,
                )
        return

    if layer == _v4_global(_v4_scope, 'EvidenceLayer').PAGE.value:
        receipt = details.get('receipt')
        if not _v4_global(_v4_scope, 'isinstance')(receipt, _v4_global(_v4_scope, 'Mapping')):
            return
        for field in ('business_date', 'page_date'):
            if field in receipt:
                self._validate_evidence_date(
                    receipt[field],
                    business_date,
                    matches_business_date=require_business_date_match,
                )
