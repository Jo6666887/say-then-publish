import base64
import io
import unittest
from unittest import mock

import requests
from PIL import Image

from web_image_search import (
    IllustrationConfig,
    IllustrationSecurityError,
    IllustrationValidationError,
    SearchResult,
    WebImageSearchService,
    plan_image_queries,
    sanitize_image,
    validate_blocks,
    validate_remote_url,
)


class FakeResponse:
    def __init__(
        self,
        *,
        status_code=200,
        headers=None,
        payload=None,
        raw=b"",
        chunks=None,
        url="",
    ):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload
        self._chunks = list(chunks) if chunks is not None else [raw]
        self.url = url
        self.closed = False

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def iter_content(self, chunk_size):
        del chunk_size
        yield from self._chunks

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.trust_env = True

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if not response.url:
            response.url = url
        return response


class FakePlanner:
    def __init__(self, items):
        self.items = items
        self.calls = []

    def status(self):
        return {"enabled": True, "model": "test-model", "reason": None}

    def plan_illustrations(self, blocks, *, max_images):
        self.calls.append((blocks, max_images))
        return self.items


def jpeg_bytes(*, exif=False, orientation=None):
    image = Image.new("RGB", (8, 6), "#336699")
    output = io.BytesIO()
    options = {}
    if exif or orientation:
        metadata = Image.Exif()
        if exif:
            metadata[270] = "private description"
            metadata[305] = "private software"
        if orientation:
            metadata[274] = orientation
        options["exif"] = metadata
    image.save(output, format="JPEG", **options)
    return output.getvalue()


def wikimedia_payload(*, include_svg=False, host="upload.wikimedia.org"):
    pages = [
        {
            "title": "File:Safe example.jpg",
            "imageinfo": [
                {
                    "url": f"https://{host}/wikipedia/commons/a/a1/safe.jpg",
                    "thumburl": f"https://{host}/wikipedia/commons/thumb/a/a1/safe.jpg/1200px-safe.jpg",
                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:Safe_example.jpg",
                    "width": 1600,
                    "height": 1200,
                    "mime": "image/jpeg",
                    "extmetadata": {
                        "Artist": {"value": "<b>Alice</b>"},
                        "LicenseShortName": {"value": "CC BY-SA 4.0"},
                        "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0/"},
                    },
                }
            ],
        }
    ]
    if include_svg:
        pages.insert(
            0,
            {
                "title": "File:Unsafe.svg",
                "imageinfo": [
                    {
                        "url": "https://upload.wikimedia.org/unsafe.svg",
                        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Unsafe.svg",
                        "mime": "image/svg+xml",
                    }
                ],
            },
        )
    return {"query": {"pages": pages}}


class WebImageSearchTests(unittest.TestCase):
    def make_service(self, responses=(), *, key="", planner=None, max_bytes=1024 * 1024):
        return WebImageSearchService(
            IllustrationConfig(
                pexels_api_key=key,
                timeout_seconds=1,
                cache_ttl_seconds=60,
                max_image_bytes=max_bytes,
                max_preview_bytes=max_bytes,
            ),
            ai_layout=planner,
            session=FakeSession(responses),
        )

    def test_status_exposes_capability_but_no_key_or_endpoint_configuration(self):
        service = self.make_service(key="pexels-super-secret", planner=FakePlanner([]))
        status = service.status()
        rendered = str(status).lower()
        self.assertTrue(status["enabled"])
        self.assertTrue(status["providers"][1]["enabled"])
        self.assertNotIn("pexels-super-secret", rendered)
        self.assertNotIn("api.pexels.com", rendered)
        self.assertNotIn("api_key", rendered)

    def test_blocks_must_be_unique_and_must_match_saved_content(self):
        content = "第一段正文\n\n第二段正文"
        self.assertEqual(
            validate_blocks(
                [
                    {"blockId": "block-0", "text": "第一段正文"},
                    {"blockId": "block-1", "text": "第二段正文"},
                ],
                content=content,
            )[1]["blockId"],
            "block-1",
        )
        self.assertEqual(
            validate_blocks(
                [{"blockId": "block-2", "text": "带格式的 多行正文"}],
                content="{{color:#5B5FEF|带格式的}}\n多行正文",
            )[0]["blockId"],
            "block-2",
        )
        for blocks in (
            [{"blockId": "../bad", "text": "第一段正文"}],
            [
                {"blockId": "same", "text": "第一段正文"},
                {"blockId": "same", "text": "第二段正文"},
            ],
            [{"blockId": "block-0", "text": "不存在的正文"}],
        ):
            with self.subTest(blocks=blocks):
                with self.assertRaises(IllustrationValidationError):
                    validate_blocks(blocks, content=content)

    def test_ai_plan_can_only_reference_submitted_block_ids(self):
        blocks = [
            {"blockId": "block-0", "text": "# 人工智能平台"},
            {"blockId": "block-1", "text": "统一管理文本、图片和视频模型"},
        ]
        planner = FakePlanner(
            [
                {"blockId": "made-up", "query": "恶意候选", "reason": "wrong"},
                {
                    "blockId": "block-1",
                    "query": "artificial intelligence workspace",
                    "reason": "核心概念",
                },
            ]
        )
        plan = plan_image_queries(blocks, max_images=2, ai_layout=planner)
        self.assertEqual(plan["source"], "ai")
        self.assertEqual(plan["items"][0]["blockId"], "block-1")
        self.assertNotIn("made-up", str(plan))
        self.assertEqual(blocks[1]["text"], "统一管理文本、图片和视频模型")

    def test_failed_ai_plan_has_deterministic_fallback(self):
        planner = FakePlanner("not-a-list")
        blocks = [
            {"blockId": "a", "text": "短段"},
            {"blockId": "b", "text": "# 更适合做封面的核心主题"},
            {"blockId": "c", "text": "另一个具体场景描述"},
        ]
        first = plan_image_queries(blocks, max_images=2, ai_layout=planner)
        second = plan_image_queries(blocks, max_images=2, ai_layout=planner)
        self.assertEqual(first, second)
        self.assertEqual(first["source"], "fallback")
        self.assertEqual(first["items"][0]["blockId"], "b")
        self.assertNotIn("更适合做封面", str(first))
        self.assertRegex(first["items"][0]["query"], r"^[a-z ]+$")

    def test_ai_query_is_reduced_to_safe_visual_words(self):
        planner = FakePlanner(
            [
                {
                    "blockId": "block-0",
                    "query": "AI productivity sk-private-123456 alice@example.com workspace",
                    "reason": "核心概念",
                }
            ]
        )
        plan = plan_image_queries(
            [{"blockId": "block-0", "text": "内部项目与工作流"}],
            max_images=1,
            ai_layout=planner,
        )
        self.assertEqual(
            plan["items"][0]["query"],
            "ai productivity workspace",
        )
        self.assertNotIn("private", str(plan))
        self.assertNotIn("example", str(plan))

    def test_wikimedia_search_uses_official_api_filters_svg_and_hides_remote_image_url(self):
        api_response = FakeResponse(payload=wikimedia_payload(include_svg=True))
        service = self.make_service([api_response])
        result = service.search(
            project_id="project-1",
            updated_at=10,
            content="# 人工智能平台",
            blocks=[{"blockId": "block-0", "text": "# 人工智能平台"}],
            provider="wikimedia",
            max_images=1,
            max_candidates=2,
        )
        self.assertEqual(len(result["candidates"]), 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["provider"], "wikimedia")
        self.assertEqual(candidate["creator"], "Alice")
        self.assertEqual(candidate["license"], "CC BY-SA 4.0")
        self.assertEqual(candidate["previewUrl"], candidate["thumbnailUrl"])
        self.assertTrue(candidate["previewUrl"].startswith("/api/illustrations/candidates/"))
        self.assertNotIn("upload.wikimedia.org", str(candidate))
        url, kwargs = service._session.calls[0]
        self.assertEqual(url, "https://commons.wikimedia.org/w/api.php")
        self.assertFalse(kwargs["allow_redirects"])
        self.assertTrue(kwargs["headers"]["User-Agent"].startswith("WriteThenPublish/"))

    def test_search_results_are_cached_without_repeating_provider_call(self):
        service = self.make_service([FakeResponse(payload=wikimedia_payload())])
        arguments = dict(
            project_id="project-1",
            updated_at=10,
            content="摄影 场景",
            blocks=[{"blockId": "b", "text": "摄影 场景"}],
            provider="wikimedia",
            max_images=1,
            max_candidates=2,
        )
        service.search(**arguments)
        service.search(**arguments)
        self.assertEqual(len(service._session.calls), 1)

    def test_wikimedia_retries_a_shorter_query_when_literal_phrase_has_no_results(self):
        service = self.make_service(
            [
                FakeResponse(payload={"query": {"pages": []}}),
                FakeResponse(payload=wikimedia_payload()),
            ]
        )
        results = service._search_wikimedia(
            "AI productivity technology workspace",
            max_candidates=2,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(len(service._session.calls), 2)
        first_params = service._session.calls[0][1]["params"]
        retry_params = service._session.calls[1][1]["params"]
        self.assertEqual(
            first_params["gsrsearch"],
            "AI productivity technology workspace",
        )
        self.assertEqual(retry_params["gsrsearch"], "artificial intelligence")

    def test_wikimedia_excludes_candidates_without_explicit_license(self):
        payload = wikimedia_payload()
        del payload["query"]["pages"][0]["imageinfo"][0]["extmetadata"][
            "LicenseShortName"
        ]
        service = self.make_service([FakeResponse(payload=payload)])
        results = service._search_wikimedia("photography", max_candidates=2)
        self.assertEqual(results, [])

    def test_explicit_pexels_requires_server_key(self):
        service = self.make_service()
        with self.assertRaises(IllustrationValidationError) as raised:
            service.search(
                project_id="p",
                updated_at=1,
                content="正文",
                blocks=[{"blockId": "b", "text": "正文"}],
                provider="pexels",
                max_images=1,
                max_candidates=2,
            )
        self.assertEqual(raised.exception.code, "PEXELS_NOT_CONFIGURED")

    def test_redirect_to_non_allowlisted_host_is_blocked_before_followup_request(self):
        service = self.make_service(
            [
                FakeResponse(
                    status_code=302,
                    headers={"Location": "https://attacker.example/private.jpg"},
                )
            ]
        )
        with self.assertRaises(IllustrationSecurityError) as raised:
            service._download_image(
                "https://upload.wikimedia.org/safe.jpg",
                provider="wikimedia",
                maximum_bytes=1024,
            )
        self.assertEqual(raised.exception.code, "IMAGE_URL_BLOCKED")
        self.assertEqual(len(service._session.calls), 1)

    def test_download_checks_declared_and_streamed_size_limits(self):
        for response in (
            FakeResponse(
                headers={"Content-Type": "image/jpeg", "Content-Length": "2048"},
                raw=b"x",
            ),
            FakeResponse(
                headers={"Content-Type": "image/jpeg"},
                chunks=[b"x" * 700, b"y" * 700],
            ),
        ):
            service = self.make_service([response], max_bytes=1024)
            with self.subTest(headers=response.headers):
                with self.assertRaises(IllustrationSecurityError) as raised:
                    service._download_image(
                        "https://upload.wikimedia.org/safe.jpg",
                        provider="wikimedia",
                        maximum_bytes=1024,
                    )
                self.assertEqual(raised.exception.code, "IMAGE_TOO_LARGE")

    def test_svg_and_mime_mismatch_are_rejected(self):
        service = self.make_service(
            [
                FakeResponse(
                    headers={"Content-Type": "image/svg+xml"},
                    raw=b"<svg/>",
                )
            ]
        )
        with self.assertRaises(IllustrationSecurityError) as svg_error:
            service._download_image(
                "https://upload.wikimedia.org/unsafe.svg",
                provider="wikimedia",
                maximum_bytes=1024,
            )
        self.assertEqual(svg_error.exception.code, "IMAGE_TYPE_BLOCKED")
        with self.assertRaises(IllustrationSecurityError) as mismatch:
            sanitize_image(
                jpeg_bytes(),
                declared_mime_type="image/png",
                maximum_bytes=1024 * 1024,
            )
        self.assertEqual(mismatch.exception.code, "IMAGE_TYPE_MISMATCH")

    def test_image_is_reencoded_without_exif_metadata(self):
        raw = jpeg_bytes(exif=True)
        self.assertTrue(Image.open(io.BytesIO(raw)).getexif())
        clean, mime_type, width, height = sanitize_image(
            raw,
            declared_mime_type="image/jpeg",
            maximum_bytes=1024 * 1024,
        )
        decoded = Image.open(io.BytesIO(clean))
        self.assertEqual(mime_type, "image/jpeg")
        self.assertEqual((width, height), (8, 6))
        self.assertFalse(decoded.getexif())
        self.assertNotIn(b"private description", clean)

    def test_exif_orientation_is_applied_before_metadata_is_removed(self):
        clean, mime_type, width, height = sanitize_image(
            jpeg_bytes(orientation=6),
            declared_mime_type="image/jpeg",
            maximum_bytes=1024 * 1024,
        )
        decoded = Image.open(io.BytesIO(clean))
        self.assertEqual(mime_type, "image/jpeg")
        self.assertEqual((width, height), (6, 8))
        self.assertEqual(decoded.size, (6, 8))
        self.assertFalse(decoded.getexif())

    def test_import_returns_data_url_and_source_but_rejects_changed_revision(self):
        raw = jpeg_bytes()
        api_response = FakeResponse(payload=wikimedia_payload())
        image_response = FakeResponse(
            headers={"Content-Type": "image/jpeg", "Content-Length": str(len(raw))},
            raw=raw,
        )
        service = self.make_service([api_response, image_response])
        search = service.search(
            project_id="project-1",
            updated_at=10,
            content="人工智能平台",
            blocks=[{"blockId": "block-0", "text": "人工智能平台"}],
            provider="wikimedia",
            max_images=1,
            max_candidates=2,
        )
        candidate_id = search["candidates"][0]["id"]
        with self.assertRaises(IllustrationValidationError) as conflict:
            service.import_candidate(
                candidate_id,
                project_id="project-1",
                updated_at=11,
                content="人工智能平台",
            )
        self.assertEqual(conflict.exception.code, "DRAFT_VERSION_CONFLICT")
        imported = service.import_candidate(
            candidate_id,
            project_id="project-1",
            updated_at=10,
            content="人工智能平台",
        )
        self.assertEqual(imported["blockId"], "block-0")
        self.assertEqual(imported["asset"]["source"]["provider"], "wikimedia")
        prefix, encoded = imported["asset"]["dataUrl"].split(",", 1)
        self.assertEqual(prefix, "data:image/jpeg;base64")
        self.assertTrue(base64.b64decode(encoded))

    def test_url_validation_rejects_credentials_ports_http_and_unknown_hosts(self):
        for url in (
            "http://upload.wikimedia.org/a.jpg",
            "https://user:pass@upload.wikimedia.org/a.jpg",
            "https://upload.wikimedia.org:444/a.jpg",
            "https://127.0.0.1/a.jpg",
        ):
            with self.subTest(url=url):
                with self.assertRaises(IllustrationSecurityError):
                    validate_remote_url(
                        url,
                        allowed_hosts=frozenset({"upload.wikimedia.org"}),
                    )

    def test_provider_transport_error_does_not_leak_request_url_or_query(self):
        secret_query = "private-draft-secret"
        service = self.make_service([requests.ConnectionError("contains full request URL")])
        with self.assertRaises(Exception) as raised:
            service.search(
                project_id="p",
                updated_at=1,
                content=secret_query,
                blocks=[{"blockId": "b", "text": secret_query}],
                provider="wikimedia",
                max_images=1,
                max_candidates=2,
            )
        self.assertNotIn(secret_query, str(raised.exception))
        self.assertNotIn("commons.wikimedia.org", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
