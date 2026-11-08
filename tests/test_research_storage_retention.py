"""Lifecycle tests use tiny derived artifacts, never active research data."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import shutil
import types
import sys

import pytest

from ops import research_storage_retention as storage


def write(path, value):
    storage.atomic_json(path, value)
    return dict(path=str(path), sha256=storage.digest(path))


@pytest.fixture
def fixture(tmp_path):
    data, runs, quarantine = tmp_path / "data", tmp_path / "runs", tmp_path / "Desktop/待删除文件夹/V4_lifecycle"
    for path in (data, runs, quarantine):
        path.mkdir(parents=True)
    formal = {role: data / role for role in storage.ROLES}
    for root in formal.values():
        root.mkdir()
    entries = []
    baseline = {role: "0" * 64 for role in storage.ROLES}
    for index in range(5):
        run = runs / ("qfq_" + str(index) * 20)
        run.mkdir()
        candidates, hashes = {}, {}
        for role, root in formal.items():
            path = root / f"generation_{index}" / ("panel" if role == "backtest" else "") / f"{role}.parquet"
            path.parent.mkdir(parents=True)
            path.write_bytes(f"panel-{index}-{role}".encode())
            candidates[role], hashes[role] = str(path), storage.digest(path)
        status = dict(status="READY", run_dir=str(run), generation_id=str(index) * 64,
                      target_date=20261100 + index, candidates=candidates, candidate_sha256=hashes,
                      baseline_panel_sha256=baseline, selector_pointer_ready=True,
                      backtest_pointer_ready=True, **storage.FLAGS)
        write(run / "stage_status.json", status)
        write(run / "candidate_receipt.json", {**status, "status": "CANDIDATE_READY"})
        checks = run / "symbol_checkpoints"
        checks.mkdir()
        checkpoint = checks / "000001.SZ.parquet"
        checkpoint.write_bytes(f"checkpoint-{index}".encode())
        write(checks / "000001.SZ.receipt.json", dict(sha256=storage.digest(checkpoint)))
        if index:
            for role in storage.ROLES:
                spool = run / f"current_{role}_buckets"
                spool.mkdir()
                bucket = spool / "bucket_00.parquet"
                bucket.write_bytes(f"bucket-{index}-{role}".encode())
                write(spool / "receipt.json", dict(source_sha256=baseline[role], row_copy="ARROW_V1",
                    files={"0": dict(path=str(bucket), sha256=storage.digest(bucket))}))
        entries.append((run, status))
        baseline = hashes
    pointers = {}
    for role in storage.ROLES:
        path = data / f"CURRENT_{role}.txt"
        path.write_text(entries[-1][1]["candidates"][role] + "\n")
        pointers[role] = str(path)
    binding=write(tmp_path / "consumers.json", {})
    inventory_ref=write(tmp_path / "managed-pin-inventory.json",dict(schema="v4_research_managed_pin_inventory_v1",
        status="COMPLETE_REVIEWED",consumer_scopes={key:"REVIEWED_NO_MANAGED_PINS" for key in storage.CONSUMER_SCOPES},
        expected_main_app_root=str(Path(storage.__file__).resolve().parents[1]),pins=[],source_bindings=[binding]))
    policy = dict(schema=storage.SCHEMA, keep_completed=2, data_root=str(data), run_root=str(runs),
                  formal_roots={key: str(value) for key, value in formal.items()}, pointers=pointers,
                  quarantine_root=str(quarantine), managed_pin_inventory=inventory_ref,
                  max_managed_bytes=10**9, max_quarantine_bytes=10**8,
                  reserve_bytes=1, minimum_build_bytes=10)
    policy_path = tmp_path / "policy.json"
    write(policy_path, policy)
    return types.SimpleNamespace(policy=policy, policy_path=policy_path, entries=entries,
                                 tmp=tmp_path, data=data, runs=runs, quarantine=quarantine)


def add_managed_pin(f,path):
    inventory_path=Path(f.policy["managed_pin_inventory"]["path"])
    value=json.loads(inventory_path.read_text())
    value["pins"].append(dict(kind="managed_path",path=str(path)))
    f.policy["managed_pin_inventory"]=write(inventory_path,value)
    write(f.policy_path,f.policy)


def recovery_ref(f,run):
    snapshot=write(f.tmp/"recovery-snapshot.json",{})
    core=write(f.tmp/"recovery-core.json",{})
    return write(f.tmp/"recovery.json",dict(schema="qfq_original_checkpoint_recovery_v1",source_run=str(run),
        original_snapshot=snapshot,source_core=core,source_identity={},retry_original_quarantined=[],
        chunks={"000001.SZ":dict(artifact=dict(path=str(run/"symbol_checkpoints/000001.SZ.parquet"),sha256=storage.digest(run/"symbol_checkpoints/000001.SZ.parquet")),
            receipt=dict(path=str(run/"symbol_checkpoints/000001.SZ.receipt.json"),sha256=storage.digest(run/"symbol_checkpoints/000001.SZ.receipt.json")))}))


def actions(proposal):
    return {Path(item["source"]) for item in proposal["actions"]}


def test_current_rollback_and_small_audit_receipts_survive(fixture):
    f = fixture
    policy = storage.load_policy(f.policy_path)
    proposal = storage.plan(policy)
    for run, status in f.entries[-2:]:
        assert not any(storage.under(path, run) for path in actions(proposal))
        assert not any(Path(value).is_relative_to(path) for path in actions(proposal)
                       for value in status["candidates"].values())
    assert f.entries[0][0] / "symbol_checkpoints" in actions(proposal)
    outcome = storage.apply(policy, proposal)
    assert outcome["freed_bytes"] == 0
    assert outcome["status"] == "DRY_RUN_NO_DATA_MUTATION"
    assert all((run / "stage_status.json").exists() and (run / "candidate_receipt.json").exists()
               for run, _ in f.entries)
    assert storage.apply(policy, proposal) == outcome


def test_recursive_consumer_and_recovery_pins_protect_old_checkpoint(fixture):
    f = fixture
    old = f.entries[0][0] / "symbol_checkpoints" / "000001.SZ.parquet"
    nested = recovery_ref(f,f.entries[0][0])
    add_managed_pin(f,old)
    proposal = storage.plan(f.policy)
    assert old.parent not in actions(proposal)
    run, status = f.entries[1]
    status["checkpoint_recovery"] = nested
    write(run / "stage_status.json", status)
    assert old.parent not in actions(storage.plan(f.policy))


@pytest.mark.parametrize("state", ["FAILED", "RUNNING", "CANDIDATE_READY"])
def test_failed_pending_and_their_transitive_refs_preserved(fixture, state):
    f = fixture
    run, status = f.entries[1]
    checkpoint = f.entries[0][0] / "symbol_checkpoints" / "000001.SZ.parquet"
    status.update(status=state, checkpoint_recovery=recovery_ref(f,f.entries[0][0]))
    write(run / "stage_status.json", status)
    proposal = storage.plan(f.policy)
    assert checkpoint.parent not in actions(proposal)
    assert not any(storage.under(path, run) for path in actions(proposal))


def test_source_hash_conflict_preserves_whole_run(fixture):
    f = fixture
    source = Path(f.entries[0][1]["candidates"]["selector"])
    source.write_bytes(b"changed-live-bytes")
    proposal = storage.plan(f.policy)
    run = f.entries[1][0]
    assert not any(storage.under(path, run) for path in actions(proposal))
    assert any(item["path"] == str(run) and "HASH_DRIFT" in item["reason"]
               for item in proposal["preserved_unknown"])


@pytest.mark.parametrize("change", ["pointer", "receipt", "new_run", "pin"])
def test_apply_rechecks_pointer_receipt_inventory_and_pins(fixture, change):
    f = fixture
    proposal = storage.plan(f.policy)
    if change == "pointer":
        Path(f.policy["pointers"]["selector"]).write_text(f.entries[-2][1]["candidates"]["selector"])
    elif change == "receipt":
        write(f.entries[0][0] / "stage_status.json", {"status": "FAILED"})
    elif change == "new_run":
        (f.runs / ("qfq_" + "f" * 20)).mkdir()
    else:
        write(f.tmp/"consumers.json", {"changed": True})
    with pytest.raises(storage.RetentionError):
        storage.apply(f.policy, proposal)
    assert not list(f.quarantine.iterdir())


def test_dry_run_never_enters_rename_transaction(fixture, monkeypatch):
    f = fixture
    proposal = storage.plan(f.policy)
    def forbidden(*args, **kwargs):
        pytest.fail("dry-run must never rename ordinary data")
    monkeypatch.setattr(storage.os, "rename", forbidden)
    assert storage.apply(f.policy, proposal)["status"] == "DRY_RUN_NO_DATA_MUTATION"
    assert not list(f.quarantine.iterdir())
    assert all(Path(row["source"]).exists() for row in proposal["actions"])


def test_symlink_alias_path_escape_and_collision(fixture):
    f = fixture
    proposal = storage.plan(f.policy)
    destination = f.quarantine / proposal["plan_id"]
    destination.mkdir()
    assert storage.apply(f.policy, proposal)["moved_bytes"] == 0
    destination.rmdir()
    checkpoint = f.entries[0][0] / "symbol_checkpoints" / "000001.SZ.parquet"
    alias = f.tmp / "alias"
    storage.os.link(checkpoint, alias)
    assert checkpoint.parent not in actions(storage.plan(f.policy))
    alias.unlink()
    checkpoint.unlink()
    checkpoint.symlink_to(f.entries[1][0] / "symbol_checkpoints" / "000001.SZ.parquet")
    assert checkpoint.parent not in actions(storage.plan(f.policy))
    with pytest.raises(storage.RetentionError, match="UNSAFE_PATH"):
        storage.safe_path(f.tmp / ".." / "escape")


def test_quarantine_limit_and_absolute_growth_guard(fixture, monkeypatch):
    f = fixture
    f.policy["max_quarantine_bytes"] = 1
    proposal = storage.plan(f.policy)
    assert storage.apply(f.policy, proposal)["moved_bytes"] == 0
    assert storage.growth_guard(f.policy, already_current=True)["status"].startswith("REUSE")
    monkeypatch.setattr(storage.shutil, "disk_usage", lambda _: types.SimpleNamespace(free=1000))
    f.policy["max_quarantine_bytes"] = 10**8
    f.policy["reserve_bytes"] = 10
    assert storage.growth_guard(f.policy, already_current=False)["predicted_bytes"] < 1000
    f.policy["reserve_bytes"] = 999
    with pytest.raises(storage.RetentionError, match="SPACE_BUDGET"):
        storage.growth_guard(f.policy, already_current=False)
    f.policy["reserve_bytes"] = 1
    f.policy["max_managed_bytes"] = 1
    with pytest.raises(storage.RetentionError, match="MANAGED_BUDGET"):
        storage.growth_guard(f.policy, already_current=False)


def test_cross_day_budget_counts_quarantine_no_rehash_of_protected_history(fixture, monkeypatch):
    f = fixture
    proposal = storage.plan(f.policy)
    storage.apply(f.policy, proposal)
    moved = storage.logical_bytes(f.quarantine)
    assert moved == 0
    moved = proposal["move_bytes"]
    f.policy["max_managed_bytes"] = moved
    with pytest.raises(storage.RetentionError, match="MANAGED_BUDGET"):
        storage.growth_guard(f.policy, already_current=False)
    original = storage.digest
    def no_current_payload_read(path):
        assert str(path) not in f.entries[-1][1]["candidates"].values()
        return original(path)
    monkeypatch.setattr(storage, "digest", no_current_payload_read)
    storage.plan(f.policy)


def test_postcommit_only_and_failures_do_not_relabel_committed_pair(fixture, monkeypatch):
    f = fixture
    write(f.policy_path, f.policy)
    monkeypatch.setenv("V4_RESEARCH_RETENTION_POLICY", str(f.policy_path))
    monkeypatch.setenv("V4_RESEARCH_RETENTION_POLICY_SHA256", storage.digest(f.policy_path))
    calls = []
    def rebuild(**kwargs):
        calls.append("committed")
        return {"status": "READY", "already_current": True}
    original = storage.plan
    def after_commit(policy, **_):
        assert calls == ["committed"]
        raise storage.RetentionError("unknown consumer")
    monkeypatch.setattr(storage, "plan", after_commit)
    result = storage.run_with_retention(rebuild, data_root=f.data, return_root=f.runs,
        pointers={key: Path(value) for key, value in f.policy["pointers"].items()}, target=20261104,
        ready_check=lambda: True)
    assert result["status"] == "READY"
    assert result["storage_retention"]["outcome"]["status"] == "PRESERVED_UNKNOWN"
    monkeypatch.setattr(storage, "plan", original)
    before = set(f.quarantine.iterdir())
    with pytest.raises(RuntimeError, match="compute failed"):
        storage.run_with_retention(lambda **_: (_ for _ in ()).throw(RuntimeError("compute failed")),
            data_root=f.data, return_root=f.runs,
            pointers={key: Path(value) for key, value in f.policy["pointers"].items()}, target=20261104,
            ready_check=lambda: True)
    assert set(f.quarantine.iterdir()) == before


def test_caller_hook_keeps_qfq_owner_bytes_and_formula_untouched():
    root = Path(__file__).resolve().parents[1]
    assert storage.digest(root / "ops/research_panel_qfq.py") == "05e8aa7aa19c1ae998481360d80fb99a39498ffd31c5945caedd5c791daa1fad"
    source = root / "ops/macos_research_panel_daily_authority.py"
    tree = ast.parse(source.read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run_windows_a_formula_authority")
    assert any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "run_with_retention" for node in ast.walk(function))


def test_explicit_relocation_uses_receipt_sha_and_protects_pin(fixture):
    f = fixture
    original = Path(f.entries[0][1]["candidates"]["selector"])
    archived = f.data / "legacy-archive" / "selector_generation_0" / original.name
    archived.parent.mkdir(parents=True)
    shutil.move(original, archived)
    manifest = write(f.tmp / "old-move-manifest.json", dict(moved=[str(original)]))
    f.policy["formal_relocations"] = [dict(original_path=str(original), archived_path=str(archived), manifest=manifest)]
    write(f.policy_path, f.policy)
    storage.load_policy(f.policy_path)
    add_managed_pin(f,original)
    proposal = storage.plan(f.policy)
    assert not any(storage.under(archived, path) for path in actions(proposal))
    archived.write_bytes(b"source-drift")
    proposal = storage.plan(f.policy)
    assert not any(storage.under(path, f.entries[1][0]) for path in actions(proposal))


def enable_future(f):
    f.policy.update(future_reclamation=True, activation_id="test-activation-v1")
    f.policy["activation"] = write(f.tmp / "activation.json", dict(
        schema="v4_research_storage_activation_v1", activation_id=f.policy["activation_id"],
        authority="FUTURE_CREATED_SUCCESSFUL_UNPINNED_DERIVED_ONLY"))
    write(f.policy_path, f.policy)
    storage.load_policy(f.policy_path)


def append_future_generation(f, index, *, successful=True):
    reservation = storage.begin_creation(f.policy)
    previous = f.entries[-1][1]
    run = f.runs / ("qfq_" + str(index) * 20)
    run.mkdir()
    candidates, hashes = {}, {}
    for role, root in f.policy["formal_roots"].items():
        path = Path(root) / f"generation_{index}" / ("panel" if role == "backtest" else "") / f"{role}.parquet"
        path.parent.mkdir(parents=True)
        path.write_bytes(f"future-panel-{index}-{role}".encode())
        candidates[role], hashes[role] = str(path), storage.digest(path)
    for name in ("symbol_checkpoints", "current_selector_buckets", "current_backtest_buckets"):
        directory = run / name
        directory.mkdir()
        if name == "symbol_checkpoints":
            path = directory / "000001.SZ.parquet"
            path.write_bytes(f"future-checkpoint-{index}".encode())
            write(path.with_suffix(".receipt.json"), dict(sha256=storage.digest(path)))
        else:
            role = name.removeprefix("current_").removesuffix("_buckets")
            path = directory / "bucket_00.parquet"
            path.write_bytes(f"future-bucket-{index}-{role}".encode())
            write(directory / "receipt.json", dict(source_sha256=previous["candidate_sha256"][role], row_copy="ARROW_V1",
                files={"0": dict(path=str(path), sha256=storage.digest(path))}))
    status = dict(status="READY" if successful else "FAILED", run_dir=str(run), generation_id=str(index) * 64,
        target_date=20261100 + index, candidates=candidates, candidate_sha256=hashes,
        baseline_panel_sha256=previous["candidate_sha256"], selector_pointer_ready=True,
        backtest_pointer_ready=True, **storage.FLAGS)
    write(run / "stage_status.json", status)
    write(run / "candidate_receipt.json", {**status, "status": "CANDIDATE_READY"})
    if successful:
        for role, value in candidates.items():
            Path(f.policy["pointers"][role]).write_text(value + "\n")
    storage.register_creation(f.policy, reservation, status)
    if successful:
        f.entries.append((run, status))
    return run, status


def test_only_registered_future_obsolete_artifacts_can_be_reclaimed(fixture):
    f = fixture
    enable_future(f)
    # Existing dirs cannot acquire ownership from a later READY receipt/mtime.
    reservation = storage.begin_creation(f.policy)
    with pytest.raises(storage.RetentionError, match="NOT_PROVEN_NEW"):
        storage.register_creation(f.policy, reservation, f.entries[-1][1])
    future, _ = append_future_generation(f, 5)
    append_future_generation(f, 6)
    append_future_generation(f, 7)
    proposal = storage.plan(f.policy)
    assert all(action["disposition"] == ("RECLAIM_FUTURE" if Path(action["source"]).name.startswith("current_")
        else "QUARANTINE_FUTURE_UNPROVEN") for action in proposal["actions"] if action["run"] == str(future))
    assert all(action["disposition"] == "QUARANTINE_EXISTING" for action in proposal["actions"]
               if Path(action["run"]) in {item[0] for item in f.entries[:5]})
    outcome = storage.apply(f.policy, proposal)
    assert outcome["reclaimed_logical_bytes"] == 0
    assert outcome["freed_bytes"] == 0
    assert all(Path(row["source"]).exists() for row in proposal["actions"])
    assert not list(f.quarantine.iterdir())
    assert storage.apply(f.policy, proposal) == outcome


def test_future_failed_or_reused_current_never_registered(fixture):
    f = fixture
    enable_future(f)
    failed, _ = append_future_generation(f, 5, successful=False)
    assert not (storage._ownership_root(f.policy) / "completed" / (failed.name + ".json")).exists()
    current = {**f.entries[-1][1], "already_current": True}
    storage.register_creation(f.policy, storage.begin_creation(f.policy), current)
    assert not (storage._ownership_root(f.policy) / "completed" / (f.entries[-1][0].name + ".json")).exists()
    assert not any(storage.under(path, failed) for path in actions(storage.plan(f.policy)))


def test_legacy_future_flag_cannot_bypass_dryrun_or_reader_blocker(fixture, monkeypatch):
    f = fixture
    enable_future(f)
    append_future_generation(f, 5)
    append_future_generation(f, 6)
    append_future_generation(f, 7)
    proposal = storage.plan(f.policy)
    def forbidden(*args, **kwargs):
        pytest.fail("legacy future_reclamation must not bypass no-delete defaults")
    monkeypatch.setattr(Path, "unlink", forbidden)
    assert storage.apply(f.policy, proposal)["reclaimed_logical_bytes"] == 0
    assert all(Path(row["source"]).exists() for row in proposal["actions"])
    f.policy.update(auto_gc_enabled=True, dry_run=False)
    proposal=storage.plan(f.policy)
    with pytest.raises(storage.RetentionError,match="UNREGISTERED_READER"):
        storage.apply(f.policy,proposal)


def test_future_pin_and_owner_lock_block_reclamation(fixture):
    f = fixture
    enable_future(f)
    future, _ = append_future_generation(f, 5)
    append_future_generation(f, 6)
    append_future_generation(f, 7)
    # New consumer pin invalidates ownership policy SHA, conservatively retaining
    # future ownership until explicitly migrated; graph pin still protects it.
    add_managed_pin(f,future)
    proposal = storage.plan(f.policy)
    assert not any(storage.under(path, future) for path in actions(proposal))
    with storage.owner_lock(f.policy):
        with pytest.raises(storage.RetentionError, match="OWNER_ALREADY_ACTIVE"):
            with storage.owner_lock(f.policy):
                pytest.fail("overlapping ownership")




def test_unknown_oversized_metadata_blocks_instead_of_dropping_dependencies(fixture, monkeypatch):
    f = fixture
    original = storage.stamp
    pin = Path(f.policy["managed_pin_inventory"]["path"])
    def oversized(path):
        info = original(path)
        return {**info, "size": 800 * 1024**2} if path == pin else info
    monkeypatch.setattr(storage, "stamp", oversized)
    with pytest.raises(storage.RetentionError, match="METADATA_BUDGET"):
        storage.plan(f.policy)
    assert not list(f.quarantine.iterdir())


def test_unchanged_source_conflict_hash_is_reused_but_ctime_drift_rechecked(fixture, monkeypatch):
    f = fixture
    path = Path(f.entries[0][1]["candidates"]["selector"])
    path.write_bytes(b"conflicting source")
    first = storage.plan(f.policy)
    write(f.runs / "storage_retention_source_verifications.json", dict(schema=storage.SCHEMA,
        policy_sha256=storage.canonical(f.policy), sources=first["source_verifications"]))
    digest = storage.digest
    def do_not_rehash(value):
        assert value != path
        return digest(value)
    monkeypatch.setattr(storage, "digest", do_not_rehash)
    storage.plan(f.policy)
    monkeypatch.setattr(storage, "digest", digest)
    path.write_bytes(b"changed source again")
    changed = storage.plan(f.policy)
    assert first["source_verifications"][str(path)] != changed["source_verifications"][str(path)]


def test_policy_binding_is_required_when_configured(fixture, monkeypatch):
    f = fixture
    monkeypatch.setenv("V4_RESEARCH_RETENTION_POLICY", str(f.policy_path))
    monkeypatch.delenv("V4_RESEARCH_RETENTION_POLICY_SHA256", raising=False)
    with pytest.raises(storage.RetentionError, match="PATH_AND_SHA"):
        storage.run_with_retention(lambda **_: pytest.fail("must not run"),
            data_root=f.data, return_root=f.runs, pointers={}, target=20261104, ready_check=lambda: True)
    with pytest.raises(storage.RetentionError, match="HASH_BINDING"):
        storage.load_policy(f.policy_path, expected_sha256="0" * 64)


def test_actual_caller_codeobject_rebinding_preserves_local_hook(fixture, monkeypatch):
    f = fixture
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "ops/macos_research_panel_daily_authority.py").read_text())
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "run_windows_a_formula_authority")
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
    ast.fix_missing_locations(module)
    seen = []
    selector = Path(f.entries[-1][1]["candidates"]["selector"])
    backtest = Path(f.entries[-1][1]["candidates"]["backtest"])
    def rebuild(**kwargs):
        seen.append(kwargs)
        return dict(status="READY", selector=str(selector), backtest=str(backtest), authority={})
    fake_qfq = types.ModuleType("ops.research_panel_qfq")
    fake_qfq.run_daily_rebuild = rebuild
    fake_qfq.input_path = lambda _: f.tmp / "snapshot.json"
    fake_qfq.pointer_ready = lambda *_: True
    monkeypatch.setitem(sys.modules, "ops.research_panel_qfq", fake_qfq)
    monkeypatch.delenv("V4_RESEARCH_RETENTION_POLICY", raising=False)
    monkeypatch.delenv("V4_RESEARCH_RETENTION_POLICY_SHA256", raising=False)
    namespace = dict(Path=Path, __file__=str(root / "ops/macos_research_panel_daily.py"),
        _date=lambda value: value, _ensure_pointer_seed=lambda *_: None,
        _formula_artifact_binding=lambda *_: {})
    exec(compile(module, "caller_hook_test", "exec"), namespace)
    original = namespace["run_windows_a_formula_authority"]
    rebound = types.FunctionType(original.__code__, namespace, argdefs=original.__defaults__)
    rebound.__kwdefaults__ = original.__kwdefaults__
    output = rebound("legacy.py", tdx_root=f.tmp, data_root=f.data,
        selector_pointer=f.policy["pointers"]["selector"], backtest_pointer=f.policy["pointers"]["backtest"],
        selector_seed=None, backtest_seed=None, contract_csv=f.tmp / "fields.csv",
        canonical_formula_path=f.tmp / "formula.py", return_root=f.runs, target_date="20261104")
    assert output["status"] == "READY" and len(seen) == 1
    assert seen[0]["refresh_inputs"] is True and seen[0]["publish"] is True
    assert seen[0]["pointers"] == {key: Path(value) for key, value in f.policy["pointers"].items()}


def test_future_ready_spools_expire_immediately_but_current_labels_stay(fixture):
    f = fixture
    enable_future(f)
    future, status = append_future_generation(f, 5)
    proposal = storage.plan(f.policy)
    selected = [action for action in proposal["actions"] if action["run"] == str(future)]
    assert {Path(action["source"]).name for action in selected} == {"current_selector_buckets", "current_backtest_buckets"}
    assert all(action["disposition"] == "RECLAIM_FUTURE" for action in selected)
    storage.apply(f.policy, proposal)
    assert all(Path(value).exists() for value in status["candidates"].values())
    assert (future / "symbol_checkpoints/000001.SZ.parquet").exists()
    # Previous existing generation is rollback and must not be retroactively
    # classified as future temp just because it is now an older date.
    assert (f.entries[-2][0] / "current_selector_buckets/bucket_00.parquet").exists()


def test_explicit_consumer_of_current_future_spool_prevents_immediate_disposal(fixture):
    f = fixture
    future = f.runs / ("qfq_" + "5" * 20)
    bucket = future / "current_selector_buckets/bucket_00.parquet"
    add_managed_pin(f,bucket)
    enable_future(f)
    append_future_generation(f, 5)
    assert future / "current_selector_buckets" not in actions(storage.plan(f.policy))


def test_cross_device_dryrun_never_moves(fixture, monkeypatch):
    f = fixture
    proposal = storage.plan(f.policy)
    original = Path.stat
    def different_device(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == f.quarantine:
            values = list(info)
            values[2] += 1
            return storage.os.stat_result(values)
        return info
    monkeypatch.setattr(Path, "stat", different_device)
    assert storage.apply(f.policy, proposal)["moved_bytes"] == 0
    assert not list(f.quarantine.iterdir())


def test_cli_rejects_managed_output_and_saves_external_plan(fixture, monkeypatch):
    f = fixture
    arguments = ["retention", "--policy", str(f.policy_path), "--policy-sha256", storage.digest(f.policy_path), "--plan"]
    monkeypatch.setattr(sys, "argv", [*arguments, str(f.runs / "unsafe.json")])
    with pytest.raises(storage.RetentionError, match="EXTERNAL_AUDIT_JSON"):
        storage.main()
    output = f.tmp / "external-audit-plan.json"
    monkeypatch.setattr(sys, "argv", [*arguments, str(output)])
    storage.main()
    assert json.loads(output.read_text())["plan_id"]
    assert not list(f.quarantine.iterdir())


def test_actual_publication_pointer_text_is_decoded_narrowly(fixture):
    f = fixture
    after = f.entries[-1][1]["candidates"]
    before = f.entries[-2][1]["candidates"]
    value = dict(status="COMMITTED", pointers=f.policy["pointers"],
        after={role: path + "\n" for role, path in after.items()},
        before_base64={role: storage.base64.b64encode((path + "\n").encode()).decode() for role, path in before.items()})
    journal = f.data / "runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_publication.json"
    write(journal, value)
    proposal = storage.plan(f.policy)
    assert {Path(path) for path in [*before.values(), *after.values()]} <= set(map(Path,proposal["protected"]))
    add_managed_pin(f,next(iter(after.values())) + "\n")
    with pytest.raises(storage.RetentionError, match="MISSING_PATH"):
        storage.plan(f.policy)
    update_inventory(f,lambda value:value.update(pins=[]))
    write(journal, {**value, "status": "PREPARED"})
    with pytest.raises(storage.RetentionError, match="RECOVERY_PENDING"):
        storage.plan(f.policy)




def install_checkpoint_proof_fixture(f, monkeypatch, run, status):
    import pyarrow as pa
    import pyarrow.parquet as pq
    raw_bytes = b"frozen-native-input"
    raw_sha = storage.hashlib.sha256(raw_bytes).hexdigest()
    raw = f.tmp / f"000001.SZ.{raw_sha}.day"
    raw.write_bytes(raw_bytes)
    event = write(f.tmp / "immutable-event.json", dict(events=[]))
    native_receipt = write(f.tmp / "native-update.receipt.json", dict(raw_sha256=raw_sha))
    snapshot = dict(schema="a_share_qfq_adjustment_input_research_cache_v1", asof_date=status["target_date"],
        source_files=[event], symbols={"000001.SZ":dict(raw_files=[dict(path=str(raw),sha256=raw_sha,
            native_update_receipt=native_receipt, original_ref=dict(current_native=dict(path="/missing/mutable/provenance.day")))], events=[])})
    snapshot_ref = write(run / "adjustment_input_snapshot.json", snapshot)
    keys = {"driver_sha256", "formula_sha256", "field_contract_sha256", "adapter_sha256",
            "input_adapter_sha256", "factor_cache_sha256", "tdx_adapter_sha256"}
    refs = {}
    for key in sorted(keys - {"adapter_sha256"}):
        path = f.tmp / "immutable_code" / (key + ".py")
        path.parent.mkdir(exist_ok=True)
        path.write_text(f"# frozen {key}\n")
        refs[key] = dict(path=str(path), sha256=storage.digest(path))
    owner = f.tmp / "immutable_code/research_panel_qfq.py"
    owner.write_text(f"DRIVER_SHA = {refs['driver_sha256']['sha256']!r}\nFORMULA_SHA = {refs['formula_sha256']['sha256']!r}\nUSER_FORMULA_SHA = {'a'*64!r}\n")
    refs["adapter_sha256"] = dict(path=str(owner), sha256=storage.digest(owner))
    monkeypatch.setattr(storage, "CERTIFIED_QFQ_OWNER", refs["adapter_sha256"]["sha256"])
    identity = {key:value["sha256"] for key,value in refs.items()}
    identity.update(input_sha256=storage.canonical(snapshot), user_formula_sha256="a"*64, turnover_input_sha256="b"*64)
    status.update(identity, adjustment_snapshot=snapshot_ref, asof_date=status["target_date"])
    write(run / "stage_status.json", status)
    write(run / "candidate_receipt.json", {**status, "status":"CANDIDATE_READY"})
    code = "000001.SZ"
    checkpoint_id = storage.canonical(dict(code=code, item=snapshot["symbols"][code], **identity))
    table = pa.table({"ts_code":[code],"trade_date":[status["target_date"]]}).replace_schema_metadata(
        {b"a_share_qfq_contract_v1":json.dumps(dict(checkpoint_id=checkpoint_id)).encode()})
    checkpoint = run / "symbol_checkpoints/000001.SZ.parquet"
    pq.write_table(table, checkpoint)
    write(checkpoint.with_suffix(".receipt.json"), dict(checkpoint_id=checkpoint_id,sha256=storage.digest(checkpoint)))
    claim_path = storage._ownership_root(f.policy) / "completed" / (run.name + ".json")
    claim = json.loads(claim_path.read_text())
    claim["checkpoint_reconstruction"] = dict(schema="v4_qfq_checkpoint_reconstruction_inputs_v1",
        snapshot=snapshot_ref, identity=identity, code_refs=refs, runtime=storage.reconstruction_runtime())
    write(claim_path, claim)
    return raw, snapshot, checkpoint


def test_certified_future_checkpoint_remains_candidate_without_reader_coordination(fixture, monkeypatch):
    f=fixture
    enable_future(f)
    run,status=append_future_generation(f,5)
    install_checkpoint_proof_fixture(f,monkeypatch,run,status)
    append_future_generation(f,6)
    append_future_generation(f,7)
    proposal=storage.plan(f.policy)
    checkpoint=next(action for action in proposal["actions"] if action["source"]==str(run/"symbol_checkpoints"))
    assert checkpoint["disposition"]=="RECLAIM_FUTURE"
    assert checkpoint["reconstruction"]["status"]=="PASS_SOURCE_CLOSURE"
    assert checkpoint["reconstruction"]["checkpoint_count"]==1
    for role,path in status["candidates"].items():
        root=Path(path).parent if role=="selector" else Path(path).parent.parent
        disposition,proof,_=storage.reclamation_classification(f.policy,dict(run=str(run),source=str(root)),status,{})
        assert disposition=="QUARANTINE_FUTURE_UNPROVEN" and proof["status"]=="UNKNOWN_FORMAL_RECONSTRUCTION"
    assert storage.apply(f.policy,proposal)["reclaimed_logical_bytes"]==0
    assert (run/"symbol_checkpoints/000001.SZ.parquet").exists()


@pytest.mark.parametrize("failure",["missing_raw","changed_raw","changed_code","fingerprint","source_budget"])
def test_unproven_future_checkpoint_only_quarantines(fixture,monkeypatch,failure):
    f=fixture
    enable_future(f)
    run,status=append_future_generation(f,5)
    raw,snapshot,checkpoint=install_checkpoint_proof_fixture(f,monkeypatch,run,status)
    append_future_generation(f,6)
    append_future_generation(f,7)
    if failure=="missing_raw":raw.unlink()
    elif failure=="changed_raw":raw.write_bytes(b"changed")
    elif failure=="changed_code":
        (f.tmp/"immutable_code/formula_sha256.py").write_text("# changed\n")
    elif failure=="fingerprint":
        write(checkpoint.with_suffix(".receipt.json"),dict(checkpoint_id="f"*64,sha256=storage.digest(checkpoint)))
    else:
        # A changed policy invalidates old ownership claims. Instead lower the
        # bounded proof directly to exercise source closure cap behavior.
        monkeypatch.setattr(storage,"stamp",(lambda original: lambda path: {**original(path),"size":40*1024**3} if path==raw else original(path))(storage.stamp))
    proposal=storage.plan(f.policy)
    action=next(action for action in proposal["actions"] if action["source"]==str(run/"symbol_checkpoints"))
    assert action["disposition"]=="QUARANTINE_FUTURE_UNPROVEN"
    assert action["reconstruction"]["status"]=="UNKNOWN_CHECKPOINT_RECONSTRUCTION"


def test_wrapper_releases_publication_lock_before_real_producer_flock(fixture,monkeypatch):
    f=fixture
    monkeypatch.setenv("V4_RESEARCH_RETENTION_POLICY",str(f.policy_path))
    monkeypatch.setenv("V4_RESEARCH_RETENTION_POLICY_SHA256",storage.digest(f.policy_path))
    acquired=[]
    def producer(**kwargs):
        with storage.owner_lock(f.policy,publication=True):acquired.append(True)
        return dict(status="READY",already_current=True)
    result=storage.run_with_retention(producer,data_root=f.data,return_root=f.runs,
        pointers={key:Path(value) for key,value in f.policy["pointers"].items()},target=20261104,ready_check=lambda:True)
    assert acquired==[True] and result["status"]=="READY"


def update_inventory(f,mutate):
    path=Path(f.policy["managed_pin_inventory"]["path"])
    value=json.loads(path.read_text())
    mutate(value)
    f.policy["managed_pin_inventory"]=write(path,value)
    write(f.policy_path,f.policy)


def test_typed_projection_watches_provenance_as_leaf_without_recursive_audit_walk(fixture):
    f=fixture
    source=f.tmp/"consumers.json"
    ref=write(source,dict(final_price_owner="/root/qfq_daily_writer",controller="/root",
        command_template="/missing/python /missing/script.py --run",old_audit=dict(path="/missing/historical-receipt.json",sha256="f"*64)))
    update_inventory(f,lambda value:value.update(source_bindings=[ref]))
    proposal=storage.plan(f.policy)
    assert str(source) in proposal["evidence"]
    assert not any("historical-receipt" in path for path in proposal["protected"])
    assert proposal["consumer_scope_attestations"]["model_frozen"]=="REVIEWED_NO_MANAGED_PINS"


def test_api_binding_byte_drift_blocks_reclamation(fixture):
    import plistlib
    f=fixture
    binding=f.tmp/"api.plist"
    binding.write_bytes(plistlib.dumps(dict(Label="V4_API",ProgramArguments=["/immutable/api/app"])))
    ref=dict(path=str(binding),sha256=storage.digest(binding))
    update_inventory(f,lambda value:value["source_bindings"].append(ref))
    assert storage.plan(f.policy)["plan_id"]
    binding.write_bytes(plistlib.dumps(dict(Label="V4_API",ProgramArguments=["/different/api/app"])))
    with pytest.raises(storage.RetentionError,match="HASH_DRIFT"):
        storage.plan(f.policy)


def test_unknown_consumer_scope_and_unknown_runtime_schema_block(fixture):
    f=fixture
    update_inventory(f,lambda value:value["consumer_scopes"].update(model_frozen="UNKNOWN"))
    with pytest.raises(storage.RetentionError,match="SCOPE_INCOMPLETE"):
        storage.plan(f.policy)
    update_inventory(f,lambda value:value["consumer_scopes"].update(model_frozen="REVIEWED_NO_MANAGED_PINS"))
    run,status=f.entries[-1]
    status["checkpoint_recovery"]=write(f.tmp/"unknown-runtime.json",dict(schema="unrecognized_recovery_v99",source_run=str(f.entries[0][0])))
    write(run/"stage_status.json",status)
    with pytest.raises(storage.RetentionError,match="RUNTIME_SCHEMA_UNKNOWN"):
        storage.plan(f.policy)


def test_runtime_main_binding_is_enforced_but_cli_plan_can_run_from_worktree(fixture,monkeypatch):
    f=fixture
    update_inventory(f,lambda value:value.update(expected_main_app_root="/different/immutable/Main/app"))
    # CLI planning is allowed from the isolated Writer/review worktree.
    assert storage.plan(f.policy)["plan_id"]
    monkeypatch.setenv("V4_RESEARCH_RETENTION_POLICY",str(f.policy_path))
    monkeypatch.setenv("V4_RESEARCH_RETENTION_POLICY_SHA256",storage.digest(f.policy_path))
    with pytest.raises(storage.RetentionError,match="MAIN_APP_ROOT_BINDING"):
        storage.run_with_retention(lambda **_:pytest.fail("wrong Main must not compute"),
            data_root=f.data,return_root=f.runs,pointers={key:Path(value) for key,value in f.policy["pointers"].items()},
            target=20261104,ready_check=lambda:True)


def test_history_runtime_refs_are_leaves_and_pin_managed_artifact(fixture):
    f=fixture
    old=f.entries[0][0]/"symbol_checkpoints/000001.SZ.parquet"
    config=write(f.tmp/"history-config.json",dict(final_price_owner="/root/qfq_daily_writer",provenance_path="/missing/audit.json"))
    policy=write(f.tmp/"history-policy.json",{})
    run,status=f.entries[-1]
    status["history_retention_binding"]=dict(source_config=config,source_policy=policy,
        archive_refs=[dict(path=str(old),sha256=storage.digest(old))],accepted_evidence=[])
    write(run/"stage_status.json",status)
    assert old.parent not in actions(storage.plan(f.policy))


def test_genuine_managed_root_paths_are_not_actor_id_exclusions(fixture):
    f=fixture
    add_managed_pin(f,"/root/qfq_daily_writer")
    with pytest.raises(storage.RetentionError,match="MISSING_PATH"):
        storage.plan(f.policy)


def test_historical_d30_recovery_drift_does_not_become_active_invocation(fixture):
    f=fixture
    source_run,source_status=f.entries[0]
    source_status["status"]="FAILED"
    write(source_run/"stage_status.json",source_status)
    d30,d30_status=f.entries[1]
    ref=recovery_ref(f,source_run)
    d30_status["checkpoint_recovery"]=ref
    write(d30/"stage_status.json",d30_status)
    add_managed_pin(f,d30)
    # Original mutable-cache snapshot was valid at the old D30 invocation and
    # later changed. It is not an input to the current Maincaller (resume=None).
    write(f.tmp/"recovery-snapshot.json",dict(asof_date=20261106))
    proposal=storage.plan(f.policy)
    assert str(source_run) in proposal["protected"] and str(d30) in proposal["protected"]
    assert any(storage.under(path,f.entries[2][0]) for path in actions(proposal))
    update_inventory(f,lambda value:value["pins"].append({**ref,"kind":"checkpoint_recovery","usage":"historical_pin"}))
    assert storage.plan(f.policy)["plan_id"]
    # An explicitly active invocation still requires the old _source bytes.
    with pytest.raises(storage.RetentionError,match="HASH_DRIFT"):
        storage.plan(f.policy,active_recovery_refs=[ref])
    update_inventory(f,lambda value:value["pins"][-1].update(usage="active_input"))
    with pytest.raises(storage.RetentionError,match="HASH_DRIFT"):
        storage.plan(f.policy)


def test_missing_usage_is_strict_and_unknown_usage_fails(fixture):
    f=fixture
    ref=recovery_ref(f,f.entries[0][0])
    update_inventory(f,lambda value:value["pins"].append({**ref,"kind":"checkpoint_recovery"}))
    write(f.tmp/"recovery-snapshot.json",dict(changed=True))
    with pytest.raises(storage.RetentionError,match="HASH_DRIFT"):
        storage.plan(f.policy)
    update_inventory(f,lambda value:value["pins"][-1].update(usage="unknown_mode"))
    with pytest.raises(storage.RetentionError,match="USAGE_UNKNOWN"):
        storage.plan(f.policy)


@pytest.mark.parametrize('verified', [True,False])
def test_governed_ready_reads_bypass_space_registry_but_stale_control_never_rebuilds(fixture,monkeypatch,verified):
    from ops import research_storage_governance as governance
    f=fixture
    f.policy['governance']=dict(enabled=True,registry_root=str(f.tmp/'registry'),pool_id='test-shared-apfs',pool_identity_verified=True)
    write(f.policy_path,f.policy)
    monkeypatch.setenv('V4_RESEARCH_RETENTION_POLICY',str(f.policy_path))
    monkeypatch.setenv('V4_RESEARCH_RETENTION_POLICY_SHA256',storage.digest(f.policy_path))
    monkeypatch.setattr(governance,'verified_qfq_current',lambda *args:dict(status='READY',already_current=True) if verified else None)
    monkeypatch.setattr(storage.shutil,'disk_usage',lambda _:pytest.fail('verified safe reuse must not need disk admission'))
    def forbidden(**kwargs):pytest.fail('no original full producer invocation from stale cheap READY')
    def run():return storage.run_with_retention(forbidden,data_root=f.data,return_root=f.runs,
        pointers={k:Path(v) for k,v in f.policy['pointers'].items()},target=20261104,ready_check=lambda:True)
    if verified:
        assert run()['storage_retention']['reservation']['status']=='VERIFIED_REUSE_NO_WRITES'
    else:
        with pytest.raises(storage.RetentionError,match='NO_AUTOMATIC_REBUILD'):run()
    assert not (f.tmp/'registry').exists()


def test_user_deleted_quarantine_dryrun_load_guard_plan_status_never_recreates(fixture,monkeypatch):
    from ops import research_storage_governance as governance
    f=fixture;f.quarantine.rmdir()
    f.policy.update(dry_run=True,auto_gc_enabled=False)
    f.policy['governance']=dict(enabled=True,registry_root=str(f.tmp/'registry'),pool_id='shared-test-apfs',pool_identity_verified=True)
    write(f.policy_path,f.policy)
    policy=storage.load_policy(f.policy_path)
    monkeypatch.setattr(storage.shutil,'disk_usage',lambda _:types.SimpleNamespace(free=200*1024**3,total=1000*1024**3))
    outcome=storage.growth_guard(policy,already_current=False)
    assert outcome['quarantine_bytes']==0 and outcome['quarantine_status']=='KNOWN_ABSENT_NONDELETING_DRYRUN'
    proposal=storage.plan(policy)
    assert storage.apply(policy,proposal)['moved_bytes']==0
    assert governance.read_only_status(policy)['status']=='READ_ONLY'
    assert not f.quarantine.exists() and not (f.tmp/'registry').exists()


@pytest.mark.parametrize('failure',['permission','not_directory','delete_enabled'])
def test_missing_quarantine_does_not_turn_unknown_or_unsafe_states_into_zero(fixture,monkeypatch,failure):
    f=fixture;f.quarantine.rmdir()
    if failure=='permission':
        original=Path.stat
        def denied(path,*args,**kwargs):
            if path==f.quarantine:raise PermissionError('controlled permission denied')
            return original(path,*args,**kwargs)
        monkeypatch.setattr(Path,'stat',denied)
        with pytest.raises(PermissionError):storage.quarantine_state(f.policy)
    elif failure=='not_directory':
        f.quarantine.write_text('not a directory')
        with pytest.raises(storage.RetentionError,match='NOT_DIRECTORY'):storage.quarantine_state(f.policy)
    else:
        f.policy.update(auto_gc_enabled=True,dry_run=False)
        with pytest.raises(storage.RetentionError,match='OUTSIDE_NONDELETING'):storage.quarantine_state(f.policy)


def test_three_registered_publications_keep_old_ordinary_bytes_billed_without_double_charge(fixture,monkeypatch):
    from ops import research_storage_governance as governance
    f=fixture;enable_future(f)
    f.policy['governance']=dict(enabled=True,registry_root=str(f.tmp/'registry'),pool_id='shared-test-pool',pool_identity_verified=True)
    monkeypatch.setattr(storage.shutil,'disk_usage',lambda _:types.SimpleNamespace(free=200*1024**3,total=1000*1024**3))
    config=governance.configuration(f.policy)
    initial=governance.ordinary_resident_paths(config)
    first_rollback=f.entries[-2][1]['candidates']['selector']
    charges=[]
    for index in (5,6,7):
        registry=governance.Registry(config,f.data)
        before=registry.read()
        expected_paths=set(initial)
        for row in before['tasks'].values():expected_paths.update(row.get('billing_paths',[]))
        expected=sum(storage.logical_bytes(path) for path in governance.unique_roots(expected_paths))
        with governance.admission(f.policy,key='publish-'+str(index),directory=f.runs,predicted=1024*1024) as (active,_):
            row=active.registry.read()['tasks'][active.key]
            assert row['category_baseline_bytes']==expected
            charges.append(expected)
            run,status=append_future_generation(f,index)
            active.finish(dict(status='READY',generation_id=status['generation_id']),list(status['candidates'].values()))
    assert charges[0]<charges[1]<charges[2]
    state=registry.read()
    assert first_rollback in state['resident_baseline_paths']
    assert any(str(f.entries[-3][0]) in row['billing_paths'] for row in state['tasks'].values())
    # Paths shared by dynamic current/rollback and prior V2 ownership roots are
    # deduplicated by actual containment, never baseline+everwritten arithmetic.
    paths=initial+governance.ordinary_resident_paths(config)
    for row in state['tasks'].values():paths.extend(row['billing_paths'])
    billed=governance.unique_roots(paths)
    assert not any(left!=right and storage.under(left,right) for left in billed for right in billed)
