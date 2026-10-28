import json
from datetime import datetime, timezone

import pytest

from v4.manager_workbench.inputs.capture import _body_page, content_url
from v4.manager_workbench.inputs.capture_store import CaptureStore


class Response:
    status_code = 200

    def __init__(self, url, content):
        self.url = url
        self.content = content


class Transport:
    def __init__(self, content=None, error=None):
        self.content = content
        self.error = error
        self.calls = 0

    def get(self, url, **_kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return Response(url, self.content)


def page(title="Current title"):
    return json.dumps({
        "success": 1,
        "data": {
            "art_code": "AN202610151830532649",
            "notice_title": title,
            "notice_date": "2026-10-15 18:30:00",
            "page_size": 1,
            "security": [{"market_uni": "116", "stock": "01371"}],
            "notice_content": "complete source body",
        },
    }).encode()


def validate_for(title):
    def validate(raw):
        listing = {
            "art_code": "AN202610151830532649",
            "title": title,
            "publication_date": "2026-10-15",
            "source_issuer_codes": [{"code": "HK.01371", "source_stock_code": "01371"}],
        }
        _body_page(raw, listing, page=1, total=None)
    return validate


def make_store(tmp_path, now="2026-10-16T14:57:00+08:00"):
    instant = datetime.fromisoformat(now)
    store = CaptureStore(tmp_path, clock=lambda: instant.astimezone(timezone.utc))
    store.grant(expires_at="2026-10-17T00:00:00+08:00")
    return store


def scopes(listing_sha):
    return {
        "protocol": "EASTMONEY_CONTENT_V1",
        "publication_date": "2026-10-15",
        "listing_sha256": listing_sha * 64,
    }


def test_changed_listing_metadata_reuses_verified_success_and_preserves_source_receipt(tmp_path):
    store = make_store(tmp_path)
    url = content_url("AN202610151830532649", 1)
    original_transport = Transport(page())
    old_raw, old_receipt = store.fetch(
        url, scope=scopes("a"), transport=original_transport,
        validate=validate_for("Current title"),
    )
    original_pointer = (tmp_path / "requests" / f"{old_receipt['request_sha256']}.json").read_bytes()
    reuse_scope = {"protocol": "EASTMONEY_CONTENT_V1", "publication_date": "2026-10-15"}
    blocked_transport = Transport(error=AssertionError("verified source cache should satisfy this request"))

    reused_raw, reused_receipt = store.fetch(
        url, scope=scopes("b"), transport=blocked_transport,
        validate=validate_for("Current title"), reusable_scope=reuse_scope,
        reuse_before="2026-10-16T14:57:00+08:00",
    )

    assert blocked_transport.calls == 0
    assert reused_raw == old_raw
    assert reused_receipt["request"]["scope"] == scopes("b")
    assert reused_receipt["sha256"] == old_receipt["sha256"]
    assert reused_receipt["artifact_ref"] == old_receipt["artifact_ref"]
    assert reused_receipt["available_at"] == old_receipt["available_at"]
    assert reused_receipt["reused_from"] == {
        "request_sha256": old_receipt["request_sha256"],
        "receipt_sha256": old_receipt["receipt_sha256"],
        "artifact_ref": old_receipt["artifact_ref"],
        "captured_at": old_receipt["captured_at"],
        "available_at": old_receipt["available_at"],
    }
    assert (tmp_path / "requests" / f"{old_receipt['request_sha256']}.json").read_bytes() == original_pointer

    again, cached = store.fetch(
        url, scope=scopes("b"), transport=blocked_transport,
        validate=validate_for("Current title"), reusable_scope=reuse_scope,
        reuse_before="2026-10-16T14:57:00+08:00",
    )
    assert blocked_transport.calls == 0
    assert again == old_raw
    assert cached["receipt_sha256"] == reused_receipt["receipt_sha256"]


def test_reuse_revalidates_against_current_listing_before_selecting_old_body(tmp_path):
    store = make_store(tmp_path)
    url = content_url("AN202610151830532649", 1)
    store.fetch(url, scope=scopes("a"), transport=Transport(page("Old title")),
                validate=validate_for("Old title"))
    current_transport = Transport(page("Current title"))

    raw, receipt = store.fetch(
        url, scope=scopes("b"), transport=current_transport,
        validate=validate_for("Current title"),
        reusable_scope={"protocol": "EASTMONEY_CONTENT_V1", "publication_date": "2026-10-15"},
        reuse_before="2026-10-16T14:57:00+08:00",
    )

    assert current_transport.calls == 1
    assert json.loads(raw)["data"]["notice_title"] == "Current title"
    assert "reused_from" not in receipt


def test_reuse_does_not_cross_research_cutoff(tmp_path):
    store = make_store(tmp_path, now="2026-10-16T15:00:00+08:00")
    url = content_url("AN202610151830532649", 1)
    store.fetch(url, scope=scopes("a"), transport=Transport(page()),
                validate=validate_for("Current title"))
    current_transport = Transport(page())

    store.fetch(
        url, scope=scopes("b"), transport=current_transport,
        validate=validate_for("Current title"),
        reusable_scope={"protocol": "EASTMONEY_CONTENT_V1", "publication_date": "2026-10-15"},
        reuse_before="2026-10-16T14:57:00+08:00",
    )

    assert current_transport.calls == 1


def test_failed_receipt_is_not_a_negative_cache_and_a_later_call_can_succeed(tmp_path):
    store = make_store(tmp_path)
    url = content_url("AN202610151830532649", 1)
    failed = Transport(error=RuntimeError("temporary connection reset"))
    with pytest.raises(RuntimeError):
        store.fetch(url, scope=scopes("a"), transport=failed,
                    validate=validate_for("Current title"))
    successful = Transport(page())

    raw, _receipt = store.fetch(url, scope=scopes("a"), transport=successful,
                               validate=validate_for("Current title"))

    assert failed.calls == successful.calls == 1
    assert json.loads(raw)["data"]["notice_content"] == "complete source body"
