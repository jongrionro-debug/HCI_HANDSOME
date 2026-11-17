"""OpenCode Go (DeepSeek) chat/completions adapter; fake transport, no network."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from stylemate_memory.errors import StyleMateError
from stylemate_memory.llm import OpenAIResponsesGateway, OpenCodeGoChatGateway, create_model_gateway
from stylemate_memory.settings import DEEPSEEK_DEFAULT_MODEL, ConsumerSettings

ENDPOINT = "https://example.invalid/v1/chat/completions"
KEY = "dummy-api-key"
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}


def chat(content="{\"ok\": true}", finish="stop", **message):
    return {"choices": [{"index": 0, "finish_reason": finish,
                         "message": {"role": "assistant", "content": content, **message}}]}


class FakeTransport:
    def __init__(self, response=None, error=None):
        self.response = response if response is not None else chat()
        self.error = error
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append((url, dict(headers), payload, timeout))
        if self.error is not None:
            raise self.error
        return self.response


def gateway(transport, **options):
    return OpenCodeGoChatGateway(endpoint=ENDPOINT, model="deepseek-test", api_key=KEY, transport=transport, **options)


class OpenCodeGoChatTests(unittest.TestCase):
    def test_request_is_chat_json_mode_with_schema_and_identifying_headers(self):
        transport = FakeTransport()
        self.assertEqual(gateway(transport, session_id="sess-1").complete("지시", {"값": "한글"}, SCHEMA), {"ok": True})
        url, headers, payload, _ = transport.calls[0]
        self.assertEqual(url, ENDPOINT)
        self.assertEqual(headers["Authorization"], f"Bearer {KEY}")
        self.assertEqual(headers["x-opencode-session"], "sess-1")
        self.assertNotIn("python-urllib", headers["User-Agent"].lower())
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["model"], "deepseek-test")
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        on = FakeTransport()
        gateway(on, thinking=True).complete("", {}, SCHEMA)
        self.assertNotIn("thinking", on.calls[0][2])
        system, user = payload["messages"]
        self.assertEqual((system["role"], user["role"]), ("system", "user"))
        self.assertIn("JSON", system["content"])
        self.assertIn(json.dumps(SCHEMA, sort_keys=True), system["content"])
        self.assertEqual(json.loads(user["content"]), {"값": "한글"})
        self.assertNotIn(KEY, json.dumps(payload))

    def test_non_success_shapes_are_safe_errors_not_partial_results(self):
        cases = [
            (chat(finish="length"), "provider_incomplete"),
            (chat(finish="content_filter"), "provider_refusal"),
            (chat(refusal="no"), "provider_refusal"),
            (chat(content=None), "empty_response"),
            (chat(content="  "), "empty_response"),
            (chat(content=["x"]), "provider_invalid_response"),
            ({"choices": []}, "provider_invalid_response"),
            ({"choices": [chat()["choices"][0]] * 2}, "provider_invalid_response"),
            ({"error": {"message": "private-body"}}, "provider_error"),
            ({"status_code": 429}, "provider_rate_limited"),
            ({"status_code": 500}, "provider_http_error"),
            (chat(content="not json"), "invalid_output"),
            (chat(content="[1]"), "invalid_output"),
            (chat(content='{"ok": true, "ok": false}'), "invalid_output"),
            (chat(content=f'{{"echo": "{KEY}"}}'), "invalid_output"),
        ]
        for response, code in cases:
            with self.subTest(code=code, response=str(response)[:50]):
                with self.assertRaises(StyleMateError) as caught:
                    gateway(FakeTransport(response=response)).complete("", {}, SCHEMA)
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn("private-body", str(caught.exception))

    def test_transport_errors_hide_details_and_do_not_retry(self):
        for error, code in ((RuntimeError(KEY), "provider_unavailable"),
                            (TimeoutError(KEY), "provider_timeout"),
                            (StyleMateError("provider_timeout", KEY), "provider_timeout")):
            transport = FakeTransport(error=error)
            with self.subTest(code=code), self.assertRaises(StyleMateError) as caught:
                gateway(transport).complete("", {}, SCHEMA)
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn(KEY, str(caught.exception))
            self.assertEqual(len(transport.calls), 1)

    def test_endpoint_has_no_default_and_must_be_https(self):
        for endpoint in ("", "http://x.invalid/v1", "https://x .invalid", None):
            with self.subTest(endpoint=endpoint), self.assertRaises(StyleMateError) as caught:
                OpenCodeGoChatGateway(endpoint=endpoint, model="m", api_key=KEY)
            self.assertEqual(caught.exception.code, "invalid_endpoint")
        with self.assertRaises(StyleMateError) as caught:
            create_model_gateway("opencode-go", model="m", api_key=KEY)
        self.assertEqual(caught.exception.code, "invalid_endpoint")
        with self.assertRaises(StyleMateError) as caught:
            OpenCodeGoChatGateway(endpoint=ENDPOINT, model="m", api_key="")
        self.assertEqual(caught.exception.code, "invalid_api_key")

    def test_factory_and_fake_provider_reject_misplaced_configuration(self):
        built = create_model_gateway("opencode-go", model="m", api_key=KEY, endpoint=ENDPOINT, transport=FakeTransport())
        self.assertIsInstance(built, OpenCodeGoChatGateway)
        with self.assertRaises(StyleMateError):
            create_model_gateway("fake", endpoint=ENDPOINT)

    def test_opencode_defaults_allow_reasoning_tokens_and_slow_replies(self):
        built = create_model_gateway("opencode-go", model="m", api_key=KEY, endpoint=ENDPOINT)
        self.assertEqual((built.max_output_tokens, built.timeout), (8000, 120.0))
        openai = create_model_gateway("openai", model="m", api_key=KEY)
        self.assertEqual((openai.max_output_tokens, openai.timeout), (1200, 30.0))

    def test_openai_responses_request_is_unchanged(self):
        transport = FakeTransport(response={"status": "completed", "output_text": "{\"ok\": true}"})
        OpenAIResponsesGateway(model="m", api_key=KEY, transport=transport).complete("i", {}, SCHEMA)
        payload = transport.calls[0][2]
        self.assertEqual(payload["text"]["format"]["strict"], True)
        self.assertIs(payload["store"], False)
        self.assertNotIn("User-Agent", transport.calls[0][1])


class OpenCodeGoSettingsTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.args = {"db": str(self.root / "m.sqlite3"), "catalog_db": str(self.root / "c.sqlite3")}

    def options(self, **extra):
        class Options:
            db = catalog_db = image_root = user = provider = model = port = endpoint = None
        o = Options()
        for key, value in {**self.args, **extra}.items():
            setattr(o, key, value)
        return o

    def test_environment_selects_provider_model_and_endpoint_without_reading_key(self):
        env = {"STYLEMATE_PROVIDER": "opencode-go", "STYLEMATE_OPENCODE_ENDPOINT": ENDPOINT}
        settings = ConsumerSettings.from_options(self.options(), env)
        self.assertEqual((settings.provider, settings.model, settings.endpoint),
                         ("opencode-go", DEEPSEEK_DEFAULT_MODEL, ENDPOINT))
        env["STYLEMATE_MODEL"] = "deepseek-v4-pro"
        self.assertEqual(ConsumerSettings.from_options(self.options(), env).model, "deepseek-v4-pro")
        with patch("urllib.request.urlopen", side_effect=AssertionError("network")):
            built = settings.gateway(settings={"OPENCODE_API_KEY": KEY}, transport=FakeTransport())
        self.assertIsInstance(built, OpenCodeGoChatGateway)

    def test_missing_key_or_endpoint_fails_explicitly_without_fallback(self):
        settings = ConsumerSettings.from_options(self.options(provider="opencode-go", endpoint=ENDPOINT), {})
        with self.assertRaises(StyleMateError) as caught:
            settings.gateway(settings={})
        self.assertEqual(caught.exception.code, "invalid_api_key")
        no_endpoint = ConsumerSettings.from_options(self.options(provider="opencode-go"), {})
        with self.assertRaises(StyleMateError) as caught:
            no_endpoint.gateway(settings={"OPENCODE_API_KEY": KEY})
        self.assertEqual(caught.exception.code, "invalid_endpoint")

    def test_openai_settings_keep_their_default_and_ignore_endpoint(self):
        settings = ConsumerSettings.from_options(self.options(provider="openai", endpoint=ENDPOINT), {})
        self.assertEqual((settings.model, settings.endpoint), ("gpt-6-luna", None))
        with self.assertRaises(StyleMateError):
            ConsumerSettings.from_options(self.options(provider="other"), {})


if __name__ == "__main__":
    unittest.main()
