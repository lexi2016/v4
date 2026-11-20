"""Single Mac zero-FIT contract checks, using the frozen V8 synthetic harness."""
from pathlib import Path

import pytest

from .authority import Authority, initialize_authority
from .execution import _OfficialBackend
from .official_inputs import verify_run_a
from .test_v8_fixtures import create_fixture, reserve_data
from .test_v8_governance import archive_inputs, lab, no_new_calls
from .validation import OFFICIAL, Rejected, RUN_A, verify_authorization


def test_mac_one_local_service_lock(lab):
    with pytest.raises(Rejected, match="AUTHORITY_INSTANCE_ALREADY_RUNNING"):
        Authority(lab.anchor)
    assert lab.snapshot()["authority_id"] == lab.authority_id
    no_new_calls(lab)


def test_mac_rpc_read_surface_cannot_mutate_or_access_backend(lab):
    operations = ("open_database", "start_stage", "claim_real_call", "commit_output", "enroll_official_trust")
    for op in operations:
        with pytest.raises(Rejected, match="REMOTE_MUTATION_FORBIDDEN"):
            lab.rpc(op)
    no_new_calls(lab)


def test_mac_formal_backend_rejects_untrusted_direct_context():
    with pytest.raises(Rejected, match="OFFICIAL_AUTHORITY_CONTEXT_REQUIRED"):
        _OfficialBackend(object(), "invalid", None)


def test_mac_formal_backend_rejects_ordinary_synthetic_context(lab):
    lab.stop()
    candidate = Authority(lab.anchor)
    try:
        before = candidate.status()["real_counts"]
        with pytest.raises(Rejected, match="OFFICIAL_AUTHORITY_CONTEXT_REQUIRED"):
            _OfficialBackend(candidate, "fabricated", object())
        assert not any(before.values())
        assert candidate.status()["real_counts"] == before
    finally:
        candidate.close()
        lab.start()


def test_mac_tester_supplied_key_cannot_bootstrap_official(tmp_path):
    prepared, _, _, synthetic_trust = create_fixture(tmp_path / "fixture")
    with pytest.raises(Rejected):
        initialize_authority(tmp_path / "not-the-designated-authority", prepared, synthetic_trust, domain=OFFICIAL)
    assert not (tmp_path / "not-the-designated-authority").exists()


def test_mac_valid_synthetic_signature_rejected_in_formal_domain(lab):
    signed, package = lab.bundle()
    from .validation import digest
    with pytest.raises(Rejected, match="AUTH_TRUST_DOMAIN_MISMATCH"):
        verify_authorization(signed, lab.trust, lab.prepared, digest(lab.prepared_path.read_bytes()),
                             lab.authority_id, "F1_RETRY", package, OFFICIAL)
    with pytest.raises(Rejected, match="MODE_AUTHORITY_DOMAIN_MISMATCH"):
        lab.rpc("reserve", **reserve_data(signed, package, mode="AUTHORIZED_EXECUTION"))
    no_new_calls(lab)


def test_mac_archive_state_has_all_historical_events_and_tokens():
    config = archive_inputs()
    data = verify_run_a(Path(config["archive"]), Path(config["original_prelaunch"]))
    assert data["execution_identity_sha256"] == RUN_A
    assert len(data["historical_events"]) == 14 and len(data["historical_start_tokens"]) == 7
    assert data["historical_units"]["F1"]["state"] == "FAILED_ERROR"
    assert data["historical_units"]["F2"]["rows"] == 9503 and data["historical_units"]["F3"]["rows"] == 5250
    assert data["counts"] == {"preprocessing_fit": 3, "model_fit": 2, "model_api": 2, "failed_attempts": 1}


def test_mac_actual_real_counters_stay_zero_in_synthetic_commit(lab):
    tx = lab.reserve()
    out = lab.execute(tx)
    assert out["state"] == "COMMITTED"
    status = lab.snapshot()
    assert status["stub_calls"] == {"preprocessing_fit": 1, "model_fit": 1, "model_api": 1}
    assert len(status["starts"]) == 3
    assert not any(status["real_counts"].values())


def test_mac_forged_execute_at_rpc_is_rejected_before_start(lab):
    with pytest.raises(Rejected, match="TRANSACTION|LEASE"):
        lab.rpc("execute", transaction_id="fabricated-transaction", lease_token="fabricated-lease")
    no_new_calls(lab)
