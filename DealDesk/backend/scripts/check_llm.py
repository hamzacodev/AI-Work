"""Calls the real model (Ollama by default) with both roles.

Run from backend/:  uv run python scripts/check_llm.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so "app" is importable

from pydantic import BaseModel

from app.core.llm import LLMError, get_llm


class Parsed(BaseModel):
    item: str
    max_price: float
    currency: str


async def main() -> int:
    llm = get_llm()
    try:
        for role in ("main", "fast"):
            out = await llm.complete_json(
                role,
                "Extract the item, the maximum price and the currency code from the request.",
                "I want to buy a Dell XPS 15 under $800 with 16GB RAM",
                Parsed,
            )
            print(f"OK {role} ({llm.model_name(role)}): {out}")
    except LLMError as e:
        print(f"FAIL: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
