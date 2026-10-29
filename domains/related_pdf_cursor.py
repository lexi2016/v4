"""Bounded per-process cursor sessions for PDF relation pagination.

Opaque random tokens carry no offset or source data. A restart, different
worker, expiry, eviction or mismatch is a stale cursor, never an empty page.
"""
from __future__ import annotations

import os
import re
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable

CURSOR_TTL_SECONDS = 300
MAX_CURSOR_SESSIONS = 256
MAX_PRIOR_DOCUMENTS = 32
MAX_PRIOR_BYTES = 96 * 1024 * 1024
MAX_CURRENT_PAGE_BYTES = 96 * 1024 * 1024


@dataclass(frozen=True)
class PriorDocument:
    document_id: str
    research_date: str
    pdf_sha256: str
    receipt_sha256: str
    pdf_size: int
    pages_size: int


@dataclass(frozen=True)
class CursorState:
    checkpoint: str
    signature: str
    offset: int
    prior: tuple[PriorDocument, ...]
    expires: float
    pid: int


class CursorStore:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 ttl: int = CURSOR_TTL_SECONDS, capacity: int = MAX_CURSOR_SESSIONS):
        self._clock = clock
        self._ttl = ttl
        self._capacity = capacity
        self._lock = threading.RLock()
        self._states: OrderedDict[str, CursorState] = OrderedDict()

    def _expire_locked(self, now: float) -> None:
        for token, state in list(self._states.items()):
            if state.expires <= now or state.pid != os.getpid():
                self._states.pop(token, None)

    def issue(self, checkpoint: str, signature: str, offset: int, prior: tuple[PriorDocument, ...]) -> str:
        if (type(offset) is not int or offset < 0 or len(prior) > MAX_PRIOR_DOCUMENTS
                or sum(item.pdf_size + item.pages_size for item in prior) > MAX_PRIOR_BYTES):
            raise ValueError('SEARCH_PAGINATION_VALIDATION_LIMIT')
        now = self._clock()
        with self._lock:
            self._expire_locked(now)
            while len(self._states) >= self._capacity:
                self._states.popitem(last=False)
            token = secrets.token_urlsafe(32)
            while token in self._states:
                token = secrets.token_urlsafe(32)
            self._states[token] = CursorState(checkpoint, signature, offset, prior, now + self._ttl, os.getpid())
            return token

    def resolve(self, token: str, checkpoint: str, signature: str, count: int) -> CursorState:
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            raise ValueError('SEARCH_CURSOR_INVALID')
        now = self._clock()
        with self._lock:
            self._expire_locked(now)
            state = self._states.get(token)
            if (state is None or state.checkpoint != checkpoint or state.signature != signature
                    or not 0 <= state.offset <= count):
                raise ValueError('SEARCH_CURSOR_STALE')
            return state

    def invalidate(self, token: str | None) -> None:
        if token:
            with self._lock:
                self._states.pop(token, None)


CURSORS = CursorStore()
