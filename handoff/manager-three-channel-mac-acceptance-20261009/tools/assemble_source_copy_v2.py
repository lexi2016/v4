#!/usr/bin/env python3
"""Assemble a disposable full-source validation copy from approved frozen inputs."""
from __future__ import annotations
import hashlib
import json
import os
import shutil
from pathlib import Path

E = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_THREE_CHANNEL_MAC_ACCEPTANCE_20261009").resolve()
API = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_R3_REPAIR_MAC_20261009/candidate/api/app").resolve()
WEB = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_R3_REPAIR_MAC_20261009/candidate/web/repo/apps/web").resolve()
OWNER = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_REAL_RESULT_RECOVERY_20261009/candidate/original_r3_business_source").resolve()
PACKAGE = E / "incoming/manager-three-channel-repair-20261009"
TARGET = E / "candidate/mac_source_v2"
manifest = json.loads((PACKAGE / "source_manifest.json").read_text(encoding="utf-8"))
old_test_origin = E / "incoming/source_origins/test_manager_screen_summary_contract.py"
exclude_dir_names = {".git", ".venv", "venv", "node_modules", "dist", ".cache", "cache", "caches",
                     ".pytest_cache", ".mypy_cache", ".ruff_cache", ".vite", "coverage", "__pycache__",
                     "state", "states", "market_data", "raw_market_data", "credentials", "secrets"}
exclude_file_names = {".env", ".env.local", ".env.production", ".env.development", "credentials.json",
                      "service-account.json", "token.json", "id_rsa", "id_ed25519"}
excluded_raw_prefix = Path("tests/fixtures/hkconnect_stage_replay")
copied: dict[str, dict] = {}
excluded: list[dict] = []

if TARGET.exists() or TARGET.is_symlink():
    raise SystemExit("TARGET_ALREADY_EXISTS:" + str(TARGET))
if not API.is_dir() or not WEB.is_dir() or not OWNER.is_dir():
    raise SystemExit("APPROVED_SOURCE_MISSING")
if not old_test_origin.is_file():
    raise SystemExit("FIXED_TEST_ORIGIN_MISSING")

def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

def target_path(rel_path: Path, *, web_mode: bool) -> Path:
    return (Path("apps/web") / rel_path) if web_mode else rel_path

def copy_source(src_root: Path, role: str, *, skip_api_web: bool = False, web_mode: bool = False) -> None:
    for current_raw, dirs, files in os.walk(src_root, topdown=True, followlinks=False):
        current = Path(current_raw)
        rel_dir = current.relative_to(src_root)
        kept = []
        for name in sorted(dirs):
            rel = rel_dir / name
            low = name.lower()
            if (name in exclude_dir_names or low in exclude_dir_names or
                    (skip_api_web and rel == Path("apps/web")) or
                    (not web_mode and rel == excluded_raw_prefix)):
                reason = ("R3_API_WEB_REPLACED_BY_FROZEN_WEB_SOURCE" if skip_api_web and rel == Path("apps/web")
                          else "RAW_HK_MARKET_FIXTURE_EXCLUDED" if rel == excluded_raw_prefix
                          else "STATE_CACHE_CREDENTIAL_OR_BUILD_EXCLUDED")
                source_dir = src_root / rel
                if source_dir.exists() and source_dir.is_dir():
                    for q in source_dir.rglob("*"):
                        if q.is_file() and not q.is_symlink():
                            excluded.append({"source": str(q), "relative_source_path": str(q.relative_to(src_root)),
                                             "bytes": q.stat().st_size, "reason": reason})
                else:
                    excluded.append({"source": str(source_dir), "relative_source_path": rel.as_posix(),
                                     "bytes": None, "reason": reason})
                continue
            candidate = current / name
            if candidate.is_symlink():
                excluded.append({"source": str(candidate), "relative_source_path": rel.as_posix(),
                                 "bytes": None, "reason": "SOURCE_SYMLINK_NOT_COPIED"})
                continue
            kept.append(name)
        dirs[:] = kept
        for name in sorted(files):
            src = current / name
            source_rel = Path(rel_dir / name)
            rel = source_rel.as_posix()
            low_name = name.lower()
            if not web_mode and (source_rel == excluded_raw_prefix or excluded_raw_prefix in source_rel.parents):
                excluded.append({"source": str(src), "relative_source_path": rel, "bytes": src.stat().st_size,
                                 "reason": "RAW_HK_MARKET_FIXTURE_EXCLUDED"})
                continue
            if (low_name in exclude_file_names or low_name.startswith(".env.") or
                    src.suffix.lower() in {".pem", ".p12", ".pfx", ".key", ".secret", ".token"}):
                excluded.append({"source": str(src), "relative_source_path": rel, "bytes": src.stat().st_size,
                                 "reason": "CREDENTIAL_OR_SECRET_EXCLUDED"})
                continue
            if src.is_symlink():
                excluded.append({"source": str(src), "relative_source_path": rel, "bytes": None,
                                 "reason": "SOURCE_SYMLINK_NOT_COPIED"})
                continue
            target_rel = target_path(source_rel, web_mode=web_mode)
            dst = TARGET / target_rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            raw = dst.read_bytes()
            copied[target_rel.as_posix()] = {"path": target_rel.as_posix(), "role": role,
                                             "source": str(src), "bytes": len(raw), "sha256": sha(raw)}

copy_source(API, "R3_API_FROZEN_CANDIDATE", skip_api_web=True)
copy_source(WEB, "R3_WEB_FROZEN_CANDIDATE", web_mode=True)
owner_cli = OWNER / "ops/run_manager_daily_announcement.py"
target_cli = TARGET / "ops/run_manager_daily_announcement.py"
if not owner_cli.is_file() or not target_cli.is_file() or owner_cli.read_bytes() != target_cli.read_bytes():
    raise SystemExit("OWNER_CLI_SOURCE_DISAGREES_WITH_FROZEN_R3")
copied["ops/run_manager_daily_announcement.py"]["role"] = "ORIGINAL_ANNOUNCEMENT_OWNER_REFERENCE_BYTE_IDENTICAL_TO_R3"
copied["ops/run_manager_daily_announcement.py"]["verified_source"] = str(owner_cli)
test_rel = "tests/test_manager_screen_summary_contract.py"
test_target = TARGET / test_rel
test_raw = old_test_origin.read_bytes()
test_sha = hashlib.sha1(b"blob " + str(len(test_raw)).encode("ascii") + b"\0" + test_raw).hexdigest()
if len(test_raw) != 4760 or test_sha != "0d8a781023226e89de15bf2391dfa86d943153d9":
    raise SystemExit("FIXED_TEST_ORIGIN_IDENTITY_MISMATCH")
if test_target.exists():
    if test_target.read_bytes() != test_raw:
        raise SystemExit("EXISTING_BASELINE_TEST_DIFFERS:" + test_rel)
else:
    test_target.parent.mkdir(parents=True, exist_ok=True)
    test_target.write_bytes(test_raw)
copied[test_rel] = {"path": test_rel, "role": "FIXED_GITHUB_BASELINE_TEST_BLOB_ONLY_NOT_R3_RUNTIME",
                    "source": "lexi2016/v4@b19eb112bd641ca97cac1246af7c81d8873641f4:" +
                              "handoff/v4-running-source-20261005/canonical/tests/test_manager_screen_summary_contract.py",
                    "bytes": len(test_raw), "git_blob_sha": test_sha, "sha256": sha(test_raw)}
for p in TARGET.rglob("*"):
    if p.is_symlink():
        raise SystemExit("SYMLINK_IN_SOURCE_COPY:" + str(p))
    if p.is_file():
        try:
            p.resolve().relative_to(TARGET)
        except ValueError:
            raise SystemExit("SOURCE_COPY_ESCAPED_TARGET:" + str(p))
baseline = [{"path": rel, "bytes": (TARGET / rel).stat().st_size,
             "sha256": sha((TARGET / rel).read_bytes())} for rel in sorted(copied)]
root_bytes = sum(x["bytes"] for x in baseline)
api_preserve = []
for row in manifest.get("preserve", []):
    if "api_r3_candidate" in row["profiles"]:
        p = TARGET / row["path"]
        raw = p.read_bytes()
        api_preserve.append({"path": row["path"], "expected_sha256": row["sha256"],
                             "actual_sha256": sha(raw), "pass": sha(raw) == row["sha256"]})
receipt = {
    "schema_version": "three_channel_source_assembly.v1",
    "source_root": str(TARGET),
    "source_roles": {
        "api_r3_candidate": str(API),
        "web_r3_candidate": str(WEB),
        "original_announcement_owner_reference": str(owner_cli),
        "fixed_baseline_test": str(old_test_origin),
        "frozen_r3_candidate": manifest["frozen_r3_candidate"],
        "current_runtime_source_verified": False,
        "deployment_or_live_integration_claimed": False
    },
    "api_r3_files_copied": sum(x["role"].startswith("R3_API") or x["role"].startswith("ORIGINAL_ANNOUNCEMENT") for x in copied.values()),
    "web_r3_files_copied": sum(x["role"] == "R3_WEB_FROZEN_CANDIDATE" for x in copied.values()),
    "total_files": len(baseline), "total_bytes": root_bytes,
    "symlink_count": 0, "excluded": excluded,
    "protected_issue32_files": api_preserve,
    "files": list(copied.values()),
    "pass": all(x["pass"] for x in api_preserve) and len(baseline) == len(copied)
}
(E / "evidence").mkdir(parents=True, exist_ok=True)
(E / "evidence/source_profile_map_v2.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
(E / "evidence/source_baseline_manifest_v2.json").write_text(json.dumps({"source_root": str(TARGET), "files": baseline}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"source_root": str(TARGET), "files": len(baseline), "bytes": root_bytes,
                  "excluded_count": len(excluded), "symlink_count": 0,
                  "web_r3_files": receipt["web_r3_files_copied"],
                  "protected_issue32_files": api_preserve, "pass": receipt["pass"]}, ensure_ascii=False))
if not receipt["pass"]:
    raise SystemExit(1)
