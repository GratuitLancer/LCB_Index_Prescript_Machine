"""Server-side LLM configuration. Environment variables override the project .env."""

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
import os
from typing import Literal
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False, encoding="utf-8-sig")


class ConfigurationError(ValueError):
    pass


class _GenerationOptions(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    timeout_seconds: float = Field(default=120, ge=1, le=600)
    max_tokens: int = Field(default=80, ge=1, le=32768)
    temperature: float | None = Field(default=1.0, ge=0, le=2)
    token_limit_field: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    base_url: str
    model: str
    api_key: str = field(repr=False)
    timeout_seconds: float = 120
    max_tokens: int = 80
    temperature: float | None = 1.0
    token_limit_field: str = "max_tokens"


@lru_cache(maxsize=1)
def get_settings() -> LLMSettings:
    provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
    if provider not in {"ollama", "openai_compatible"}:
        raise ConfigurationError("LLM_PROVIDER 必须为 ollama 或 openai_compatible。")

    local = provider == "ollama"
    base_url = os.getenv("LLM_BASE_URL", "http://localhost:11434" if local else "").strip().rstrip("/")
    model = os.getenv("LLM_MODEL", "qwen2.5:3b" if local else "").strip()
    api_key = os.getenv("LLM_API_KEY", "").strip()
    try:
        url = urlsplit(base_url)
        valid_url = (
            url.scheme in {"http", "https"} and url.hostname and url.port != 0
            and not url.username and not url.password and not url.query and not url.fragment
            and not any(char.isspace() for char in base_url)
        )
    except ValueError:
        valid_url = False
    if not valid_url:
        raise ConfigurationError("LLM_BASE_URL 必须为 HTTP(S) API 基础地址，不能包含账号、查询参数或片段。")
    if url.path.endswith(("/chat/completions", "/api/generate")):
        raise ConfigurationError("LLM_BASE_URL 请填写基础地址，不要包含 /chat/completions 或 /api/generate。")
    if not model:
        raise ConfigurationError("请在后端 .env 中设置 LLM_MODEL。")
    if not local and not api_key:
        raise ConfigurationError("请在后端 .env 中设置 LLM_API_KEY。")
    if "\r" in api_key or "\n" in api_key:
        raise ConfigurationError("LLM_API_KEY 不能包含换行。")

    temperature = os.getenv("LLM_TEMPERATURE", "1.0").strip()
    try:
        options = _GenerationOptions(
            timeout_seconds=os.getenv("LLM_TIMEOUT_SECONDS", "120"),
            max_tokens=os.getenv("LLM_MAX_TOKENS", "80" if local else "256"),
            temperature=temperature if temperature else None,
            token_limit_field=os.getenv("LLM_TOKEN_LIMIT_FIELD", "max_tokens").strip(),
        )
    except ValidationError:
        raise ConfigurationError(
            "LLM 参数无效：超时需为 1–600 秒，token 上限需为 1–32768，"
            "temperature 需为 0–2 或留空，token 字段需为 max_tokens 或 max_completion_tokens。"
        ) from None
    return LLMSettings(provider, base_url, model, api_key, **options.model_dump())


def get_cors_origins() -> list[str]:
    return [origin.strip() for origin in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if origin.strip()]
