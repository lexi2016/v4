"""Reproduce old reference CLI behavior against a real R2 owner GET response.

Uses the existing explicit synthetic artifact fixture and the real R2 router,
import owner, store and hash validators; not a Mac or live-data acceptance.
"""
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest
import test_manager_announcement_parity_20261008 as parity
from ops import run_manager_daily_announcement as current_cli


def main():
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return parity.NOW.astimezone(tz) if tz else parity.NOW.replace(tzinfo=None)

    with TemporaryDirectory(prefix="synthetic-announcement-cli-") as root, pytest.MonkeyPatch.context() as patch:
        patch.setattr(parity.api, "datetime", Clock)
        patch.setattr(parity.consumer, "_now", lambda: parity.NOW.isoformat())
        service = parity._FixtureService(Path(root))
        try:
            product, registered = parity._fixture(service)
            with parity._client(service) as client:
                imported = parity._import(client, registered)
                before = parity._snapshot(service.store.root)

                def request(api_base, path, **kwargs):
                    assert not kwargs
                    response = client.get(path)
                    assert response.status_code == 200, response.text
                    return response.json()

                reference = Path(__file__).resolve().parents[2] / "input/package/code/actual_owner_runner_20261009/ops/run_manager_daily_announcement.py"
                spec = importlib.util.spec_from_file_location("announcement_old_reference_cli", reference)
                old_cli = importlib.util.module_from_spec(spec)
                paths = list(sys.path)
                try:
                    spec.loader.exec_module(old_cli)
                finally:
                    sys.path[:] = paths
                old_cli._request = request
                patch.setattr(current_cli, "_request", request)
                args = SimpleNamespace(target_date=parity.TARGET,
                    publication_date=parity.PUBLICATION, api_base="http://127.0.0.1:8873")
                try:
                    old_cli._readback(args)
                except ValueError as exc:
                    old_error = str(exc)
                else:
                    raise AssertionError("Historical thin-product readback unexpectedly passed")
                assert old_error == "ANNOUNCEMENT_OWNER_IMPORT_RECEIPT_HANDOFF_BINDING_INVALID"
                accepted = current_cli._readback(args)
                assert accepted["status"] == "OWNER_READBACK_VERIFIED"
                assert accepted["product_sha256"] == product["sha256"]
                assert accepted["owner_receipt_sha256"] == imported["owner_import_receipt"]["sha256"]
                assert parity._snapshot(service.store.root) == before
                print(json.dumps({"status": "PASS_EXPECTED_COMPATIBILITY_DISTINCTION",
                    "scope": "SYNTHETIC_FIXTURE_REAL_R2_OWNER_ROUTE_READBACK",
                    "old_reference_error": old_error,
                    "fixed_git_support_cli_result": accepted["status"],
                    "readback_byte_mutations": 0,
                    "real_owner_data_verified": False,
                    "natural_run_verified": False}, indent=2))
        finally:
            service.close()


if __name__ == "__main__":
    main()
