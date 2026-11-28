"""Keep frozen transport verdicts separate from explicitly scoped structural findings."""

from __future__ import annotations

import re

from research.act070a.case_contract import require

STRUCTURAL_STATES = {"STRUCT_PASS_CANDIDATE", "STRUCT_WATCH_ONLY", "STRUCT_VETO_RISK"}
SCOPED_CODE = re.compile(r"[A-Z][A-Z0-9_]{1,79}")


def summarize_validator(verdict: dict, *, veto_scope: str, structural_verdict: str | None = None) -> dict:
    require(isinstance(veto_scope, str) and SCOPED_CODE.fullmatch(veto_scope),
            "MISSING_EXPLICIT_VETO_SCOPE", str(veto_scope))
    accepted, code = verdict.get("accepted"), verdict.get("code")
    require(type(accepted) is bool and isinstance(code, str) and SCOPED_CODE.fullmatch(code),
            "INVALID_FROZEN_VALIDATOR_VERDICT", str(code))
    if not accepted:
        require(structural_verdict is None and code != "ACCEPTED_CANDIDATE_ONLY",
                "STRUCTURAL_VERDICT_REQUIRES_TECHNICAL_PASS", veto_scope)
        return {"technical_status": "FAIL", "technical_fail_code": code, "veto_scope": veto_scope}
    require(code == "ACCEPTED_CANDIDATE_ONLY", "INVALID_FROZEN_VALIDATOR_VERDICT", code)
    result = {"technical_status": "PASS", "veto_scope": veto_scope}
    if structural_verdict is not None:
        require(structural_verdict in STRUCTURAL_STATES, "INVALID_STRUCTURAL_VERDICT", structural_verdict)
        result["structural_verdict"] = structural_verdict
    return result
