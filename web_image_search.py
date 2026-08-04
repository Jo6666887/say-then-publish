"""Safe, server-side web image search and import for Write Then Publish.

Only official JSON APIs are supported.  Remote image URLs are never returned to
the browser: candidates receive opaque, short-lived IDs and both preview and
import pass through the same allow-list, redirect, size, MIME and image-decoder
checks.  Imported bytes are re-encoded in memory so EXIF and other metadata are
not carried into the user's asset library.
"""

from __future__ import annotations

import base64
import hashlib
import html
import io
import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urljoin, urlparse

import requests

from ai_layout import AILayoutService


WIKIMEDIA_API_URL = "https://commons.wikimedia.org/w/api.php"
PEXELS_API_URL = "https://api.pexels.com/v1/search"
PEXELS_LICENSE_URL = "https://www.pexels.com/license/"
APP_USER_AGENT = "SayThenPublish/1.0 (local creator workspace)"

OFFICIAL_API_HOSTS = frozenset({"commons.wikimedia.org", "api.pexels.com"})
WIKIMEDIA_IMAGE_HOSTS = frozenset({"upload.wikimedia.org"})
PEXELS_IMAGE_HOSTS = frozenset({"images.pexels.com"})
ALLOWED_IMAGE_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
PIL_FORMAT_TO_MIME = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}

DEFAULT_TIMEOUT_SECONDS = 12.0
DEFAULT_CACHE_TTL_SECONDS = 10 * 60
DEFAULT_MAX_IMAGE_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_PREVIEW_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
MAX_BLOCKS = 80
MAX_BLOCK_TEXT_CHARS = 8000
MAX_QUERY_CHARS = 64
MAX_IMAGE_PIXELS = 16_000_000

_BLOCK_ID_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")
_IMAGE_MARKER_RE = re.compile(r"\[\[image:[^\]]+\]\]")
_STYLE_MACRO_RE = re.compile(r"\{\{(?:color|bg):#[0-9a-fA-F]{3,8}\|([\s\S]*?)\}\}")
_MARKDOWN_RE = re.compile(
    r"(?:^|\s)(?:#{1,6}|>|[-+*]|\d+[.)])\s+|[*_`~]+|!?\[[^\]]*\]\([^)]*\)",
    re.MULTILINE,
)
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")
_HTML_TAG_RE = re.compile(r"<[^>]*>")
_SAFE_AI_QUERY_WORDS = frozenset(
    {
        "abstract",
        "ai",
        "analysis",
        "architecture",
        "art",
        "artificial",
        "business",
        "city",
        "cloud",
        "coding",
        "communication",
        "community",
        "computer",
        "concept",
        "creative",
        "creativity",
        "culture",
        "data",
        "design",
        "digital",
        "editorial",
        "education",
        "energy",
        "engineering",
        "environment",
        "finance",
        "food",
        "future",
        "health",
        "human",
        "illustration",
        "innovation",
        "intelligence",
        "internet",
        "landscape",
        "learning",
        "lifestyle",
        "machine",
        "market",
        "media",
        "mobile",
        "model",
        "modern",
        "nature",
        "network",
        "office",
        "people",
        "photography",
        "product",
        "productivity",
        "professional",
        "programming",
        "research",
        "robotics",
        "science",
        "security",
        "social",
        "software",
        "strategy",
        "teamwork",
        "technology",
        "tools",
        "travel",
        "visual",
        "wellness",
        "workflow",
        "workspace",
    }
)
_FALLBACK_VISUAL_CATEGORIES = (
    (("ai", "人工智能", "大模型", "智能体", "agent", "模型"), "artificial intelligence technology"),
    (("效率", "办公", "工作流", "生产力", "协作"), "productivity workspace"),
    (("数据", "分析", "研究", "报告", "调研"), "data analysis research"),
    (("代码", "编程", "软件", "api", "开发"), "software technology"),
    (("设计", "图片", "视频", "创作", "视觉"), "creative design"),
    (("商业", "产品", "营销", "品牌", "增长"), "business product strategy"),
    (("金融", "投资", "股票", "市场"), "finance market"),
    (("健康", "医疗", "运动", "健身"), "health wellness"),
    (("教育", "学习", "课程", "知识"), "education learning"),
    (("旅行", "城市", "建筑", "空间"), "travel city architecture"),
    (("自然", "环境", "生态", "能源"), "nature environment"),
    (("食物", "美食", "餐饮"), "food lifestyle"),
)


class IllustrationError(RuntimeError):
    """A safe-to-display illustration service error."""

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


class IllustrationValidationError(IllustrationError):
    pass


class IllustrationNotFoundError(IllustrationError):
    pass


class IllustrationProviderError(IllustrationError):
    pass


class IllustrationSecurityError(IllustrationError):
    pass


@dataclass(frozen=True)
class IllustrationConfig:
    pexels_api_key: str = ""
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES
    max_preview_bytes: int = DEFAULT_MAX_PREVIEW_BYTES

    @classmethod
    def from_env(
        cls,
        environ: Optional[Mapping[str, str]] = None,
    ) -> "IllustrationConfig":
        values = os.environ if environ is None else environ
        return cls(
            pexels_api_key=(values.get("WTP_PEXELS_API_KEY") or "").strip(),
            timeout_seconds=_positive_float(
                values.get("WTP_ILLUSTRATION_TIMEOUT_SECONDS"),
                DEFAULT_TIMEOUT_SECONDS,
            ),
            cache_ttl_seconds=_positive_int(
                values.get("WTP_ILLUSTRATION_CACHE_TTL_SECONDS"),
                DEFAULT_CACHE_TTL_SECONDS,
            ),
            max_image_bytes=_positive_int(
                values.get("WTP_ILLUSTRATION_MAX_IMAGE_BYTES"),
                DEFAULT_MAX_IMAGE_BYTES,
            ),
            max_preview_bytes=_positive_int(
                values.get("WTP_ILLUSTRATION_MAX_PREVIEW_BYTES"),
                DEFAULT_MAX_PREVIEW_BYTES,
            ),
        )


@dataclass(frozen=True)
class SearchResult:
    provider: str
    title: str
    image_url: str
    preview_image_url: str
    source_page_url: str
    creator: str
    license: str
    license_url: str
    width: int | None
    height: int | None
    mime_type: str


@dataclass
class CandidateRecord:
    candidate_id: str
    project_id: str
    updated_at: int
    content_hash: str
    block_id: str
    query: str
    result: SearchResult
    created_at: float
    expires_at: float


class _TTLCache:
    """Small process-local TTL cache with a deterministic upper bound."""

    def __init__(self, *, ttl_seconds: int, maximum_entries: int):
        self.ttl_seconds = max(1, int(ttl_seconds))
        self.maximum_entries = max(1, int(maximum_entries))
        self._values: dict[str, tuple[float, Any]] = {}
        self._lock = threading.RLock()

    def get(self, key: str) -> Any | None:
        now = time.monotonic()
        with self._lock:
            self._purge(now)
            item = self._values.get(key)
            return item[1] if item else None

    def set(self, key: str, value: Any) -> None:
        now = time.monotonic()
        with self._lock:
            self._purge(now)
            if len(self._values) >= self.maximum_entries:
                oldest = min(self._values, key=lambda item: self._values[item][0])
                self._values.pop(oldest, None)
            self._values[key] = (now + self.ttl_seconds, value)

    def _purge(self, now: float) -> None:
        expired = [key for key, (expires, _) in self._values.items() if expires <= now]
        for key in expired:
            self._values.pop(key, None)


class CandidateCache:
    def __init__(self, *, ttl_seconds: int, maximum_entries: int = 256):
        self.ttl_seconds = max(1, int(ttl_seconds))
        self.maximum_entries = max(1, int(maximum_entries))
        self._records: dict[str, CandidateRecord] = {}
        self._lock = threading.RLock()

    def put(
        self,
        *,
        project_id: str,
        updated_at: int,
        content_hash: str,
        block_id: str,
        query: str,
        result: SearchResult,
    ) -> CandidateRecord:
        now = time.monotonic()
        with self._lock:
            self._purge(now)
            if len(self._records) >= self.maximum_entries:
                oldest = min(self._records, key=lambda key: self._records[key].created_at)
                self._records.pop(oldest, None)
            candidate_id = uuid.uuid4().hex
            record = CandidateRecord(
                candidate_id=candidate_id,
                project_id=project_id,
                updated_at=updated_at,
                content_hash=content_hash,
                block_id=block_id,
                query=query,
                result=result,
                created_at=now,
                expires_at=now + self.ttl_seconds,
            )
            self._records[candidate_id] = record
            return record

    def get(self, candidate_id: str) -> CandidateRecord:
        if not isinstance(candidate_id, str) or not re.fullmatch(r"[0-9a-f]{32}", candidate_id):
            raise IllustrationNotFoundError("配图候选不存在或已过期", code="CANDIDATE_NOT_FOUND")
        now = time.monotonic()
        with self._lock:
            self._purge(now)
            record = self._records.get(candidate_id)
            if record is None:
                raise IllustrationNotFoundError(
                    "配图候选不存在或已过期",
                    code="CANDIDATE_NOT_FOUND",
                )
            return record

    def _purge(self, now: float) -> None:
        expired = [
            candidate_id
            for candidate_id, record in self._records.items()
            if record.expires_at <= now
        ]
        for candidate_id in expired:
            self._records.pop(candidate_id, None)


class WebImageSearchService:
    """Official-provider search, safe proxy preview and sanitized import."""

    def __init__(
        self,
        config: IllustrationConfig,
        *,
        ai_layout: AILayoutService | Any | None = None,
        session: Any | None = None,
        clock: Any = time.monotonic,
    ):
        self.config = config
        self.ai_layout = ai_layout
        self._clock = clock
        if session is None:
            session = requests.Session()
            session.trust_env = False
        self._session = session
        self._search_cache = _TTLCache(
            ttl_seconds=config.cache_ttl_seconds,
            maximum_entries=128,
        )
        self._candidates = CandidateCache(
            ttl_seconds=config.cache_ttl_seconds,
            maximum_entries=256,
        )

    @classmethod
    def from_env(
        cls,
        environ: Optional[Mapping[str, str]] = None,
        *,
        ai_layout: AILayoutService | Any | None = None,
        session: Any | None = None,
    ) -> "WebImageSearchService":
        return cls(
            IllustrationConfig.from_env(environ),
            ai_layout=ai_layout,
            session=session,
        )

    def status(self) -> dict[str, Any]:
        ai_status = (
            self.ai_layout.status()
            if self.ai_layout is not None and callable(getattr(self.ai_layout, "status", None))
            else {"enabled": False}
        )
        return {
            "ok": True,
            "enabled": True,
            "providers": [
                {
                    "id": "wikimedia",
                    "label": "Wikimedia Commons",
                    "enabled": True,
                    "requiresKey": False,
                },
                {
                    "id": "pexels",
                    "label": "Pexels",
                    "enabled": bool(self.config.pexels_api_key),
                    "requiresKey": True,
                },
            ],
            "limits": {
                "maxImages": 3,
                "maxCandidates": 4,
                "maxImageBytes": self.config.max_image_bytes,
            },
            "ai": {
                "enabled": bool(ai_status.get("enabled")),
            },
            "message": "配图只使用 Wikimedia Commons 或已配置的 Pexels 官方接口",
        }

    def search(
        self,
        *,
        project_id: str,
        updated_at: int,
        content: str,
        blocks: Sequence[Mapping[str, Any]],
        provider: str = "auto",
        max_images: int = 2,
        max_candidates: int = 3,
    ) -> dict[str, Any]:
        normalized_blocks = validate_blocks(blocks, content=content)
        provider = validate_provider(provider, pexels_enabled=bool(self.config.pexels_api_key))
        max_images = _bounded_integer(max_images, name="maxImages", minimum=1, maximum=3)
        max_candidates = _bounded_integer(
            max_candidates,
            name="maxCandidates",
            minimum=2,
            maximum=4,
        )

        plan = plan_image_queries(
            normalized_blocks,
            max_images=max_images,
            ai_layout=self.ai_layout,
        )
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        public_candidates: list[dict[str, Any]] = []
        for item in plan["items"]:
            results = self._search_provider(
                provider,
                item["query"],
                max_candidates=max_candidates,
            )
            for result in results[:max_candidates]:
                record = self._candidates.put(
                    project_id=project_id,
                    updated_at=updated_at,
                    content_hash=content_hash,
                    block_id=item["blockId"],
                    query=item["query"],
                    result=result,
                )
                public_candidates.append(self._public_candidate(record))

        expires_at = datetime.fromtimestamp(
            time.time() + self.config.cache_ttl_seconds,
            tz=timezone.utc,
        ).isoformat()
        return {
            "ok": True,
            "plan": plan,
            "candidates": public_candidates,
            "expiresAt": expires_at,
        }

    def preview(self, candidate_id: str) -> tuple[bytes, str]:
        record = self._candidates.get(candidate_id)
        raw, content_type = self._download_image(
            record.result.preview_image_url,
            provider=record.result.provider,
            maximum_bytes=self.config.max_preview_bytes,
        )
        clean, mime_type, _, _ = sanitize_image(
            raw,
            declared_mime_type=content_type,
            maximum_bytes=self.config.max_preview_bytes,
        )
        return clean, mime_type

    def import_candidate(
        self,
        candidate_id: str,
        *,
        project_id: str,
        updated_at: int,
        content: str,
    ) -> dict[str, Any]:
        record = self._candidates.get(candidate_id)
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if (
            record.project_id != project_id
            or record.updated_at != updated_at
            or record.content_hash != content_hash
        ):
            raise IllustrationValidationError(
                "正文已有新修改，请保存后重新配图",
                code="DRAFT_VERSION_CONFLICT",
            )
        raw, content_type = self._download_image(
            record.result.image_url,
            provider=record.result.provider,
            maximum_bytes=self.config.max_image_bytes,
        )
        clean, mime_type, width, height = sanitize_image(
            raw,
            declared_mime_type=content_type,
            maximum_bytes=self.config.max_image_bytes,
        )
        data_url = (
            f"data:{mime_type};base64,"
            f"{base64.b64encode(clean).decode('ascii')}"
        )
        return {
            "ok": True,
            "blockId": record.block_id,
            "asset": {
                "dataUrl": data_url,
                "mimeType": mime_type,
                "byteSize": len(clean),
                "width": width,
                "height": height,
                "source": {
                    "kind": "web",
                    "provider": record.result.provider,
                    "title": record.result.title,
                    "sourcePageUrl": record.result.source_page_url,
                    "creator": record.result.creator,
                    "license": record.result.license,
                    "licenseUrl": record.result.license_url,
                    "query": record.query,
                    "fetchedAt": datetime.now(timezone.utc).isoformat(),
                },
            },
        }

    def _public_candidate(self, record: CandidateRecord) -> dict[str, Any]:
        preview_path = f"/api/illustrations/candidates/{record.candidate_id}/preview"
        result = record.result
        return {
            "id": record.candidate_id,
            "blockId": record.block_id,
            "provider": result.provider,
            "title": result.title,
            "thumbnailUrl": preview_path,
            "previewUrl": preview_path,
            "sourcePageUrl": result.source_page_url,
            "creator": result.creator,
            "license": result.license,
            "licenseUrl": result.license_url,
            "width": result.width,
            "height": result.height,
        }

    def _search_provider(
        self,
        provider: str,
        query: str,
        *,
        max_candidates: int,
    ) -> list[SearchResult]:
        if provider == "wikimedia":
            return self._search_wikimedia(query, max_candidates=max_candidates)
        if provider == "pexels":
            return self._search_pexels(query, max_candidates=max_candidates)
        # auto uses Pexels when configured, but Wikimedia remains a deterministic
        # fallback for provider outages and zero-result searches.
        if self.config.pexels_api_key:
            try:
                results = self._search_pexels(query, max_candidates=max_candidates)
            except IllustrationProviderError:
                results = []
            if results:
                return results
        return self._search_wikimedia(query, max_candidates=max_candidates)

    def _search_wikimedia(self, query: str, *, max_candidates: int) -> list[SearchResult]:
        cache_key = f"wikimedia:{max_candidates}:{query}"
        cached = self._search_cache.get(cache_key)
        if cached is not None:
            return list(cached)
        results = []
        # Commons search is intentionally literal: a good 4–6 word visual
        # phrase can still return nothing. Retry only with shorter variants
        # derived from the same already-approved query, never with more draft
        # text. This keeps privacy boundaries unchanged while avoiding an empty
        # result for otherwise useful plans such as "AI productivity workspace".
        for search_query in _wikimedia_query_variants(query):
            payload = self._official_api_json(
                WIKIMEDIA_API_URL,
                params={
                    "action": "query",
                    "format": "json",
                    "formatversion": "2",
                    "generator": "search",
                    "gsrsearch": search_query,
                    "gsrnamespace": "6",
                    "gsrlimit": str(max_candidates * 2),
                    "prop": "imageinfo",
                    "iiprop": "url|size|mime|extmetadata",
                    "iiurlwidth": "1200",
                    "origin": "*",
                },
                headers={"Accept": "application/json"},
            )
            pages = (
                (payload.get("query") or {}).get("pages")
                if isinstance(payload, dict)
                else None
            )
            for page in pages if isinstance(pages, list) else []:
                info_list = page.get("imageinfo") if isinstance(page, dict) else None
                info = info_list[0] if isinstance(info_list, list) and info_list else None
                if not isinstance(info, dict):
                    continue
                mime_type = normalize_mime_type(info.get("mime"))
                if mime_type not in ALLOWED_IMAGE_MIME_TYPES:
                    continue
                image_url = info.get("url")
                preview_url = info.get("thumburl") or image_url
                source_page_url = info.get("descriptionurl")
                try:
                    validate_remote_url(image_url, allowed_hosts=WIKIMEDIA_IMAGE_HOSTS)
                    validate_remote_url(preview_url, allowed_hosts=WIKIMEDIA_IMAGE_HOSTS)
                    validate_remote_url(
                        source_page_url,
                        allowed_hosts=frozenset({"commons.wikimedia.org"}),
                    )
                except IllustrationSecurityError:
                    continue
                metadata = (
                    info.get("extmetadata")
                    if isinstance(info.get("extmetadata"), dict)
                    else {}
                )
                license_name = _metadata_value(
                    metadata,
                    "LicenseShortName",
                    maximum=80,
                )
                # A source page is not a substitute for an explicit reuse
                # license. Unclear candidates are excluded before the user can
                # select them.
                if not license_name:
                    continue
                result = SearchResult(
                    provider="wikimedia",
                    title=_clean_text(page.get("title"), maximum=180).removeprefix("File:"),
                    image_url=image_url,
                    preview_image_url=preview_url,
                    source_page_url=source_page_url,
                    creator=_metadata_value(metadata, "Artist", maximum=160)
                    or "来源页未注明作者",
                    license=license_name,
                    license_url=_safe_metadata_url(
                        _metadata_value(metadata, "LicenseUrl", maximum=500)
                    ),
                    width=_safe_dimension(info.get("width")),
                    height=_safe_dimension(info.get("height")),
                    mime_type=mime_type,
                )
                results.append(result)
                if len(results) >= max_candidates:
                    break
            if results:
                break
        self._search_cache.set(cache_key, tuple(results))
        return results

    def _search_pexels(self, query: str, *, max_candidates: int) -> list[SearchResult]:
        if not self.config.pexels_api_key:
            raise IllustrationValidationError(
                "Pexels 尚未配置，请选择自动或 Wikimedia",
                code="PEXELS_NOT_CONFIGURED",
            )
        cache_key = f"pexels:{max_candidates}:{query}"
        cached = self._search_cache.get(cache_key)
        if cached is not None:
            return list(cached)
        payload = self._official_api_json(
            PEXELS_API_URL,
            params={"query": query, "per_page": str(max_candidates)},
            headers={
                "Accept": "application/json",
                "Authorization": self.config.pexels_api_key,
            },
        )
        photos = payload.get("photos") if isinstance(payload, dict) else None
        results = []
        for photo in photos if isinstance(photos, list) else []:
            if not isinstance(photo, dict):
                continue
            sources = photo.get("src") if isinstance(photo.get("src"), dict) else {}
            image_url = sources.get("original") or sources.get("large2x")
            preview_url = sources.get("large") or sources.get("medium") or image_url
            source_page_url = photo.get("url")
            try:
                validate_remote_url(image_url, allowed_hosts=PEXELS_IMAGE_HOSTS)
                validate_remote_url(preview_url, allowed_hosts=PEXELS_IMAGE_HOSTS)
                validate_remote_url(
                    source_page_url,
                    allowed_hosts=frozenset({"www.pexels.com", "pexels.com"}),
                )
            except IllustrationSecurityError:
                continue
            results.append(
                SearchResult(
                    provider="pexels",
                    title=_clean_text(photo.get("alt"), maximum=180) or "Pexels 图片",
                    image_url=image_url,
                    preview_image_url=preview_url,
                    source_page_url=source_page_url,
                    creator=_clean_text(photo.get("photographer"), maximum=160),
                    license="Pexels License",
                    license_url=PEXELS_LICENSE_URL,
                    width=_safe_dimension(photo.get("width")),
                    height=_safe_dimension(photo.get("height")),
                    mime_type="image/jpeg",
                )
            )
        self._search_cache.set(cache_key, tuple(results))
        return results

    def _official_api_json(
        self,
        url: str,
        *,
        params: Mapping[str, str],
        headers: Mapping[str, str],
    ) -> dict[str, Any]:
        validate_remote_url(url, allowed_hosts=OFFICIAL_API_HOSTS)
        request_headers = {
            "User-Agent": APP_USER_AGENT,
            **dict(headers),
        }
        try:
            response = self._session.get(
                url,
                params=dict(params),
                headers=request_headers,
                timeout=self.config.timeout_seconds,
                allow_redirects=False,
            )
        except requests.Timeout:
            raise IllustrationProviderError(
                "图片搜索超时，请稍后重试",
                code="IMAGE_SEARCH_TIMEOUT",
            ) from None
        except requests.RequestException:
            raise IllustrationProviderError(
                "图片搜索服务暂时不可用",
                code="IMAGE_SEARCH_UNAVAILABLE",
            ) from None
        try:
            if 300 <= int(response.status_code) < 400:
                raise IllustrationProviderError(
                    "图片搜索服务返回了异常跳转",
                    code="IMAGE_SEARCH_REDIRECTED",
                )
            if int(response.status_code) != 200:
                raise IllustrationProviderError(
                    "图片搜索服务暂时不可用",
                    code="IMAGE_SEARCH_FAILED",
                )
            payload = response.json()
        except (TypeError, ValueError, json.JSONDecodeError):
            raise IllustrationProviderError(
                "图片搜索服务返回了无效数据",
                code="IMAGE_SEARCH_INVALID_RESPONSE",
            ) from None
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        if not isinstance(payload, dict):
            raise IllustrationProviderError(
                "图片搜索服务返回了无效数据",
                code="IMAGE_SEARCH_INVALID_RESPONSE",
            )
        return payload

    def _download_image(
        self,
        url: str,
        *,
        provider: str,
        maximum_bytes: int,
    ) -> tuple[bytes, str]:
        allowed_hosts = (
            WIKIMEDIA_IMAGE_HOSTS if provider == "wikimedia" else PEXELS_IMAGE_HOSTS
        )
        current_url = validate_remote_url(url, allowed_hosts=allowed_hosts)
        response = None
        try:
            for redirect_count in range(MAX_REDIRECTS + 1):
                try:
                    response = self._session.get(
                        current_url,
                        headers={
                            "Accept": "image/jpeg,image/png,image/webp",
                            "User-Agent": "WriteThenPublish/1.0 image-import",
                        },
                        timeout=self.config.timeout_seconds,
                        stream=True,
                        allow_redirects=False,
                    )
                except requests.Timeout:
                    raise IllustrationProviderError(
                        "图片下载超时，请稍后重试",
                        code="IMAGE_DOWNLOAD_TIMEOUT",
                    ) from None
                except requests.RequestException:
                    raise IllustrationProviderError(
                        "图片暂时无法下载",
                        code="IMAGE_DOWNLOAD_FAILED",
                    ) from None

                status_code = int(response.status_code)
                if 300 <= status_code < 400:
                    location = response.headers.get("Location")
                    close = getattr(response, "close", None)
                    if callable(close):
                        close()
                    response = None
                    if not location or redirect_count >= MAX_REDIRECTS:
                        raise IllustrationSecurityError(
                            "图片下载跳转无效",
                            code="IMAGE_REDIRECT_BLOCKED",
                        )
                    current_url = validate_remote_url(
                        urljoin(current_url, location),
                        allowed_hosts=allowed_hosts,
                    )
                    continue
                if status_code != 200:
                    raise IllustrationProviderError(
                        "图片暂时无法下载",
                        code="IMAGE_DOWNLOAD_FAILED",
                    )

                final_url = getattr(response, "url", None) or current_url
                validate_remote_url(final_url, allowed_hosts=allowed_hosts)
                content_type = normalize_mime_type(response.headers.get("Content-Type"))
                if content_type not in ALLOWED_IMAGE_MIME_TYPES:
                    raise IllustrationSecurityError(
                        "仅支持 JPEG、PNG 或 WebP 图片",
                        code="IMAGE_TYPE_BLOCKED",
                    )
                content_length = _optional_nonnegative_int(
                    response.headers.get("Content-Length")
                )
                if content_length is not None and content_length > maximum_bytes:
                    raise IllustrationSecurityError(
                        "图片文件过大",
                        code="IMAGE_TOO_LARGE",
                    )
                chunks = []
                total = 0
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > maximum_bytes:
                        raise IllustrationSecurityError(
                            "图片文件过大",
                            code="IMAGE_TOO_LARGE",
                        )
                    chunks.append(bytes(chunk))
                if not chunks:
                    raise IllustrationProviderError(
                        "图片内容为空",
                        code="IMAGE_EMPTY",
                    )
                return b"".join(chunks), content_type
            raise IllustrationSecurityError(
                "图片下载跳转过多",
                code="IMAGE_REDIRECT_BLOCKED",
            )
        finally:
            if response is not None:
                close = getattr(response, "close", None)
                if callable(close):
                    close()


def validate_blocks(
    blocks: Sequence[Mapping[str, Any]],
    *,
    content: str,
) -> list[dict[str, str]]:
    if isinstance(blocks, (str, bytes)) or not isinstance(blocks, Sequence):
        raise IllustrationValidationError(
            "正文分块无效",
            code="INVALID_BLOCKS",
        )
    if not blocks or len(blocks) > MAX_BLOCKS:
        raise IllustrationValidationError(
            "正文分块数量无效",
            code="INVALID_BLOCKS",
        )
    normalized = []
    seen_ids = set()
    normalized_content = _plain_block_text(content)
    for block in blocks:
        block_id = block.get("blockId") if isinstance(block, Mapping) else None
        text = block.get("text") if isinstance(block, Mapping) else None
        if (
            not isinstance(block_id, str)
            or not _BLOCK_ID_RE.fullmatch(block_id)
            or block_id in seen_ids
            or not isinstance(text, str)
            or not text.strip()
            or len(text) > MAX_BLOCK_TEXT_CHARS
            or not _plain_block_text(text)
            or _plain_block_text(text) not in normalized_content
        ):
            raise IllustrationValidationError(
                "正文分块与当前草稿不一致",
                code="INVALID_BLOCKS",
            )
        seen_ids.add(block_id)
        normalized.append({"blockId": block_id, "text": text})
    return normalized


def validate_provider(provider: Any, *, pexels_enabled: bool) -> str:
    if not isinstance(provider, str) or provider not in {"auto", "wikimedia", "pexels"}:
        raise IllustrationValidationError(
            "不支持的图片来源",
            code="INVALID_PROVIDER",
        )
    if provider == "pexels" and not pexels_enabled:
        raise IllustrationValidationError(
            "Pexels 尚未配置，请选择自动或 Wikimedia",
            code="PEXELS_NOT_CONFIGURED",
        )
    return provider


def plan_image_queries(
    blocks: Sequence[Mapping[str, str]],
    *,
    max_images: int,
    ai_layout: Any | None,
) -> dict[str, Any]:
    """Ask the configured AI only for blockId/query pairs, then validate them.

    Any disabled, malformed or failed AI response falls back to a deterministic
    local selector.  Neither path receives permission to return or mutate the
    full document.
    """

    allowed_ids = {block["blockId"] for block in blocks}
    if ai_layout is not None and callable(getattr(ai_layout, "plan_illustrations", None)):
        try:
            # Send only a bounded set of likely illustration passages to the
            # configured AI, not the full draft. The browser discloses this
            # before the explicit search action.
            ai_blocks = [
                ranked[2]
                for ranked in _rank_visual_blocks(blocks)[
                    : min(8, max(4, max_images * 3))
                ]
            ]
            items = ai_layout.plan_illustrations(ai_blocks, max_images=max_images)
            normalized = _validate_plan_items(
                items,
                allowed_ids={block["blockId"] for block in ai_blocks},
                maximum=max_images,
            )
            if normalized:
                return {"source": "ai", "items": normalized}
        except Exception:
            # Planning is optional.  Search remains useful and predictable even
            # when the model provider is disabled or temporarily unavailable.
            pass
    return {
        "source": "fallback",
        "items": _fallback_plan(blocks, max_images=max_images),
    }


def _validate_plan_items(
    items: Any,
    *,
    allowed_ids: set[str],
    maximum: int,
) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []
    normalized = []
    used_ids = set()
    for item in items:
        block_id = item.get("blockId") if isinstance(item, Mapping) else None
        query = item.get("query") if isinstance(item, Mapping) else None
        reason = item.get("reason") if isinstance(item, Mapping) else ""
        if (
            block_id not in allowed_ids
            or block_id in used_ids
            or not isinstance(query, str)
            or not query.strip()
        ):
            continue
        used_ids.add(block_id)
        safe_query = _safe_ai_visual_query(query)
        if not safe_query:
            continue
        normalized.append(
            {
                "blockId": block_id,
                "query": safe_query,
                "reason": _clean_text(reason, maximum=120) or "根据该段主题配图",
            }
        )
        if len(normalized) >= maximum:
            break
    return [item for item in normalized if item["query"]]


def _fallback_plan(
    blocks: Sequence[Mapping[str, str]],
    *,
    max_images: int,
) -> list[dict[str, str]]:
    ranked = _rank_visual_blocks(blocks)
    selected = sorted(ranked[:max_images], key=lambda item: -item[1])
    return [
        {
            "blockId": block["blockId"],
            "query": _fallback_visual_query(cleaned),
            "reason": "已在本机提取通用主题词，未把正文原句发送给图库",
        }
        for _, _, block, cleaned in selected
        if _fallback_visual_query(cleaned)
    ]


def _rank_visual_blocks(
    blocks: Sequence[Mapping[str, str]],
) -> list[tuple[int, int, Mapping[str, str], str]]:
    ranked = []
    for index, block in enumerate(blocks):
        cleaned = _plain_block_text(block["text"])
        if not cleaned:
            continue
        heading_bonus = 500 if block["text"].lstrip().startswith("#") else 0
        ranked.append((heading_bonus + min(len(cleaned), 400), -index, block, cleaned))
    ranked.sort(reverse=True, key=lambda item: (item[0], item[1]))
    return ranked


def validate_remote_url(url: Any, *, allowed_hosts: frozenset[str]) -> str:
    if not isinstance(url, str) or not url:
        raise IllustrationSecurityError("图片地址无效", code="IMAGE_URL_BLOCKED")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme != "https"
        or not host
        or host not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
    ):
        raise IllustrationSecurityError("图片地址被安全策略拒绝", code="IMAGE_URL_BLOCKED")
    return url


def sanitize_image(
    raw: bytes,
    *,
    declared_mime_type: str,
    maximum_bytes: int,
) -> tuple[bytes, str, int, int]:
    """Decode and re-encode a supported still image without source metadata."""

    if declared_mime_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise IllustrationSecurityError(
            "仅支持 JPEG、PNG 或 WebP 图片",
            code="IMAGE_TYPE_BLOCKED",
        )
    if not raw or len(raw) > maximum_bytes:
        raise IllustrationSecurityError("图片文件过大或为空", code="IMAGE_TOO_LARGE")
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError:
        raise IllustrationProviderError(
            "服务器缺少图片安全处理组件",
            code="IMAGE_PROCESSOR_UNAVAILABLE",
        ) from None

    try:
        source = Image.open(io.BytesIO(raw))
        source_format = str(source.format or "").upper()
        actual_mime_type = PIL_FORMAT_TO_MIME.get(source_format)
        if actual_mime_type not in ALLOWED_IMAGE_MIME_TYPES:
            raise IllustrationSecurityError(
                "仅支持 JPEG、PNG 或 WebP 图片",
                code="IMAGE_TYPE_BLOCKED",
            )
        if actual_mime_type != declared_mime_type:
            raise IllustrationSecurityError(
                "图片类型与内容不一致",
                code="IMAGE_TYPE_MISMATCH",
            )
        width, height = source.size
        if (
            width <= 0
            or height <= 0
            or width > 20_000
            or height > 20_000
            or width * height > MAX_IMAGE_PIXELS
            or bool(getattr(source, "is_animated", False))
        ):
            raise IllustrationSecurityError(
                "图片尺寸或帧数不安全",
                code="IMAGE_DIMENSIONS_BLOCKED",
            )
        source.load()
        oriented = ImageOps.exif_transpose(source)
        width, height = oriented.size
        if actual_mime_type == "image/jpeg":
            mode = "RGB"
            output_format = "JPEG"
            save_options = {"quality": 90, "optimize": True}
        elif actual_mime_type == "image/png":
            mode = "RGBA" if "A" in oriented.getbands() else "RGB"
            output_format = "PNG"
            save_options = {"optimize": True}
        else:
            mode = "RGBA" if "A" in oriented.getbands() else "RGB"
            output_format = "WEBP"
            save_options = {"quality": 90, "method": 4}
        pixels = oriented.convert(mode)
        clean = Image.new(mode, pixels.size)
        clean.paste(pixels)
        output = io.BytesIO()
        clean.save(output, format=output_format, **save_options)
        encoded = output.getvalue()
    except IllustrationSecurityError:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError, MemoryError):
        raise IllustrationSecurityError(
            "图片无法安全解码",
            code="IMAGE_DECODE_FAILED",
        ) from None
    finally:
        try:
            if oriented is not source:
                oriented.close()
        except (NameError, OSError):
            pass
        try:
            source.close()
        except (NameError, OSError):
            pass

    if len(encoded) > maximum_bytes:
        raise IllustrationSecurityError("图片处理后仍然过大", code="IMAGE_TOO_LARGE")
    return encoded, actual_mime_type, width, height


def normalize_mime_type(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    mime_type = value.split(";", 1)[0].strip().lower()
    return "image/jpeg" if mime_type == "image/jpg" else mime_type


def _plain_block_text(value: str) -> str:
    text = _IMAGE_MARKER_RE.sub(" ", value)
    text = _STYLE_MACRO_RE.sub(lambda match: match.group(1), text)
    text = _URL_RE.sub(" ", text)
    text = _MARKDOWN_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def _clean_query(value: str) -> str:
    cleaned = _plain_block_text(value)
    cleaned = re.sub(r"[^\w\u3400-\u9fff -]+", " ", cleaned, flags=re.UNICODE)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip(" -_")
    return cleaned[:MAX_QUERY_CHARS].strip()


def _safe_ai_visual_query(value: str) -> str:
    """Reduce an AI suggestion to a small allow-listed visual vocabulary."""

    words = re.findall(r"[A-Za-z]+", _clean_query(value).casefold())
    safe = []
    for word in words:
        normalized = "ai" if word in {"ai", "a"} else word
        if normalized in _SAFE_AI_QUERY_WORDS and normalized not in safe:
            safe.append(normalized)
        if len(safe) >= 6:
            break
    if safe == ["ai"]:
        return "artificial intelligence"
    return " ".join(safe)


def _fallback_visual_query(value: str) -> str:
    """Map draft text to generic local categories without sending a sentence."""

    lowered = _plain_block_text(value).casefold()
    categories = []
    for needles, query in _FALLBACK_VISUAL_CATEGORIES:
        if any(needle in lowered for needle in needles):
            categories.extend(query.split())
        if len(categories) >= 5:
            break
    if not categories:
        return "editorial abstract concept"
    unique = []
    for word in categories:
        if word not in unique:
            unique.append(word)
    return " ".join(unique[:6])


def _wikimedia_query_variants(value: str) -> tuple[str, ...]:
    """Return a small, deterministic retry ladder for Commons full-text search."""

    cleaned = _clean_query(value)
    if not cleaned:
        return ()
    variants = [cleaned]
    latin_tokens = re.findall(r"[A-Za-z][A-Za-z0-9.+-]*", cleaned)
    if latin_tokens:
        if latin_tokens[0].casefold() in {"ai", "a.i"}:
            variants.append("artificial intelligence")
        if len(latin_tokens) >= 2:
            variants.append(" ".join(latin_tokens[:2]))
            variants.append(" ".join(latin_tokens[-2:]))
        elif len(latin_tokens[0]) >= 3:
            variants.append(latin_tokens[0])
    unique = []
    seen = set()
    for variant in variants:
        normalized = _clean_query(variant)
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            unique.append(normalized)
    return tuple(unique[:4])


def _clean_text(value: Any, *, maximum: int) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = _HTML_TAG_RE.sub(" ", html.unescape(value))
    return _WHITESPACE_RE.sub(" ", cleaned).strip()[:maximum]


def _metadata_value(metadata: Mapping[str, Any], name: str, *, maximum: int) -> str:
    item = metadata.get(name)
    value = item.get("value") if isinstance(item, Mapping) else None
    return _clean_text(value, maximum=maximum)


def _safe_metadata_url(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value)
    return (
        value
        if (
            parsed.scheme == "https"
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
        )
        else ""
    )


def _safe_dimension(value: Any) -> int | None:
    try:
        numeric = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return numeric if 0 < numeric <= 100_000 else None


def _optional_nonnegative_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        numeric = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return numeric if numeric >= 0 else None


def _bounded_integer(value: Any, *, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        numeric = 0
    else:
        try:
            numeric = int(value)
        except (TypeError, ValueError, OverflowError):
            numeric = 0
    if numeric < minimum or numeric > maximum:
        raise IllustrationValidationError(
            f"{name} 超出允许范围",
            code="INVALID_LIMIT",
        )
    return numeric


def _positive_int(value: Any, default: int) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return numeric if numeric > 0 else default


def _positive_float(value: Any, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return numeric if numeric > 0 else default
