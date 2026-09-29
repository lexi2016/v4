"""Validate manager payloads without confusing research labels with orders.

The existing UI contract calls its advisory label ``action``. Only that field
in a recognized, research-only recommendation/summary or cached-facts
re-evaluation is projected to ``research_label`` for the common guard. No
trading flag, order field, arbitrary action, or nested metadata is exempted.
The persisted/API contract is unchanged; the shared trading guard stays strict.
"""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any
from infrastructure.trading_safety import assert_safe_tree
_SCHEMAS = {'v4.manager_research.recommendation.v1', 'v4.manager_research.recommendation.v2'}
_LABELS = {'BUY', 'CONDITIONAL_BUY', 'WATCH', 'AVOID', 'DATA_INSUFFICIENT', 'NO_BUY', 'NO_TRADE'}


def assert_manager_safe_tree(value: Any) -> None:
    active: set[int] = set()

    def project(item: Any, *, role: str = '', parent_contract: bool = False, depth: int = 0) -> Any:
        if depth > 128:
            raise ValueError('MANAGER_PAYLOAD_NESTING')
        if not isinstance(item, (Mapping, list, tuple)):
            return item
        ident = id(item)
        if ident in active:
            raise ValueError('MANAGER_PAYLOAD_CYCLE')
        active.add(ident)
        try:
            if isinstance(item, (list, tuple)):
                return [project(v, role=role, parent_contract=parent_contract, depth=depth + 1) for v in item]
            contract = (
                item.get('schema_version') in _SCHEMAS
                and item.get('execution_scope') == 'RESEARCH_ONLY'
            )
            summary = role == 'recommendation_summary' and contract and (item.get('execution_buy_count') == 0)
            cached_advice = role in {
                'financial_re_evaluation',
                'financial_advice',
            } and item.get('from_cached_facts') is True and (item.get('financial_collection_calls') == 0)
            label_slot = (
                contract
                or cached_advice
                or (role == 'investment_advice' and parent_contract and (item.get('advice_scope') == 'CURRENT_RESEARCH_JUDGMENT'))
                or (role == 'actions' and parent_contract)
            )
            out = {}
            for key, nested in item.items():
                if key == 'order' and isinstance(nested, int) and not isinstance(nested, bool):
                    # Legacy selection rank alias, validated against the stage
                    # rank at the input boundary; not an order instruction.
                    continue
                if key == 'action' and label_slot:
                    if 'research_label' in item:
                        raise ValueError('MANAGER_RESEARCH_LABEL_COLLISION')
                    if not isinstance(nested, str) or nested not in _LABELS:
                        raise ValueError('MANAGER_RESEARCH_LABEL_INVALID')
                    key = 'research_label'
                child_context = summary if key == 'actions' else contract
                out[key] = project(nested, role=str(key), parent_contract=child_context, depth=depth + 1)
            return out
        finally:
            active.remove(ident)
    assert_safe_tree(project(value), label='manager research')
