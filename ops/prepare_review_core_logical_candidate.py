"""Prepare a reproducible two-file overlay for the isolated Review Core role."""
import argparse
import hashlib
import json
from pathlib import Path

from infrastructure.owned_io import SafeRoot


BASE = {
    'macos_daily.py': 'b280430cab67a576b9baaf58147e6bb9ebd4d793211d1728d685d05790e787d7',
    'review_pipeline.py': '632b85281aa23e95c72fd1de9e40523ac1031c1e3d6ba89cf320ecd80e39b707',
}

GATE_READ = '''    selector_validation = inspect_selector_pointer(paths.selector_pointer, target, **selector_kwargs)
    selector_ready = bool(selector_validation.get("ready"))
'''
GATE_DIAGNOSTIC = '''    selector_validation = inspect_selector_pointer(paths.selector_pointer, target, **selector_kwargs)
    from ops.review_core_logical_selector import candidate_selector
    try:
        logical_path = selector_validation.get("path") or _selector_target(paths.selector_pointer)
        if logical_path:
            logical = candidate_selector(Path(logical_path), target,
                                         expected_sha256=selector_validation.get("selector_sha256"))
            if logical is not None:
                selector_validation["logical_read"] = logical.evidence()
    except Exception as error:
        selector_validation["logical_read"] = {"status": "CANNOT_CONFIRM", "reason": str(error)}
    selector_ready = bool(selector_validation.get("ready"))
'''
EXACT_READ = '''        table = parquet.read_table(path, columns=["trade_date"])
'''
EXACT_LOGICAL_READ = '''        from ops.review_core_logical_selector import candidate_selector
        logical = candidate_selector(path, target_date)
        if logical is not None:
            return logical.pit_certified and logical.exact(["trade_date"]).num_rows > 0
        table = parquet.read_table(path, columns=["trade_date"])
'''
PIPELINE_LOAD = '''    selector_rows, selector_names = _load_selector_rows(selector_file, trade_date)
'''
PIPELINE_LOGICAL_LOAD = '''    selector_rows, selector_names = _load_selector_rows(
        selector_file, trade_date, expected_sha256=selector_identity["sha256"]
    )
'''
DATASET = '''        dataset = ds.dataset(str(path), format="parquet")
        current = dataset.to_table(
            columns=_SELECTOR_CURRENT_COLUMNS,
            filter=ds.field("trade_date") == trade_date,
        ).to_pylist()
        mapping_rows = dataset.to_table(
            columns=_SELECTOR_MAPPING_COLUMNS,
            filter=ds.field("trade_date") == trade_date,
        ).to_pylist()
'''
LOGICAL_DATASET = '''        from ops.review_core_logical_selector import candidate_selector
        dataset = candidate_selector(path, trade_date, expected_sha256=expected_sha256)
        if dataset is None:
            dataset = ds.dataset(str(path), format="parquet")
            current = dataset.to_table(
                columns=_SELECTOR_CURRENT_COLUMNS,
                filter=ds.field("trade_date") == trade_date,
            ).to_pylist()
            mapping_rows = dataset.to_table(
                columns=_SELECTOR_MAPPING_COLUMNS,
                filter=ds.field("trade_date") == trade_date,
            ).to_pylist()
        else:
            columns = list(dict.fromkeys(_SELECTOR_CURRENT_COLUMNS + _SELECTOR_MAPPING_COLUMNS))
            exact = dataset.exact(columns)
            current = exact.select(_SELECTOR_CURRENT_COLUMNS).to_pylist()
            mapping_rows = exact.select(_SELECTOR_MAPPING_COLUMNS).to_pylist()
'''
SIGNATURE = 'def _load_selector_rows(path: Path, trade_date: str) -> tuple[list[dict[str, Any]], dict[str, str]]:'
LOGICAL_SIGNATURE = '''def _load_selector_rows(path: Path, trade_date: str, *, expected_sha256: str | None = None) -> tuple[list[dict[str, Any]], dict[str, str]]:'''
PROOF = '''    if proof_ok:
        metadata.setdefault("pit_safe", True)
        metadata.setdefault("signal", "SELECTOR_READY")
'''
LOGICAL_PROOF = '''    from ops.review_core_logical_selector import candidate_selector
    logical = candidate_selector(path, target, expected_sha256=actual)
    if logical is not None and not logical.pit_certified:
        metadata["pit_safe"] = False
    if proof_ok:
        if logical is None:
            metadata.setdefault("pit_safe", True)
        metadata.setdefault("signal", "SELECTOR_READY")
'''


def apply_overlay(name, raw):
    if hashlib.sha256(raw).hexdigest() != BASE[name]:
        raise ValueError(f'REVIEW_CORE_BASE_SHA_MISMATCH:{name}')
    edits = {
        'macos_daily.py': [(GATE_READ, GATE_DIAGNOSTIC), (EXACT_READ, EXACT_LOGICAL_READ)],
        'review_pipeline.py': [(SIGNATURE, LOGICAL_SIGNATURE), (DATASET, LOGICAL_DATASET),
                               (PIPELINE_LOAD, PIPELINE_LOGICAL_LOAD), (PROOF, LOGICAL_PROOF)],
    }
    source = raw.decode()
    for before, after in edits[name]:
        if source.count(before) != 1:
            raise ValueError(f'REVIEW_CORE_OVERLAY_SITE_MISMATCH:{name}')
        source = source.replace(before, after, 1)
    compile(source, name, 'exec')
    return source.encode()


def prepare(original_package, output):
    """Write changed files only. The caller owns assembling the role copy."""
    if not output.is_absolute() or output.exists() or output.is_symlink() or output.parent.resolve() != output.parent:
        raise ValueError('REVIEW_CORE_NEW_CANDIDATE_OUTPUT_REQUIRED')
    files = {name: apply_overlay(name, (original_package / name).read_bytes()) for name in BASE}
    output.mkdir(mode=0o700)
    io = SafeRoot(output)
    result = {}
    for name, raw in files.items():
        io.write_bytes(name, raw, require_absent=True)
        result[name] = dict(baseline_sha256=BASE[name], sha256=hashlib.sha256(raw).hexdigest())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-package', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.original_package, args.output), sort_keys=True))


if __name__ == '__main__':
    main()
