"""infrastructure.runtime_graph.service: node_semantics (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _RuntimeGraphService__validate_node_runtime_body(_v4_scope, /, self, node, descriptor, business_date, target_date):
    runtime_fields = {'status', 'reason', 'evidence', *_v4_global(_v4_scope, 'SAFETY_FLAGS')}
    static_descriptor = {
        key: value
        for key, value in descriptor.items()
        if key not in {'status', 'reason', 'evidence', *_v4_global(_v4_scope, 'SAFETY_FLAGS')}
    }
    actual_static = {key: value for key, value in node.items() if key not in runtime_fields}
    if actual_static != static_descriptor:
        raise self._semantic_error()
    if _v4_global(_v4_scope, 'set')(node) != _v4_global(_v4_scope, 'set')(static_descriptor) | runtime_fields:
        raise self._semantic_error()
    for flag in _v4_global(_v4_scope, 'SAFETY_FLAGS'):
        if _v4_global(_v4_scope, 'type')(node.get(flag)) is not _v4_global(_v4_scope, 'bool') or node[flag] is not False:
            raise self._semantic_error()
    if _v4_global(_v4_scope, 'type')(node.get('status')) is not _v4_global(_v4_scope, 'str') or node['status'] not in {item.value for item in _v4_global(_v4_scope, 'GraphStatus')}:
        raise self._semantic_error()
    if _v4_global(_v4_scope, 'type')(node.get('reason')) is not _v4_global(_v4_scope, 'str') or not node['reason']:
        raise self._semantic_error()
    node_status = _v4_global(_v4_scope, 'GraphStatus')(node['status'])
    node_reason = node['reason']
    evidence = node.get('evidence')
    if not _v4_global(_v4_scope, 'isinstance')(evidence, _v4_global(_v4_scope, 'list')):
        raise self._semantic_error()
    if not evidence:
        if node_status is not _v4_global(_v4_scope, 'GraphStatus').EVIDENCE_GAP or node_reason not in _v4_global(_v4_scope, '_EMPTY_EVIDENCE_REASONS'):
            raise self._semantic_error()
        return node_status, node_reason
    evidence_keys = {'layer', 'status', 'reason', 'details'}
    results: list[EvidenceResult] = []
    for item in evidence:
        if not _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(item) != evidence_keys:
            raise self._semantic_error()
        if (
            _v4_global(_v4_scope, 'type')(item.get('layer')) is not _v4_global(_v4_scope, 'str')
            or _v4_global(_v4_scope, 'type')(item.get('status')) is not _v4_global(_v4_scope, 'str')
            or _v4_global(_v4_scope, 'type')(item.get('reason')) is not _v4_global(_v4_scope, 'str')
            or not item['reason']
            or not _v4_global(_v4_scope, 'isinstance')(item.get('details'), _v4_global(_v4_scope, 'Mapping'))
            or not self._json_shape(item['details'])
        ):
            raise self._semantic_error()
        self._validate_evidence_dates(item, descriptor, business_date, target_date)
        try:
            layer = _v4_global(_v4_scope, 'EvidenceLayer')(item['layer'])
            status = _v4_global(_v4_scope, 'GraphStatus')(item['status'])
            results.append(_v4_global(_v4_scope, 'EvidenceResult')(layer, status, item['reason'], item['details']))
        except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')):
            raise self._semantic_error() from None
    if _v4_global(_v4_scope, 'len')(results) == 1:
        if (
            results[0].layer is not _v4_global(_v4_scope, 'EvidenceLayer').CALENDAR
            or results[0].status
            not in {_v4_global(_v4_scope, 'GraphStatus').NOT_DUE, _v4_global(_v4_scope, 'GraphStatus').SKIPPED_EXPECTED}
        ):
            raise self._semantic_error()
        if node_status is not results[0].status or node_reason != results[0].reason:
            raise self._semantic_error()
        return node_status, node_reason
    required = _v4_global(_v4_scope, 'required_evidence_layers')(descriptor)
    if _v4_global(_v4_scope, 'len')(results) != _v4_global(_v4_scope, 'len')(required) or _v4_global(_v4_scope, 'any')(
        item.status in {_v4_global(_v4_scope, 'GraphStatus').NOT_DUE, _v4_global(_v4_scope, 'GraphStatus').SKIPPED_EXPECTED}
        for item in results
    ):
        raise self._semantic_error()
    if [item.layer for item in results] != _v4_global(_v4_scope, 'list')(required):
        raise self._semantic_error()
    reduced = _v4_global(_v4_scope, 'reduce_status')(results, required)
    reduced_reason = _v4_global(_v4_scope, 'next')(item.reason for item in results if item.status is reduced)
    if node_status is not reduced or node_reason != reduced_reason:
        raise self._semantic_error()
    return node_status, node_reason


def _RuntimeGraphService__validate_snapshot_semantics_body(_v4_scope, /, self, payload):
    expected_keys = _v4_global(_v4_scope, '_SNAPSHOT_CORE_FIELDS') | _v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, 'SAFETY_FLAGS'))
    if _v4_global(_v4_scope, 'set')(payload) != expected_keys:
        raise self._semantic_error()
    for flag in _v4_global(_v4_scope, 'SAFETY_FLAGS'):
        if _v4_global(_v4_scope, 'type')(payload.get(flag)) is not _v4_global(_v4_scope, 'bool') or payload[flag] is not False:
            raise self._semantic_error()
    if (
        payload.get('topology_schema_version') != self.topology['schema_version']
        or payload.get('topology_authority_root') != self.topology['authority_root']
        or payload.get('topology_version_sha') != self.topology_version_sha
    ):
        raise self._semantic_error()
    nodes = payload.get('nodes')
    if not _v4_global(_v4_scope, 'isinstance')(nodes, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'len')(nodes) != _v4_global(_v4_scope, 'len')(self.topology['nodes']):
        raise self._semantic_error()
    if payload.get('edges') != self.topology['edges']:
        raise self._semantic_error()
    statuses: list[GraphStatus] = []
    reasons: list[str] = []
    business_date = payload.get('business_date')
    if not _v4_global(_v4_scope, 'isinstance')(business_date, _v4_global(_v4_scope, 'str')):
        raise self._semantic_error()
    for node, descriptor in _v4_global(_v4_scope, 'zip')(nodes, self.topology['nodes']):
        if not _v4_global(_v4_scope, 'isinstance')(node, _v4_global(_v4_scope, 'Mapping')):
            raise self._semantic_error()
        try:
            target_date = _v4_global(_v4_scope, '_target_date_for_node')(_v4_global(_v4_scope, 'str')(descriptor["node_id"]), business_date)
        except (_v4_global(_v4_scope, 'KeyError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')):
            target_date = None
        status, reason = self._validate_node_runtime(node, descriptor, business_date, target_date)
        statuses.append(status)
        reasons.append(reason)
    graph_status = _v4_global(_v4_scope, 'reduce_graph_status')(statuses)
    if _v4_global(_v4_scope, 'type')(payload.get('status')) is not _v4_global(_v4_scope, 'str') or payload['status'] != graph_status.value:
        raise self._semantic_error()
    if _v4_global(_v4_scope, 'type')(payload.get('reason')) is not _v4_global(_v4_scope, 'str') or not payload['reason']:
        raise self._semantic_error()
    graph_reason = _v4_global(_v4_scope, 'next')(reason for status, reason in _v4_global(_v4_scope, 'zip')(statuses, reasons) if status is graph_status)
    if payload['reason'] != graph_reason:
        raise self._semantic_error()
