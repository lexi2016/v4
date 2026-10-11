#!/usr/bin/env bash
set -euo pipefail
PY=${1:?Usage: bash run_repro.sh /absolute/path/to/existing/python}
case "$PY" in /*) ;; *) echo 'An existing absolute Python interpreter path is required' >&2; exit 2;; esac
BUNDLE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
WORK=$(mktemp -d "${TMPDIR:-/tmp}/m05-r8-cloud-XXXXXX")
WORK=$(cd -- "$WORK" && pwd -P)
export BUNDLE WORK
"$PY" -B - <<'PY'
import ast, hashlib, os, sys, zipfile
from pathlib import Path, PurePosixPath
b=Path(os.environ['BUNDLE']); w=Path(os.environ['WORK']); target=w/'source'; target.mkdir()
inputs={
 'V5_M05_SOURCE_REVIEW_20261010.zip':'241f56dbff2bd91514eaa976239007ca53f73d48cfce20bf173fbfadfd6a4d27',
 'V5_M05_R8_STRICT_STORE_BINDING_CANDIDATE_20261011.zip':'61164b69960de0741dbaa157e4704cff431538a00eadf99550b0eaa934edfab2',
}
for name, expected in inputs.items():
 data=(b/name).read_bytes(); actual=hashlib.sha256(data).hexdigest()
 assert actual==expected, (name,actual)
 print('INPUT_VERIFIED',name,len(data),actual)
with zipfile.ZipFile(b/'V5_M05_SOURCE_REVIEW_20261010.zip') as archive:
 assert archive.testzip() is None
 assert all(not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts for n in archive.namelist())
 archive.extractall(target)
after={
 'V5/src/v5_shadow/a_preselection_daily.py':'485950f042ee2e0b0c9e01a9fcdb686d355b7bdfcffffe2985012b85b1da7669',
 'V5/tests/test_m05_daily_boundary.py':'347bfd706c79b46fed9f7c33b6fb0cf8e5ccf5905ec28921f7c273802a4f2cb1',
}
with zipfile.ZipFile(b/'V5_M05_R8_STRICT_STORE_BINDING_CANDIDATE_20261011.zip') as archive:
 assert archive.testzip() is None
 for name, expected in after.items():
  data=archive.read(name); assert hashlib.sha256(data).hexdigest()==expected
  ast.parse(data); (target/name).write_bytes(data)
  print('AFTER_VERIFIED',name,expected)
print('INTERPRETER',sys.executable,sys.version.replace('\n',' '))
print('ISOLATED_SOURCE',target)
PY
export PYTHONPATH="$WORK/source/V5/src"
echo "Running isolated real-store rejection reproduction; expected result is BUG_REPRODUCED, not product PASS."
set +e
"$PY" -B "$BUNDLE/M05_R8_STRICT_GATE_REPRO_20261011.py" "$WORK/source" >"$WORK/repro.stdout.log" 2>"$WORK/repro.stderr.log"
STATUS=$?
set -e
cat "$WORK/repro.stdout.log"
cat "$WORK/repro.stderr.log" >&2
printf 'REPRO_EXIT=%s\nLOG_DIRECTORY=%s\n' "$STATUS" "$WORK"
exit "$STATUS"
