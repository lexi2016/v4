from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path


E = Path("/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009")
PACKAGE = E / "package"
MANIFEST = PACKAGE / "SOURCE_MANIFEST.json"
OUT = E / "candidate/issue32_scheduler_shared_pair_r1"
RECEIPT = E / "writer/scheduler_shared_pair_candidate_r1.json"

ACTIVE = {
    "actual_pool_scheduler": Path(
        "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/"
        "hk-research-calendar-all-r1-20261007-scheduler/app"
    ),
    "actual_shared_owner": Path(
        "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/"
        "20260923-hk02-owner-rebase-r2/app/upstreams/v3_shared_data"
    ),
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def mode(path: Path) -> str:
    return format(stat.S_IMODE(path.stat().st_mode), "04o")


def canonical_sha(payload: object) -> str:
    return sha(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


def write_exclusive(path: Path, raw: bytes, file_mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, file_mode)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def main() -> None:
    if OUT.exists() or RECEIPT.exists():
        raise SystemExit("REFUSE_EXISTING_SCHEDULER_SHARED_CANDIDATE_OR_RECEIPT")
    source = json.loads(MANIFEST.read_text(encoding="utf-8"))
    selected = [
        row for row in source["files"]
        if row["owner"] in {"actual_pool_scheduler", "actual_shared_owner"}
    ]
    if len(selected) != 4:
        raise SystemExit(f"EXPECTED_FOUR_PAIRED_SOURCE_FILES:{len(selected)}")
    OUT.mkdir(parents=True, exist_ok=False)
    records = []
    try:
        for row in selected:
            owner = row["owner"]
            product = row["product_path"]
            if owner == "actual_pool_scheduler":
                active_path = ACTIVE[owner] / product
                output_rel = Path("scheduler_app") / product
            else:
                active_path = ACTIVE[owner] / product
                output_rel = Path("shared_owner") / "upstreams/v3_shared_data" / product
            active_raw = active_path.read_bytes()
            active_sha = sha(active_raw)
            active_mode = mode(active_path)
            if (active_sha, len(active_raw), active_mode) != (
                row["before_sha256"], row["before_bytes"], row["before_mode"]
            ):
                raise SystemExit(f"ACTIVE_OWNER_BASELINE_MISMATCH:{owner}:{product}")
            source_after = PACKAGE / row["after_package_path"]
            after_raw = source_after.read_bytes()
            after_sha = sha(after_raw)
            after_mode = format(int(row["after_mode"], 8), "04o")
            if (after_sha, len(after_raw), after_mode) != (
                row["after_sha256"], row["after_bytes"], row["after_mode"]
            ):
                raise SystemExit(f"PACKAGE_AFTER_IDENTITY_MISMATCH:{owner}:{product}")
            target = OUT / output_rel
            write_exclusive(target, after_raw)
            os.chmod(target, int(after_mode, 8))
            written = target.read_bytes()
            if sha(written) != after_sha or mode(target) != after_mode:
                raise SystemExit(f"CANDIDATE_AFTER_IDENTITY_MISMATCH:{owner}:{product}")
            records.append({
                "owner": owner,
                "product_path": product,
                "candidate_path": str(target),
                "active_source_path": str(active_path),
                "active_before_sha256": active_sha,
                "active_before_bytes": len(active_raw),
                "active_before_mode": active_mode,
                "candidate_after_sha256": after_sha,
                "candidate_after_bytes": len(written),
                "candidate_after_mode": after_mode,
            })
        candidate_manifest = {
            "schema_version": "v4.issue32.scheduler_shared_candidate.v1",
            "candidate_id": OUT.name,
            "candidate_type": "PAIRED_SOURCE_OVERLAY_NOT_FULL_RELEASE",
            "target_date": source["target_date"],
            "signal_date": source["price_signal_date"],
            "scheduler_runtime_identity": {
                "launchd_label": "com.lexi.v35.scheduler",
                "pid_observed": 1310,
                "active_working_directory": str(ACTIVE["actual_pool_scheduler"]),
                "active_module_root": str(ACTIVE["actual_pool_scheduler"]),
            },
            "shared_owner_root": str(ACTIVE["actual_shared_owner"]),
            "paired_owners": ["actual_pool_scheduler", "actual_shared_owner"],
            "files": records,
            "source_manifest_sha256": sha(MANIFEST.read_bytes()),
            "source_after_inventory_sha256": canonical_sha([
                {k: r[k] for k in ("owner", "product_path", "candidate_after_sha256", "candidate_after_bytes", "candidate_after_mode")}
                for r in records
            ]),
            "activation_performed": False,
            "live_source_modified": False,
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "stop_rule": "Do not publish unless both current owner baselines still match and independent review accepts the shared-source restore/atomicity boundary.",
        }
        m_raw = (json.dumps(candidate_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        write_exclusive(OUT / "candidate-manifest.json", m_raw)
        receipt = {
            "status": "PAIRED_CANDIDATE_READY_FOR_REVIEW",
            "candidate_path": str(OUT),
            "candidate_manifest_sha256": sha(m_raw),
            "candidate_source_inventory_sha256": candidate_manifest["source_after_inventory_sha256"],
            "paired_file_count": len(records),
            "active_before_identities_match": True,
            "after_package_identities_match": True,
            "candidate_after_identities_match": True,
            "active_write_count": 0,
            "live_owner_mutation_count": 0,
            "files": records,
            "source_manifest_sha256": candidate_manifest["source_manifest_sha256"],
        }
        receipt_raw = (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        write_exclusive(RECEIPT, receipt_raw)
        print(json.dumps({"receipt_path": str(RECEIPT), "receipt_sha256": sha(receipt_raw), **receipt}, ensure_ascii=False, sort_keys=True))
    except Exception:
        # Preserve partial candidate bytes as evidence if a late operation fails.
        raise


if __name__ == "__main__":
    main()
