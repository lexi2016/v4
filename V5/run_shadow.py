"""Source-only entry point for the V5 source-bundle distribution.

Usage: python -B run_shadow.py <CLI arguments>
       python -B run_shadow.py web --output-root <root> --port <port>
Run this file directly; a timestamp cache is never used for the main script.
"""
from pathlib import Path
import sys
import tempfile


def main():
    with tempfile.TemporaryDirectory(prefix='v5-source-import-') as cache:
        sys.pycache_prefix = cache
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
        args = sys.argv[1:]
        if args and args[0] == 'web':
            from v5_shadow.web import main as entry
            return entry(args[1:])
        from v5_shadow.cli import main as entry
        return entry(args)


if __name__ == '__main__':
    raise SystemExit(main())
