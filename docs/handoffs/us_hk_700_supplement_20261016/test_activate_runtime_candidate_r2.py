from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
import sys

import pytest


HANDOFF_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(HANDOFF_DIR))
import activate_runtime_candidate_r2 as activation_r2  # noqa: E402


_CORE_BINDING_NAMES = (
    "CANDIDATE", "ACTIVE_CONFIG", "NEW_CONFIG", "PLAN_PATH", "STAGED_PLIST",
    "ROLLBACK_PLIST", "ACTIVATION_RECEIPT_PATH",
)


def _restore_core_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    core = activation_r2.activation
    for name in _CORE_BINDING_NAMES:
        monkeypatch.setattr(core, name, getattr(core, name))


def test_bind_r2_uses_r2_plan_config_staged_rollback_and_distinct_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _restore_core_binding(monkeypatch)
    core = activation_r2.activation
    r1_receipt = HANDOFF_DIR / "runtime-activation-receipt.json"
    assert core.ACTIVATION_RECEIPT_PATH == r1_receipt
    assert core.CANDIDATE.name.endswith("-r1")

    binding = activation_r2.bind_r2()

    assert core.CANDIDATE == activation_r2.CANDIDATE
    assert core.ACTIVE_CONFIG == activation_r2.ACTIVE_CONFIG
    assert core.NEW_CONFIG == activation_r2.NEW_CONFIG
    assert core.PLAN_PATH == activation_r2.PLAN_PATH
    assert core.STAGED_PLIST == activation_r2.STAGED_PLIST
    assert core.ROLLBACK_PLIST == activation_r2.ROLLBACK_PLIST
    assert core.ACTIVATION_RECEIPT_PATH == activation_r2.ACTIVATION_RECEIPT
    assert core.ACTIVATION_RECEIPT_PATH != r1_receipt
    assert binding["candidate_manifest_sha256"] == json.loads(
        activation_r2.PREPARATION_RECEIPT.read_text(encoding="utf-8")
    )["candidate_manifest_sha256"]
    assert binding["binding_status"] == "PASS"


def test_r2_entry_without_activation_flags_is_read_only_prepared_gate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    _restore_core_binding(monkeypatch)
    monkeypatch.setattr(sys, "argv", [str(HANDOFF_DIR / "activate_runtime_candidate_r2.py")])

    activation_r2.main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "PREPARED_ONLY"
    assert output["launchctl_called"] is False
    assert not activation_r2.ACTIVATION_RECEIPT.exists()


def test_mocked_cutover_writes_receipt_only_to_bound_r2_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    _restore_core_binding(monkeypatch)
    activation_r2.bind_r2()
    core = activation_r2.activation
    r1_receipt = activation_r2.R1_ACTIVATION_RECEIPT
    r1_before = r1_receipt.read_bytes() if r1_receipt.exists() else None
    isolated_r2_receipt = tmp_path / "runtime-activation-receipt-r2.json"
    monkeypatch.setattr(core, "ACTIVATION_RECEIPT_PATH", isolated_r2_receipt)

    manifest_sha = json.loads(activation_r2.PREPARATION_RECEIPT.read_text(encoding="utf-8"))[
        "candidate_manifest_sha256"
    ]
    review = tmp_path / "review.md"
    review.write_text(
        "# Runtime independent review\n"
        "Reviewer: `mapping700_review_test` (independent from `mapping700_writer`)\n"
        f"Candidate manifest SHA256: `{manifest_sha}`\n\n"
        "REVIEWED=PASS — isolated test fixture\n"
        "BEHAVIOR_VERIFIED=PASS — isolated test fixture\n",
        encoding="utf-8",
    )

    @contextmanager
    def fake_lock(*_args: object, **_kwargs: object):
        yield object()

    launch_calls: list[tuple[str, ...]] = []
    installs: list[bytes] = []
    monkeypatch.setattr(core, "shared_api_release_lock", fake_lock)
    monkeypatch.setattr(core, "verify_api_release_candidate", lambda **kwargs: {
        "status": "PASS", "active_pointer": kwargs["active_pointer"]
    })
    monkeypatch.setattr(core, "bootout_and_wait", lambda *_args, **_kwargs: {
        "old_pids": [], "old_pids_exited": True, "label_absent": True,
    })
    monkeypatch.setattr(core, "launch", lambda *args, **_kwargs: (
        launch_calls.append(tuple(args)) or {"argv": ["launchctl", *args], "exit_code": 0}
    ))
    monkeypatch.setattr(core, "atomic_install", lambda raw, _mode: installs.append(raw))
    monkeypatch.setattr(core, "check_live_api", lambda: {
        "exact_reviewed_rid": "R001/FULL/two evidence fields",
        "exact_unprocessed_rid": "R700/NOT_PROCESSED/SUMMARY/null",
    })
    monkeypatch.setattr(sys, "argv", [
        str(HANDOFF_DIR / "activate_runtime_candidate_r2.py"),
        "--review-receipt", str(review),
        "--root-authorization-ref", "TEST_ONLY_NOT_A_REAL_AUTHORIZATION",
        "--activate",
    ])

    core.main()

    receipt = json.loads(isolated_r2_receipt.read_text(encoding="utf-8"))
    assert receipt["status"] == "ACTIVATED_API_READBACK_OK"
    assert receipt["candidate_manifest_sha256"] == manifest_sha
    assert len(launch_calls) == 1 and launch_calls[0][0] == "bootstrap"
    assert installs == [activation_r2.STAGED_PLIST.read_bytes()]
    assert (r1_receipt.read_bytes() if r1_receipt.exists() else None) == r1_before
    assert not activation_r2.ACTIVATION_RECEIPT.exists()
    assert capsys.readouterr().out
