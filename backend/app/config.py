"""Application settings. Everything is env-driven; no secrets in code."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "postgresql+asyncpg://findoc:findoc@localhost:5433/findoc"
    storage_dir: Path = Path("./data")

    # Public base URL of the object store holding rendered page JPEGs (e.g. a
    # Cloudflare R2 public bucket, "https://pub-xxxx.r2.dev"). When set, the
    # page-image endpoint 307-redirects to
    #   {base}/filings/{accession_nodash}/pages/page_{n:04d}.jpg
    # instead of streaming a local file. Empty = serve from storage_dir on the
    # local disk (dev default). Render's disk is ephemeral, so prod sets this.
    image_public_base_url: str = ""

    @field_validator("image_public_base_url", mode="before")
    @classmethod
    def _strip_trailing_slash(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip().rstrip("/")
        return v

    # --- LLM provider selection (see app/llm/factory.py) ---
    llm_provider: Literal["groq", "vllm", "openai"] = "groq"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    vllm_base_url: str = "http://localhost:8001/v1"
    vllm_model: str = "meta-llama/Llama-3.1-8B-Instruct"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # --- embeddings (ColPali family; 128-dim multi-vectors) ---
    colpali_model: str = "vidore/colqwen2-v1.0"
    colpali_device: str = "auto"  # auto | cuda | cpu | mps
    colpali_dtype: str = "auto"  # auto | bfloat16 | float32
    # Load the ColPali model in the API process to embed queries for the
    # visual/MaxSim retrieval path. Off by default: the server stays light and
    # retrieval degrades to FTS (see agents/retrieval.py). Turn on where the
    # model is available and page embeddings exist.
    query_embedding: bool = False

    # --- EDGAR ---
    edgar_user_agent: str = ""
    edgar_max_requests_per_sec: float = 5.0

    # --- rate limiting ("<count>/<second|minute|hour>") ---
    rate_limit_query: str = "20/minute"

    # --- observability (phase 5) ---
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # --- rendering ---
    render_dpi: int = 150
    render_jpeg_quality: int = 85

    # Browser origins allowed by CORS. In prod set CORS_ORIGINS to the deployed
    # frontend origin(s) as a comma-separated list, e.g.
    #   CORS_ORIGINS=https://findoc-frontend.vercel.app
    # Origin must be scheme+host[+port] with no path or trailing slash — the
    # validator strips a stray trailing slash so a pasted URL still matches.
    # NoDecode disables pydantic's default JSON parsing so a plain comma list
    # works (no need to type a JSON array into the Render dashboard).
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip().rstrip("/") for o in v.split(",") if o.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
