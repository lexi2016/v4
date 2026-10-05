"""Serialize a graph result without any file access or clock lookup."""
from __future__ import annotations
import html
import re
from typing import Any
from .roles import ROLES
from .util import is_degraded_report
SCHEMA_VERSION = 1
_MIN_FOCUS_MD = 200

def usable(payload: Any) -> bool:
    """这份复盘算「可用」吗 —— 用来判断能不能覆盖已有结果。

    判据只看**AI 收敛的那一段**（明天关注点）：硬指标是纯数据算的，
    LLM 挂了它照样在，所以拿它判会把空复盘也算成可用。
    """
    if not isinstance(payload, dict):
        return False
    if payload.get("focus"):            # 结构化关注点出来了 = 裁判跑通了
        return True
    return len((payload.get("focus_md") or "").strip()) >= _MIN_FOCUS_MD

def md_to_html(text: str) -> str:
    if not text:
        return ""
    out = []
    for ln in text.split("\n"):
        s = ln.strip()
        if not s:
            continue
        s = html.escape(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        m = re.match(r"^(#+)\s*(.*)", s)
        if m:
            out.append(f"<h4>{m.group(2)}</h4>")
        else:
            out.append(f"<p>{s}</p>")
    return "\n".join(out)

def strip_prefix(text: str, prefix: str) -> str:
    return "\n".join(
        ln.strip()[len(prefix):].strip() if ln.strip().startswith(prefix) else ln
        for ln in text.split("\n")
    ).strip()

def serialize(final: dict, date: str, extra_warnings: list[str] | None = None,
              *, pack, reflection_record: dict | None, data_as_of: str, generated_at: str) -> dict:
    """把图的产物打成落盘 envelope。

    `extra_warnings` 来自入口体检（preflight）—— 下面那个 `is_degraded_report`
    只认**报告以 `[⚠️` 开头**这一种降级；取数成功但内容是空的时候，模型会写出
    一份看着正常的报告、里面用散文说"数据缺失"，前缀判据看不出来，
    warnings 就会是空的。所以数据层的缺失由体检（preflight）那边告诉我们。
    """
    analysts = []
    warnings = list(extra_warnings or [])
    for role in ROLES:
        raw = final.get(role.report_field, "") or ""
        if is_degraded_report(raw):
            warnings.append(f"{role.title}：数据或生成降级")
        analysts.append({"key": role.key, "title": role.title, "tag": role.tag, "html": md_to_html(raw)})
    focus_struct = final.get("focus_struct")
    focus_md = final.get("tomorrow_focus", "") or ""
    # Keep a final, entry-point-independent guard immediately before an
    # envelope is built.  The graph normally guards and re-renders first, but
    # CLI/tests/older callers can call serialize directly.  The helper returns
    # a copy, so loading an existing historical artifact never rewrites its
    # original evidence.
    if isinstance(focus_struct, dict):
        from . import schemas

        guarded, guard_notes = schemas.guard_focus_against_market_facts(
            focus_struct, final.get("market_facts") or {},
        )
        if guarded != focus_struct:
            try:
                guarded_obj = pack.focus_model.model_validate(guarded)
                focus_struct = guarded_obj.model_dump()
                focus_md = pack.render_focus(guarded_obj)
            except Exception:  # noqa: BLE001  unsafe custom-pack render must not publish the unchecked prose
                focus_struct = None
                focus_md = "CANNOT_CONFIRM：复盘焦点的结构化事实校验后无法安全渲染。"
                guard_notes = [*guard_notes, "结构化焦点校验失败，已标记 CANNOT_CONFIRM"]
        warnings.extend(f"焦点事实校验：{note}" for note in guard_notes)

    macro = final.get("macro_sector_report", "") or ""
    return {
        "schema_version": SCHEMA_VERSION,
        "run_type": "daily_review",
        "review_id": f"daily_{date}",
        "target_date": date,
        "trade_date": date,       # 兼容旧前端字段
        "data_as_of": data_as_of,
        "generated_at": generated_at,
        "warnings": warnings,
        "focus": focus_struct,
        "focus_md": focus_md,
        "emotion_metrics": final.get("emotion_metrics") or {},
        "market_facts": final.get("market_facts") or {},
        "macro_sector": macro,
        "reflection": reflection_record,   # 反思闭环：只保留目标日前已知回看
        "analysts": analysts,
    }
