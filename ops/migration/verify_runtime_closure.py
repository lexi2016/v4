from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

_HASH = re.compile(r"--hash=sha256:[0-9a-fA-F]{64}(?:\s|$)")
_REQ = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)")
_CANON_NAME = re.compile(r"[-_.]+")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UNKNOWN = {"", "unknown", "cannot_confirm", "cannot_confirm_from_intake", "none", "null"}


class RuntimeClosureError(ValueError):
    pass


def _sha256(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_hash_pinned_lock(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file() or p.is_symlink():
        raise RuntimeClosureError(f"LOCK_MISSING_OR_SYMLINK:{p}")
    blocks: list[tuple[int, list[str], str, str]] = []
    current: tuple[int, list[str], str, str] | None = None
    for line_no, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _REQ.match(line)
        if match:
            if current is not None:
                blocks.append(current)
            raw_name, version = match.groups()
            name = _CANON_NAME.sub("-", raw_name.strip()).lower()
            current = (line_no, [line], name, version)
            continue
        if line.startswith("--hash=") and current is not None:
            current[1].append(line)
            continue
        if line.startswith("--") and current is None:
            continue
        if line == "\\" and current is not None:
            continue
        raise RuntimeClosureError(f"LOCK_LINE_INVALID:{line_no}:{line}")
    if current is not None:
        blocks.append(current)
    if not blocks:
        raise RuntimeClosureError("LOCK_EMPTY")
    hash_count = 0
    packages: dict[str, str] = {}
    for line_no, lines, name, version in blocks:
        joined = " ".join(lines)
        hashes = _HASH.findall(joined)
        if not hashes:
            raise RuntimeClosureError(f"UNHASHED_REQUIREMENT:{line_no}:{lines[0]}")
        previous = packages.get(name)
        if previous is not None and previous != version:
            raise RuntimeClosureError(f"LOCK_DUPLICATE_PACKAGE_VERSION:{name}:{previous}:{version}")
        packages[name] = version
        hash_count += len(hashes)
    return {
        "status": "HASH_PINNED_LOCK_VALID",
        "path": str(p.resolve()),
        "sha256": _sha256(p),
        "requirements": len(blocks),
        "hashes": hash_count,
        "packages": packages,
    }


def _package_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, str] = {}
    for raw_name, raw_version in value.items():
        name = _CANON_NAME.sub("-", str(raw_name).strip()).lower()
        if name:
            out[name] = str(raw_version)
    return out


def _source_lock_inventory_blockers(
    label: str, matrix_packages: Any, lock_result: dict[str, Any]
) -> list[str]:
    expected = _package_map(matrix_packages)
    locked = _package_map(lock_result.get("packages") or {})
    blockers: list[str] = []
    prefix = label.upper()
    for name, version in sorted(expected.items()):
        if name not in locked:
            blockers.append(f"{prefix}_SOURCE_LOCK_INVENTORY_MISMATCH:{name}")
        elif locked[name] != version:
            blockers.append(f"{prefix}_SOURCE_LOCK_VERSION_MISMATCH:{name}")
    return blockers


def _known_architecture(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    return None if text in _UNKNOWN else text


def _load_receipt(path: Path | str, schema: str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file() or p.is_symlink():
        raise RuntimeClosureError(f"EVIDENCE_RECEIPT_INVALID:{schema}:{p}")
    try:
        value = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeClosureError(f"EVIDENCE_RECEIPT_PARSE_FAILED:{schema}:{p}") from error
    if not isinstance(value, dict) or value.get("schema_version") != schema or value.get("status") != "PASS":
        raise RuntimeClosureError(f"EVIDENCE_RECEIPT_CONTRACT_MISMATCH:{schema}:{p}")
    value = dict(value)
    value["receipt_path"] = str(p.resolve())
    value["receipt_sha256"] = _sha256(p)
    return value


# Legacy/source-environment receipts remain readable for provenance, but they
# cannot prove that one merged runtime exists.
def _validate_legacy_abi_receipt(path: Path | str, matrix: dict[str, Any]) -> dict[str, Any]:
    receipt = _load_receipt(path, "v4.runtime.abi_compatibility_receipt.v1")
    if receipt.get("abi_compatibility_verified") is not True:
        raise RuntimeClosureError("ABI_RECEIPT_NOT_VERIFIED")
    architecture = _known_architecture(receipt.get("architecture"))
    minor = str(receipt.get("python_minor") or "").strip()
    stage = matrix.get("stage") or {}
    hk02 = matrix.get("hk02") or {}
    if architecture is None or not minor:
        raise RuntimeClosureError("ABI_RECEIPT_IDENTITY_MISSING")
    if minor != str(stage.get("python_minor") or "") or minor != str(hk02.get("python_minor") or ""):
        raise RuntimeClosureError("ABI_RECEIPT_PYTHON_MINOR_MISMATCH")
    return receipt


def _validate_legacy_launch_receipt(path: Path | str) -> dict[str, Any]:
    receipt = _load_receipt(path, "v4.runtime.launch_contract_equivalence_receipt.v1")
    if receipt.get("launch_contract_equivalence_verified") is not True:
        raise RuntimeClosureError("LAUNCH_RECEIPT_NOT_VERIFIED")
    return receipt


def _validate_legacy_rebuild_receipt(
    path: Path | str, *, stage_lock_sha256: str, hk02_lock_sha256: str
) -> dict[str, Any]:
    receipt = _load_receipt(path, "v4.runtime.fresh_rebuild_receipt.v1")
    wheelhouse_sha = str(receipt.get("wheelhouse_manifest_sha256") or "").lower()
    if (
        receipt.get("fresh_rebuild_verified") is not True
        or receipt.get("offline") is not True
        or _SHA256.fullmatch(wheelhouse_sha) is None
        or receipt.get("stage_lock_sha256") != stage_lock_sha256
        or receipt.get("hk02_lock_sha256") != hk02_lock_sha256
    ):
        raise RuntimeClosureError("REBUILD_RECEIPT_NOT_VERIFIED")
    return receipt


def _validate_legacy_behavior_receipt(path: Path | str) -> dict[str, Any]:
    receipt = _load_receipt(path, "v4.runtime.behavior_equivalence_receipt.v1")
    count = receipt.get("test_count")
    if receipt.get("behavior_equivalence_verified") is not True or not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        raise RuntimeClosureError("BEHAVIOR_RECEIPT_NOT_VERIFIED")
    return receipt




def _runtime_identity(receipt: dict[str, Any], *, code: str) -> tuple[str, str, str]:
    prefix = str(receipt.get("runtime_prefix") or "").strip()
    executable = str(receipt.get("python_executable") or "").strip()
    executable_sha = str(receipt.get("python_executable_sha256") or "").lower().strip()
    if not prefix or not executable or _SHA256.fullmatch(executable_sha) is None:
        raise RuntimeClosureError(f"{code}_RUNTIME_IDENTITY_MISSING")
    return prefix, executable, executable_sha

def _validate_unified_abi_receipt(path: Path | str, *, matrix_sha256: str) -> dict[str, Any]:
    receipt = _load_receipt(path, "v4.runtime.unified_abi_receipt.v1")
    minor = str(receipt.get("candidate_python_minor") or "").strip()
    architecture = _known_architecture(receipt.get("architecture"))
    if (
        receipt.get("abi_compatibility_verified") is not True
        or receipt.get("stage_import_abi_verified") is not True
        or receipt.get("hk02_import_abi_verified") is not True
        or not minor
        or architecture is None
    ):
        raise RuntimeClosureError("UNIFIED_ABI_RECEIPT_NOT_VERIFIED")
    if receipt.get("matrix_sha256") != matrix_sha256:
        raise RuntimeClosureError("UNIFIED_ABI_MATRIX_SHA_MISMATCH")
    _runtime_identity(receipt, code="UNIFIED_ABI")
    return receipt


def _validate_unified_rebuild_receipt(
    path: Path | str,
    *,
    stage_source_lock_sha256: str,
    hk02_source_lock_sha256: str,
    unified_lock_sha256: str,
    candidate_python_minor: str,
    architecture: str,
    runtime_identity: tuple[str, str, str],
    matrix_sha256: str,
    unified_abi_receipt_sha256: str,
) -> dict[str, Any]:
    receipt = _load_receipt(path, "v4.runtime.unified_rebuild_receipt.v1")
    wheelhouse_sha = str(receipt.get("wheelhouse_manifest_sha256") or "").lower()
    receipt_arch = _known_architecture(receipt.get("architecture"))
    identity = _runtime_identity(receipt, code="UNIFIED_REBUILD")
    if identity != runtime_identity:
        raise RuntimeClosureError("UNIFIED_REBUILD_RUNTIME_IDENTITY_MISMATCH")
    if (
        receipt.get("fresh_rebuild_verified") is not True
        or receipt.get("offline") is not True
        or receipt.get("same_runtime_prefix_verified") is not True
        or receipt.get("stage_workload_loaded") is not True
        or receipt.get("hk02_workload_loaded") is not True
        or str(receipt.get("candidate_python_minor") or "") != candidate_python_minor
        or receipt_arch != architecture
        or _SHA256.fullmatch(wheelhouse_sha) is None
        or receipt.get("stage_source_lock_sha256") != stage_source_lock_sha256
        or receipt.get("hk02_source_lock_sha256") != hk02_source_lock_sha256
        or receipt.get("unified_lock_sha256") != unified_lock_sha256
        or receipt.get("matrix_sha256") != matrix_sha256
        or receipt.get("unified_abi_receipt_sha256") != unified_abi_receipt_sha256
    ):
        raise RuntimeClosureError("UNIFIED_REBUILD_RECEIPT_NOT_VERIFIED")
    return receipt


def _validate_unified_launch_receipt(
    path: Path | str, *, unified_lock_sha256: str, unified_rebuild_receipt_sha256: str,
    runtime_identity: tuple[str, str, str], matrix_sha256: str
) -> dict[str, Any]:
    receipt = _load_receipt(path, "v4.runtime.unified_launch_contract_receipt.v1")
    if _runtime_identity(receipt, code="UNIFIED_LAUNCH") != runtime_identity:
        raise RuntimeClosureError("UNIFIED_LAUNCH_RUNTIME_IDENTITY_MISMATCH")
    if (
        receipt.get("launch_contract_equivalence_verified") is not True
        or receipt.get("same_runtime_prefix_verified") is not True
        or receipt.get("stage_launch_verified") is not True
        or receipt.get("hk02_launch_verified") is not True
        or receipt.get("unified_lock_sha256") != unified_lock_sha256
        or receipt.get("unified_rebuild_receipt_sha256") != unified_rebuild_receipt_sha256
        or receipt.get("matrix_sha256") != matrix_sha256
    ):
        raise RuntimeClosureError("UNIFIED_LAUNCH_RECEIPT_NOT_VERIFIED")
    return receipt


def _validate_unified_behavior_receipt(
    path: Path | str, *, unified_lock_sha256: str, unified_rebuild_receipt_sha256: str,
    runtime_identity: tuple[str, str, str], matrix_sha256: str
) -> dict[str, Any]:
    receipt = _load_receipt(path, "v4.runtime.unified_behavior_equivalence_receipt.v1")
    if _runtime_identity(receipt, code="UNIFIED_BEHAVIOR") != runtime_identity:
        raise RuntimeClosureError("UNIFIED_BEHAVIOR_RUNTIME_IDENTITY_MISMATCH")
    stage_count = receipt.get("stage_test_count")
    hk_count = receipt.get("hk02_test_count")
    if (
        receipt.get("behavior_equivalence_verified") is not True
        or receipt.get("same_runtime_prefix_verified") is not True
        or receipt.get("stage_output_equivalence_verified") is not True
        or receipt.get("hk02_output_equivalence_verified") is not True
        or not isinstance(stage_count, int)
        or isinstance(stage_count, bool)
        or stage_count <= 0
        or not isinstance(hk_count, int)
        or isinstance(hk_count, bool)
        or hk_count <= 0
        or receipt.get("unified_lock_sha256") != unified_lock_sha256
        or receipt.get("unified_rebuild_receipt_sha256") != unified_rebuild_receipt_sha256
        or receipt.get("matrix_sha256") != matrix_sha256
    ):
        raise RuntimeClosureError("UNIFIED_BEHAVIOR_RECEIPT_NOT_VERIFIED")
    return receipt


def _source_differences(matrix: dict[str, Any]) -> list[str]:
    stage = matrix.get("stage") or {}
    hk02 = matrix.get("hk02") or {}
    differences: list[str] = []
    if stage.get("python_minor") != hk02.get("python_minor"):
        differences.append("PYTHON_MINOR_MISMATCH")
    sp = _package_map(stage.get("packages") or {})
    hp = _package_map(hk02.get("packages") or {})
    for name in sorted(set(sp) & set(hp)):
        if sp[name] != hp[name]:
            differences.append(f"PACKAGE_VERSION_MISMATCH:{name}")
    return differences


def evaluate_runtime_closure(
    path: Path | str,
    *,
    stage_lock: Path | str | None = None,
    hk02_lock: Path | str | None = None,
    # Legacy/source-environment evidence.  Kept only so old review fixtures are
    # explicit; none of these fields can substitute for unified-candidate proof.
    abi_receipt: Path | str | None = None,
    launch_receipt: Path | str | None = None,
    rebuild_receipt: Path | str | None = None,
    behavior_receipt: Path | str | None = None,
    # A merge feasibility result requires one concrete candidate environment.
    unified_lock: Path | str | None = None,
    unified_abi_receipt: Path | str | None = None,
    unified_launch_receipt: Path | str | None = None,
    unified_rebuild_receipt: Path | str | None = None,
    unified_behavior_receipt: Path | str | None = None,
) -> dict[str, Any]:
    matrix_path = Path(path)
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    if not isinstance(matrix, dict):
        raise RuntimeClosureError("MATRIX_NOT_OBJECT")

    matrix_sha256 = _sha256(matrix_path)
    source_differences = _source_differences(matrix)
    blockers: list[str] = []
    evidence: dict[str, Any] = {}
    source_closure_gaps: list[str] = []

    stage_lock_result: dict[str, Any] | None = None
    hk_lock_result: dict[str, Any] | None = None
    if stage_lock is None or hk02_lock is None:
        blockers.append("SOURCE_LOCKS_NOT_VALIDATED")
        source_closure_gaps.append("HASH_PINNED_SOURCE_LOCKS_MISSING")
    else:
        stage_lock_result = validate_hash_pinned_lock(stage_lock)
        hk_lock_result = validate_hash_pinned_lock(hk02_lock)
        evidence["stage_source_lock"] = stage_lock_result
        evidence["hk02_source_lock"] = hk_lock_result
        blockers.extend(_source_lock_inventory_blockers("STAGE", (matrix.get("stage") or {}).get("packages"), stage_lock_result))
        blockers.extend(_source_lock_inventory_blockers("HK02", (matrix.get("hk02") or {}).get("packages"), hk_lock_result))

    # Validate legacy/source evidence if supplied, but never count it as merged
    # runtime proof.  Missing legacy receipts are a source-closure gap, not an
    # independent way to become merge-eligible.
    if abi_receipt is not None:
        evidence["legacy_abi_receipt"] = _validate_legacy_abi_receipt(abi_receipt, matrix)
    else:
        source_closure_gaps.append("LEGACY_ABI_RECEIPT_NOT_VALIDATED")
    if launch_receipt is not None:
        evidence["legacy_launch_receipt"] = _validate_legacy_launch_receipt(launch_receipt)
    else:
        source_closure_gaps.append("LEGACY_LAUNCH_RECEIPT_NOT_VALIDATED")
    if rebuild_receipt is not None and stage_lock_result is not None and hk_lock_result is not None:
        evidence["legacy_rebuild_receipt"] = _validate_legacy_rebuild_receipt(
            rebuild_receipt,
            stage_lock_sha256=str(stage_lock_result["sha256"]),
            hk02_lock_sha256=str(hk_lock_result["sha256"]),
        )
    elif rebuild_receipt is not None:
        raise RuntimeClosureError("LEGACY_REBUILD_RECEIPT_REQUIRES_SOURCE_LOCKS")
    else:
        source_closure_gaps.append("LEGACY_REBUILD_RECEIPT_NOT_VALIDATED")
    if behavior_receipt is not None:
        evidence["legacy_behavior_receipt"] = _validate_legacy_behavior_receipt(behavior_receipt)
    else:
        source_closure_gaps.append("LEGACY_BEHAVIOR_RECEIPT_NOT_VALIDATED")

    unified_lock_result: dict[str, Any] | None = None
    if unified_lock is None:
        blockers.append("UNIFIED_LOCK_NOT_VALIDATED")
    else:
        unified_lock_result = validate_hash_pinned_lock(unified_lock)
        evidence["unified_lock"] = unified_lock_result

    unified_abi: dict[str, Any] | None = None
    if unified_abi_receipt is None:
        blockers.append("UNIFIED_ABI_RECEIPT_NOT_VALIDATED")
    else:
        unified_abi = _validate_unified_abi_receipt(unified_abi_receipt, matrix_sha256=matrix_sha256)
        evidence["unified_abi_receipt"] = unified_abi

    unified_rebuild: dict[str, Any] | None = None
    if (
        unified_rebuild_receipt is None
        or unified_lock_result is None
        or stage_lock_result is None
        or hk_lock_result is None
        or unified_abi is None
    ):
        blockers.append("UNIFIED_REBUILD_RECEIPT_NOT_VALIDATED")
        blockers.append("UNIFIED_WHEELHOUSE_NOT_VERIFIED")
    else:
        unified_runtime_identity = _runtime_identity(unified_abi, code="UNIFIED_ABI")
        unified_rebuild = _validate_unified_rebuild_receipt(
            unified_rebuild_receipt,
            stage_source_lock_sha256=str(stage_lock_result["sha256"]),
            hk02_source_lock_sha256=str(hk_lock_result["sha256"]),
            unified_lock_sha256=str(unified_lock_result["sha256"]),
            candidate_python_minor=str(unified_abi["candidate_python_minor"]),
            architecture=str(_known_architecture(unified_abi["architecture"])),
            runtime_identity=unified_runtime_identity,
            matrix_sha256=matrix_sha256,
            unified_abi_receipt_sha256=str(unified_abi["receipt_sha256"]),
        )
        evidence["unified_rebuild_receipt"] = unified_rebuild

    if unified_launch_receipt is None or unified_lock_result is None or unified_rebuild is None:
        blockers.append("UNIFIED_LAUNCH_RECEIPT_NOT_VALIDATED")
    else:
        evidence["unified_launch_receipt"] = _validate_unified_launch_receipt(
            unified_launch_receipt,
            unified_lock_sha256=str(unified_lock_result["sha256"]),
            unified_rebuild_receipt_sha256=str(unified_rebuild["receipt_sha256"]),
            runtime_identity=_runtime_identity(unified_rebuild, code="UNIFIED_REBUILD"),
            matrix_sha256=matrix_sha256,
        )

    if unified_behavior_receipt is None or unified_lock_result is None or unified_rebuild is None:
        blockers.append("UNIFIED_BEHAVIOR_RECEIPT_NOT_VALIDATED")
    else:
        evidence["unified_behavior_receipt"] = _validate_unified_behavior_receipt(
            unified_behavior_receipt,
            unified_lock_sha256=str(unified_lock_result["sha256"]),
            unified_rebuild_receipt_sha256=str(unified_rebuild["receipt_sha256"]),
            runtime_identity=_runtime_identity(unified_rebuild, code="UNIFIED_REBUILD"),
            matrix_sha256=matrix_sha256,
        )

    # When no complete single-runtime candidate exists, observed current-source
    # differences are active blockers.  A fully proven unified candidate may
    # supersede those differences, but they remain visible for review.
    candidate_blockers = list(dict.fromkeys(blockers))
    if candidate_blockers:
        for difference in source_differences:
            if difference not in candidate_blockers:
                candidate_blockers.append(difference)

    return {
        "decision": "KEEP_ISOLATED" if candidate_blockers else "MERGE_ELIGIBLE_FOR_INDEPENDENT_REVIEW",
        "merge_approved": False,
        "matrix_sha256": matrix_sha256,
        "blockers": candidate_blockers,
        "source_differences": source_differences,
        "source_closure_gaps": source_closure_gaps,
        "validated_evidence": evidence,
        "shared_cache_allowed": "IMMUTABLE_WHEEL_DOWNLOAD_CACHE_ONLY",
        "installed_site_packages_share_allowed": False,
        "evidence_rule": (
            "two independently rebuildable runtimes are not merge proof; eligibility requires source locks plus "
            "one hash-pinned unified candidate lock and ABI, launch, offline rebuild/wheelhouse, and behavior receipts "
            "proving both workloads ran in the same candidate runtime. Eligibility is review-only; merge_approved stays false."
        ),
    }


def evaluate_matrix(path: Path | str) -> dict[str, Any]:
    """Conservative compatibility wrapper: matrix-only evidence never permits a merge."""
    return evaluate_runtime_closure(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--stage-lock", type=Path)
    parser.add_argument("--hk02-lock", type=Path)
    parser.add_argument("--abi-receipt", type=Path, help="legacy/source-environment evidence only")
    parser.add_argument("--launch-receipt", type=Path, help="legacy/source-environment evidence only")
    parser.add_argument("--rebuild-receipt", type=Path, help="legacy/source-environment evidence only")
    parser.add_argument("--behavior-receipt", type=Path, help="legacy/source-environment evidence only")
    parser.add_argument("--unified-lock", type=Path)
    parser.add_argument("--unified-abi-receipt", type=Path)
    parser.add_argument("--unified-launch-receipt", type=Path)
    parser.add_argument("--unified-rebuild-receipt", type=Path)
    parser.add_argument("--unified-behavior-receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        result = evaluate_runtime_closure(
            args.matrix,
            stage_lock=args.stage_lock,
            hk02_lock=args.hk02_lock,
            abi_receipt=args.abi_receipt,
            launch_receipt=args.launch_receipt,
            rebuild_receipt=args.rebuild_receipt,
            behavior_receipt=args.behavior_receipt,
            unified_lock=args.unified_lock,
            unified_abi_receipt=args.unified_abi_receipt,
            unified_launch_receipt=args.unified_launch_receipt,
            unified_rebuild_receipt=args.unified_rebuild_receipt,
            unified_behavior_receipt=args.unified_behavior_receipt,
        )
    except (RuntimeClosureError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "REJECTED", "error": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
