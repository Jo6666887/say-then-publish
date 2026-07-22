import json
import threading
import unittest
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer

import server


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


if __name__ == "__main__":
    unittest.main()
