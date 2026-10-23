# A23 six-quotes repair source snapshot

This directory preserves the frozen, independently reviewed source delta and the unchanged modules required by its facade. It contains one changed facade, its 12 unchanged split-module dependencies, the changed MAC daily adapter, and the focused test module.

This repository is a partial source archive. The `runtime-source/` path is for review and reproduction; it is not the application's active runtime entry or a deployed release. The local source baseline commit and the remote parent are recorded separately in `source-hashes.json`; the snapshot does not claim that those commits are the same source tree.

The independent review recorded PASS for 8 focused tests and a no-network replay of six cached candidates (6 accepted, 0 quarantined). The cached responses, quote files, test logs, and virtual environment are excluded. The test module contains small protocol-level fixture values.

To run the focused test from the repository root, use an environment that already provides `pytdx`:

```bash
PYTHONPATH='research/a23-six-quotes-repair-20261024/runtime-source:<existing-v4-site-packages>' <python> -S -m unittest discover -s research/a23-six-quotes-repair-20261024/tests -p test_a23_six_quotes_repair_20261024.py -v
```

The reported test result came from the reviewer task worktree and its existing package paths; this source archive was not tested as a clean standalone V4 checkout. Authority collection, panel/pointer readback, automatic scheduler binding/reload, natural recovery, and deployment remain unverified or not run. This snapshot does not change research or trading gates.
