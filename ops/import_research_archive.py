"""Import an explicit frozen research snapshot without mutating the source."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from domains.research import build_research_archive
from infrastructure.research_store import ResearchArchiveStore


def import_research_archive_file(
    *,
    data_root: Path,
    source: Path,
    mode: str = "BACKFILL",
) -> dict[str, Any]:
    raw = source.read_bytes()
    before = hashlib.sha256(raw).hexdigest()
    source_payload = json.loads(raw.decode("utf-8-sig"))
    archive = build_research_archive(source_payload, source_input_sha256=before)
    publication = ResearchArchiveStore(data_root).publish(archive, mode=mode)
    after = hashlib.sha256(source.read_bytes()).hexdigest()
    if after != before:
        raise ValueError("external research source changed during read-only import")
    return {
        "archive": archive,
        "publication": publication,
        "external_source_sha256": before,
        "external_source_unchanged": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a frozen V3 research archive into V3.5")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--mode", choices=("LIVE", "REPLAY", "BACKFILL"), default="BACKFILL")
    args = parser.parse_args()
    result = import_research_archive_file(
        data_root=args.data_root,
        source=args.source,
        mode=args.mode,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
