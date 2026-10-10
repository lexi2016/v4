"""Build or verify the small, non-secret handoff package manifest."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "PACKAGE_MANIFEST.json"
EXCLUDED_NAMES = {
    "raw_capture.json", "capture.json", "hkconnect_vipdoc_daily_panel.parquet",
    "panel.parquet", "membership_codes.json", "credentials.json", ".env",
}
EXCLUDED_SUFFIXES = {".parquet", ".sqlite", ".db", ".pem", ".p12", ".pfx", ".key"}
SECRET_MARKERS = ("-----BEGIN PRIVATE KEY-----", "-----BEGIN OPENSSH PRIVATE KEY-----")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def payload_paths():
    return sorted(path for path in ROOT.rglob("*")
                  if path.is_file() and path != MANIFEST and "__pycache__" not in path.parts)


def build():
    files = [{"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path),
              "size_bytes": path.stat().st_size} for path in payload_paths()]
    manifest = {
        "schema_version": "v5.rebound_admission_handoff_package.v1",
        "classification": "PRIVATE_REVIEW_PACKAGE_NOT_ADMISSION_EVIDENCE",
        "files_excluding_this_manifest": files,
        "file_count_excluding_manifest": len(files),
        "exclusion_policy": {
            "no_raw_market_rows_or_capture_files": True,
            "no_full_membership_dump": True,
            "no_credentials_or_sdk_logs": True,
            "no_parquet_database_key_or_certificate_files": True,
        },
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def verify():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected = {entry["path"]: entry for entry in manifest["files_excluding_this_manifest"]}
    actual_paths = payload_paths()
    actual = {path.relative_to(ROOT).as_posix(): path for path in actual_paths}
    if set(expected) != set(actual):
        raise SystemExit(f"MANIFEST_PATH_SET_MISMATCH expected={len(expected)} actual={len(actual)}")
    for rel, path in actual.items():
        entry = expected[rel]
        if sha256(path) != entry["sha256"] or path.stat().st_size != entry["size_bytes"]:
            raise SystemExit(f"MANIFEST_HASH_MISMATCH {rel}")
        if path.name.lower() in EXCLUDED_NAMES or path.suffix.lower() in EXCLUDED_SUFFIXES:
            raise SystemExit(f"EXCLUDED_FILE_PRESENT {rel}")
        if path.stat().st_size > 1024 * 1024:
            raise SystemExit(f"UNEXPECTEDLY_LARGE_FILE {rel}")
        if path != Path(__file__).resolve() and path.suffix.lower() in {".md", ".json", ".py", ".patch"}:
            data = path.read_bytes()
            if any(marker.encode("ascii") in data for marker in SECRET_MARKERS):
                raise SystemExit(f"PRIVATE_KEY_MARKER {rel}")
    print(json.dumps({"status": "PACKAGE_HASHES_AND_EXCLUSION_SCAN_PASS",
                      "payload_file_count": len(actual),
                      "checked_excluded_names_and_suffixes": True,
                      "checked_private_key_markers": True,
                      "manifest_sha256": sha256(MANIFEST)}, sort_keys=True))


if __name__ == "__main__":
    if sys.argv[1:] == ["--build"]:
        built = build()
        print(f"built {built['file_count_excluding_manifest']} file entries")
    elif not sys.argv[1:]:
        verify()
    else:
        raise SystemExit("usage: python3 verify_package.py [--build]")
