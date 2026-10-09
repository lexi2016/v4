"""Run one isolated review suite and record exact sources, command and output."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent
PROJECT = WORK.parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--suite", choices=["api", "api-author", "writer", "writer-finalization", "clock", "clock-author"], required=True)
parser.add_argument("--label", required=True)
parser.add_argument("--python", help="Existing Python interpreter with pytest; defaults to the review venv when present, otherwise the current interpreter")
args = parser.parse_args()
if not args.label.replace("_", "").replace("-", "").isalnum():
    raise SystemExit("safe label required")
suite, report = {
    "api": (ROOT / "api_review/tests", ROOT / "api_review"),
    "api-author": (WORK / "api_ui/tests", ROOT / "api_review"),
    "writer": (WORK / "receipt_binding/tests", ROOT / "receipt_review"),
    "writer-finalization": (ROOT / "receipt_review/tests", ROOT / "receipt_review"),
    "clock": (ROOT / "clock_review/tests", ROOT / "clock_review"),
    "clock-author": (WORK / "entrypoint_clock/tests", ROOT / "clock_review"),
}[args.suite]
out = report / "evidence" / args.label
out.mkdir(parents=True, exist_ok=False)
review_python = PROJECT / "issue28/references/work/test-venv/bin/python"
python = Path(args.python) if args.python else (review_python if review_python.exists() else Path(sys.executable))
if args.suite.startswith("clock"):
    paths = sorted((WORK / "entrypoint_clock").rglob("*.py"))
else:
    paths = [WORK / "api_ui/after/source/actual_api/stage_center/execution_evidence.py"]
    paths += sorted((WORK / "api_ui/after/conditional_api").rglob("*.py"))
    paths += sorted((WORK / "receipt_binding/after/source").rglob("*.py"))
    paths += [ROOT / "api_review/tests/conftest.py", WORK / "quote_fields/SUPPORT_MANIFEST.json"]
paths += sorted(suite.rglob("*.py"))
paths = list(dict.fromkeys(paths))
def identities():
    return [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
             "bytes": len(p.read_bytes())} for p in paths]
before = identities()
targets = ([suite / "test_owner_receipt_binding.py", suite / "test_slot_receipt_wiring.py"]
           if args.suite == "writer" else [suite])
command = [str(python), "-m", "pytest", "-q", *map(str, targets), "--junitxml=" + str(out / "junit.xml")]
started = datetime.now(timezone.utc).isoformat()
process = subprocess.run(command, text=True, capture_output=True)
after = identities()
(out / "stdout.log").write_text(process.stdout)
(out / "stderr.log").write_text(process.stderr)
metadata = {"command": command, "returncode": process.returncode,
    "platform": platform.platform(), "started_at": started,
    "completed_at": datetime.now(timezone.utc).isoformat(),
    "python": subprocess.run([str(python), "--version"], text=True, capture_output=True).stdout.strip(),
    "sources_unchanged": before == after, "sources": before,
    "test_scope": "SOURCE_SLICE_WITH_ORIGINAL_HISTORICAL_SUPPORT_NOT_MAC_RUNTIME"}
(out / "execution.json").write_text(json.dumps(metadata, indent=2) + "\n")
print(process.stdout[-16000:])
print(process.stderr[-2000:])
print(json.dumps({"returncode": process.returncode, "sources_unchanged": before == after, "evidence": str(out)}))
raise SystemExit(process.returncode if before == after else 9)
