"""Explicit, sanitized deployment inputs. Never creates credentials or app service."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WorkbenchConfig:
    state_root: Path
    rules_version: str
    model: str
    prompt_version: str
    legacy_root: Path | None = None
    codex_binary: str = "codex"
    cli_isolation_attested: bool = False
    workers: int = 2
    reasoning_effort: str = "max"

    def __post_init__(self) -> None:
        root = Path(self.state_root)
        if not root.is_absolute() or ".." in root.parts:
            raise ValueError("STATE_ROOT_UNSAFE")
        if self.legacy_root is not None:
            legacy = Path(self.legacy_root)
            if not legacy.is_absolute() or ".." in legacy.parts or legacy == root:
                raise ValueError("LEGACY_ROOT_UNSAFE")
        if not self.rules_version or not self.prompt_version or not self.model:
            raise ValueError("CONFIG_VERSION_MISSING")
        if self.reasoning_effort not in ("high", "xhigh", "max"):
            raise ValueError("REASONING_EFFORT_INVALID")
        if not 1 <= self.workers <= 8:
            raise ValueError("WORKERS_INVALID")
        if self.codex_binary != "codex" and not Path(self.codex_binary).is_absolute():
            raise ValueError("CODEX_BINARY_MUST_BE_ABSOLUTE")


def load_config(path: str | Path) -> WorkbenchConfig:
    """Reject keys suggesting secret material rather than silently persisting it."""
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("CONFIG_INVALID")
    allowed = {"state_root", "rules_version", "model", "prompt_version", "legacy_root", "codex_binary", "cli_isolation_attested", "workers", "reasoning_effort"}
    if set(obj) - allowed:
        raise ValueError("CONFIG_UNRECOGNIZED_KEYS")
    if type(obj.get("cli_isolation_attested", False)) is not bool:
        raise ValueError("ATTESTATION_INVALID")
    if not isinstance(obj.get("workers", 2), int) or isinstance(obj.get("workers", 2), bool):
        raise ValueError("WORKERS_INVALID")
    return WorkbenchConfig(
        state_root=Path(obj["state_root"]), rules_version=obj["rules_version"],
        model=obj["model"], prompt_version=obj["prompt_version"],
        legacy_root=Path(obj["legacy_root"]) if obj.get("legacy_root") else None,
        codex_binary=obj.get("codex_binary", "codex"),
        cli_isolation_attested=obj.get("cli_isolation_attested", False),
        workers=obj.get("workers", 2), reasoning_effort=obj.get("reasoning_effort", "max"),
    )
