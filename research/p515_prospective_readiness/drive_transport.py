"""Authenticated Google Drive v3 transport for a future authorized operator."""
from __future__ import annotations

from collections.abc import Callable
import json
import re
import secrets
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .drive_store import DriveEvidenceError

_FIELDS = "id,name,mimeType,size,parents,createdTime,modifiedTime,version,headRevisionId"
_FILES = "https://www.googleapis.com/drive/v3/files"
_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
_LIMIT = 64 * 1024 * 1024
_ID = re.compile(r"[A-Za-z0-9_-]+")


class _NoRedirect(HTTPRedirectHandler):
    # Never forward an Authorization header to a different server.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _file_id(raw):
    if not isinstance(raw, str) or not _ID.fullmatch(raw):
        raise DriveEvidenceError("invalid Drive identifier")
    return raw


class DriveV3RestTransport:
    """Uses an operator-supplied authorized token provider. No default credentials."""

    def __init__(self, access_token: Callable[[], str]):
        self._token = access_token
        self._opener = build_opener(_NoRedirect())

    def _request(self, endpoint, params, *, data=None, content_type=None):
        auth = self._token()
        if not isinstance(auth, str) or not auth or any(ch.isspace() for ch in auth):
            raise DriveEvidenceError("Drive access token unavailable")
        headers = {"Authorization": "Bearer " + auth, "Accept-Encoding": "identity"}
        if content_type:
            headers["Content-Type"] = content_type
        request = Request(endpoint + "?" + urlencode(params), data=data, headers=headers)
        try:
            with self._opener.open(request, timeout=20) as response:
                raw = response.read(_LIMIT + 1)
        except HTTPError as exc:
            raise DriveEvidenceError(f"Drive request failed with HTTP {exc.code}") from None
        except (OSError, URLError):
            raise DriveEvidenceError("Drive request network failure; upload outcome may be uncertain") from None
        if len(raw) > _LIMIT:
            raise DriveEvidenceError("Drive response exceeded bounded artifact limit")
        return raw

    def get_file_metadata(self, file_id):
        return json.loads(self._request(
            f"{_FILES}/{_file_id(file_id)}", {"fields": _FIELDS, "supportsAllDrives": "true"}
        ))

    def download_media(self, file_id):
        return self._request(
            f"{_FILES}/{_file_id(file_id)}", {"alt": "media", "supportsAllDrives": "true"}
        )

    def list_revisions(self, file_id):
        endpoint = f"{_FILES}/{_file_id(file_id)}/revisions"
        query = {"fields": "nextPageToken,revisions(id,modifiedTime,size)", "pageSize": "1000"}
        items = []
        for _ in range(4):
            page = json.loads(self._request(endpoint, query))
            items.extend(page.get("revisions", []))
            token = page.get("nextPageToken")
            if not token:
                return items
            query["pageToken"] = token
        raise DriveEvidenceError("incomplete Drive revisions after bounded pagination")

    def create_file(self, *, name, parent_id, mime_type, content):
        if not isinstance(content, bytes) or len(content) > _LIMIT:
            raise DriveEvidenceError("upload content must be bounded raw bytes")
        if not re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+-]+", mime_type):
            raise DriveEvidenceError("invalid binary Drive media type")
        boundary = "p515_" + secrets.token_hex(24)
        marker = b"--" + boundary.encode("ascii")
        metadata = json.dumps({"name": name, "mimeType": mime_type, "parents": [_file_id(parent_id)]},
                              ensure_ascii=False).encode("utf-8")
        body = (marker + b"\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n" + metadata
                + b"\r\n" + marker + b"\r\nContent-Type: " + mime_type.encode("ascii")
                + b"\r\n\r\n" + content + b"\r\n" + marker + b"--\r\n")
        return json.loads(self._request(
            _UPLOAD, {"uploadType": "multipart", "supportsAllDrives": "true", "fields": _FIELDS},
            data=body, content_type="multipart/related; boundary=" + boundary,
        ))
