import hashlib, json, os
from pathlib import Path
package = Path(os.environ['V4_HANDOFF']).resolve()
target = Path(os.environ['V4_REVIEW_ROOT']).resolve()
manifest = json.loads((package / 'test_source_manifest.json').read_text())
pending = []
for row in manifest['unchanged_support']:
    rel = Path(row['path'])
    if rel.is_absolute() or '..' in rel.parts:
        raise SystemExit('Invalid support path')
    src = package / row['archive_path']
    raw = src.read_bytes()
    if len(raw) != row['bytes'] or hashlib.sha256(raw).hexdigest() != row['sha256']:
        raise SystemExit(f'Support payload mismatch: {rel}')
    dst = target / rel
    if dst.is_symlink() or target not in dst.resolve().parents:
        raise SystemExit(f'Unsafe target: {rel}')
    if dst.exists() and dst.read_bytes() != raw:
        raise SystemExit(f'Existing support differs: {rel}')
    if not dst.exists():
        pending.append((dst, raw))
for dst, raw in pending:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(raw)
print(f'Verified {len(manifest["unchanged_support"])}; added {len(pending)} support files in temporary source only')
