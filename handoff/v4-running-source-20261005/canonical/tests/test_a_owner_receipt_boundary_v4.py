from __future__ import annotations

from pathlib import Path

import pytest

from infrastructure import formula_generation
from ops import publish_research_panel_runtime_receipt as publisher


def _owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    owner = tmp_path / "state" / "data" / "a_formula"
    owner.mkdir(parents=True)
    monkeypatch.setattr(formula_generation, "V4_FORMULA_STATE_OWNER", owner)
    return owner


def test_a_owner_validator_accepts_only_a_formula_descendants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = _owner(tmp_path, monkeypatch)
    valid = owner / "receipts"
    valid.mkdir()
    assert publisher._validate_a_producer_receipt_root(valid) == valid
    receipt = valid / "a-20260911.json"
    receipt.write_text("{}", encoding="utf-8")
    assert publisher._exact_a_producer_receipt(
        valid, "A", "20260911", owner_bound=True
    ) == receipt

    symlink_parent = tmp_path / "state-alias"
    symlink_parent.symlink_to(owner.parent)
    rejected = {
        "sibling": owner.parent / "other",
        "raw_traversal": owner / ".." / "other",
        "symlink_ancestor": symlink_parent / "a_formula" / "receipts",
        "non_posix": r"C:\\v4\\state\\data\\a_formula\\receipts",
    }
    for label, candidate in rejected.items():
        with pytest.raises(publisher.EvidenceError, match="A_PRODUCER_RECEIPT_ROOT_UNSAFE"):
            publisher._validate_a_producer_receipt_root(candidate)


def test_a_publish_checks_dedicated_root_before_shared_receipt_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = _owner(tmp_path, monkeypatch)
    symlink_parent = tmp_path / "state-alias"
    symlink_parent.symlink_to(owner.parent)
    rejected = (
        owner.parent / "other",
        owner / ".." / "other",
        symlink_parent / "a_formula" / "receipts",
        r"C:\\v4\\state\\data\\a_formula\\receipts",
    )
    looked_up: list[tuple[Path | str, str, str]] = []
    original_lookup = publisher._exact_producer_receipt

    def spy_lookup(root: Path | str, lane: str, business_date: str) -> Path:
        looked_up.append((root, lane, business_date))
        return original_lookup(root, lane, business_date)

    monkeypatch.setattr(publisher, "_exact_producer_receipt", spy_lookup)
    for candidate in rejected:
        result = publisher._publish_a(
            "20260911",
            candidate,
            None,
            None,
            owner_bound=True,
        )
        assert result["status"] == "CANNOT_CONFIRM"
        assert "A_PRODUCER_RECEIPT_ROOT_UNSAFE" in result["reason"]
    assert looked_up == []
