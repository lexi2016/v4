"""Run only the three-channel synthetic regression files from an isolated app.

The scoped namespace helper avoids unrelated package-initializer imports missing
from the handoff closure. It supplies no implementation or runtime data. Complete
native Mac repository acceptance must also use its normal import environment.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root', type=Path, required=True)
    parser.add_argument('--junitxml', type=Path)
    args = parser.parse_args()
    app = args.app_root.resolve(strict=True)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.dont_write_bytecode = True
    os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    os.chdir(app)
    for path in reversed((app, app/'upstreams', app/'tests')):
        sys.path.insert(0, str(path))
    import r3_scoped_loader
    if Path(r3_scoped_loader.__file__).resolve() != app/'tests/r3_scoped_loader.py':
        raise RuntimeError('SCOPED_LOADER_SOURCE_MISMATCH')
    r3_scoped_loader.install()
    for name in ('v4.manager_research', 'infrastructure.scheduling'):
        parent, child = name.rsplit('.', 1)
        setattr(sys.modules[parent], child, sys.modules[name])
    import pytest
    command = ['-q','-p','no:cacheprovider','--tb=short',
        'tests/test_manager_announcement_handoff_20261009.py',
        'tests/test_manager_us_mapping_three_channel_20261009.py',
        'tests/test_manager_three_channel_hk_reader.py']
    if args.junitxml: command += ['--junitxml', str(args.junitxml.resolve())]
    return pytest.main(command)


if __name__ == '__main__':
    raise SystemExit(main())
