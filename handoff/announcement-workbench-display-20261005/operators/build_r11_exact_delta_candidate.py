#!/usr/bin/env python3
"""Apply only this task's source-snapshot delta to a new R11 candidate tree.

The currently running release is read only. The script copies the pinned R11
tree into a temporary directory, applies a zero-fuzz patch derived from the
canonical before snapshot, then moves the completed candidate into the supplied
new path. It refuses a mismatched source/release root or an existing candidate.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


RUNTIME_FILES = (
    "apps/api/v35_api/manager_research_router.py",
    "v4/manager_research/service.py",
    "v4/manager_research/announcement_analysis.py",
    "apps/web/src/api/managerAnnouncementAnalysis.ts",
    "apps/web/src/manager-selection/catalystObservationPanel.ts",
    "apps/web/src/manager-selection/businessStatus.ts",
    "apps/web/src/manager-selection/announcementAnalysis.ts",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def patch_for_text(old_text: str, new_text: str, relative: str,
                   *, old_exists: bool, new_exists: bool) -> str:
    old = old_text.splitlines(keepends=True) if old_exists else []
    new = new_text.splitlines(keepends=True) if new_exists else []
    if old == new:
        return ""
    old_header = f"a/{relative}" if old_exists else "/dev/null"
    new_header = f"b/{relative}" if new_exists else "/dev/null"
    return "".join(difflib.unified_diff(old, new, fromfile=old_header,
                                       tofile=new_header, n=4, lineterm="\n"))


def patch_for(before: Path, after: Path, relative: str) -> str:
    old_text = before.read_text(encoding="utf-8") if before.is_file() else ""
    new_text = after.read_text(encoding="utf-8") if after.is_file() else ""
    return patch_for_text(old_text, new_text, relative,
                          old_exists=before.is_file(), new_exists=after.is_file())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before-snapshot", type=Path, required=True)
    parser.add_argument("--canonical-root", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()

    snapshot = args.before_snapshot.resolve(strict=True)
    canonical = args.canonical_root.resolve(strict=True)
    release = args.release_root.resolve(strict=True)
    evidence = args.evidence_root.resolve(strict=True)
    candidate = args.candidate_root.resolve()
    manifest = json.loads((snapshot / "manifest.json").read_bytes())
    if Path(manifest["canonical_root"]).resolve() != canonical:
        raise ValueError("CANONICAL_ROOT_DIFFERS_FROM_PINNED_SNAPSHOT")
    if Path(manifest["release_root"]).resolve() != release:
        raise ValueError("RELEASE_ROOT_DIFFERS_FROM_PINNED_SNAPSHOT")
    if candidate.parent != evidence or candidate.exists():
        raise ValueError("CANDIDATE_MUST_BE_NEW_CHILD_OF_EVIDENCE_ROOT")
    if shutil.which("patch") is None:
        raise RuntimeError("PATCH_UTILITY_UNAVAILABLE")

    pieces: list[str] = []
    changed: list[str] = []
    before_root = snapshot / "canonical"
    for relative in RUNTIME_FILES:
        if relative == "apps/api/v35_api/manager_research_router.py":
            release_router = release / relative
            canonical_router = canonical / relative
            original = release_router.read_text(encoding="utf-8")
            canonical_text = canonical_router.read_text(encoding="utf-8")
            start = canonical_text.index('    @router.get("/announcements/analysis")')
            end = canonical_text.index('    @router.post("/announcements/refresh")', start)
            handler = canonical_text[start:end]
            marker = '    @router.post("/announcements/refresh")'
            if "/announcements/analysis" in original:
                raise ValueError("R11_ANALYSIS_ROUTE_ALREADY_EXISTS")
            if original.count(marker) != 1:
                raise ValueError("R11_ANNOUNCEMENT_REFRESH_ROUTE_ANCHOR_INVALID")
            routed = original.replace(marker, handler + marker, 1)
            delta = patch_for_text(original, routed, relative, old_exists=True, new_exists=True)
            if delta:
                changed.append(relative)
                pieces.append(delta)
            continue
        before = before_root / relative
        after = canonical / relative
        if before.is_file() == after.is_file() and before.is_file() and sha(before) == sha(after):
            continue
        if not before.is_file() and not after.is_file():
            continue
        delta = patch_for(before, after, relative)
        if delta:
            changed.append(relative)
            pieces.append(delta)
    if not changed:
        raise ValueError("NO_CANONICAL_DELTA_TO_APPLY")
    delta_text = "".join(pieces)
    delta_hash = hashlib.sha256(delta_text.encode("utf-8")).hexdigest()[:12]
    patch_path = evidence / f"r11_announcement_page_exact_delta_{delta_hash}.patch"
    if patch_path.exists() and patch_path.read_text(encoding="utf-8") != delta_text:
        raise FileExistsError("EXACT_DELTA_HASH_COLLISION")
    if not patch_path.exists():
        patch_path.write_text(delta_text, encoding="utf-8")

    candidate.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".r11-candidate-", dir=evidence) as temp_name:
        temp = Path(temp_name) / "app"
        shutil.copytree(release, temp, symlinks=True)
        for relative in changed:
            release_file = temp / relative
            expected_release = manifest["files"].get(f"r11:{relative}", {}).get("sha256")
            current_release = release / relative
            actual_release = sha(current_release) if current_release.is_file() else None
            if actual_release != expected_release:
                raise ValueError(f"R11_FILE_CHANGED_SINCE_SNAPSHOT:{relative}")
            if actual_release is None and expected_release is not None:
                raise ValueError(f"R11_FILE_MISSING_SINCE_SNAPSHOT:{relative}")
        checked = subprocess.run(["patch", "--batch", "--forward", "--fuzz=0", "--dry-run", "-p1"],
                                 cwd=temp, input=delta_text, text=True, capture_output=True)
        if checked.returncode:
            print(json.dumps({"status": "PATCH_CONFLICT", "changed_files": changed,
                              "patch": str(patch_path), "stdout": checked.stdout,
                              "stderr": checked.stderr}, ensure_ascii=False))
            return 2
        applied = subprocess.run(["patch", "--batch", "--forward", "--fuzz=0", "-p1"],
                                 cwd=temp, input=delta_text, text=True, capture_output=True)
        if applied.returncode:
            print(json.dumps({"status": "PATCH_APPLY_FAILED", "changed_files": changed,
                              "patch": str(patch_path), "stdout": applied.stdout,
                              "stderr": applied.stderr}, ensure_ascii=False))
            return 3
        shutil.move(str(temp), str(candidate))

    result = {
        "schema_version": "v4.announcement_page_r11_candidate.v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "EXACT_DELTA_APPLIED_TO_NEW_CANDIDATE",
        "canonical_head": manifest["head"],
        "release_root": str(release),
        "candidate_root": str(candidate),
        "patch": str(patch_path),
        "changed_files": changed,
        "files": {relative: {"r11_before_sha256": manifest["files"].get(f"r11:{relative}", {}).get("sha256"),
                              "candidate_sha256": sha(candidate / relative)}
                  for relative in changed},
        "release_modified": False,
    }
    receipt_path = evidence / f"r11_announcement_page_candidate_manifest_{delta_hash}.json"
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if receipt_path.exists() and receipt_path.read_text(encoding="utf-8") != encoded:
        raise FileExistsError("CANDIDATE_MANIFEST_EXISTS_WITH_DIFFERENT_CONTENT")
    if not receipt_path.exists():
        receipt_path.write_text(encoded, encoding="utf-8")
    print(json.dumps({"status": result["status"], "candidate": str(candidate),
                      "patch": str(patch_path), "manifest": str(receipt_path),
                      "changed_files": changed, "release_modified": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
