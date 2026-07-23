"""Build the active provider from settings.

Acceptance criterion: switching LLM_PROVIDER=groq|vllm|openai changes
inference with zero edits under app/agents/.
"""

from app.config import Settings
from app.llm.base import LLMProvider
from app.llm.groq_provider import GroqProvider
from app.llm.openai_provider import OpenAIProvider
from app.llm.vllm_provider import VLLMProvider


def build_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "groq":
        return GroqProvider(settings.groq_api_key, settings.groq_model)
    if settings.llm_provider == "vllm":
        return VLLMProvider(settings.vllm_base_url, settings.vllm_model)
    if settings.llm_provider == "openai":
        return OpenAIProvider(settings.openai_api_key, settings.openai_model)
    raise ValueError(f"unknown LLM_PROVIDER: {settings.llm_provider!r}")  # pragma: no cover
