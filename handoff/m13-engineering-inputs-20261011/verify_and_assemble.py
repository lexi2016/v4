#!/usr/bin/env python3
"""Verify material bytes and optionally assemble a NEW isolated source tree.

Standard library only. Never imports product modules or executes tests/fixtures.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def safe_members(archive):
    names = set()
    for member in archive.infolist():
        p = PurePosixPath(member.filename)
        if p.is_absolute() or ".." in p.parts or "\\" in member.filename or member.filename in names:
            raise ValueError("Unsafe or duplicate ZIP path: " + member.filename)
        mode = member.external_attr >> 16
        if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
            raise ValueError("Non-regular ZIP member: " + member.filename)
        names.add(member.filename)
    return names


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", help="Optional new absolute directory; must not exist")
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    manifest = json.loads((here / "MANIFEST.json").read_text())
    member_manifest = json.loads((here / "verification/ZIP_MEMBERS.json").read_text())
    expected_members = {(r["package_role"], r["member"]): r for r in member_manifest}
    archives = {}
    for package in manifest["packages"]:
        data = (here / package["path"]).read_bytes()
        assert len(data) == package["bytes"], package["path"]
        assert digest(data) == package["sha256"], package["path"]
        assert git_blob(data) == package["git_blob_sha1"], package["path"]
        archive = zipfile.ZipFile(here / package["path"])
        assert archive.testzip() is None, package["path"]
        names = safe_members(archive)
        assert len(names) == package["files"], package["path"]
        assert names == {n for role, n in expected_members if role == package["role"]}
        for info in archive.infolist():
            entry = expected_members[(package["role"], info.filename)]
            data = archive.read(info)
            assert len(data) == entry["bytes"] and digest(data) == entry["sha256"], info.filename
            assert f"{info.CRC:08x}" == entry["crc32"], info.filename
        archives[package["role"]] = (package, archive)
    source_prefix = archives["source"][0]["root"] + "/"
    overlay_prefix = archives["consumer"][0]["root"] + "/overlay/"
    source = {n[len(source_prefix):]: archives["source"][1].read(n)
              for n in archives["source"][1].namelist() if n.startswith(source_prefix) and not n.endswith("/")}
    overlay = {n[len(overlay_prefix):]: archives["consumer"][1].read(n)
               for n in archives["consumer"][1].namelist() if n.startswith(overlay_prefix) and not n.endswith("/")}
    assert not (source.keys() & overlay.keys()), "Unexpected SOURCE/overlay overlap"
    assert len(overlay) == 93
    assembled = dict(source)
    assembled.update(overlay)
    closure = json.loads(archives["consumer"][1].read(archives["consumer"][0]["root"] + "/FIXED_CLOSURE.json"))
    assert len(closure["entries"]) == 111
    existing = added = 0
    for entry in closure["entries"]:
        data = assembled[entry["path"]]
        assert len(data) == entry["bytes"] and digest(data) == entry["sha256"], entry["path"]
        assert git_blob(data) == entry["git_blob_sha1"], entry["path"]
        existing += entry["path"] in source
        added += entry["path"] in overlay
    assert (existing, added) == (18, 93)
    result = {"package_sha256_and_crc": "PASS", "packages": len(archives), "zip_members": len(member_manifest),
              "consumer_closure": "111/111 PASS", "source_existing": existing, "overlay_added": added,
              "source_files_preserved": len(source), "assembled_source_files": len(assembled),
              "product_execution": "NOT_RUN", "fixture_execution": "NOT_RUN", "mac_access": "NOT_USED"}
    if args.destination:
        destination = Path(args.destination)
        if not destination.is_absolute() or destination.exists():
            raise ValueError("Destination must be an absolute NEW directory")
        for parent in (destination, *destination.parents):
            if parent.is_symlink():
                raise ValueError("Symlink destination path")
        destination.mkdir(parents=True, exist_ok=False)
        for role, (package, archive) in archives.items():
            target = destination / "unpacked"
            for member in archive.infolist():
                if member.is_dir():
                    continue
                path = target / member.filename
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as stream:
                    stream.write(archive.read(member))
        source_root = destination / "unpacked" / archives["source"][0]["root"]
        for name, data in overlay.items():
            target = source_root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(data)
        for name, data in assembled.items():
            assert (source_root / name).read_bytes() == data, name
        result["source_root"] = str(source_root)
        result["revision_root"] = str(destination / "unpacked" / archives["revision"][0]["root"] / "e06d-original-fixture")
        result["offline_root"] = str(destination / "unpacked" / archives["offline"][0]["root"] / "1a699a0-original-fixture")
        result["physical_assembly"] = "PASS; original bytes preserved; no product/test execution"
        (destination / "ASSEMBLY_RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
