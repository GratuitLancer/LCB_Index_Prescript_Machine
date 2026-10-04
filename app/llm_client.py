"""Ollama and OpenAI-compatible Chat Completions adapters."""

import requests

from app.config import LLMSettings, get_settings


class LLMError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _request_json(url: str, payload: dict, settings: LLMSettings, headers: dict | None = None) -> dict:
    try:
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=(min(10, settings.timeout_seconds), settings.timeout_seconds),
            allow_redirects=False,
        )
    except requests.Timeout:
        raise LLMError("模型响应超时，请稍后重试或调整 LLM_TIMEOUT_SECONDS。", 504) from None
    except requests.RequestException:
        raise LLMError("无法连接模型服务，请检查服务是否启动及 LLM_BASE_URL。", 503) from None

    try:
        status = response.status_code
        # Never expose upstream bodies, URLs or authorization headers to the browser.
        if status in {401, 403}:
            raise LLMError("模型服务认证失败，请检查后端 API 密钥和模型访问权限。")
        if status == 429:
            raise LLMError("模型服务限流或额度不足，请稍后重试并检查账户额度。", 429)
        if status == 404:
            raise LLMError("模型或 API 路径不存在，请检查 LLM_MODEL 和 LLM_BASE_URL。")
        if status >= 500:
            raise LLMError("模型服务暂时不可用，请稍后重试。", 503)
        if not 200 <= status < 300:
            raise LLMError("模型服务拒绝请求，请检查 API 地址、模型和生成参数。")
        try:
            data = response.json()
        except ValueError:
            raise LLMError("模型服务返回了无效 JSON。") from None
        if not isinstance(data, dict):
            raise LLMError("模型服务响应格式不符合预期。")
        return data
    finally:
        response.close()


def _require_text(content: object) -> str:
    if not isinstance(content, str) or not content.strip():
        raise LLMError("模型未返回正文，请检查模型、token 上限或内容限制后重试。")
    return content.strip()


def _generate_ollama(prompt: str, settings: LLMSettings) -> str:
    options = {"top_p": 0.95, "num_predict": settings.max_tokens, "repeat_penalty": 1.1}
    if settings.temperature is not None:
        options["temperature"] = settings.temperature
    data = _request_json(
        settings.base_url + "/api/generate",
        {"model": settings.model, "prompt": prompt, "stream": False, "options": options},
        settings,
    )
    # Thinking is not a final answer and must never become a saved prescript.
    return _require_text(data.get("response"))


def _generate_chat_completion(prompt: str, settings: LLMSettings) -> str:
    payload = {
        "model": settings.model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        settings.token_limit_field: settings.max_tokens,
    }
    if settings.temperature is not None:
        payload["temperature"] = settings.temperature
    data = _request_json(
        settings.base_url + "/chat/completions",
        payload,
        settings,
        headers={"Authorization": f"Bearer {settings.api_key}"},
    )
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMError("模型服务响应缺少 choices[0].message.content。") from None
    return _require_text(content)


def generate_from_llm(prompt: str, settings: LLMSettings | None = None) -> str:
    settings = settings or get_settings()
    if settings.provider == "ollama":
        return _generate_ollama(prompt, settings)
    return _generate_chat_completion(prompt, settings)


def generate_from_local_llm(prompt: str) -> str:
    """Backward-compatible entry point for callers explicitly using Ollama."""
    settings = get_settings()
    if settings.provider != "ollama":
        raise LLMError("当前配置不是 Ollama，请使用 generate_from_llm。", 503)
    return _generate_ollama(prompt, settings)
