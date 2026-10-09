"""Git tracking and active-release additions are independent dimensions."""
import subprocess

import pytest

from test_builder_issue30 import _build_args
from test_build_release_candidate import BUILDER, _write_delta_receipt


def test_untracked_receipt_file_still_requires_explicit_include(tmp_path):
    args = _build_args(tmp_path)
    source = args["source_root"]
    relative = "apps/api/v35_api/preselection_service.py"
    (source / relative).write_text("REVIEWED = True\n")
    args["api_integration_delta_receipt_path"] = _write_delta_receipt(
        tmp_path / "untracked.json", api_plist=args["api_plist_path"],
        source_root=source, relative_paths=["apps/api/v35_api/app.py", relative])
    with pytest.raises(ValueError):
        BUILDER.build_candidate(**args)
    assert not (args["candidate_root"] / "app" / relative).exists()


def test_untracked_source_may_modify_an_existing_active_file(tmp_path):
    args = _build_args(tmp_path)
    relative = "apps/api/v35_api/app.py"
    subprocess.run(["git", "rm", "--cached", relative], cwd=args["source_root"], check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    args["include_untracked_paths"] = [relative]
    result = BUILDER.build_candidate(**args)
    assert result["explicit_untracked_paths"] == [relative]
    assert (args["candidate_root"] / "app" / relative).read_bytes() == b"VALUE = 1\n"


def test_tracked_flag_cannot_authorize_an_undeclared_file(tmp_path):
    args = _build_args(tmp_path)
    args["include_untracked_paths"] = ["ops/entry.py"]
    with pytest.raises(ValueError):
        BUILDER.build_candidate(**args)
    assert not (args["candidate_root"] / "app").exists()
