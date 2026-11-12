from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path


RELEASE_ID = "20260827T060000Z-v35-main-scheduler-daemon"
STABLE_RUNTIME = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/"
    "20260825T172000Z-v35-a3-stage-authority-binding-v5/runtime"
)
STABLE_HK_PYTHON = STABLE_RUNTIME / "venvs/v4-hk02/bin/python"
SHARED_PACKAGE_ROOT = Path("/Users/lexi/Desktop/学习/v3_shared_data")


def _app_root() -> Path:
    return Path(__file__).parents[1].resolve()


def _hk_wrapper() -> Path:
    return _app_root() / "ops/launch_hk_0_2_python_nosite.sh"


def _hk_env(**overrides: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "V4_RUNTIME_ROOT": str(STABLE_RUNTIME),
            "V4_HK_0_2_REAL_PYTHON": str(STABLE_HK_PYTHON),
            "V4_SHARED_PACKAGE_ROOT": str(SHARED_PACKAGE_ROOT),
            "PYTHONPATH": "",
            "PYTHONNOUSERSITE": "1",
        }
    )
    env.update(overrides)
    return env


def test_hk_wrapper_imports_runtime_packages_with_explicit_site_path() -> None:
    completed = subprocess.run(
        [
            str(_hk_wrapper()),
            "-c",
            (
                "import sys, numpy, pandas, sklearn, shared_data.hk_0_2; "
                "print('.'.join(map(str, sys.version_info[:3])))"
            ),
        ],
        env=_hk_env(),
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "3.13.12"


def test_hk_wrapper_fails_closed_when_explicit_site_path_is_missing(tmp_path: Path) -> None:
    missing_runtime = tmp_path / "runtime"
    completed = subprocess.run(
        [str(_hk_wrapper()), "-c", "print('must not run')"],
        env=_hk_env(
            V4_RUNTIME_ROOT=str(missing_runtime),
            V4_HK_0_2_REAL_PYTHON=sys.executable,
            V4_SHARED_PACKAGE_ROOT=str(tmp_path / "shared"),
        ),
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    assert completed.returncode != 0
    assert "site-packages" in completed.stderr


def test_hk_wrapper_forwards_python_arguments() -> None:
    completed = subprocess.run(
        [
            str(_hk_wrapper()),
            "-c",
            "import sys; print(sys.argv[1:])",
            "forwarded-argument",
        ],
        env=_hk_env(),
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    assert completed.returncode == 0, completed.stderr
    assert "forwarded-argument" in completed.stdout


def test_scheduler_launcher_uses_nosite_main_runtime_and_hk_wrapper() -> None:
    source = (_app_root() / "ops/launch_v4_macos_scheduler.sh").read_text(
        encoding="utf-8"
    )
    assert "venvs/v4-mac/lib/python3.14/site-packages" in source
    assert 'exec "$python_bin" -S -m ops.run_v4_macos_scheduler' in source
    assert "V4_HK_0_2_REAL_PYTHON" in source or "launch_hk_0_2_python_nosite.sh" in source
    assert "--hk-0-2-python" in source


def test_scheduler_launcher_nosite_canary_emits_no_due_and_forwards_wrapper(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    main_python = runtime_root / "venvs/v4-mac/bin/python"
    main_site = runtime_root / "venvs/v4-mac/lib/python3.14/site-packages"
    hk_python = runtime_root / "venvs/v4-hk02/bin/python"
    hk_site = runtime_root / "venvs/v4-hk02/lib/python3.13/site-packages"
    main_python.parent.mkdir(parents=True)
    main_site.mkdir(parents=True)
    hk_python.parent.mkdir(parents=True)
    hk_site.mkdir(parents=True)
    argv_log = tmp_path / "main-argv.json"
    env_log = tmp_path / "main-pythonpath"
    main_python.write_text(
        """#!/bin/sh
python3 -c 'import json,os,sys; json.dump(sys.argv[1:],open(os.environ["V4_TEST_ARGV"],"w")); open(os.environ["V4_TEST_PYTHONPATH"],"w").write(os.environ.get("PYTHONPATH","")); print(json.dumps({"status":"NO_DUE_SLOT","provider_calls":0,"business_writes":0}))' "$@"
""",
        encoding="utf-8",
    )
    hk_python.write_text(
        "#!/bin/sh\n"
        "if [ \"$2\" = \"-c\" ]; then printf '3.13.12\\n'; fi\n",
        encoding="utf-8",
    )
    main_python.chmod(0o755)
    hk_python.chmod(0o755)

    env = _hk_env(
        V4_RUNTIME_ROOT=str(runtime_root),
        V4_HK_0_2_REAL_PYTHON=str(hk_python),
        V4_HK_0_2_PYTHON=str(_hk_wrapper()),
        V4_DATA_ROOT=str(tmp_path / "data"),
        V4_DISPATCH_LEDGER_ROOT=str(tmp_path / "ledger"),
        V4_STAGE_CENTER_SELECTION_ROOT=str(tmp_path / "selection"),
        V4_PRESELECTION_INPUT_ROOT=str(tmp_path / "preselection"),
        V4_TEST_ARGV=str(argv_log),
        V4_TEST_PYTHONPATH=str(env_log),
        V4_RELEASE_ID=RELEASE_ID,
    )
    completed = subprocess.run(
        ["bash", str(_app_root() / "ops/launch_v4_macos_scheduler.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == "NO_DUE_SLOT"
    argv = json.loads(argv_log.read_text(encoding="utf-8"))
    assert "-S" in argv
    assert argv[argv.index("-m") + 1] == "ops.run_v4_macos_scheduler"
    assert argv[argv.index("--hk-0-2-python") + 1] == str(_hk_wrapper())
    pythonpath = env_log.read_text(encoding="utf-8")
    assert str(_app_root()) in pythonpath
    assert str(runtime_root / "venvs/v4-mac/lib/python3.14/site-packages") in pythonpath


def test_scheduler_plist_binds_t060_daemon_and_keeps_stable_runtime() -> None:
    plist = _app_root().parents[0] / "com.lexi.v4.scheduler.plist"
    with plist.open("rb") as stream:
        payload = plistlib.load(stream)
    env = payload["EnvironmentVariables"]
    assert payload["ProgramArguments"] == [
        "/bin/bash",
        "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/"
        "20260827T060000Z-v35-main-scheduler-daemon/app/ops/launch_v4_macos_scheduler.sh",
    ]
    assert payload["RunAtLoad"] is True
    assert payload["KeepAlive"] is True
    assert payload["ThrottleInterval"] == 60
    assert "StartCalendarInterval" not in payload
    assert "StartInterval" not in payload
    assert "ProcessType" not in payload
    assert env["V4_RELEASE_ID"] == RELEASE_ID
    assert env["V4_DAEMON_MODE"] == "persistent-minute"
    assert env["V4_HK_0_2_PYTHON"].endswith(
        "/20260827T060000Z-v35-main-scheduler-daemon/app/ops/launch_hk_0_2_python_nosite.sh"
    )
    assert env["V4_HK_0_2_REAL_PYTHON"] == str(STABLE_HK_PYTHON)
    assert env["V4_RUNTIME_ROOT"] == str(STABLE_RUNTIME)
