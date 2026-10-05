import pytest

from app.core.config import Settings


def test_local_uses_ollama_and_never_groq():
    s = Settings(_env_file=None, groq_api_key="gsk_test")
    assert s.app_env == "local" and s.llm_provider == "ollama" and "11434" in s.llm_base_url and s.llm_api_key == "ollama"


def test_production_switches_to_groq_by_itself():
    s = Settings(_env_file=None, app_env="production", groq_api_key="gsk_test")
    assert s.llm_provider == "groq" and s.llm_base_url == "https://api.groq.com/openai/v1" and s.llm_api_key == "gsk_test"
    assert s.llm_model_main == "openai/gpt-oss-120b" and s.llm_model_fast == "openai/gpt-oss-20b" and s.llm_max_concurrency == 3


def test_production_without_a_groq_key_refuses_to_start():
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        Settings(_env_file=None, app_env="production")


def test_health_tells_the_website_which_model_and_whether_the_agent_runs():
    from fastapi.testclient import TestClient

    from main import app

    body = TestClient(app).get("/health").json()
    assert body["status"] == "ok" and "provider" in body and isinstance(body["agent_enabled"], bool)
