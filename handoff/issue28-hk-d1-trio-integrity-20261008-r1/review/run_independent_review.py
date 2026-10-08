"""Run only the scoped Issue28 Stage integrity review, using fresh isolated roots.

Inputs are the supplied source package and candidate. No input file is modified.
The output path must not already exist. Synthetic fixtures remain in output/work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

BEFORE = "92e8fb2be06e6530c33f3cf2f5b44f29b0bcf7875e6a5902260f8be4c814f735"
AFTER = "b20baa18d0ee9748971db835f6fb3dd9a0e1d66aabd8da8d450aee3a4a528a8e"
HELPER = "stage_center/_runner_parts/hk_input_validation.py"
OWNERS = ("actual_stage_owner", "canonical")
HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    package = options.package.resolve()
    output = options.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "logs").mkdir()
    manifest = json.loads((package / "test_run/SOURCE_IDENTITIES.json").read_text())
    verified = []
    selected = []
    for entry in manifest["files"]:
        rel = Path(entry["path"])
        if rel.parts[0] == "owners":
            source = package / "baseline/source" / Path(*rel.parts[1:])
        elif rel.parts[0] == "support":
            source = package / "test_run" / rel
        elif rel.parts[0] == "tests":
            source = package / "baseline" / rel
        else:
            raise AssertionError(rel)
        assert sha(source) == entry["sha256"], source
        assert source.stat().st_size == entry["bytes"], source
        verified.append({"path": str(source.relative_to(package)),
                         "sha256": sha(source), "bytes": source.stat().st_size,
                         "role": entry["role"]})
        selected.append((rel, source))
    for owner in OWNERS:
        assert sha(package / "baseline/source" / owner / HELPER) == BEFORE
        candidate = package / "candidate" / owner / HELPER
        assert sha(candidate) == AFTER
        verified.append({"path": str(candidate.relative_to(package)),
                         "sha256": AFTER, "bytes": candidate.stat().st_size,
                         "role": "INDEPENDENTLY_HASHED_CANDIDATE"})
    new_test = package / "tests/test_hk_split_date_identity_closure.py"
    verified.append({"path": str(new_test.relative_to(package)), "sha256": sha(new_test),
                     "bytes": new_test.stat().st_size, "role": "SUPPLIED_TARGETED_TEST"})
    results = []
    for phase in ("before", "after"):
        for owner in OWNERS:
            root = output / "work" / f"{phase}-{owner}"
            root.mkdir(parents=True)
            for rel, source in selected:
                if rel.parts[0] == "owners":
                    if rel.parts[1] != owner:
                        continue
                    dest = root / "owner" / Path(*rel.parts[2:])
                else:
                    dest = root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
            if phase == "after":
                shutil.copyfile(package / "candidate" / owner / HELPER, root / "owner" / HELPER)
            shutil.copyfile(new_test, root / "tests" / new_test.name)
            shutil.copyfile(HERE / "test_root_identity_probe.py", root / "tests/test_root_identity_probe.py")
            shutil.copyfile(HERE / "review_conftest.py", root / "conftest.py")
            expected = {}
            for name in ("stage_center.runner", "stage_center.calendar",
                         "stage_center._runner_parts.hk_input_validation",
                         "infrastructure.preselection_pool_store",
                         "infrastructure.preselection_pool_readers",
                         "infrastructure.preselection_pool_sources"):
                relative = "owner/" + name.replace(".", "/") + ".py"
                expected[name] = {"path": relative, "sha256": sha(root / relative)}
            (root / "expected_modules.json").write_text(json.dumps(expected, indent=2) + "\n")
            for suite, test_file in (("supplied", new_test.name), ("reviewer", "test_root_identity_probe.py")):
                tag = f"{phase}-{owner}-{suite}"
                log = output / "logs" / (tag + ".log")
                junit = output / "logs" / (tag + ".xml")
                imports = output / "logs" / (tag + "-imports.json")
                command = [sys.executable, "-B", "-m", "pytest", "-q", "-ra", "-p", "no:cacheprovider",
                           "--basetemp=" + str(root / (suite + "-tmp")),
                           "--junitxml=" + str(junit), "tests/" + test_file]
                env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", REVIEW_IMPORT_LOG=str(imports))
                env.pop("PYTHONPATH", None)
                completed = subprocess.run(command, cwd=root, env=env, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, text=True)
                log.write_text(completed.stdout)
                if not junit.exists():
                    raise RuntimeError(f"No JUnit: {tag}; see {log}")
                cases = ET.parse(junit).getroot().findall(".//testcase")
                failures = [case.attrib["name"] for case in cases if case.find("failure") is not None]
                errors = [case.attrib["name"] for case in cases if case.find("error") is not None]
                skipped = [case.attrib["name"] for case in cases if case.find("skipped") is not None]
                result = {"phase": phase, "owner": owner, "suite": suite, "command": command,
                          "cwd": str(root), "exit_code": completed.returncode,
                          "cases": len(cases), "passed": len(cases)-len(failures)-len(errors)-len(skipped),
                          "failures": failures, "errors": errors, "skipped": skipped,
                          "log": str(log.relative_to(output)), "junit": str(junit.relative_to(output)),
                          "imports": str(imports.relative_to(output))}
                assert json.loads(imports.read_text())["asserted_exact_loaded_modules"] is True
                results.append(result)
                print(json.dumps({key: result[key] for key in ("phase", "owner", "suite", "cases", "passed", "failures", "errors")}))
    report = {"environment": {"executable": sys.executable, "python_version": sys.version,
                              "platform": platform.platform(), "machine": platform.machine()},
              "inputs": {"package": str(package), "before_helper_sha256": BEFORE,
                         "after_helper_sha256": AFTER,
                         "source_manifest_sha256": sha(package / "test_run/SOURCE_IDENTITIES.json"),
                         "review_conftest_sha256": sha(HERE / "review_conftest.py"),
                         "reviewer_probe_sha256": sha(HERE / "test_root_identity_probe.py")},
              "verified_inputs": verified, "results": results}
    (output / "RESULTS.json").write_text(json.dumps(report, indent=2) + "\n")
    assert all(not r["errors"] and not r["skipped"] for r in results)
    assert all(r["passed"] == r["cases"] and r["exit_code"] == 0 for r in results if r["phase"] == "after")
    assert all(len(r["failures"]) == (4 if r["suite"] == "supplied" else 2)
               and r["exit_code"] == 1 for r in results if r["phase"] == "before")


if __name__ == "__main__":
    main()
