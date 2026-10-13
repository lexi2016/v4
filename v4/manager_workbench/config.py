"""Injected roots and pinned owner bindings; no implicit current/latest fallback."""
from __future__ import annotations
from pathlib import Path
from pydantic import Field, field_validator, model_validator
from .contracts import StrictModel


class WorkbenchConfig(StrictModel):
    state_root: Path
    manager_root: Path | None = None
    shared_root: Path | None = None
    stage_root: Path | None = None
    dynamic_source_bindings: bool = False
    # New exclusive capture is opt-in; roots/token are operator-only, never HTTP.
    capture_enabled: bool = False
    capture_root: Path | None = None
    capture_lease_root: Path | None = None
    capture_lease_token: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$", repr=False)
    capture_poll_seconds: int = Field(default=60, ge=5, le=3600)
    us_root: Path | None = None
    relation_root: Path | None = None
    relation_evidence_relative: str = "v4/manager_research/us_mapping_relation_evidence_20261011.json"
    relation_review_relative: str = "v4/manager_research/us_mapping_relation_evidence_review_20261011.json"
    us_calendar_path: Path | None = None
    us_calendar_sha256: str | None = None
    legacy_root: Path | None = None
    # Exact-date bindings are resolved by the operator, never accepted over HTTP.
    source_bindings: dict[str, dict] = Field(default_factory=dict)
    rules_version: str = "POSITIVE_OPERATING_RESEARCH_V1"
    model: str = "gpt-6-luna"
    announcement_reasoning_effort: str = "max"
    prompt_version: str = "MWB_ANNOUNCEMENT_READER_REVIEWER_V3_20261013"
    codex_binary: Path | None = None
    cli_isolation_attested: bool = False
    model_timeout_seconds: int = Field(default=900, ge=1, le=3600)
    workers: int = Field(default=3, ge=1, le=5)

    @field_validator("state_root", "manager_root", "shared_root", "stage_root", "legacy_root", "codex_binary", "us_calendar_path", "us_root", "relation_root", "capture_root", "capture_lease_root")
    @classmethod
    def root_check(cls, value):
        if value is not None and (not value.is_absolute() or ".." in value.parts or value.is_symlink()):
            raise ValueError("CONFIG_PATH_INVALID")
        return value

    @model_validator(mode="after")
    def separate_writes(self):
        for root in (self.manager_root, self.shared_root, self.stage_root):
            if root and (self.state_root == root or self.state_root.is_relative_to(root) or root.is_relative_to(self.state_root)):
                raise ValueError("DERIVED_STATE_MUST_BE_SEPARATE_FROM_SOURCE_ROOT")
        if self.capture_enabled and not (self.capture_root and self.capture_lease_root and self.capture_lease_token):
            raise ValueError("CAPTURE_EXPLICIT_ROOTS_AND_GRANTED_TOKEN_REQUIRED")
        for capture in (self.capture_root, self.capture_lease_root):
            for source in (self.manager_root,self.shared_root,self.stage_root,self.us_root,self.relation_root):
                if capture and source and (capture==source or capture.is_relative_to(source) or source.is_relative_to(capture)):
                    raise ValueError("CAPTURE_ROOT_MUST_NOT_OVERLAP_EXISTING_OWNER")
        if self.capture_root and (self.capture_root==self.state_root or self.capture_root.is_relative_to(self.state_root) or self.state_root.is_relative_to(self.capture_root)):
            raise ValueError("CAPTURE_MATERIAL_AND_DERIVED_STATE_MUST_BE_SEPARATE")
        return self


def load_config(path: str | Path) -> WorkbenchConfig:
    import json
    return WorkbenchConfig.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
