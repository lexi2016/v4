"""Safe shared live acquisition CLI + orchestration entry (DS2C).

Deterministic entry point over the DS2B/DS2C shared core: safe codes parsing,
fixed Python resolution and a fixed four-option CLI. The registry is fixed —
a Futu runner delegating to the injectable ``futu_collector`` plus explicit
non-executable PyTDX/QMT placeholders; ``run_source_priority`` then
``persist_stage_result`` run exactly once. There is no arbitrary source
path, no ``--python`` / ``--store-root`` / source-path option, no shell and
no V3 runtime dependency. ``main`` returns a JSON-able dict and converts all
argument/input/validation/store failures into ``{ok: false, error: ...}``
without tracebacks.
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

# Direct-script bootstrap: when executed by absolute path from a cwd outside
# the project, sys.path[0] is the scripts/ dir, so the v3_shared_data project
# root is derived from this file's location and made importable. Inserted only
# when absent; `python -m scripts.acquire_stage_raw` and imports are unchanged.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from shared_data.store import StoreError

from scripts.live_acquisition.contracts import StageSourceResult
from scripts.live_acquisition.futu_bridge import collect_futu_minute
from scripts.live_acquisition.orchestrator import persist_stage_result, run_source_priority

_CODE_RE = re.compile(r"^(SH|SZ)\.\d{6}$")

_FUTU_PYTHON_ENV = "V3_SHARED_FUTU_PYTHON"
_STORE_ROOT_ENV = "V3_SHARED_DATA_STORE_ROOT"
_DEFAULT_FUTU_PYTHON = Path(r"C:\Python314\python.exe")

# Trusted store default: project v3_shared_data/.runtime/data, resolved from
# this script's location. Overridable only via V3_SHARED_DATA_STORE_ROOT.
_DEFAULT_STORE_ROOT = Path(__file__).resolve().parent.parent / ".runtime" / "data"

# Explicit non-executable placeholders: these results are never produced by
# running anything; they exist only so fallback order is observable.
_PYTDX_PLACEHOLDER = StageSourceResult(
    source_id="pytdx",
    display_name="PyTDX",
    status="DATA_BLOCKED",
    fidelity="PYTDX_NOT_IMPLEMENTED",
    rows=[],
    error="PyTDX 采集尚未在共享核心实现",
    cannot_confirm=["PyTDX 采集尚未在共享核心实现"],
)
_QMT_PLACEHOLDER = StageSourceResult(
    source_id="qmt_tdxqt",
    display_name="QMT/TDXQT",
    status="DATA_BLOCKED",
    fidelity="QMT_TDXQT_NOT_IMPLEMENTED",
    rows=[],
    error="QMT/TDXQT 采集尚未在共享核心实现",
    cannot_confirm=["QMT/TDXQT 采集尚未在共享核心实现"],
)


def parse_codes_json(text: str) -> list[str]:
    """Parse a JSON array of code strings into normalized unique SH./SZ. codes.

    Accepts only a JSON array of strings; normalizes uppercase, preserves
    first order and rejects duplicates, empty, malformed and non-string
    entries. A path or any non-array JSON value is never accepted.
    """
    if not isinstance(text, str):
        raise ValueError("codes input must be a JSON array of code strings")
    try:
        value = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"codes input 不是合法 JSON: {exc}") from exc
    if not isinstance(value, list):
        raise ValueError("codes input 必须是 JSON 字符串数组")
    if not value:
        raise ValueError("codes 数组不能为空")
    codes: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"codes 条目必须是字符串: {item!r}")
        code = item.strip().upper()
        if not _CODE_RE.fullmatch(code):
            raise ValueError(f"非法股票代码 {code!r}; 期望 SH.###### 或 SZ.######")
        if code in seen:
            raise ValueError(f"重复股票代码 {code!r}")
        seen.add(code)
        codes.append(code)
    return codes


def resolve_futu_python(env: dict[str, str] | None = None) -> Path:
    """Resolve the Futu bridge Python interpreter.

    Uses ``V3_SHARED_FUTU_PYTHON`` when set (non-empty), otherwise the fixed
    ``C:\\Python314\\python.exe``. The returned Path is validated as an
    existing file; invalid values fail closed with ValueError.
    """
    env = os.environ if env is None else env
    raw = str(env.get(_FUTU_PYTHON_ENV, "") or "").strip()
    path = _DEFAULT_FUTU_PYTHON if not raw else Path(raw)
    if not path.is_file():
        raise ValueError(f"futu python 不是文件: {path}")
    return path


def run_acquisition(
    store_root: Path | str,
    trade_date: str,
    stage_id: str,
    codes: list[str],
    python_path: Path | str,
    dry_run: bool = False,
    futu_collector: Callable[..., StageSourceResult] = collect_futu_minute,
) -> dict[str, Any]:
    """Run the fixed source registry once and persist the selected result once.

    Returns the selected source/status, all called results in call order and
    the persistence evidence (safety flags stay store-owned false). The Futu
    runner delegates to ``futu_collector`` with the real ``subprocess.run`` as
    ``process_runner``; PyTDX/QMT are explicit non-executable placeholders.
    """
    python_path = Path(python_path)

    def _futu() -> StageSourceResult:
        return futu_collector(python_path, trade_date, stage_id, codes,
                              process_runner=subprocess.run)

    runners = {
        "futu": _futu,
        "pytdx": lambda: _PYTDX_PLACEHOLDER,
        "qmt_tdxqt": lambda: _QMT_PLACEHOLDER,
    }
    selected, results = run_source_priority(runners)
    persistence = persist_stage_result(store_root, trade_date, stage_id, selected,
                                       dry_run=dry_run)
    return {
        "selected_source_id": selected.source_id,
        "selected_status": selected.status,
        "selected_display_name": selected.display_name,
        "results": results,
        "persistence": persistence,
    }


def _parse_args(argv: list[str]) -> dict[str, Any]:
    """Fixed four-option parser; raises ValueError with a clean message."""
    args: dict[str, Any] = {
        "trade_date": None,
        "stage_id": None,
        "codes_json": None,
        "dry_run": False,
    }
    value_options = {
        "--trade-date": "trade_date",
        "--stage-id": "stage_id",
        "--codes-json": "codes_json",
    }
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--dry-run":
            args["dry_run"] = True
            index += 1
            continue
        key = value_options.get(token)
        if key is None:
            raise ValueError(f"未知选项或参数 {token!r}")
        if index + 1 >= len(argv):
            raise ValueError(f"选项 {token} 缺少值")
        args[key] = argv[index + 1]
        index += 2
    missing = [option for option, key in value_options.items() if args[key] is None]
    if missing:
        raise ValueError(f"缺少必需选项: {', '.join(missing)}")
    return args


def main(argv: list[str], *, futu_collector: Callable[..., StageSourceResult] = collect_futu_minute,
         env: dict[str, str] | None = None) -> dict[str, Any]:
    """Run the acquisition CLI and return a JSON-able result dict.

    Accepts only ``--trade-date`` / ``--stage-id`` / ``--codes-json`` /
    ``--dry-run``. The store root comes only from the trusted
    ``V3_SHARED_DATA_STORE_ROOT`` env or the fixed service default; python
    only from ``resolve_futu_python``. Argument/input/validation/store
    failures become ``{ok: false, error: ...}`` without tracebacks.
    """
    env = os.environ if env is None else env
    try:
        args = _parse_args(argv)
        codes = parse_codes_json(args["codes_json"])
        python_path = resolve_futu_python(env=env)
        raw_store_root = str(env.get(_STORE_ROOT_ENV, "") or "").strip()
        store_root = Path(raw_store_root) if raw_store_root else _DEFAULT_STORE_ROOT
        acquisition = run_acquisition(
            store_root,
            args["trade_date"],
            args["stage_id"],
            codes,
            python_path,
            dry_run=bool(args["dry_run"]),
            futu_collector=futu_collector,
        )
        return {"ok": True, "acquisition": acquisition}
    except (ValueError, StoreError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def _serializable(outcome: dict[str, Any]) -> dict[str, Any]:
    """JSON view of main's outcome: dataclass results become plain dicts."""
    if not outcome.get("ok"):
        return outcome
    acquisition = dict(outcome["acquisition"])
    acquisition["results"] = [dataclasses.asdict(result) for result in acquisition["results"]]
    return {"ok": True, "acquisition": acquisition}


if __name__ == "__main__":
    result = main(sys.argv[1:])
    print(json.dumps(_serializable(result), ensure_ascii=False))
    sys.exit(0 if result.get("ok") else 1)
