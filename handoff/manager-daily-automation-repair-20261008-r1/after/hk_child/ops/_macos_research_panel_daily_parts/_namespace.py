"""Resolve globals from the exact monolithic HK child entry point."""
from __future__ import annotations

import builtins


def read_global(scope, name):
    try:
        return scope[name]
    except KeyError:
        values = scope.get("__builtins__", builtins)
        if isinstance(values, dict):
            if name in values:
                return values[name]
        elif hasattr(values, name):
            return getattr(values, name)
        raise NameError("name '" + name + "' is not defined", name=name) from None
