"""ops.run_review_core_natural_pool_pipeline: pipeline_execution (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _run_pipeline_body(_v4_scope, /, request, *, runner):
    """Invoke the released module once and return a typed adapter envelope."""

    command = _v4_global(_v4_scope, 'build_command')(request)
    environment = _v4_global(_v4_scope, 'build_environment')(request)
    invoke = runner or _v4_global(_v4_scope, 'subprocess').run
    execution = _v4_global(_v4_scope, '_execution_metadata')(request, command, environment)
    try:
        completed = invoke(
            command,
            cwd=_v4_global(_v4_scope, 'str')(request.review_core_package_root),
            env=environment,
            shell=False,
            capture_output=True,
            text=True,
            check=False,
        )
    except _v4_global(_v4_scope, 'Exception') as error:
        envelope = _v4_global(_v4_scope, '_base_envelope')(request)
        envelope["errors"] = [_v4_global(_v4_scope, '_error')(_v4_global(_v4_scope, 'type')(error).__name__, _v4_global(_v4_scope, 'str')(error) or _v4_global(_v4_scope, 'type')(error).__name__)]
        envelope["error"] = envelope["errors"][0]
        envelope["execution"] = execution
        envelope["official_exit_code"] = None
        envelope["exit_code"] = 2
        return envelope

    child_exit_code = _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'getattr')(completed, "returncode", 1))
    official = _v4_global(_v4_scope, '_json_stdout')(_v4_global(_v4_scope, 'getattr')(completed, "stdout", ""))
    if official is None:
        envelope = _v4_global(_v4_scope, '_base_envelope')(request)
        errors: list[dict[str, str]] = []
        if child_exit_code != 0:
            errors.append(_v4_global(_v4_scope, '_error')("OfficialPipelineExit", f"official pool_pipeline exited with code {child_exit_code}"))
        errors.append(_v4_global(_v4_scope, '_error')("OfficialOutputInvalid", "official pool_pipeline did not emit a JSON receipt"))
        envelope["errors"] = errors
        envelope["error"] = errors[0]
        if _v4_global(_v4_scope, 'getattr')(completed, "stderr", ""):
            envelope["stderr"] = _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'getattr')(completed, "stderr"))[-2000:]
        envelope["execution"] = execution
        envelope["official_exit_code"] = child_exit_code
        envelope["exit_code"] = 2
        return envelope

    envelope = _v4_global(_v4_scope, 'validate_official_result')(
        official,
        request,
        official_exit_code=child_exit_code,
        stderr=_v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'getattr')(completed, "stderr", "") or ""),
    )
    envelope["execution"] = execution
    envelope["official_exit_code"] = child_exit_code
    envelope["exit_code"] = 0 if envelope["status"] == "READY" else 2
    return envelope
