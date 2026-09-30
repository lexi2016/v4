"""Opaque public error references; never persist exception text or credentials."""
from __future__ import annotations
from uuid import uuid4

def public_error(exc: BaseException) -> str:
    return f'{type(exc).__name__}: CANNOT_CONFIRM; error_ref={uuid4().hex}'
