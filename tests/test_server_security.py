import base64
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
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
        self.deleted_projects = []
        self.config = SimpleNamespace(
            workspace_id="test-workspace",
            supabase_secret_key="supabase-test-secret",
            tos_access_key="tos-test-access",
            tos_secret_key="tos-test-secret",
        )

    def sync_store(self, store):
        self.calls += 1
        return json.loads(json.dumps(store))

    def delete_project(self, project_id, deleted_at, *, active_id=None):
        self.deleted_projects.append((project_id, deleted_at, active_id))
        return deleted_at


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


class FakeIllustrationService:
    def __init__(self):
        self.search_calls = []
        self.import_calls = []
        self.preview_calls = []

    def status(self):
        return {
            "ok": True,
            "enabled": True,
            "providers": [
                {
                    "id": "wikimedia",
                    "label": "Wikimedia Commons",
                    "enabled": True,
                    "requiresKey": False,
                }
            ],
            "limits": {"maxImages": 3, "maxCandidates": 4, "maxImageBytes": 1024},
            "ai": {"enabled": False, "model": None},
            "message": "test",
        }

    def search(self, **kwargs):
        self.search_calls.append(kwargs)
        return {
            "ok": True,
            "plan": {
                "source": "fallback",
                "items": [
                    {
                        "blockId": "block-0",
                        "query": "正文",
                        "reason": "主题",
                    }
                ],
            },
            "candidates": [
                {
                    "id": "a" * 32,
                    "blockId": "block-0",
                    "provider": "wikimedia",
                    "title": "候选",
                    "thumbnailUrl": "/api/illustrations/candidates/" + "a" * 32 + "/preview",
                    "previewUrl": "/api/illustrations/candidates/" + "a" * 32 + "/preview",
                    "sourcePageUrl": "https://commons.wikimedia.org/wiki/File:Safe.jpg",
                    "creator": "Alice",
                    "license": "CC BY-SA 4.0",
                    "licenseUrl": "https://creativecommons.org/licenses/by-sa/4.0/",
                    "width": 100,
                    "height": 80,
                }
            ],
            "expiresAt": "2099-01-01T00:00:00+00:00",
        }

    def import_candidate(self, candidate_id, **kwargs):
        self.import_calls.append((candidate_id, kwargs))
        return {
            "ok": True,
            "blockId": "block-0",
            "asset": {
                "dataUrl": "data:image/png;base64,aW1hZ2U=",
                "mimeType": "image/png",
                "byteSize": 5,
                "width": 1,
                "height": 1,
                "source": {
                    "provider": "wikimedia",
                    "title": "候选",
                    "sourcePageUrl": "https://commons.wikimedia.org/wiki/File:Safe.jpg",
                    "creator": "Alice",
                    "license": "CC BY-SA 4.0",
                    "licenseUrl": "https://creativecommons.org/licenses/by-sa/4.0/",
                },
            },
        }

    def preview(self, candidate_id):
        self.preview_calls.append(candidate_id)
        return b"image", "image/png"


@contextmanager
def running_configured_server(config):
    handler = partial(server.WriteThenPublishHandler, directory=str(server.ROOT))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    httpd.runtime_config = config
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    try:
        yield httpd, f"http://{host}:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def basic_auth_header(username="editor", password="correct horse"):
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


class RuntimeSecurityConfigurationTests(unittest.TestCase):
    def test_default_runtime_keeps_current_loopback_behavior(self):
        config = server.ServerRuntimeConfig.from_env({})

        config.validate()
        self.assertEqual(config.bind_host, "127.0.0.1")
        self.assertEqual(config.port, 5173)
        self.assertEqual(config.allowed_hosts, ("127.0.0.1", "localhost", "::1"))
        self.assertEqual(config.app_url, "http://127.0.0.1:5173/")
        self.assertTrue(config.open_browser)
        self.assertFalse(config.basic_auth_enabled)
        self.assertFalse(config.tls_enabled)

    def test_non_loopback_requires_explicit_host_auth_and_tls(self):
        cases = (
            (
                {
                    "WTP_BIND_HOST": "0.0.0.0",
                    "WTP_BASIC_AUTH_USER": "editor",
                    "WTP_BASIC_AUTH_PASSWORD": "secret",
                    "WTP_ALLOW_INSECURE_HTTP": "1",
                },
                "WTP_ALLOWED_HOSTS",
            ),
            (
                {
                    "WTP_BIND_HOST": "0.0.0.0",
                    "WTP_ALLOWED_HOSTS": "203.0.113.8",
                    "WTP_ALLOW_INSECURE_HTTP": "1",
                },
                "Basic Auth",
            ),
            (
                {
                    "WTP_BIND_HOST": "0.0.0.0",
                    "WTP_ALLOWED_HOSTS": "203.0.113.8",
                    "WTP_BASIC_AUTH_USER": "editor",
                    "WTP_BASIC_AUTH_PASSWORD": "secret",
                },
                "TLS",
            ),
        )
        for environ, expected in cases:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(ValueError, expected):
                    server.ServerRuntimeConfig.from_env(environ).validate()

    def test_explicit_insecure_override_is_allowed_only_with_host_and_auth(self):
        config = server.ServerRuntimeConfig.from_env(
            {
                "WTP_BIND_HOST": "0.0.0.0",
                "WTP_PORT": "8517",
                "WTP_ALLOWED_HOSTS": "203.0.113.8",
                "WTP_BASIC_AUTH_USER": "editor",
                "WTP_BASIC_AUTH_PASSWORD": "secret",
                "WTP_ALLOW_INSECURE_HTTP": "1",
                "WTP_OPEN_BROWSER": "0",
            }
        )

        config.validate()
        self.assertEqual(config.port, 8517)
        self.assertEqual(config.app_url, "http://203.0.113.8:8517/")
        self.assertEqual(config.health_url, "http://127.0.0.1:8517/api/health")
        self.assertFalse(config.open_browser)

    def test_specific_public_bind_must_appear_in_allowed_hosts(self):
        config = server.ServerRuntimeConfig.from_env(
            {
                "WTP_BIND_HOST": "203.0.113.8",
                "WTP_ALLOWED_HOSTS": "app.example.test",
                "WTP_BASIC_AUTH_USER": "editor",
                "WTP_BASIC_AUTH_PASSWORD": "secret",
                "WTP_ALLOW_INSECURE_HTTP": "1",
            }
        )

        with self.assertRaisesRegex(ValueError, "WTP_BIND_HOST"):
            config.validate()

    def test_tls_files_must_be_paired_and_exist(self):
        with tempfile.TemporaryDirectory() as temporary:
            cert = Path(temporary) / "server.crt"
            key = Path(temporary) / "server.key"
            cert.write_text("certificate", encoding="utf-8")
            key.write_text("key", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "同时配置"):
                server.ServerRuntimeConfig.from_env(
                    {"WTP_TLS_CERT_FILE": str(cert)}
                ).validate()

            config = server.ServerRuntimeConfig.from_env(
                {
                    "WTP_BIND_HOST": "0.0.0.0",
                    "WTP_PORT": "8517",
                    "WTP_ALLOWED_HOSTS": "203.0.113.8",
                    "WTP_BASIC_AUTH_USER": "editor",
                    "WTP_BASIC_AUTH_PASSWORD": "secret",
                    "WTP_TLS_CERT_FILE": str(cert),
                    "WTP_TLS_KEY_FILE": str(key),
                }
            )
            config.validate()
            self.assertEqual(config.app_url, "https://203.0.113.8:8517/")
            self.assertEqual(config.health_url, "https://127.0.0.1:8517/api/health")

    def test_invalid_ports_booleans_and_wildcard_hosts_are_rejected(self):
        for environ in (
            {"WTP_PORT": "0"},
            {"WTP_PORT": "not-a-port"},
            {"WTP_OPEN_BROWSER": "sometimes"},
            {"WTP_ALLOWED_HOSTS": "*"},
            {"WTP_ALLOWED_HOSTS": "example.test:8517"},
        ):
            with self.subTest(environ=environ):
                with self.assertRaises(ValueError):
                    server.ServerRuntimeConfig.from_env(environ)

    def test_create_runtime_server_uses_configured_bind_port_and_tls_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            cert = Path(temporary) / "server.crt"
            key = Path(temporary) / "server.key"
            cert.write_text("certificate", encoding="utf-8")
            key.write_text("key", encoding="utf-8")
            config = server.ServerRuntimeConfig.from_env(
                {
                    "WTP_BIND_HOST": "0.0.0.0",
                    "WTP_PORT": "8517",
                    "WTP_ALLOWED_HOSTS": "203.0.113.8",
                    "WTP_BASIC_AUTH_USER": "editor",
                    "WTP_BASIC_AUTH_PASSWORD": "secret",
                    "WTP_TLS_CERT_FILE": str(cert),
                    "WTP_TLS_KEY_FILE": str(key),
                }
            )
            fake_httpd = SimpleNamespace(socket=object(), runtime_config=None)
            fake_context = mock.Mock()
            fake_context.wrap_socket.return_value = "tls-socket"
            with (
                mock.patch.object(
                    server,
                    "ThreadingHTTPServer",
                    return_value=fake_httpd,
                ) as factory,
                mock.patch.object(
                    server.ssl,
                    "SSLContext",
                    return_value=fake_context,
                ) as context_factory,
            ):
                result = server.create_runtime_server(config, object())

        self.assertIs(result, fake_httpd)
        factory.assert_called_once_with(("0.0.0.0", 8517), mock.ANY)
        context_factory.assert_called_once_with(server.ssl.PROTOCOL_TLS_SERVER)
        fake_context.load_cert_chain.assert_called_once_with(
            certfile=str(config.tls_cert_file),
            keyfile=str(config.tls_key_file),
        )
        fake_context.wrap_socket.assert_called_once_with(mock.ANY, server_side=True)
        self.assertEqual(fake_httpd.socket, "tls-socket")
        self.assertIs(fake_httpd.runtime_config, config)

    def test_configured_https_health_probe_uses_port_host_auth_and_local_context(self):
        config = server.ServerRuntimeConfig(
            bind_host="0.0.0.0",
            port=8517,
            allowed_hosts=("203.0.113.8",),
            allowed_hosts_explicit=True,
            open_browser=False,
            basic_auth_user="editor",
            basic_auth_password="secret",
            tls_cert_file=Path("/test/server.crt"),
            tls_key_file=Path("/test/server.key"),
            allow_insecure_http=False,
        )
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"ok": True, "service": "write-then-publish", "schema": 1}
        ).encode("utf-8")
        context = object()
        opener = mock.Mock()
        opener.open.return_value = response
        https_handler = object()
        with (
            mock.patch.object(
                server.ssl,
                "_create_unverified_context",
                return_value=context,
            ),
            mock.patch.object(
                server.urllib.request,
                "HTTPSHandler",
                return_value=https_handler,
            ) as handler_factory,
            mock.patch.object(
                server.urllib.request,
                "build_opener",
                return_value=opener,
            ) as build_opener,
        ):
            healthy = server.existing_app_is_healthy(config)

        self.assertTrue(healthy)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://127.0.0.1:8517/api/health")
        self.assertEqual(request.get_header("Host"), "203.0.113.8:8517")
        self.assertTrue(request.get_header("Authorization").startswith("Basic "))
        handler_factory.assert_called_once_with(context=context)
        self.assertIn(
            https_handler,
            build_opener.call_args.args,
        )
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 2)

    def test_basic_auth_protects_static_and_api_but_loopback_health_is_exempt(self):
        config = self.authenticated_loopback_config()
        with running_configured_server(config) as (_, base_url):
            for path, method, data in (
                ("/", "GET", None),
                ("/api/project-store", "GET", None),
                ("/api/cloud-sync", "POST", b"{}"),
            ):
                request = urllib.request.Request(
                    f"{base_url}{path}",
                    method=method,
                    data=data,
                    headers={"Content-Type": "application/json"} if data else {},
                )
                with self.subTest(path=path):
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(request, timeout=3)
                    self.assertEqual(caught.exception.code, 401)
                    self.assertIn(
                        "Basic",
                        caught.exception.headers.get("WWW-Authenticate", ""),
                    )

            authenticated = urllib.request.Request(
                f"{base_url}/",
                headers=basic_auth_header(),
            )
            with urllib.request.urlopen(authenticated, timeout=3) as response:
                self.assertEqual(response.status, 200)

            for method in ("GET", "HEAD"):
                health = urllib.request.Request(
                    f"{base_url}/api/health",
                    method=method,
                )
                with urllib.request.urlopen(health, timeout=3) as response:
                    self.assertEqual(response.status, 200)
                    if method == "HEAD":
                        self.assertEqual(response.read(), b"")

    def test_remote_health_requires_auth_and_malformed_basic_never_leaks_credentials(self):
        config = self.authenticated_loopback_config()
        with (
            running_configured_server(config) as (_, base_url),
            mock.patch.object(
                server,
                "client_address_is_loopback",
                return_value=False,
            ),
        ):
            for authorization in (
                "",
                "Basic !!!",
                "Basic " + base64.b64encode(b"editor:wrong").decode(),
                "Basic "
                + base64.b64encode("编辑者:错误".encode("utf-8")).decode("ascii"),
            ):
                request = urllib.request.Request(
                    f"{base_url}/api/health",
                    headers={"Authorization": authorization} if authorization else {},
                )
                with self.subTest(authorization=authorization):
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(request, timeout=3)
                    body = caught.exception.read().decode("utf-8")
                    self.assertEqual(caught.exception.code, 401)
                    self.assertNotIn("editor", body)
                    self.assertNotIn("correct horse", body)

            request = urllib.request.Request(
                f"{base_url}/api/health",
                headers=basic_auth_header(),
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                self.assertEqual(response.status, 200)

    def test_strict_host_allows_exact_entry_and_rejects_missing_or_wrong_port(self):
        config = server.ServerRuntimeConfig(
            bind_host="127.0.0.1",
            port=5173,
            allowed_hosts=("public.example.test",),
            allowed_hosts_explicit=True,
            open_browser=False,
            basic_auth_user="editor",
            basic_auth_password="correct horse",
            tls_cert_file=None,
            tls_key_file=None,
            allow_insecure_http=False,
        )
        with running_configured_server(config) as (httpd, base_url):
            port = httpd.server_port
            valid_headers = {
                **basic_auth_header(),
                "Host": f"public.example.test:{port}",
            }
            request = urllib.request.Request(f"{base_url}/", headers=valid_headers)
            with urllib.request.urlopen(request, timeout=3) as response:
                self.assertEqual(response.status, 200)

            for host in (
                "public.example.test",
                f"public.example.test:{port + 1}",
                f"attacker.example:{port}",
                f"user@public.example.test:{port}",
                "[invalid-ipv6",
            ):
                request = urllib.request.Request(
                    f"{base_url}/",
                    headers={**basic_auth_header(), "Host": host},
                )
                with self.subTest(host=host):
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(request, timeout=3)
                    self.assertEqual(caught.exception.code, 403)

    @staticmethod
    def authenticated_loopback_config():
        return server.ServerRuntimeConfig(
            bind_host="127.0.0.1",
            port=5173,
            allowed_hosts=("127.0.0.1",),
            allowed_hosts_explicit=True,
            open_browser=False,
            basic_auth_user="editor",
            basic_auth_password="correct horse",
            tls_cert_file=None,
            tls_key_file=None,
            allow_insecure_http=False,
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

    def request_status(self, path, *, method="GET", headers=None, data=None, timeout=3):
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            method=method,
            headers=headers or {},
            data=data,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def test_browser_assets_remain_available(self):
        for path in ("/", "/index.html", "/src/app.js", "/src/styles.css"):
            with self.subTest(path=path):
                status, body = self.request_status(path)
                self.assertEqual(status, 200)
                self.assertTrue(body)

    def test_health_endpoint_identifies_this_service(self):
        status, body = self.request_status("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(
            json.loads(body.decode("utf-8")),
            {"ok": True, "service": "write-then-publish", "schema": 1},
        )

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

    def test_write_env_updates_merges_and_preserves_comments(self):
        import pathlib
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / ".env"
            path.write_text("# keep me\nTOS_BUCKET=old\nSUPABASE_URL=u\n", encoding="utf-8")
            server.write_env_updates(path, {"TOS_BUCKET": "new", "TOS_KEY_PREFIX": "cards/"})
            text = path.read_text(encoding="utf-8")
            resolved = server.read_env_file_map(path)
            self.assertEqual(resolved["TOS_BUCKET"], "new")
            self.assertEqual(resolved["SUPABASE_URL"], "u")
            self.assertEqual(resolved["TOS_KEY_PREFIX"], "cards/")
            self.assertIn("# keep me", text)

    def test_settings_env_status_never_returns_secret_values(self):
        status, body = self.request_status("/api/settings/env-status")
        self.assertEqual(status, 200)
        fields = json.loads(body.decode("utf-8"))["fields"]
        for group in fields.values():
            for key, info in group.items():
                self.assertIn("configured", info)
                if key in server.SETTINGS_ENV_SECRET:
                    self.assertNotIn("value", info)

    def test_settings_env_rejects_unknown_key(self):
        data = json.dumps({"values": {"PATH": "/tmp"}}).encode("utf-8")
        status, _ = self.request_status(
            "/api/settings/env", method="POST", headers={"Content-Type": "application/json"}, data=data
        )
        self.assertEqual(status, 400)

    def test_settings_env_rejects_newline_injection(self):
        data = json.dumps({"values": {"TOS_BUCKET": "a\nSUPABASE_SECRET_KEY=leak"}}).encode("utf-8")
        status, _ = self.request_status(
            "/api/settings/env", method="POST", headers={"Content-Type": "application/json"}, data=data
        )
        self.assertEqual(status, 400)

    def test_settings_env_write_targets_only_whitelisted_keys(self):
        import pathlib
        import tempfile

        original = server.ENV_PATH
        with tempfile.TemporaryDirectory() as directory:
            server.ENV_PATH = pathlib.Path(directory) / ".env"
            server.ENV_PATH.write_text("# comment\nTOS_BUCKET=old\n", encoding="utf-8")
            try:
                data = json.dumps({"values": {"TOS_BUCKET": "new-bucket"}}).encode("utf-8")
                status, _ = self.request_status(
                    "/api/settings/env", method="POST", headers={"Content-Type": "application/json"}, data=data
                )
                self.assertEqual(status, 200)
                text = server.ENV_PATH.read_text(encoding="utf-8")
                self.assertIn("TOS_BUCKET=new-bucket", text)
                self.assertIn("# comment", text)
            finally:
                server.ENV_PATH = original

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

    def test_dns_rebinding_host_is_rejected_for_reads_and_mutations(self):
        port = urllib.parse.urlparse(self.base_url).port
        headers = {
            "Host": f"attacker.example:{port}",
            "Origin": f"http://attacker.example:{port}",
        }
        status, body = self.request_status("/api/project-store", headers=headers)
        self.assertEqual(status, 403)
        self.assertIn("Host", body.decode("utf-8"))

        status, body = self.request_status(
            "/api/illustrations/search",
            method="POST",
            headers={**headers, "Content-Type": "application/json"},
            data=b"{}",
        )
        self.assertEqual(status, 403)
        self.assertIn("Host", body.decode("utf-8"))

    def test_ai_status_is_public_but_contains_no_credentials(self):
        fake_ai = FakeAILayoutService()
        with mock.patch.object(server, "AI_LAYOUT", fake_ai):
            status, body = self.request_status("/api/ai/status")
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload, {"enabled": True, "model": "test-model", "reason": None})
        self.assertNotIn("key", body.decode("utf-8").lower())

    def test_illustration_status_is_public_but_contains_no_credentials(self):
        fake_service = FakeIllustrationService()
        with mock.patch.object(server, "ILLUSTRATIONS", fake_service):
            status, body = self.request_status("/api/illustrations/status")
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertTrue(payload["enabled"])
        self.assertNotIn("apiKey", body.decode("utf-8"))
        self.assertNotIn("secret", body.decode("utf-8").lower())

    def test_illustration_search_requires_exact_saved_revision_and_never_writes_store(self):
        fake_service = FakeIllustrationService()
        store = {
            "activeId": "project-image",
            "projects": [
                {
                    "id": "project-image",
                    "updatedAt": 456789,
                    "data": {"content": "# 正文"},
                }
            ],
        }
        request_payload = {
            "projectId": "project-image",
            "baseUpdatedAt": 456789,
            "content": "# 正文",
            "blocks": [{"blockId": "block-0", "text": "# 正文"}],
            "provider": "wikimedia",
            "maxImages": 1,
            "maxCandidates": 2,
        }
        with tempfile.TemporaryDirectory() as temporary:
            store_file = Path(temporary) / "project-store.json"
            store_file.write_text(json.dumps(store), encoding="utf-8")
            with (
                mock.patch.object(server, "STORE_FILE", store_file),
                mock.patch.object(server, "ILLUSTRATIONS", fake_service),
            ):
                status, body = self.request_status(
                    "/api/illustrations/search",
                    method="POST",
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(request_payload).encode("utf-8"),
                )
                saved_after = json.loads(store_file.read_text(encoding="utf-8"))
        self.assertEqual(status, 200)
        response = json.loads(body.decode("utf-8"))
        self.assertEqual(response["baseUpdatedAt"], 456789)
        self.assertEqual(response["candidates"][0]["blockId"], "block-0")
        self.assertEqual(saved_after, store)
        self.assertEqual(fake_service.search_calls[0]["content"], "# 正文")

    def test_illustration_search_rejects_stale_content_before_provider_call(self):
        fake_service = FakeIllustrationService()
        store = {
            "activeId": "project-image",
            "projects": [
                {
                    "id": "project-image",
                    "updatedAt": 20,
                    "data": {"content": "服务器新版"},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            store_file = Path(temporary) / "project-store.json"
            store_file.write_text(json.dumps(store), encoding="utf-8")
            with (
                mock.patch.object(server, "STORE_FILE", store_file),
                mock.patch.object(server, "ILLUSTRATIONS", fake_service),
            ):
                status, body = self.request_status(
                    "/api/illustrations/search",
                    method="POST",
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(
                        {
                            "projectId": "project-image",
                            "baseUpdatedAt": 20,
                            "content": "浏览器旧版",
                            "blocks": [{"blockId": "block-0", "text": "浏览器旧版"}],
                        }
                    ).encode("utf-8"),
                )
        self.assertEqual(status, 409)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "DRAFT_VERSION_CONFLICT")
        self.assertEqual(fake_service.search_calls, [])

    def test_illustration_import_returns_data_only_and_never_writes_store(self):
        fake_service = FakeIllustrationService()
        store = {
            "activeId": "project-image",
            "projects": [
                {
                    "id": "project-image",
                    "updatedAt": 30,
                    "data": {"content": "正文"},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            store_file = Path(temporary) / "project-store.json"
            store_file.write_text(json.dumps(store), encoding="utf-8")
            with (
                mock.patch.object(server, "STORE_FILE", store_file),
                mock.patch.object(server, "ILLUSTRATIONS", fake_service),
            ):
                status, body = self.request_status(
                    "/api/illustrations/import",
                    method="POST",
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(
                        {
                            "projectId": "project-image",
                            "baseUpdatedAt": 30,
                            "content": "正文",
                            "candidateId": "a" * 32,
                        }
                    ).encode("utf-8"),
                )
                saved_after = json.loads(store_file.read_text(encoding="utf-8"))
        self.assertEqual(status, 200)
        response = json.loads(body.decode("utf-8"))
        self.assertTrue(response["asset"]["dataUrl"].startswith("data:image/png;base64,"))
        self.assertEqual(saved_after, store)
        self.assertEqual(fake_service.import_calls[0][0], "a" * 32)

    def test_illustration_import_rechecks_revision_after_remote_download(self):
        store = {
            "activeId": "project-image",
            "projects": [
                {
                    "id": "project-image",
                    "updatedAt": 30,
                    "data": {"content": "正文"},
                }
            ],
        }
        newer_store = {
            "activeId": "project-image",
            "projects": [
                {
                    "id": "project-image",
                    "updatedAt": 31,
                    "data": {"content": "另一台浏览器保存的新正文"},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            store_file = Path(temporary) / "project-store.json"
            store_file.write_text(json.dumps(store), encoding="utf-8")

            class RacingIllustrationService(FakeIllustrationService):
                def import_candidate(self, candidate_id, **kwargs):
                    result = super().import_candidate(candidate_id, **kwargs)
                    store_file.write_text(json.dumps(newer_store), encoding="utf-8")
                    return result

            fake_service = RacingIllustrationService()
            with (
                mock.patch.object(server, "STORE_FILE", store_file),
                mock.patch.object(server, "ILLUSTRATIONS", fake_service),
            ):
                status, body = self.request_status(
                    "/api/illustrations/import",
                    method="POST",
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(
                        {
                            "projectId": "project-image",
                            "baseUpdatedAt": 30,
                            "content": "正文",
                            "candidateId": "a" * 32,
                        }
                    ).encode("utf-8"),
                )

        self.assertEqual(status, 409)
        response = json.loads(body.decode("utf-8"))
        self.assertEqual(response["error"]["code"], "DRAFT_VERSION_CONFLICT")
        self.assertNotIn("dataUrl", response)

    def test_illustration_preview_is_same_origin_nosniff_content(self):
        fake_service = FakeIllustrationService()
        with mock.patch.object(server, "ILLUSTRATIONS", fake_service):
            request = urllib.request.Request(
                f"{self.base_url}/api/illustrations/candidates/{'a' * 32}/preview"
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                body = response.read()
                headers = response.headers
        self.assertEqual(body, b"image")
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(headers.get("Cross-Origin-Resource-Policy"), "same-origin")
        self.assertEqual(fake_service.preview_calls, ["a" * 32])

    def test_illustration_provider_error_does_not_leak_remote_url_or_query(self):
        class FailingIllustrationService(FakeIllustrationService):
            def search(self, **kwargs):
                del kwargs
                raise server.IllustrationProviderError(
                    "图片搜索服务暂时不可用",
                    code="IMAGE_SEARCH_UNAVAILABLE",
                )

        fake_service = FailingIllustrationService()
        secret_content = "private-query-secret"
        store = {
            "activeId": "project-image",
            "projects": [
                {
                    "id": "project-image",
                    "updatedAt": 40,
                    "data": {"content": secret_content},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            store_file = Path(temporary) / "project-store.json"
            store_file.write_text(json.dumps(store), encoding="utf-8")
            with (
                mock.patch.object(server, "STORE_FILE", store_file),
                mock.patch.object(server, "ILLUSTRATIONS", fake_service),
            ):
                status, body = self.request_status(
                    "/api/illustrations/search",
                    method="POST",
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(
                        {
                            "projectId": "project-image",
                            "baseUpdatedAt": 40,
                            "content": secret_content,
                            "blocks": [{"blockId": "block-0", "text": secret_content}],
                        }
                    ).encode("utf-8"),
                )
        self.assertEqual(status, 502)
        rendered = body.decode("utf-8")
        self.assertNotIn(secret_content, rendered)
        self.assertNotIn("http", rendered.lower())

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

    def test_ai_preview_rejects_a_second_concurrent_provider_call(self):
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
        request_payload = {
            "projectId": "project-ai",
            "baseUpdatedAt": 10,
            "content": "正文",
            "mode": "polish",
            "accentColor": "#5B5FEF",
        }
        with tempfile.TemporaryDirectory() as temporary:
            store_file = Path(temporary) / "project-store.json"
            store_file.write_text(json.dumps(store), encoding="utf-8")
            with (
                mock.patch.object(server, "STORE_FILE", store_file),
                mock.patch.object(server, "AI_LAYOUT", fake_ai),
            ):
                server.AI_OPTIMIZE_LOCK.acquire()
                try:
                    status, body = self.request_status(
                        "/api/ai/optimize-layout",
                        method="POST",
                        headers={"Content-Type": "application/json"},
                        data=json.dumps(request_payload).encode("utf-8"),
                    )
                finally:
                    server.AI_OPTIMIZE_LOCK.release()

        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body.decode("utf-8"))["code"], "AI_REQUEST_IN_PROGRESS")
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
                    headers={
                        "Content-Type": "application/json",
                        "X-WTP-Save-Protocol": "2",
                    },
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

    def test_legacy_page_cannot_overwrite_an_existing_project(self):
        current = {
            "activeId": "project-1",
            "projects": [
                {
                    "id": "project-1",
                    "title": "服务器恢复版",
                    "updatedAt": 200,
                    "data": {"content": "绿色版本"},
                }
            ],
        }
        incoming = {
            "activeId": "project-1",
            "projects": [
                {
                    "id": "project-1",
                    "title": "浏览器旧缓存",
                    "updatedAt": 999,
                    "data": {"content": "蓝色旧版本"},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            store_file = Path(temporary) / "project-store.json"
            store_file.write_text(json.dumps(current), encoding="utf-8")
            with mock.patch.object(server, "STORE_FILE", store_file):
                status, body = self.request_status(
                    "/api/project-store",
                    method="PUT",
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(incoming).encode("utf-8"),
                )

            saved = json.loads(store_file.read_text(encoding="utf-8"))

        self.assertEqual(status, 428)
        self.assertEqual(
            json.loads(body.decode("utf-8"))["code"],
            "SAVE_PROTOCOL_REQUIRED",
        )
        self.assertEqual(saved, current)

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
                            headers={
                                "Content-Type": "application/json",
                                "X-WTP-Save-Protocol": "2",
                                "X-WTP-Expected-Project-Id": "project-1",
                                "X-WTP-Expected-Project-Updated-At": "200",
                            },
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
                    headers={
                        "Content-Type": "application/json",
                        "X-WTP-Save-Protocol": "2",
                        "X-WTP-Expected-Project-Id": "project-1",
                        "X-WTP-Expected-Project-Updated-At": "200",
                    },
                    data=json.dumps(incoming).encode("utf-8"),
                )

        self.assertEqual(status, 200)
        response = json.loads(body.decode("utf-8"))
        self.assertTrue(response["saveMeta"]["saved"])
        self.assertEqual(response["saveMeta"]["savedUpdatedAt"], 201)
        self.assertEqual(response["projects"][0]["data"]["content"], "新正文")
        schedule.assert_called_once()

    def test_agent_project_api_lists_reads_and_conditionally_updates(self):
        fake_cloud = FakeCloudStore()
        current = {
            "activeId": "project-1",
            "projects": [
                {
                    "id": "project-1",
                    "title": "原项目",
                    "updatedAt": 200,
                    "cloudBaseUpdatedAt": 200,
                    "data": {"content": "原正文", "published": False},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            store_file = Path(temporary) / "project-store.json"
            store_file.write_text(json.dumps(current), encoding="utf-8")
            with (
                mock.patch.object(server, "STORE_FILE", store_file),
                mock.patch.object(server, "CLOUD", fake_cloud),
                mock.patch.dict(server.CLOUD_STATUS, enabled_cloud_status(), clear=True),
            ):
                list_status, list_body = self.request_status("/api/projects")
                get_status, get_body = self.request_status("/api/projects/project-1")
                update_status, update_body = self.request_status(
                    "/api/projects/project-1",
                    method="PATCH",
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(
                        {
                            "expectedUpdatedAt": 200,
                            "title": "Codex 修改",
                            "content": "新正文",
                            "published": True,
                            "addImage": {
                                "id": "img-agent",
                                "image": {
                                    "src": "data:image/png;base64,dGVzdA==",
                                    "name": "Agent 配图.png",
                                },
                            },
                        }
                    ).encode("utf-8"),
                )

        self.assertEqual(list_status, 200)
        self.assertEqual(json.loads(list_body)["projects"][0]["published"], False)
        self.assertEqual(get_status, 200)
        self.assertEqual(json.loads(get_body)["project"]["data"]["content"], "原正文")
        self.assertEqual(update_status, 200)
        response = json.loads(update_body)
        self.assertTrue(response["localSaved"])
        self.assertTrue(response["cloudSynced"])
        self.assertEqual(response["project"]["title"], "Codex 修改")
        self.assertEqual(response["project"]["data"]["content"], "新正文")
        self.assertTrue(response["project"]["data"]["published"])
        self.assertEqual(response["project"]["data"]["images"]["img-agent"]["name"], "Agent 配图.png")

    def test_agent_project_api_rejects_a_stale_revision_without_overwrite(self):
        current = {
            "activeId": "project-1",
            "projects": [
                {"id": "project-1", "updatedAt": 201, "data": {"content": "伙伴新版"}}
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            store_file = Path(temporary) / "project-store.json"
            store_file.write_text(json.dumps(current), encoding="utf-8")
            with mock.patch.object(server, "STORE_FILE", store_file):
                status, body = self.request_status(
                    "/api/projects/project-1",
                    method="PATCH",
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(
                        {"expectedUpdatedAt": 200, "content": "Codex 旧基线修改"}
                    ).encode("utf-8"),
                )
                saved = json.loads(store_file.read_text(encoding="utf-8"))

        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)["code"], "DRAFT_VERSION_CONFLICT")
        self.assertEqual(saved, current)

    def test_agent_project_api_creates_a_shared_project(self):
        fake_cloud = FakeCloudStore()
        with tempfile.TemporaryDirectory() as temporary:
            store_file = Path(temporary) / "project-store.json"
            with (
                mock.patch.object(server, "STORE_FILE", store_file),
                mock.patch.object(server, "CLOUD", fake_cloud),
                mock.patch.dict(server.CLOUD_STATUS, enabled_cloud_status(), clear=True),
            ):
                status, body = self.request_status(
                    "/api/projects",
                    method="POST",
                    headers={"Content-Type": "application/json"},
                    data=json.dumps({"title": "Codex 新项目", "content": "正文"}).encode("utf-8"),
                )

        self.assertEqual(status, 201)
        response = json.loads(body)
        self.assertTrue(response["localSaved"])
        self.assertTrue(response["cloudSynced"])
        self.assertEqual(response["project"]["title"], "Codex 新项目")
        self.assertEqual(response["project"]["cloudBaseUpdatedAt"], response["project"]["updatedAt"])

    def test_agent_image_update_uses_zero_config_local_asset_library(self):
        disabled_cloud = SimpleNamespace(
            enabled=False,
            disabled_reason="WRITE_THEN_PUBLISH_CLOUD_SYNC 未开启",
        )
        current = {
            "activeId": "project-1",
            "projects": [
                {
                    "id": "project-1",
                    "title": "本地项目",
                    "updatedAt": 200,
                    "cloudBaseUpdatedAt": 0,
                    "data": {"content": "## 01 本地配图", "images": {}},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "runtime-data"
            store_file = data_dir / "project-store.json"
            data_dir.mkdir(parents=True)
            store_file.write_text(json.dumps(current), encoding="utf-8")
            local_assets = server.LocalAssetStore(server.ROOT, data_dir=data_dir, env={})
            with (
                mock.patch.object(server, "STORE_FILE", store_file),
                mock.patch.object(server, "DATA_DIR", data_dir),
                mock.patch.object(server, "LOCAL_ASSETS", local_assets),
                mock.patch.object(server, "CLOUD", disabled_cloud),
                mock.patch.dict(
                    server.CLOUD_STATUS,
                    {
                        **enabled_cloud_status(),
                        "enabled": False,
                        "fallbackToLocal": True,
                    },
                    clear=True,
                ),
            ):
                status, body = self.request_status(
                    "/api/projects/project-1",
                    method="PATCH",
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(
                        {
                            "expectedUpdatedAt": 200,
                            "content": "## 01 本地配图\n\n[[image:img-agent]]",
                            "addImage": {
                                "id": "img-agent",
                                "image": {
                                    "src": "data:image/png;base64,dGVzdA==",
                                    "name": "Agent 本地配图.png",
                                },
                            },
                        }
                    ).encode("utf-8"),
                )
                saved = json.loads(store_file.read_text(encoding="utf-8"))
                saved_image = saved["projects"][0]["data"]["images"]["img-agent"]
                local_asset_exists = (
                    local_assets.asset_dir / saved_image["localAssetName"]
                ).is_file()

        self.assertEqual(status, 200)
        response = json.loads(body)
        self.assertTrue(response["localSaved"])
        self.assertFalse(response["cloudSynced"])
        self.assertTrue(saved_image["localAssetId"])
        self.assertTrue(saved_image["localAssetName"])
        self.assertTrue(local_asset_exists)

    def test_conditional_project_store_put_requires_the_expected_base_revision(self):
        fake_cloud = FakeCloudStore()
        current = {
            "activeId": "project-1",
            "projects": [
                {"id": "project-1", "updatedAt": 200, "data": {"content": "基础正文"}}
            ],
        }
        incoming = {
            "activeId": "project-1",
            "projects": [
                {"id": "project-1", "updatedAt": 202, "data": {"content": "插入配图后的正文"}}
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
                store_file.write_text(json.dumps(current), encoding="utf-8")
                status, _ = self.request_status(
                    "/api/project-store",
                    method="PUT",
                    headers={
                        "Content-Type": "application/json",
                        "X-WTP-Save-Protocol": "2",
                        "X-WTP-Expected-Project-Id": "project-1",
                        "X-WTP-Expected-Project-Updated-At": "200",
                    },
                    data=json.dumps(incoming).encode("utf-8"),
                )
                self.assertEqual(status, 200)

                store_file.write_text(
                    json.dumps(
                        {
                            "activeId": "project-1",
                            "projects": [
                                {
                                    "id": "project-1",
                                    "updatedAt": 201,
                                    "data": {"content": "另一台浏览器的新正文"},
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                status, body = self.request_status(
                    "/api/project-store",
                    method="PUT",
                    headers={
                        "Content-Type": "application/json",
                        "X-WTP-Save-Protocol": "2",
                        "X-WTP-Expected-Project-Id": "project-1",
                        "X-WTP-Expected-Project-Updated-At": "200",
                    },
                    data=json.dumps(incoming).encode("utf-8"),
                )

        self.assertEqual(status, 409)
        self.assertEqual(
            json.loads(body.decode("utf-8"))["code"],
            "DRAFT_VERSION_CONFLICT",
        )
        schedule.assert_called_once()

    def test_project_delete_persists_tombstone_and_keeps_a_valid_active_project(self):
        fake_cloud = FakeCloudStore()
        project_a = {
            "id": "project-a",
            "title": "A",
            "updatedAt": 100,
            "data": {"content": "正文 A"},
        }
        project_b = {
            "id": "project-b",
            "title": "B",
            "updatedAt": 200,
            "data": {"content": "正文 B"},
        }
        cases = (
            (
                "current project",
                {"activeId": "project-a", "projects": [project_a, project_b]},
                "project-a",
                ["project-b"],
                "project-b",
            ),
            (
                "non-current project",
                {"activeId": "project-a", "projects": [project_a, project_b]},
                "project-b",
                ["project-a"],
                "project-a",
            ),
            (
                "last project",
                {"activeId": "project-a", "projects": [project_a]},
                "project-a",
                [],
                None,
            ),
        )

        for case_index, (
            label,
            current,
            target_id,
            expected_ids,
            expected_active_id,
        ) in enumerate(cases):
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temporary:
                store_file = Path(temporary) / "project-store.json"
                store_file.write_text(json.dumps(current), encoding="utf-8")
                deleted_at = 10_000 + case_index
                with (
                    mock.patch.object(server, "STORE_FILE", store_file),
                    mock.patch.object(server, "CLOUD", fake_cloud),
                    mock.patch.object(server.time, "time", return_value=5.0),
                    mock.patch.dict(
                        server.CLOUD_STATUS,
                        enabled_cloud_status(),
                        clear=True,
                    ),
                    mock.patch.object(server, "schedule_cloud_sync") as schedule,
                ):
                    status, body = self.request_status(
                        f"/api/project-store/{target_id}",
                        method="DELETE",
                        headers={"Content-Type": "application/json"},
                        data=json.dumps(
                            {
                                "confirm": True,
                                "deletedAt": deleted_at,
                                "activeId": expected_active_id,
                            }
                        ).encode("utf-8"),
                    )
                    saved = json.loads(store_file.read_text(encoding="utf-8"))

                self.assertEqual(status, 200)
                response = json.loads(body.decode("utf-8"))
                self.assertTrue(response["ok"])
                self.assertEqual(
                    [project["id"] for project in saved["projects"]],
                    expected_ids,
                )
                self.assertEqual(saved["activeId"], expected_active_id)
                self.assertEqual(
                    saved["deletedProjects"],
                    [{"id": target_id, "deletedAt": deleted_at}],
                )
                self.assertEqual(response["store"], saved)
                self.assertEqual(
                    {
                        "projectId": response["deletionMeta"]["projectId"],
                        "deletedAt": response["deletionMeta"]["deletedAt"],
                        "localSaved": response["deletionMeta"]["localSaved"],
                        "cloudDeleted": response["deletionMeta"]["cloudDeleted"],
                    },
                    {
                        "projectId": target_id,
                        "deletedAt": deleted_at,
                        "localSaved": True,
                        "cloudDeleted": True,
                    },
                )
                self.assertEqual(
                    fake_cloud.deleted_projects[-1],
                    (target_id, deleted_at, expected_active_id),
                )
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
                            headers={
                                "Content-Type": "application/json",
                                "X-WTP-Save-Protocol": "2",
                            },
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
                    headers={
                        "Content-Type": "application/json",
                        "X-WTP-Save-Protocol": "2",
                    },
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
        schedule.assert_not_called()

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
            # The shared test server can still be draining a background cloud-save
            # worker from the concurrency tests above. Give this redaction boundary
            # enough time to observe the response without turning scheduler jitter
            # into a false negative.
            status, body = self.request_status("/api/assets", timeout=10)

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


class ProjectStoreMergeTests(unittest.TestCase):
    def test_browser_store_payload_lazy_loads_existing_cloud_images(self):
        payload = {
            "projects": [
                {
                    "id": "project-1",
                    "data": {
                        "images": {
                            "cloud": {
                                "src": "data:image/png;base64,aGVsbG8=",
                                "cloudAssetId": "asset/one",
                            },
                            "local": {"src": "data:image/png;base64,bG9jYWw="},
                        }
                    },
                }
            ]
        }

        with mock.patch.object(server, "CLOUD", FakeCloudStore()), mock.patch.object(
            server,
            "cloud_status",
            return_value={"fallbackToLocal": False},
        ):
            result = server.browser_store_payload(payload)

        images = result["projects"][0]["data"]["images"]
        self.assertEqual(images["cloud"]["src"], "/api/assets/asset%2Fone/content")
        self.assertTrue(images["local"]["src"].startswith("data:image/png"))

    def test_tombstone_prevents_an_older_project_from_resurrecting(self):
        current = {
            "activeId": "project-live",
            "projects": [
                {
                    "id": "project-live",
                    "updatedAt": 300,
                    "data": {"content": "保留"},
                }
            ],
            "deletedProjects": [{"id": "project-deleted", "deletedAt": 200}],
        }
        incoming = {
            "activeId": "project-deleted",
            "projects": [
                {
                    "id": "project-deleted",
                    "updatedAt": 100,
                    "data": {"content": "旧浏览器缓存"},
                }
            ],
        }

        merged = server.merge_store(current, incoming)

        self.assertEqual(
            [project["id"] for project in merged["projects"]],
            ["project-live"],
        )
        self.assertEqual(merged["activeId"], "project-live")
        self.assertEqual(
            merged["deletedProjects"],
            [{"id": "project-deleted", "deletedAt": 200}],
        )

    def test_equal_timestamp_does_not_replace_a_different_complete_project(self):
        current_project = {
            "id": "project-1",
            "title": "当前标题",
            "updatedAt": 200,
            "data": {
                "content": "相同正文",
                "images": {"image-new": {"name": "new.png"}},
            },
        }
        incoming_project = {
            "id": "project-1",
            "title": "旧标题",
            "updatedAt": 200,
            "data": {
                "content": "相同正文",
                "images": {"image-old": {"name": "old.png"}},
            },
        }

        merged = server.merge_store(
            {"activeId": "project-1", "projects": [current_project]},
            {"activeId": "project-1", "projects": [incoming_project]},
        )

        self.assertEqual(merged["projects"], [current_project])

    def test_newer_browser_revision_cannot_regress_confirmed_cloud_cursor(self):
        current_project = {
            "id": "project-1",
            "title": "云端已确认",
            "updatedAt": 200,
            "cloudBaseUpdatedAt": 200,
            "data": {"content": "第一版"},
        }
        stale_browser_revision = {
            "id": "project-1",
            "title": "继续编辑",
            "updatedAt": 201,
            "cloudBaseUpdatedAt": 0,
            "data": {"content": "第二版"},
        }

        merged = server.merge_store(
            {"activeId": "project-1", "projects": [current_project]},
            {"activeId": "project-1", "projects": [stale_browser_revision]},
        )

        self.assertEqual(merged["projects"][0]["data"]["content"], "第二版")
        self.assertEqual(merged["projects"][0]["cloudBaseUpdatedAt"], 200)

    def test_late_cloud_confirmation_advances_newer_browser_revision_cursor(self):
        newer_browser_revision = {
            "id": "project-1",
            "title": "继续编辑",
            "updatedAt": 201,
            "cloudBaseUpdatedAt": 0,
            "data": {"content": "第二版"},
        }
        confirmed_older_revision = {
            "id": "project-1",
            "title": "云端已确认",
            "updatedAt": 200,
            "cloudBaseUpdatedAt": 200,
            "data": {"content": "第一版"},
        }

        merged = server.merge_store(
            {"activeId": "project-1", "projects": [newer_browser_revision]},
            {"activeId": "project-1", "projects": [confirmed_older_revision]},
        )

        self.assertEqual(merged["projects"][0]["data"]["content"], "第二版")
        self.assertEqual(merged["projects"][0]["cloudBaseUpdatedAt"], 200)

    def test_store_retains_up_to_configured_project_limit(self):
        projects = [
            {
                "id": f"project-{index}",
                "title": f"稿件 {index}",
                "updatedAt": index + 1,
                "data": {"content": str(index)},
            }
            for index in range(server.MAX_PROJECTS + 5)
        ]

        merged = server.merge_store(
            {"activeId": projects[-1]["id"], "projects": []},
            {"activeId": projects[-1]["id"], "projects": projects},
        )

        self.assertEqual(len(merged["projects"]), server.MAX_PROJECTS)
        self.assertEqual(merged["projects"][0]["id"], projects[-1]["id"])


if __name__ == "__main__":
    unittest.main()
