#!/usr/bin/env python3
"""Assemble an INACTIVE API candidate for the supplement-inline panel change.

Copies the currently active Edan candidate (verified bytes), applies the
declared delta, recomputes the release manifest inventory, stages a new API
plist, and self-verifies with the real runtime identity validator plus an
isolated smoke on a spare port.  Never touches the live LaunchAgent, the live
API process, or the active candidate.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import plistlib
import shutil
import socket
import stat
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

LOCAL = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local")
ACTIVE_ROOT = LOCAL / "candidates/edan-single-20261102-b843699e8d3371ea"
ACTIVE_PLIST = Path.home() / "Library/LaunchAgents/com.lexi.v4.api.plist"
ACTIVE_PLIST_SHA256 = "09baad3ed6870940d2747fb639a6b42df73895fcc41a3db5258b36c217ca5cd2"
ACTIVE_MANIFEST_SHA256 = "f10179c1b8028d088ae8e00e9de60d068550e9441a41febaa76569a5c2c2fcb1"
RUNTIME_PYTHON = LOCAL / "runtime/venvs/v4-mac/bin/python"
WORKDIR = Path("/Users/lexi/Desktop/学习/agents调试/v4_stage_supplement_inline_20261102")
NEW_ID = "v4-stage-supplement-inline-20261102-89ef3a68"
NEW_ROOT = LOCAL / "candidates" / NEW_ID

# (relative path, source file, is_addition)
DELTA = [
    ("apps/web/src/App.vue", WORKDIR / "app/apps/web/src/App.vue", False),
    ("apps/web/dist/index.html", WORKDIR / "app/apps/web/dist/index.html", False),
    ("apps/web/dist/assets/main-CzmllJyl.js", WORKDIR / "app/apps/web/dist/assets/main-CzmllJyl.js", True),
    ("apps/web/dist/assets/main-DO7TQB6O.css", WORKDIR / "app/apps/web/dist/assets/main-DO7TQB6O.css", True),
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def diff_proof(before: bytes, after: bytes):
    if b"\x00" in before or b"\x00" in after:
        return None, None
    try:
        before_lines = before.decode("utf-8").splitlines()
        after_lines = after.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None, None
    lines = list(difflib.unified_diff(before_lines, after_lines, fromfile="before", tofile="after", n=0, lineterm=""))
    raw = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
    return sha256_bytes(raw), sum(line.startswith("@@") for line in lines)


def inventory(app_root: Path):
    entries = []
    for path in sorted(app_root.rglob("*")):
        if path.is_dir():
            continue
        st = path.lstat()
        if stat.S_ISLNK(st.st_mode):
            raise SystemExit(f"unexpected symlink in app tree: {path}")
        if not stat.S_ISREG(st.st_mode):
            raise SystemExit(f"unexpected non-regular file: {path}")
        entries.append({
            "kind": "file",
            "mode": f"{stat.S_IMODE(st.st_mode):04o}",
            "path": path.relative_to(app_root).as_posix(),
            "sha256": sha256_file(path),
            "size": st.st_size,
        })
    aggregate = sha256_bytes(json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
    return entries, aggregate


def free_port() -> int:
    for port in (8896, 8897, 8895, 8894):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise SystemExit("no free smoke port")


def http_get(url: str, timeout: float = 5.0) -> tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.status, resp.read()


def candidate_launch_plist(previous: bytes, new_app: Path, release_id: str,
                           manifest_path: Path, manifest_sha: str) -> dict:
    plist = plistlib.loads(previous)
    env = plist["EnvironmentVariables"]
    env["V4_APP_ROOT"] = str(new_app)
    env["V4_RELEASE_ID"] = release_id
    env["V4_RELEASE_MANIFEST_PATH"] = str(manifest_path)
    env["V4_RELEASE_MANIFEST_SHA256"] = manifest_sha
    # python -m resolves apps from cwd before PYTHONPATH. Match real launchd.
    plist["WorkingDirectory"] = str(new_app)
    return plist


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-receipt", type=Path, required=True)
    args = parser.parse_args()

    receipt_review = json.loads(args.review_receipt.read_text())
    review_status = str(receipt_review.get("status") or receipt_review.get("verdict") or "")
    if "PASS" not in review_status.upper() and "APPROVE" not in review_status.upper():
        raise SystemExit(f"independent review is not PASS: {review_status!r}")
    review_sha = sha256_file(args.review_receipt)

    if NEW_ROOT.exists():
        raise SystemExit(f"candidate root already exists: {NEW_ROOT}")
    active_app = ACTIVE_ROOT / "app"
    active_manifest_path = ACTIVE_ROOT / "release-manifest.json"
    if sha256_file(ACTIVE_PLIST) != ACTIVE_PLIST_SHA256:
        raise SystemExit("ACTIVE_API_PLIST_CHANGED")
    if sha256_file(active_manifest_path) != ACTIVE_MANIFEST_SHA256:
        raise SystemExit("ACTIVE_MANIFEST_CHANGED")
    active_manifest = json.loads(active_manifest_path.read_text())
    if active_manifest["application_inventory"]["aggregate_sha256"] != hashlib.sha256(
        json.dumps(active_manifest["application_inventory"]["entries"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest():
        raise SystemExit("ACTIVE_MANIFEST_INVENTORY_INCONSISTENT")

    delta_entries = []
    for relative, source, is_addition in DELTA:
        if not source.is_file():
            raise SystemExit(f"delta source missing: {source}")
        after = source.read_bytes()
        target = active_app / relative
        before = target.read_bytes() if target.exists() else None
        if is_addition and before is not None:
            raise SystemExit(f"addition target already exists in active app: {relative}")
        if not is_addition and before is None:
            raise SystemExit(f"modification target missing in active app: {relative}")
        entry = {"path": relative, "before_sha256": sha256_bytes(before) if before is not None else None,
                 "after_sha256": sha256_bytes(after)}
        if before is not None:
            entry["unified_diff_sha256"], entry["unified_diff_hunk_count"] = diff_proof(before, after)
        delta_entries.append(entry)
    delta_entries.sort(key=lambda item: item["path"])

    NEW_ROOT.mkdir()
    (NEW_ROOT / ".candidate-build-in-progress").write_text(f"created_at={int(time.time())}\n")
    try:
        base_entries = active_manifest["application_inventory"]["entries"]
        new_app = NEW_ROOT / "app"
        new_app.mkdir(parents=True)
        for base_entry in base_entries:
            relative = base_entry["path"]
            source = active_app / relative
            if source.is_symlink() or not source.is_file():
                raise SystemExit(f"manifest entry missing or irregular in active app: {relative}")
            target = new_app / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if target.stat().st_size != base_entry["size"] or sha256_file(target) != base_entry["sha256"]:
                raise SystemExit(f"base copy drift: {relative}")
        shutil.copytree(ACTIVE_ROOT / "research-panel", NEW_ROOT / "research-panel", symlinks=True)
        shutil.copy2(ACTIVE_ROOT / "research-panel-assets.json", NEW_ROOT / "research-panel-assets.json")
        (NEW_ROOT / "config").mkdir()
        shutil.copy2(ACTIVE_ROOT / "config/workbench-binding.json", NEW_ROOT / "config/workbench-binding.json")
        shutil.copy2(ACTIVE_PLIST, NEW_ROOT / "config/pre-supplement-com.lexi.v4.api.plist")

        for relative, source, _ in DELTA:
            target = new_app / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if sha256_file(target) != next(e["after_sha256"] for e in delta_entries if e["path"] == relative):
                raise SystemExit(f"delta copy mismatch: {relative}")

        entries, aggregate = inventory(new_app)
        additions = sum(1 for _, _, is_addition in DELTA if is_addition)
        if len(entries) != len(base_entries) + additions:
            raise SystemExit(f"unexpected inventory count: {len(entries)}")

        manifest = json.loads(json.dumps(active_manifest))
        manifest["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        manifest["release_id"] = NEW_ID
        manifest["app_root"] = str(new_app)
        manifest["activation_status"] = "NOT_ACTIVATED"
        manifest["deployment_status"] = "CANNOT_CONFIRM"
        manifest["candidate"] = dict(manifest.get("candidate") or {})
        manifest["candidate"]["root"] = str(NEW_ROOT)
        manifest["candidate"]["app_root"] = str(new_app)
        manifest["candidate"]["release_id"] = NEW_ID
        manifest["app_files"] = entries
        manifest["application_inventory"] = {"aggregate_sha256": aggregate, "entries": entries, "entry_count": len(entries)}
        manifest["base_candidate"] = {
            "release_id": active_manifest["release_id"],
            "manifest_sha256": ACTIVE_MANIFEST_SHA256,
            "plist_sha256": ACTIVE_PLIST_SHA256,
            "application_inventory_sha256": active_manifest["application_inventory"]["aggregate_sha256"],
        }
        manifest["supplement_inline_delta"] = {
            "purpose": "render AFTERFACT snapshot reselection Top10 inside the A-share candidate column; remove standalone data-snapshot-reselection block",
            "entries": delta_entries,
            "source_workspace": str(WORKDIR / "app"),
            "independent_review_receipt_sha256": review_sha,
            "frontend_build_assets": ["assets/main-CzmllJyl.js", "assets/main-DO7TQB6O.css"],
            "source_app_vue_sha256": sha256_file(WORKDIR / "app/apps/web/src/App.vue"),
            "research_panel_binding": "PRESERVED external env + manifest references unchanged (assets byte-identical)",
        }
        manifest_path = NEW_ROOT / "release-manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        manifest_sha = sha256_file(manifest_path)

        delta_receipt = {
            "schema_version": "v4.api_release_delta_receipt.v1",
            "base": {
                "release_root": str(ACTIVE_ROOT),
                "app_root": str(active_app),
                "release_id": active_manifest["release_id"],
                "release_manifest_path": str(active_manifest_path),
                "release_manifest_sha256": ACTIVE_MANIFEST_SHA256,
                "application_inventory_sha256": active_manifest["application_inventory"]["aggregate_sha256"],
                "application_inventory_entry_count": active_manifest["application_inventory"]["entry_count"],
            },
            "entries": delta_entries,
        }
        (NEW_ROOT / "api-integration-delta-receipt.json").write_text(json.dumps(delta_receipt, ensure_ascii=False, indent=2) + "\n")

        plist = candidate_launch_plist(ACTIVE_PLIST.read_bytes(), new_app, NEW_ID,
                                      manifest_path, manifest_sha)
        env = plist["EnvironmentVariables"]
        plist_path = NEW_ROOT / "config/com.lexi.v4.api.plist"
        plist_path.write_bytes(plistlib.dumps(plist, fmt=plistlib.FMT_XML, sort_keys=True))

        identity_env = {
            "V4_APP_ROOT": str(new_app),
            "V4_RELEASE_ID": NEW_ID,
            "V4_RELEASE_MANIFEST_PATH": str(manifest_path),
            "V4_RELEASE_MANIFEST_SHA256": manifest_sha,
            "PYTHONPATH": env.get("PYTHONPATH", "") + f":{new_app}",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        }
        identity = subprocess.run(
            [str(RUNTIME_PYTHON), "-B", "-c",
             "from infrastructure.scheduling.dispatcher import validate_release_identity as v; import json; print(json.dumps(v()))"],
            cwd=str(new_app), env={**identity_env}, text=True, capture_output=True, timeout=120,
        )
        if identity.returncode != 0:
            raise SystemExit(f"identity validation failed: {identity.stderr[-800:]}")
        identity_result = json.loads(identity.stdout.strip().splitlines()[-1])

        smoke_port = free_port()
        smoke_env = dict(plist["EnvironmentVariables"])
        smoke_env["V4_API_PORT"] = str(smoke_port)
        program = list(plist["ProgramArguments"])
        program[program.index("--port") + 1] = str(smoke_port)
        smoke_proc = subprocess.Popen(program, cwd=plist["WorkingDirectory"], env=smoke_env,
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        smoke = {"port": smoke_port, "healthz": None, "index_ok": None, "runtime_identity": None, "workbench_ok": None}
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    status, body = http_get(f"http://127.0.0.1:{smoke_port}/healthz")
                    if status == 200:
                        smoke["healthz"] = body.decode()
                        break
                except Exception:
                    time.sleep(0.5)
            if smoke["healthz"] is None:
                raise SystemExit("smoke API did not become healthy")
            _, index = http_get(f"http://127.0.0.1:{smoke_port}/")
            smoke["index_ok"] = b"main-CzmllJyl.js" in index
            _, meta = http_get(f"http://127.0.0.1:{smoke_port}/api/v1/runs/date-list?date=20261102")
            payload = json.loads(meta)
            smoke["runtime_identity"] = payload.get("runtime_identity")
            _, workbench = http_get(f"http://127.0.0.1:{smoke_port}/api/v4/workbench/stage?date=20261102&stage=STAGE_0925")
            wb = json.loads(workbench)
            smoke["workbench_ok"] = bool(wb.get("snapshot_reselection"))
            if not smoke["index_ok"] or (smoke["runtime_identity"] or {}).get("status") != "MANIFEST_EXECUTION_FILES_VERIFIED" \
                    or (smoke["runtime_identity"] or {}).get("release_id") != NEW_ID or not smoke["workbench_ok"]:
                raise SystemExit(f"smoke assertions failed: {json.dumps(smoke, ensure_ascii=False)}")
        finally:
            smoke_proc.terminate()
            try:
                smoke_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                smoke_proc.kill()
        (NEW_ROOT / "isolated-smoke.log").write_text(json.dumps(smoke, ensure_ascii=False, indent=2) + "\n")

        if sha256_file(ACTIVE_PLIST) != ACTIVE_PLIST_SHA256:
            raise SystemExit("live plist changed during packaging")
        status, _ = http_get("http://127.0.0.1:8873/healthz")
        if status != 200:
            raise SystemExit("live API unhealthy after packaging")

        preparation = {
            "schema_version": "v4.supplement_inline.preparation.v1",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "before_manifest_sha256": ACTIVE_MANIFEST_SHA256,
            "before_plist_sha256": ACTIVE_PLIST_SHA256,
            "candidate_manifest_sha256": manifest_sha,
            "candidate_plist_sha256": sha256_file(plist_path),
            "delta_receipt_sha256": sha256_file(NEW_ROOT / "api-integration-delta-receipt.json"),
            "identity_validation": identity_result,
            "isolated_smoke": smoke,
            "build_inventory_entry_count": len(entries),
            "build_inventory_aggregate_sha256": aggregate,
            "live_plist_untouched": True,
            "live_api_healthy": True,
            "activation_status": "NOT_ACTIVATED",
            "launchctl_called": False,
            "independent_review_receipt_sha256": review_sha,
        }
        (NEW_ROOT / "preparation.json").write_text(json.dumps(preparation, ensure_ascii=False, indent=2) + "\n")
        (NEW_ROOT / ".candidate-build-in-progress").unlink()
        print(json.dumps({
            "candidate_root": str(NEW_ROOT),
            "manifest_sha256": manifest_sha,
            "plist_sha256": preparation["candidate_plist_sha256"],
            "inventory_entries": len(entries),
            "identity": identity_result,
            "smoke": smoke,
        }, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"packaging failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
