"""domains.d1_review_lane_producer: preopen_lanes (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _ensure_preopen_lane_artifacts_body(_v4_scope, /, target_date, *, signal_date, source_dir, output_dir, video_dir, force):
    """Ensure D-1 fupan and Stage7 lane CSVs exist for a target opening date."""

    signal = _v4_global(_v4_scope, '_signal_date')(target_date, signal_date)
    paths = _v4_global(_v4_scope, '_paths')(
        target_date,
        signal,
        source_dir=_v4_global(_v4_scope, 'Path')(source_dir),
        output_dir=_v4_global(_v4_scope, 'Path')(output_dir),
        video_dir=_v4_global(_v4_scope, 'Path')(video_dir) if video_dir is not None else None,
    )
    output_paths = [
        paths["fupan_pool"],
        paths["stage7_preopen_pool"],
        paths["stage7_next_pool"],
        paths["stage7_intraday_pool"],
        paths["stage7_summary"],
        paths["fupan_manifest"],
        paths["stage7_manifest"],
    ]
    real_stage7_available = _v4_global(_v4_scope, 'bool')(paths["real_stage7_pool"].exists() and _v4_global(_v4_scope, '_read_csv')(paths["real_stage7_pool"]))
    if not force and _v4_global(_v4_scope, 'all')(path.exists() and path.stat().st_size > 5 for path in output_paths):
        fupan_manifest = _v4_global(_v4_scope, '_read_json')(paths["fupan_manifest"])
        stage7_manifest = _v4_global(_v4_scope, '_read_json')(paths["stage7_manifest"])
        if fupan_manifest.get("fupan_pool_rule") != "AUTO_FUPAN_THEN_VIDEO_SECOND_REVIEW":
            force = True
        elif real_stage7_available and stage7_manifest.get("source_role") != "real_d1_stage7_tail_replay":
            force = True
        else:
            existing_rows = _v4_global(_v4_scope, '_read_csv')(paths["fupan_pool"])
            return {
                "ok": True,
                "status": "PREOPEN_D1_LANES_READY_EXISTING",
                "target_date": target_date,
                "signal_date": signal,
                "row_count": _v4_global(_v4_scope, 'len')(existing_rows),
                "paths": {key: _v4_global(_v4_scope, 'str')(value) for key, value in paths.items() if key not in {"fupan_dir"}},
                "cannot_confirm": [],
            }

    missing = [path for path in _v4_global(_v4_scope, '_source_paths')(paths) if not path.exists()]
    if missing:
        return {
            "ok": False,
            "status": "SKIPPED_MISSING_D1_FUPAN_EVIDENCE",
            "target_date": target_date,
            "signal_date": signal,
            "row_count": 0,
            "missing_paths": [_v4_global(_v4_scope, 'str')(path) for path in missing],
            "cannot_confirm": [
                f"未找到 {signal} 的 D-1 复盘证据文件，不能生成 {target_date} 早盘复盘/Stage7 lane。",
                "不会使用目标日收盘结果、强势股榜或其他日期文件补位。",
            ],
        }

    anchor_rows = _v4_global(_v4_scope, '_read_csv')(paths["anchor_role"])
    theme_rows = _v4_global(_v4_scope, '_read_csv')(paths["theme_stocks"])
    plan_rows = _v4_global(_v4_scope, '_read_csv')(paths["prior_plan"])
    handoff_rows = _v4_global(_v4_scope, '_read_csv')(paths["intraday_handoff"])
    video_context = _v4_global(_v4_scope, '_load_video_fupan_context')(paths, signal)
    rows = _v4_global(_v4_scope, '_build_rows')(
        target_date=target_date,
        signal_date=signal,
        paths=paths,
        anchor_rows=anchor_rows,
        theme_rows=theme_rows,
        plan_rows=plan_rows,
        handoff_rows=handoff_rows,
    )
    if not rows:
        return {
            "ok": False,
            "status": "SKIPPED_EMPTY_D1_FUPAN_LANES",
            "target_date": target_date,
            "signal_date": signal,
            "row_count": 0,
            "source_paths": [_v4_global(_v4_scope, 'str')(path) for path in _v4_global(_v4_scope, '_source_paths')(paths)],
            "cannot_confirm": ["D-1 复盘证据存在，但没有可映射代码的观察行。"],
        }

    auto_fupan_rows = _v4_global(_v4_scope, '_rows_for_lane')(rows, lane="fupan_lane")
    video_rows = _v4_global(_v4_scope, '_build_video_fupan_rows')(
        target_date=target_date,
        signal_date=signal,
        video_context=video_context,
        code_map=_v4_global(_v4_scope, '_build_code_maps')(theme_rows),
    )
    fupan_rows = _v4_global(_v4_scope, '_merge_fupan_and_video_rows')(auto_fupan_rows, video_rows)
    real_stage7_manifest: dict[str, Any] = {}
    stage7_source_role = "synthetic_from_d1_fupan_role_table"
    if real_stage7_available:
        stage7_rows, real_stage7_manifest = _v4_global(_v4_scope, '_build_real_stage7_rows')(
            target_date=target_date,
            signal_date=signal,
            path=paths["real_stage7_pool"],
            manifest_path=paths["real_stage7_manifest"],
        )
        if stage7_rows:
            stage7_source_role = "real_d1_stage7_tail_replay"
        else:
            stage7_rows = _v4_global(_v4_scope, '_rows_for_lane')(rows, lane="stage7_lane")
    else:
        stage7_rows = _v4_global(_v4_scope, '_rows_for_lane')(rows, lane="stage7_lane")
    _v4_global(_v4_scope, '_write_csv')(paths["fupan_pool"], fupan_rows, _v4_global(_v4_scope, 'FIELDS'))
    _v4_global(_v4_scope, '_write_csv')(paths["stage7_preopen_pool"], stage7_rows, _v4_global(_v4_scope, 'FIELDS'))
    _v4_global(_v4_scope, '_write_csv')(paths["stage7_next_pool"], stage7_rows, _v4_global(_v4_scope, 'FIELDS'))
    _v4_global(_v4_scope, '_write_csv')(paths["stage7_intraday_pool"], stage7_rows, _v4_global(_v4_scope, 'FIELDS'))
    _v4_global(_v4_scope, '_write_csv')(paths["stage7_summary"], _v4_global(_v4_scope, '_build_summary')(stage7_rows, target_date, signal), _v4_global(_v4_scope, 'SUMMARY_FIELDS'))

    cannot_confirm = [
        f"{target_date} 早盘复盘 lane 来自 {signal} 复盘结构化证据；Stage7 lane 优先来自 {signal} 14:45-15:00 尾盘 1 分钟回放。",
        "未确认L2/十档/逐笔委托/撤单/未匹配量；目标日仍必须看09:25-09:45承接。",
        "该 lane 不能替代正式 1.9.2/FMLA04 selector，只能作为辅助并源。",
    ]
    cannot_confirm.extend(video_context.get("cannot_confirm") or [])
    generated_at = _v4_global(_v4_scope, 'datetime').now().isoformat(timespec="seconds")
    source_path_strings = [_v4_global(_v4_scope, 'str')(path) for path in _v4_global(_v4_scope, '_source_paths')(paths)]
    all_source_path_strings = [*source_path_strings, *(video_context.get("source_paths") or [])]
    _v4_global(_v4_scope, '_write_json')(
        paths["fupan_manifest"],
        {
            "status": "FUPAN_WATCHLIST_POOL_READY_DATA_PARTIAL",
            "fupan_pool_rule": "AUTO_FUPAN_THEN_VIDEO_SECOND_REVIEW",
            "target_date": target_date,
            "signal_date": signal,
            "row_count": _v4_global(_v4_scope, 'len')(fupan_rows),
            "auto_fupan_row_count": _v4_global(_v4_scope, 'len')(auto_fupan_rows),
            "video_fupan_status": video_context.get("status"),
            "video_fupan_raw_status": video_context.get("raw_status"),
            "video_fupan_gap_rows": _v4_global(_v4_scope, 'len')(video_context.get("gap_rows") or []),
            "video_fupan_stock_rows_added": _v4_global(_v4_scope, 'len')(video_rows),
            "source_paths": all_source_path_strings,
            "auto_fupan_source_paths": source_path_strings,
            "video_source_paths": video_context.get("source_paths") or [],
            "pool_path": _v4_global(_v4_scope, 'str')(paths["fupan_pool"]),
            "generated_at": generated_at,
            "overlap_note": "This lane starts from automatic D-1 fupan, then consumes available Bilibili/video second-review gap rows; video-blocked runs stay explicit in video_fupan_status.",
            "cannot_confirm": cannot_confirm,
            **_v4_global(_v4_scope, 'SAFETY'),
        },
    )
    _v4_global(_v4_scope, '_write_json')(
        paths["stage7_manifest"],
        {
            "status": "STAGE7_TAIL_POOL_READY_DATA_PARTIAL",
            "target_date": target_date,
            "signal_date": signal,
            "row_count": _v4_global(_v4_scope, 'len')(stage7_rows),
            "source_role": stage7_source_role,
            "source_paths": (
                [_v4_global(_v4_scope, 'str')(paths["real_stage7_pool"]), _v4_global(_v4_scope, 'str')(paths["real_stage7_manifest"])]
                if stage7_source_role == "real_d1_stage7_tail_replay"
                else source_path_strings
            ),
            "pool_paths": [
                _v4_global(_v4_scope, 'str')(paths["stage7_preopen_pool"]),
                _v4_global(_v4_scope, 'str')(paths["stage7_next_pool"]),
                _v4_global(_v4_scope, 'str')(paths["stage7_intraday_pool"]),
            ],
            "summary_path": _v4_global(_v4_scope, 'str')(paths["stage7_summary"]),
            "generated_at": generated_at,
            "upstream_manifest": real_stage7_manifest if stage7_source_role == "real_d1_stage7_tail_replay" else {},
            "overlap_note": (
                "Stage7 lane is generated from the real D-1 14:45-15:00 replay, so full equality with fupan lane is treated as a bug."
                if stage7_source_role == "real_d1_stage7_tail_replay"
                else "Fallback lane is distilled from D-1 fupan role evidence and must be treated as inferred, not real tail replay."
            ),
            "cannot_confirm": cannot_confirm,
            **_v4_global(_v4_scope, 'SAFETY'),
        },
    )

    return {
        "ok": True,
        "status": "PREOPEN_D1_LANES_READY",
        "target_date": target_date,
        "signal_date": signal,
        "row_count": _v4_global(_v4_scope, 'len')(fupan_rows),
        "stage7_row_count": _v4_global(_v4_scope, 'len')(stage7_rows),
        "stage7_source_role": stage7_source_role,
        "paths": {key: _v4_global(_v4_scope, 'str')(value) for key, value in paths.items() if key not in {"fupan_dir"}},
        "source_paths": all_source_path_strings,
        "video_fupan_status": video_context.get("status"),
        "video_fupan_stock_rows_added": _v4_global(_v4_scope, 'len')(video_rows),
        "cannot_confirm": cannot_confirm,
        **_v4_global(_v4_scope, 'SAFETY'),
    }
