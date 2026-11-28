"""Synthetic boundary checks. This module never loads or invokes a VLM."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from research.act070a.case_contract import Rejected, json_bytes, strict_json
from research.act072m import contract
from research.act072m.run_case import _launch, child_environment, remove_outer_fence, reserve_attempt, user_message


def check_text():
    siblings = b'```json\n{}\n```\n```json\n{}\n```\n'
    spaced_siblings = b'```json\r\n{}\r\n   ```` \t\r\n```json\r\n{}\r\n```\r\n'
    for raw in (siblings, spaced_siblings):
        assert remove_outer_fence(raw) == (raw, "IDENTITY")
    for raw, desired in (
        (b'    {"claims": []}\n', b'    {"claims": []}\n'),
        (b'```json\n  {"claims": []}  \n```\n', b'  {"claims": []}  '),
        (b'```\r\n{"claims": []}\r\n```\r\n', b'{"claims": []}'),
        (b'preface\n```json\n{}\n```\n', b'preface\n```json\n{}\n```\n'),
        (b'```JSON\n{}\n```\n', b'```JSON\n{}\n```\n'),
        (b'```json\n{}\n```\n\n', b'```json\n{}\n```\n\n'),
        (b'', b''),
    ):
        assert remove_outer_fence(raw)[0] == desired
    sample = {name: f'{{"file":"{name}"}}\n' for name in contract.ATTACHMENTS[1:]}
    prompt = "合成 UTF-8 指令\n"
    messages = user_message(prompt, sample)
    assert len(messages) == 1 and messages[0]["role"] == "user"
    assert messages[0]["content"][0] == {"type": "text", "text": prompt}
    assert messages[0]["content"][1] == {"type": "image"}
    assert len(messages[0]["content"][2:]) == 3
    assert all(sample[name] in row["text"] and name in row["text"]
               for name, row in zip(contract.ATTACHMENTS[1:], messages[0]["content"][2:], strict=True))


def check_model_receipt(root: Path):
    stage = root / "model_receipt"
    model = stage / ".local_model" / contract.MODEL_REVISION
    model.mkdir(parents=True)
    weight = b"synthetic bytes"
    weight_sha = hashlib.sha256(weight).hexdigest()
    names = {"config.json": b"{}", "tokenizer_config.json": b"{}",
             "preprocessor_config.json": b"{}", "model.safetensors": weight}
    for name, payload in names.items():
        (model / name).write_bytes(payload)
    rows = [{"file": k, "bytes": len(v), "sha256": hashlib.sha256(v).hexdigest(), "publisher_sha_match": True}
            for k, v in sorted(names.items())]
    manifest = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    (stage / contract.MODEL_RECEIPT_NAME).write_bytes(json_bytes({
        "status": "VERIFIED_DOWNLOAD", "model_id": contract.MODEL_ID, "revision": contract.MODEL_REVISION,
        "weights_sha256": weight_sha, "network_inference_calls": 0, "files": rows,
        "manifest_sha256": manifest, "local_model_path": str(model),
    }))
    with patch.object(contract, "WEIGHT_SHA256", weight_sha), patch.object(contract, "WEIGHT_BYTES", len(weight)):
        assert contract.check_model(stage)[1]["asset_manifest_sha256"] == manifest
        (model / "tokenizer_config.json").write_bytes(b"[]")
        try:
            contract.check_model(stage)
        except Rejected as exc:
            assert exc.code == "MODEL_ASSET_HASH_MISMATCH"
        else:
            raise AssertionError("tampered tokenizer asset was accepted")


def check_once_and_launch(root: Path):
    stage = root / "试验" / "artifacts" / "ACT072M_20261128"
    stage.mkdir(parents=True)
    first = reserve_attempt(stage, "T01")
    try:
        reserve_attempt(stage, "T01")
    except Rejected as exc:
        assert exc.code == "CASE_ALREADY_RESERVED"
    else:
        raise AssertionError("second attempt reserved")
    model = stage / ".local_model" / contract.MODEL_REVISION
    model.mkdir(parents=True)
    case = stage / "frozen_A_case_inputs" / "T01"
    case.mkdir(parents=True)
    prompt = stage / contract.PROMPT_NAME
    prompt.write_bytes(b"synthetic")
    stub = {"case_id": "T01", "case_dir": str(case), "prompt": str(prompt)}
    for name in contract.ATTACHMENTS:
        (case / name).write_bytes(b"synthetic")
    svg = case / "chart.svg"
    svg.write_bytes(b"not seen")
    prior = case.parent / "T02"
    prior.mkdir()
    (prior / "chart.png").write_bytes(b"not seen")
    a_receipt = case.parent / "private_a_receipt.json"
    a_receipt.write_bytes(b"not seen")
    deprecated = stage.parent / "synthetic_forward_file.csv"
    deprecated.write_bytes(b"not seen")
    active = stage.parent.parent / "active.txt"
    active.write_bytes(b"unchanged")
    code = (
        "from pathlib import Path\nimport sys\n"
        "from research.act072m.contract import prove_network_denial\n"
        "prove_network_denial()\n"
        "for arg in sys.argv[1:5]: assert Path(arg).read_bytes()==b'synthetic'\n"
        "for arg in sys.argv[5:-2]:\n"
        " try: Path(arg).read_bytes()\n"
        " except PermissionError: pass\n"
        " else: raise AssertionError(arg)\n"
        "try: Path(sys.argv[-2]).write_bytes(b'changed')\n"
        "except PermissionError: pass\n"
        "else: raise AssertionError('active write permitted')\n"
        "Path(sys.argv[-1]).write_bytes(b'ok')\n"
    )
    profile = contract.sandbox_profile(stage, first, model, stub)
    probe = subprocess.run(
        [str(contract.SAFE_EXECUTABLE), "-p", profile, sys.executable, "-B", "-c", code,
         *(str(case / name) for name in contract.ATTACHMENTS), str(svg), str(prior / "chart.png"),
         str(a_receipt), str(deprecated), str(active), str(first / "sandbox_probe.txt")],
        env=child_environment(first), capture_output=True, check=False,
    )
    assert probe.returncode == 0, probe.stderr
    assert (first / "sandbox_probe.txt").read_bytes() == b"ok"
    raw = b'  malformed\nanswer\n'

    def fail_after_output(*_, **__):
        (first / "T01_raw.txt").write_bytes(raw)
        return subprocess.CompletedProcess([], 7)

    with patch("research.act072m.run_case.subprocess.run", side_effect=fail_after_output):
        assert _launch(stage, first, Path(sys.executable), model, {}, stub) == 7
    assert (first / "T01_raw.txt").read_bytes() == (first / "T01.json").read_bytes() == raw
    stored = strict_json((first / "launch_receipt.json").read_bytes())
    assert stored["raw_sha256"] == stored["response_sha256"] and stored["exit_code"] == 7


def check_checkpoint_template(model_metadata: Path) -> None:
    # This opens public tokenizer/processor metadata only. No MLX model, weights,
    # real case, prompt inference or vision decode is involved.
    from transformers import AutoProcessor

    renderer = AutoProcessor.from_pretrained(str(model_metadata), local_files_only=True, trust_remote_code=False)
    prompt = "合成 UTF-8 exact prompt\n"
    sample = {name: f'{{"file":"{name}"}}\n' for name in contract.ATTACHMENTS[1:]}
    messages = user_message(prompt, sample)
    rendered = renderer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    assert rendered.count("<|image_pad|>") == 1
    assert all(block["text"] in rendered for block in messages[0]["content"] if block["type"] == "text")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-metadata-dir", type=Path)
    args = parser.parse_args()
    check_text()
    with TemporaryDirectory(prefix="act072m-synthetic-") as temp:
        root = Path(temp).resolve()
        check_model_receipt(root)
        check_once_and_launch(root)
    if args.model_metadata_dir:
        check_checkpoint_template(args.model_metadata_dir)
    print(json_bytes({"status": "PASS", "synthetic_checks": 3,
                      "checkpoint_template_check": "PASS" if args.model_metadata_dir else "NOT_RUN",
                      "model_initialization_calls": 0, "model_inference_calls": 0}).decode())


if __name__ == "__main__":
    main()
