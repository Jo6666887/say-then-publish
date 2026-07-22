import json
import unittest

import requests

from ai_layout import (
    AILayoutConfig,
    AILayoutDisabledError,
    AILayoutProviderError,
    AILayoutResponseError,
    AILayoutService,
    AILayoutValidationError,
    parse_ai_layout_response,
    validate_optimized_content,
)


class FakeResponse:
    def __init__(self, payload=None, *, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class RecordingSession:
    def __init__(self, response=None, *, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


def enabled_config():
    return AILayoutConfig(
        api_base="https://provider.example/v2",
        api_key="server-only-test-key",
        model_id="test-model",
        app_id="test-app",
        resource_id="0",
        timeout_seconds=12,
        max_tokens=2048,
    )


def completion(content):
    return FakeResponse(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": content,
                    }
                }
            ]
        }
    )


class AILayoutConfigTests(unittest.TestCase):
    def test_missing_secret_config_is_explicitly_disabled(self):
        config = AILayoutConfig.from_env({})

        self.assertFalse(config.enabled)
        self.assertEqual(
            config.missing_environment_variables,
            ("WTP_AI_API_KEY", "WTP_AI_APP_ID"),
        )
        self.assertIn("WTP_AI_API_KEY", config.disabled_reason)
        self.assertNotIn("CLOTHAGENT", config.disabled_reason)

    def test_only_wtp_environment_names_are_used(self):
        config = AILayoutConfig.from_env(
            {
                "CLOTHAGENT_API_KEY": "legacy-must-not-be-used",
                "CLOTHAGENT_APP_ID": "legacy-app",
                "WTP_AI_API_KEY": "wtp-key",
                "WTP_AI_APP_ID": "wtp-app",
                "WTP_AI_MODEL_ID": "wtp-model",
            }
        )

        self.assertTrue(config.enabled)
        self.assertEqual(config.api_key, "wtp-key")
        self.assertEqual(config.app_id, "wtp-app")
        self.assertEqual(config.model_id, "wtp-model")


class AILayoutParsingTests(unittest.TestCase):
    def test_strips_think_and_json_fence_before_strict_parse(self):
        raw = (
            "<think>private reasoning</think>\n"
            "```json\n"
            + json.dumps(
                {"optimized_content": "## 标题", "changes": ["增加标题"]},
                ensure_ascii=False,
            )
            + "\n```"
        )

        parsed = parse_ai_layout_response(raw)

        self.assertEqual(parsed["optimized_content"], "## 标题")
        self.assertEqual(parsed["changes"], ["增加标题"])

    def test_rejects_explanation_outside_json(self):
        with self.assertRaises(AILayoutResponseError) as caught:
            parse_ai_layout_response(
                '这是结果：{"optimized_content":"正文","changes":[]}'
            )

        self.assertEqual(caught.exception.code, "AI_INVALID_JSON")

    def test_rejects_invalid_schema(self):
        with self.assertRaises(AILayoutResponseError):
            parse_ai_layout_response('{"optimized_content": 123, "changes": []}')


class AILayoutGuardrailTests(unittest.TestCase):
    def test_layout_accepts_supported_formatting_without_copy_change(self):
        original = "标题\n\n正文重点\n[[image:img_1]]\n第二段"
        optimized = (
            "# 标题\n\n{{bg:#E8E9FF|正文重点}}\n"
            "[[image:img_1]]\n- 第二段"
        )

        validate_optimized_content(original, optimized, mode="layout")

    def test_layout_rejects_visible_copy_change(self):
        with self.assertRaises(AILayoutValidationError) as caught:
            validate_optimized_content("原文", "**改过的原文**", mode="layout")

        self.assertEqual(caught.exception.code, "VISIBLE_COPY_CHANGED")

    def test_rejects_missing_reordered_or_duplicated_image_markers(self):
        original = "A\n[[image:img_1]]\nB\n[[image:img_2]]"
        candidates = (
            "A\n[[image:img_1]]\nB",
            "A\n[[image:img_2]]\nB\n[[image:img_1]]",
            "A\n[[image:img_1]]\n[[image:img_1]]\nB\n[[image:img_2]]",
        )
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                with self.assertRaises(AILayoutValidationError) as caught:
                    validate_optimized_content(original, candidate, mode="polish")
                self.assertEqual(caught.exception.code, "IMAGE_MARKERS_CHANGED")

    def test_polish_preserves_numbers_urls_and_markers(self):
        original = (
            "Lite 39 元，2500 Credits / 7 天。"
            "详情 https://example.com/plan\n[[image:img_1]]"
        )
        optimized = (
            "Lite 仅需 39 元，可获得 2500 Credits / 7 天。"
            "查看详情：https://example.com/plan\n[[image:img_1]]"
        )

        validate_optimized_content(original, optimized, mode="polish")

    def test_polish_rejects_changed_number_or_url(self):
        original = "39 元，见 https://example.com/a\n[[image:img_1]]"
        for candidate, code in (
            ("49 元，见 https://example.com/a\n[[image:img_1]]", "NUMBERS_CHANGED"),
            ("39 元，见 https://example.com/b\n[[image:img_1]]", "URLS_CHANGED"),
        ):
            with self.subTest(candidate=candidate):
                with self.assertRaises(AILayoutValidationError) as caught:
                    validate_optimized_content(original, candidate, mode="polish")
                self.assertEqual(caught.exception.code, code)


class AILayoutClientTests(unittest.TestCase):
    def test_disabled_service_never_calls_provider(self):
        session = RecordingSession()
        service = AILayoutService.from_env({}, session=session)

        with self.assertRaises(AILayoutDisabledError):
            service.optimize("正文")

        self.assertEqual(session.calls, [])

    def test_malformed_mode_and_accent_color_are_structured_validation_errors(self):
        session = RecordingSession()
        service = AILayoutService(enabled_config(), session=session)

        for kwargs, expected_code in (
            ({"mode": []}, "INVALID_MODE"),
            ({"accent_color": {}}, "INVALID_ACCENT_COLOR"),
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(AILayoutValidationError) as caught:
                    service.optimize("正文", **kwargs)
                self.assertEqual(caught.exception.code, expected_code)

        self.assertEqual(session.calls, [])

    def test_non_stream_request_uses_server_headers_and_returns_validated_result(self):
        model_json = json.dumps(
            {
                "optimized_content": "# 标题\n正文\n[[image:img_1]]",
                "changes": ["增加标题层级"],
            },
            ensure_ascii=False,
        )
        session = RecordingSession(completion(model_json))
        service = AILayoutService(enabled_config(), session=session)

        result = service.optimize("标题\n正文\n[[image:img_1]]", mode="layout")

        self.assertEqual(result.model, "test-model")
        self.assertEqual(result.changes, ("增加标题层级",))
        self.assertEqual(len(session.calls), 1)
        url, kwargs = session.calls[0]
        self.assertEqual(url, "https://provider.example/v2/chat/completions")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer server-only-test-key")
        self.assertEqual(kwargs["headers"]["X-Appid"], "test-app")
        self.assertEqual(kwargs["headers"]["lora_id"], "0")
        self.assertFalse(kwargs["json"]["stream"])
        self.assertTrue(kwargs["json"]["search_disable"])
        self.assertEqual(kwargs["timeout"], 12)

    def test_network_error_does_not_expose_provider_or_secret_details(self):
        private_detail = "Bearer secret-value sid:private-provider-id"
        session = RecordingSession(error=requests.ConnectionError(private_detail))
        service = AILayoutService(enabled_config(), session=session)

        with self.assertRaises(AILayoutProviderError) as caught:
            service.optimize("正文")

        public_message = str(caught.exception)
        self.assertNotIn("secret-value", public_message)
        self.assertNotIn("sid", public_message.lower())
        self.assertEqual(caught.exception.code, "AI_PROVIDER_UNAVAILABLE")

    def test_http_error_does_not_echo_response_body(self):
        session = RecordingSession(
            FakeResponse({"error": {"message": "provider secret detail"}}, status_code=401)
        )
        service = AILayoutService(enabled_config(), session=session)

        with self.assertRaises(AILayoutProviderError) as caught:
            service.optimize("正文")

        self.assertEqual(caught.exception.code, "AI_PROVIDER_AUTH_FAILED")
        self.assertNotIn("provider secret detail", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
