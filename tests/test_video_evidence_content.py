from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from domains.review_evidence_layers import load_review_core_a_share_review
from domains.video_evidence_content import MAX_SEGMENT_BYTES, video_transcript_content
from test_review_evidence_layers import _rewrite_bundle_chain, _write_bundle


TARGET = "20260821"
RAW = "source_audio,segment_index,start,end,text,split_reason\naudio.wav,1,0.8,23.72, 原始市场复盘 ,pause\naudio.wav,2,24,31,可能是歌曲也可能识别有误,pause\n".encode()


def _fixture(root: Path, data: bytes = RAW):
    bundle, current = _write_bundle(root)
    path = "review/20260821/runs/rcv1-20260821-BV1WFnU6cE5r/asr/segments_path"
    segment = root / path
    segment.parent.mkdir(parents=True)
    segment.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    ref = {"kind": "segment", "path": path, "size": len(data), "sha256": sha}
    video = {
        "trade_date": TARGET, "target_trade_date": TARGET, "bv_id": "BV1WFnU6cE5r",
        "date_scope": "SAME_DAY_FUPAN", "discovery_status": "TARGET_BV_LOCKED",
        "status": "ASR_REVIEW_REQUIRED", "asr_status": "ASR_REVIEW_REQUIRED",
        "gap_status": "VIDEO_GAP_AUDIT_EMPTY", "targeted_spotcheck_count": 0,
        "asr_segment_count": 2, "artifact_refs": [ref],
        "cannot_confirm": ["ASR transcript is not usable"],
        "video_input_count": 0, "video_augmented": False,
    }
    manifest_path = root / current["manifest_path"]
    manifest = json.loads(manifest_path.read_text())
    manifest["readiness"] = {"video": deepcopy(video)}
    manifest["source_refs"] = [{
        "artifact_kind": "segment", "artifact_path": path, "sha256": sha,
        "semantic_identity": {"trade_date": TARGET, "sha256": sha, "size": len(data)},
    }]
    manifest_path.write_text(json.dumps(manifest))
    bundle["compatibility"]["video"] = video
    bundle["video"] = deepcopy(video)
    _rewrite_bundle_chain(root, bundle, current)
    return video, manifest, segment


def test_raw_segments_preserve_text_provenance_and_asr_boundaries(tmp_path):
    video, manifest, _ = _fixture(tmp_path)
    before = deepcopy(video)
    content = video_transcript_content(video, TARGET, tmp_path, manifest)
    review = load_review_core_a_share_review(TARGET, tmp_path)
    assert video == before
    assert content["content_status"] == "RAW_ASR_AVAILABLE"
    assert content["content_cannot_confirm"] == []
    assert content["content_quality"]["segment_count"] == 2
    assert content["transcript_segments"][0] == {
        "segment_id": "1", "start_seconds": 0.8, "end_seconds": 23.72,
        "text": " 原始市场复盘 ", "evidence_status": "ASR_UNVERIFIED",
        "source_sha256": hashlib.sha256(RAW).hexdigest(),
    }
    assert review["video"]["transcript_segments"] == content["transcript_segments"]
    for field in ("status", "asr_status", "gap_status", "targeted_spotcheck_count", "cannot_confirm", "video_input_count", "video_augmented"):
        assert review["video"][field] == before[field]
    assert review["model_review"]["independent_review"]["video_input_count"] == 0
    assert review["model_review"]["independent_review"]["video_augmented"] is False
    assert review["production_allowed"] is review["buy_gate_updated"] is review["orders_sent"] is False


@pytest.mark.parametrize("path", [
    "/tmp/segments.csv", "../segments.csv", "review/20260820/runs/x/asr/segments_path",
    "review/20260821/runs/x/../../segments.csv", "review\\20260821\\runs\\x\\asr\\segments_path",
])
def test_rejects_absolute_escape_and_other_date_paths(tmp_path, path):
    video, manifest, _ = _fixture(tmp_path)
    video["artifact_refs"][0]["path"] = path
    result = video_transcript_content(video, TARGET, tmp_path, manifest)
    assert result["content_status"] == "CANNOT_CONFIRM"
    assert result["transcript_segments"] == []


@pytest.mark.parametrize("mutation", ["missing", "sha", "date", "path", "size", "bv", "video_date", "video_ref"])
def test_requires_manifest_binding(tmp_path, mutation):
    video, manifest, _ = _fixture(tmp_path)
    binding = manifest["source_refs"][0]
    if mutation == "missing":
        manifest["source_refs"] = []
    elif mutation == "date":
        binding["semantic_identity"]["trade_date"] = "20260820"
    elif mutation == "path":
        binding["artifact_path"] = "review/20260821/other.csv"
    elif mutation == "size":
        binding["semantic_identity"]["size"] += 1
    elif mutation == "bv":
        manifest["readiness"]["video"]["bv_id"] = "BV1gR8e6bETL"
    elif mutation == "video_date":
        manifest["readiness"]["video"]["trade_date"] = "20260820"
    elif mutation == "video_ref":
        manifest["readiness"]["video"]["artifact_refs"] = []
    else:
        binding["sha256"] = "0" * 64
    result = video_transcript_content(video, TARGET, tmp_path, manifest)
    assert result["content_cannot_confirm"] == ["VIDEO_CONTENT_MANIFEST_BINDING_REQUIRED"]
    assert result["transcript_segments"] == []


@pytest.mark.parametrize("field,value", [
    ("trade_date", "20260820"), ("target_trade_date", "20260820"),
    ("bv_id", ""), ("date_scope", "OTHER_DAY"), ("discovery_status", "NOT_LOCKED"),
])
def test_requires_locked_same_day_video_identity(tmp_path, field, value):
    video, manifest, _ = _fixture(tmp_path)
    video[field] = value
    assert video_transcript_content(video, TARGET, tmp_path, manifest)["content_cannot_confirm"] == ["VIDEO_CONTENT_SAME_DAY_IDENTITY_REQUIRED"]


@pytest.mark.parametrize("link_directory", [False, True])
def test_rejects_file_and_directory_symlinks_even_within_root(tmp_path, link_directory):
    video, manifest, segment = _fixture(tmp_path)
    if link_directory:
        original = segment.parent
        moved = original.with_name("original_asr")
        original.rename(moved)
        original.symlink_to(moved, target_is_directory=True)
    else:
        moved = segment.with_name("original_segments")
        segment.rename(moved)
        segment.symlink_to(moved)
    result = video_transcript_content(video, TARGET, tmp_path, manifest)
    assert result["content_status"] == "CANNOT_CONFIRM"
    assert not result["transcript_segments"]


@pytest.mark.parametrize("data", [
    b"segment_index,start,end,text\n1,nan,2,bad\n",
    b"segment_index,start,end,text\n1,0,inf,bad\n",
    b"segment_index,start,end,text\n1,-1,2,bad\n",
    b"segment_index,start,end,text\n1,4,2,bad\n",
    b"segment_index,start,end,text\n1,0,2\n",
    b"segment_index,start,end,text\n1,0,2,bad,extra\n",
    b"segment_index,start,end,text\n1,0,2,first\n1,2,3,duplicate\n",
    b"segment_index,start,end,text\n1,0,2,\"unterminated\n",
    b"start,end,text\n0,2,missing_index\n",
    b"\xff\xfe\xfd",
])
def test_invalid_csv_is_isolated_from_independent_review(tmp_path, data):
    _fixture(tmp_path, data)
    review = load_review_core_a_share_review(TARGET, tmp_path)
    assert review["video"]["content_status"] == "CANNOT_CONFIRM"
    assert review["video"]["transcript_segments"] == []
    assert review["status"] == "MODEL_REVIEW_READY"
    assert review["model_review"]["independent_review"]["video_input_count"] == 0
    assert review["board_rows"][0]["section"] == "医药"


def test_sha_size_missing_and_count_failures(tmp_path):
    video, manifest, segment = _fixture(tmp_path)
    segment.write_bytes(RAW.replace(b"23.72", b"23.73"))
    assert video_transcript_content(video, TARGET, tmp_path, manifest)["content_cannot_confirm"] == ["VIDEO_CONTENT_SHA_MISMATCH"]
    segment.write_bytes(RAW)
    video["asr_segment_count"] = 3
    manifest["readiness"]["video"]["asr_segment_count"] = 3
    assert video_transcript_content(video, TARGET, tmp_path, manifest)["content_cannot_confirm"] == ["VIDEO_CONTENT_SEGMENT_COUNT_MISMATCH"]
    video["artifact_refs"][0]["size"] = MAX_SEGMENT_BYTES + 1
    manifest["readiness"]["video"]["artifact_refs"][0]["size"] = MAX_SEGMENT_BYTES + 1
    manifest["source_refs"][0]["semantic_identity"]["size"] = MAX_SEGMENT_BYTES + 1
    assert video_transcript_content(video, TARGET, tmp_path, manifest)["content_cannot_confirm"] == ["VIDEO_CONTENT_SIZE_LIMIT_OR_MISMATCH"]
    video["artifact_refs"][0]["size"] = len(RAW)
    manifest["readiness"]["video"]["artifact_refs"][0]["size"] = len(RAW)
    manifest["source_refs"][0]["semantic_identity"]["size"] = len(RAW)
    segment.unlink()
    assert video_transcript_content(video, TARGET, tmp_path, manifest)["content_status"] == "CANNOT_CONFIRM"


def test_old_bundle_without_segments_remains_compatible(tmp_path):
    _write_bundle(tmp_path)
    review = load_review_core_a_share_review(TARGET, tmp_path)
    assert review["status"] == "MODEL_REVIEW_READY"
    assert review["video"]["content_status"] == "CANNOT_CONFIRM"
    assert review["video"]["content_cannot_confirm"] == ["VIDEO_CONTENT_NO_SEGMENT_ARTIFACT"]


def test_configured_empty_root_never_silently_falls_back(monkeypatch, tmp_path):
    _fixture(tmp_path)
    configured = tmp_path / "wrong-configured-root"
    monkeypatch.setenv("REVIEW_CORE_DATA_ROOT", str(configured))
    with pytest.raises(FileNotFoundError):
        load_review_core_a_share_review(TARGET, tmp_path)
