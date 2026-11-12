from __future__ import annotations

import ast
from pathlib import Path

from infrastructure.research_store import HourlyResearchStore, ResearchSelectionStore


STORE_SOURCE = Path(__file__).parents[1] / "infrastructure/research_store.py"
SELECTION_READERS = {
    "read_exact",
    "read_run",
    "read_lineage",
    "read_exact_with_lineage",
}
MISPLACED_HOURLY_READERS = SELECTION_READERS - {"read_exact"}


def _class_methods(tree: ast.Module) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            result[node.name] = {
                item.name
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
    return result


def test_selection_readers_have_single_original_class_owner() -> None:
    classes = _class_methods(ast.parse(STORE_SOURCE.read_text(encoding="utf-8")))
    assert SELECTION_READERS <= classes["ResearchSelectionStore"]
    assert not (MISPLACED_HOURLY_READERS & classes["HourlyResearchStore"])
    for name in SELECTION_READERS:
        assert getattr(ResearchSelectionStore, name).__qualname__.startswith(
            "ResearchSelectionStore."
        )


def test_selection_empty_read_is_date_bound_and_does_not_use_hourly_namespace(
    tmp_path: Path,
) -> None:
    store = ResearchSelectionStore(tmp_path)
    assert store.read_exact("20260907") is None
    assert store.read_lineage("20260907") is None
    assert store._date_current_relative("20260907") == (
        "research/selection/20260907/current.json"
    )
    assert HourlyResearchStore._relative("20260907", "1200", "LIVE") == (
        "research/hourly/live/20260907/1200.json"
    )
