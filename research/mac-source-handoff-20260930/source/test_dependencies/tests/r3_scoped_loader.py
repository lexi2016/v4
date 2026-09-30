"""Test-only namespace loader for the deliberately scoped R3 source export.

It does not provide any missing implementation.  It only prevents package
``__init__`` side effects from importing files that the handoff did not export.
Every imported target/dependency is still loaded from the real source tree.
Mac native acceptance must run without this helper in the complete repository.
"""
from pathlib import Path
import sys
import types

ROOT=Path(__file__).resolve().parents[1]

def install() -> None:
    for name, path in (
        ("v4", ROOT/"v4"),
        ("v4.manager_research", ROOT/"v4"/"manager_research"),
        ("infrastructure", ROOT/"infrastructure"),
        ("infrastructure.scheduling", ROOT/"infrastructure"/"scheduling"),
        ("contracts", ROOT/"contracts"),
    ):
        if name in sys.modules:
            continue
        module=types.ModuleType(name)
        module.__path__=[str(path)]
        module.__package__=name
        sys.modules[name]=module
