"""Independent repro for delivery profile/path correspondence rejection."""
import json
from pathlib import Path

import pytest

from test_frozen_contracts import make_delivery


@pytest.mark.parametrize("damage", ["undeclared_profile", "wrong_payload_filename", "empty_selected_profile"])
def test_manifest_profile_and_logical_path_must_be_closed(tmp_path, damage):
    verifier, package, source = make_delivery(tmp_path)
    manifest_path = package / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    row = manifest["files"][0]
    if damage == "undeclared_profile":
        row["profile"] = "undeclared_worker"
        for side in ("before", "after"):
            old = package / row[side + "_path"]
            new_relative = f"{side}/undeclared_worker/ops/owned.py"
            new = package / new_relative
            new.parent.mkdir(parents=True)
            old.rename(new)
            row[side + "_path"] = new_relative
        # A source-root check for declared worker now has no matching record.
    elif damage == "wrong_payload_filename":
        for side in ("before", "after"):
            old = package / row[side + "_path"]
            new_relative = f"{side}/worker/ops/different.py"
            old.rename(package / new_relative)
            row[side + "_path"] = new_relative
        # Logical source path still says owned.py; payload names disagree.
    else:
        manifest["profiles"]["empty"] = dict(manifest["profiles"]["worker"])
    if damage in {"undeclared_profile", "empty_selected_profile"}:
        (source / "ops/owned.py").write_bytes(b"UNREVIEWED_SOURCE_DRIFT\n")
    manifest_path.write_text(json.dumps(manifest))
    selected = "empty" if damage == "empty_selected_profile" else "worker"
    with pytest.raises(ValueError):
        result = verifier.verify(package, profile=selected, source_root=source, against="before")
        print(json.dumps({"damage": damage, "unexpected_acceptance": result}, sort_keys=True))
