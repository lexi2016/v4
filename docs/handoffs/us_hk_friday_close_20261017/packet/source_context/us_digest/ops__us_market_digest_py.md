## Source excerpt: `ops/us_market_digest.py`

Original source path: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/futu-industry-us-20261016-r1/app/ops/us_market_digest.py`

Original full-file SHA-256: `96b15646e35fad6e399edb61eb8c3bd8d20b52141323e0bb1ce477b7313bcaf8`

Release/worktree group: `us_digest`

Deployed US digest module entrypoint.

### Full-source lines 725-727

```python

def main(argv: Sequence[str] | None = None) -> int:
    from ops._us_market_digest_parts.cli_primitives import _main_body as _v4_impl
    return _v4_impl(globals(), argv)

```
