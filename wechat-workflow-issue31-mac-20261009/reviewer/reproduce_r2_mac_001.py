#!/usr/bin/env python3
"""Replay the two minimal R2-MAC-001 reproductions against a candidate copy.

Only the candidate scripts and the supplied collector scripts are imported.
Promotion fixture files are created in a temporary directory and removed.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


def run_binding(fetch, collector) -> None:
    url = "https://mmbiz.qpic.cn/example/repeated"
    text_html = (
        f'<html><body><div id="js_content">正文'
        f'<img data-src="{url}"></div></body></html>'
    ).encode()
    fetch._validate_article_body(text_html, [])
    print("text_body_missing_manifest=ACCEPTED")

    image_html = (
        f'<html><body><div id="js_content">'
        f'<img data-src="{url}"><img data-src="{url}">'
        f"</div></body></html>"
    )
    manifest = [{"url": url}]
    print("external_collector_unique_images=", collector.extract_image_urls(image_html))
    try:
        fetch._validate_article_body(image_html.encode(), manifest)
    except ValueError as exc:
        print("candidate_image_only_duplicate=REJECTED:", exc)
    else:
        print("candidate_image_only_duplicate=ACCEPTED")


def run_promotion(fetch) -> None:
    url = "https://mp.weixin.qq.com/s/TokenABC"
    html = (
        b'<html><body><div id="js_content">body text'
        b'<img data-src="https://mmbiz.qpic.cn/example/missing">'
        b"</div></body></html>"
    )
    with tempfile.TemporaryDirectory(prefix="r2_mac_001_") as temp_dir:
        root = Path(temp_dir)
        (root / "wechat_article_raw.html").write_bytes(html)
        (root / "wechat_article_image_manifest.csv").write_text(
            "idx,url,sha256" + chr(10), encoding="utf-8-sig"
        )
        summary = {
            "article_url": url,
            "canonical_url": url,
            "canonical_token": "TokenABC",
            "title": "Fixture article",
            "account_name": "Fixture account",
            "biz": "fixture-biz",
            "article_date": "20261008",
            "content_hash": "a" * 40,
            "http_status": 200,
            "html_bytes": len(html),
            "article_body_found": True,
            "text_preview_length": 9,
            "image_count": 0,
            "downloaded_image_count": 0,
            "final_label": "WECHAT_RESEARCH_INTAKE_COMPLETE",
            "fetch_error": "",
            "html_path": str(root / "wechat_article_raw.html"),
            "image_manifest_path": str(root / "wechat_article_image_manifest.csv"),
        }
        (root / "wechat_article_intake_summary.json").write_text(
            json.dumps(summary), encoding="utf-8"
        )
        prepared = fetch._prepare_promotion(root, url, attempt_id="attempt_fixture")
        print(
            json.dumps(
                {
                    "promotion_validation": "ACCEPTED",
                    "body_has_image": b"<img" in html,
                    "manifest_rows": len(prepared["images"]),
                    "identity_image_count": prepared["identity"]["image_count"],
                    "raw_html_sha256": prepared["artifact_sha256"]["wechat_article_raw.html"],
                },
                ensure_ascii=False,
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate-scripts",
        required=True,
        type=Path,
        help="Path to the candidate scripts directory containing wechat_article_fetch.py",
    )
    parser.add_argument(
        "--collector-scripts",
        type=Path,
        help="Collector scripts directory; defaults to --candidate-scripts",
    )
    parser.add_argument(
        "--mode",
        choices=("binding", "promotion", "all"),
        default="all",
        help="Run one reproduction or both (default: all)",
    )
    args = parser.parse_args()

    candidate_scripts = args.candidate_scripts.expanduser().resolve()
    collector_scripts = (args.collector_scripts or candidate_scripts).expanduser().resolve()
    if not (candidate_scripts / "wechat_article_fetch.py").is_file():
        parser.error(f"no wechat_article_fetch.py in {candidate_scripts}")
    if not (collector_scripts / "wechat_article_intake.py").is_file():
        parser.error(f"no wechat_article_intake.py in {collector_scripts}")

    sys.dont_write_bytecode = True
    sys.path.insert(0, str(candidate_scripts))
    if collector_scripts != candidate_scripts:
        sys.path.insert(0, str(collector_scripts))
    import wechat_article_fetch as fetch
    import wechat_article_intake as collector

    if args.mode in ("binding", "all"):
        run_binding(fetch, collector)
    if args.mode in ("promotion", "all"):
        run_promotion(fetch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
