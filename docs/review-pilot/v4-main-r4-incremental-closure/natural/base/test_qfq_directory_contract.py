"""Exact return-root to generation-child contract checks on temporary paths."""
import importlib.util
from pathlib import Path

import pytest


CONTRACT_PATH = Path(__file__).resolve().parents[1] / "app/ops/qfq_directory_contract.py"
SPEC = importlib.util.spec_from_file_location("isolated_qfq_directory_contract", CONTRACT_PATH)
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)


def test_exact_generation_child_is_accepted(tmp_path):
    generation = "a" * 64
    root = tmp_path / "return-root"
    run = root / ("qfq_" + generation[:20])
    run.mkdir(parents=True)
    assert CONTRACT.validate_qfq_generation_directory(str(root), str(run), generation) == (root, run)


@pytest.mark.parametrize("damage", ["wrong-root", "wrong-generation-child", "symlink-root", "symlink-run", "noncanonical"])
def test_generation_child_rejects_root_escape_alias_and_sibling(tmp_path, damage):
    generation = "b" * 64
    root = tmp_path / "return-root"
    run = root / ("qfq_" + generation[:20])
    run.mkdir(parents=True)
    root_text, run_text = str(root), str(run)
    if damage == "wrong-root":
        other = tmp_path / "other-root"
        other.mkdir()
        root_text = str(other)
    elif damage == "wrong-generation-child":
        sibling = root / ("qfq_" + "c" * 20)
        sibling.mkdir()
        run_text = str(sibling)
    elif damage == "symlink-root":
        alias = tmp_path / "root-link"
        alias.symlink_to(root, target_is_directory=True)
        root_text, run_text = str(alias), str(alias / run.name)
    elif damage == "symlink-run":
        alias = root / ("qfq_" + "d" * 20)
        alias.symlink_to(run, target_is_directory=True)
        run_text = str(alias)
    elif damage == "noncanonical":
        root_text = str(root) + "/"
    with pytest.raises(ValueError):
        CONTRACT.validate_qfq_generation_directory(root_text, run_text, generation)


def test_generation_identity_is_exact_64_hex():
    with pytest.raises(ValueError, match="QFQ_GENERATION_ID_INVALID"):
        CONTRACT.validate_qfq_generation_directory("/tmp/root", "/tmp/root/qfq_bad", "not-a-generation")
