"""OpenAI-compatible adapter. Serves two purposes:

1. `OpenAIProvider` — proves the provider abstraction against a third API.
2. Base class for `VLLMProvider` (vLLM speaks the OpenAI protocol).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any, cast

from openai import AsyncOpenAI

from app.llm.base import Completion, Message, StreamChunk, TokenPrice, Usage

OPENAI_PRICES: dict[str, TokenPrice] = {
    # USD per Mtok, checked 2026-07; unknown models fall back to 0.
    "gpt-4o-mini": TokenPrice(0.15, 0.60),
    "gpt-4.1-mini": TokenPrice(0.40, 1.60),
}


class OpenAICompatibleProvider:
    name = "openai-compatible"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        price: TokenPrice | None = None,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.price = price or TokenPrice(0.0, 0.0)

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> Completion:
        resp = await self._client.chat.completions.create(
            model=self.model,
            messages=cast("Any", list(messages)),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = resp.choices[0].message.content or ""
        usage = Usage()
        if resp.usage is not None:
            usage = Usage(
                tokens_in=int(resp.usage.prompt_tokens or 0),
                tokens_out=int(resp.usage.completion_tokens or 0),
            )
        return Completion(text=text, usage=usage, model=self.model, provider=self.name)

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> AsyncIterator[StreamChunk]:
        stream = await self._client.chat.completions.create(
            model=self.model,
            messages=cast("Any", list(messages)),
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
        final_usage: Usage | None = None
        async for chunk in stream:
            if chunk.choices:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    yield StreamChunk(delta=delta)
            if chunk.usage is not None:
                final_usage = Usage(
                    tokens_in=int(chunk.usage.prompt_tokens or 0),
                    tokens_out=int(chunk.usage.completion_tokens or 0),
                )
        yield StreamChunk(delta="", usage=final_usage or Usage())


class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str, price: TokenPrice | None = None) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for LLM_PROVIDER=openai")
        super().__init__(
            api_key=api_key,
            model=model,
            price=price or OPENAI_PRICES.get(model, TokenPrice(0.0, 0.0)),
        )
