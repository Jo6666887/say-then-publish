"""Server-side AI layout/polish client with content-loss guardrails.

The browser must never call the model provider directly.  This module reads only
``WTP_AI_*`` environment variables, makes a synchronous non-streaming request,
and validates the model result before it can be shown or applied by the UI.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

import requests


DEFAULT_API_BASE = "https://maas-api.cn-huabei-1.xf-yun.com/v2"
DEFAULT_MODEL_ID = "xopkimik25"
DEFAULT_TIMEOUT_SECONDS = 90.0
DEFAULT_MAX_TOKENS = 8192
VALID_MODES = {"layout", "polish"}

_IMAGE_MARKER_RE = re.compile(r"\[\[image:([\w-]+)\]\]")
_THINK_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)
_FENCE_RE = re.compile(r"^```(?:json)?\s*([\s\S]*?)\s*```$", re.IGNORECASE)
_STYLE_MACRO_RE = re.compile(
    r"\{\{(?:color|bg):(#[0-9a-fA-F]{3,8})\|([\s\S]*?)\}\}"
)
_URL_RE = re.compile(r"https?://[^\s<>\"'\[\]{}（）。，、；：！？]+", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*(?:%|[A-Za-z]+)?")
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$")


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

        payload = {
            "model": self.config.model_id,
            "messages": _build_messages(content, mode=mode, accent_color=accent_color),
            "temperature": 0.15 if mode == "layout" else 0.25,
            "max_tokens": self.config.max_tokens,
            "stream": False,
            "search_disable": True,
        }
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Appid": self.config.app_id,
        }
        if self.config.resource_id:
            headers["lora_id"] = self.config.resource_id

        requester = self._session if self._session is not None else requests
        try:
            response = requester.post(
                f"{self.config.api_base}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.config.timeout_seconds,
            )
        except requests.RequestException:
            raise AILayoutProviderError(
                "AI 排版服务暂时不可用，请稍后重试",
                code="AI_PROVIDER_UNAVAILABLE",
            ) from None
        except Exception:
            raise AILayoutProviderError(
                "AI 排版服务暂时不可用，请稍后重试",
                code="AI_PROVIDER_UNAVAILABLE",
            ) from None

        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code >= 400:
            raise _http_error(status_code)

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

        parsed = parse_ai_layout_response(raw_content)
        optimized_content = parsed["optimized_content"]
        validate_optimized_content(content, optimized_content, mode=mode)
        return AILayoutResult(
            optimized_content=optimized_content,
            changes=tuple(parsed["changes"]),
            model=self.config.model_id,
        )


def parse_ai_layout_response(raw_content: str) -> dict[str, Any]:
    """Parse the model's strict JSON envelope after allowed wrapper cleanup."""

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

    original_without_urls = _URL_RE.sub("", original_without_markers)
    optimized_without_urls = _URL_RE.sub("", optimized_without_markers)
    if _NUMBER_RE.findall(original_without_urls) != _NUMBER_RE.findall(optimized_without_urls):
        raise AILayoutValidationError(
            "AI 润色结果改变了数字，本次未修改内容",
            code="NUMBERS_CHANGED",
        )


def _build_messages(content: str, *, mode: str, accent_color: str) -> list[dict[str, str]]:
    shared_rules = f"""
只输出一个合法 JSON 对象，不要 Markdown 代码块，不要解释，不要 <think>。
JSON schema：
{{"optimized_content":"完整优化后正文","changes":["最多 8 条简短变更说明"]}}

正文使用“写了就发”语法。只可使用以下排版：# / ## / ### 标题、> 引用、- 列表、
**加粗**、*斜体*、{{{{color:{accent_color}|文字}}}}、{{{{bg:#E8E9FF|文字}}}}。
所有 [[image:图片ID]] 标记必须逐字保留，数量和先后顺序不得变化；不得创造新图片 ID。
不得输出 HTML，不得把正文包进额外字段，不得输出 JSON 以外文字。
""".strip()
    if mode == "layout":
        task_rules = """
这是“智能排版”任务：正文的所有可见文字、数字、链接、标点和先后顺序必须保持不变。
你只能调整空行、标题/引用/列表层级，并添加或调整允许的加粗、斜体、文字色、背景高亮标记。
重点要克制：每屏只突出少量最重要的结论，不要整段全部高亮。
""".strip()
    else:
        task_rules = """
这是“一键润色”任务：可以改善病句、节奏和段落结构，但不得改变事实、数字、价格、日期、
比例、URL、专有名词和图片标记；不得凭空增加承诺、功能或结论。
同时做克制的重点高亮和层级排版。
""".strip()
    return [
        {"role": "system", "content": f"你是中文社交图文编辑。\n\n{shared_rules}\n\n{task_rules}"},
        {"role": "user", "content": f"请优化下面的完整正文：\n\n{content}"},
    ]


def _visible_copy(content: str) -> str:
    text = _IMAGE_MARKER_RE.sub("", content or "")
    previous = None
    while previous != text:
        previous = text
        text = _STYLE_MACRO_RE.sub(lambda match: match.group(2), text)
    if "{{" in text or "}}" in text:
        raise AILayoutValidationError(
            "AI 排版结果包含不支持的样式标记，本次未修改内容",
            code="UNSUPPORTED_STYLE_MARKUP",
        )

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
