"""Server-side AI layout/polish client with content-loss guardrails.

The browser must never call the model provider directly. This module reads only
``WTP_AI_*`` environment variables, uses a short response for layout and a
streamed response for polish, then validates the result before the UI can show
or apply it.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

import requests


DEFAULT_API_BASE = "https://maas-api.cn-huabei-1.xf-yun.com/v2"
DEFAULT_MODEL_ID = "xopkimik25"
DEFAULT_TIMEOUT_SECONDS = 90.0
DEFAULT_POLISH_TIMEOUT_SECONDS = 180.0
DEFAULT_MAX_TOKENS = 8192
MAX_POLISH_TOKENS = 6144
MAX_STREAMED_RESPONSE_CHARS = 4 * 1024 * 1024
VALID_MODES = {"layout", "polish"}
VALID_LAYOUT_STYLES = {"color", "bg", "bold"}
LOGGER = logging.getLogger("write-then-publish.ai-layout")

_IMAGE_MARKER_RE = re.compile(r"\[\[image:([\w-]+)\]\]")
_THINK_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)
_FENCE_RE = re.compile(r"^```(?:json)?\s*([\s\S]*?)\s*```$", re.IGNORECASE)
_STYLE_MACRO_RE = re.compile(
    r"\{\{(?:color|bg):(#[0-9a-fA-F]{3,8})\|([\s\S]*?)\}\}"
)
_URL_RE = re.compile(r"https?://[^\s<>\"'\[\]{}（）。，、；：！？]+", re.IGNORECASE)
_MEASUREMENT_UNIT_PATTERN = (
    r"(?:个(?:分钟|小时|工作日|天|日|周|月|年|人|位|名|档|层|级|项|种|"
    r"张|套|轮|件|条|款|次|处|字|页|屏|段|篇|章)?"
    r"|(?:人民币|美元|美金|元|块|角|分)(?:\s*/\s*(?:分钟|小时|天|日|周|月|年|次))?"
    r"|Credits?|积分|Tokens?|分钟|小时|工作日|天|日|周|月|年|人|位|名|"
    r"档|层|级|项|种|张|套|轮|件|条|款|次|折|成|倍|处|字|行|句|页|屏|段|篇|章)"
)
_NUMBER_RE = re.compile(
    rf"\d+(?:[.,]\d+)*(?:%|[A-Za-z]+)?(?:\s*{_MEASUREMENT_UNIT_PATTERN})?",
    re.IGNORECASE,
)
_CHINESE_QUANTITY_RE = re.compile(
    rf"(?:第[零〇一二两三四五六七八九十百千万亿兆]+"
    rf"(?:\s*{_MEASUREMENT_UNIT_PATTERN})?"
    rf"|[零〇一二两三四五六七八九]*[十百千万亿兆][零〇一二两三四五六七八九]*"
    rf"(?:点[零〇一二两三四五六七八九]+)?(?:\s*{_MEASUREMENT_UNIT_PATTERN})?"
    rf"|[零〇一二两三四五六七八九]+(?:点[零〇一二两三四五六七八九]+)?"
    rf"\s*{_MEASUREMENT_UNIT_PATTERN})",
    re.IGNORECASE,
)
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$")
_BOLD_RE = re.compile(r"\*\*[^*\n]+?\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*[^*\n]+?\*(?!\*)")
_INLINE_CODE_RE = re.compile(r"`[^`\n]+?`")
_FENCED_CODE_RE = re.compile(
    r"(?:^|\n)(?:```|~~~)[^\n]*\n[\s\S]*?\n(?:```|~~~)(?=\n|$)"
)
_OBSIDIAN_LINK_RE = re.compile(r"!?\[\[[^\]\n]+\]\]")
_MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]\n]*\]\([^\)\n]+\)")
_MARKDOWN_REFERENCE_RE = re.compile(r"!?\[[^\]\n]+\]\[[^\]\n]+\]")
_MARKDOWN_REFERENCE_DEFINITION_RE = re.compile(
    r"^[ \t]{0,3}\[[^\]\n]+\]:[^\n]+$", re.MULTILINE
)
_HTML_TAG_RE = re.compile(r"<[^>\n]+>")


class AILayoutError(RuntimeError):
    """Base error whose message is safe to show in the browser."""

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


class AILayoutDisabledError(AILayoutError):
    pass


class AILayoutProviderError(AILayoutError):
    pass


class AILayoutResponseError(AILayoutError):
    pass


class AILayoutValidationError(AILayoutError):
    pass


@dataclass(frozen=True)
class AILayoutConfig:
    api_base: str
    api_key: str
    model_id: str
    app_id: str
    resource_id: str = "0"
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_tokens: int = DEFAULT_MAX_TOKENS
    polish_timeout_seconds: float = DEFAULT_POLISH_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None) -> "AILayoutConfig":
        values = os.environ if environ is None else environ
        return cls(
            api_base=(values.get("WTP_AI_API_BASE") or DEFAULT_API_BASE).strip().rstrip("/"),
            api_key=(values.get("WTP_AI_API_KEY") or "").strip(),
            model_id=(values.get("WTP_AI_MODEL_ID") or DEFAULT_MODEL_ID).strip(),
            app_id=(values.get("WTP_AI_APP_ID") or "").strip(),
            resource_id=(values.get("WTP_AI_RESOURCE_ID") or "0").strip(),
            timeout_seconds=_read_positive_float(
                values.get("WTP_AI_TIMEOUT_SECONDS"),
                default=DEFAULT_TIMEOUT_SECONDS,
            ),
            max_tokens=_read_positive_int(
                values.get("WTP_AI_MAX_TOKENS"),
                default=DEFAULT_MAX_TOKENS,
            ),
            polish_timeout_seconds=_read_positive_float(
                values.get("WTP_AI_POLISH_TIMEOUT_SECONDS"),
                default=DEFAULT_POLISH_TIMEOUT_SECONDS,
            ),
        )

    @property
    def missing_environment_variables(self) -> tuple[str, ...]:
        missing = []
        if not self.api_key:
            missing.append("WTP_AI_API_KEY")
        if not self.app_id:
            missing.append("WTP_AI_APP_ID")
        return tuple(missing)

    @property
    def enabled(self) -> bool:
        return not self.missing_environment_variables

    @property
    def disabled_reason(self) -> str:
        if self.enabled:
            return ""
        variables = "、".join(self.missing_environment_variables)
        return f"AI 排版未配置：缺少服务端环境变量 {variables}"


@dataclass(frozen=True)
class AILayoutResult:
    optimized_content: str
    changes: tuple[str, ...]
    model: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "optimizedContent": self.optimized_content,
            "changes": list(self.changes),
            "model": self.model,
        }


class AILayoutService:
    def __init__(self, config: AILayoutConfig, *, session: Optional[Any] = None):
        self.config = config
        if session is None:
            session = requests.Session()
            # The configured MaaS endpoint is a direct mainland service. System
            # proxy settings are a common source of long-stream disconnects.
            session.trust_env = False
        self._session = session

    @classmethod
    def from_env(
        cls,
        environ: Optional[Mapping[str, str]] = None,
        *,
        session: Optional[Any] = None,
    ) -> "AILayoutService":
        return cls(AILayoutConfig.from_env(environ), session=session)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.config.enabled,
            "model": self.config.model_id if self.config.enabled else None,
            "reason": self.config.disabled_reason or None,
        }

    def optimize(
        self,
        content: str,
        *,
        mode: str = "layout",
        accent_color: str = "#5B5FEF",
    ) -> AILayoutResult:
        if not self.config.enabled:
            raise AILayoutDisabledError(
                self.config.disabled_reason,
                code="AI_LAYOUT_DISABLED",
            )
        if not isinstance(mode, str) or mode not in VALID_MODES:
            raise AILayoutValidationError("不支持的 AI 优化模式", code="INVALID_MODE")
        if not isinstance(content, str) or not content.strip():
            raise AILayoutValidationError("当前正文为空，无法优化", code="EMPTY_CONTENT")
        if not isinstance(accent_color, str) or not _HEX_COLOR_RE.fullmatch(accent_color):
            raise AILayoutValidationError("主题色格式无效", code="INVALID_ACCENT_COLOR")

        messages = (
            _build_layout_selection_messages(content)
            if mode == "layout"
            else _build_polish_selection_messages(content)
        )
        stream = mode == "polish"
        payload = {
            "model": self.config.model_id,
            "messages": messages,
            "temperature": 0 if mode == "layout" else 0.25,
            "max_tokens": (
                min(self.config.max_tokens, 2048)
                if mode == "layout"
                else _polish_token_budget(content, self.config.max_tokens)
            ),
            "stream": stream,
            "search_disable": True,
        }
        if stream:
            payload["stream_options"] = {"include_usage": True}
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
            "X-Appid": self.config.app_id,
        }
        if self.config.resource_id:
            headers["lora_id"] = self.config.resource_id

        timeout_seconds = (
            max(self.config.timeout_seconds, self.config.polish_timeout_seconds)
            if mode == "polish"
            else self.config.timeout_seconds
        )
        started = time.monotonic()
        try:
            response = self._session.post(
                f"{self.config.api_base}/chat/completions",
                json=payload,
                headers=headers,
                timeout=timeout_seconds,
                stream=stream,
            )
        except requests.Timeout as error:
            LOGGER.warning(
                "AI %s request timed out after %.1fs (%s)",
                mode,
                time.monotonic() - started,
                type(error).__name__,
            )
            raise AILayoutProviderError(
                "AI 润色生成超时，原文未修改，请稍后重试"
                if mode == "polish"
                else "AI 排版生成超时，原文未修改，请稍后重试",
                code="AI_PROVIDER_TIMEOUT",
            ) from None
        except requests.RequestException:
            LOGGER.warning(
                "AI %s request transport failed after %.1fs",
                mode,
                time.monotonic() - started,
            )
            raise AILayoutProviderError(
                "AI 排版服务暂时不可用，请稍后重试",
                code="AI_PROVIDER_UNAVAILABLE",
            ) from None
        except Exception:
            LOGGER.warning(
                "AI %s request failed after %.1fs",
                mode,
                time.monotonic() - started,
            )
            raise AILayoutProviderError(
                "AI 排版服务暂时不可用，请稍后重试",
                code="AI_PROVIDER_UNAVAILABLE",
            ) from None

        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code >= 400:
            close = getattr(response, "close", None)
            if callable(close):
                close()
            raise _http_error(status_code)

        if stream:
            raw_content = _read_streamed_content(response, started=started)
        else:
            try:
                response_payload = response.json()
                choices = response_payload.get("choices")
                message = choices[0].get("message") if isinstance(choices, list) and choices else None
                raw_content = message.get("content") if isinstance(message, dict) else None
            except Exception:
                raw_content = None
        if not isinstance(raw_content, str) or not raw_content.strip():
            raise AILayoutResponseError(
                "AI 未返回有效排版结果，本次未修改内容",
                code="AI_EMPTY_RESPONSE",
            )

        if mode == "layout":
            selection = parse_ai_layout_selection_response(raw_content)
            optimized_content, changes = apply_ai_layout_highlights(
                content,
                selection["highlights"],
                accent_color=accent_color,
            )
        else:
            selection = parse_ai_polish_selection_response(raw_content)
            polished_content, edit_count = apply_ai_polish_edits(
                content,
                selection["edits"],
            )
            optimized_content, highlight_changes = apply_ai_layout_highlights(
                polished_content,
                selection["highlights"],
                accent_color=accent_color,
            )
            changes = (
                (
                    f"安全润色 {edit_count} 处表达"
                    if edit_count
                    else "没有找到可安全替换的表达，已保留原句"
                ),
                *highlight_changes,
            )
        validate_optimized_content(content, optimized_content, mode=mode)
        return AILayoutResult(
            optimized_content=optimized_content,
            changes=changes,
            model=self.config.model_id,
        )


def _polish_token_budget(content: str, configured_max: int) -> int:
    """Keep safe-edit responses useful without inviting excessive latency."""

    estimated = len(content) * 2 + 1024
    return min(configured_max, MAX_POLISH_TOKENS, max(2048, estimated))


def _read_streamed_content(response: Any, *, started: float) -> str:
    """Collect OpenAI-compatible SSE deltas while keeping the connection active."""

    parts: list[str] = []
    total_chars = 0
    try:
        # MaaS currently omits an explicit UTF-8 charset on SSE responses.
        # requests would otherwise decode Chinese as ISO-8859-1 mojibake.
        for raw_line in response.iter_lines(decode_unicode=False):
            if isinstance(raw_line, bytes):
                line = raw_line.decode("utf-8", errors="ignore").strip()
            else:
                line = str(raw_line or "").strip()
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            if not isinstance(chunk, dict):
                continue
            if chunk.get("error"):
                raise AILayoutProviderError(
                    "AI 排版服务繁忙，请稍后重试",
                    code="AI_PROVIDER_BUSY",
                )
            choices = chunk.get("choices")
            choice = choices[0] if isinstance(choices, list) and choices else None
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            message = choice.get("message")
            content = (
                delta.get("content")
                if isinstance(delta, dict)
                else message.get("content")
                if isinstance(message, dict)
                else None
            )
            if not isinstance(content, str) or not content:
                continue
            total_chars += len(content)
            if total_chars > MAX_STREAMED_RESPONSE_CHARS:
                raise AILayoutResponseError(
                    "AI 返回内容过长，本次未修改内容",
                    code="AI_RESPONSE_TOO_LARGE",
                )
            parts.append(content)
    except requests.Timeout as error:
        LOGGER.warning(
            "AI polish stream timed out after %.1fs (%s)",
            time.monotonic() - started,
            type(error).__name__,
        )
        raise AILayoutProviderError(
            "AI 润色生成超时，原文未修改，请稍后重试",
            code="AI_PROVIDER_TIMEOUT",
        ) from None
    except requests.RequestException:
        LOGGER.warning(
            "AI polish stream transport failed after %.1fs",
            time.monotonic() - started,
        )
        raise AILayoutProviderError(
            "AI 排版服务暂时不可用，请稍后重试",
            code="AI_PROVIDER_UNAVAILABLE",
        ) from None
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
    return "".join(parts).strip()


def parse_ai_layout_response(raw_content: str) -> dict[str, Any]:
    """Parse the model's strict JSON envelope after allowed wrapper cleanup."""

    payload = _parse_ai_json_object(raw_content)
    optimized_content = payload.get("optimized_content")
    changes = payload.get("changes", [])
    if not isinstance(optimized_content, str) or not optimized_content.strip():
        raise AILayoutResponseError(
            "AI 返回格式不符合要求，本次未修改内容",
            code="AI_INVALID_SCHEMA",
        )
    if not isinstance(changes, list) or not all(isinstance(item, str) for item in changes):
        raise AILayoutResponseError(
            "AI 返回格式不符合要求，本次未修改内容",
            code="AI_INVALID_SCHEMA",
        )
    return {
        "optimized_content": optimized_content.strip(),
        "changes": [item.strip() for item in changes if item.strip()][:8],
    }


def parse_ai_layout_selection_response(raw_content: str) -> dict[str, Any]:
    """Parse exact-source highlight choices used by safe layout mode."""

    payload = _parse_ai_json_object(raw_content)

    highlights = payload.get("highlights")
    changes = payload.get("changes", [])
    if not isinstance(highlights, list) or not isinstance(changes, list):
        raise AILayoutResponseError(
            "AI 返回格式不符合要求，本次未修改内容",
            code="AI_INVALID_SCHEMA",
        )
    if not all(isinstance(item, str) for item in changes):
        raise AILayoutResponseError(
            "AI 返回格式不符合要求，本次未修改内容",
            code="AI_INVALID_SCHEMA",
        )

    normalized = []
    for item in highlights[:8]:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        style = item.get("style")
        if (
            isinstance(text, str)
            and 4 <= len(text) <= 64
            and isinstance(style, str)
            and style in VALID_LAYOUT_STYLES
        ):
            normalized.append({"text": text, "style": style})
    return {
        "highlights": normalized,
        "changes": [item.strip() for item in changes if item.strip()][:8],
    }


def parse_ai_polish_selection_response(raw_content: str) -> dict[str, Any]:
    """Parse model-proposed exact-source edits; application stays deterministic."""

    payload = _parse_ai_json_object(raw_content)
    edits = payload.get("edits")
    highlights = payload.get("highlights", [])
    changes = payload.get("changes", [])
    if not isinstance(edits, list) or not isinstance(highlights, list) or not isinstance(changes, list):
        raise AILayoutResponseError(
            "AI 返回格式不符合要求，本次未修改内容",
            code="AI_INVALID_SCHEMA",
        )
    if not all(isinstance(item, str) for item in changes):
        raise AILayoutResponseError(
            "AI 返回格式不符合要求，本次未修改内容",
            code="AI_INVALID_SCHEMA",
        )

    normalized_edits = []
    for item in edits[:12]:
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        replacement = item.get("replacement")
        if isinstance(source, str) and isinstance(replacement, str):
            normalized_edits.append(
                {
                    "source": source,
                    "replacement": replacement,
                }
            )

    normalized_highlights = []
    for item in highlights[:8]:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        style = item.get("style")
        if (
            isinstance(text, str)
            and 4 <= len(text) <= 64
            and isinstance(style, str)
            and style in VALID_LAYOUT_STYLES
        ):
            normalized_highlights.append({"text": text, "style": style})

    return {
        "edits": normalized_edits,
        "highlights": normalized_highlights,
        "changes": [item.strip() for item in changes if item.strip()][:8],
    }


def _parse_ai_json_object(raw_content: str) -> dict[str, Any]:
    cleaned = _THINK_RE.sub("", raw_content or "").strip().lstrip("\ufeff")
    fence = _FENCE_RE.fullmatch(cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    if not cleaned.startswith("{") or not cleaned.endswith("}"):
        raise AILayoutResponseError(
            "AI 返回格式不符合要求，本次未修改内容",
            code="AI_INVALID_JSON",
        )
    try:
        payload = json.loads(cleaned)
    except (TypeError, json.JSONDecodeError):
        raise AILayoutResponseError(
            "AI 返回格式不符合要求，本次未修改内容",
            code="AI_INVALID_JSON",
        ) from None
    if not isinstance(payload, dict):
        raise AILayoutResponseError(
            "AI 返回格式不符合要求，本次未修改内容",
            code="AI_INVALID_SCHEMA",
        )
    return payload


def apply_ai_layout_highlights(
    content: str,
    highlights: Sequence[Mapping[str, str]],
    *,
    accent_color: str,
) -> tuple[str, tuple[str, ...]]:
    """Apply only exact, unique, unformatted source spans selected by the AI."""

    protected_spans = _protected_layout_spans(content)
    selected_spans: list[tuple[int, int, str]] = []
    for item in highlights:
        target = item.get("text", "")
        style = item.get("style", "")
        if (
            not target
            or style not in VALID_LAYOUT_STYLES
            or any(
                token in target
                for token in (
                    "\n",
                    "\r",
                    "[[",
                    "]]",
                    "{{",
                    "}}",
                    "*",
                    "`",
                    "|",
                )
            )
            or re.match(r"^\s*(?:#{1,6}|>|[-+]|\d+[.)])\s", target)
        ):
            continue
        start = content.find(target)
        if start < 0 or content.find(target, start + 1) >= 0:
            continue
        end = start + len(target)
        if any(_spans_overlap(start, end, left, right) for left, right in protected_spans):
            continue
        if style in {"color", "bg"} and _line_contains_pipe(content, start, end):
            continue
        if any(_spans_overlap(start, end, left, right) for left, right, _ in selected_spans):
            continue
        selected_spans.append((start, end, style))

    optimized = content
    for start, end, style in sorted(selected_spans, reverse=True):
        target = content[start:end]
        if style == "color":
            replacement = f"{{{{color:{accent_color}|{target}}}}}"
        elif style == "bg":
            replacement = f"{{{{bg:#E8E9FF|{target}}}}}"
        else:
            replacement = f"**{target}**"
        optimized = optimized[:start] + replacement + optimized[end:]

    count = len(selected_spans)
    if count:
        return optimized, (f"从原文中安全标出 {count} 处重点",)
    return content, ("没有找到可安全应用的新增重点，已完整保留原文",)


def apply_ai_polish_edits(
    content: str,
    edits: Sequence[Mapping[str, str]],
) -> tuple[str, int]:
    """Apply only unique, plain-text edits that preserve protected tokens."""

    protected_spans = _protected_layout_spans(content)
    selected_spans: list[tuple[int, int, str]] = []
    for item in edits:
        source = item.get("source", "")
        replacement = item.get("replacement", "")
        if (
            not source
            or not replacement
            or source == replacement
            or len(source) < 4
            or len(source) > 600
            or len(replacement) > 800
            or "\n" in source
            or "\r" in source
            or "\n" in replacement
            or "\r" in replacement
            or any(token in replacement for token in ("[[", "]]", "{{", "}}", "```", "~~~"))
            or _HTML_TAG_RE.search(replacement)
        ):
            continue
        start = content.find(source)
        if start < 0 or content.find(source, start + 1) >= 0:
            continue
        end = start + len(source)
        if any(_spans_overlap(start, end, left, right) for left, right in protected_spans):
            continue
        if any(_spans_overlap(start, end, left, right) for left, right, _ in selected_spans):
            continue
        if _number_tokens(source) != _number_tokens(replacement):
            continue
        if _URL_RE.findall(source) != _URL_RE.findall(replacement):
            continue
        maximum_length = max(len(source) + 80, int(len(source) * 1.6))
        minimum_length = max(1, min(len(source) - 80, int(len(source) * 0.5)))
        if len(replacement) > maximum_length or len(replacement) < minimum_length:
            continue
        selected_spans.append((start, end, replacement))

    optimized = content
    for start, end, replacement in sorted(selected_spans, reverse=True):
        optimized = optimized[:start] + replacement + optimized[end:]
    return optimized, len(selected_spans)


def _protected_layout_spans(content: str) -> tuple[tuple[int, int], ...]:
    spans = []
    for pattern in (
        _IMAGE_MARKER_RE,
        _STYLE_MACRO_RE,
        _BOLD_RE,
        _ITALIC_RE,
        _INLINE_CODE_RE,
        _FENCED_CODE_RE,
        _OBSIDIAN_LINK_RE,
        _MARKDOWN_LINK_RE,
        _MARKDOWN_REFERENCE_RE,
        _MARKDOWN_REFERENCE_DEFINITION_RE,
        _URL_RE,
        _HTML_TAG_RE,
    ):
        spans.extend((match.start(), match.end()) for match in pattern.finditer(content))
    return tuple(spans)


def _spans_overlap(start: int, end: int, other_start: int, other_end: int) -> bool:
    return start < other_end and end > other_start


def _line_contains_pipe(content: str, start: int, end: int) -> bool:
    line_start = content.rfind("\n", 0, start) + 1
    line_end = content.find("\n", end)
    if line_end < 0:
        line_end = len(content)
    return "|" in content[line_start:line_end]


def validate_optimized_content(original: str, optimized: str, *, mode: str) -> None:
    """Reject any model result that can lose assets or protected copy."""

    if mode not in VALID_MODES:
        raise AILayoutValidationError("不支持的 AI 优化模式", code="INVALID_MODE")
    original_markers = _image_markers(original)
    optimized_markers = _image_markers(optimized)
    if optimized_markers != original_markers:
        raise AILayoutValidationError(
            "AI 结果改变了图片位置或数量，本次未修改内容",
            code="IMAGE_MARKERS_CHANGED",
        )

    if mode == "layout":
        if _visible_copy(original) != _visible_copy(optimized):
            raise AILayoutValidationError(
                "AI 排版结果改动了正文文字，本次未修改内容",
                code="VISIBLE_COPY_CHANGED",
            )
        return

    original_without_markers = _IMAGE_MARKER_RE.sub("", original)
    optimized_without_markers = _IMAGE_MARKER_RE.sub("", optimized)
    original_urls = _URL_RE.findall(original_without_markers)
    optimized_urls = _URL_RE.findall(optimized_without_markers)
    if optimized_urls != original_urls:
        raise AILayoutValidationError(
            "AI 润色结果改变了链接，本次未修改内容",
            code="URLS_CHANGED",
        )

    original_without_urls = _strip_supported_style_macros(
        _URL_RE.sub("", original_without_markers)
    )
    optimized_without_urls = _strip_supported_style_macros(
        _URL_RE.sub("", optimized_without_markers)
    )
    if _number_tokens(original_without_urls) != _number_tokens(optimized_without_urls):
        raise AILayoutValidationError(
            "AI 润色结果改变了数字，本次未修改内容",
            code="NUMBERS_CHANGED",
        )

    original_visible_length = len(_visible_copy(original))
    optimized_visible_length = len(_visible_copy(optimized))
    maximum_length = max(
        original_visible_length + 320,
        int(original_visible_length * 1.35),
    )
    minimum_length = max(
        1,
        min(
            original_visible_length - 320,
            int(original_visible_length * 0.65),
        ),
    )
    if optimized_visible_length > maximum_length:
        raise AILayoutValidationError(
            "AI 润色结果扩写过多，本次未修改内容",
            code="POLISH_EXPANDED_TOO_MUCH",
        )
    if optimized_visible_length < minimum_length:
        raise AILayoutValidationError(
            "AI 润色结果删减过多，本次未修改内容",
            code="POLISH_REMOVED_TOO_MUCH",
        )


def _build_layout_selection_messages(content: str) -> list[dict[str, str]]:
    rules = """
你是中文社交图文排版助手。只输出一个合法 JSON 对象，不要代码块、解释或 <think>。
JSON schema：
{"highlights":[{"text":"原文中逐字存在的连续短语","style":"color|bg|bold"}],"changes":["简短说明"]}

从原文选择 3-8 个最值得强调的短语，每个 4-64 个字符。text 必须从输入正文逐字复制且只出现一次，
不得改字、标点、大小写或空格，不得包含换行、[[image:...]]、{{...}}、Markdown 标记，
也不要选择已经位于 color/bg/加粗/斜体标记内的文字。style 只能是 color、bg、bold。
重点要克制，优先结论、行动建议与关键限制；无法确认逐字一致的内容不要选择。
""".strip()
    return [
        {"role": "system", "content": rules},
        {"role": "user", "content": f"请从下面正文中选择排版重点：\n\n{content}"},
    ]


def _build_polish_selection_messages(content: str) -> list[dict[str, str]]:
    rules = """
你是中文社交图文编辑。只输出一个合法 JSON 对象，不要代码块、解释或 <think>。
JSON schema：
{"edits":[{"source":"原文中逐字存在的单行片段","replacement":"润色后的单行片段"}],
"highlights":[{"text":"应用 edits 后正文中逐字存在的连续短语","style":"color|bg|bold"}],
"changes":["简短说明"]}

这是安全润色任务，不要返回完整正文。选择最多十二处真正需要改善的句子或短语：
- source 必须从输入正文逐字复制、只出现一次，长度为四到六百个字符，且不能跨行。
- replacement 只改善病句、啰嗦、节奏和表达，不得改变事实、专有名词或原意，不得扩写。
- source 与 replacement 中的全部数字、价格、日期、比例和 URL 必须按原顺序逐字一致，
  包括“一、两、三、十、一个月、三档”等中文数量表达。
- 不要编辑 [[image:...]]、{{...}}、Markdown 链接、代码、HTML 或已有样式中的文字。
- replacement 只能是普通单行文字，不得加入标题、列表、样式标记或图片标记。

再选择最多八处排版重点。highlight.text 必须逐字存在于应用 edits 后的正文且只出现一次，
长度为四到六十四个字符，不得包含换行、图片/样式/Markdown 标记或 URL。
style 只能是 color、bg、bold。重点要克制，优先结论、行动建议和关键限制。
无法安全润色的片段不要提交；宁可少改，也不要猜测或补充内容。
""".strip()
    return [
        {"role": "system", "content": rules},
        {"role": "user", "content": f"请为下面正文提出安全的局部润色与排版选择：\n\n{content}"},
    ]


def _visible_copy(content: str) -> str:
    text = _strip_supported_style_macros(_IMAGE_MARKER_RE.sub("", content or ""))

    visible_lines = []
    for line in text.splitlines():
        value = re.sub(r"^\s*#{1,6}\s+", "", line)
        value = re.sub(r"^\s*>\s+", "", value)
        value = re.sub(r"^\s*(?:[-+*]\s+|\d+[.)]\s+)", "", value)
        if re.fullmatch(r"\s*([-*_])(?:\s*\1){2,}\s*", value):
            value = ""
        visible_lines.append(value)
    text = "\n".join(visible_lines).replace("**", "").replace("*", "")
    return re.sub(r"\s+", "", text)


def _strip_supported_style_macros(content: str) -> str:
    text = content or ""
    previous = None
    while previous != text:
        previous = text
        text = _STYLE_MACRO_RE.sub(lambda match: match.group(2), text)
    if "{{" in text or "}}" in text:
        raise AILayoutValidationError(
            "AI 排版结果包含不支持的样式标记，本次未修改内容",
            code="UNSUPPORTED_STYLE_MARKUP",
        )
    return text


def _number_tokens(content: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return (
        tuple(_NUMBER_RE.findall(content or "")),
        tuple(_CHINESE_QUANTITY_RE.findall(content or "")),
    )


def _image_markers(content: str) -> list[str]:
    return _IMAGE_MARKER_RE.findall(content or "")


def _http_error(status_code: int) -> AILayoutProviderError:
    if status_code in {401, 403}:
        return AILayoutProviderError(
            "AI 排版服务配置无效，请检查服务端环境变量",
            code="AI_PROVIDER_AUTH_FAILED",
        )
    if status_code == 429 or status_code >= 500:
        return AILayoutProviderError(
            "AI 排版服务繁忙，请稍后重试",
            code="AI_PROVIDER_BUSY",
        )
    return AILayoutProviderError(
        "AI 排版请求未被模型服务接受",
        code="AI_PROVIDER_REJECTED",
    )


def _read_positive_float(raw: Optional[str], *, default: float) -> float:
    try:
        value = float(raw) if raw not in (None, "") else default
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _read_positive_int(raw: Optional[str], *, default: int) -> int:
    try:
        value = int(raw) if raw not in (None, "") else default
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default
