from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str | bool]:
    s = get_settings()
    # agent_enabled tells the website whether this server runs the agent. provider says which model host is in use (ollama or groq).
    return {
        "status": "ok", "service": "dealdesk", "model": s.llm_model_main, "provider": s.llm_provider,
        "agent_enabled": s.agent_enabled,
    }  # fmt: skip
