"""Transport request shape without credentials or network."""
import io
import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from research.p515_prospective_readiness.drive_store import (
    DriveEvidenceError, DriveFileExpectation, sha256_bytes, verify_google_drive_readback,
)
from research.p515_prospective_readiness.drive_transport import DriveV3RestTransport


def test_official_v3_requests_share_one_transport():
    backend = DriveV3RestTransport(lambda: "synthetic-token")
    requests = []

    def send(request, timeout):
        requests.append(request)
        url = urlsplit(request.full_url)
        query = parse_qs(url.query)
        assert url.netloc == "www.googleapis.com"
        if url.path.endswith("/revisions"):
            return io.BytesIO(b'{"revisions":[{"id":"R1","modifiedTime":"2026-11-18T12:00:00Z"}]}')
        if query.get("alt") == ["media"]:
            return io.BytesIO(b"data")
        return io.BytesIO(b'{"id":"f1","version":"2"}')

    backend._opener.open = send
    assert backend.get_file_metadata("f1")["version"] == "2"
    assert backend.list_revisions("f1")[0]["id"] == "R1"
    assert backend.download_media("f1") == b"data"
    created = backend.create_file(name="fixture.json", parent_id="f0",
                                  mime_type="application/json", content=b"fixture")
    assert created["id"] == "f1"
    assert [rq.get_method() for rq in requests] == ["GET", "GET", "GET", "POST"]
    multipart = requests[-1].data.split(b"\r\n\r\n")
    assert json.loads(multipart[1].split(b"\r\n", 1)[0])["parents"] == ["f0"]
    assert multipart[2].split(b"\r\n", 1)[0] == b"fixture"
    with pytest.raises(DriveEvidenceError, match="invalid Drive identifier"):
        backend.download_media("../other")
    assert len(requests) == 4


@pytest.mark.parametrize(("different", "changed_bytes", "observed_hour", "message"), [
    ({"parents": ["wrong"]}, b"fixture", 12, "parent directory mismatch"),
    ({}, b"differs", 12, "SHA256 mismatch"),
    (None, b"fixture", 12, "version changed"),
    ({}, b"fixture", 14, "after the required deadline"),
    ({}, b"fixture", 10, "predates Drive modifiedTime"),
])
def test_remote_readback_evidence_rejects_faults(different, changed_bytes, observed_hour, message):
    base = dict(id="f1", name="fixed.json", mimeType="application/json", parents=["parent"], size="7",
                createdTime="2026-11-18T11:21:43Z", modifiedTime="2026-11-18T11:21:43Z",
                version="3", headRevisionId="rev")
    if different is None:
        before, after = base, dict(base, version="4")
    else:
        before = after = {**base, **different}
    expectation = DriveFileExpectation(
        "f1", "fixed.json", "parent", "application/json", sha256_bytes(b"fixture"), 7,
        expected_version="3", readback_not_after=datetime(2026, 11, 18, 13, tzinfo=timezone.utc),
    )
    with pytest.raises(DriveEvidenceError, match=message):
        verify_google_drive_readback(
            before, changed_bytes, after, expected=expectation,
            observed_at=datetime(2026, 11, 18, observed_hour, tzinfo=timezone.utc),
        )
