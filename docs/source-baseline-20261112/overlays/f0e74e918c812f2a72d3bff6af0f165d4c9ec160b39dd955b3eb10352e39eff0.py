import argparse
import os
from pathlib import Path

import uvicorn

from apps.api.v4_api.app import create_app
from infrastructure.logging_config import setup_json_logging
from infrastructure.runtime import ServerConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the V4 loopback API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8873, type=int)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--preselection-source-root", type=Path)
    parser.add_argument("--shared-data-root", type=Path)
    parser.add_argument("--ledger-root", type=Path)
    parser.add_argument("--stage-selection-root", type=Path)
    parser.add_argument(
        "--stage-mode", choices=("shared", "local"),
        default=os.environ.get("V4_STAGE_MODE", "shared"),
        help="shared consumes stage artifacts; local explicitly enables the local producer",
    )
    arguments = parser.parse_args()
    stage_root = arguments.stage_selection_root or (
        Path(os.environ["V4_STAGE_CENTER_SELECTION_ROOT"])
        if os.environ.get("V4_STAGE_CENTER_SELECTION_ROOT") else None
    )
    if arguments.stage_mode not in {"shared", "local"}:
        parser.error("V4_STAGE_MODE must be shared or local")
    if arguments.stage_mode == "shared" and stage_root is None:
        parser.error("shared stage mode requires --stage-selection-root or V4_STAGE_CENTER_SELECTION_ROOT")
    if arguments.stage_mode == "local" and stage_root is not None:
        parser.error("local stage mode cannot also consume a shared stage root")
    config = ServerConfig(host=arguments.host, port=arguments.port)
    data_root = arguments.data_root or (
        Path(os.environ["V4_DATA_ROOT"]) if os.environ.get("V4_DATA_ROOT") else None
    )
    shared_data_root = arguments.shared_data_root or (
        Path(os.environ["V4_SHARED_DATA_ROOT"])
        if os.environ.get("V4_SHARED_DATA_ROOT")
        else None
    )
    ledger_root = arguments.ledger_root or (
        Path(os.environ["V4_DISPATCH_LEDGER_ROOT"])
        if os.environ.get("V4_DISPATCH_LEDGER_ROOT")
        else None
    )
    setup_json_logging()
    uvicorn.run(
        create_app(
            data_root=data_root,
            preselection_source_root=arguments.preselection_source_root,
            shared_data_root=shared_data_root,
            ledger_root=ledger_root,
            stage_center_selection_root=stage_root,
        ),
        host=config.host,
        port=config.port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
