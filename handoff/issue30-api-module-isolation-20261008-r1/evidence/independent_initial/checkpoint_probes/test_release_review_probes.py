"""Independent review probes: synthetic filesystem fixtures only.

These are acceptance expectations. A failure is preserved as review evidence;
the SOURCE_CANDIDATE remains unmodified.
"""
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "candidate"))
sys.path.insert(0, str(ROOT / "candidate/tests"))

from ops import api_release_integration as integration
from test_api_release_integration import _integrated_candidate
from test_builder_issue30 import _build_args
from test_build_release_candidate import BUILDER, _write_delta_receipt


@pytest.mark.parametrize("explicit_include", [False, True])
def test_committed_reviewed_module_addition_can_be_built(tmp_path, explicit_include):
    args = _build_args(tmp_path)
    source = args["source_root"]
    relative = "apps/api/v35_api/preselection_service.py"
    (source / relative).write_bytes(b"REVIEWED_MODULE = True\n")
    subprocess.run(["git", "add", relative], cwd=source, check=True)
    subprocess.run(["git", "commit", "-qm", "reviewed module addition"], cwd=source, check=True)
    receipt_path = _write_delta_receipt(tmp_path / "committed-delta.json",
        api_plist=args["api_plist_path"], source_root=source,
        relative_paths=["apps/api/v35_api/app.py", relative])
    args["api_integration_delta_receipt_path"] = receipt_path
    if explicit_include:
        args["include_untracked_paths"] = [relative]
    result = BUILDER.build_candidate(**args)
    assert result["activation_status"] == "NOT_ACTIVATED"
    assert (args["candidate_root"] / "app" / relative).read_bytes() == b"REVIEWED_MODULE = True\n"


def test_verifier_rejects_undeclared_directory_mode_change(tmp_path):
    active, candidate, _ = _integrated_candidate(tmp_path)
    directory = candidate / "app/apps/api"
    baseline_mode = (Path(active["app_root"]) / "apps/api").stat().st_mode & 0o7777
    directory.chmod(0o777 if baseline_mode != 0o777 else 0o755)
    with pytest.raises(ValueError):
        integration.verify_api_release_candidate(candidate_root=candidate,
            active_api_plist_path=Path(active["api_plist"]))


def test_scheduler_staging_cannot_follow_late_config_symlink(tmp_path, monkeypatch):
    args = _build_args(tmp_path)
    candidate = args["candidate_root"]
    outside = tmp_path / "outside-config"
    original = BUILDER.render_cutover

    def swap_config_after_prepare(**kwargs):
        plan = original(**kwargs)
        (candidate / "config").rename(outside)
        (candidate / "config").symlink_to(outside, target_is_directory=True)
        return plan

    monkeypatch.setattr(BUILDER, "render_cutover", swap_config_after_prepare)
    refused = False
    try:
        BUILDER.build_candidate(**args)
    except (ValueError, OSError):
        refused = True
    assert not (outside / "com.lexi.v35.scheduler.plist").exists(), "builder wrote through config symlink outside its candidate"
    assert refused, "builder accepted an aliased candidate config directory"
