from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

from infrastructure.tushare_relay import RelayConfig, canonical, query, read_isolated_sample, sha256
from ops.audit_tushare_capabilities import menu_items, parse_doc, probe


class Response:
    def __init__(self, status=200, content=b""):
        self.status_code = status
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset:offset + chunk_size]


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        item = next(self.responses)
        if isinstance(item, BaseException):
            raise item
        return item


def test_config_requires_private_file_and_never_displays_token(tmp_path):
    env = tmp_path / "credentials.env"
    env.write_text("TUSHARE_TOKEN=secret-value\nTUSHARE_HTTP_URL=https://relay.test/sdk\n")
    env.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        RelayConfig.from_file(env)
    env.chmod(0o600)
    cfg = RelayConfig.from_file(env)
    assert "secret-value" not in repr(cfg)
    assert cfg.primary == "https://relay.test/sdk"
    env.write_text("TUSHARE_TOKEN=secret-value\nTUSHARE_HTTP_URL=https://relay.test/sdk?key=oops\n")
    with pytest.raises(ValueError, match="HTTPS URL"):
        RelayConfig.from_file(env)


def test_redirect_and_permission_failure_do_not_fallback_or_leak():
    cfg = RelayConfig("secret-value", "https://primary.test/sdk", "https://backup.test/sdk")
    redirect = Session([Response(307)])
    assert query(cfg, "daily", {}, allow_fallback=True, session=redirect)["status"] == "REDIRECT_REJECTED"
    assert len(redirect.calls) == 1
    body = canonical({"code": -1, "msg": "权限不足 secret-value"})
    denied = Session([Response(content=body)])
    value = query(cfg, "daily", {}, allow_fallback=True, session=denied)
    assert value["status"] == "ACCESS_DENIED"
    assert "secret-value" not in json.dumps(value)
    assert len(denied.calls) == 1


def test_transport_only_fallback_and_sdk_wire_shape():
    cfg = RelayConfig("private-token", "https://primary.test/sdk", "https://backup.test/sdk")
    body = canonical({"code": 0, "data": {"fields": ["name"], "items": [["private-token"]]}})
    sess = Session([requests.exceptions.Timeout(), Response(content=body)])
    value = query(cfg, "daily", {"limit": 1}, allow_fallback=True, session=sess)
    assert value["endpoint_role"] == "fallback"
    assert value["data"]["items"] == [["[REDACTED]"]]
    assert len(sess.calls) == 2
    assert sess.calls[1][0] == "https://backup.test/sdk/daily"
    assert sess.calls[1][1]["json"]["params"]["ts_type_name"] == "https://backup.test/sdk"
    assert sess.calls[1][1]["allow_redirects"] is False


def test_response_bounds_and_shape_fail_closed():
    cfg = RelayConfig("token-1", "https://relay.test/sdk")
    huge = Session([Response(content=b"x" * 1025)])
    assert query(cfg, "daily", {}, max_bytes=1024, session=huge)["status"] == "RESPONSE_TOO_LARGE"
    malformed = Session([Response(content=canonical({"code": 0, "data": {"fields": ["x"], "items": [[1, 2]]}}))])
    assert query(cfg, "daily", {}, session=malformed)["status"] == "MALFORMED_RESPONSE"
    empty = Session([Response(content=canonical({"code": 0, "data": {"fields": ["x"], "items": []}}))])
    assert query(cfg, "daily", {}, session=empty)["status"] == "EMPTY_RESPONSE"


def test_menu_and_document_keep_unknown_pages_and_parameters():
    html = b'<div id="jstree"><ul><li><a href="/document/2?doc_id=14">Cat</a><ul><li><a href="/document/2?doc_id=27">Daily</a></li></ul></li><li><a href="/document/2?doc_id=27">Daily</a></li></ul></div>'
    entries = menu_items(html)
    assert len(entries) == 2
    item = next(x for x in entries if x["doc_id"] == 27)
    doc = b'<div class="content"><h2>Daily</h2><p>\xe6\x8e\xa5\xe5\x8f\xa3\xef\xbc\x9adaily</p><p>\xe8\xbe\x93\xe5\x85\xa5\xe5\x8f\x82\xe6\x95\xb0</p><table><thead><tr><th>name</th><th>\xe5\xbf\x85\xe9\x80\x89</th></tr></thead><tbody><tr><td>ts_code</td><td>Y</td></tr></tbody></table><pre>pro.daily(ts_code="000001.SZ")</pre></div>'
    parsed = parse_doc(doc, item, "today")
    assert parsed["api_name"] == "daily"
    assert parsed["input_tables"][0]["rows"] == [["ts_code", "Y"]]
    assert parsed["example_literal_calls"] == [{"ts_code": "000001.SZ"}]
    unknown = parse_doc(b'<div class="content"><h2>Intro</h2></div>', item, "today")
    assert unknown["doc_status"] == "API_NOT_IDENTIFIED"


def setup_report(tmp_path: Path):
    catalog = {"records": [{"doc_id": 335, "api_name": "index_member_all", "doc_status": "DOCUMENTED_NOT_PROBED"},
                           {"doc_id": 27, "api_name": "daily", "doc_status": "DOCUMENTED_NOT_PROBED"}]}
    (tmp_path / "official_catalog.json").write_bytes(canonical(catalog))
    prior = tmp_path / "prior.json"
    prior.write_bytes(b"existing evidence")
    receipt = {"time": "2026-11-08T21:54:17+08:00", "results": [{"role": "primary", "endpoint": "https://relay.test/sdk",
        "api": "daily", "params": {"ts_code": "000001.SZ", "trade_date": "20260930"},
        "status": "PASS_RESPONSE_STRUCTURE", "artifact": str(prior), "sha256": sha256(prior.read_bytes()), "rows": 1}]}
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_bytes(canonical(receipt))
    return receipt_path


def test_probe_checkpoint_artifact_and_no_duplicate_call(tmp_path):
    receipt = setup_report(tmp_path)
    cfg = RelayConfig("token-1", "https://relay.test/sdk")
    result = {"endpoint": cfg.primary, "endpoint_role": "primary", "http_status": 200, "provider_code": 0,
              "status": "SUCCESS_RESPONSE", "row_count": 1, "data": {"fields": ["ts_code"], "items": [["000001.SZ"]]}}
    with patch("ops.audit_tushare_capabilities.query", return_value=result) as send, patch("ops.audit_tushare_capabilities.time.sleep"):
        probe(tmp_path, cfg, ["index_member_all"], receipt, 3, False)
        probe(tmp_path, cfg, ["index_member_all"], receipt, 3, False)
    assert send.call_count == 1
    report = json.loads((tmp_path / "capability_report.json").read_text())
    row = report["probes"]["index_member_all"]
    sample_path = tmp_path / row["artifact"]
    assert row["artifact_sha256"] == sha256(sample_path.read_bytes())
    sample = json.loads(sample_path.read_text())
    assert sample["pit_status"] == "CANNOT_CONFIRM"
    assert sample["production_allowed"] is False
    assert report["page_status_counts"]["PRIOR_SUCCESS_RESPONSE"] == 1
    assert read_isolated_sample(tmp_path, "index_member_all") == sample
    sample_path.write_text("{}")
    with pytest.raises(ValueError, match="sample identity mismatch"):
        read_isolated_sample(tmp_path, "index_member_all")
    with pytest.raises(ValueError, match="credential changed"):
        probe(tmp_path, RelayConfig("other-token", cfg.primary), ["index_member_all"], receipt, 3, False)


def test_interrupted_request_is_not_replayed(tmp_path):
    receipt = setup_report(tmp_path)
    cfg = RelayConfig("token-1", "https://relay.test/sdk")
    with patch("ops.audit_tushare_capabilities.query", side_effect=RuntimeError("simulated crash")):
        with pytest.raises(RuntimeError):
            probe(tmp_path, cfg, ["index_member_all"], receipt, 3, False)
    with patch("ops.audit_tushare_capabilities.query") as send:
        probe(tmp_path, cfg, ["index_member_all"], receipt, 3, False)
    assert send.call_count == 0
    report = json.loads((tmp_path / "capability_report.json").read_text())
    assert report["probes"]["index_member_all"]["status"] == "INTERRUPTED_OUTCOME_UNKNOWN_NO_RETRY"
