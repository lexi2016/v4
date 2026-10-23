"""Manual loopback-only entry. No key creation, installation or self-start behavior."""
from __future__ import annotations

import argparse
import os
import socket
from pathlib import Path

from .gateway import Limits, create_app
from .saved_reader import Bindings, SavedReader


def main():
    parser = argparse.ArgumentParser(description="Local saved V4 reader; deployment needs separate approval.")
    parser.add_argument("--pool-root", type=Path, required=True)
    parser.add_argument("--workbench-root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8887)
    parser.add_argument("--concurrency", type=int, choices=[1, 2], default=1)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535 or args.port in {8873, 8910}:
        parser.error("GATEWAY_PORT_INVALID_OR_RESERVED")
    # This new dedicated name is the only secret this entry can read. Never inspect V4 or ChatGPT credentials.
    token = os.environ.get("V4_READONLY_API_TOKEN")
    if (not token or not 32 <= len(token) <= 256 or not token.isascii()
            or any(ch.isspace() for ch in token) or "test" in token.lower() or "placeholder" in token.lower()):
        parser.error("DEDICATED_NEW_SECRET_REQUIRED_AFTER_APPROVAL")
    for root in (args.pool_root, args.workbench_root):
        if not root.is_absolute() or not root.is_dir() or any(p.is_symlink() for p in (root, *root.parents)):
            parser.error("EXPLICIT_EXISTING_SAFE_DATA_ROOT_REQUIRED")
    import uvicorn

    app = create_app(SavedReader(Bindings(args.pool_root, args.workbench_root)),
                     lambda: os.environ.get("V4_READONLY_API_TOKEN"), limits=Limits(concurrency=args.concurrency))
    # Binding itself is the atomic conflict check. The original V4 socket is untouched.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", args.port))
        listener.listen(8)
        config = uvicorn.Config(app, access_log=False, log_level="warning", proxy_headers=False,
                                limit_concurrency=8, timeout_keep_alive=2)
        uvicorn.Server(config).run(sockets=[listener])


if __name__ == "__main__":
    main()
