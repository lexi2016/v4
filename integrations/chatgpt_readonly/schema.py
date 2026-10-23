"""Export JSON-compatible YAML 1.2 OpenAPI without a server, data or credentials."""
from __future__ import annotations

import json
from pathlib import Path

from .gateway import create_app, openapi_document


def main():
    app = create_app(None, lambda: None)
    target = Path(__file__).with_name("openapi.yaml")
    target.write_text(json.dumps(openapi_document(app), ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
