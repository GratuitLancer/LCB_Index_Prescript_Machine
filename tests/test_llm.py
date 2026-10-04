import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import requests
from fastapi.testclient import TestClient

from app.config import ConfigurationError, get_settings
from app.llm_client import LLMError, generate_from_llm
from app.main import app
from app.prompt_builder import MODE_STYLES, build_prompt
from app.rule_engine import normalize_output
from app.storage import get_recent_prescripts, save_prescript

CLOUD_ENV = {
    "LLM_PROVIDER": "openai_compatible",
    "LLM_BASE_URL": "https://llm.example/v1/",
    "LLM_MODEL": "test-model",
    "LLM_API_KEY": "secret-test-key",
}


def response_for(data=None, status=200, raw=None):
    response = requests.Response()
    response.status_code = status
    response.encoding = "utf-8"
    response._content = raw if raw is not None else json.dumps(data, ensure_ascii=False).encode("utf-8")
    response._content_consumed = True
    return response


def chat_response(text="将桌面左侧的空杯移到未编号的角落。"):
    return response_for({"choices": [{"message": {"content": text}}]})


class EnvironmentTestCase(unittest.TestCase):
    def setUp(self):
        self.env_patch = patch.dict(os.environ, {}, clear=True)
        self.env_patch.start()
        get_settings.cache_clear()
        self.addCleanup(self.env_patch.stop)
        self.addCleanup(get_settings.cache_clear)


class ConfigurationTests(EnvironmentTestCase):
    def test_defaults_preserve_ollama(self):
        settings = get_settings()
        self.assertEqual(settings.provider, "ollama")
        self.assertEqual(settings.model, "qwen2.5:3b")
        self.assertEqual(settings.base_url, "http://localhost:11434")
        self.assertEqual(settings.max_tokens, 80)

    def test_cloud_requires_base_model_and_key(self):
        for missing in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY"):
            with self.subTest(missing=missing), patch.dict(os.environ, CLOUD_ENV):
                os.environ.pop(missing)
                get_settings.cache_clear()
                with self.assertRaises(ConfigurationError):
                    get_settings()

    def test_cloud_settings_and_secret_repr(self):
        os.environ.update(CLOUD_ENV)
        settings = get_settings()
        self.assertEqual(settings.base_url, "https://llm.example/v1")
        self.assertEqual(settings.max_tokens, 256)
        self.assertNotIn("secret-test-key", repr(settings))

    def test_invalid_configuration_is_rejected_without_echoing_values(self):
        cases = {
            "LLM_PROVIDER": ["unknown"],
            "LLM_BASE_URL": [
                "file:///secret-test-key", "https://user:secret-test-key@llm.example",
                "https://llm.example?key=secret-test-key",
                "https://llm.example/v1/chat/completions",
                "http://localhost:broken", "http://localhost:0",
            ],
            "LLM_TIMEOUT_SECONDS": ["0", "NaN", "secret-test-key"],
            "LLM_MAX_TOKENS": ["0", "1.5"],
            "LLM_TEMPERATURE": ["3", "inf"],
            "LLM_TOKEN_LIMIT_FIELD": ["unsupported"],
            "LLM_API_KEY": ["secret-test-key\nsecond-line"],
        }
        for name, values in cases.items():
            for value in values:
                with self.subTest(name=name, value=value), patch.dict(os.environ, {**CLOUD_ENV, name: value}):
                    get_settings.cache_clear()
                    with self.assertRaises(ConfigurationError) as caught:
                        get_settings()
                    self.assertNotIn("secret-test-key", str(caught.exception))


class AdapterTests(EnvironmentTestCase):
    def test_ollama_uses_configured_url_and_final_response(self):
        os.environ.update({"LLM_BASE_URL": "http://localhost:1234", "LLM_MODEL": "local-test"})
        with patch("app.llm_client.requests.post", return_value=response_for({
            "response": "  将桌面左侧的空杯移到角落  ", "thinking": "private reasoning"
        })) as post:
            text = generate_from_llm("prompt")
        self.assertEqual(text, "将桌面左侧的空杯移到角落")
        self.assertEqual(post.call_args.args[0], "http://localhost:1234/api/generate")
        self.assertEqual(post.call_args.kwargs["json"]["model"], "local-test")
        self.assertFalse(post.call_args.kwargs["json"]["stream"])
        self.assertIsNone(post.call_args.kwargs["headers"])

    def test_thinking_only_response_is_rejected(self):
        with patch("app.llm_client.requests.post", return_value=response_for({"thinking": "思考内容"})):
            with self.assertRaises(LLMError):
                generate_from_llm("prompt")

    def test_chat_completion_authentication_and_content(self):
        os.environ.update(CLOUD_ENV)
        with patch("app.llm_client.requests.post", return_value=chat_response()) as post:
            self.assertIn("空杯", generate_from_llm("中文提示"))
        self.assertEqual(post.call_args.args[0], "https://llm.example/v1/chat/completions")
        self.assertEqual(post.call_args.kwargs["headers"], {"Authorization": "Bearer secret-test-key"})
        self.assertEqual(post.call_args.kwargs["json"]["messages"], [{"role": "user", "content": "中文提示"}])
        self.assertEqual(post.call_args.kwargs["timeout"], (10, 120))
        self.assertFalse(post.call_args.kwargs["allow_redirects"])

    def test_model_specific_token_field_and_omitted_temperature(self):
        os.environ.update({
            **CLOUD_ENV, "LLM_TOKEN_LIMIT_FIELD": "max_completion_tokens",
            "LLM_TEMPERATURE": "", "LLM_MAX_TOKENS": "1024",
        })
        with patch("app.llm_client.requests.post", return_value=chat_response()) as post:
            generate_from_llm("prompt")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["max_completion_tokens"], 1024)
        self.assertNotIn("max_tokens", payload)
        self.assertNotIn("temperature", payload)

    def test_upstream_errors_are_sanitized(self):
        os.environ.update(CLOUD_ENV)
        for upstream, expected in ((401, 502), (403, 502), (404, 502), (429, 429), (500, 503), (400, 502), (302, 502)):
            with self.subTest(status=upstream), patch(
                "app.llm_client.requests.post",
                return_value=response_for({"error": "secret-test-key"}, status=upstream),
            ):
                with self.assertRaises(LLMError) as caught:
                    generate_from_llm("prompt")
                self.assertEqual(caught.exception.status_code, expected)
                self.assertNotIn("secret-test-key", str(caught.exception))

    def test_timeout_and_connection_failures(self):
        for error, expected in ((requests.Timeout("secret-test-key"), 504), (requests.ConnectionError("secret-test-key"), 503)):
            with self.subTest(error=type(error)), patch("app.llm_client.requests.post", side_effect=error):
                with self.assertRaises(LLMError) as caught:
                    generate_from_llm("prompt")
                self.assertEqual(caught.exception.status_code, expected)
                self.assertNotIn("secret-test-key", str(caught.exception))

    def test_malformed_and_empty_responses(self):
        os.environ.update(CLOUD_ENV)
        cases = [
            response_for(raw=b"not json"), response_for([]), response_for({}),
            response_for({"choices": []}), response_for({"choices": [{"message": None}]}),
            chat_response(None), chat_response("  "), chat_response(["not text"]),
        ]
        for response in cases:
            with self.subTest(body=response.content), patch("app.llm_client.requests.post", return_value=response):
                with self.assertRaises(LLMError):
                    generate_from_llm("prompt")


class ApplicationTests(EnvironmentTestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_patch = patch("app.storage.DB_PATH", Path(self.temp.name) / "prescripts.db")
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_webpage_assets_and_secret_files(self):
        root = self.client.get("/")
        self.assertEqual(root.status_code, 200)
        self.assertIn('src="app.js"', root.text)
        for asset in ("app.js", "style.css"):
            self.assertEqual(self.client.get("/web/" + asset).status_code, 200)
        self.assertEqual(self.client.get("/web/.env").status_code, 404)
        self.assertEqual(self.client.get("/.env").status_code, 404)

    def test_health_checks_config_without_calling_model_or_exposing_key(self):
        os.environ.update(CLOUD_ENV)
        with patch("app.llm_client.requests.post") as post:
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "configured")
        self.assertNotIn("secret-test-key", response.text)
        self.assertNotIn("base_url", response.json())
        post.assert_not_called()

    def test_missing_config_returns_503_without_call_or_save(self):
        os.environ["LLM_PROVIDER"] = "openai_compatible"
        with patch("app.llm_client.requests.post") as post:
            for path in ("/health", "/generate"):
                response = self.client.get(path) if path == "/health" else self.client.post(path, json={})
                self.assertEqual(response.status_code, 503)
        post.assert_not_called()
        self.assertEqual(get_recent_prescripts(), [])

    def test_cloud_generation_saves_normalized_text_with_persistent_id(self):
        os.environ.update(CLOUD_ENV)
        with patch("app.llm_client.requests.post", return_value=chat_response()) as post:
            first = self.client.post("/generate", json={"mode": "daily"})
            second = self.client.post("/generate", json={"mode": "absurd"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), {"id": 1, "mode": "daily", "prescript": "将桌面左侧的空杯移到未编号的角落"})
        self.assertEqual(second.json()["id"], 2)
        self.assertEqual(len(get_recent_prescripts()), 2)
        prompt = post.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertIn(MODE_STYLES["absurd"], prompt)
        self.assertIn(first.json()["prescript"], prompt)

    def test_default_local_generation_still_works(self):
        with patch("app.llm_client.requests.post", return_value=response_for({"response": "将空杯放到桌面左侧。"})):
            response = self.client.post("/generate", json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "ritual")

    def test_failed_generation_never_writes_history(self):
        os.environ.update(CLOUD_ENV)
        for response, expected in (
            (response_for({"error": "secret-test-key"}, 429), 429),
            (chat_response(""), 502),
            (chat_response("English only"), 502),
            (chat_response("<think>只包含思考内容</think>"), 502),
            (chat_response("<think>未闭合的思考内容"), 502),
        ):
            with self.subTest(body=response.content), patch("app.llm_client.requests.post", return_value=response):
                result = self.client.post("/generate", json={})
                self.assertEqual(result.status_code, expected)
                self.assertNotIn("secret-test-key", result.text)
                self.assertEqual(get_recent_prescripts(), [])

    def test_unsupported_mode_is_422_and_never_calls_model(self):
        with patch("app.llm_client.requests.post") as post:
            response = self.client.post("/generate", json={"mode": "typo"})
        self.assertEqual(response.status_code, 422)
        post.assert_not_called()

    def test_cross_origin_requests_are_not_allowed_by_default(self):
        response = self.client.options("/generate", headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "POST",
        })
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_history_order_limit_and_placeholder_filter(self):
        save_prescript("第一条", "ritual")
        save_prescript("静候下一则指令", "ritual")
        save_prescript("第二条", "daily")
        save_prescript("第三条", "absurd")
        self.assertEqual(get_recent_prescripts(limit=2), ["第二条", "第三条"])


class PromptTests(unittest.TestCase):
    def test_each_mode_and_only_ten_recent_entries_are_included(self):
        history = [f"历史编号{i}" for i in range(12)]
        for mode, style in MODE_STYLES.items():
            prompt = build_prompt(mode, history)
            self.assertIn(style, prompt)
            self.assertIn(json.dumps(history[-10:], ensure_ascii=False), prompt)
            self.assertNotIn('"历史编号0"', prompt)

    def test_reasoning_tags_are_removed(self):
        self.assertEqual(normalize_output("<think>分析请求</think>指令：将空杯放到桌面左侧。"), "将空杯放到桌面左侧")
        self.assertEqual(normalize_output("<think>分析请求"), "")


if __name__ == "__main__":
    unittest.main()
