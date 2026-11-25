"""Single-directory configuration and minimal real disk-space guard."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil


class InsufficientDiskSpaceError(RuntimeError):
    """Raised only when actual OS free disk space drops below the safety floor."""


@dataclass(frozen=True)
class V4Config:
    base_dir: Path
    data_dir: Path
    db_path: Path
    bars_dir: Path
    logs_dir: Path
    min_free_gib: float = 30.0
    api_host: str = "127.0.0.1"
    api_port: int = 8873
    log_retention_days: int = 30

    @classmethod
    def from_env(cls, base_dir: str | Path | None = None) -> "V4Config":
        root = Path(base_dir or os.environ.get("V4_CORE_HOME", Path.cwd() / "v4_data")).resolve()
        data_dir = root / "data"
        return cls(
            base_dir=root,
            data_dir=data_dir,
            db_path=data_dir / "v4_state.sqlite3",
            bars_dir=data_dir / "bars",
            logs_dir=root / "logs",
            min_free_gib=float(os.environ.get("V4_MIN_FREE_GIB", "30.0")),
            api_host=os.environ.get("V4_API_HOST", "127.0.0.1"),
            api_port=int(os.environ.get("V4_API_PORT", "8873")),
            log_retention_days=int(os.environ.get("V4_LOG_RETENTION_DAYS", "30")),
        )

    def ensure_dirs(self) -> None:
        for path in (self.base_dir, self.data_dir, self.bars_dir, self.logs_dir):
            path.mkdir(parents=True, exist_ok=True)


def assert_disk_space(path: Path, min_free_gib: float = 30.0) -> float:
    """3-line real OS free space check. Replaces 261 GiB virtual ledgers & 512 MiB claims."""
    target = path if path.exists() else path.parent
    free_gib = shutil.disk_usage(target).free / (1024 ** 3)
    if free_gib < min_free_gib:
        raise InsufficientDiskSpaceError(
            f"Free disk space {free_gib:.2f} GiB < required {min_free_gib:.2f} GiB at {target}"
        )
    return round(free_gib, 2)
