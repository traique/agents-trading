"""Provider chain - dùng nhiều LLM provider với failover kiểu lananh.

Ý tưởng: cấu hình một chuỗi provider theo thứ tự ưu tiên
(``llm_provider`` chính + ``llm_provider_fallbacks`` dự phòng). Khi build
client cho provider chính thất bại (key sai, provider không hỗ trợ), hệ
thống rơi xuống provider kế tiếp dùng model mặc định của provider đó từ
model catalog. Provider vừa gặp lỗi quota/rate-limit bị đưa vào cooldown
ngắn nên các lượt chạy kế tiếp trong phiên bỏ qua nó ngay từ đầu, đỡ mất
thời gian chờ 429.

Mid-run failover (graph đã build xong rồi mới chết provider) không nằm
trong phạm vi module này - trường hợp đó được che bởi ``llm_max_retries``
của từng provider; chain chỉ đảm bảo điểm khởi đầu luôn sống.
"""
from __future__ import annotations

import logging
import re
import threading
import time

from .factory import create_llm_client
from .model_catalog import MODEL_OPTIONS

logger = logging.getLogger(__name__)

# Quota/rate-limit cooldown dài hơn lỗi thường (key sai, provider chết)
QUOTA_COOLDOWN_SEC = 15 * 60
TRANSIENT_COOLDOWN_SEC = 2 * 60
_QUOTA_RE = re.compile(r"429|quota|rate.?limit|insufficient|billing|credit", re.I)

# Provider chạy keyless nội bộ - không cần key trong api_keys vẫn thử được
_KEYLESS_PROVIDERS = {"ollama", "openai_compatible", "lmstudio"}


def _looks_like_quota(exc: BaseException) -> bool:
    return bool(_QUOTA_RE.search(str(exc)))


def _default_model_for(provider: str, mode: str = "deep") -> str | None:
    """Model đầu tiên trong catalog của provider; None nếu provider chỉ nhận
    custom model id (giá trị placeholder 'custom') - lúc đó fallback bỏ qua
    nếu caller không chỉ định model riêng."""
    options = MODEL_OPTIONS.get(provider.lower())
    if not options:
        return None
    values = [value for _, value in options.get(mode, [])]
    if not values:
        return None
    model = values[0]
    return None if model.lower() == "custom" else model


class ProviderHealth:
    """Cooldown registry trong process cho các provider vừa lỗi."""

    def __init__(self) -> None:
        self._cooldown_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def is_cooling(self, provider: str) -> bool:
        with self._lock:
            until = self._cooldown_until.get(provider.lower())
        return until is not None and time.monotonic() < until

    def record_failure(self, provider: str, exc: BaseException | None = None) -> None:
        seconds = QUOTA_COOLDOWN_SEC if exc is not None and _looks_like_quota(exc) else TRANSIENT_COOLDOWN_SEC
        with self._lock:
            self._cooldown_until[provider.lower()] = time.monotonic() + seconds
        logger.warning("provider %s cooldown %ss (%s)", provider, seconds, exc)

    def record_success(self, provider: str) -> None:
        with self._lock:
            self._cooldown_until.pop(provider.lower(), None)

    def snapshot(self) -> dict[str, float]:
        """Trả cooldown còn lại (giây) theo provider - cho debug/report."""
        now = time.monotonic()
        with self._lock:
            return {p: round(until - now, 1) for p, until in self._cooldown_until.items() if until > now}


# Dùng chung toàn process - trạng thái sống qua các lượt phân tích trong
# cùng một backend worker, tương đương provider_state của lananh.
_health = ProviderHealth()


def normalize_chain(provider: str, fallbacks) -> list[str]:
    """Chuỗi [primary] + fallbacks, bỏ trùng/bỏ rỗng. Fallbacks nhận list
    hoặc chuỗi phân tách bởi dấu phẩy (từ TRADINGAGENTS_LLM_PROVIDER_FALLBACKS)."""
    if isinstance(fallbacks, str):
        fallbacks = [f.strip() for f in fallbacks.split(",")]
    chain = [provider]
    for f in fallbacks or []:
        if f and f.lower() not in [c.lower() for c in chain]:
            chain.append(f)
    return chain


def create_client_with_fallback(
    chain: list[str],
    model: str,
    mode: str = "deep",
    api_keys: dict | None = None,
    base_url: str | None = None,
    **kwargs,
):
    """Build client theo chuỗi ưu tiên. Trả ``(provider_used, client)``.

    Mỗi fallback giữ model riêng: nếu caller không chỉ định model cho provider
    đó thì lấy model mặc định đầu tiên trong catalog; provider không có
    catalog (custom-only) và không có model chỉ định thì bị bỏ qua.

    Raises:
        ValueError: cả chuỗi đều thất bại - message chứa lỗi của provider
            cuối cùng (đúng hành vi cũ khi chỉ có 1 provider).
    """
    api_keys = api_keys or {}
    last_exc: BaseException | None = None
    last_provider = chain[0] if chain else ""

    for idx, provider in enumerate(chain):
        provider_lower = provider.lower()
        if _health.is_cooling(provider_lower):
            logger.info("provider %s đang cooldown, bỏ qua", provider)
            continue
        # Provider chính giữ nguyên model người dùng chọn; fallback dùng
        # model mặc định của chính nó nếu không được chỉ định.
        if idx == 0 or provider_lower == chain[0].lower():
            provider_model = model
        else:
            provider_model = kwargs.pop(f"_model_{provider_lower}", None) or _default_model_for(provider_lower, mode)
        if not provider_model:
            logger.info("provider %s không có model mặc định, bỏ qua", provider)
            continue

        provider_kwargs = dict(kwargs)
        # UI lưu key theo tên provider ('openai', 'google', ...)
        key = api_keys.get(provider) or api_keys.get(provider_lower)
        if key:
            provider_kwargs["api_key"] = key
        elif provider_lower not in _KEYLESS_PROVIDERS:
            logger.info("provider %s chưa có API key, bỏ qua", provider)
            continue
        # Azure kwargs chỉ có nghĩa với provider azure - không strip thì
        # fallback sang provider khác chết vì unexpected kwarg
        if provider_lower != "azure":
            provider_kwargs.pop("azure_endpoint", None)
            provider_kwargs.pop("azure_deployment", None)
        if provider_lower in ("azure", "openai_compatible") and not (
            provider_kwargs.get("base_url") or base_url
        ):
            # azure/openai_compatible bắt buộc base_url; bỏ qua thay vì chết
            continue
        try:
            client = create_llm_client(
                provider=provider_lower,
                model=provider_model,
                base_url=base_url,
                **provider_kwargs,
            )
            llm = client.get_llm()  # xác nhận build thật sự (validate key/endpoint)
            _health.record_success(provider_lower)
            return provider_lower, llm
        except Exception as exc:
            last_exc = exc
            last_provider = provider_lower
            _health.record_failure(provider_lower, exc)

    raise ValueError(
        f"All providers in chain failed (last: {last_provider}): {last_exc}"
    )


def provider_health_snapshot() -> dict[str, float]:
    return _health.snapshot()
