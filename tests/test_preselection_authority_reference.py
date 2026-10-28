from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from v4_migration.write_authority_reference import (
    AUTHORITY_REFERENCE_ENV,
    DeclarationSource,
    DispatchCorrelation,
    ExactWriteScope,
    UntrustedAuthorizationReference,
    WriteAuthorityRequest,
    WriteAuthorityResolutionError,
    WriteOperation,
    reject_cli_authority_declaration,
    resolve_write_authority_reference,
)


_CLI_MODULES = (
    "ops.materialize_preselection",
    "ops.materialize_scheduled_preselection",
    "ops.refresh_research_preselection",
)


def _argv(module_name: str, tmp_path: Path) -> tuple[list[str], Path]:
    data_root = tmp_path / "data-root"
    common = ["--data-root", str(data_root)]
    if module_name == "ops.materialize_preselection":
        return common + [
            "--trade-date", "20260928",
            "--selector", str(tmp_path / "selector.csv"),
            "--fupan", str(tmp_path / "fupan.csv"),
            "--stage7", str(tmp_path / "stage7.csv"),
            "--research-preview", str(tmp_path / "research.json"),
            "--hk", str(tmp_path / "hk.csv"),
            "--wechat-rows", str(tmp_path / "wechat.csv"),
            "--wechat-manifest", str(tmp_path / "wechat.json"),
        ], data_root
    if module_name == "ops.materialize_scheduled_preselection":
        return common + [
            "--trade-date", "20260928",
            "--signal-date", "20260925",
            "--input-root", str(tmp_path / "inputs"),
            "--shared-data-root", str(tmp_path / "shared-data"),
            "--shared-package-root", str(tmp_path / "shared-package"),
        ], data_root
    if module_name == "ops.refresh_research_preselection":
        return common + ["--date", "20260928"], data_root
    raise AssertionError(f"unrecognized CLI module: {module_name}")


def _invoke(module_name: str, argv: list[str]) -> int:
    return importlib.import_module(module_name).main(argv)


def _assert_rejected(capsys, *, reason: str, source: str) -> None:
    output = capsys.readouterr()
    assert output.err == ""
    result = json.loads(output.out)
    assert result["status"] == "REJECTED"
    assert result["reason"] == reason
    assert result["authorization_source"] == source
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False


def _expected_missing_artifacts(trade_date: str) -> list[dict]:
    from domains.preselection_materializer import build_expected_missing_pool
    from infrastructure.preselection_pool_store import POOL_ORDER

    return [
        build_expected_missing_pool(
            trade_date,
            pool_id=pool_id,
            display_name=f"fixture {pool_id}",
            market="HK" if pool_id == "hkconnect_d1_top100" else "A",
            reason="ISOLATED_LEGACY_CLI_COMPATIBILITY_FIXTURE",
        )
        for pool_id in POOL_ORDER
    ]


@pytest.mark.parametrize("module_name", _CLI_MODULES)
@pytest.mark.parametrize("declaration_kind", ("self_asserted", "json", "json_path"))
def test_cli_self_asserted_or_local_json_reference_denies_before_store_creation(
    module_name: str,
    declaration_kind: str,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    read_attempts: list[str] = []
    argv, data_root = _argv(module_name, tmp_path)
    if declaration_kind == "self_asserted":
        value = "owner=fixture-owner;approved=true"
    elif declaration_kind == "json":
        value = '{"owner_id":"fixture-owner","approved":true}'
    else:
        local_json = tmp_path / "self-asserted-authorization.json"
        local_json.write_text('{"approved":true}', encoding="utf-8")
        value = str(local_json)
        original_read_text = Path.read_text
        original_read_bytes = Path.read_bytes

        def guarded_read_text(path: Path, *args, **kwargs):
            if path == local_json:
                read_attempts.append("read_text")
                raise AssertionError("CLI must not read a local authorization JSON file")
            return original_read_text(path, *args, **kwargs)

        def guarded_read_bytes(path: Path, *args, **kwargs):
            if path == local_json:
                read_attempts.append("read_bytes")
                raise AssertionError("CLI must not read a local authorization JSON file")
            return original_read_bytes(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", guarded_read_text)
        monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    argv += ["--write-authorization-ref", value]

    assert _invoke(module_name, argv) == 3

    _assert_rejected(
        capsys,
        reason="AUTHORITY_PROVIDER_UNAVAILABLE",
        source="argv",
    )
    assert not data_root.exists()
    assert read_attempts == []


@pytest.mark.parametrize("module_name", _CLI_MODULES)
@pytest.mark.parametrize("value", ("fixture-self-assertion", "{\"approved\":true}", "", "   "))
def test_cli_environment_reference_denies_before_store_creation(
    module_name: str,
    value: str,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    argv, data_root = _argv(module_name, tmp_path)
    monkeypatch.setenv(AUTHORITY_REFERENCE_ENV, value)

    assert _invoke(module_name, argv) == 3

    expected_reason = (
        "EMPTY_AUTHORITY_REFERENCE_DECLARATION" if not value.strip()
        else "AUTHORITY_PROVIDER_UNAVAILABLE"
    )
    _assert_rejected(capsys, reason=expected_reason, source="env")
    assert not data_root.exists()


@pytest.mark.parametrize("module_name", _CLI_MODULES)
def test_cli_conflicting_or_repeated_reference_declarations_deny(
    module_name: str,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.delenv(AUTHORITY_REFERENCE_ENV, raising=False)
    argv, data_root = _argv(module_name, tmp_path)
    argv += ["--write-authorization-ref", "argv-ref", "--write-authorization-ref", "second-argv-ref"]

    assert _invoke(module_name, argv) == 3

    _assert_rejected(
        capsys,
        reason="CONFLICTING_AUTHORITY_REFERENCE_DECLARATIONS",
        source="argv",
    )
    assert not data_root.exists()


@pytest.mark.parametrize("module_name", _CLI_MODULES)
def test_cli_without_reference_keeps_the_default_legacy_materialize_path(
    module_name: str,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.delenv(AUTHORITY_REFERENCE_ENV, raising=False)
    argv, data_root = _argv(module_name, tmp_path)
    trade_date = "20260928"
    module = importlib.import_module(module_name)
    if module_name == "ops.materialize_preselection":
        for flag in (
            "--fupan",
            "--stage7",
            "--research-preview",
            "--hk",
            "--wechat-rows",
            "--wechat-manifest",
        ):
            input_path = Path(argv[argv.index(flag) + 1])
            input_path.write_bytes(b"isolated input fixture")
        monkeypatch.setattr(module, "build_artifacts", lambda _args: _expected_missing_artifacts(trade_date))
    elif module_name == "ops.materialize_scheduled_preselection":
        monkeypatch.setattr(
            module,
            "build_scheduled_artifacts",
            lambda **_kwargs: _expected_missing_artifacts(trade_date),
        )
    else:
        monkeypatch.setattr(
            module,
            "build_hourly_research_pool",
            lambda *_args, **_kwargs: _expected_missing_artifacts(trade_date)[3],
        )

    assert module.main(argv) == 0

    output = capsys.readouterr()
    assert output.err == ""
    result = json.loads(output.out)
    assert result["trade_date"] == trade_date
    manifest_path = data_root / "preselection_pools" / trade_date / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if module_name == "ops.refresh_research_preselection":
        expected_ids = {"a_share_research_recommendation_pool"}
    else:
        from infrastructure.preselection_pool_store import POOL_ORDER

        expected_ids = set(POOL_ORDER)
        if module_name == "ops.materialize_scheduled_preselection":
            deferred_ids = {"a_d1_premarket_pool", "hkconnect_d1_top100"}
            expected_ids -= deferred_ids
            deferred = [row for row in result["artifacts"] if row.get("status") == "DEFERRED"]
            assert {row["pool_id"] for row in deferred} == deferred_ids
            assert all(row["artifact_written"] is False for row in deferred)
            assert result["status"] == "PARTIAL"
    assert set(manifest) == expected_ids

    argv, data_root = _argv(module_name, tmp_path / "argv-env-conflict")
    argv += ["--write-authorization-ref", "argv-ref"]
    monkeypatch.setenv(AUTHORITY_REFERENCE_ENV, "env-ref")

    assert _invoke(module_name, argv) == 3

    _assert_rejected(
        capsys,
        reason="CONFLICTING_AUTHORITY_REFERENCE_DECLARATIONS",
        source="argv+env",
    )
    assert not data_root.exists()


def test_typed_exact_scope_contains_operation_revision_recovery_and_dispatch_contract(
    tmp_path: Path,
) -> None:
    correlation = DispatchCorrelation(
        dispatch_run_id="dispatch-1",
        workload_id="materialize-preselection",
        slot_id="2030-01-02T20:00:00+08:00",
        business_date="20300102",
        target_date="20300103",
        parent_identity="dispatcher-parent-1",
        child_identity="materializer-child-1",
    )
    scope = ExactWriteScope(
        operation=WriteOperation.RECOVER_EXPECTED_MISSING,
        trade_date="20300103",
        pool_ids=("a_d1_fupan_watchlist_pool", "a_d1_stage7_fenshi_review_pool"),
        canonical_data_root=tmp_path / "data-root",
        active_release_id="release-r1",
        active_release_manifest_sha256="a" * 64,
        expected_gate_revision=17,
        dispatch_correlation=correlation,
        recovery_preimage_sha256="b" * 64,
        recovery_replacement_sha256="c" * 64,
    )
    request = WriteAuthorityRequest(
        reference=UntrustedAuthorizationReference(
            value="caller-asserted-reference",
            source=DeclarationSource.ARGV,
        ),
        scope=scope,
    )

    with pytest.raises(WriteAuthorityResolutionError) as error:
        resolve_write_authority_reference(request)

    assert error.value.reason_code == "AUTHORITY_PROVIDER_UNAVAILABLE"
    assert error.value.source == "argv"


def test_recovery_and_rollback_scope_require_operation_specific_hashes(tmp_path: Path) -> None:
    common = dict(
        trade_date="20300103",
        pool_ids=("a_d1_fupan_watchlist_pool",),
        canonical_data_root=tmp_path / "data-root",
        active_release_id="release-r1",
        active_release_manifest_sha256="a" * 64,
        expected_gate_revision=0,
    )

    with pytest.raises(ValueError, match="preimage and replacement SHAs"):
        ExactWriteScope(operation=WriteOperation.RECOVER_EXPECTED_MISSING, **common)
    with pytest.raises(ValueError, match="current SHA and recovery-record identity"):
        ExactWriteScope(operation=WriteOperation.ROLLBACK_RECOVERY, **common)

    rollback_scope = ExactWriteScope(
        operation=WriteOperation.ROLLBACK_RECOVERY,
        rollback_current_sha256="d" * 64,
        rollback_recovery_record_id="recovery-record-1",
        **common,
    )
    assert rollback_scope.rollback_current_sha256 == "d" * 64
    assert rollback_scope.rollback_recovery_record_id == "recovery-record-1"


@pytest.mark.parametrize("cli_reference", ("", "   "))
def test_empty_argv_reference_does_not_fall_back_to_legacy(cli_reference: str) -> None:
    with pytest.raises(WriteAuthorityResolutionError) as error:
        reject_cli_authority_declaration(cli_reference, environ={})

    assert error.value.reason_code == "EMPTY_AUTHORITY_REFERENCE_DECLARATION"
