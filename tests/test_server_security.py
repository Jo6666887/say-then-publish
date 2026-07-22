import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import server


class FakeCloudStore:
    enabled = True
    disabled_reason = ""

    def __init__(self):
        self.calls = 0
        self.config = SimpleNamespace(
            workspace_id="test-workspace",
            supabase_secret_key="supabase-test-secret",
            tos_access_key="tos-test-access",
            tos_secret_key="tos-test-secret",
        )

    def sync_store(self, store):
        self.calls += 1
        return json.loads(json.dumps(store))


class BlockingCloudStore(FakeCloudStore):
    def __init__(self):
        super().__init__()
        self.first_started = threading.Event()
        self.release_first = threading.Event()
        self.second_finished = threading.Event()
        self.synced_versions = []

    def sync_store(self, store):
        self.calls += 1
        checkpoint = server.project_checkpoint(store)
        self.synced_versions.append(checkpoint["updatedAt"])
        if self.calls == 1:
            self.first_started.set()
            if not self.release_first.wait(timeout=3):
                raise RuntimeError("test cloud release timed out")
        elif self.calls == 2:
            self.second_finished.set()
        return json.loads(json.dumps(store))


class FailingCloudStore(FakeCloudStore):
    def __init__(self, message):
        super().__init__()
        self.message = message

    def list_assets(self, _store):
        raise server.CloudStoreError(self.message)


def enabled_cloud_status():
    return {
        "enabled": True,
        "workspaceId": "test-workspace",
        "backend": "supabase+tos",
        "syncing": False,
        "syncingProjectId": None,
        "syncingUpdatedAt": None,
        "lastSuccessAt": None,
        "projectId": None,
        "syncedUpdatedAt": None,
        "lastError": None,
        "fallbackToLocal": False,
    }


class FakeAILayoutService:
    def __init__(self):
        self.calls = []

    def status(self):
        return {"enabled": True, "model": "test-model", "reason": None}

    def optimize(self, content, *, mode, accent_color):
        self.calls.append((content, mode, accent_color))
        return SimpleNamespace(
            as_dict=lambda: {
                "optimizedContent": f"## {content}",
                "changes": ["增加标题层级"],
                "model": "test-model",
            }
        )


class StaticFileBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = partial(server.WriteThenPublishHandler, directory=str(server.ROOT))
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        host, port = cls.httpd.server_address
        cls.base_url = f"http://{host}:{port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def request_status(self, path, *, method="GET", headers=None, data=None):
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            method=method,
            headers=headers or {},
            data=data,
        )
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def test_browser_assets_remain_available(self):
        for path in ("/", "/index.html", "/src/app.js", "/src/styles.css"):
            with self.subTest(path=path):
                status, body = self.request_status(path)
                self.assertEqual(status, 200)
                self.assertTrue(body)

    def test_sensitive_project_files_are_not_served(self):
        for path in (
            "/.env",
            "/.git/config",
            "/runtime-data/project-store.json",
            "/backups/anything.json",
            "/cloud_store.py",
            "/server.py",
            "/sql/20260722_write_then_publish_cloud.sql",
        ):
            with self.subTest(path=path):
                status, _ = self.request_status(path)
                self.assertEqual(status, 404)

    def test_encoded_dot_path_is_not_served(self):
        status, _ = self.request_status("/%2eenv")
        self.assertEqual(status, 404)

    def test_head_cannot_probe_sensitive_files(self):
        status, _ = self.request_status("/.env", method="HEAD")
        self.assertEqual(status, 404)

    def test_project_store_remains_api_only(self):
        status, body = self.request_status("/api/project-store")
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertIsInstance(payload.get("projects"), list)

    def test_cross_site_mutations_are_rejected(self):
        status, body = self.request_status(
            "/api/local-assets/select-directory",
            method="POST",
            headers={"Origin": "https://attacker.example", "Sec-Fetch-Site": "cross-site"},
            data=b"",
        )
        self.assertEqual(status, 403)
        self.assertIn("跨站", body.decode("utf-8"))

    def test_ai_status_is_public_but_contains_no_credentials(self):
        fake_ai = FakeAILayoutService()
        with mock.patch.object(server, "AI_LAYOUT", fake_ai):
            status, body = self.request_status("/api/ai/status")
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload, {"enabled": True, "model": "test-model", "reason": None})
        self.assertNotIn("key", body.decode("utf-8").lower())

    def test_ai_preview_requires_exact_saved_project_version_and_never_writes_result(self):
        fake_ai = FakeAILayoutService()
        store = {
            "activeId": "project-ai",
            "projects": [
                {
                    "id": "project-ai",
                    "title": "AI preview",
                    "updatedAt": 456789,
                    "data": {"content": "正文 [[image:image-1]]"},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            store_file = Path(temporary) / "project-store.json"
            store_file.write_text(json.dumps(store), encoding="utf-8")
            request_payload = {
                "projectId": "project-ai",
                "baseUpdatedAt": 456789,
                "content": "正文 [[image:image-1]]",
                "mode": "layout",
                "accentColor": "#5B5FEF",
            }
            with (
                mock.patch.object(server, "STORE_FILE", store_file),
                mock.patch.object(server, "AI_LAYOUT", fake_ai),
            ):
                status, body = self.request_status(
                    "/api/ai/optimize-layout",
                    method="POST",
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(request_payload).encode("utf-8"),
                )
                saved_after = json.loads(store_file.read_text(encoding="utf-8"))

        self.assertEqual(status, 200)
        response = json.loads(body.decode("utf-8"))
        self.assertEqual(response["optimizedContent"], "## 正文 [[image:image-1]]")
        self.assertEqual(response["baseUpdatedAt"], 456789)
        self.assertEqual(saved_after, store)
        self.assertEqual(fake_ai.calls, [("正文 [[image:image-1]]", "layout", "#5B5FEF")])

    def test_ai_preview_rejects_stale_version_before_provider_call(self):
        fake_ai = FakeAILayoutService()
        store = {
            "activeId": "project-ai",
            "projects": [{"id": "project-ai", "updatedAt": 10, "data": {"content": "新版"}}],
        }
        with tempfile.TemporaryDirectory() as temporary:
            store_file = Path(temporary) / "project-store.json"
            store_file.write_text(json.dumps(store), encoding="utf-8")
            with (
                mock.patch.object(server, "STORE_FILE", store_file),
                mock.patch.object(server, "AI_LAYOUT", fake_ai),
            ):
                status, body = self.request_status(
                    "/api/ai/optimize-layout",
                    method="POST",
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(
                        {
                            "projectId": "project-ai",
                            "baseUpdatedAt": 9,
                            "content": "旧版",
                            "mode": "layout",
                            "accentColor": "#5B5FEF",
                        }
                    ).encode("utf-8"),
                )
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body.decode("utf-8"))["code"], "DRAFT_VERSION_CONFLICT")
        self.assertEqual(fake_ai.calls, [])

    def test_ai_preview_rejects_malformed_mode_and_accent_color_without_calling_provider(self):
        fake_ai = FakeAILayoutService()
        store = {
            "activeId": "project-ai",
            "projects": [
                {
                    "id": "project-ai",
                    "updatedAt": 10,
                    "data": {"content": "正文"},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            store_file = Path(temporary) / "project-store.json"
            store_file.write_text(json.dumps(store), encoding="utf-8")
            with (
                mock.patch.object(server, "STORE_FILE", store_file),
                mock.patch.object(server, "AI_LAYOUT", fake_ai),
            ):
                for field, value, expected_code in (
                    ("mode", [], "INVALID_MODE"),
                    ("accentColor", {}, "INVALID_ACCENT_COLOR"),
                ):
                    payload = {
                        "projectId": "project-ai",
                        "baseUpdatedAt": 10,
                        "content": "正文",
                        "mode": "layout",
                        "accentColor": "#5B5FEF",
                    }
                    payload[field] = value
                    with self.subTest(field=field):
                        status, body = self.request_status(
                            "/api/ai/optimize-layout",
                            method="POST",
                            headers={"Content-Type": "application/json"},
                            data=json.dumps(payload).encode("utf-8"),
                        )
                        self.assertEqual(status, 400)
                        self.assertEqual(
                            json.loads(body.decode("utf-8"))["code"],
                            expected_code,
                        )
        self.assertEqual(fake_ai.calls, [])

    def test_project_store_put_returns_versioned_save_checkpoint(self):
        fake_cloud = FakeCloudStore()
        payload = {
            "activeId": "project-1",
            "projects": [
                {
                    "id": "project-1",
                    "title": "checkpoint",
                    "updatedAt": 123456,
                    "data": {"content": "saved"},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            store_file = Path(temporary) / "project-store.json"
            cloud_status = {
                "enabled": True,
                "workspaceId": "test-workspace",
                "backend": "supabase+tos",
                "syncing": False,
                "syncingProjectId": None,
                "syncingUpdatedAt": None,
                "lastSuccessAt": None,
                "projectId": None,
                "syncedUpdatedAt": None,
                "lastError": None,
                "fallbackToLocal": False,
            }
            with (
                mock.patch.object(server, "STORE_FILE", store_file),
                mock.patch.object(server, "CLOUD", fake_cloud),
                mock.patch.dict(server.CLOUD_STATUS, cloud_status, clear=True),
                mock.patch.object(server, "schedule_cloud_sync") as schedule,
            ):
                status, body = self.request_status(
                    "/api/project-store",
                    method="PUT",
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(payload).encode("utf-8"),
                )

        self.assertEqual(status, 200)
        response = json.loads(body.decode("utf-8"))
        self.assertEqual(response["activeId"], "project-1")
        self.assertEqual(response["projects"][0]["data"]["content"], "saved")
        self.assertEqual(response["saveMeta"]["projectId"], "project-1")
        self.assertEqual(response["saveMeta"]["savedUpdatedAt"], 123456)
        self.assertEqual(response["saveMeta"]["destination"], "local-server")
        self.assertTrue(response["saveMeta"]["cloudSyncScheduled"])
        schedule.assert_called_once()

    def test_project_store_put_rejects_older_or_equal_divergent_content(self):
        fake_cloud = FakeCloudStore()
        current = {
            "activeId": "project-1",
            "projects": [
                {
                    "id": "project-1",
                    "title": "current",
                    "updatedAt": 200,
                    "data": {"content": "服务器新版"},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            store_file = Path(temporary) / "project-store.json"
            with (
                mock.patch.object(server, "STORE_FILE", store_file),
                mock.patch.object(server, "CLOUD", fake_cloud),
                mock.patch.dict(server.CLOUD_STATUS, enabled_cloud_status(), clear=True),
                mock.patch.object(server, "schedule_cloud_sync") as schedule,
            ):
                for updated_at in (199, 200):
                    store_file.write_text(json.dumps(current), encoding="utf-8")
                    incoming = {
                        "activeId": "project-1",
                        "projects": [
                            {
                                "id": "project-1",
                                "title": "stale",
                                "updatedAt": updated_at,
                                "data": {"content": "旧正文"},
                            }
                        ],
                    }
                    with self.subTest(updated_at=updated_at):
                        status, body = self.request_status(
                            "/api/project-store",
                            method="PUT",
                            headers={"Content-Type": "application/json"},
                            data=json.dumps(incoming).encode("utf-8"),
                        )
                        self.assertEqual(status, 409)
                        self.assertEqual(
                            json.loads(body.decode("utf-8"))["code"],
                            "DRAFT_VERSION_CONFLICT",
                        )
                        self.assertEqual(
                            json.loads(store_file.read_text(encoding="utf-8")),
                            current,
                        )
                schedule.assert_not_called()

    def test_project_store_put_accepts_a_strictly_newer_revision(self):
        fake_cloud = FakeCloudStore()
        current = {
            "activeId": "project-1",
            "projects": [
                {"id": "project-1", "updatedAt": 200, "data": {"content": "旧正文"}}
            ],
        }
        incoming = {
            "activeId": "project-1",
            "projects": [
                {"id": "project-1", "updatedAt": 201, "data": {"content": "新正文"}}
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            store_file = Path(temporary) / "project-store.json"
            store_file.write_text(json.dumps(current), encoding="utf-8")
            with (
                mock.patch.object(server, "STORE_FILE", store_file),
                mock.patch.object(server, "CLOUD", fake_cloud),
                mock.patch.dict(server.CLOUD_STATUS, enabled_cloud_status(), clear=True),
                mock.patch.object(server, "schedule_cloud_sync") as schedule,
            ):
                status, body = self.request_status(
                    "/api/project-store",
                    method="PUT",
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(incoming).encode("utf-8"),
                )

        self.assertEqual(status, 200)
        response = json.loads(body.decode("utf-8"))
        self.assertTrue(response["saveMeta"]["saved"])
        self.assertEqual(response["saveMeta"]["savedUpdatedAt"], 201)
        self.assertEqual(response["projects"][0]["data"]["content"], "新正文")
        schedule.assert_called_once()

    def test_current_text_patch_rejects_conflicts_and_accepts_newer_revision(self):
        fake_cloud = FakeCloudStore()
        current = {
            "activeId": "project-1",
            "projects": [
                {"id": "project-1", "updatedAt": 200, "data": {"content": "服务器新版"}}
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            store_file = Path(temporary) / "project-store.json"
            with (
                mock.patch.object(server, "STORE_FILE", store_file),
                mock.patch.object(server, "CLOUD", fake_cloud),
                mock.patch.dict(server.CLOUD_STATUS, enabled_cloud_status(), clear=True),
                mock.patch.object(server, "schedule_cloud_sync") as schedule,
            ):
                for updated_at in (199, 200):
                    store_file.write_text(json.dumps(current), encoding="utf-8")
                    with self.subTest(updated_at=updated_at):
                        status, body = self.request_status(
                            "/api/project-store/current-text",
                            method="PATCH",
                            headers={"Content-Type": "application/json"},
                            data=json.dumps(
                                {
                                    "id": "project-1",
                                    "updatedAt": updated_at,
                                    "content": "旧正文",
                                }
                            ).encode("utf-8"),
                        )
                        self.assertEqual(status, 409)
                        self.assertEqual(
                            json.loads(body.decode("utf-8"))["code"],
                            "DRAFT_VERSION_CONFLICT",
                        )
                        self.assertEqual(
                            json.loads(store_file.read_text(encoding="utf-8")),
                            current,
                        )

                store_file.write_text(json.dumps(current), encoding="utf-8")
                status, body = self.request_status(
                    "/api/project-store/current-text",
                    method="PATCH",
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(
                        {
                            "id": "project-1",
                            "updatedAt": 201,
                            "content": "真正新正文",
                        }
                    ).encode("utf-8"),
                )
                saved = json.loads(store_file.read_text(encoding="utf-8"))

        self.assertEqual(status, 200)
        response = json.loads(body.decode("utf-8"))
        self.assertEqual(response["saveMeta"]["savedUpdatedAt"], 201)
        self.assertEqual(saved["projects"][0]["updatedAt"], 201)
        self.assertEqual(saved["projects"][0]["data"]["content"], "真正新正文")
        schedule.assert_called_once()

    def test_cloud_asset_error_response_redacts_credentials(self):
        leaked = "supabase-test-secret tos-test-access tos-test-secret"
        fake_cloud = FailingCloudStore(leaked)
        with (
            mock.patch.object(server, "CLOUD", fake_cloud),
            mock.patch.dict(server.CLOUD_STATUS, enabled_cloud_status(), clear=True),
            mock.patch.object(
                server,
                "local_asset_library_payload",
                side_effect=lambda reason=None: {"reason": reason},
            ),
        ):
            status, body = self.request_status("/api/assets")

        self.assertEqual(status, 200)
        response_text = body.decode("utf-8")
        self.assertNotIn("supabase-test-secret", response_text)
        self.assertNotIn("tos-test-access", response_text)
        self.assertNotIn("tos-test-secret", response_text)
        self.assertIn("[REDACTED]", response_text)


class CloudCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.status = enabled_cloud_status()

    def test_cloud_checkpoint_requires_the_exact_revision(self):
        status = {
            **self.status,
            "projectId": "project-1",
            "syncedUpdatedAt": 500,
        }

        self.assertTrue(server.checkpoint_is_confirmed(status, "project-1", 500))
        self.assertFalse(server.checkpoint_is_confirmed(status, "project-1", 499))
        self.assertFalse(server.checkpoint_is_confirmed(status, "project-1", 501))

    def test_cloud_status_records_synced_project_version(self):
        fake_cloud = FakeCloudStore()
        store = {
            "activeId": "project-1",
            "projects": [
                {
                    "id": "project-1",
                    "updatedAt": 789,
                    "title": "cloud",
                    "data": {"content": "latest"},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            store_file = Path(temporary) / "project-store.json"
            store_file.write_text(json.dumps(store), encoding="utf-8")
            with (
                mock.patch.object(server, "STORE_FILE", store_file),
                mock.patch.object(server, "CLOUD", fake_cloud),
                mock.patch.dict(server.CLOUD_STATUS, self.status, clear=True),
            ):
                self.assertTrue(server.sync_cloud_store())
                status = server.cloud_status()

        self.assertEqual(fake_cloud.calls, 1)
        self.assertEqual(status["projectId"], "project-1")
        self.assertEqual(status["syncedUpdatedAt"], 789)
        self.assertIsNotNone(status["lastSuccessAt"])
        self.assertFalse(status["fallbackToLocal"])

    def test_manual_sync_waits_for_and_reuses_confirmed_background_result(self):
        fake_cloud = FakeCloudStore()
        results = []
        with (
            mock.patch.object(server, "CLOUD", fake_cloud),
            mock.patch.dict(server.CLOUD_STATUS, self.status, clear=True),
        ):
            self.assertTrue(server.CLOUD_SYNC_LOCK.acquire(blocking=False))
            worker = threading.Thread(
                target=lambda: results.append(
                    server.sync_cloud_store(
                        wait_for_existing=True,
                        target_project_id="project-1",
                        target_updated_at=500,
                        wait_timeout=1,
                    )
                )
            )
            try:
                worker.start()
                time.sleep(0.05)
                self.assertTrue(worker.is_alive())
                with server.CLOUD_STATUS_LOCK:
                    server.CLOUD_STATUS.update(
                        {
                            "projectId": "project-1",
                            "syncedUpdatedAt": 500,
                            "lastSuccessAt": server.datetime_now_iso(),
                            "lastError": None,
                            "fallbackToLocal": False,
                        }
                    )
            finally:
                server.CLOUD_SYNC_LOCK.release()
                worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(results, [True])
        self.assertEqual(fake_cloud.calls, 0)

    def test_scheduled_sync_waits_behind_busy_lock_and_flushes_latest_revision(self):
        fake_cloud = BlockingCloudStore()
        first_store = {
            "activeId": "project-1",
            "projects": [
                {"id": "project-1", "updatedAt": 1, "data": {"content": "first"}}
            ],
        }
        second_store = {
            "activeId": "project-1",
            "projects": [
                {"id": "project-1", "updatedAt": 2, "data": {"content": "second"}}
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            store_file = Path(temporary) / "project-store.json"
            store_file.write_text(json.dumps(first_store), encoding="utf-8")
            first_worker = threading.Thread(target=server.sync_cloud_store)
            with (
                mock.patch.object(server, "STORE_FILE", store_file),
                mock.patch.object(server, "CLOUD", fake_cloud),
                mock.patch.dict(server.CLOUD_STATUS, self.status, clear=True),
                mock.patch.object(server, "CLOUD_SYNC_TIMER", None),
                mock.patch.object(server, "CLOUD_SYNC_PENDING", False),
                mock.patch.object(server, "CLOUD_SYNC_WORKER_ACTIVE", False),
            ):
                try:
                    first_worker.start()
                    self.assertTrue(fake_cloud.first_started.wait(timeout=1))
                    with server.STORE_LOCK:
                        server.write_store(second_store)
                    server.schedule_cloud_sync(delay=0.01)
                    time.sleep(0.05)
                    fake_cloud.release_first.set()
                    self.assertTrue(fake_cloud.second_finished.wait(timeout=2))
                    first_worker.join(timeout=2)
                    deadline = time.monotonic() + 2
                    while server.CLOUD_SYNC_WORKER_ACTIVE and time.monotonic() < deadline:
                        time.sleep(0.01)
                finally:
                    fake_cloud.release_first.set()
                    server.cancel_scheduled_cloud_sync()
                    first_worker.join(timeout=2)

                self.assertFalse(first_worker.is_alive())
                self.assertFalse(server.CLOUD_SYNC_WORKER_ACTIVE)

        self.assertEqual(fake_cloud.synced_versions[:2], [1, 2])
        self.assertEqual(fake_cloud.calls, 2)

    def test_cloud_errors_redact_all_configured_credentials(self):
        fake_cloud = FakeCloudStore()
        leaked = "supabase-test-secret tos-test-access tos-test-secret"
        with (
            mock.patch.object(server, "CLOUD", fake_cloud),
            mock.patch.dict(server.CLOUD_STATUS, self.status, clear=True),
        ):
            server.record_cloud_failure(RuntimeError(leaked))
            status = server.cloud_status()

        self.assertNotIn("supabase-test-secret", status["lastError"])
        self.assertNotIn("tos-test-access", status["lastError"])
        self.assertNotIn("tos-test-secret", status["lastError"])
        self.assertIn("[REDACTED]", status["lastError"])


if __name__ == "__main__":
    unittest.main()
