"""Groq adapter — the production default."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any, cast

from groq import AsyncGroq

from app.llm.base import Completion, Message, StreamChunk, TokenPrice, Usage

# USD per Mtok, checked 2026-07 (groq.com/pricing). Prices drift — pass an
# explicit TokenPrice for models not listed; unknown models fall back to 0
# so cost shows up as 0 rather than fabricated.
GROQ_PRICES: dict[str, TokenPrice] = {
    "openai/gpt-oss-120b": TokenPrice(0.15, 0.60),
    "llama-3.1-8b-instant": TokenPrice(0.05, 0.08),
}


class GroqProvider:
    name = "groq"

    def __init__(self, api_key: str, model: str, price: TokenPrice | None = None) -> None:
        if not api_key:
            raise ValueError("GROQ_API_KEY is required for LLM_PROVIDER=groq")
        self._client = AsyncGroq(api_key=api_key)
        self.model = model
        self.price = price or GROQ_PRICES.get(model, TokenPrice(0.0, 0.0))

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
        )
        final_usage: Usage | None = None
        async for chunk in stream:
            if chunk.choices:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    yield StreamChunk(delta=delta)
            # Groq reports final usage on the terminal chunk under x_groq.
            x_groq = getattr(chunk, "x_groq", None)
            usage = getattr(x_groq, "usage", None) if x_groq is not None else None
            if usage is not None:
                final_usage = Usage(
                    tokens_in=int(usage.prompt_tokens or 0),
                    tokens_out=int(usage.completion_tokens or 0),
                )
        yield StreamChunk(delta="", usage=final_usage or Usage())
