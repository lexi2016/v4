"""Test source overlay without copying panels, runtime, or changing frozen app."""
from pathlib import Path
import argparse
import hashlib
import json
import sys
import os
import tempfile
import shutil

HERE = Path(__file__).resolve().parent


def main():
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frozen-app', type=Path, required=True)
    parser.add_argument('--frozen-controller', type=Path, required=True)
    args, extra = parser.parse_known_args()
    records = json.loads((HERE/'PREIMAGE_SHA256.json').read_bytes())
    for name, value in records.items():
        path = args.frozen_controller if name.startswith('cutover/') else args.frozen_app/name
        raw = path.read_bytes()
        if len(raw) != value['bytes'] or hashlib.sha256(raw).hexdigest() != value['sha256']:
            raise SystemExit('FROZEN_PREIMAGE_CONFLICT:'+name)
    # Some existing oracles resolve required siblings through owner.__file__.
    # Assemble only Python source, never a panel/runtime/data mirror. Absolute
    # source identities now describe the actual merged executable test tree.
    with tempfile.TemporaryDirectory(prefix="path-a-source-") as temporary:
        merged = Path(temporary).resolve()
        for source in (args.frozen_app/'ops').rglob('*.py'):
            destination = merged/'ops'/source.relative_to(args.frozen_app/'ops')
            destination.parent.mkdir(exist_ok=True,parents=True)
            shutil.copyfile(source, destination)
        for source in (HERE/'app-overlay/ops').rglob('*.py'):
            destination=merged/'ops'/source.relative_to(HERE/'app-overlay/ops')
            destination.parent.mkdir(exist_ok=True,parents=True)
            shutil.copyfile(source,destination)
        sys.path[:0] = [str(merged), str(args.frozen_app)]
        import pytest
        raise SystemExit(pytest.main(extra or [str(HERE/'tests'), '-q', '-p', 'no:cacheprovider']))


if __name__ == '__main__':
    main()
