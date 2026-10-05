import hashlib
import json
import subprocess
from pathlib import Path

import pytest


BASE = "35213f7416fa9f920f9a747151147b24eddc12c8"
TRACKED = (
    "apps/api/v35_api/research_router.py",
    "apps/web/src/components/review/AshareReviewPanel.vue",
    "apps/web/src/components/review/ReviewEvidencePanel.vue",
    "apps/web/src/contracts/research.ts",
    "apps/web/src/contracts/review.ts",
    "apps/web/src/views/ResearchView.spec.ts",
    "apps/web/src/views/ResearchView.vue",
    "apps/web/src/views/ReviewView.spec.ts",
    "domains/a_share_review.py",
    "domains/preselection.py",
    "domains/research.py",
    "domains/review_envelope.py",
    "infrastructure/a_share_review_store.py",
    "infrastructure/data_store.py",
    "infrastructure/research_store.py",
    "ops/import_a_share_review_reference.py",
    "ops/import_preselection.py",
    "ops/import_research_archive.py",
    "tests/test_a_share_review.py",
    "tests/test_a_share_review_store.py",
    "tests/test_preselection_slice.py",
)
INJECTED = (
    "a_share_reviews/20260731.json",
    "a_share_reviews/receipts/20260731.json",
    "preselection/20260731.json",
    "receipts/20260731.json",
    "receipts/research/archives/20260731.json",
    "receipts/research/desks/20260731.json",
    "receipts/stage_references/20260731/STAGE_0925.json",
    "research/archives/20260731.json",
    "research/desks/20260731.json",
    "stage_references/20260731/STAGE_0925.json",
)
ORACLES = (
    ".runtime/evidence/phase2/20260731/preselection_v3_20260731.json",
    ".runtime/evidence/phase2/20260731/stage_0925_v3_20260731.json",
    ".runtime/evidence/phase2/20260731/research_lane_v3_20260731.json",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(root: Path, *args: str) -> None:
    subprocess.run(("git", "-c", "core.hooksPath=NUL", "-c", "commit.gpgSign=false", *args), cwd=root, check=True, capture_output=True)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _raw_state(root: Path) -> dict[str, bytes]:
    paths = [*TRACKED, *(f".runtime/data/{item}" for item in INJECTED), *ORACLES]
    paths.extend((
        ".runtime/data/manifest.json",
        ".runtime/data/a_share_reviews/manifest.json",
        ".runtime/data/nested/manifest.json",
        ".runtime/data/date_catalog.json",
        ".runtime/data/research/latest.json",
        ".runtime/data/research/hourly/latest.json",
        ".runtime/data/research/latest.backup.json",
    ))
    return {relative: (root / relative).read_bytes() for relative in paths if (root / relative).is_file()}


@pytest.fixture
def recovery_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Recovery Test")
    for relative in TRACKED:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"base:{relative}\n", encoding="utf-8")
    for relative in ORACLES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"oracle:{relative}".encode())
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base")
    for relative in TRACKED:
        (root / relative).write_text(f"wrong:{relative}\n", encoding="utf-8")
    for relative in (
        "docs/superpowers/plans/2026-07-31-v35-runtime-and-review-remediation.md",
        "docs/superpowers/plans/2026-08-02-v35-equivalent-rebuild-corrective-plan.md",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    data = root / ".runtime/data"
    payload_hashes: dict[str, str] = {}
    for relative in INJECTED:
        path = data / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"injected:{relative}".encode())
        payload_hashes[relative] = _sha(path)
    _write_json(data / "manifest.json", {**payload_hashes, "unrelated/20260730.json": "a" * 64})
    _write_json(data / "a_share_reviews/manifest.json", {"a_share_reviews/20260731.json": payload_hashes["a_share_reviews/20260731.json"], "a_share_reviews/20260730.json": "b" * 64})
    _write_json(data / "nested/manifest.json", {"unrelated/20260730.json": "c" * 64})
    _write_json(data / "date_catalog.json", {"future_target_dates": ["20260731"], "materialized_rows": {"20260730": 1}, "stage_dates": ["20260730"]})
    _write_json(data / "research/latest.json", {"payload_path": "research/archives/20260731.json", "payload_sha256": payload_hashes["research/archives/20260731.json"]})
    _write_json(data / "research/hourly/latest.json", {"payload_path": "research/archives/20260730.json", "payload_sha256": "d" * 64})
    (data / "research/latest.backup.json").write_bytes(b"unmatched latest backup\r\n")
    return root


def _load():
    from ops.migration import recover_wrong_direction

    return recover_wrong_direction


def test_rejects_unexpected_head_before_any_destination_write(recovery_repo: Path) -> None:
    tool = _load()
    with pytest.raises(tool.RecoveryError, match="HEAD"):
        tool.recover(recovery_repo, "not-the-base", dry_run=True)
    assert not list((recovery_repo / ".runtime/evidence/recovery").glob("**/*")) if (recovery_repo / ".runtime/evidence/recovery").exists() else True


def test_rejects_unexpected_dirty_path_before_any_destination_write(recovery_repo: Path) -> None:
    tool = _load()
    (recovery_repo / "unapproved.txt").write_text("no", encoding="utf-8")
    with pytest.raises(tool.RecoveryError, match="unexpected dirty path"):
        tool.recover(recovery_repo, tool.current_head(recovery_repo), dry_run=True)
    assert not (recovery_repo / ".runtime/evidence/recovery").exists()


def test_apply_rejects_raw_byte_sha_drift_after_dry_run(recovery_repo: Path) -> None:
    tool = _load()
    base = tool.current_head(recovery_repo)
    result = tool.recover(recovery_repo, base, dry_run=True)
    (recovery_repo / TRACKED[0]).write_text("drift", encoding="utf-8")
    with pytest.raises(tool.RecoveryError, match="SHA drift"):
        tool.recover(recovery_repo, base, apply=True)
    assert (recovery_repo / ".runtime/data" / INJECTED[0]).exists()
    assert (Path(result["evidence_dir"]) / "operation-manifest.json").is_file()


def test_apply_restores_only_exact_paths_quarantines_ten_and_cleans_only_matched_references(recovery_repo: Path) -> None:
    tool = _load()
    base = tool.current_head(recovery_repo)
    date_catalog_bytes = (recovery_repo / ".runtime/data/date_catalog.json").read_bytes()
    hourly_latest_bytes = (recovery_repo / ".runtime/data/research/hourly/latest.json").read_bytes()
    oracle_hashes = {relative: _sha(recovery_repo / relative) for relative in ORACLES}
    unmatched_latest_bytes = (recovery_repo / ".runtime/data/research/latest.backup.json").read_bytes()
    dry = tool.recover(recovery_repo, base, dry_run=True)
    result = tool.recover(recovery_repo, base, apply=True)
    assert result["status"] == "APPLIED"
    assert result["quarantined_paths"] == list(INJECTED)
    for relative in TRACKED:
        assert (recovery_repo / relative).read_text(encoding="utf-8") == f"base:{relative}\n"
    for relative in INJECTED:
        assert not (recovery_repo / ".runtime/data" / relative).exists()
        assert (Path(dry["evidence_dir"]) / "injected_runtime" / relative).is_file()
    manifest = json.loads((recovery_repo / ".runtime/data/manifest.json").read_text(encoding="utf-8"))
    assert manifest == {"unrelated/20260730.json": "a" * 64}
    assert (recovery_repo / ".runtime/data/date_catalog.json").read_bytes() == date_catalog_bytes
    assert (recovery_repo / ".runtime/data/research/hourly/latest.json").read_bytes() == hourly_latest_bytes
    assert (recovery_repo / ".runtime/data/research/latest.backup.json").read_bytes() == unmatched_latest_bytes
    assert not (recovery_repo / ".runtime/data/research/latest.json").exists()
    assert {relative: _sha(recovery_repo / relative) for relative in ORACLES} == oracle_hashes


def test_preserves_unrelated_keys_plans_oracles_and_is_idempotent(recovery_repo: Path) -> None:
    tool = _load()
    base = tool.current_head(recovery_repo)
    plans = [recovery_repo / "docs/superpowers/plans/2026-07-31-v35-runtime-and-review-remediation.md", recovery_repo / "docs/superpowers/plans/2026-08-02-v35-equivalent-rebuild-corrective-plan.md"]
    before = {str(path): _sha(path) for path in [*plans, *(recovery_repo / item for item in ORACLES)]}
    tool.recover(recovery_repo, base, dry_run=True)
    first = tool.recover(recovery_repo, base, apply=True)
    second = tool.recover(recovery_repo, base, apply=True)
    assert second["status"] == "ALREADY_APPLIED"
    assert first["evidence_dir"] == second["evidence_dir"]
    assert {str(path): _sha(path) for path in [*plans, *(recovery_repo / item for item in ORACLES)]} == before


def test_fails_closed_on_ambiguous_latest_pointer(recovery_repo: Path) -> None:
    tool = _load()
    base = tool.current_head(recovery_repo)
    latest = recovery_repo / ".runtime/data/research/latest.json"
    payload = json.loads(latest.read_text(encoding="utf-8"))
    payload["payload_sha256"] = "0" * 64
    _write_json(latest, payload)
    with pytest.raises(tool.RecoveryError, match="ambiguous"):
        tool.recover(recovery_repo, base, dry_run=True)
    assert (recovery_repo / ".runtime/data/research/archives/20260731.json").exists()


def test_destination_collision_preflights_before_any_mutation(recovery_repo: Path) -> None:
    tool = _load()
    base = tool.current_head(recovery_repo)
    dry = tool.recover(recovery_repo, base, dry_run=True)
    collision = Path(dry["evidence_dir"]) / "injected_runtime" / INJECTED[0]
    collision.parent.mkdir(parents=True, exist_ok=True)
    collision.write_bytes(b"collision")
    before = _raw_state(recovery_repo)
    with pytest.raises(tool.RecoveryError, match="destination"):
        tool.recover(recovery_repo, base, apply=True)
    assert _raw_state(recovery_repo) == before
    assert collision.read_bytes() == b"collision"


def test_mid_move_failure_rolls_back_raw_state_and_is_rerunnable(recovery_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _load()
    base = tool.current_head(recovery_repo)
    tool.recover(recovery_repo, base, dry_run=True)
    before = _raw_state(recovery_repo)
    actual_move = tool.shutil.move
    failed = False

    def fail_second_injected_move(source: str, destination: str, *args: object, **kwargs: object) -> str:
        nonlocal failed
        if not failed and Path(source).as_posix().endswith(INJECTED[1]):
            failed = True
            raise OSError("injected move failure")
        return actual_move(source, destination, *args, **kwargs)

    monkeypatch.setattr(tool.shutil, "move", fail_second_injected_move)
    with pytest.raises(tool.RecoveryError, match="rollback completed"):
        tool.recover(recovery_repo, base, apply=True)
    assert _raw_state(recovery_repo) == before
    monkeypatch.setattr(tool.shutil, "move", actual_move)
    assert tool.recover(recovery_repo, base, apply=True)["status"] == "APPLIED"


def test_nested_manifest_drift_is_detected_before_apply_mutation(recovery_repo: Path) -> None:
    tool = _load()
    base = tool.current_head(recovery_repo)
    tool.recover(recovery_repo, base, dry_run=True)
    nested = recovery_repo / ".runtime/data/nested/manifest.json"
    before = _raw_state(recovery_repo)
    nested.write_bytes(b'{"drift":true}\n')
    with pytest.raises(tool.RecoveryError, match="reference SHA drift"):
        tool.recover(recovery_repo, base, apply=True)
    assert (recovery_repo / ".runtime/data" / INJECTED[0]).exists()
    assert (recovery_repo / TRACKED[0]).read_bytes() == before[TRACKED[0]]


def test_date_catalog_raw_byte_drift_is_detected_before_apply_mutation(recovery_repo: Path) -> None:
    tool = _load()
    base = tool.current_head(recovery_repo)
    tool.recover(recovery_repo, base, dry_run=True)
    before = _raw_state(recovery_repo)
    (recovery_repo / ".runtime/data/date_catalog.json").write_bytes(b'{"drift": true}\r\n')
    with pytest.raises(tool.RecoveryError, match="reference SHA drift"):
        tool.recover(recovery_repo, base, apply=True)
    assert (recovery_repo / ".runtime/data" / INJECTED[0]).exists()
    assert (recovery_repo / TRACKED[0]).read_bytes() == before[TRACKED[0]]


@pytest.mark.parametrize("drift", ("tracked", "quarantine", "oracle"))
def test_already_applied_revalidates_all_frozen_state(recovery_repo: Path, drift: str) -> None:
    tool = _load()
    base = tool.current_head(recovery_repo)
    dry = tool.recover(recovery_repo, base, dry_run=True)
    tool.recover(recovery_repo, base, apply=True)
    if drift == "tracked":
        (recovery_repo / TRACKED[0]).write_bytes(b"drift")
    elif drift == "quarantine":
        (Path(dry["evidence_dir"]) / "injected_runtime" / INJECTED[0]).write_bytes(b"drift")
    else:
        (recovery_repo / ORACLES[0]).write_bytes(b"drift")
    with pytest.raises(tool.RecoveryError, match="applied-state"):
        tool.recover(recovery_repo, base, apply=True)


@pytest.mark.parametrize("drift", ("head", "plan", "runtime_source", "pointer", "new_manifest", "new_latest"))
def test_already_applied_reenumerates_official_reference_surface(recovery_repo: Path, drift: str) -> None:
    tool = _load()
    base = tool.current_head(recovery_repo)
    tool.recover(recovery_repo, base, dry_run=True)
    tool.recover(recovery_repo, base, apply=True)
    if drift == "head":
        (recovery_repo / "head-drift.txt").write_text("drift", encoding="utf-8")
        _git(recovery_repo, "add", "head-drift.txt")
        _git(recovery_repo, "commit", "-m", "head drift")
    elif drift == "plan":
        (recovery_repo / "docs/superpowers/plans/2026-07-31-v35-runtime-and-review-remediation.md").write_bytes(b"drift")
    elif drift == "runtime_source":
        (recovery_repo / ".runtime/data" / INJECTED[0]).parent.mkdir(parents=True, exist_ok=True)
        (recovery_repo / ".runtime/data" / INJECTED[0]).write_bytes(b"reappeared")
    elif drift == "pointer":
        (recovery_repo / ".runtime/data/a_share_reviews/manifest.json").write_bytes(b"{}\n")
    elif drift == "new_manifest":
        _write_json(recovery_repo / ".runtime/data/new/manifest.json", {"unrelated": "e" * 64})
    else:
        _write_json(recovery_repo / ".runtime/data/research/hourly/latest.json", {"payload_path": "new", "payload_sha256": "f" * 64})
    with pytest.raises(tool.RecoveryError, match="applied-state"):
        tool.recover(recovery_repo, base, apply=True)


@pytest.mark.parametrize("failure", ("status", "manifest"))
def test_finalization_failure_rolls_back_and_is_rerunnable(
    recovery_repo: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    tool = _load()
    base = tool.current_head(recovery_repo)
    tool.recover(recovery_repo, base, dry_run=True)
    before = _raw_state(recovery_repo)
    if failure == "status":
        original = tool._status
        calls = 0

        def fail_final_status(root: Path) -> dict[str, str]:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("final status failure")
            return original(root)

        monkeypatch.setattr(tool, "_status", fail_final_status)
    else:
        original_write = tool._write_json

        def fail_applied_manifest(path: Path, value: object) -> None:
            if path.name == "operation-manifest.json" and isinstance(value, dict) and value.get("status") == "APPLIED":
                raise OSError("final manifest failure")
            original_write(path, value)

        monkeypatch.setattr(tool, "_write_json", fail_applied_manifest)
    with pytest.raises(tool.RecoveryError, match="rollback completed"):
        tool.recover(recovery_repo, base, apply=True)
    assert _raw_state(recovery_repo) == before
    monkeypatch.undo()
    assert tool.recover(recovery_repo, base, apply=True)["status"] == "APPLIED"
