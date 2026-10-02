#!/usr/bin/env python3
"""Apply only BR003-C2 to the failed isolated candidate, compile first, then run 39+2 tests.

No provider calls, service starts, deployment, scheduler execution, or business-data writes.
"""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
PATCH = ROOT / "br003-c2.incremental.patch"
PINS = json.loads((ROOT / "SOURCE_PINS.json").read_text())
UPSTREAM = REPO / "research" / "manager-bi-contract-fix-20261001"
BR003_V1 = REPO / "research" / "manager-br003-owner-continuation-20261002"
TARGET = Path("apps/web/src/api/managerWorkspace.ts")

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--app", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    app = args.app.resolve()
    out = args.output.resolve()
    if not app.is_dir() or "releases" in app.parts or out.exists() or out == app or out.is_relative_to(app):
        ap.error("use the existing disposable failed candidate and a new output directory")
    target = app / TARGET
    if not target.is_file():
        ap.error("managerWorkspace.ts missing")
    expected_before = PINS["failed_candidate_sha256"]
    expected_after = PINS["fixed_candidate_sha256"]
    observed = sha(target)
    if observed not in {expected_before, expected_after}:
        print(json.dumps({"status":"SOURCE_DRIFT","actual":observed,"before":expected_before,"after":expected_after},indent=2))
        return 2
    for rel, expected in PINS["unchanged_companion_files"].items():
        path = app / rel
        if not path.is_file() or sha(path) != expected:
            print(json.dumps({"status":"COMPANION_SOURCE_DRIFT","path":rel,"actual":sha(path) if path.is_file() else None,"expected":expected},indent=2))
            return 2

    out.mkdir(parents=True)
    receipt = {
        "status":"NOT_RUN","patch_applied":False,"source_before":observed,
        "production_allowed":False,"buy_gate_updated":False,"orders_sent":False,
        "DEPLOYED":"NOT_RUN","API_VERIFIED":"NOT_RUN","UI_VERIFIED":"NOT_RUN"
    }
    try:
        if observed == expected_before:
            for check in (True, False):
                cmd = ["git","apply",*(["--check"] if check else []),str(PATCH)]
                run = subprocess.run(cmd,cwd=app,text=True,capture_output=True)
                (out / ("patch_check.log" if check else "patch_apply.log")).write_text(run.stdout+run.stderr)
                if run.returncode:
                    raise RuntimeError("BR003_C2_PATCH_APPLY_FAILED")
            receipt["patch_applied"] = True
        if sha(target) != expected_after:
            raise RuntimeError("BR003_C2_AFTER_SHA_MISMATCH")

        built = out / "tsc"
        tsc = shutil.which("tsc")
        if not tsc:
            raise RuntimeError("TSC_NOT_FOUND")
        compile_cmd = [
            tsc,
            str(app/"apps/web/src/api/managerWorkspace.ts"),
            str(app/"apps/web/src/manager-selection/researchAttention.ts"),
            str(app/"apps/web/src/manager-selection/announcementObservation.ts"),
            "--target","ES2020","--module","ES2020","--lib","ES2020,DOM",
            "--outDir",str(built),"--strict","--skipLibCheck",
        ]
        comp = subprocess.run(compile_cmd,text=True,capture_output=True)
        (out/"tsc.log").write_text(comp.stdout+comp.stderr)
        receipt["tsc_exit_code"] = comp.returncode
        if comp.returncode:
            receipt["status"] = "TSC_FAILED"
            return comp.returncode

        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join([str(app),str(UPSTREAM/"tests"),str(BR003_V1/"tests")])
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["BI_APP"] = str(app)
        env["BI_OUTPUT"] = str(out/"cases")
        test_cmd = [
            sys.executable,"-m","pytest","-c",str(UPSTREAM/"pytest.ini"),
            str(UPSTREAM/"tests/test_cross_boundary.py"),
            str(BR003_V1/"tests/test_br003_target_date.py"),
            "-q","--tb=short","--junitxml="+str(out/"junit.xml"),
        ]
        test = subprocess.run(test_cmd,cwd=ROOT,env=env,text=True,capture_output=True)
        (out/"pytest.log").write_text(test.stdout+test.stderr)
        print(test.stdout+test.stderr)
        receipt.update(
            status="ISOLATED_TSC_AND_41_PASS" if test.returncode==0 else "TEST_FAILED",
            test_exit_code=test.returncode,
            source_after=sha(target),
            compile_command=compile_cmd,
            test_command=test_cmd,
        )
        return test.returncode
    except (OSError, ValueError, RuntimeError, AssertionError) as exc:
        receipt.update(status="FAILED",error=type(exc).__name__,reason=str(exc))
        print(json.dumps(receipt,ensure_ascii=False,indent=2))
        return 2
    finally:
        (out/"WORK_RECEIPT.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n")

if __name__ == "__main__":
    raise SystemExit(main())
