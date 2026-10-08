"""Independently reconstruct owner candidates from frozen before bytes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


reports = []
specs = []
for owner in ("canonical", "active_stage_reference"):
    product = [
        (Path("stage_center/_live_collectors_parts/selection_builder_registry.py"), owner),
        (Path("stage_center/_selection_parts/a_auction.py"), "canonical"),
    ]
    specs.append((
        f"auction_{owner}", ROOT / f"delivery/auction/patches/{owner}.patch",
        [(relative, ROOT / f"baseline/source/{actual}" / relative,
          ROOT / f"delivery/auction/after/source/{actual}" / relative)
         for relative, actual in product],
    ))
for name, before, after, patch in (
    ("release", ROOT / "delivery/release/before", HERE / "initial_candidate/release/after", HERE / "initial_candidate/release/frozen.patch"),
    ("hk", ROOT / "delivery/hk/before/active_producer_reference", HERE / "initial_candidate/hk/after/active_producer_reference", HERE / "initial_candidate/hk/frozen.patch"),
):
    specs.append((name, patch, [(path.relative_to(before), path, after / path.relative_to(before)) for path in sorted(before.rglob("*.py"))]))

for name, patch, files in specs:
    with tempfile.TemporaryDirectory(prefix=f"{name}-patch-", dir=HERE) as directory:
        temporary = Path(directory)
        for relative, before, after in files:
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(before, target)
        phases = []
        for reverse in (False, True):
            args = ["git", "apply", *(["--reverse"] if reverse else [])]
            subprocess.run([*args, "--check", str(patch)], cwd=temporary, check=True, capture_output=True)
            subprocess.run([*args, str(patch)], cwd=temporary, check=True, capture_output=True)
            compared = []
            for relative, before, after in files:
                expected = before if reverse else after
                matches = (temporary / relative).read_bytes() == expected.read_bytes()
                assert matches, (name, relative, reverse)
                compared.append({"path": str(relative), "sha256": sha(expected), "exact_bytes_match": matches})
            phases.append({"phase": "reverse" if reverse else "forward", "files": compared})
        reports.append({"owner": name, "patch_sha256": sha(patch), "phases": phases})

(HERE / "PATCH_REPLAY.json").write_text(json.dumps(reports, indent=2) + "\n")
print(json.dumps({"owner_replays": len(reports), "forward_and_reverse_exact_bytes": "PASS"}, indent=2))
