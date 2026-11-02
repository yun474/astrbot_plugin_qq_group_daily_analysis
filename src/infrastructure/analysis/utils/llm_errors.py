"""
LLM 错误识别与超时解析工具

负责：
- 识别 Provider 不支持 response_format 的兼容性错误
- 识别模型服务商的内容风控拦截
- 把常见报错归类成一句中文排查提示
- 解析单次请求的硬超时上限
"""

import re

from astrbot.api.star import Context

# 未配置插件硬超时时的最小上限（秒）
DEFAULT_LLM_HARD_TIMEOUT_SECONDS = 300.0

# 结构化风控错误码（GLM 1301/1302、百度千帆 336003/336100）
_RISK_CODE_PATTERN = re.compile(
    r"(?:code['\":\s]+|error_code['\":\s]+|\b)(?:1301|1302|336003|336100)\b",
    re.I,
)

_RISK_PATTERNS = (
    # DeepSeek
    "content exists risk",
    # OpenAI、Azure 及常见中转网关
    "content_filter",
    "content management policy",
    "content_policy_violation",
    "sensitive_words",
    "triggering azure openai",
    # GLM、通义千问、百度千帆、Moonshot
    "datainspectionfailed",
    "inappropriate content",
    "安全风险",
    "敏感词",
    "安全策略",
    # Gemini 安全评级
    "harm_category",
    "safety rating",
)

_RESPONSE_FORMAT_PATTERNS = (
    "response_format",
    "json_schema",
    "unexpected keyword argument",
    "extra fields not permitted",
    "unknown field",
    "not support",
    "not supported",
    "invalid request",
)

# (匹配关键字, 中文提示)，按顺序匹配，命中第一条即返回
_ERROR_HINTS = (
    (
        ("401", "unauthorized", "invalid api key", "incorrect api key"),
        "API Key 无效或已过期，请检查 Provider 的密钥配置",
    ),
    (("402", "insufficient", "余额", "quota"), "账户余额或额度不足，请检查服务商账户"),
    (
        ("429", "rate limit", "too many requests"),
        "请求过于频繁被限流，可调低并发数或增大重试退避",
    ),
    (
        ("404", "model_not_found", "does not exist"),
        "模型不存在或无权访问，请检查 Provider 的模型名称",
    ),
    (
        ("context length", "maximum context", "too long", "max_tokens"),
        "输入超过模型上下文长度，可减少单次分析的消息数",
    ),
    (
        ("connect", "connection", "name resolution", "ssl"),
        "无法连接到模型服务，请检查网络、代理或接口地址",
    ),
    (
        (
            "500",
            "502",
            "503",
            "504",
            "bad gateway",
            "service unavailable",
            "overloaded",
        ),
        "模型服务端暂时不可用，稍后会自动重试",
    ),
)


def is_response_format_unsupported_error(error: Exception) -> bool:
    """判断是否为 Provider/网关不支持 response_format 的兼容性错误"""
    text = str(error).lower()
    return any(pattern in text for pattern in _RESPONSE_FORMAT_PATTERNS)


def is_content_risk_error(error: Exception | None) -> bool:
    """判断是否为模型服务商的内容安全审查（风控）拦截"""
    if error is None:
        return False
    text = str(error).lower()
    if any(pattern in text for pattern in _RISK_PATTERNS):
        return True
    return bool(_RISK_CODE_PATTERN.search(text))


def describe_llm_error(error: Exception | None) -> str:
    """把常见 LLM 报错归类成一句中文提示，无法归类时返回空字符串"""
    if error is None:
        return ""
    if isinstance(error, TimeoutError):
        return "请求超时，可检查模型服务状态，或调大 Provider 的 timeout / 插件的 LLM 硬超时"
    if is_content_risk_error(error):
        return "内容被模型服务商风控拦截，建议配置备用模型，或调整分析人格与提示词"
    text = str(error).lower()
    for keywords, hint in _ERROR_HINTS:
        if any(k in text for k in keywords):
            return hint
    return ""


def resolve_hard_timeout(
    context: Context, provider_id: str, configured_timeout: int
) -> tuple[float, str]:
    """
    解析单次 LLM 请求的硬超时上限。

    插件配置大于 0 时直接使用；否则取 Provider timeout 与 300 秒中较大的一个。
    Provider 的 timeout 是 HTTP 单次读取超时而不是整个请求的总时长，服务商发送保活空行时
    一个请求可以合法地超过它，所以不能直接拿来当总时长上限，否则会误杀原本能成功的长请求。

    Returns:
        (超时秒数, 来源说明)
    """
    if configured_timeout and configured_timeout > 0:
        return float(configured_timeout), "插件配置"

    raw_timeout = None
    try:
        provider = context.get_provider_by_id(provider_id=provider_id)
    except Exception:
        provider = None
    if provider is not None:
        prov_cfg = getattr(provider, "provider_config", None)
        if isinstance(prov_cfg, dict):
            raw_timeout = prov_cfg.get("timeout")
        if raw_timeout is None:
            raw_timeout = getattr(provider, "timeout", None)

    try:
        timeout = float(raw_timeout) if raw_timeout is not None else 0.0
    except (TypeError, ValueError):
        timeout = 0.0
    if timeout > DEFAULT_LLM_HARD_TIMEOUT_SECONDS:
        return timeout, "Provider 配置"
    return DEFAULT_LLM_HARD_TIMEOUT_SECONDS, "默认兜底"
