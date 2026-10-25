"""Final announcement request construction and exact, provider-free preflight."""
from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any, Callable

from .announcement_preprocessing import SEMANTIC_CONTRACT, SEMANTIC_CONTRACT_VERSION


class RequestBudgetError(ValueError):
    def __init__(self, code: str, payload: dict[str, Any], cap: int):
        super().__init__(code)
        self.code, self.payload, self.cap = code, payload, cap


def preflight(payload: dict[str, Any], count_tokens: Callable, cap: int, *,
              code: str = 'EXTENSION_PROMPT_TOKEN_CAP_EXCEEDED') -> dict[str, Any]:
    """Count the complete final messages; malformed/unknown budgets fail closed."""
    if type(cap) is not int or cap < 1:
        raise ValueError('EXTENSION_REQUEST_BUDGET_INVALID')
    messages = payload['messages']
    if (not isinstance(messages, list) or not messages
            or any(not isinstance(m, dict) or not isinstance(m.get('content'), str) for m in messages)):
        raise ValueError('EXTENSION_REQUEST_MESSAGES_INVALID')
    exact = count_tokens(messages)
    if type(exact) is not int or exact < 0:
        raise ValueError('EXTENSION_REQUEST_TOKEN_COUNT_INVALID')
    result = {**payload, 'prompt_tokens_exact': exact}
    if exact > cap:
        raise RequestBudgetError(code, result, cap)
    return result


def finalize_extension_payload(payload, material, extension, extension_sha):
    """Preserve source bytes and the historical facade's payload/rules contract."""
    p = deepcopy(payload)
    if p['messages'][0].get('role') != 'system':
        raise ValueError('EXTENSION_REQUEST_SYSTEM_MESSAGE_INVALID')
    if SEMANTIC_CONTRACT not in p['messages'][0]['content']:
        p['messages'][0]['content'] += '\n\n' + SEMANTIC_CONTRACT
    p['prompt_sha256'] = hashlib.sha256(p['messages'][0]['content'].encode()).hexdigest()
    p['configuration_sha256'] = material['configuration_sha256']
    p['semantic_contract_version'] = SEMANTIC_CONTRACT_VERSION
    p['rules'] += f'+semantic-contract:{SEMANTIC_CONTRACT_VERSION}+execution-extension:{extension_sha}'
    p['execution_extension_sha256'] = extension_sha
    if p['article_id'] == extension['failed']['article_id']:
        p['recovery_of'] = deepcopy(extension['failed'])
        if extension.get('semantic_repair'):
            p['semantic_recovery_of'] = deepcopy(extension['semantic_repair'])
    return p


def extension_payload(payload, material, extension, extension_sha, count_tokens, cap):
    return preflight(finalize_extension_payload(payload, material, extension, extension_sha), count_tokens, cap)
