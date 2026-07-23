"""vLLM adapter — LOCAL ONLY.

vLLM serves the OpenAI chat protocol, so this is the OpenAI-compatible client
pointed at a local base URL. Local inference costs $0 by definition. Requires
a vLLM recent enough to honor stream_options.include_usage (>= 0.6).
"""

from app.llm.base import TokenPrice
from app.llm.openai_provider import OpenAICompatibleProvider


class VLLMProvider(OpenAICompatibleProvider):
    name = "vllm"

    def __init__(self, base_url: str, model: str) -> None:
        if not base_url:
            raise ValueError("VLLM_BASE_URL is required for LLM_PROVIDER=vllm")
        super().__init__(
            api_key="EMPTY",  # vLLM ignores the key but the client requires one
            model=model,
            base_url=base_url,
            price=TokenPrice(0.0, 0.0),
        )
