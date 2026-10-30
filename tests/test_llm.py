import json
import os
import unittest
from unittest.mock import patch

from stylemate_memory.errors import StyleMateError
from stylemate_memory.llm import (
    DEFAULT_ENDPOINT,
    DEFAULT_MODEL,
    OpenAIResponsesGateway,
    OpenAIResponsesAdapter,
    create_model_gateway,
    _ProviderHTTPError,
    _urllib_transport,
)


def proposal() -> dict:
    return {
        "suggestions": [
            {
                "target_id": "pants-1",
                "feature": "fit",
                "values": ["Slim"],
                "match": "any",
                "source_ids": ["m-now"],
                "reason": "이번 요청에서 슬림핏을 원한다고 확인했습니다.",
            }
        ],
        "questions": [],
    }


def response_with_output(value: dict) -> dict:
    return {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps(value, ensure_ascii=False)}],
            }
        ],
    }


class FakeTransport:
    def __init__(self, response=None, error=None):
        self.response = response if response is not None else response_with_output(proposal())
        self.error = error
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append((url, headers, payload, timeout))
        if self.error is not None:
            raise self.error
        return self.response


class OpenAIResponsesAdapterTests(unittest.TestCase):
    def context(self):
        return {
            "user_id": "user-secret",
            "request_revision": 99,
            "targets": [{"target_id": "pants-1", "garment_type": "Pants", "snapshot": {"version": 4}}],
            "memories": [
                {
                    "memory_id": "m-now",
                    "content": "이번 발표에는 슬림핏을 원함",
                    "key": "fit",
                    "value": "Slim",
                    "origin": "explicit",
                    "confirmed": True,
                    "version": 2,
                    "snapshot_version": 7,
                    "user_id": "user-secret",
                }
            ],
            "bindings": [
                {
                    "target_id": "pants-1",
                    "feature_id": "fit",
                    "values": ["Slim"],
                    "operator": "preferred_any_of",
                }
            ],
            "facts": [{"fact_id": "f1", "type": "occasion", "value": "presentation", "user_id": "user-secret"}],
            "facts_by_target": {
                "pants-1": {
                    "occasion": "presentation",
                    "goal": "단정한 바지",
                    "unsupported": "must-not-forward",
                },
                "other-target": {"goal": "다른 사용 대상"},
            },
            "fact_sources": [
                {
                    "fact": "occasion",
                    "value": "presentation",
                    "source_ids": ["m-occasion"],
                    "source_versions": [4],
                    "target_scope": "global",
                    "target_id": "pants-1",
                    "raw_provider_error": "must-not-forward",
                }
            ],
            "request": {"goal": "발표용 바지", "request_id": "r1", "profile_revision": 3},
            "registry": {
                "version": "v1",
                "features": [
                    {
                        "feature_id": "fit",
                        "values": ["Slim"],
                    },
                    {
                        "feature_id": "length",
                        "values": ["Cropped", "Maxi"],
                        "by_garment_type": {
                            "Pants": ["Cropped", "Full-length"],
                            "Skirt": ["Maxi"],
                            "unrelated-target": ["secret-value"],
                        },
                    },
                ],
            },
        }

    def adapter(self, transport):
        return OpenAIResponsesAdapter(
            model="test-model",
            api_key="dummy-api-key",
            transport=transport,
            timeout=12,
            max_output_tokens=321,
        )

    def test_posts_structured_payload_with_separate_instructions_and_input(self):
        transport = FakeTransport()
        result = self.adapter(transport).propose(self.context())

        self.assertEqual(result, proposal())
        self.assertEqual(len(transport.calls), 1)
        url, headers, payload, timeout = transport.calls[0]
        self.assertEqual(url, DEFAULT_ENDPOINT)
        self.assertEqual(headers["Authorization"], "Bearer dummy-api-key")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(timeout, 12.0)
        self.assertEqual(payload["model"], "test-model")
        self.assertFalse(payload["store"])
        self.assertEqual(payload["max_output_tokens"], 321)
        self.assertIsInstance(payload["instructions"], str)
        self.assertIsInstance(payload["input"], str)
        self.assertNotIn("슬림핏을 원함", payload["instructions"])
        self.assertIn("슬림핏을 원함", payload["input"])

        output_format = payload["text"]["format"]
        self.assertEqual(output_format["type"], "json_schema")
        self.assertEqual(output_format["name"], "target_feature_suggestions")
        self.assertTrue(output_format["strict"])
        schema = output_format["schema"]
        self.assertEqual(schema["required"], ["suggestions", "questions"])
        self.assertFalse(schema["additionalProperties"])
        suggestion_schema = schema["properties"]["suggestions"]["items"]
        self.assertFalse(suggestion_schema["additionalProperties"])
        self.assertEqual(
            suggestion_schema["required"],
            ["target_id", "feature", "values", "match", "source_ids", "reason"],
        )
        self.assertEqual(
            suggestion_schema["properties"]["values"]["items"]["anyOf"],
            [{"type": "string"}, {"type": "integer"}],
        )

    def test_context_allowlist_removes_identity_versions_and_raw_provider_data(self):
        transport = FakeTransport()
        self.adapter(transport).propose(self.context())
        sent = json.loads(transport.calls[0][2]["input"])["context"]

        self.assertNotIn("user_id", sent)
        self.assertNotIn("request_revision", sent)
        self.assertNotIn("snapshot", sent["targets"][0])
        self.assertNotIn("snapshot_version", sent["memories"][0])
        self.assertNotIn("user_id", sent["memories"][0])
        self.assertEqual(sent["memories"][0]["origin"], "explicit")
        self.assertTrue(sent["memories"][0]["confirmed"])
        self.assertEqual(sent["memories"][0]["version"], 2)
        self.assertNotIn("request_id", sent["request"])
        self.assertNotIn("profile_revision", sent["request"])
        self.assertNotIn("user_id", sent["facts"][0])
        self.assertEqual(
            sent["facts_by_target"],
            {"pants-1": {"occasion": "presentation", "goal": "단정한 바지"}},
        )
        evidence = sent["fact_sources"][0]
        self.assertEqual(evidence["source_ids"], ["m-occasion"])
        self.assertEqual(evidence["source_versions"], [4])
        self.assertEqual(evidence["target_scope"], "global")
        self.assertNotIn("raw_provider_error", evidence)
        length = next(item for item in sent["registry"]["features"] if item.get("feature_id") == "length")
        self.assertEqual(length["by_garment_type"], {"Pants": ["Cropped", "Full-length"]})
        self.assertEqual(sent["bindings"][0]["feature_id"], "fit")

    def test_top_level_output_text_convenience_is_parsed(self):
        transport = FakeTransport(response={"status": "completed", "output_text": json.dumps(proposal())})
        self.assertEqual(self.adapter(transport).propose({}), proposal())

    def test_direct_refusal_is_not_partial_success(self):
        transport = FakeTransport(response={"status": "completed", "refusal": "unsafe"})
        with self.assertRaisesRegex(StyleMateError, "provider declined") as raised:
            self.adapter(transport).propose({})
        self.assertEqual(raised.exception.code, "provider_refusal")
        self.assertNotIn("unsafe", str(raised.exception))

    def test_nested_refusal_is_not_partial_success(self):
        response = {
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "secret"}]}],
        }
        with self.assertRaisesRegex(StyleMateError, "provider declined") as raised:
            self.adapter(FakeTransport(response=response)).propose({})
        self.assertEqual(raised.exception.code, "provider_refusal")

    def test_incomplete_response_is_not_partial_success(self):
        response = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}
        with self.assertRaises(StyleMateError) as raised:
            self.adapter(FakeTransport(response=response)).propose({})
        self.assertEqual(raised.exception.code, "provider_incomplete")

    def test_output_shape_rejects_unknown_fields_and_origin_metadata(self):
        invalid = proposal()
        invalid["suggestions"][0]["origin"] = "inferred"
        with self.assertRaises(StyleMateError) as raised:
            self.adapter(FakeTransport(response=response_with_output(invalid))).propose({})
        self.assertEqual(raised.exception.code, "invalid_output")

    def test_output_shape_rejects_unknown_feature_and_bool_values(self):
        invalid = proposal()
        invalid["suggestions"][0]["feature"] = "not-in-registry"
        with self.assertRaises(StyleMateError):
            self.adapter(FakeTransport(response=response_with_output(invalid))).propose({})

    def test_known_target_rejects_registry_invalid_values_and_target_length_values(self):
        invalid = proposal()
        invalid["suggestions"][0]["values"] = ["Maxi"]
        with self.assertRaises(StyleMateError) as raised:
            self.adapter(FakeTransport(response=response_with_output(invalid))).propose(self.context())
        self.assertEqual(raised.exception.code, "invalid_output")

        invalid = proposal()
        invalid["suggestions"][0].update({"feature": "length", "values": ["Maxi"]})
        with self.assertRaises(StyleMateError) as raised:
            self.adapter(FakeTransport(response=response_with_output(invalid))).propose(self.context())
        self.assertEqual(raised.exception.code, "invalid_output")

        invalid = proposal()
        invalid["suggestions"][0]["values"] = [True]
        with self.assertRaises(StyleMateError):
            self.adapter(FakeTransport(response=response_with_output(invalid))).propose({})

    def test_invalid_json_empty_and_error_response_are_safe(self):
        cases = [
            ({"status": "completed", "output_text": "not-json"}, "invalid_output"),
            ({"status": "completed", "output": []}, "empty_response"),
            ({"status": "failed", "error": {"message": "provider-secret"}}, "provider_error"),
        ]
        for response, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(StyleMateError) as raised:
                    self.adapter(FakeTransport(response=response)).propose({})
                self.assertEqual(raised.exception.code, code)
                self.assertNotIn("provider-secret", str(raised.exception))

    def test_non_completed_statuses_are_not_accepted_as_results(self):
        for status in ("queued", "in_progress", "provider-status-unknown"):
            with self.subTest(status=status):
                response = {"status": status, "output_text": json.dumps(proposal())}
                with self.assertRaises(StyleMateError) as raised:
                    self.adapter(FakeTransport(response=response)).propose(self.context())
                self.assertEqual(raised.exception.code, "provider_incomplete")

        with self.assertRaises(StyleMateError) as raised:
            self.adapter(FakeTransport(response={"output_text": json.dumps(proposal())})).propose(self.context())
        self.assertEqual(raised.exception.code, "provider_invalid_response")

    def test_transport_stylemate_errors_are_replaced_with_safe_messages(self):
        known = StyleMateError("provider_http_error", "dummy-key/body")
        with self.assertRaises(StyleMateError) as raised:
            self.adapter(FakeTransport(error=known)).propose(self.context())
        self.assertEqual(raised.exception.code, "provider_http_error")
        self.assertNotIn("dummy-key/body", str(raised.exception))
        self.assertEqual(str(raised.exception), "The feature proposal provider returned an error.")

        unknown = StyleMateError("internal_provider_secret", "dummy-key/body")
        with self.assertRaises(StyleMateError) as raised:
            self.adapter(FakeTransport(error=unknown)).propose(self.context())
        self.assertEqual(raised.exception.code, "provider_unavailable")
        self.assertNotIn("internal_provider_secret", str(raised.exception))
        self.assertNotIn("dummy-key/body", str(raised.exception))

    def test_http_rate_limit_and_server_errors_hide_provider_body(self):
        for status, code in ((400, "provider_http_error"), (429, "provider_rate_limited"), (500, "provider_http_error")):
            with self.subTest(status=status):
                with self.assertRaises(StyleMateError) as raised:
                    self.adapter(FakeTransport(error=_ProviderHTTPError(status))).propose({})
                self.assertEqual(raised.exception.code, code)
                self.assertNotIn(str(status), str(raised.exception))

    def test_timeout_and_unknown_transport_errors_are_safe(self):
        with self.assertRaises(StyleMateError) as raised:
            self.adapter(FakeTransport(error=TimeoutError("provider-secret"))).propose({})
        self.assertEqual(raised.exception.code, "provider_timeout")
        self.assertNotIn("provider-secret", str(raised.exception))

        with self.assertRaises(StyleMateError) as raised:
            self.adapter(FakeTransport(error=RuntimeError("provider-secret"))).propose({})
        self.assertEqual(raised.exception.code, "provider_unavailable")
        self.assertNotIn("provider-secret", str(raised.exception))

    def test_connection_error_is_distinguished_from_timeout(self):
        import urllib.error

        with self.assertRaises(StyleMateError) as raised:
            self.adapter(FakeTransport(error=urllib.error.URLError("offline"))).propose({})
        self.assertEqual(raised.exception.code, "provider_unavailable")
        self.assertNotIn("offline", str(raised.exception))

    def test_constructor_requires_explicit_nonblank_model_and_api_key(self):
        for kwargs, code in (
            ({"model": "", "api_key": "dummy"}, "invalid_model"),
            ({"model": "model", "api_key": "   "}, "invalid_api_key"),
        ):
            with self.subTest(code=code):
                with self.assertRaises(StyleMateError) as raised:
                    OpenAIResponsesAdapter(**kwargs)
                self.assertEqual(raised.exception.code, code)

        old = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = "environment-secret"
        try:
            with self.assertRaises(StyleMateError) as raised:
                OpenAIResponsesAdapter(model="model", api_key="")
            self.assertEqual(raised.exception.code, "invalid_api_key")
            self.assertNotIn("environment-secret", str(raised.exception))
        finally:
            if old is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = old

    def test_incomplete_registry_is_not_replaced_by_a_smaller_fallback(self):
        import unittest.mock

        with unittest.mock.patch("stylemate_memory.llm.FEATURES", {}):
            with self.assertRaises(StyleMateError) as raised:
                self.adapter(FakeTransport()).propose({})
        self.assertEqual(raised.exception.code, "registry_unavailable")

    def test_default_transport_is_lazy_and_uses_post(self):
        import unittest.mock

        class FakeHTTPResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, size=-1):
                return json.dumps(response_with_output(proposal())).encode("utf-8")[:size]

        with unittest.mock.patch("stylemate_memory.llm.urllib.request.urlopen", return_value=FakeHTTPResponse()) as urlopen:
            adapter = OpenAIResponsesAdapter(model="model", api_key="dummy")
            # Construction did not initiate a request.
            urlopen.assert_not_called()
            self.assertEqual(adapter.propose({}), proposal())
            request, = urlopen.call_args.args
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.full_url, DEFAULT_ENDPOINT)
            self.assertEqual(request.headers["Authorization"], "Bearer dummy")


class OpenAIResponsesGatewayTests(unittest.TestCase):
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
              "required": ["ok"], "additionalProperties": False}

    def gateway(self, transport):
        return OpenAIResponsesGateway(api_key="dummy-api-key", transport=transport)

    def test_complete_is_a_domain_independent_strict_responses_request(self):
        transport = FakeTransport(response=response_with_output({"ok": True}))
        gateway = OpenAIResponsesGateway(api_key="dummy-api-key", transport=transport,
                                         model="injected-model", timeout=9, max_output_tokens=2222)
        self.assertEqual(gateway.complete("Convert only JSON.", {"title": "합성 상품"}, self.schema), {"ok": True})
        url, headers, payload, timeout = transport.calls[0]
        self.assertEqual((url, timeout), (DEFAULT_ENDPOINT, 9.0))
        self.assertEqual(headers["Authorization"], "Bearer dummy-api-key")
        self.assertEqual(payload["model"], "injected-model")
        self.assertEqual(payload["max_output_tokens"], 2222)
        self.assertFalse(payload["store"])
        self.assertEqual(payload["instructions"], "Convert only JSON.")
        self.assertEqual(json.loads(payload["input"]), {"title": "합성 상품"})
        self.assertEqual(payload["text"]["format"], {
            "type": "json_schema", "name": "lumi_json", "strict": True, "schema": self.schema})
        self.assertNotIn("dummy-api-key", json.dumps(payload))
        self.assertNotIn("tools", payload)
        self.assertNotIn("previous_response_id", payload)
        self.assertNotIn("last_metadata", vars(gateway))

    def test_failures_do_not_retry_fallback_or_return_provider_text(self):
        cases = [
            (FakeTransport(error=TimeoutError("dummy-api-key raw body")), "provider_timeout"),
            (FakeTransport(error=_ProviderHTTPError(429)), "provider_rate_limited"),
            (FakeTransport(response={"http_status": 429, "error": "dummy-api-key"}), "provider_rate_limited"),
            (FakeTransport(error=RuntimeError("dummy-api-key raw body")), "provider_unavailable"),
            (FakeTransport(response={"status": "incomplete", "output_text": "{}"}), "provider_incomplete"),
            (FakeTransport(response={"status": "completed", "output_text": "bad dummy-api-key"}), "invalid_output"),
            (FakeTransport(response={"status": "completed", "output_text": []}), "provider_invalid_response"),
            (FakeTransport(response={"status": "completed", "output_text": "{}", "refusal": "dummy-api-key"}), "provider_refusal"),
            (FakeTransport(response={"status": "completed", "output_text": "{}", "output": [
                {"type": "message", "content": [{"type": "refusal", "refusal": "dummy-api-key"}]}]}), "provider_refusal"),
            (FakeTransport(response={"status": "completed", "output": [
                {"type": "function_call", "arguments": "dummy-api-key"}]}), "provider_invalid_response"),
            (FakeTransport(response={"status": "completed", "output": [
                {"type": [], "content": []}]}), "provider_invalid_response"),
            (FakeTransport(response={"status": "completed", "output": [
                {"type": "message", "content": [{"type": [], "text": "{}"}]}]}), "provider_invalid_response"),
        ]
        for transport, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(StyleMateError) as caught:
                    self.gateway(transport).complete("JSON only", {}, self.schema)
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn("dummy-api-key", json.dumps(caught.exception.as_dict()))
                self.assertNotIn("raw body", str(caught.exception))
                self.assertEqual(len(transport.calls), 1)

    def test_malformed_json_duplicate_keys_nonfinite_and_echoed_key_are_rejected(self):
        for output in ('{"ok":true,"ok":false}', '{"ok":NaN}', '[]',
                       '{"question":"dummy-api-key"}', '{"question":"dummy-\\u0061pi-key"}'):
            with self.subTest(output=output):
                transport = FakeTransport(response={"status": "completed", "output_text": output})
                with self.assertRaises(StyleMateError) as caught:
                    self.gateway(transport).complete("", {}, self.schema)
                self.assertEqual(caught.exception.code, "invalid_output")

    def test_default_is_offline_and_openai_requires_explicit_configuration(self):
        with patch("shutil.which", side_effect=AssertionError("CLI lookup")), \
             patch("subprocess.run", side_effect=AssertionError("CLI execution")), \
             patch("urllib.request.urlopen", side_effect=AssertionError("network")), \
             patch("os.getenv", side_effect=AssertionError("credential lookup")):
            fake = create_model_gateway()
            self.assertEqual(fake.model, "fake")
            gateway = create_model_gateway("openai", api_key="dummy-api-key", transport=FakeTransport())
            self.assertEqual(gateway.model, DEFAULT_MODEL)
            with self.assertRaises(StyleMateError) as caught:
                create_model_gateway("openai")
            self.assertEqual(caught.exception.code, "invalid_api_key")
            for configuration in ({"provider": "unknown"}, {"api_key": "dummy-api-key"}):
                with self.assertRaises(StyleMateError):
                    create_model_gateway(**configuration)

    def test_invalid_settings_and_payload_fail_before_transport(self):
        for value in (True, 0, -1, float("nan"), float("inf")):
            with self.subTest(timeout=value):
                with self.assertRaises(StyleMateError):
                    OpenAIResponsesGateway(api_key="dummy-api-key", timeout=value)
        transport = FakeTransport()
        for payload in ({"value": float("nan")}, {"text": "a" * (256 * 1024)}):
            with self.assertRaises(StyleMateError) as caught:
                self.gateway(transport).complete("", payload, self.schema)
            self.assertEqual(caught.exception.code, "invalid_input")
        self.assertEqual(transport.calls, [])

    def test_urllib_posts_strict_json_and_rejects_invalid_http_bodies(self):
        class FakeHTTPResponse:
            status = 200

            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, size=-1):
                return self.body[:size]

        valid = json.dumps(response_with_output({"ok": True})).encode("utf-8")
        for body, code in ((valid, None), (b"private-provider-body", "provider_invalid_response"),
                           (b"[1]", "provider_invalid_response"),
                           (b"x" * 1_000_001, "provider_invalid_response")):
            with self.subTest(code=code), patch("urllib.request.urlopen", return_value=FakeHTTPResponse(body)) as urlopen:
                gateway = OpenAIResponsesGateway(api_key="dummy-api-key")
                urlopen.assert_not_called()
                if code is None:
                    self.assertEqual(gateway.complete("JSON only", {"title": "합성"}, self.schema), {"ok": True})
                else:
                    with self.assertRaises(StyleMateError) as caught:
                        gateway.complete("JSON only", {}, self.schema)
                    self.assertEqual(caught.exception.code, code)
                    self.assertNotIn("private-provider-body", str(caught.exception))
                request, = urlopen.call_args.args
                self.assertEqual(request.method, "POST")
                posted = json.loads(request.data)
                self.assertFalse(posted["store"])
                self.assertTrue(posted["text"]["format"]["strict"])

    def test_urllib_rate_limit_and_timeout_do_not_expose_http_error_details(self):
        import io
        import urllib.error

        errors = [
            (urllib.error.HTTPError(DEFAULT_ENDPOINT, 429, "dummy-api-key", {}, io.BytesIO(b"private-provider-body")),
             "provider_rate_limited"),
            (urllib.error.URLError(TimeoutError("dummy-api-key")), "provider_timeout"),
        ]
        for error, code in errors:
            with self.subTest(code=code), patch("urllib.request.urlopen", side_effect=error):
                with self.assertRaises(StyleMateError) as caught:
                    OpenAIResponsesGateway(api_key="dummy-api-key").complete("", {}, self.schema)
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn("dummy-api-key", str(caught.exception))
                self.assertNotIn("private-provider-body", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
