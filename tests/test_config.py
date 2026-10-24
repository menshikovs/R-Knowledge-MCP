import pytest

from cran_knowledge_mcp.config import (
    cache_bytes,
    cache_ttl,
    context7_api_key,
    http_user_agent,
    positive_float,
    prompt_default_detail_level,
    prompt_default_target,
    prompt_intelligence_enabled,
    prompt_max_grounding_packages,
)
from cran_knowledge_mcp.errors import KnowledgeError


def test_configuration_defaults_and_context7_key(monkeypatch):
    monkeypatch.delenv("CACHE_TTL_SECONDS", raising=False)
    monkeypatch.delenv("CACHE_MAX_BYTES", raising=False)
    monkeypatch.delenv("CONTEXT7_API_KEY", raising=False)
    assert cache_ttl(300) == 300
    assert cache_bytes() == 64 << 20
    assert context7_api_key() is None
    monkeypatch.setenv("CONTEXT7_API_KEY", "  server-secret  ")
    assert context7_api_key() == "server-secret"


@pytest.mark.parametrize("value", ["0", "-1", "not-a-number", "301"])
def test_timeout_configuration_is_bounded(monkeypatch, value):
    monkeypatch.setenv("HTTP_TIMEOUT_SECONDS", value)
    with pytest.raises(KnowledgeError, match="HTTP_TIMEOUT_SECONDS"):
        positive_float("HTTP_TIMEOUT_SECONDS", 15)


def test_cache_byte_configuration_is_bounded(monkeypatch):
    monkeypatch.setenv("CACHE_MAX_BYTES", str(256 << 20))
    assert cache_bytes() == 256 << 20
    monkeypatch.setenv("CACHE_MAX_BYTES", str((256 << 20) + 1))
    with pytest.raises(KnowledgeError, match="CACHE_MAX_BYTES"):
        cache_bytes()


def test_http_user_agent_rejects_header_injection(monkeypatch):
    monkeypatch.setenv("HTTP_USER_AGENT", "client\r\nAuthorization: leaked")
    with pytest.raises(KnowledgeError, match="HTTP_USER_AGENT"):
        http_user_agent()


def test_prompt_configuration_defaults_and_bounds(monkeypatch):
    for name in (
        "PROMPT_INTELLIGENCE_ENABLED",
        "PROMPT_DEFAULT_TARGET",
        "PROMPT_DEFAULT_DETAIL_LEVEL",
        "PROMPT_MAX_GROUNDING_PACKAGES",
    ):
        monkeypatch.delenv(name, raising=False)
    assert prompt_intelligence_enabled() is True
    assert prompt_default_target() == "generic"
    assert prompt_default_detail_level() == "standard"
    assert prompt_max_grounding_packages() == 5
    monkeypatch.setenv("PROMPT_INTELLIGENCE_ENABLED", "sometimes")
    with pytest.raises(KnowledgeError, match="PROMPT_INTELLIGENCE_ENABLED"):
        prompt_intelligence_enabled()
    monkeypatch.setenv("PROMPT_MAX_GROUNDING_PACKAGES", "11")
    with pytest.raises(KnowledgeError, match="PROMPT_MAX_GROUNDING_PACKAGES"):
        prompt_max_grounding_packages()
