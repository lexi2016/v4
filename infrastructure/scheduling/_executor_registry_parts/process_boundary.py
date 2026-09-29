"""infrastructure.scheduling.executor_registry: process_boundary (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __default_runner_body(_v4_scope, /, command, *, cwd, timeout_seconds, env):
    return _v4_global(_v4_scope, 'subprocess').run(
        command,
        shell=False,
        cwd=cwd,
        env=env,
        timeout=timeout_seconds,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _FixedExecutorRegistry__hk_0_2_runtime_error_body(_v4_scope, /, self, executable):
    """Validate an explicitly selected HK 0.2 interpreter in isolation.

        This probe is deliberately scoped to the HK lane.  A direct scheduler
        or slot invocation may bypass the shell launcher, so ``is_file`` alone
        is not enough: an existing Python 3.14 executable must be rejected
        before any HK producer is started.  The caller records the result as a
        lane-local ``CANNOT_CONFIRM`` degradation and continues sibling work.
        """
    # Production callers must validate the effective default as well:
    # without an explicit argument it would otherwise fall back to the
    # scheduler's Python 3.14 interpreter.  Test doubles that do not
    # provide an explicit runtime retain their command-level seam.
    if self._runner is not _v4_global(_v4_scope, '_default_runner') and not self._hk_0_2_python_explicit:
        return None
    executable = _v4_global(_v4_scope, 'Path')(executable) if executable is not None else self.hk_0_2_python_executable
    if not executable.is_file() or not _v4_global(_v4_scope, 'os').access(executable, _v4_global(_v4_scope, 'os').X_OK):
        return f"HK 0.2 Python runtime missing or not executable: {executable}"
    try:
        completed = _v4_global(_v4_scope, 'subprocess').run(
            [
                _v4_global(_v4_scope, 'str')(executable),
                "-c",
                "import sys; print('.'.join(map(str, sys.version_info[:3])))",
            ],
            shell=False,
            cwd=self.repo_root if self.repo_root and self.repo_root.is_dir() else None,
            timeout=_v4_global(_v4_scope, 'max')(1, _v4_global(_v4_scope, 'min')(self.timeout_seconds, 15)),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except _v4_global(_v4_scope, 'subprocess').TimeoutExpired:
        return f"HK 0.2 Python version probe timed out: {executable}"
    except _v4_global(_v4_scope, 'OSError') as error:
        return f"HK 0.2 Python version probe failed: {_v4_global(_v4_scope, 'type')(error).__name__}: {executable}"
    version = _v4_global(_v4_scope, 'str')(completed.stdout or "").strip()
    if completed.returncode != 0:
        return f"HK 0.2 Python version probe exited {completed.returncode}: {executable}"
    if version != _v4_global(_v4_scope, '_HK_0_2_REQUIRED_PYTHON_VERSION'):
        return (
            f"HK 0.2 requires Python {_v4_global(_v4_scope, '_HK_0_2_REQUIRED_PYTHON_VERSION')}, "
            f"got {version or 'unknown'}: {executable}"
        )
    return None


def _FixedExecutorRegistry__run_body(_v4_scope, /, self, module, arguments, *, cwd, env, python_executable, timeout_seconds):
    executable = _v4_global(_v4_scope, 'str')(python_executable or _v4_global(_v4_scope, 'sys').executable)
    effective_timeout = self.timeout_seconds if timeout_seconds is None else _v4_global(_v4_scope, 'int')(timeout_seconds)
    command = [executable, "-m", module, *arguments]
    try:
        completed = self._runner(
            command,
            cwd=self.repo_root if cwd is None else cwd,
            timeout_seconds=effective_timeout,
            env=env,
        )
    except _v4_global(_v4_scope, 'subprocess').TimeoutExpired as error:
        return {
            "status": "TIMEOUT",
            "workload_id": "",
            "modules": [module],
            "exit_code": _v4_global(_v4_scope, '_TIMEOUT_EXIT_CODE'),
            "stdout": _v4_global(_v4_scope, '_bounded')(_v4_global(_v4_scope, 'str')(error.stdout or ""), _v4_global(_v4_scope, '_STDOUT_LIMIT')),
            "stderr": _v4_global(_v4_scope, '_bounded')(
                _v4_global(_v4_scope, 'str')(error.stderr or "") or "subprocess timed out", _v4_global(_v4_scope, '_STDERR_LIMIT')
            ),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    return {
        "status": "SUCCEEDED" if completed.returncode == 0 else "FAILED",
        "workload_id": "",
        "modules": [module],
        "exit_code": _v4_global(_v4_scope, 'int')(completed.returncode),
        "stdout": _v4_global(_v4_scope, '_bounded')(completed.stdout, _v4_global(_v4_scope, '_STDOUT_LIMIT')),
        "stderr": _v4_global(_v4_scope, '_bounded')(completed.stderr, _v4_global(_v4_scope, '_STDERR_LIMIT')),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
