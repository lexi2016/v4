"""Run the exact frozen 174 against the final R4 app and copied Main runtime."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent
SOURCE_ONLY_PYCACHE_PREFIX="/dev/null/v4-main-r4-source-only-pycache"
TESTS=[
    "tests/test_qfq_task_continuity.py",
    "tests/test_qfq_registry_summary.py",
    "tests/test_governance_unique_roots.py",
    "tests/test_daily_derivatives_registry_summary.py",
    "tests/test_qfq_dependency_identity.py",
    "tests/test_main_root_binding_candidate.py",
]
TARGETED=[
    "tests/test_qfq_dependency_identity.py::test_D17_two_processes_share_one_complete_identity_reservation",
    "tests/test_qfq_dependency_identity.py::test_D18_concurrent_registry_or_token_change_fails_cas",
    "tests/test_qfq_task_continuity.py::test_repeated_failure_reuses_original_peak_and_cumulative_accounting",
    "tests/test_qfq_task_continuity.py::test_rekey_preserves_every_old_row_field_and_one_reservation",
    "tests/test_qfq_task_continuity.py::test_cross_root_unknown_row_blocks_actual_governed_owner_without_bridge",
    "tests/test_qfq_task_continuity.py::test_cross_root_unknown_row_created_after_preflight_is_fenced_at_claim",
]


def main():
    assembly=json.loads((HERE/"ASSEMBLY_RECEIPT.json").read_bytes())
    release=Path(assembly["release_root"])
    app=release/"app"
    plist=plistlib.loads((release/"launchd.plist").read_bytes())
    binding=plist["EnvironmentVariables"]
    runtime=Path(binding["V4_RUNTIME_ROOT"])
    site=runtime/"venvs/v4-mac/lib/python3.14/site-packages"
    python=runtime/"venvs/v4-mac/bin/python"
    env={k:v for k,v in os.environ.items() if not k.startswith(("V4_","PYTHON","PANEL_","RESEARCH_PANEL_"))}
    env.update(binding)
    env.update(PYTHONPATH=os.pathsep.join((str(app),str(site),binding.get("PYTHONPATH",""))),
        PYTHONPYCACHEPREFIX=SOURCE_ONLY_PYCACHE_PREFIX,
        PYTHONDONTWRITEBYTECODE="1",PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        V4_SOURCE_ONLY_PYCACHE_REQUIRED="1")
    probe=[str(python),"-X",f"pycache_prefix={SOURCE_ONLY_PYCACHE_PREFIX}","-B","-S","-c",
           "import runpy,sys;runpy.run_path(sys.argv[1],run_name='__main__')",str(HERE/"runtime_probe.py")]
    p=subprocess.run(probe,cwd=app,env=env,capture_output=True,text=True)
    (HERE/"runtime-probe.stdout.txt").write_text(p.stdout+p.stderr)
    print(p.stdout,p.stderr,flush=True)
    if p.returncode:
        raise SystemExit(p.returncode)
    # Keep loader/environment identical; suppress production control env only
    # for unrelated fixture code that deliberately sets its own scoped policy.
    test_env={k:v for k,v in env.items() if not k.startswith(("V4_","RESEARCH_PANEL_"))}
    test_env.update(PYTHONPATH=env["PYTHONPATH"],PYTHONDONTWRITEBYTECODE="1",
                    PYTHONPYCACHEPREFIX=SOURCE_ONLY_PYCACHE_PREFIX,
                    V4_SOURCE_ONLY_PYCACHE_REQUIRED="1",
                    PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",V4_A_QFQ_COMPUTE_BACKEND="process")
    with tempfile.TemporaryDirectory(prefix="v4-r4-final174-") as directory:
        temp=Path(directory).resolve()
        (HERE/"TEST_TEMP_OWNERSHIP.json").write_text(json.dumps(
            dict(root=str(temp),owner="r4_bundle_writer",lifecycle="automatic cleanup after suite"),indent=2)+"\n")
        cmd=[str(python),"-X",f"pycache_prefix={SOURCE_ONLY_PYCACHE_PREFIX}","-B","-S","-m","pytest","-q","-p","no:cacheprovider",
             "--tb=short","--basetemp",str(temp/"pytest"),*TESTS]
        p=subprocess.run(cmd,cwd=app,env=test_env,capture_output=True,text=True)
    (HERE/"pytest-full.stdout.txt").write_text(p.stdout+p.stderr)
    print(p.stdout,p.stderr,flush=True)
    if p.returncode or not re.search(r"\b174 passed\b",p.stdout):
        raise SystemExit(p.returncode or 1)
    # The focused list is a selection map of cases in the already completed
    # suite. No duplicate rerun is needed to turn its names into evidence.
    out=dict(status="PASS_FINAL_174",test_command=cmd,return_code=p.returncode,passed=174,failed=0,skipped=0,
        stdout=p.stdout,stderr=p.stderr,
        exact_runtime_probe="RUNTIME_PROBE_RECEIPT.json",
        focused_in_completed_suite=TARGETED,
        test_file_sha256={name:hashlib.sha256((app/name).read_bytes()).hexdigest() for name in TESTS},
        actual_python_sha256=hashlib.sha256(python.read_bytes()).hexdigest(),
        source_inventory_sha256=assembly["candidate_validation"]["app_inventory_sha256"])
    (HERE/"FINAL_174_TEST_RECEIPT.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")


if __name__=="__main__":
    main()
