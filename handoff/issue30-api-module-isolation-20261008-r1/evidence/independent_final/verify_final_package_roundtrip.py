"""Independent exact-identity, source-only delivery patch verification.

This runs only git init/apply in a disposable directory. No product module is
imported, no service is called, and no deployment path is written.
"""
from pathlib import Path
import argparse
import ast
import datetime
import hashlib
import json
import os
import platform
import stat
import subprocess
import sys
import tempfile


EXPECTED_AFTER = {
    "ops/api_release_integration.py": "1f4afc70d7e5920b67c2b148def6b9167819664c33c92b475d919a097b9dd050",
    "ops/build_release_candidate.py": "81f4290a6f51e5958048d782c2d4b1eecfc42f892e387e6c1a22bb71912abef6",
    "ops/prepare_api_only_cutover.py": "0fee40c13bdb76d8d4d7b5b0068eb8b6e7cade9187a5f3c3154b7d6238a1af4c",
    "ops/create_api_module_delta.py": "04e67a3ce948eecf9dac04083277bd919c7ec8880ec5814bbe57e7a5ba8d0072",
    "actual_cutover_reference/api_only_cutover_r2_ready.py": "389be853923a72066472ad229129a9a41ef9e9785f1b729aa468ed3e58df19f5",
    "apps/api/v35_api/app.py": "5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5",
    "apps/api/v35_api/preselection_router.py": "718d54a6c6aa8cde2871ce4dc41cbc1d825f199a57b605e4f5ec70d8c4fe19ae",
    "apps/api/v35_api/preselection_service.py": "91eba3ad5d005161d876f9c2f1a69ff51db56f129267cde29394d4581d1a4c95",
}
EXPECTED_BEFORE = {
    "ops/api_release_integration.py": "579bb0986404232bb497027705d9d7a0f18ee74ad663a44e8ce0befd0f9cb24a",
    "ops/build_release_candidate.py": "86ba30a04df15dad6f15587a3a63597d375d11af9da00b41241fa6b026e73155",
    "ops/prepare_api_only_cutover.py": "2a6cc7972cdf367965001314ee20f459579028accbc132345ab37db99aaee0a6",
    "actual_cutover_reference/api_only_cutover_r2_ready.py": "ddb7c5b5b95aed1e2e9fb8a592503b88ec3966f6e34c9350c47648bb0f97ce4a",
    "apps/api/v35_api/app.py": "90a2bf6390c6c0e219aa3d9bb22bc3b3630ecb2d447df494ae69425933424ed7",
}
EXPECTED_POLICY = "c55f4f09269661e0db05fa566aa1be9a96b2aa681912223c38fb802c4127e1b6"
EXPECTED_PATCH = "6caf2d02546e17aabfeb06c721fa3ac8748aaf0e1f73aeb13ffd7c9de3dfc86e"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def assignment(raw, name):
    return next(ast.literal_eval(node.value) for node in ast.parse(raw).body
                if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == name for target in node.targets))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    package = args.package_root.resolve(strict=True)
    out = args.output_dir.resolve(strict=True)
    manifest_path = package / "SOURCE_MANIFEST.json"
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw)
    patch = package / "patches/all_product_changes.patch"
    patch_raw = patch.read_bytes()
    assert sha(patch_raw) == EXPECTED_PATCH
    files = manifest["files"]
    assert len(files) == 8 and {item["path"] for item in files} == set(EXPECTED_AFTER)
    patch_paths = [line.split(" b/", 1)[1] for line in patch_raw.decode().splitlines()
                   if line.startswith("diff --git ")]
    assert len(patch_paths) == 8 and set(patch_paths) == set(EXPECTED_AFTER)
    assert {str(p.relative_to(package / "after")) for p in (package / "after").rglob("*")
            if p.is_file()} == set(EXPECTED_AFTER)
    source_checks = []
    before_bytes, after_bytes = {}, {}
    for item in files:
        rel = item["path"]
        after = package / item["after_path"]
        raw = after.read_bytes()
        assert after.resolve(strict=True) == after
        assert sha(raw) == item["after_sha256"] == EXPECTED_AFTER[rel]
        assert len(raw) == item["after_bytes"] and blob(raw) == item["after_git_blob"]
        assert stat.S_IMODE(after.stat().st_mode) == int(item["after_mode"], 8) == 0o644
        after_bytes[rel] = raw
        if rel in EXPECTED_BEFORE:
            before = package / item["before_path"]
            old = before.read_bytes()
            assert before.resolve(strict=True) == before
            assert sha(old) == item["before_sha256"] == EXPECTED_BEFORE[rel]
            assert len(old) == item["before_bytes"] and blob(old) == item["before_git_blob"]
            assert item["before_mode"] == "0644"
            before_bytes[rel] = old
        else:
            assert item["change"] == "add"
            assert all(item[key] is None for key in (
                "before_sha256", "before_path", "before_bytes", "before_mode", "before_git_blob"))
        source_checks.append({"path": rel, "before_sha256": item["before_sha256"],
                              "after_sha256": sha(raw), "before_mode": item["before_mode"],
                              "after_mode": item["after_mode"], "reviewed_source_sha_exact": True})
    core_pin = assignment(after_bytes["actual_cutover_reference/api_only_cutover_r2_ready.py"],
                          "INTEGRATION_GUARD_SHA256")
    assert core_pin == EXPECTED_AFTER["ops/api_release_integration.py"] == manifest["actual_publisher_core_pin"]
    policy = assignment(after_bytes["ops/api_release_integration.py"], "POLICY")
    assert sha(json.dumps(policy, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()) == EXPECTED_POLICY
    assert manifest["module_ownership_policy_sha256"] == EXPECTED_POLICY
    commands, forward, reverse = [], [], []
    previous_umask = os.umask(0o022)
    try:
        with tempfile.TemporaryDirectory(prefix="independent-package-roundtrip-", dir=out) as temp:
            temp = Path(temp)
            for rel, raw in before_bytes.items():
                p = temp / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(raw)
                p.chmod(0o644)
            for rel in EXPECTED_AFTER.keys() - EXPECTED_BEFORE.keys():
                assert not (temp / rel).exists()
            with (out / "final_package_roundtrip.log").open("w") as log:
                def run(command):
                    result = subprocess.run(command, cwd=temp, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, text=True, timeout=30)
                    commands.append({"command": command, "cwd": str(temp), "exit_code": result.returncode})
                    log.write(json.dumps(commands[-1]) + "\n" + result.stdout)
                    assert result.returncode == 0, result.stdout
                run(["git", "init", "-q"])
                run(["git", "apply", "--check", "--whitespace=nowarn", str(patch)])
                run(["git", "apply", "--whitespace=nowarn", str(patch)])
                for item in files:
                    p = temp / item["path"]
                    raw = p.read_bytes()
                    assert raw == after_bytes[item["path"]]
                    assert stat.S_IMODE(p.stat().st_mode) == 0o644
                    forward.append({"path": item["path"], "sha256": sha(raw), "mode": "0644"})
                run(["git", "apply", "--reverse", "--check", "--whitespace=nowarn", str(patch)])
                run(["git", "apply", "--reverse", "--whitespace=nowarn", str(patch)])
                for item in files:
                    p = temp / item["path"]
                    if item["change"] == "add":
                        assert not p.exists()
                        reverse.append({"path": item["path"], "absent": True})
                    else:
                        raw = p.read_bytes()
                        assert raw == before_bytes[item["path"]]
                        assert stat.S_IMODE(p.stat().st_mode) == 0o644
                        reverse.append({"path": item["path"], "sha256": sha(raw), "mode": "0644"})
                remaining = {str(p.relative_to(temp)) for p in temp.rglob("*")
                             if p.is_file() and ".git" not in p.relative_to(temp).parts}
                assert remaining == set(EXPECTED_BEFORE)
    finally:
        os.umask(previous_umask)
    assert manifest_path.read_bytes() == manifest_raw and patch.read_bytes() == patch_raw
    result = {
        "schema_version": "v4.issue30.independent_package_roundtrip.v1", "status": "PASS",
        "source_file_count": 8, "source_manifest_sha256": sha(manifest_raw),
        "patch_sha256": sha(patch_raw), "actual_publisher_core_pin": core_pin,
        "module_ownership_policy_sha256": EXPECTED_POLICY, "source_checks": source_checks,
        "forward": forward, "reverse": reverse, "commands": commands,
        "new_files_absent_after_reverse": True, "no_extra_product_paths": True,
        "package_bytes_unchanged": True, "process_umask": "0022",
        "scope": "source-only synthetic baseline; not current Mac file absence or modes",
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "python": sys.version, "platform": platform.platform(),
        "script_sha256": sha(Path(__file__).read_bytes()),
    }
    (out / "final_package_roundtrip.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in (
        "status", "source_file_count", "source_manifest_sha256", "patch_sha256",
        "actual_publisher_core_pin", "new_files_absent_after_reverse", "no_extra_product_paths")}, indent=2))


if __name__ == "__main__":
    main()
