import argparse
import os
from pathlib import Path

import uvicorn

from apps.api.v35_api.app import create_app
from apps.api.v35_api.module_proxy import load_module_contract
from infrastructure.logging_config import setup_json_logging
from infrastructure.runtime import ServerConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the V4 gateway or one isolated API module")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int)
    parser.add_argument(
        "--role", choices=("gateway", "stage", "manager", "combined"),
        default=os.environ.get("V35_API_ROLE", "gateway"),
    )
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--shared-data-root", type=Path)
    parser.add_argument("--ledger-root", type=Path)
    parser.add_argument("--stage-selection-root", type=Path)
    parser.add_argument(
        "--stage-mode", choices=("shared", "local"),
        default=os.environ.get("V35_STAGE_MODE", "shared"),
        help="shared consumes stage artifacts; local explicitly enables the local producer",
    )
    arguments = parser.parse_args()
    if arguments.role == "combined":
        role_target = {"host": "127.0.0.1", "port": 8873}
    else:
        role_target = load_module_contract()["roles"][arguments.role]
    if arguments.host != role_target["host"]:
        parser.error("the selected API role only binds to its contracted loopback host")
    if arguments.port is not None and arguments.port != role_target["port"]:
        parser.error("the selected API role only binds to its contracted port")
    port = role_target["port"]
    stage_root = arguments.stage_selection_root or (
        Path(os.environ["V35_STAGE_CENTER_SELECTION_ROOT"])
        if os.environ.get("V35_STAGE_CENTER_SELECTION_ROOT") else None
    )
    if arguments.stage_mode not in {"shared", "local"}:
        parser.error("V35_STAGE_MODE must be shared or local")
    if arguments.role != "combined" and arguments.stage_mode != "shared":
        parser.error("isolated API roles require shared Stage selection mode")
    if arguments.stage_mode == "shared" and stage_root is None:
        parser.error("shared stage mode requires --stage-selection-root or V35_STAGE_CENTER_SELECTION_ROOT")
    if arguments.stage_mode == "local" and stage_root is not None:
        parser.error("local stage mode cannot also consume a shared stage root")
    config = ServerConfig(host=arguments.host, port=port)
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
            stage_center_selection_root=stage_root,
            module_role=arguments.role,
        ),
        host=config.host,
        port=config.port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
