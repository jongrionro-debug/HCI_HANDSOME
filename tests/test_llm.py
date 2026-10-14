import json
import os
import unittest

from stylemate_memory.errors import StyleMateError
from stylemate_memory.llm import (
    DEFAULT_ENDPOINT,
    OpenAIResponsesAdapter,
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

            def read(self):
                return json.dumps(response_with_output(proposal())).encode("utf-8")

        with unittest.mock.patch("stylemate_memory.llm.urllib.request.urlopen", return_value=FakeHTTPResponse()) as urlopen:
            adapter = OpenAIResponsesAdapter(model="model", api_key="dummy")
            # Construction did not initiate a request.
            urlopen.assert_not_called()
            self.assertEqual(adapter.propose({}), proposal())
            request, = urlopen.call_args.args
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.full_url, DEFAULT_ENDPOINT)
            self.assertEqual(request.headers["Authorization"], "Bearer dummy")


if __name__ == "__main__":
    unittest.main()
