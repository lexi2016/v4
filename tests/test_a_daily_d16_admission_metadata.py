"""Bounded regressions for the native R2 daily admission metadata overlay."""
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / "docs/handoffs/a_daily_d16_metadata_20261116"
R2 = Path.home() / ("Library/Application Support/com.lexi.v4.local/candidates/"
                    "v4-single-panel-daily-20261116-r2/main/app")
TARGET = 20261116
CODE = "001246.SZ"


@pytest.fixture
def owner(tmp_path, monkeypatch):
    inventory = json.loads((HANDOFF / "OVERLAY_INVENTORY.json").read_bytes())
    manifest = R2.parent / "release-manifest.json"
    if any(not path.exists() and not path.is_symlink() for path in (R2, manifest)):
        pytest.skip("The exact Mac R2 role and manifest are required for this native overlay test")
    assert sha256(manifest.read_bytes()).hexdigest() == inventory["baseline_manifest_sha256"]
    path = inventory["file"]
    original = R2 / path
    candidate = tmp_path / path
    candidate.parent.mkdir()
    raw = original.read_bytes()
    assert sha256(raw).hexdigest() == inventory["before_sha256"]
    candidate.write_bytes(raw)
    patch = HANDOFF / "CANDIDATE_OVERLAY.patch"
    assert sha256(patch.read_bytes()).hexdigest() == inventory["patch_sha256"]
    subprocess.run(["git", "apply", str(patch)], cwd=tmp_path, check=True, capture_output=True)
    assert sha256(candidate.read_bytes()).hexdigest() == inventory["after_sha256"]
    monkeypatch.syspath_prepend(str(R2))

    def load(file, name):
        spec = importlib.util.spec_from_file_location(name, file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return load(original, "r2_admission_baseline"), load(candidate, "r2_admission_candidate")


def test_observed_raw_endpoint_stays_out_of_original_binding(owner, tmp_path, monkeypatch):
    before, after = owner
    driver = SimpleNamespace(is_a_bj_ts=lambda _: True, DAILY_FORMULA_LOOKBACK_RECORDS=260)
    day = tmp_path / "sz001246.day"
    day.write_bytes(b"".join(struct.pack("<I28x", n) for n in (20261113, TARGET, 20261117)))
    binding = tmp_path / "no-archive.json"
    for module in owner:
        monkeypatch.setattr(module, "existing_day_files", lambda _: [(CODE, day)])
    end = {}
    original = before.raw_bindings(tmp_path, driver, binding, target=TARGET)
    observed = after.raw_bindings(tmp_path, driver, binding, target=TARGET, _observed_ends=end)
    assert original == observed and "history_end_date" not in observed[CODE]
    assert end == {CODE: TARGET}


def test_no_new_metadata_for_unconfirmed_native_or_factor(owner):
    _, after = owner
    source = {"path": "/exact/sz001246.day", "sha256": "1"*64}
    lineage = dict(source_kind="TDX_OFFICIAL_G4DAY", source_url="https://www.tdx.com.cn/dated.zip",
                   package={"path": "/exact/dated.zip", "sha256": "2"*64}, input_ref={"path": "/exact/input.json"},
                   calendar={}, calendar_adapter={}, previous_session=20261113,
                   record={"seq": 10_020, "target_date": TARGET}, target_date=TARGET, market=0, code="001246")
    package = SimpleNamespace(lineage=lambda market, code: lineage if (market, code) == (0, "001246") else None)
    row = dict(classification="ACCEPTED", quarantine=False, target_date_ready=True, last_date_after=TARGET,
               market=0, source_kind=lineage["source_kind"], source_lineage=lineage,
               path=source["path"], source_sha256_after=source["sha256"])
    common = [{"path": "/exact/frozen-sync.json", "sha256": "3"*64}]
    factor = [{"path": "/exact/001246-factor.json", "sha256": "4"*64}]
    invoke = after._official_symbol_admission
    binding = {"raw_files": [source]}
    admission = ({CODE: row}, package, common)
    assert invoke(CODE, binding, TARGET, TARGET, admission, factor) == {
        "history_end_date": TARGET, "accepted_evidence": common + factor,
    }
    assert invoke(CODE, binding, 20261113, TARGET, admission, factor) == {}
    assert invoke(CODE, binding, TARGET, TARGET, admission, []) == {}
    assert invoke(CODE, binding, TARGET, TARGET, ({}, package, common), factor) == {}
    for changes in ({"source_lineage": ["malformed"]}, {"source_sha256_after": "0"*64},
                    {"qualification": "UNKNOWN", "classification": "QUARANTINED"},
                    {"source_lineage": {**lineage, "record": {"seq": -1}}}):
        invalid = {**deepcopy(row), **changes}
        assert invoke(CODE, binding, TARGET, TARGET, ({CODE: invalid}, package, common), factor) == {}
