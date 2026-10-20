"""Build only the two reviewed source overlays; never modify a retained release.

Usage: python build_runtime_overlay.py --base-app <retained-app> --output <new-dir>
The parent integrator must bind a complete new release and its inventory separately.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE_ROOT = HERE.parents[2]
FILES = {
    "infrastructure/scheduling/executor_registry_preselection.py": SOURCE_ROOT / "infrastructure/scheduling/executor_registry_preselection.py",
    "ops/materialize_scheduled_preselection.py": HERE / "runtime_overlay/ops/materialize_scheduled_preselection.py",
}

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def build(base_app: Path, output: Path):
    base_app, output = base_app.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(base_app.parent) or base_app.is_relative_to(output):
        raise ValueError("output must be a new directory outside the retained release tree")
    receipt = json.loads((HERE / "writer_receipt.json").read_text())
    payloads = {}
    for relative, source in FILES.items():
        pins = receipt["runtime_files"][relative]
        if sha((base_app / relative).read_bytes()) != pins["before_sha256"]:
            raise ValueError("retained runtime baseline mismatch: " + relative)
        raw = source.read_bytes()
        if sha(raw) != pins["after_sha256"]:
            raise ValueError("reviewed overlay source mismatch: " + relative)
        compile(raw, relative, "exec")
        payloads[relative] = raw
    output.mkdir(parents=True, exist_ok=False)
    for relative, raw in payloads.items():
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    result = {"output": str(output), "files": {p: sha(raw) for p, raw in payloads.items()},
        "status": "OVERLAY_BUILT_NOT_DEPLOYED", "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    print(json.dumps(result, sort_keys=True))
    return result

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-app", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.base_app, args.output)
