from __future__ import annotations

import os

from dotenv import find_dotenv, load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv(find_dotenv())

MAX_RECURSION_DEPTH = int(os.getenv("MAX_RECURSION_DEPTH", "80"))


def get_model() -> ChatOpenAI:
    """Create the chat model used by LangChain agents from environment variables."""
    provider = os.getenv("MODEL_PROVIDER", "").strip().lower()
    api_key = os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
    model_name = os.getenv("MODEL_NAME")
    base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_API_BASE")

    if not provider:
        provider = "deepseek" if os.getenv("DEEPSEEK_API_KEY") else "openai"
    if not model_name:
        model_name = "deepseek-chat" if provider == "deepseek" else "gpt-4o"
    if not base_url and provider == "deepseek":
        base_url = "https://api.deepseek.com"
    if not api_key:
        raise RuntimeError(
            "No model API key configured. Set API_KEY, OPENAI_API_KEY, or DEEPSEEK_API_KEY."
        )

    kwargs = {
        "model": model_name,
        "api_key": api_key,
        "temperature": float(os.getenv("MODEL_TEMPERATURE", "0")),
    }
    if base_url:
        kwargs["base_url"] = base_url
    return ChatOpenAI(**kwargs)
