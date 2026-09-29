from __future__ import annotations

import json
from pathlib import Path

import pytest

from domains.research_review_generation import GenerationRefused, run_generation, write_exact_review
from test_research_review_generation import _payload


def test_existing_output_refuses_before_backend_work(tmp_path: Path):
    root = tmp_path / "review"
    write_exact_review(root, "20260911", _payload())
    calls = []
    with pytest.raises(GenerationRefused, match="already exists"):
        run_generation("20260911", review_root=root,
                       backend=lambda d: calls.append(d) or _payload(d))
    assert calls == []


def test_root_symlink_refused_without_outside_write(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "review"
    root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(GenerationRefused):
        write_exact_review(root, "20260911", _payload())
    assert list(outside.iterdir()) == []
