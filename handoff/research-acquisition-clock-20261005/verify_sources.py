"""Read-only all-file SHA guard. Does not apply or roll back changes."""
import hashlib
import json
from pathlib import Path
import sys

if len(sys.argv) != 3 or sys.argv[2] not in {'before', 'after'}:
    raise SystemExit('Usage: verify_sources.py ABSOLUTE_CANDIDATE_ROOT before|after')
root = Path(sys.argv[1])
if not root.is_absolute():
    raise SystemExit('Absolute candidate root required')
changes = json.loads(Path(__file__).with_name('changes.json').read_text())
failed = []
for row in changes:
    path = root / row['path']
    actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else 'MISSING'
    if actual != row[sys.argv[2] + '_sha256']:
        failed.append(row['path'])
if failed:
    raise SystemExit('SHA MISMATCH; do not apply: ' + ', '.join(failed))
print(f'{sys.argv[2]}: {len(changes)}/{len(changes)} exact SHA PASS')
