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
    apply_ai_layout_highlights,
    apply_ai_polish_edits,
    parse_ai_layout_response,
    parse_ai_layout_selection_response,
    parse_ai_polish_selection_response,
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


class FakeStreamResponse(FakeResponse):
    def __init__(self, lines, *, status_code=200, error=None):
        super().__init__(status_code=status_code)
        self.lines = lines
        self.error = error
        self.closed = False

    def iter_lines(self, *, decode_unicode=False):
        yield from self.lines
        if self.error:
            raise self.error

    def close(self):
        self.closed = True


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

    def test_layout_selection_keeps_only_supported_items(self):
        parsed = parse_ai_layout_selection_response(
            json.dumps(
                {
                    "highlights": [
                        {"text": "逐字存在的重点", "style": "color"},
                        {"text": "另一个重点", "style": "rainbow"},
                        "invalid",
                    ],
                    "changes": ["选择重点"],
                },
                ensure_ascii=False,
            )
        )

        self.assertEqual(
            parsed["highlights"],
            [{"text": "逐字存在的重点", "style": "color"}],
        )

    def test_polish_selection_keeps_edits_and_supported_highlights(self):
        parsed = parse_ai_polish_selection_response(
            json.dumps(
                {
                    "edits": [
                        {"source": "原来不顺的句子", "replacement": "读起来更顺的句子"},
                        {"source": 123, "replacement": "无效"},
                    ],
                    "highlights": [
                        {"text": "读起来更顺的句子", "style": "bold"},
                        {"text": "无效重点", "style": "rainbow"},
                    ],
                    "changes": ["改善表达"],
                },
                ensure_ascii=False,
            )
        )

        self.assertEqual(
            parsed["edits"],
            [{"source": "原来不顺的句子", "replacement": "读起来更顺的句子"}],
        )
        self.assertEqual(
            parsed["highlights"],
            [{"text": "读起来更顺的句子", "style": "bold"}],
        )


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

    def test_layout_applies_only_unique_exact_unformatted_targets(self):
        original = (
            "标题\n唯一重点值得强调。\n重复短语，重复短语。\n"
            "{{color:#5B5FEF|已经高亮}}\n[[image:img_1]]"
        )
        optimized, changes = apply_ai_layout_highlights(
            original,
            [
                {"text": "唯一重点", "style": "color"},
                {"text": "重复短语", "style": "bold"},
                {"text": "已经高亮", "style": "bg"},
                {"text": "img_1", "style": "bold"},
                {"text": "# 标题", "style": "color"},
            ],
            accent_color="#5B5FEF",
        )

        self.assertIn("{{color:#5B5FEF|唯一重点}}", optimized)
        self.assertEqual(optimized.count("重复短语"), 2)
        self.assertEqual(optimized.count("{{color:#5B5FEF|已经高亮}}"), 1)
        self.assertIn("[[image:img_1]]", optimized)
        self.assertEqual(changes, ("从原文中安全标出 1 处重点",))
        validate_optimized_content(original, optimized, mode="layout")

    def test_layout_protects_links_images_code_and_table_structure(self):
        original = (
            "安全重点值得强调。\n"
            "链接 https://example.com/plan\n"
            "![[终稿素材.png]]\n"
            "![终稿](assets/final.png)\n"
            "[文档](docs/guide.md)\n"
            "[guide]: docs/guide-final.md \"文档标题\"\n"
            "```python\ndanger_call()\n```\n"
            "| 项目 | 说明 |\n| --- | --- |\n| A | 表格重点 |"
        )
        optimized, changes = apply_ai_layout_highlights(
            original,
            [
                {"text": "安全重点", "style": "color"},
                {"text": "example.com", "style": "color"},
                {"text": "终稿素材.png", "style": "bg"},
                {"text": "assets/final.png", "style": "color"},
                {"text": "docs/guide.md", "style": "bold"},
                {"text": "docs/guide-final.md", "style": "bold"},
                {"text": "文档标题", "style": "color"},
                {"text": "danger_call()", "style": "bold"},
                {"text": "表格重点", "style": "bg"},
                {"text": "A | 表格重点", "style": "bold"},
            ],
            accent_color="#5B5FEF",
        )

        self.assertIn("{{color:#5B5FEF|安全重点}}", optimized)
        self.assertIn("https://example.com/plan", optimized)
        self.assertIn("![[终稿素材.png]]", optimized)
        self.assertIn("![终稿](assets/final.png)", optimized)
        self.assertIn("[文档](docs/guide.md)", optimized)
        self.assertIn('[guide]: docs/guide-final.md "文档标题"', optimized)
        self.assertIn("```python\ndanger_call()\n```", optimized)
        self.assertIn("| A | 表格重点 |", optimized)
        self.assertEqual(changes, ("从原文中安全标出 1 处重点",))
        validate_optimized_content(original, optimized, mode="layout")

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

    def test_polish_number_guard_ignores_supported_style_color_values(self):
        original = "Lite 39 元，重点信息保持清楚。"
        optimized = "Lite 39 元，{{color:#5B5FEF|重点信息}}保持清楚。"

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

    def test_polish_rejects_changed_chinese_quantities(self):
        for original, candidate in (
            ("个人版目前有三档。", "个人版目前有四档。"),
            ("用量包有效期一个月。", "用量包有效期一个周。"),
            ("用量包有效期 1 个月。", "用量包有效期 1 周。"),
            ("Lite 价格 39 元。", "Lite 价格 39 美元。"),
        ):
            with self.subTest(original=original):
                with self.assertRaises(AILayoutValidationError) as caught:
                    validate_optimized_content(original, candidate, mode="polish")
                self.assertEqual(caught.exception.code, "NUMBERS_CHANGED")

    def test_polish_allows_non_numeric_wording_that_contains_yi(self):
        validate_optimized_content(
            "我以前一直在使用这个入口。",
            "我以前长期使用这个入口。",
            mode="polish",
        )

    def test_polish_rejects_runaway_expansion_or_content_loss(self):
        original = "这是需要安全润色的正文。" * 120
        candidates = (
            (original * 2, "POLISH_EXPANDED_TOO_MUCH"),
            ("只剩少量文字。", "POLISH_REMOVED_TOO_MUCH"),
        )
        for candidate, code in candidates:
            with self.subTest(code=code):
                with self.assertRaises(AILayoutValidationError) as caught:
                    validate_optimized_content(original, candidate, mode="polish")
                self.assertEqual(caught.exception.code, code)

    def test_polish_applies_only_unique_plain_edits_that_preserve_numbers(self):
        original = (
            "这句话写得不太顺畅，39 元方案保持不变。\n"
            "重复句子。重复句子。\n"
            "[[image:img_1]]"
        )
        optimized, count = apply_ai_polish_edits(
            original,
            [
                {
                    "source": "这句话写得不太顺畅，39 元方案保持不变。",
                    "replacement": "这句话读起来不够顺畅，39 元方案保持不变。",
                },
                {"source": "重复句子。", "replacement": "重复内容。"},
                {
                    "source": "这句话写得不太顺畅",
                    "replacement": "{{color:#fff|危险样式}}",
                },
                {
                    "source": "39 元方案保持不变",
                    "replacement": "49 元方案保持不变",
                },
                {
                    "source": "这句话写得不太顺畅",
                    "replacement": "这四句话写得不太顺畅",
                },
                {"source": "image:img_1", "replacement": "删除图片"},
            ],
        )

        self.assertEqual(count, 1)
        self.assertIn("这句话读起来不够顺畅，39 元方案保持不变。", optimized)
        self.assertIn("[[image:img_1]]", optimized)
        validate_optimized_content(original, optimized, mode="polish")


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
                "highlights": [{"text": "正文重点", "style": "color"}],
                "changes": ["选择正文重点"],
            },
            ensure_ascii=False,
        )
        session = RecordingSession(completion(model_json))
        service = AILayoutService(enabled_config(), session=session)

        result = service.optimize("标题\n正文重点\n[[image:img_1]]", mode="layout")

        self.assertEqual(result.model, "test-model")
        self.assertEqual(result.changes, ("从原文中安全标出 1 处重点",))
        self.assertEqual(
            result.optimized_content,
            "标题\n{{color:#5B5FEF|正文重点}}\n[[image:img_1]]",
        )
        self.assertEqual(len(session.calls), 1)
        url, kwargs = session.calls[0]
        self.assertEqual(url, "https://provider.example/v2/chat/completions")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer server-only-test-key")
        self.assertEqual(kwargs["headers"]["X-Appid"], "test-app")
        self.assertEqual(kwargs["headers"]["lora_id"], "0")
        self.assertFalse(kwargs["json"]["stream"])
        self.assertTrue(kwargs["json"]["search_disable"])
        self.assertEqual(kwargs["json"]["temperature"], 0)
        self.assertEqual(kwargs["json"]["max_tokens"], 2048)
        self.assertEqual(kwargs["timeout"], 12)
        self.assertFalse(kwargs["stream"])

    def test_polish_streams_utf8_safe_edits_with_a_bounded_token_budget(self):
        original = "这句话不够顺畅，39 元方案见 https://example.com/plan\n[[image:img_1]]"
        model_json = json.dumps(
            {
                "edits": [
                    {
                        "source": "这句话不够顺畅",
                        "replacement": "这句话读起来不够顺畅",
                    }
                ],
                "highlights": [
                    {"text": "这句话读起来不够顺畅", "style": "bold"}
                ],
                "changes": ["改善句子节奏"],
            },
            ensure_ascii=False,
        )
        midpoint = len(model_json) // 2
        stream_lines = [
            "data: "
            + json.dumps(
                {"choices": [{"delta": {"reasoning_content": "内部思考"}}]},
                ensure_ascii=False,
            ),
            "data: "
            + json.dumps(
                {"choices": [{"delta": {"content": model_json[:midpoint]}}]},
                ensure_ascii=False,
            ),
            "data: "
            + json.dumps(
                {"choices": [{"delta": {"content": model_json[midpoint:]}}]},
                ensure_ascii=False,
            ),
            "data: [DONE]",
        ]
        response = FakeStreamResponse([line.encode("utf-8") for line in stream_lines])
        session = RecordingSession(response)
        service = AILayoutService(enabled_config(), session=session)

        result = service.optimize(original, mode="polish")

        self.assertEqual(
            result.optimized_content,
            "**这句话读起来不够顺畅**，39 元方案见 https://example.com/plan\n[[image:img_1]]",
        )
        self.assertEqual(result.changes[0], "安全润色 1 处表达")
        self.assertEqual(result.changes[1], "从原文中安全标出 1 处重点")
        self.assertTrue(response.closed)
        _, kwargs = session.calls[0]
        self.assertTrue(kwargs["stream"])
        self.assertTrue(kwargs["json"]["stream"])
        self.assertEqual(kwargs["json"]["stream_options"], {"include_usage": True})
        self.assertEqual(kwargs["headers"]["Accept"], "text/event-stream")
        self.assertEqual(kwargs["timeout"], 180)
        self.assertLessEqual(kwargs["json"]["max_tokens"], 6144)
        self.assertIn("不要返回完整正文", kwargs["json"]["messages"][0]["content"])

    def test_polish_timeout_has_a_specific_safe_error(self):
        session = RecordingSession(error=requests.ReadTimeout("private timeout detail"))
        service = AILayoutService(enabled_config(), session=session)

        with self.assertRaises(AILayoutProviderError) as caught:
            service.optimize("用于超时测试的合成正文", mode="polish")

        self.assertEqual(caught.exception.code, "AI_PROVIDER_TIMEOUT")
        self.assertIn("润色生成超时", str(caught.exception))
        self.assertNotIn("private timeout detail", str(caught.exception))

    def test_polish_stream_timeout_closes_response_and_keeps_the_same_error_code(self):
        response = FakeStreamResponse(
            [
                "data: "
                + json.dumps(
                    {"choices": [{"delta": {"content": '{"optimized_content":'}}]},
                    ensure_ascii=False,
                )
            ],
            error=requests.ReadTimeout("private stream timeout detail"),
        )
        service = AILayoutService(enabled_config(), session=RecordingSession(response))

        with self.assertRaises(AILayoutProviderError) as caught:
            service.optimize("用于流式超时测试的合成正文", mode="polish")

        self.assertEqual(caught.exception.code, "AI_PROVIDER_TIMEOUT")
        self.assertTrue(response.closed)

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
