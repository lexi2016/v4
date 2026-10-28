"""Pure string helpers used by the review core."""
_DEGRADE_PREFIX = "[⚠️"

def is_degraded_report(text: str) -> bool:
    """报告是否为**降级信封**（analysts/_fail 与 data/_degrade 产出的 `[ …]` 开头）"""
    return (text or "").lstrip().startswith(_DEGRADE_PREFIX)
