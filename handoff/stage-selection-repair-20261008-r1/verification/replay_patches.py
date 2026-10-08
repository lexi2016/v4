"""Reconstruct delivered owner files in temporary directories; never install."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    specs = []
    for owner in ("canonical", "active_stage_reference"):
        files = []
        for relative, source_owner in (
            ("stage_center/_live_collectors_parts/selection_builder_registry.py", owner),
            ("stage_center/_selection_parts/a_auction.py", "canonical"),
        ):
            files.append((Path(relative),
                          ROOT / "auction/before/source" / source_owner / relative,
                          ROOT / "auction/after/source" / source_owner / relative))
        specs.append((f"auction_{owner}", ROOT / f"auction/patches/{owner}.patch", files))
    for name, before, after, patch in (
        ("hk", ROOT / "hk/before/active_producer_reference",
         ROOT / "hk/after/active_producer_reference", ROOT / "hk/hk_split_date.patch"),
        ("release", ROOT / "release/before", ROOT / "release/after", ROOT / "release/minimal.patch"),
    ):
        specs.append((name, patch, [
            (path.relative_to(before), path, after / path.relative_to(before))
            for path in sorted(before.rglob("*.py"))
        ]))

    reports = []
    for name, patch, files in specs:
        with tempfile.TemporaryDirectory(prefix=f"issue28-{name}-patch-") as temporary:
            work = Path(temporary)
            for relative, before, _after in files:
                target = work / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(before, target)
            phases = []
            for reverse in (False, True):
                command = ["git", "apply", *(["--reverse"] if reverse else [])]
                subprocess.run([*command, "--check", str(patch)], cwd=work,
                               check=True, capture_output=True, text=True)
                subprocess.run([*command, str(patch)], cwd=work,
                               check=True, capture_output=True, text=True)
                compared = []
                for relative, before, after in files:
                    expected = before if reverse else after
                    if (work / relative).read_bytes() != expected.read_bytes():
                        raise RuntimeError(f"{name} exact-byte mismatch: {relative}; reverse={reverse}")
                    compared.append({"path": str(relative), "sha256": digest(expected),
                                     "exact_bytes_match": True})
                phases.append({"phase": "reverse" if reverse else "forward", "files": compared})
            reports.append({"owner": name, "patch": str(patch.relative_to(ROOT)),
                            "patch_sha256": digest(patch), "phases": phases})

    patch = ROOT / "hk/hk_reuse_isolation_review_fix.patch"
    relative = Path("ops/materialize_scheduled_preselection.py")
    final = ROOT / "hk/after/active_producer_reference" / relative
    rejected_sha = "25623e0ddd684a9e400aeaea5b9911ff35da7c615bdf3e288dd1fbd76874d331"
    with tempfile.TemporaryDirectory(prefix="issue28-hk-review-fix-") as temporary:
        work = Path(temporary)
        target = work / relative
        target.parent.mkdir(parents=True)
        shutil.copyfile(final, target)
        phases = []
        for reverse in (True, False):
            command = ["git", "apply", *(["--reverse"] if reverse else [])]
            subprocess.run([*command, "--check", str(patch)], cwd=work,
                           check=True, capture_output=True, text=True)
            subprocess.run([*command, str(patch)], cwd=work,
                           check=True, capture_output=True, text=True)
            expected = rejected_sha if reverse else digest(final)
            if digest(target) != expected:
                raise RuntimeError("HK review-fix reconstruction SHA mismatch")
            phases.append({"phase": "reconstruct_rejected" if reverse else "restore_final",
                           "sha256": expected, "exact_bytes_match": True})
        reports.append({"owner": "hk_review_fix_evidence_only", "patch": str(patch.relative_to(ROOT)),
                        "patch_sha256": digest(patch), "phases": phases})

    print(json.dumps({
        "scope": "OFFLINE_DELIVERED_BYTES_ONLY_NOT_CURRENT_OWNER_OR_DEPLOYMENT",
        "primary_owner_patches": 4, "review_evidence_patches": 1,
        "forward_reverse_exact_bytes": "PASS", "reports": reports,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
