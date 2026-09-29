"""Evidence runner, not a service/producer. Real graph tests are never skipped.

No HOME alteration, fake LangGraph, production monkeypatch or dependency install.
The audit hook prevents network/child processes during the tests, and accesses
by filename to known legacy HOME state. It is not a general filesystem sandbox.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--suite", choices=("boundary", "graph", "baseline", "all"), default="all")
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--root", type=Path, help="explicit isolated tree, for baseline/patch replay only")
    args=parser.parse_args()
    root=(args.root or Path(__file__).resolve().parents[2]).absolute()
    evidence=args.evidence_dir.absolute()
    evidence.mkdir(parents=True, exist_ok=True)
    sys.dont_write_bytecode=True
    sys.path[:0]=[str(root), str(root/"tests")]
    os.chdir(root)
    import pytest
    def source_bytes():
        return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob('*') if p.is_file()
                and not any(part in {'.git','__pycache__','.pytest_cache'} for part in p.relative_to(root).parts)
                and evidence not in p.parents and p != evidence}
    source_before=source_bytes()
    home=os.environ.get("HOME")
    legacy=[Path.home()/s for s in (".duanxian-agents", ".vibe-astock", ".config/mimo", ".config/cc-switch")]
    blocked=[]
    def audit(event, values):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.bind", "subprocess.Popen", "os.system", "os.posix_spawn"}:
            blocked.append({"event":event})
            raise RuntimeError("offline fixture denies network and child processes")
        if event in {"open", "os.mkdir", "os.remove", "os.rmdir", "os.listdir", "os.scandir"} and values:
            name=values[0]
            if isinstance(name, (str,bytes)):
                p=Path(os.fsdecode(name)).absolute()
                if any(p==r or r in p.parents for r in legacy):
                    blocked.append({"event":event,"scope":"legacy_home_state"})
                    raise RuntimeError("legacy HOME state is out of scope")
    sys.addaudithook(audit)
    original_boundary=["tests/test_vibe_ownership_boundary.py", "tests/test_vibe_owned_inputs.py", "tests/test_vibe_owned_nodes.py"]
    original_other=["tests/test_research_review_generation.py", "tests/test_daily_research_review.py", "tests/test_a_formula_increment_offline.py"]
    new_boundary=["tests/test_a_known_history_keys.py", "tests/test_vibe_task_lock.py",
        "tests/test_vibe_data_owner.py", "tests/test_vibe_model_factory.py",
        "tests/test_vibe_evidence_chain.py", "tests/test_vibe_assembly.py",
        "tests/test_vibe_calculation_parity.py", "tests/test_vibe_last_boundary_gates.py"]
    graph=["tests/test_vibe_real_graph.py", "tests/test_vibe_cli_real_graph.py"]
    if args.suite=="boundary": tests=original_boundary+new_boundary
    elif args.suite=="graph": tests=graph
    elif args.suite=="baseline": tests=original_boundary+[graph[0]]+original_other
    else: tests=original_boundary+new_boundary+graph+original_other
    command=["-q", "-o", "addopts=", "--continue-on-collection-errors", "-p", "no:cacheprovider", "-p", "no:metadata", "--basetemp="+str(evidence/"tmp"), "--junitxml="+str(evidence/"results.xml"), *tests]
    versions={}
    for name in ("pytest", "pydantic", "langgraph", "langchain-core", "langchain-openai", "pandas", "akshare", "pyarrow"):
        try: versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: versions[name]="MISSING"
    result=int(pytest.main(command))
    source_after=source_bytes()
    drift=sorted(k for k in source_before.keys() | source_after.keys()
                 if source_before.get(k) != source_after.get(k))
    source_pin=source_before.get('domains/research_review_generation/OWNED_SOURCE_MANIFEST.json')
    runner_exit=result if result else (1 if drift or os.environ.get('HOME') != home else 0)
    summary={"suite":args.suite,"pytest_exit_code":result,"python":sys.version,"platform":" ".join(os.uname()) if hasattr(os,"uname") else sys.platform,
        "dependencies":versions,"root":str(root),"source_manifest_sha256":source_pin,"source_files_before":source_before,"source_file_drift":drift,"runner_exit_code":runner_exit,"pytest_arguments":command,"HOME_unchanged":os.environ.get("HOME")==home,
        "blocked_actions":blocked,"graph_faked_or_skipped":False,
        "real_authority_provider_calls":"ACTUAL_OWNED_CALCULATIONS_AND_RAW_OWNER_WITH_SYNTHETIC_TRANSPORT",
        "raw_provider_deduplication":"ASSERTED_AT_FIXTURE_RAW_BOUNDARY; LIVE_AND_SDK_INTERNAL_HTTP_CANNOT_CONFIRM","deployed":False,"natural_run":"CANNOT_CONFIRM"}
    (evidence/"result.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
    return runner_exit

if __name__=="__main__":
    raise SystemExit(main())
