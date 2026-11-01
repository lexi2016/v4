"""Offline tests for the optional, pinned Iwencai adapter."""
from __future__ import annotations

import hashlib
import json
import socket
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from domains.research_review_generation._owned_io import BoundaryError
from domains.research_review_generation import iwencai_binding as binding


def _config(*, enabled=True):
    return {
        "enabled": enabled,
        "client_source_path": str(binding.CLIENT_SOURCE_PATH),
        "client_source_sha256": binding.CLIENT_SOURCE_SHA256,
        "credential_ref": binding.CREDENTIAL_REFERENCE,
        "base_url": binding.CLIENT_BASE_URL,
        "timeout_seconds": 30,
        "max_retries": 1,
        "retry_delay_seconds": 0,
    }


def _assembly_fixture(tmp_path, *, mode="collect", binding_value=None):
    root = tmp_path / "state"
    root.mkdir()
    cache = root / "cache"
    cache.mkdir()
    inventory = tmp_path / "cache-inventory.json"
    inventory.write_text(json.dumps({"schema": "v4.vibe_cache_inventory.v1", "files": {}}))
    profile = Path(__file__).resolve().parents[1] / "contracts/vibe_runtime_profile.json"
    profile_sha = hashlib.sha256(profile.read_bytes()).hexdigest()
    body = {
        "schema": "v4.vibe_assembly.v1",
        "state_root": str(root),
        "cache_root": str(cache),
        "cache_manifest_path": str(inventory),
        "cache_manifest_sha256": hashlib.sha256(inventory.read_bytes()).hexdigest(),
        "profile_path": str(profile),
        "profile_sha256": profile_sha,
        "credential_db": str(tmp_path / "provider.db"),
        "data_mode": mode,
        "data_as_of": "2026-09-11T15:05:00+08:00",
    }
    if mode == "snapshot":
        body["snapshot_sha256"] = "a" * 64
    if binding_value is not None:
        body["iwencai_binding"] = binding_value
    path = tmp_path / "assembly.json"
    path.write_text(json.dumps(body, sort_keys=True))
    source_manifest = Path(__file__).resolve().parents[1] / "domains/research_review_generation/OWNED_SOURCE_MANIFEST.json"
    implementation_sha = hashlib.sha256(source_manifest.read_bytes()).hexdigest()
    return path, hashlib.sha256(path.read_bytes()).hexdigest(), implementation_sha, body


def _block_network(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("offline test attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", blocked)


def test_disabled_binding_does_not_read_source_or_resolve_credential(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("disabled binding performed optional-client work")

    monkeypatch.setattr(binding, "_read_pinned_client_source", forbidden)
    monkeypatch.setattr(binding, "_resolve_explicit_credential", forbidden)
    before = {name for name in sys.modules if name.startswith(binding._MODULE_PREFIX)}
    assert binding.create_iwencai_query_client(_config(enabled=False)) is None
    after = {name for name in sys.modules if name.startswith(binding._MODULE_PREFIX)}
    assert after == before


@pytest.mark.parametrize(
    "change",
    [
        {"extra": True},
        {"base_url": "https://example.invalid"},
        {"credential_ref": "env:IWENCAI_API_KEY"},
        {"max_retries": 2},
        {"timeout_seconds": True},
        {"enabled": 1},
    ],
)
def test_binding_schema_is_closed_and_fixed(change):
    invalid = _config()
    invalid.update(change)
    with pytest.raises(BoundaryError):
        binding.validate_iwencai_binding(invalid)


def test_enabled_binding_loads_only_pinned_source_and_constructs_one_attempt(monkeypatch):
    monkeypatch.delenv(binding.CREDENTIAL_ENVIRONMENT_NAME, raising=False)
    client = binding.create_iwencai_query_client(_config(), _api_key_for_testing="SYNTHETIC-ONLY")
    assert client is not None
    original = client._client
    assert original.api_key == "SYNTHETIC-ONLY"
    assert original.base_url == binding.CLIENT_BASE_URL
    assert original.timeout == 30
    assert original.max_retries == 1
    assert original.retry_delay == 0
    assert original._session.trust_env is False
    assert original._session.proxies == {}
    assert original._session.auth is None
    assert original._session.headers["Authorization"] == "Bearer SYNTHETIC-ONLY"
    assert hashlib.sha256(Path(binding.CLIENT_SOURCE_PATH).read_bytes()).hexdigest() == binding.CLIENT_SOURCE_SHA256


def test_pinned_source_hash_mismatch_refuses_before_module_load(tmp_path, monkeypatch):
    path = tmp_path / "changed_client.py"
    path.write_text("class IwencaiClient: pass\n")
    monkeypatch.setattr(binding, "CLIENT_SOURCE_PATH", path)
    config = _config()
    config["client_source_path"] = str(path)
    module_names = {name for name in sys.modules if name.startswith(binding._MODULE_PREFIX)}
    with pytest.raises(BoundaryError, match="IWENCAI_CLIENT_SOURCE_SHA_MISMATCH"):
        binding._read_pinned_client_source(config)
    assert {name for name in sys.modules if name.startswith(binding._MODULE_PREFIX)} == module_names


def test_symlinked_pinned_source_is_refused(tmp_path, monkeypatch):
    target = tmp_path / "real_client.py"
    target.write_bytes(Path(binding.CLIENT_SOURCE_PATH).read_bytes())
    link = tmp_path / "client_link.py"
    link.symlink_to(target)
    monkeypatch.setattr(binding, "CLIENT_SOURCE_PATH", link)
    config = _config()
    config["client_source_path"] = str(link)
    with pytest.raises(BoundaryError, match="IWENCAI_CLIENT_SOURCE_UNSAFE"):
        binding._read_pinned_client_source(config)


@pytest.mark.parametrize(
    "url",
    [
        "http://openapi.iwencai.com/v1/query2data",
        "https://openapi.iwencai.com:444/v1/query2data",
        "https://openapi.iwencai.com/v1/comprehensive/search",
        "https://openapi.iwencai.com/v1/query2data?override=1",
        "https://user@openapi.iwencai.com/v1/query2data",
        "https://openapi.iwencai.com.attacker.invalid/v1/query2data",
    ],
)
def test_query_endpoint_rejects_noncanonical_targets(url):
    with pytest.raises(BoundaryError, match="IWENCAI_ENDPOINT_FORBIDDEN"):
        binding._assert_query_endpoint(url)


def test_query_endpoint_accepts_only_official_tls_path():
    binding._assert_query_endpoint("https://openapi.iwencai.com/v1/query2data")
    binding._assert_query_endpoint("https://openapi.iwencai.com:443/v1/query2data")


def test_official_query_redirect_is_not_followed_and_errors_are_redacted(monkeypatch):
    import requests
    from requests.adapters import BaseAdapter

    class RedirectAdapter(BaseAdapter):
        def __init__(self):
            self.sent = []

        def send(self, request, **_kwargs):
            self.sent.append(request.url)
            response = requests.Response()
            response.status_code = 302
            response.headers["Location"] = "https://attacker.invalid/collect"
            response.url = request.url
            response.request = request
            response._content = b"provider diagnostic with secret marker"
            return response

        def close(self):
            return None

    client = binding.create_iwencai_query_client(_config(), _api_key_for_testing="SYNTHETIC-ONLY")
    adapter = RedirectAdapter()
    client._client._session.mount("https://", adapter)
    with pytest.raises(binding.IwencaiRequestFailure) as error:
        client.query("synthetic query", page=1, limit=50)
    assert "secret marker" not in str(error.value)
    assert len(adapter.sent) == 1
    assert adapter.sent[0].startswith("https://openapi.iwencai.com/v1/query2data")
    assert all("attacker.invalid" not in item for item in adapter.sent)


def test_wrong_destination_is_blocked_before_adapter_send():
    import requests
    from requests.adapters import BaseAdapter

    class NeverSendAdapter(BaseAdapter):
        sent = 0

        def send(self, request, **_kwargs):
            self.sent += 1
            raise AssertionError("forbidden request reached adapter")

        def close(self):
            return None

    client = binding.create_iwencai_query_client(_config(), _api_key_for_testing="SYNTHETIC-ONLY")
    adapter = NeverSendAdapter()
    client._client._session.mount("https://", adapter)
    client._client.base_url = "https://example.invalid"
    with pytest.raises(binding.IwencaiRequestFailure):
        client.query("synthetic query")
    assert adapter.sent == 0


def test_existing_exact_date_fetcher_uses_client_seam_and_rejects_wrong_date():
    from domains.research_review_generation.data_core.fetchers import _fetch_iwencai_zt_reasons

    class QueryFixture:
        def __init__(self, dates):
            self.dates = dates
            self.calls = []

        def query(self, query, **params):
            self.calls.append((query, params))
            date = self.dates[min(len(self.calls) - 1, len(self.dates) - 1)]
            return pd.DataFrame(
                {
                    "代码": ["000001.SZ"],
                    f"涨停原因[{date}]": ["合成题材"],
                }
            )

    class Context:
        def __init__(self, client):
            self.client = client

        def iwencai_query(self, query, **params):
            return self.client.query(query, **params)

    exact = QueryFixture(["20260911"])
    reasons, error = _fetch_iwencai_zt_reasons("20260911", ctx=Context(exact))
    assert reasons == {"000001": "合成题材"}
    assert error is None
    assert exact.calls == [("2026-09-11涨停的股票 涨停原因", {"page": 1, "limit": 50})]

    wrong = QueryFixture(["20260910"])
    reasons, error = _fetch_iwencai_zt_reasons("20260911", ctx=Context(wrong))
    assert reasons == {}
    assert "不是 20260911" in error
    assert wrong.calls[0][1] == {"page": 1, "limit": 50}


def test_pinned_client_reaches_existing_transport_and_exact_date_fetcher_without_network(monkeypatch):
    import requests
    from requests.adapters import BaseAdapter
    from domains.research_review_generation.data_core.fetchers import _fetch_iwencai_zt_reasons
    from domains.research_review_generation.owned_authority import LiveTransport

    _block_network(monkeypatch)

    class JsonAdapter(BaseAdapter):
        def __init__(self):
            self.requests = []

        def send(self, request, **_kwargs):
            self.requests.append(request)
            response = requests.Response()
            response.status_code = 200
            response.headers["Content-Type"] = "application/json"
            response.url = request.url
            response.request = request
            response._content = json.dumps(
                {
                    "status_code": 0,
                    "datas": [{"代码": "000001.SZ", "涨停原因[20260911]": "合成题材"}],
                    "code_count": 1,
                },
                ensure_ascii=False,
            ).encode()
            return response

        def close(self):
            return None

    client = binding.create_iwencai_query_client(_config(), _api_key_for_testing="SYNTHETIC-ONLY")
    adapter = JsonAdapter()
    client._client._session.mount("https://", adapter)
    transport = LiveTransport(iwencai_client=client)

    class Context:
        def iwencai_query(self, query, **params):
            return transport.iwencai_query(query, **params)

    reasons, error = _fetch_iwencai_zt_reasons("20260911", ctx=Context())
    assert reasons == {"000001": "合成题材"}
    assert error is None
    assert len(adapter.requests) == 1
    request = adapter.requests[0]
    assert request.url == "https://openapi.iwencai.com/v1/query2data"
    body = json.loads(request.body)
    assert body["query"] == "2026-09-11涨停的股票 涨停原因"
    assert body["page"] == "1" and body["limit"] == "50"


def test_assembly_absent_and_disabled_binding_preserve_lazy_default_path(tmp_path, monkeypatch):
    from domains.research_review_generation.assembly import assemble_runtime

    path, config_sha, implementation_sha, body = _assembly_fixture(tmp_path)
    transport = object()
    before_modules = {name for name in sys.modules if name.startswith(binding._MODULE_PREFIX)}
    absent = assemble_runtime(
        config_path=path,
        config_sha256=config_sha,
        implementation_manifest_sha256=implementation_sha,
        transport=transport,
    )
    assert absent._transport is transport
    assert absent._iwencai_binding is None
    assert {name for name in sys.modules if name.startswith(binding._MODULE_PREFIX)} == before_modules

    def forbidden(*_args, **_kwargs):
        raise AssertionError("disabled assembly tried to build the Iwencai client")

    monkeypatch.setattr(binding, "create_iwencai_query_client", forbidden)
    body["iwencai_binding"] = _config(enabled=False)
    path.write_text(json.dumps(body, sort_keys=True))
    disabled = assemble_runtime(
        config_path=path,
        config_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        implementation_manifest_sha256=implementation_sha,
        transport=None,
    )
    assert disabled._transport is None
    assert disabled._iwencai_binding["enabled"] is False
    assert not (Path(body["state_root"]) / "reviews").exists()


def test_enabled_assembly_does_not_read_key_or_load_sdk_bytes(tmp_path, monkeypatch):
    from domains.research_review_generation.assembly import assemble_runtime

    path, config_sha, implementation_sha, body = _assembly_fixture(
        tmp_path, binding_value=_config(enabled=True)
    )
    monkeypatch.setenv(binding.CREDENTIAL_ENVIRONMENT_NAME, "SYNTHETIC-NOT-A-REAL-KEY")
    builders = []

    def build(config, **_kwargs):
        builders.append(config)
        return object()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("enabled assembly touched external SDK bytes or credential")

    monkeypatch.setattr(binding, "create_iwencai_query_client", build)
    monkeypatch.setattr(binding, "_read_pinned_client_source", forbidden)
    monkeypatch.setattr(binding, "_load_pinned_client_module", forbidden)
    monkeypatch.setattr(binding, "_resolve_explicit_credential", forbidden)
    before_modules = {name for name in sys.modules if name.startswith(binding._MODULE_PREFIX)}
    result = assemble_runtime(
        config_path=path,
        config_sha256=config_sha,
        implementation_manifest_sha256=implementation_sha,
    )
    assert builders == []
    assert result._transport is None
    assert result._iwencai_binding["enabled"] is True
    assert {name for name in sys.modules if name.startswith(binding._MODULE_PREFIX)} == before_modules
    assert not (Path(body["state_root"]) / "reviews").exists()


@pytest.mark.parametrize("guard", ["existing-output", "occupied-lock"])
def test_public_generation_guards_refuse_before_iwencai_key_or_sdk(guard, tmp_path, monkeypatch, capsys):
    from domains.research_review_generation import generation
    from domains.research_review_generation.generation import GenerationRefused
    from ops.run_research_review_generation import main

    path, config_sha, implementation_sha, body = _assembly_fixture(
        tmp_path, binding_value=_config(enabled=True)
    )
    monkeypatch.setenv(binding.CREDENTIAL_ENVIRONMENT_NAME, "SYNTHETIC-NOT-A-REAL-KEY")
    _block_network(monkeypatch)
    calls = []

    def should_not_build(config, **_kwargs):
        calls.append(config)
        return object()

    def should_not_read(*_args, **_kwargs):
        raise AssertionError("generation guard reached Iwencai credential or source access")

    monkeypatch.setattr(binding, "create_iwencai_query_client", should_not_build)
    monkeypatch.setattr(binding, "_read_pinned_client_source", should_not_read)
    monkeypatch.setattr(binding, "_resolve_explicit_credential", should_not_read)

    date = "2026-09-11"
    reviews = Path(body["state_root"]) / "reviews"
    if guard == "existing-output":
        reviews.mkdir()
        output = reviews / "2026-09-11.json"
        output.write_text('{"preserved":true}')
        output_before = output.read_bytes()
    else:
        @contextmanager
        def refuse_lock(*_args, **_kwargs):
            raise GenerationRefused("synthetic same-date lock refusal")
            yield

        monkeypatch.setattr(generation, "owned_interprocess_lock", refuse_lock)

    result = main([
        "--date", date,
        "--config", str(path),
        "--config-sha256", config_sha,
        "--source-manifest-sha256", implementation_sha,
    ])
    stdout = capsys.readouterr().out
    assert result == 2
    assert '"status": "CANNOT_CONFIRM"' in stdout
    assert "SYNTHETIC-NOT-A-REAL-KEY" not in stdout
    assert calls == []
    if guard == "existing-output":
        assert output.read_bytes() == output_before


@pytest.mark.parametrize(
    ("mode", "enabled", "expected_client_count"),
    [("collect", True, 1), ("collect", False, 0), ("snapshot", True, 0)],
)
def test_locked_runtime_constructs_iwencai_only_once_for_enabled_collect(
    mode, enabled, expected_client_count, tmp_path, monkeypatch, capsys
):
    from domains.research_review_generation import generation
    from domains.research_review_generation.owned_authority import LiveTransport
    from ops.run_research_review_generation import main
    import domains.research_review_generation.assembly as assembly

    path, config_sha, implementation_sha, body = _assembly_fixture(
        tmp_path, mode=mode, binding_value=_config(enabled=enabled)
    )
    synthetic_key = "SYNTHETIC-NOT-A-REAL-KEY"
    monkeypatch.setenv(binding.CREDENTIAL_ENVIRONMENT_NAME, synthetic_key)
    _block_network(monkeypatch)
    real_lock = generation.owned_interprocess_lock
    lock_held = [False]

    @contextmanager
    def observed_lock(*args, **kwargs):
        with real_lock(*args, **kwargs):
            lock_held[0] = True
            try:
                yield
            finally:
                lock_held[0] = False

    monkeypatch.setattr(generation, "owned_interprocess_lock", observed_lock)
    client_calls = []
    clients = SimpleNamespace(
        quick=SimpleNamespace(identity=object()),
        deep=SimpleNamespace(identity=object()),
        profile_sha256="b" * 64,
    )
    monkeypatch.setattr(assembly, "create_clients", lambda **_kwargs: clients)
    original_builder = binding.create_iwencai_query_client

    def observed_builder(config):
        assert lock_held[0] is True
        client_calls.append(config)
        return original_builder(config)

    monkeypatch.setattr(binding, "create_iwencai_query_client", observed_builder)
    authority_instances = []

    class FakeAuthority:
        def __init__(self, *, state_root, cache_root, transport, **_kwargs):
            assert lock_held[0] is True
            self.transport = transport
            self.cache = SimpleNamespace(root=Path(cache_root), approved={})
            self.materializations = 0
            authority_instances.append(self)

        def materialize(self, **_kwargs):
            assert lock_held[0] is True
            self.materializations += 1
            return {}, "c" * 64

    class FakeRuntime:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self, *_args, **_kwargs):
            assert lock_held[0] is True
            return {}, {}

    monkeypatch.setattr(assembly, "VibeDataAuthority", FakeAuthority)
    monkeypatch.setattr(assembly, "VibeRuntime", FakeRuntime)
    monkeypatch.setattr(generation, "write_exact_review", lambda *_args, **_kwargs: {"status": "generated"})

    result = main([
        "--date", "2026-09-11",
        "--config", str(path),
        "--config-sha256", config_sha,
        "--source-manifest-sha256", implementation_sha,
    ])
    assert result == 0, capsys.readouterr().out
    assert len(client_calls) == expected_client_count
    assert len(authority_instances) == 1
    authority = authority_instances[0]
    assert isinstance(authority.transport, LiveTransport)
    if expected_client_count:
        assert authority.transport.iwencai_client is not None
        assert authority.transport.iwencai_client._client.api_key == synthetic_key
    else:
        assert authority.transport.iwencai_client is None
    assert authority.materializations == (1 if mode == "collect" else 0)
