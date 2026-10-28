"""ops.materialize_research_peripherals: google_redirects (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _decode_google_news_url_body(_v4_scope, /, source_url, timeout, *, opener):
    """Resolve one Google News discovery URL to the publisher article URL.

    Google News serves signed redirect parameters in the article page.  The
    read-only ``Fbv4je`` endpoint converts those parameters to the publisher
    URL; the result is rejected unless it is a non-Google HTTP(S) URL.
    """
    parsed = _v4_global(_v4_scope, 'urllib').parse.urlsplit(_v4_global(_v4_scope, 'str')(source_url or ""))
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.hostname != "news.google.com" or _v4_global(_v4_scope, 'len')(parts) < 2 or parts[-2] not in {
        "articles",
        "read",
    }:
        return _v4_global(_v4_scope, 'str')(source_url or "")
    token = parts[-1]
    params: dict[str, str] = {}
    for prefix in (
        "https://news.google.com/articles/",
        "https://news.google.com/rss/articles/",
    ):
        request = _v4_global(_v4_scope, 'urllib').request.Request(
            prefix + token,
            headers={"User-Agent": _v4_global(_v4_scope, 'USER_AGENT')},
        )
        try:
            with opener(request, timeout=timeout) as response:
                page = response.read().decode("utf-8", errors="replace")
        except (_v4_global(_v4_scope, 'TimeoutError'), _v4_global(_v4_scope, 'urllib').error.URLError, _v4_global(_v4_scope, 'OSError')):
            continue
        parser = _v4_global(_v4_scope, '_GoogleNewsParamsParser')()
        parser.feed(page)
        if parser.params:
            params = parser.params
            break
    signature = params.get("data-n-a-sg")
    timestamp = params.get("data-n-a-ts")
    if not signature or not timestamp or not timestamp.isdigit():
        raise _v4_global(_v4_scope, 'ValueError')("Google News decoding parameters unavailable")
    request_payload = [
        "garturlreq",
        [
            [
                "X",
                "X",
                ["X", "X"],
                None,
                None,
                1,
                1,
                "US:en",
                None,
                1,
                None,
                None,
                None,
                None,
                None,
                0,
                1,
            ],
            "X",
            "X",
            1,
            [1, 1, 1],
            1,
            1,
            None,
            0,
            0,
            None,
            0,
        ],
        token,
        _v4_global(_v4_scope, 'int')(timestamp),
        signature,
    ]
    rpc = [
        "Fbv4je",
        _v4_global(_v4_scope, 'json').dumps(request_payload, ensure_ascii=False, separators=(",", ":")),
        None,
        "generic",
    ]
    body = _v4_global(_v4_scope, 'urllib').parse.urlencode(
        {"f.req": _v4_global(_v4_scope, 'json').dumps([[rpc]], ensure_ascii=False, separators=(",", ":"))}
    ).encode("utf-8")
    request = _v4_global(_v4_scope, 'urllib').request.Request(
        "https://news.google.com/_/DotsSplashUi/data/batchexecute",
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "User-Agent": _v4_global(_v4_scope, 'USER_AGENT'),
        },
    )
    with opener(request, timeout=timeout) as response:
        response_text = response.read().decode("utf-8", errors="replace")
    chunks = response_text.split("\n\n")
    if _v4_global(_v4_scope, 'len')(chunks) < 2:
        raise _v4_global(_v4_scope, 'ValueError')("Google News decoder response is incomplete")
    records = _v4_global(_v4_scope, 'json').loads(chunks[1])
    decoded = ""
    for record in records:
        if not _v4_global(_v4_scope, 'isinstance')(record, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'len')(record) < 3 or not record[2]:
            continue
        inner = _v4_global(_v4_scope, 'json').loads(record[2])
        if _v4_global(_v4_scope, 'isinstance')(inner, _v4_global(_v4_scope, 'list')) and _v4_global(_v4_scope, 'len')(inner) > 1:
            decoded = _v4_global(_v4_scope, 'str')(inner[1] or "").strip()
            if decoded:
                break
    final = _v4_global(_v4_scope, 'urllib').parse.urlsplit(decoded)
    if (
        final.scheme not in {"http", "https"}
        or not final.hostname
        or final.hostname == "news.google.com"
    ):
        raise _v4_global(_v4_scope, 'ValueError')("Google News decoder did not return a publisher URL")
    return decoded
