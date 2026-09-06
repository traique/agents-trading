"""Unit tests cho provider chain (llm_clients.chain) - mock hết factory."""
from unittest.mock import patch, MagicMock

import pytest

from tradingagents.llm_clients import chain as chain_mod
from tradingagents.llm_clients.chain import (
    ProviderHealth,
    create_client_with_fallback,
    normalize_chain,
)


@pytest.fixture(autouse=True)
def _reset_health():
    """_health là singleton toàn process - xóa cooldown giữa các test."""
    chain_mod._health = ProviderHealth()
    yield
    chain_mod._health = ProviderHealth()


class TestNormalizeChain:
    def test_primary_only(self):
        assert normalize_chain("openai", []) == ["openai"]

    def test_dedup_case_insensitive(self):
        assert normalize_chain("openai", ["OpenAI", "deepseek"]) == ["openai", "deepseek"]

    def test_comma_string(self):
        assert normalize_chain("openai", "google, deepseek,") == ["openai", "google", "deepseek"]

    def test_empty_entries_skipped(self):
        assert normalize_chain("openai", ["", None]) == ["openai"]


class TestProviderHealth:
    def test_record_failure_sets_cooldown(self):
        h = ProviderHealth()
        h.record_failure("openai")
        assert h.is_cooling("openai")
        h.record_success("openai")
        assert not h.is_cooling("openai")

    def test_quota_failure_cools_longer(self):
        h = ProviderHealth()
        h.record_failure("openai", Exception("429 rate limit exceeded"))
        h2 = ProviderHealth()
        h2.record_failure("deepseek", Exception("connection refused"))
        assert h.snapshot()["openai"] > h2.snapshot()["deepseek"]

    def test_case_insensitive(self):
        h = ProviderHealth()
        h.record_failure("OpenAI")
        assert h.is_cooling("openai")


class TestCreateClientWithFallback:
    def _fake_llm(self):
        return MagicMock()

    def test_primary_success(self):
        with patch(
            "tradingagents.llm_clients.chain.create_llm_client"
        ) as factory:
            factory.return_value.get_llm.return_value = self._fake_llm()
            provider, llm = create_client_with_fallback(
                ["openai", "deepseek"], "gpt-5.6", api_keys={"openai": "sk-x"}
            )
        assert provider == "openai"
        assert llm is not None
        assert factory.call_args.kwargs["api_key"] == "sk-x"

    def test_falls_to_second_provider_when_primary_raises(self):
        with patch(
            "tradingagents.llm_clients.chain.create_llm_client"
        ) as factory:
            factory.side_effect = [ValueError("bad key"), MagicMock(get_llm=lambda: self._fake_llm())]
            provider, llm = create_client_with_fallback(
                ["openai", "deepseek"], "gpt-5.6", api_keys={"openai": "sk-x", "deepseek": "sk-d"}
            )
        assert provider == "deepseek"
        # fallback lấy model mặc định của provider đó từ catalog
        assert factory.call_args.kwargs["model"] != "gpt-5.6"

    def test_all_fail_raises_valueerror(self):
        with patch(
            "tradingagents.llm_clients.chain.create_llm_client",
            side_effect=ValueError("boom"),
        ):
            with pytest.raises(ValueError, match="All providers in chain failed"):
                create_client_with_fallback(
                    ["openai", "deepseek"], "gpt-5.6", api_keys={"openai": "k", "deepseek": "k"}
                )

    def test_skips_provider_without_key(self):
        with patch(
            "tradingagents.llm_clients.chain.create_llm_client"
        ) as factory:
            factory.return_value.get_llm.return_value = self._fake_llm()
            provider, _ = create_client_with_fallback(
                ["openai", "deepseek"], "gpt-5.6", api_keys={"deepseek": "sk-d"}
            )
        assert provider == "deepseek"
        assert factory.call_count == 1

    def test_cooldown_skips_provider(self):
        health = ProviderHealth()
        health.record_failure("openai", Exception("quota exhausted"))
        with patch(
            "tradingagents.llm_clients.chain.create_llm_client"
        ) as factory, patch("tradingagents.llm_clients.chain._health", health):
            factory.return_value.get_llm.return_value = self._fake_llm()
            provider, _ = create_client_with_fallback(
                ["openai", "deepseek"], "gpt-5.6", api_keys={"openai": "k", "deepseek": "k"}
            )
        assert provider == "deepseek"
        assert factory.call_count == 1

    def test_keyless_provider_needs_no_key(self):
        with patch(
            "tradingagents.llm_clients.chain.create_llm_client"
        ) as factory:
            factory.return_value.get_llm.return_value = self._fake_llm()
            provider, _ = create_client_with_fallback(
                ["ollama", "deepseek"], "gpt-5.6", api_keys={}
            )
        assert provider == "ollama"

    def test_custom_only_provider_without_model_is_skipped(self):
        # groq là custom-only trong catalog (placeholder 'custom'): ở vị trí
        # FALLBACK không có model mặc định -> bị bỏ qua dù có key; provider
        # chính thì giữ model user chọn nên vẫn được thử.
        with patch(
            "tradingagents.llm_clients.chain.create_llm_client"
        ) as factory:
            factory.side_effect = [
                ValueError("boom"),                                  # openai fail
                MagicMock(get_llm=lambda: self._fake_llm()),         # deepseek ok
            ]
            provider, _ = create_client_with_fallback(
                ["openai", "groq", "deepseek"],
                "gpt-5.6",
                api_keys={"openai": "bad", "groq": "k", "deepseek": "k"},
            )
        assert provider == "deepseek"
        # groq bị skip: chỉ 2 lượt gọi factory (openai + deepseek)
        assert factory.call_count == 2
