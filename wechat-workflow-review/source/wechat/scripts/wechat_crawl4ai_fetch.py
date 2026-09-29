"""Optional, read-only Crawl4AI transport for one public WeChat article.

This module is deliberately a transport helper.  It returns the browser's raw
HTML to the existing intake identity and image gates; it does not use
``fit_markdown`` or any content scoring as an admission decision.  Importing
the module does not import Crawl4AI, so the normal urllib path stays fast and
works when the optional package or browser is absent.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


def _article_token(url: str) -> str:
    try:
        parsed = urlsplit(str(url or ""))
    except ValueError:
        return ""
    match = re.fullmatch(r"/s/([A-Za-z0-9_-]{1,256})/?", parsed.path or "")
    if parsed.scheme.lower() != "https" or parsed.hostname != "mp.weixin.qq.com" or not match:
        return ""
    return match.group(1)


def _same_article_url(requested: str, observed: str) -> bool:
    if not observed:
        return True
    expected = _article_token(requested)
    actual = _article_token(observed)
    return bool(expected and actual and expected == actual)


def _chrome_executable() -> Path | None:
    """Use the installed browser binary only; never inspect a user profile."""

    candidate = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    return candidate if candidate.is_file() else None


def _browser_config():
    from crawl4ai import BrowserConfig

    kwargs = {"headless": True, "browser_type": "chromium"}
    executable = _chrome_executable()
    if executable is not None:
        # Crawl4AI delegates launch to Playwright, which exposes installed
        # Google Chrome through the channel name instead of an executable
        # path.  This still selects the system binary without opening its
        # profile; persistent context and storage_state remain unset.
        kwargs["chrome_channel"] = "chrome"
        kwargs["channel"] = "chrome"
    try:
        return BrowserConfig(**kwargs)
    except TypeError:
        # Crawl4AI releases differ on whether BrowserConfig exposes a channel.
        # Retry with the common subset, still headless and isolated from the
        # user's Chrome profile.
        kwargs.pop("chrome_channel", None)
        kwargs.pop("channel", None)
        try:
            return BrowserConfig(**kwargs)
        except TypeError:
            kwargs.pop("browser_type", None)
            return BrowserConfig(**kwargs)


async def _run_crawler(url: str, timeout: int):
    # Crawl4AI 0.9.3 constructs RobotsParser() without forwarding the
    # AsyncWebCrawler base_directory.  Set its dedicated base-directory
    # variable before importing the package so import-time DB/version state
    # and the robots cache all stay inside this disposable directory.  HOME,
    # user profiles, cookies, and persistent browser storage are untouched.
    previous_base = os.environ.get("CRAWL4_AI_BASE_DIRECTORY")
    with tempfile.TemporaryDirectory(prefix="wechat-crawl4ai-") as base_directory:
        os.environ["CRAWL4_AI_BASE_DIRECTORY"] = base_directory
        try:
            from crawl4ai import AsyncWebCrawler

            browser_config = _browser_config()
            run_config = None
            try:
                from crawl4ai import CrawlerRunConfig

                try:
                    run_config = CrawlerRunConfig(wait_until="domcontentloaded")
                except TypeError:
                    run_config = CrawlerRunConfig()
            except (ImportError, AttributeError):
                run_config = None

            async with AsyncWebCrawler(config=browser_config, base_directory=base_directory) as crawler:
                if run_config is None:
                    call = crawler.arun(url=url)
                else:
                    call = crawler.arun(url=url, config=run_config)
                if inspect.isawaitable(call):
                    return await asyncio.wait_for(call, timeout=max(1, int(timeout)))
                return call
        finally:
            if previous_base is None:
                os.environ.pop("CRAWL4_AI_BASE_DIRECTORY", None)
            else:
                os.environ["CRAWL4_AI_BASE_DIRECTORY"] = previous_base


def fetch_html(url: str, timeout: int = 60) -> tuple[str, int, str]:
    """Fetch one URL in a fresh headless browser context and return raw HTML."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError("Crawl4AI transport must be called from synchronous intake code")

    try:
        result = asyncio.run(_run_crawler(url, timeout))
    except Exception as exc:  # noqa: BLE001
        return "", 0, f"{type(exc).__name__}: {exc}"

    html_text = str(getattr(result, "html", "") or "")
    status = int(getattr(result, "status_code", 200 if html_text else 0) or 0)
    error = str(getattr(result, "error_message", "") or "")
    # Crawl4AI 0.9.3 keeps the requested URL in ``result.url``.  The
    # redirect/final fields carry the navigation result and must win when
    # present, otherwise a redirect to another article would be accepted.
    observed_url = str(
        getattr(result, "redirected_url", "")
        or getattr(result, "final_url", "")
        or getattr(result, "url", "")
        or ""
    )
    if observed_url and not _same_article_url(url, observed_url):
        return html_text, status, f"Crawl4AI redirected to a different article: {observed_url}"
    if not html_text:
        return "", status, error or "Crawl4AI returned empty HTML"
    if not bool(getattr(result, "success", True)):
        return html_text, status, error or "Crawl4AI reported unsuccessful navigation"
    return html_text, status, error


__all__ = ["fetch_html"]
