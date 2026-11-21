"""Rebase only copied candidate venv metadata and freeze the runtime delta."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess


TASK = Path(__file__).resolve().parent
RELEASE = TASK / "v4-main-r4-review-remediation-20261121"
RUNTIME = RELEASE / "runtime"
PREVIOUS_CANDIDATE_RUNTIME = TASK / "candidate/runtime"
R4_BUNDLE = TASK.parents[1] / "v4_main_autorun_r4_release_readiness_20261121" / "private" / "bundle"
R4_ASSEMBLY = R4_BUNDLE / "ASSEMBLY_RECEIPT.json"
R4_INVENTORY = R4_BUNDLE / "RUNTIME_INVENTORY.json"
PYCACHE_PREFIX = "/dev/null/v4-main-r4-source-only-pycache"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_files(root: Path) -> list[dict]:
    result = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs.sort()
        for name in list(dirs):
            path = Path(directory) / name
            if path.is_symlink():
                result.append({"path": path.relative_to(root).as_posix(), "kind": "symlink", "target": os.readlink(path)})
                dirs.remove(name)
        for name in sorted(names):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            info = path.lstat()
            if path.is_symlink():
                result.append({"path": relative, "kind": "symlink", "target": os.readlink(path)})
            else:
                result.append({"path": relative, "kind": "file", "sha256": file_digest(path),
                               "size": info.st_size, "mode": format(info.st_mode & 0o777, "04o")})
    return sorted(result, key=lambda row: row["path"])


def run_probe(python: Path, *, no_site: bool, app_root: Path | None = None) -> dict:
    code = (
        "import json,sys,sysconfig;from pathlib import Path;"
        "print(json.dumps({'executable':str(Path(sys.executable).resolve()),'prefix':str(Path(sys.prefix).resolve()),"
        "'base_prefix':str(Path(sys.base_prefix).resolve()),'base_exec_prefix':str(Path(sys.base_exec_prefix).resolve()),"
        "'stdlib':str(Path(sysconfig.get_path('stdlib')).resolve()),'no_site':sys.flags.no_site,"
        "'dont_write_bytecode':sys.dont_write_bytecode,'pycache_prefix':sys.pycache_prefix}))"
    )
    command = [str(python)]
    if python == RUNTIME / "venvs/v4-mac/bin/python":
        command += ["-X", f"pycache_prefix={PYCACHE_PREFIX}"]
    command.append("-B")
    if no_site:
        command.append("-S")
    command += ["-c", code]
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPYCACHEPREFIX": PYCACHE_PREFIX,
        "V4_SOURCE_ONLY_PYCACHE_REQUIRED": "1",
    }
    if app_root is not None:
        env["PYTHONPATH"] = str(app_root)
    result = subprocess.run(command, cwd=app_root or RUNTIME, env=env,
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def main() -> None:
    assembly = json.loads(R4_ASSEMBLY.read_bytes())
    source_runtime = Path(assembly["candidate_runtime"]).resolve(strict=True)
    if source_runtime == RUNTIME.resolve():
        raise RuntimeError("SOURCE_AND_CANDIDATE_RUNTIME_MUST_DIFFER")

    rebased = []
    for venv in ("v4-mac", "v4-hk02"):
        cfg = RUNTIME / "venvs" / venv / "pyvenv.cfg"
        source_cfg = source_runtime / "venvs" / venv / "pyvenv.cfg"
        before = source_cfg.read_bytes()
        current = cfg.read_bytes()
        old_root = str(source_runtime).encode()
        new_root = str(RUNTIME.resolve()).encode()
        previous_candidate_root = str(PREVIOUS_CANDIDATE_RUNTIME.resolve()).encode()
        if old_root not in before:
            raise RuntimeError("EXPECTED_R4_RUNTIME_ROOT_NOT_PRESENT:" + venv)
        after = before.replace(old_root, new_root)
        normalized_current = current.replace(previous_candidate_root, new_root)
        if old_root in after or after == before or current not in (before, after) and normalized_current != after:
            raise RuntimeError("VENV_ROOT_REBASE_FAILED:" + venv)
        if current != after:
            cfg.write_bytes(after)
        rebased.append({"path": cfg.relative_to(RUNTIME).as_posix(), "before_sha256": digest(before),
                        "after_sha256": digest(current if current == after else after),
                        "old_root_replacements": before.count(old_root),
                        "candidate_root": str(RUNTIME.resolve())})

    expected_stdlib_314 = RUNTIME / "python/cpython-3.14.6/lib/python3.14"
    mac_parent = run_probe(RUNTIME / "venvs/v4-mac/bin/python", no_site=True,
                           app_root=RELEASE / "app")
    mac_child = run_probe(RUNTIME / "venvs/v4-mac/bin/python", no_site=False,
                          app_root=RELEASE / "app")
    if Path(mac_parent["base_prefix"]) != RUNTIME / "python/cpython-3.14.6":
        raise RuntimeError("MAC_PARENT_BASE_PREFIX_NOT_CANDIDATE")
    if Path(mac_child["base_prefix"]) != RUNTIME / "python/cpython-3.14.6":
        raise RuntimeError("MAC_CHILD_BASE_PREFIX_NOT_CANDIDATE")
    if Path(mac_parent["stdlib"]) != expected_stdlib_314 or Path(mac_child["stdlib"]) != expected_stdlib_314:
        raise RuntimeError("MAC_STDLIB_NOT_CANDIDATE_RUNTIME")
    if mac_parent["no_site"] != 1 or mac_child["no_site"] != 0:
        raise RuntimeError("MAC_PARENT_CHILD_SITE_FLAGS_CHANGED")
    source_inventory = json.loads(R4_INVENTORY.read_bytes())
    source_entries = source_inventory["entries"]
    candidate_entries = tree_files(RUNTIME)
    source_by_path = {row["path"]: row for row in source_entries}
    candidate_by_path = {row["path"]: row for row in candidate_entries}
    if source_by_path.keys() != candidate_by_path.keys():
        raise RuntimeError("RUNTIME_PATH_SET_CHANGED")
    changes = [{"path": path, "before": source_by_path[path], "after": candidate_by_path[path]}
               for path in sorted(source_by_path) if source_by_path[path] != candidate_by_path[path]]
    expected_paths = {"venvs/v4-mac/pyvenv.cfg", "venvs/v4-hk02/pyvenv.cfg"}
    if {row["path"] for row in changes} != expected_paths:
        raise RuntimeError("RUNTIME_DELTA_OUTSIDE_VENV_REBASE:" + ",".join(row["path"] for row in changes))
    aggregate = digest(json.dumps(candidate_entries, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")).encode())

    base_plist = plistlib.loads((source_runtime.parent / "launchd.plist").read_bytes())
    candidate_plist = plistlib.loads((RELEASE / "launchd.plist").read_bytes())
    external_hk_names = ("V4_HK_0_2_PYTHON", "V4_HK_0_2_REAL_PYTHON", "V4_RESEARCH_PANEL_HK_PYTHON_EXECUTABLE")
    base_env = base_plist["EnvironmentVariables"]
    candidate_env = candidate_plist["EnvironmentVariables"]
    external_hk = {name: candidate_env.get(name) for name in external_hk_names}
    if any(candidate_env.get(name) != base_env.get(name) for name in external_hk_names):
        raise RuntimeError("DECLARED_EXTERNAL_HK_RUNTIME_BINDING_CHANGED")
    external_hk_real = Path(candidate_env["V4_HK_0_2_REAL_PYTHON"]).resolve(strict=True)
    candidate_hk_link = RUNTIME / "venvs/v4-hk02/bin/python3.13"
    expected_hk_target = str(external_hk_real.parents[3] / "python/cpython-3.13.12/bin/python3.13")
    if not candidate_hk_link.is_symlink() or os.readlink(candidate_hk_link) != expected_hk_target:
        raise RuntimeError("DECLARED_EXTERNAL_HK_EXECUTABLE_LINK_DRIFT")
    if Path(expected_hk_target).resolve(strict=True) != Path(expected_hk_target):
        raise RuntimeError("DECLARED_EXTERNAL_HK_EXECUTABLE_TARGET_INVALID")

    (TASK / "FINAL_RUNTIME_INVENTORY.json").write_text(json.dumps({
        "schema": "v4.r4_remediation_runtime_inventory.v1", "root": str(RUNTIME.resolve()),
        "entry_count": len(candidate_entries), "aggregate_sha256": aggregate, "entries": candidate_entries,
    }, ensure_ascii=False, indent=2) + "\n")
    receipt = {
        "schema": "v4.r4_candidate_runtime_rebase.v1",
        "status": "PASS_COPIED_RUNTIME_REBASED_AND_FROZEN",
        "source_runtime": str(source_runtime), "candidate_runtime": str(RUNTIME.resolve()),
        "source_runtime_inventory_sha256": source_inventory["aggregate_sha256"],
        "final_runtime_inventory_sha256": aggregate, "runtime_entry_count": len(candidate_entries),
        "exact_runtime_delta": changes, "venv_metadata_rebases": rebased,
        "final_interpreter_proofs": {"mac_parent_no_site": mac_parent, "daemon_child_site": mac_child},
        "unused_hk02_copy": {"python3_13_symlink_target": expected_hk_target,
                              "interpreter_invoked": False,
                              "reason": "Main launch bindings intentionally select the separately declared external HK runtime"},
        "source_vs_candidate_interpreter_sha256": {
            "cpython314": {"source": file_digest(source_runtime / "venvs/v4-mac/bin/python"),
                           "candidate": file_digest(RUNTIME / "venvs/v4-mac/bin/python")},
            "cpython313": {"source": file_digest(source_runtime / "venvs/v4-hk02/bin/python"),
                           "candidate": file_digest(RUNTIME / "venvs/v4-hk02/bin/python")},
        },
        "external_hk_launch_bindings_preserved": external_hk,
        "launcher_or_scheduler_started": False, "external_hk_python_invoked": False,
    }
    (TASK / "RUNTIME_REBASE_RECEIPT.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "runtime_inventory_sha256": aggregate,
                      "runtime_delta_paths": [row["path"] for row in changes],
                      "mac_parent_base_prefix": mac_parent["base_prefix"],
                      "mac_child_base_prefix": mac_child["base_prefix"],
                      "mac_parent_no_site": mac_parent["no_site"], "mac_child_no_site": mac_child["no_site"]}))


if __name__ == "__main__":
    main()
