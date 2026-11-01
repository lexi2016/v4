"""Path and code-identity gates for the canonical F10 repair."""
import hashlib
import importlib.util
from pathlib import Path

import pytest

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('f10_canonical_repair_test',root/'ops/edan_f10_canonical_repair.py')
repair=importlib.util.module_from_spec(spec);spec.loader.exec_module(repair)


def test_product_root_accepts_bound_file_but_rejects_outside_and_symlink(tmp_path):
    inside=tmp_path/'root';inside.mkdir();real=inside/'ok.json';real.write_text('{}');digest=hashlib.sha256(real.read_bytes()).hexdigest()
    assert repair.inside({'path':str(real),'sha256':digest},inside)==real
    outside=tmp_path/'outside.json';outside.write_text('{}')
    with pytest.raises(ValueError,match='F10_CANONICAL_REFERENCE_OUTSIDE_ROOT'):
        repair.inside({'path':str(outside),'sha256':digest},inside)
    link=inside/'link.json';link.symlink_to(real)
    with pytest.raises(ValueError,match='F10_CANONICAL_REFERENCE_OUTSIDE_ROOT'):
        repair.inside({'path':str(link),'sha256':digest},inside)
    with pytest.raises(ValueError,match='F10_CANONICAL_REFERENCE_SHA_DRIFT'):
        repair.inside({'path':str(real),'sha256':'f'*64},inside)


def test_wrong_entrypoint_pin_fails_before_runtime_or_publication():
    with pytest.raises(ValueError,match='F10_CANONICAL_CODE_IDENTITY_DRIFT'):
        repair.verify_runtime('f'*64)
