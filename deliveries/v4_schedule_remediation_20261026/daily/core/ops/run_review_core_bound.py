"""Bind the existing daily Review Core entrypoint to explicit runtime roots.

Default: import-only check, with no daily run and no receipt publication.
Run mode delegates to the unchanged review_core.macos_daily module. This is
an entrypoint adapter, not a producer, scheduler, release manager or approval.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

_BOUND_OPTIONS = (
    "--source-root", "--release-root", "--shared-package-root",
    "--working-directory", "--python-path",
)
_PROBE = r'''
import hashlib, importlib, json, os, pathlib, sys
source, shared = map(pathlib.Path, sys.argv[1:3])
module = importlib.import_module("review_core.macos_daily")
public = importlib.import_module("shared_data.public_fupan")
expected = source / "review_core" / "macos_daily.py"
expected_public = shared / "shared_data" / "public_fupan.py"
if pathlib.Path(module.__file__).resolve() != expected:
    raise SystemExit("REVIEW_IMPORT_ORIGIN_MISMATCH")
if pathlib.Path(public.__file__).resolve() != expected_public:
    raise SystemExit("SHARED_IMPORT_ORIGIN_MISMATCH")
if not callable(getattr(module, "main", None)) or not callable(getattr(public, "read_public_fupan", None)):
    raise SystemExit("ENTRYPOINT_CONTRACT_MISSING")
print(json.dumps({
    "status": "IMPORT_BOUND_ONLY", "business_executed": False,
    "module_file": str(expected),
    "module_sha256": hashlib.sha256(expected.read_bytes()).hexdigest(),
    "shared_module_file": str(expected_public),
    "shared_module_sha256": hashlib.sha256(expected_public.read_bytes()).hexdigest(),
    "python": sys.executable, "python_version": sys.version.split()[0],
    "pythonpath_entries": os.environ["PYTHONPATH"].split(os.pathsep),
    "cwd": str(pathlib.Path.cwd()),
    "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
}, ensure_ascii=False, sort_keys=True))
'''


def _directory(value: str, label: str) -> Path:
    path = Path(value)
    if not value or not path.is_absolute():
        raise ValueError(f"ABSOLUTE_PATH_REQUIRED:{label}")
    if os.pathsep in value:
        raise ValueError(f"PATH_SEPARATOR_IN_ROOT:{label}")
    if not path.is_dir():
        raise ValueError(f"DIRECTORY_MISSING:{label}")
    if path.resolve(strict=True) != path:
        raise ValueError(f"NONCANONICAL_ROOT:{label}")
    return path


def _source_file(path: Path) -> None:
    if not path.is_file() or path.is_symlink() or path.resolve(strict=True) != path:
        raise ValueError(f"SOURCE_MISSING_OR_SYMLINK:{path}")


def _business_args(values: list[str]) -> list[str]:
    args = values[1:] if values[:1] == ["--"] else values
    for value in args:
        name = value.split("=", 1)[0]
        # The legacy parser allows abbreviated options. Reject abbreviations
        # too, otherwise --source-r could override the wrapper's source root.
        if name.startswith("--") and any(option.startswith(name) for option in _BOUND_OPTIONS):
            raise ValueError(f"BOUND_ARGUMENT_OVERRIDE:{name}")
    return args


def _natural_wait(business: list[str], *, now: datetime | None = None) -> dict | None:
    """Gate implicit launchd ticks before any runtime probe or receipt write.

    Explicit dates and manual/import checks retain the existing full validation
    path.  The downstream parser accepts abbreviations, so a possible --date
    abbreviation also opts out of this cheap gate.
    """
    if any(value in ("--help", "-h") or
           (value.startswith("--") and "--date".startswith(value.split("=", 1)[0])) or
           value.startswith("--date=") for value in business):
        return None
    if any(value.startswith("--") and value.split("=", 1)[0] != "--origin" and
           "--origin".startswith(value.split("=", 1)[0]) for value in business):
        return None
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--origin")
    known, _ = parser.parse_known_args(business)
    if known.origin not in (None, "natural_scheduler"):
        return None
    clock = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    clock = clock.replace(tzinfo=ZoneInfo("Asia/Shanghai")) if clock.tzinfo is None else clock.astimezone(ZoneInfo("Asia/Shanghai"))
    if (clock.hour, clock.minute) >= (20, 25):
        return None
    weekend = clock.weekday() >= 5
    return {
        "status": "NOOP_SKIP" if weekend else "WAITING_NOT_BEFORE_2025",
        "reason": "NON_TRADING_DAY" if weekend else "IMPLICIT_LAUNCHD_NOT_BEFORE_2025_SHANGHAI",
        "trade_date": clock.strftime("%Y%m%d"),
        "origin": "natural_scheduler", "business_executed": False,
        "runtime_probe_executed": False, "receipt_published": False,
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--python", required=True)
    parser.add_argument("--release-root", required=True)
    parser.add_argument("--shared-package-root", required=True)
    parser.add_argument("--working-directory", required=True)
    parser.add_argument("--mode", choices=("check-import", "run"), default="check-import")
    parser.add_argument("review_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        business = _business_args(args.review_args)
        if args.mode == "run":
            waiting = _natural_wait(business)
            if waiting is not None:
                print(json.dumps(waiting, ensure_ascii=False, sort_keys=True))
                return 0
        release = _directory(args.release_root, "release-root")
        shared = _directory(args.shared_package_root, "shared-package-root")
        cwd = _directory(args.working_directory, "working-directory")
        # app/review_core is the existing runtime_contract layout, not a
        # search of ancestors, a latest-release fallback or a guessed root.
        app = _directory(str(release / "app"), "release-app")
        source = _directory(str(app / "review_core"), "review-core")
        for leaf in (source / "__init__.py", source / "macos_daily.py",
                     shared / "shared_data/__init__.py", shared / "shared_data/public_fupan.py"):
            _source_file(leaf)
        python = Path(args.python)
        if not python.is_absolute():
            raise ValueError("ABSOLUTE_PATH_REQUIRED:python")
        # A venv interpreter is commonly a symlink; unlike source/data roots,
        # that is allowed and its observed executable is reported by the probe.
        if not python.is_file() or not os.access(python, os.X_OK):
            raise ValueError("EXECUTABLE_MISSING:python")
        if args.mode == "check-import" and business:
            raise ValueError("CHECK_IMPORT_DOES_NOT_ACCEPT_BUSINESS_ARGS")
        environment = dict(os.environ)
        for name in ("PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE", "PYTHONINSPECT"):
            environment.pop(name, None)
        environment.update({
            "PYTHONPATH": os.pathsep.join((str(app), str(shared))),
            "PYTHONNOUSERSITE": "1", "PYTHONSAFEPATH": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "REVIEW_CORE_SHARED_PACKAGE_ROOT": str(shared),
            "REVIEW_CORE_RELEASE_ROOT": str(release),
        })
        probe = subprocess.run(
            [str(python), "-B", "-P", "-c", _PROBE, str(app), str(shared)],
            cwd=cwd, env=environment, text=True, capture_output=True,
            timeout=15, check=False,
        )
        if probe.returncode:
            raise ValueError("IMPORT_BINDING_FAILED:" + probe.stderr.strip())
        if args.mode == "check-import":
            sys.stdout.write(probe.stdout)
            return 0
        command = [str(python), "-B", "-P", "-m", "review_core.macos_daily",
                   "--source-root", str(source), "--release-root", str(release),
                   "--shared-package-root", str(shared), "--working-directory", str(cwd),
                   "--python-path", str(python), *business]
        os.chdir(cwd)
        os.execve(python, command, environment)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"REVIEW_BOUND_STARTUP_REJECTED:{error}", file=sys.stderr)
        return 2
    return 2  # execve does not return on success.


if __name__ == "__main__":
    raise SystemExit(main())
