"""Type-only services supplied by the original inactive release-builder facade."""
from __future__ import annotations
from typing import Any, Callable, Protocol

class BuilderAPI(Protocol):
    APPROVED_UNTRACKED_CANDIDATE_PATHS: Any
    DEFAULT_DEPENDENCIES: Any
    DIST_RELATIVE_ROOT: Any
    SAFETY_KEYS: Any
    _copy_one: Callable[..., Any]
    _describe_path: Callable[..., Any]
    _describe_scheduler_path_value: Callable[..., Any]
    _entry_for_path: Callable[..., Any]
    _file_summary: Callable[..., Any]
    _git_untracked_paths: Callable[..., Any]
    _is_within: Callable[..., Any]
    _json_dump: Callable[..., Any]
    _load_plist: Callable[..., Any]
    _normalise_relative: Callable[..., Any]
    _plist_environment: Callable[..., Any]
    _probe_dependency_process: Callable[..., Any]
    _resolved: Callable[..., Any]
    _run_git: Callable[..., Any]
    _walk_entries: Callable[..., Any]
    sha256_file: Callable[..., Any]
    utc_now: Callable[..., Any]
