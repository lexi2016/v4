from pathlib import Path


def test_web_shell_declares_inline_favicon_to_keep_console_clean() -> None:
    shell = Path("apps/web/index.html").read_text(encoding="utf-8")

    assert '<link rel="icon" href="data:image/svg+xml,' in shell
