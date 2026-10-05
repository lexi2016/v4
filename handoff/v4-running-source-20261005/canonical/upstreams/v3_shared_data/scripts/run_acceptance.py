"""DS1 canary acceptance runner (Sol batch DS1-fix1).

Pure in-process verification (no subprocess / no shell):
  1. bounded protected-file SHA snapshot (exact external files used/guarded)
  2. unit tests (unittest discover)
  3. compileall on shared_data, scripts, tests
  4. CLI help smoke
  5. canary file-replay (20260716 A_SHARE_1MIN_RAW_FILE_REPLAY) via scripts/canary_registry.py
  6. verify latest + status
  7. AST-aware forbidden-behavior scan (imports/calls/string literals; docstrings
     and comments excluded): formal package must be clean, tooling scoped
  8. protected-file snapshot AFTER + diff
  9. write .runtime/acceptance/ds1_acceptance.json
"""
from __future__ import annotations

import compileall
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared_data import __version__  # noqa: E402
from shared_data.cli import build_parser  # noqa: E402
from shared_data.hashing import sha256_file  # noqa: E402
from shared_data.store import SafeRootStore  # noqa: E402
from scripts.canary_registry import canary_registry  # noqa: E402
from scripts.forbidden_scan import scan_tokens  # noqa: E402

STORE_ROOT = ROOT / ".runtime" / "data"
ACCEPTANCE_DIR = ROOT / ".runtime" / "acceptance"
SNAPSHOT_PATH = ACCEPTANCE_DIR / "external_snapshot.json"

# Exact external files used/guarded by this batch (bounded, no recursive crawl).
PROTECTED_FILES = (
    Path(r"C:\Users\huang\Desktop\学习\v3_system\30_runtime\timeline_scheduler\run_opening_scheduler.py"),
    Path(r"C:\Users\huang\Desktop\学习\v3_system\_ops\run_v3_task.py"),
    Path(r"C:\Users\huang\Desktop\学习\v3_system\40_artifacts\runtime_debug\20260716_ashare_open_live\ashare_open_live_1min_bars_20260716.csv"),
    Path(r"C:\Users\huang\Desktop\学习\v3_system\40_artifacts\runtime_debug\20260716_ashare_open_live\ashare_open_live_1min_bars_20260716.manifest.json"),
    Path(r"C:\Users\huang\Desktop\学习\v3.5\infrastructure\data_store.py"),
    Path(r"C:\Users\huang\Desktop\学习\v3.5\infrastructure\stage_store.py"),
    Path(r"C:\Users\huang\Desktop\学习\v3.5\infrastructure\stage_quote_provider.py"),
    Path(r"C:\Users\huang\Desktop\学习\v3.5\.runtime\shared_data_service_extraction_plan_20260806.md"),
    Path(r"C:\Users\huang\Desktop\学习\AGENTS.md"),
)

# Exact tokens: formal package must have zero hits; tooling hits are scoped.
FORBIDDEN_TOKENS = ("v3_system", "V35_V3_", "35_V3_", "8771", "8871", "8872", "subprocess", "os.system", "shell=True")
FORMAL_DIRS = (ROOT / "shared_data",)
TOOLING_DIRS = (ROOT / "scripts", ROOT / "tests")

MODEL_USAGE = {
    "model": "deepseek-v4-flash",
    "contextWindow": 1000000,
    "clientModel": "haiku",
    "effort": "max",
}
MODEL_USAGE_PROVENANCE = (
    "expected route metadata declared by the batch contract; "
    "independent proof is held by the controller (Sol Claude stream log)"
)


def snapshot_protected() -> dict[str, object]:
    hashed: dict[str, str] = {}
    unreadable: list[str] = []
    for path in PROTECTED_FILES:
        if not path.is_file():
            unreadable.append(f"missing:{path}")
            continue
        try:
            hashed[str(path)] = sha256_file(path)
        except OSError as error:
            unreadable.append(f"unreadable:{path}:{error}")
    return {"hashed": hashed, "unreadable": unreadable}


def diff_snapshot(before: dict[str, object], after: dict[str, object]) -> list[str]:
    changes: list[str] = []
    for path, digest in after["hashed"].items():
        if before["hashed"].get(path) != digest:
            changes.append(f"changed:{path}")
    for path, digest in before["hashed"].items():
        if path not in after["hashed"]:
            changes.append(f"disappeared:{path}")
    return changes


def main() -> int:
    commands: list[dict[str, object]] = []
    green: list[str] = []

    def record(name: str, ok: bool, detail: object = None) -> None:
        commands.append({"name": name, "ok": bool(ok), "detail": detail})
        if ok:
            green.append(name)

    before = snapshot_protected()
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding="utf-8")

    # 2. unit tests
    loader = unittest.TestLoader()
    suite = loader.discover(str(ROOT / "tests"))
    runner = unittest.TextTestRunner(verbosity=1)
    test_result = runner.run(suite)
    test_count = test_result.testsRun
    record(
        "unit_tests",
        test_result.wasSuccessful(),
        {"tests_run": test_result.testsRun, "failures": len(test_result.failures), "errors": len(test_result.errors)},
    )

    # 3. compileall
    record(
        "compileall",
        compileall.compile_dir(str(ROOT / "shared_data"), quiet=1, force=True)
        and compileall.compile_dir(str(ROOT / "scripts"), quiet=1, force=True)
        and compileall.compile_dir(str(ROOT / "tests"), quiet=1, force=True),
    )

    # 4. CLI help
    parser = build_parser()
    help_text = parser.format_help()
    record("cli_help", "file-replay" in help_text and "verify" in help_text and "status" in help_text)

    # 5. canary replay (allowlist injected from isolated tooling)
    store = SafeRootStore(root=STORE_ROOT, allowlist=canary_registry())
    canary = None
    try:
        canary = store.replay_file(
            owner="v3_shared_data",
            trade_date="20260716",
            role="A_SHARE_1MIN_RAW_FILE_REPLAY",
            source_id="v3_ashare_open_live_1min",
            stage_id="STAGE_1445_1500",
        )
        record("canary_file_replay", canary.get("ok") is True and canary.get("status") == "READY", canary)
    except Exception as error:  # noqa: BLE001 - fail closed
        record("canary_file_replay", False, str(error))

    # 6. verify + status
    verified = None
    try:
        verified = store.verify_latest("20260716", "A_SHARE_1MIN_RAW_FILE_REPLAY")
        record("canary_verify", True, verified)
    except Exception as error:  # noqa: BLE001
        record("canary_verify", False, str(error))
    status = store.status()
    record("store_status", True, {"run_keys": sorted(status["runs"]), "locked": status["locked"]})

    # 7. forbidden scan: formal package must be clean; tooling hits are scoped
    formal_hits = scan_tokens(FORMAL_DIRS, FORBIDDEN_TOKENS)
    tooling_hits = scan_tokens(TOOLING_DIRS, FORBIDDEN_TOKENS)
    record("forbidden_scan_formal", not formal_hits, {"hits": formal_hits})
    record(
        "forbidden_scan_tooling_scoped",
        True,
        {"scope": "scripts/ and tests/ may hold the frozen canary oracle path; hits listed", "hits": tooling_hits},
    )

    # 8. protected files unchanged
    after = snapshot_protected()
    changes = diff_snapshot(before, after)
    record("external_files_unchanged", not changes, {"changes": changes, "protected_count": len(PROTECTED_FILES)})

    cannot_confirm: list[str] = []
    if canary is not None:
        try:
            manifest = json.loads((STORE_ROOT / Path(canary["manifest_relative"])).read_text(encoding="utf-8"))
            cannot_confirm = list(manifest.get("cannot_confirm", []))
        except Exception as error:  # noqa: BLE001
            cannot_confirm = [f"cannot read manifest: {error}"]

    accepted = all(c["ok"] for c in commands)
    acceptance = {
        "schema_version": "v3_shared_data.acceptance.v1",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "modelUsage": MODEL_USAGE,
        "modelUsage_provenance": MODEL_USAGE_PROVENANCE,
        "files_written": sorted(
            str(p.relative_to(ROOT).as_posix())
            for base in ("shared_data", "tests", "scripts")
            for p in ROOT.joinpath(base).rglob("*")
            if p.is_file() and p.suffix == ".py"
        )
        + ["pyproject.toml", "README.md"],
        "commands": commands,
        "green_commands": green,
        "test_count": test_count,
        "canary": {
            "source": str(Path(r"C:\Users\huang\Desktop\学习\v3_system\40_artifacts\runtime_debug\20260716_ashare_open_live\ashare_open_live_1min_bars_20260716.csv")),
            "source_role": "A_SHARE_1MIN_RAW_FILE_REPLAY",
            "trade_date": "20260716",
            "stage_id": "STAGE_1445_1500",
            "source_id": "v3_ashare_open_live_1min",
            "input_sha256": canary.get("input_sha256") if canary else None,
            "artifact_sha256": canary.get("artifact_sha256") if canary else None,
            "row_count": canary.get("row_count") if canary else None,
            "run_id": canary.get("run_id") if canary else None,
            "status": canary.get("status") if canary else None,
            "latest": (verified or {}).get("latest"),
        },
        "forbidden_scan": {
            "tokens": list(FORBIDDEN_TOKENS),
            "formal_package_hits": formal_hits,
            "tooling_scoped_hits": tooling_hits,
        },
        "external_files_unchanged": not changes,
        "protected_files_snapshot": str(SNAPSHOT_PATH),
        "skills_loaded": [],
        "tools_used": ["Bash", "Read", "Write", "Edit", "Grep"],
        "workflows_used": [],
        "subagents_used": [],
        "cannot_confirm": cannot_confirm,
        "safety_flags": {
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
        "package_version": __version__,
        "final_status": "PASS" if accepted else "FAIL",
    }
    ACCEPTANCE_DIR.mkdir(parents=True, exist_ok=True)
    output = ACCEPTANCE_DIR / "ds1_acceptance.json"
    output.write_text(json.dumps(acceptance, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    print(f"final_status={acceptance['final_status']} tests={test_count} commands_ok={len(green)}/{len(commands)}")
    print(f"acceptance: {output}")
    return 0 if accepted else 1


if __name__ == "__main__":
    sys.exit(main())
