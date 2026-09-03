"""供 LangChain ModelRetryMiddleware 使用的错误分类。

对应 nanobot 的 `nanobot/providers/base.py` 里的重试/退避逻辑，以及
build-guide 第 11 步「错误分类 + 自动重试」。

核心思路：不是所有错误都应该重试。
- 429（限流）/ 5xx（服务端临时故障）/ 网络超时 → 应该重试，等一等再试
- 401（认证失败）/ 402（欠费）/ 400（请求本身有问题） → 重试没有意义，直接抛出

真正的退避、抖动和重试次数由 LangChain middleware 统一管理，本模块只保留
项目特有的“哪些错误值得重试”判断，避免重复实现 Runner。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ErrorClassification:
    should_retry: bool
    wait_seconds: float
    kind: str


# 不可重试：认证错误、欠费/额度问题、请求参数错误——重试也不会变好。
_NO_RETRY_STATUS = {400, 401, 402, 403, 404, 422}
# 可重试：限流、服务端临时故障。
_RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}


def classify_error(exc: Exception, attempt: int) -> ErrorClassification:
    """检查异常上的 status_code（大部分 HTTP 客户端库都会挂这个属性），决定是否重试。"""
    status_code = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )

    if status_code in _NO_RETRY_STATUS:
        kind = "auth_or_quota" if status_code in (401, 402, 403) else "bad_request"
        return ErrorClassification(should_retry=False, wait_seconds=0.0, kind=kind)

    if status_code in _RETRYABLE_STATUS:
        # 429 限流：等久一点；5xx：指数退避
        base = 5.0 if status_code == 429 else 1.5
        return ErrorClassification(
            should_retry=True, wait_seconds=base * (2**attempt), kind="rate_limit_or_server_error"
        )

    # 未知异常（网络超时、连接被拒等）：谨慎重试几次，指数退避。
    return ErrorClassification(should_retry=True, wait_seconds=1.5 * (2**attempt), kind="unknown")
