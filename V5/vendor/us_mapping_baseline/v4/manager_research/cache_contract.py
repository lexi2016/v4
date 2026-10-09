"""Pure exact-input verification shared by current and legacy cache readers."""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any


def validate_cached_product(product: Mapping[str, Any], inputs: Mapping[str, Any]) -> None:
    for key in (
        'target_trade_date',
        'stage_id',
        'market',
        'input_identity',
        'input_source_sha256',
        'input_row_count',
    ):
        if product.get(key) != inputs.get(key):
            raise ValueError('CACHE_INPUT_IDENTITY_MISMATCH')
    expected, actual = (inputs.get('rows'), product.get('rows'))
    if (
        not isinstance(expected, list)
        or not isinstance(actual, list)
        or len(actual) != len(expected)
    ):
        raise ValueError('CACHE_ROW_COUNT_MISMATCH')
    seen: set[str] = set()
    for source, row in zip(expected, actual):
        if not isinstance(source, Mapping) or not isinstance(row, Mapping):
            raise ValueError('CACHE_ROW_INVALID')
        code = row.get('code')
        if (
            not isinstance(code, str)
            or code in seen
            or code != source.get('code')
            or row.get('name') != source.get('name')
        ):
            raise ValueError('CACHE_CANDIDATE_ORDER_MISMATCH')
        seen.add(code)
        observation = row.get('observation') if isinstance(row.get('observation'), Mapping) else row
        for key in ('stage_rank', 'source_last_bar_time'):
            if observation.get(key, row.get(key)) != source.get(key):
                raise ValueError('CACHE_OBSERVATION_MISMATCH')
        for layer in (row, observation, row.get('stage_observation')):
            if not isinstance(layer, Mapping):
                continue
            for key in ('target_trade_date', 'stage_id', 'market'):
                if key in layer and layer[key] != inputs.get(key):
                    raise ValueError('CACHE_NESTED_IDENTITY_MISMATCH')
