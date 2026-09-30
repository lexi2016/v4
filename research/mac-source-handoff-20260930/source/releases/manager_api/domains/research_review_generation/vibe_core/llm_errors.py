"""LLM 异常分类 —— 决定「该降级」还是「该冒泡」"""

from __future__ import annotations

# 配置类错误的文字特征。仅作**兜底** —— 类型能判出来就不看字符串。
# 大小写不敏感匹配。
_CONFIG_MARKERS = (
    "invalid api key",
    "incorrect api key",
    "invalid_api_key",
    "invalid_key",
    "no api key",
    "api key not",
    "unauthorized",
    "authenticationerror",
    "oauth access token has expired",   # 本机 claude CLI 登录过期
    "re-authenticate",
    "未检测到",                          # cli_runtime：CLI 没装 / 不在 PATH
    "找不到 mimo 凭据文件",
    "mimo_api_key 未设置",
    "model_not_found",
    "does not exist or you do not have access",
)


class LlmConfigError(RuntimeError):
    """配置/凭据错误的统一出口 —— 一路抛到任务层，变成用户看得见的 error。"""


class LlmTransportError(RuntimeError):
    """模型连接被拒绝 —— 不应被当成一段正常复盘正文。"""


_TRANSPORT_MARKERS = (
    "connection refused",
    "connectionrefused",
)


def is_transport_error(exc: BaseException) -> bool:
    """只识别已证实的连接拒绝；其它暂态仍沿用节点降级策略。"""
    if isinstance(exc, LlmTransportError):
        return True
    if isinstance(exc, ConnectionRefusedError):
        return True
    text = f"{type(exc).__name__}: {exc}".lower()
    if any(marker in text for marker in _TRANSPORT_MARKERS):
        return True
    for inner in (getattr(exc, "__cause__", None), getattr(exc, "__context__", None)):
        if inner is not None and inner is not exc and is_transport_error(inner):
            return True
    return False


def is_transport_error_text(value: object) -> bool:
    """识别客户端/CLI 把连接错误当正文返回的短错误文本。

    只接受短且以错误前缀/连接错误开头的内容，避免把合法正文中提到网络问题
    的长段落误杀；JSON 解析前调用，因此不会进入 focus 或 markdown 降级结果。
    """
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text or len(text) > 512:
        return False
    lower = text.lower().replace("_", " ")
    has_refused = "connection refused" in lower or "connectionrefused" in lower
    if not has_refused:
        return False
    return lower.startswith((
        "api error",
        "error:",
        "error ",
        "exception:",
        "connection refused",
        "connectionrefused",
    ))


def raise_if_transport_error(exc: BaseException, where: str) -> None:
    """连接拒绝直接冒泡，且不把第三方异常原文（可能含凭据）带到 UI。"""
    if is_transport_error(exc):
        if isinstance(exc, LlmTransportError):
            raise exc
        raise LlmTransportError(
            f"{where}：模型连接被拒绝（ConnectionRefused），未生成复盘正文。"
            "请检查后端网络或代理配置。"
        ) from exc


def raise_if_transport_error_text(value: object, where: str) -> None:
    """客户端短错误文本不能作为正常 markdown/focus 返回。"""
    if is_transport_error_text(value):
        raise LlmTransportError(
            f"{where}：模型连接被拒绝（ConnectionRefused），未生成复盘正文。"
            "请检查后端网络或代理配置。"
        )


def safe_error_message(exc: BaseException, where: str = "模型调用") -> str:
    """给任务状态/API 的安全错误摘要；不回显第三方异常文本或凭据。"""
    if isinstance(exc, LlmTransportError):
        return str(exc)
    if is_transport_error(exc):
        return f"{where}：模型连接被拒绝（ConnectionRefused），未生成复盘正文。请检查后端网络或代理配置。"
    if is_config_error(exc):
        return f"{where}：模型调用未通过鉴权或配置校验，请检查模型配置。"
    return f"{where}失败（{type(exc).__name__}）。"


def _openai_config_types() -> tuple[type, ...]:
    """openai SDK 里属于「配置错误」的异常类型（装不上就返回空元组）。"""
    try:
        import openai
    except Exception:  # noqa: BLE001  没装 openai 也要能用（纯 CLI 后端）
        return ()
    names = ("AuthenticationError", "PermissionDeniedError", "NotFoundError")
    return tuple(t for t in (getattr(openai, n, None) for n in names) if isinstance(t, type))


def is_config_error(exc: BaseException) -> bool:
    """这个异常是「配置/凭据错误」吗 —— 是就该冒泡，别降级。"""
    if isinstance(exc, LlmConfigError):
        return True     # 已经判定过的，别在下游被重新分类成"暂时性"又给降级了
    types = _openai_config_types()
    if types and isinstance(exc, types):
        return True
    # 有些包装层会把原始异常塞进 __cause__ / __context__
    for inner in (getattr(exc, "__cause__", None), getattr(exc, "__context__", None)):
        if inner is not None and inner is not exc and types and isinstance(inner, types):
            return True
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(m in text for m in _CONFIG_MARKERS)


def raise_if_config_error(exc: BaseException, where: str) -> None:
    """节点里 `except` 到异常后**第一件事**调它：是配置错误就抛出去，别降级。

    `where` 写节点名，用户看到的报错里会带上（知道是哪一步先撞上的）。
    """
    # 保留这个函数名给现有分析师调用；连接拒绝也必须从这里冒泡，不能变成
    # 看似正常的降级报告。其它网络暂态继续由调用方按旧策略处理。
    if is_transport_error(exc):
        raise_if_transport_error(exc, where)
    if is_config_error(exc):
        raise LlmConfigError(
            f"{where}：模型调用未通过鉴权／配置有误（{type(exc).__name__}）。"
            f"请检查 API key，或用 VIBE_LLM_CLI 走本机已登录的 CLI 订阅。"
        ) from exc
