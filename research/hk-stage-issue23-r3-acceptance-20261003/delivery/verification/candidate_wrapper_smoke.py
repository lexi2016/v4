"""Candidate-own-root, no-I/O wrapper smoke. Does not run a market stage."""
from __future__ import annotations
import argparse
import hashlib
import importlib
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

EXPECTED = {
    "stage_center.runner": "2dbfa90c42cb4bd3b9b78d20bfbd1ac15eba0f3a18dd1105b32decd04a2b5232",
    "stage_center._runner_parts.slot_execution": "278085fb1effdc9dcf5c5dc9626d68faea0bc53c44f66be4eb89f9a0415fc07a",
    "stage_center._runner_parts.tick_planning": "c27cb9717ec2940364d1e1186529e6df1b37b07aae0c56f65334f6f9bf06dd15",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.app_root.expanduser().resolve(strict=True)
    if any(name == "stage_center" or name.startswith("stage_center.") for name in sys.modules):
        raise RuntimeError("Use a fresh process; Stage modules are already imported")
    for name, expected in EXPECTED.items():
        path = root / (name.replace(".", "/") + ".py")
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
            raise RuntimeError(f"Candidate source is not inside its own root: {path}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Candidate source SHA mismatch: {path}")
    sys.path[:0] = [str(root / "upstreams"), str(root)]
    modules, identities = {}, {}
    for name, expected in EXPECTED.items():
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve(strict=True)
        if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Imported wrong module identity: {name} -> {path}")
        modules[name] = module
        identities[name] = {"path": str(path), "sha256": expected}
    runner = modules["stage_center.runner"]
    date, stage, now = "20261002", "STAGE_0930_0935", datetime(2026, 10, 2, 9, 35)
    def forbidden(*args, **kwargs):
        raise AssertionError("No input/collection/receipt/publication permitted")
    class Probe:
        _execution_scope = None
        _write_receipt = _backfill_runner = forbidden
        def __init__(self):
            self.calls = []
        def _prepare_hk_active_snapshots(self, *args, **kwargs):
            self.calls.append("prepare")
            return []
        def due_decisions(self, *args, **kwargs):
            self.calls.append("due")
            return ()
    def call(entry, probe, kwargs):
        if entry == "_run_one":
            decision = SimpleNamespace(trade_date=date, stage_id=stage, status="DUE")
            return runner.StageCenterRunner._run_one(probe, decision, **kwargs)
        return runner.StageCenterRunner.tick(probe, date, now, **kwargs)
    old_markets, old_read = runner._stage_markets_for_date, runner.read_candidate_input
    cases = []
    try:
        # In-memory test boundary only; no files, calendars or live inputs change.
        runner._stage_markets_for_date = lambda *_: ()
        runner.read_candidate_input = forbidden
        for entry in ("_run_one", "tick"):
            for explicit_none in (False, True):
                probe = Probe()
                kwargs = {"historical_markets": None} if explicit_none else {}
                if entry == "_run_one":
                    try:
                        call(entry, probe, kwargs)
                    except runner.RunnerError as error:
                        if str(error) != "no securities market is open for this stage date":
                            raise
                    else:
                        raise AssertionError("R1 slot guard not reached")
                else:
                    result = call(entry, probe, kwargs)
                    assert result == {"status": "CANNOT_CONFIRM", "trade_date": date,
                                      "stages": [], "pre_captures": [], **runner.SAFETY_FLAGS}
                    assert probe.calls == ["prepare", "due"]
                cases.append({"entry": entry, "explicit_none": explicit_none, "status": "PASS"})
            for markets in (("HK_CONNECT",), (), []):
                probe = Probe()
                try:
                    call(entry, probe, {"historical_backfill": True, "historical_markets": markets})
                except TypeError as error:
                    if "unexpected keyword argument 'historical_markets'" not in str(error):
                        raise
                else:
                    raise AssertionError("Explicit history request was dropped")
                assert probe.calls == []
                cases.append({"entry": entry, "explicit_markets": markets,
                              "status": "PASS_EXPECTED_PRE_BODY_REJECTION"})
    finally:
        runner._stage_markets_for_date, runner.read_candidate_input = old_markets, old_read
    print(json.dumps({"status": "PASS_WRAPPER_COMPATIBILITY_ONLY", "python": sys.executable,
                      "python_version": sys.version, "app_root": str(root), "modules": identities,
                      "cases": cases, "collection_or_selection_called": False,
                      "data_write_performed": False, "NATURAL_VERIFIED": "NATURAL_SLOT_UNVERIFIED"},
                     ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
