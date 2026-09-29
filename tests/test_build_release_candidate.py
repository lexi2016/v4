from __future__ import annotations

import importlib.util
import json
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest


OPS_ROOT = Path(__file__).resolve().parents[1] / "ops"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CUTOVER = _load("prepare_api_only_cutover", OPS_ROOT / "prepare_api_only_cutover.py")
BUILDER = _load("build_release_candidate", OPS_ROOT / "build_release_candidate.py")


def _api_plist(path: Path, *, app_root: Path, manifest_path: Path) -> None:
    values = [
        "/usr/bin/env",
        "RESEARCH_ONLY=1",
        "production_allowed=false",
        "PRODUCTION_ALLOWED=false",
        "buy_gate_updated=false",
        "BUY_GATE_UPDATED=false",
        "orders_sent=false",
        "ORDERS_SENT=false",
        f"V35_APP_ROOT={app_root}",
        "V35_RELEASE_ID=old-release",
        f"V35_RUNTIME_ROOT={path.parent / 'runtime'}",
        f"V35_DATA_ROOT={path.parent / 'data'}",
        f"V4_MANAGER_RESEARCH_STATE_ROOT={path.parent / 'current-manager'}",
        f"V35_SHARED_DATA_ROOT={path.parent / 'shared-data'}",
        f"V35_STAGE_CENTER_SELECTION_ROOT={path.parent / 'stage-center'}",
        f"PYTHONPATH={app_root / 'upstreams'}:{app_root}",
        f"V35_RELEASE_MANIFEST_PATH={manifest_path}",
        "V35_RELEASE_MANIFEST_SHA256=old-manifest-sha",
        sys.executable,
        "-B",
        "-m",
        "apps.api.v35_api.run",
        "--host",
        "127.0.0.1",
        "--port",
        "8873",
    ]
    (path.parent / "current-manager").mkdir(exist_ok=True)
    payload = {
        "Label": "com.lexi.v35.api-only",
        "ProgramArguments": values,
        "WorkingDirectory": str(app_root),
        "RunAtLoad": True,
    }
    with path.open("wb") as handle:
        plistlib.dump(payload, handle, fmt=plistlib.FMT_XML, sort_keys=True)


def _scheduler_plist(path: Path, current_app: Path) -> None:
    payload = {
        "Label": "com.lexi.v35.scheduler",
        "ProgramArguments": ["/bin/bash", str(current_app / "ops" / "launch_v35_macos_scheduler.sh")],
        "WorkingDirectory": str(current_app),
        "EnvironmentVariables": {
            "V35_APP_ROOT": str(current_app),
            "V35_DATA_ROOT": str(path.parent / "data"),
            "V35_STAGE_CENTER_SELECTION_ROOT": str(path.parent / "stage-center"),
            "PRODUCTION_ALLOWED": "false",
            "BUY_GATE_UPDATED": "false",
            "ORDERS_SENT": "false",
        },
    }
    with path.open("wb") as handle:
        plistlib.dump(payload, handle, fmt=plistlib.FMT_XML, sort_keys=True)


def _git_source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    (source / "apps" / "web" / "src").mkdir(parents=True)
    (source / "apps" / "web" / "dist").mkdir(parents=True)
    (source / "apps" / "api").mkdir(parents=True)
    (source / "ops").mkdir(parents=True)
    (source / ".gitignore").write_text("apps/web/dist/\n")
    (source / "apps" / "web" / "index.html").write_text("<html>candidate</html>\n")
    (source / "apps" / "web" / "src" / "main.js").write_text("console.log('candidate');\n")
    (source / "apps" / "api" / "main.py").write_text("VALUE = 1\n")
    (source / "ops" / "entry.py").write_text("print('entry')\n")
    (source / "apps" / "web" / "dist" / "index.html").write_text("<html>dist</html>\n")
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.name", "candidate-test"], cwd=source, check=True)
    subprocess.run(["git", "add", ".gitignore", "apps/web/index.html", "apps/web/src/main.js", "apps/api/main.py", "ops/entry.py"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=source, check=True)
    return source


def test_rewrite_preserves_safety_and_runtime_roots_and_adds_isolated_manager_root(tmp_path: Path) -> None:
    plist_path = tmp_path / "api.plist"
    old_app = tmp_path / "old-app"
    old_manifest = tmp_path / "old-manifest.json"
    _api_plist(plist_path, app_root=old_app, manifest_path=old_manifest)
    with plist_path.open("rb") as handle:
        source = plistlib.load(handle)
    candidate_app = tmp_path / "evidence" / "candidate" / "app"
    manager_root = tmp_path / "evidence" / "candidate" / "state" / "manager_auto_research"
    staged = CUTOVER.rewrite_api_only_plist(
        source,
        candidate_app_root=candidate_app,
        release_id="candidate-release",
        manifest_path=tmp_path / "evidence" / "candidate" / "release-manifest.json",
        manifest_sha256="manifest-sha",
        candidate_manager_state_root=manager_root,
    )
    assignments = {
        item.split("=", 1)[0]: item.split("=", 1)[1]
        for item in staged["ProgramArguments"]
        if isinstance(item, str) and "=" in item
    }
    assert assignments["V35_APP_ROOT"] == str(candidate_app.resolve())
    assert assignments["V35_RELEASE_ID"] == "candidate-release"
    assert assignments["V35_RELEASE_MANIFEST_SHA256"] == "manifest-sha"
    assert assignments["V4_MANAGER_RESEARCH_STATE_ROOT"] == str(manager_root.resolve())
    assert assignments["V35_DATA_ROOT"] == str((tmp_path / "data").resolve())
    assert assignments["RESEARCH_ONLY"] == "1"
    assert assignments["PRODUCTION_ALLOWED"] == "false"
    assert staged["ProgramArguments"][0] == "/usr/bin/env"
    assert staged["ProgramArguments"].index(
        f"V4_MANAGER_RESEARCH_STATE_ROOT={manager_root.resolve()}"
    ) < staged["ProgramArguments"].index(sys.executable)
    assert staged["WorkingDirectory"] == str(candidate_app.resolve())


def test_render_cutover_is_staged_only_and_refuses_shared_manager_root(tmp_path: Path) -> None:
    source_plist = tmp_path / "api.plist"
    _api_plist(source_plist, app_root=tmp_path / "old-app", manifest_path=tmp_path / "old-manifest")
    candidate = tmp_path / "evidence" / "candidate"
    candidate.mkdir(parents=True)
    (candidate / "app").mkdir()
    manifest = candidate / "release-manifest.json"
    manifest.write_text("{}\n")
    current_state = tmp_path / "current-manager"
    current_state.mkdir(exist_ok=True)
    source_bytes = source_plist.read_bytes()
    plan = CUTOVER.render_cutover(
        source_plist_path=source_plist,
        candidate_root=candidate,
        release_id="candidate",
        manifest_path=manifest,
        manifest_sha256=CUTOVER.sha256_file(manifest),
        current_manager_state_root=current_state,
        source_root=tmp_path / "source-checkout",
    )
    assert plan["activation_status"] == "NOT_ACTIVATED"
    assert plan["launchctl_called"] is False
    assert plan["manager_state"]["roots_are_distinct"] is True
    assert (candidate / "config" / "com.lexi.v35.api-only.plist").is_file()
    with (candidate / "config" / "com.lexi.v35.api-only.plist").open("rb") as handle:
        staged = plistlib.load(handle)
    assert any(
        isinstance(item, str) and item.startswith("V4_MANAGER_RESEARCH_STATE_ROOT=")
        for item in staged["ProgramArguments"]
    )
    assert source_plist.read_bytes() == source_bytes
    shared_candidate = candidate / "shared"
    shared_candidate.mkdir()
    (shared_candidate / "app").mkdir()
    shared_manifest = shared_candidate / "release-manifest.json"
    shared_manifest.write_text("{}\n")
    with pytest.raises(ValueError, match="isolated"):
        CUTOVER.render_cutover(
            source_plist_path=source_plist,
            candidate_root=shared_candidate,
            release_id="candidate",
            manifest_path=shared_manifest,
            manifest_sha256="sha",
            current_manager_state_root=current_state,
            candidate_manager_state_root=current_state,
            source_root=tmp_path / "source-checkout",
        )


def test_render_cutover_requires_source_root_and_refuses_source_overlap(tmp_path: Path) -> None:
    source_plist = tmp_path / "api.plist"
    source = tmp_path / "source-checkout"
    source.mkdir()
    _api_plist(source_plist, app_root=tmp_path / "old-app", manifest_path=tmp_path / "old-manifest")
    manifest = source / "release-manifest.json"
    manifest.write_text("{}\n")
    current_state = tmp_path / "current-manager"
    current_state.mkdir(exist_ok=True)

    with pytest.raises(ValueError, match="separate from the source checkout"):
        CUTOVER.render_cutover(
            source_plist_path=source_plist,
            candidate_root=source,
            release_id="candidate",
            manifest_path=manifest,
            manifest_sha256="sha",
            current_manager_state_root=current_state,
            source_root=source,
        )

    with pytest.raises(SystemExit):
        CUTOVER._build_parser().parse_args(
            [
                "--source-plist",
                str(source_plist),
                "--candidate-root",
                str(tmp_path / "candidate"),
                "--release-id",
                "candidate",
                "--manifest-path",
                str(tmp_path / "candidate" / "release-manifest.json"),
                "--manifest-sha256",
                "sha",
            ]
        )


def test_render_cutover_requires_candidate_manager_root_below_candidate(tmp_path: Path) -> None:
    source_plist = tmp_path / "api.plist"
    _api_plist(source_plist, app_root=tmp_path / "old-app", manifest_path=tmp_path / "old-manifest")
    candidate = tmp_path / "evidence" / "candidate"
    candidate.mkdir(parents=True)
    (candidate / "app").mkdir()
    manifest = candidate / "release-manifest.json"
    manifest.write_text("{}\n")
    current_state = tmp_path / "current-manager"
    current_state.mkdir(exist_ok=True)

    with pytest.raises(ValueError, match="below candidate root"):
        CUTOVER.render_cutover(
            source_plist_path=source_plist,
            candidate_root=candidate,
            release_id="candidate",
            manifest_path=manifest,
            manifest_sha256="sha",
            current_manager_state_root=current_state,
            candidate_manager_state_root=tmp_path / "outside-manager",
            source_root=tmp_path / "source-checkout",
        )


def test_build_candidate_copies_current_dist_and_writes_manifest_and_plan(tmp_path: Path) -> None:
    source = _git_source(tmp_path)
    daemon = source / "ops" / "run_v35_macos_scheduler_daemon.py"
    daemon.write_text("# must be explicitly included\n", encoding="utf-8")
    formal = tmp_path / "formal-releases"
    formal.mkdir()
    current_app = tmp_path / "current-release" / "app"
    current_app.mkdir(parents=True)
    api_plist = tmp_path / "api.plist"
    scheduler_plist = tmp_path / "scheduler.plist"
    _api_plist(api_plist, app_root=current_app, manifest_path=tmp_path / "old-manifest")
    _scheduler_plist(scheduler_plist, current_app)
    current_state = tmp_path / "current-manager"
    current_state.mkdir(exist_ok=True)
    backup = tmp_path / "api-backup.plist"
    backup.write_bytes(api_plist.read_bytes())
    candidate = tmp_path / "evidence" / "candidate"
    receipt_path = tmp_path / "evidence" / "receipt.json"

    receipt = BUILDER.build_candidate(
        source_root=source,
        candidate_root=candidate,
        api_plist_path=api_plist,
        scheduler_plist_path=scheduler_plist,
        python=Path(sys.executable),
        release_id="candidate-release",
        backup_plist_path=backup,
        formal_release_root=formal,
        dependency_names=(),
        receipt_path=receipt_path,
    )
    assert receipt["activation_status"] == "NOT_ACTIVATED"
    assert receipt["deployment_status"] == "CANNOT_CONFIRM"
    assert receipt["frontend_dist_entry_count"] == 1
    assert (candidate / "app" / "apps" / "web" / "dist" / "index.html").is_file()
    assert not (candidate / "app" / "ops" / "run_v35_macos_scheduler_daemon.py").exists()
    assert (candidate / "config" / "api-only-cutover-plan.json").is_file()
    assert not (candidate / ".candidate-build-in-progress").exists()
    manifest = json.loads((candidate / "release-manifest.json").read_text())
    assert manifest["source"]["tracked_file_count"] == 5
    assert manifest["frontend_dist"]["entry_count"] == 1
    assert manifest["manager_state"]["candidate_state_copied"] is False
    assert manifest["cutover"]["launchctl_called"] is False
    assert json.loads(receipt_path.read_text())["manifest_sha256"] == receipt["manifest_sha256"]


def test_build_candidate_includes_only_explicit_reviewed_m3_untracked_paths(tmp_path: Path) -> None:
    source = _git_source(tmp_path)
    daemon = source / "ops" / "run_v35_macos_scheduler_daemon.py"
    daemon.write_text(
        "# reviewed persistent scheduler wrapper\n",
        encoding="utf-8",
    )
    (source / "domains").mkdir()
    (source / "domains" / "daily_research_review.py").write_text(
        "def load_daily_research_review():\n    return {}\n"
    )
    panel = source / "apps" / "web" / "src" / "components" / "review"
    panel.mkdir(parents=True)
    (panel / "DailyResearchReviewPanel.vue").write_text("<template><p>M3</p></template>\n")
    generation = source / "domains" / "research_review_generation"
    generation.mkdir()
    (generation / "generation.py").write_text("UNREVIEWED = True\n")

    formal = tmp_path / "formal-releases"
    formal.mkdir()
    current_app = tmp_path / "current-release" / "app"
    current_app.mkdir(parents=True)
    api_plist = tmp_path / "api.plist"
    scheduler_plist = tmp_path / "scheduler.plist"
    _api_plist(api_plist, app_root=current_app, manifest_path=tmp_path / "old-manifest")
    _scheduler_plist(scheduler_plist, current_app)
    candidate = tmp_path / "evidence" / "candidate"
    receipt_path = tmp_path / "evidence" / "receipt.json"
    requested = [
        "ops/run_v35_macos_scheduler_daemon.py",
        "domains/daily_research_review.py",
        "apps/web/src/components/review/DailyResearchReviewPanel.vue",
    ]

    receipt = BUILDER.build_candidate(
        source_root=source,
        candidate_root=candidate,
        api_plist_path=api_plist,
        scheduler_plist_path=scheduler_plist,
        python=Path(sys.executable),
        release_id="candidate-m3-review",
        formal_release_root=formal,
        dependency_names=(),
        receipt_path=receipt_path,
        include_untracked_paths=requested,
    )

    copied = sorted(requested)
    manifest = json.loads((candidate / "release-manifest.json").read_text())
    assert receipt["explicit_untracked_paths"] == copied
    assert manifest["source"]["explicit_untracked_paths_copied"] == copied
    assert manifest["source"]["git"]["included_untracked_paths"] == copied
    assert [item["path"] for item in manifest["source"]["explicit_untracked_provenance"]] == copied
    for relative in copied:
        assert (candidate / "app" / relative).is_file()
    assert (
        candidate / "app" / "ops" / "run_v35_macos_scheduler_daemon.py"
    ).read_text(encoding="utf-8") == "# reviewed persistent scheduler wrapper\n"
    assert not (candidate / "app" / "domains" / "research_review_generation" / "generation.py").exists()
    untracked = {item["path"] for item in manifest["source"]["git"]["untracked_files"]}
    assert "domains/research_review_generation/generation.py" in untracked


def test_unlisted_generation_path_remains_excluded(tmp_path: Path) -> None:
    # The explicit caller list is the approval boundary, not an obsolete ban
    # on a module which has now been independently integrated.
    source = _git_source(tmp_path)
    generation = source / "domains" / "research_review_generation"
    generation.mkdir(parents=True)
    (generation / "generation.py").write_text("UNREVIEWED = True\n")
    assert BUILDER._validate_explicit_untracked_paths(source, [],
        tracked_paths=BUILDER._git_tracked_paths(source),
        untracked_paths=BUILDER._git_untracked_paths(source)) == []


def test_existing_candidate_is_never_overwritten(tmp_path: Path) -> None:
    source = _git_source(tmp_path)
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    with pytest.raises(FileExistsError, match="overwrite existing candidate"):
        BUILDER._guard_candidate_root(
            candidate,
            source_root=source,
            formal_release_root=tmp_path / "formal",
        )


def test_candidate_under_formal_release_root_is_rejected(tmp_path: Path) -> None:
    source = _git_source(tmp_path)
    formal = tmp_path / "formal"
    formal.mkdir()
    with pytest.raises(ValueError, match="formal release"):
        BUILDER._guard_candidate_root(
            formal / "new-release",
            source_root=source,
            formal_release_root=formal,
        )


def test_explicit_reviewed_new_paths_not_limited_to_old_m3_three(tmp_path):
    from ops.build_release_candidate import _validate_explicit_untracked_paths, copy_explicit_untracked_tree, _explicit_include_provenance
    root = tmp_path / "source"; (root / "domains").mkdir(parents=True)
    (root / "domains" / "intraday_research.py").write_text("# reviewed fixture\n")
    (root / "do_not_include.py").write_text("# unreviewed fixture\n")
    paths = _validate_explicit_untracked_paths(root, ["domains/intraday_research.py"], tracked_paths=[],
        untracked_paths=["domains/intraday_research.py", "do_not_include.py"])
    out = tmp_path / "candidate"; out.mkdir(); copy_explicit_untracked_tree(root, out, paths)
    assert (out / "domains/intraday_research.py").is_file()
    assert not (out / "do_not_include.py").exists()
    assert _explicit_include_provenance(paths)[0]["approval"] == "CALLER_EXPLICIT_REVIEWED_PATH"


def test_explicit_untracked_ancestor_symlink_is_rejected(tmp_path):
    from ops.build_release_candidate import _validate_explicit_untracked_paths
    import pytest
    root = tmp_path / "source"; root.mkdir(); outside = tmp_path / "outside"; outside.mkdir()
    (outside / "x.py").write_text("pass\n"); (root / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        _validate_explicit_untracked_paths(root, ["linked/x.py"], tracked_paths=[], untracked_paths=["linked/x.py"])


def test_candidate_stages_scheduler_with_identical_api_manifest_pin(tmp_path):
    source = _git_source(tmp_path)
    (source / "ops/launch_v35_macos_scheduler.sh").write_text("#!/bin/sh\nexit 1 # fixture, not a runnable scheduler\n")
    subprocess.run(["git", "add", "ops/launch_v35_macos_scheduler.sh"], cwd=source, check=True)
    formal = tmp_path / "formal"; formal.mkdir()
    current = tmp_path / "current/app"; current.mkdir(parents=True)
    api = tmp_path / "api.plist"; scheduler = tmp_path / "scheduler.plist"
    _api_plist(api, app_root=current, manifest_path=tmp_path / "old-manifest")
    _scheduler_plist(scheduler, current)
    before_api, before_scheduler = api.read_bytes(), scheduler.read_bytes()
    candidate = tmp_path / "evidence/candidate"
    receipt = BUILDER.build_candidate(source_root=source, candidate_root=candidate, api_plist_path=api,
        scheduler_plist_path=scheduler, python=Path(sys.executable), release_id="same-reviewed-release",
        formal_release_root=formal, dependency_names=())
    api_obj = plistlib.loads((candidate / "config/com.lexi.v35.api-only.plist").read_bytes())
    sched = plistlib.loads((candidate / "config/com.lexi.v35.scheduler.plist").read_bytes())
    api_env = dict(value.split("=", 1) for value in api_obj["ProgramArguments"] if isinstance(value, str) and "=" in value)
    for key in ("V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_PATH", "V35_RELEASE_MANIFEST_SHA256", "PYTHONPATH"):
        assert sched["EnvironmentVariables"][key] == api_env[key]
    assert sched["WorkingDirectory"] == str(candidate / "app")
    assert sched["ProgramArguments"][1] == str(candidate / "app/ops/launch_v35_macos_scheduler.sh")
    assert receipt["scheduler_candidate"]["activation_status"] == "NOT_ACTIVATED"
    assert receipt["scheduler_candidate"]["launchctl_called"] is False
    assert api.read_bytes() == before_api and scheduler.read_bytes() == before_scheduler
