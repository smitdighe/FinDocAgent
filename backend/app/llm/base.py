"""Provider Protocol + usage/cost primitives.

Rule enforced by tests: nothing under app/agents/ imports an SDK — agents
receive an LLMProvider via DI and call complete()/stream() only.
"""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict, runtime_checkable

Role = Literal["system", "user", "assistant"]


class Message(TypedDict):
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class TokenPrice:
    """USD per million tokens. Providers expose this so observability/cost.py
    can turn Usage into dollars without knowing the provider."""

    input_usd_per_mtok: float
    output_usd_per_mtok: float


@dataclass(frozen=True, slots=True)
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(self.tokens_in + other.tokens_in, self.tokens_out + other.tokens_out)


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    usage: Usage
    model: str
    provider: str


@dataclass(frozen=True, slots=True)
class StreamChunk:
    delta: str
    # Set on the terminal chunk when the provider reports final usage.
    usage: Usage | None = None


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    model: str
    price: TokenPrice

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> Completion: ...

    def stream(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> AsyncIterator[StreamChunk]: ...
