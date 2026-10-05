import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]


def _unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def test_process_smoke_reaches_healthz_on_ephemeral_loopback_port() -> None:
    port = _unused_loopback_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "apps.api.v35_api.run",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            # The launcher requires an explicit stage mode: shared consumes a
            # configured stage root, local explicitly enables the local
            # producer.  This smoke test exercises the local producer path.
            "--stage-mode",
            "local",
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as response:
                    assert response.status == 200
                    return
            except OSError:
                time.sleep(0.1)
        raise AssertionError("server did not expose /healthz")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        assert process.returncode is not None
