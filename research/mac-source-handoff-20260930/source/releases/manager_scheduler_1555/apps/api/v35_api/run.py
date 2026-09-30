import argparse
import os
from pathlib import Path

import uvicorn

from apps.api.v35_api.app import create_app
from infrastructure.logging_config import setup_json_logging
from infrastructure.runtime import ServerConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the V3.5 loopback API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8873, type=int)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--shared-data-root", type=Path)
    parser.add_argument("--ledger-root", type=Path)
    parser.add_argument("--stage-selection-root", type=Path)
    arguments = parser.parse_args()
    config = ServerConfig(host=arguments.host, port=arguments.port)
    data_root = arguments.data_root or (
        Path(os.environ["V35_DATA_ROOT"]) if os.environ.get("V35_DATA_ROOT") else None
    )
    shared_data_root = arguments.shared_data_root or (
        Path(os.environ["V35_SHARED_DATA_ROOT"])
        if os.environ.get("V35_SHARED_DATA_ROOT")
        else None
    )
    ledger_root = arguments.ledger_root or (
        Path(os.environ["V35_DISPATCH_LEDGER_ROOT"])
        if os.environ.get("V35_DISPATCH_LEDGER_ROOT")
        else None
    )
    setup_json_logging()
    uvicorn.run(
        create_app(
            data_root=data_root,
            shared_data_root=shared_data_root,
            ledger_root=ledger_root,
            stage_center_selection_root=arguments.stage_selection_root,
        ),
        host=config.host,
        port=config.port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
