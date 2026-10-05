from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All settings come from environment variables or backend/.env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # "local" (the default) uses Ollama on this machine: free, no limits. "production" switches the model to Groq by itself, so a
    # deployed server needs ONE variable (APP_ENV=production) plus GROQ_API_KEY. Your local Groq quota is never touched.
    app_env: str = "local"
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model_main: str = "openai/gpt-oss-120b"  # the models this project's Groq key can use (checked 3 Oct 2026, smoke tested)
    groq_model_fast: str = "openai/gpt-oss-20b"
    groq_model_fallback: str = "openai/gpt-oss-20b"
    groq_max_concurrency: int = 3
    llm_usage_log: str = "data/llm_usage.jsonl"  # every model call is appended here (counts only, no prompts). Empty turns it off.
    research_mode: str = "web"  # "web" searches the web (uses Tavily credits). "fixed" uses a demo market price and spends nothing.

    llm_provider: str = "ollama"
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    llm_model_main: str = "llama3.1:8b"
    llm_model_fast: str = "llama3.1:8b"
    llm_model_fallback: str = "llama3.1:8b"
    llm_max_concurrency: int = 2
    llm_timeout_seconds: float = 120.0  # a slow local model may need more

    tavily_api_key: str = ""
    tavily_monthly_cap: int = 800
    research_cache_hours: int = 24

    supabase_url: str = ""
    supabase_service_role_key: str = ""

    allowed_origins: str = "http://localhost:3000"
    daily_llm_call_budget: int = 600
    max_llm_calls_per_deal: int = 300
    max_vendors_per_deal: int = 10
    max_rounds: int = 10
    ceiling_ratio: float = 0.95
    rate_limit_per_minute: int = 30
    client_ip_header: str = "cf-connecting-ip"  # the header Cloudflare sets to the visitor's real address
    agent_enabled: bool = False  # true on a server that should run the agent (start negotiations, resume after restarts)
    allow_reset: bool = False  # TESTING ONLY: lets POST /admin/reset wipe every deal and chat. Keep false on any server others can reach.
    real_send_enabled: bool = False
    owner_test_allowlist: str = ""

    @model_validator(mode="after")
    def use_groq_when_deployed(self) -> "Settings":
        if self.app_env.lower() == "production":
            if not self.groq_api_key:
                raise ValueError("APP_ENV=production needs GROQ_API_KEY, because the deployed server cannot reach Ollama on your laptop.")
            self.llm_provider, self.llm_base_url, self.llm_api_key = "groq", self.groq_base_url, self.groq_api_key
            self.llm_model_main, self.llm_model_fast, self.llm_model_fallback = self.groq_model_main, self.groq_model_fast, self.groq_model_fallback
            self.llm_max_concurrency = self.groq_max_concurrency
        return self

    @property
    def origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
