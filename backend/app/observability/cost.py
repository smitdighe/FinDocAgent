"""Token -> USD accounting from provider price tables."""

from app.llm.base import TokenPrice, Usage


def usd_for_usage(usage: Usage, price: TokenPrice) -> float:
    usd = (
        usage.tokens_in * price.input_usd_per_mtok
        + usage.tokens_out * price.output_usd_per_mtok
    ) / 1_000_000
    return round(usd, 8)
