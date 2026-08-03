#!/usr/bin/env python3
"""Verify that a newer stale browser cache cannot replace the shared project."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "project-cache-conflict"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def read_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.load(response)


def wait_for_server(url: str) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            if read_json(url + "/api/health").get("ok") is True:
                return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("test server did not start")


def main() -> None:
    shared_project = {
        "id": PROJECT_ID,
        "title": "恢复后的绿色原稿",
        "updatedAt": 200,
        "data": {
            "content": "# 服务器绿色版本",
            "images": {},
            "cardTheme": "swiss-green",
            "headerMode": "first",
            "accentColor": "#b9db16",
        },
    }
    stale_project = {
        "id": PROJECT_ID,
        "title": "浏览器蓝色旧稿",
        "updatedAt": 999,
        "data": {
            "content": "# 浏览器蓝色旧版本",
            "images": {},
            "cardTheme": "social-clean",
            "headerMode": "every",
            "accentColor": "#2563eb",
        },
    }

    with tempfile.TemporaryDirectory(prefix="write-then-publish-conflict-") as temporary:
        data_dir = Path(temporary)
        store_file = data_dir / "project-store.json"
        store_file.write_text(
            json.dumps(
                {
                    "activeId": PROJECT_ID,
                    "projects": [shared_project],
                    "deletedProjects": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        port = free_port()
        base_url = f"http://127.0.0.1:{port}"
        env = {
            **os.environ,
            "WRITE_THEN_PUBLISH_CLOUD_SYNC": "0",
            "WRITE_THEN_PUBLISH_DATA_DIR": str(data_dir),
            "WTP_PORT": str(port),
            "WTP_OPEN_BROWSER": "0",
        }
        server = subprocess.Popen(
            [str(ROOT / ".venv/bin/python3"), str(ROOT / "server.py")],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            wait_for_server(base_url)
            write_requests: list[str] = []
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                )
                page = browser.new_page(viewport={"width": 1600, "height": 1000})
                page.on(
                    "request",
                    lambda request: write_requests.append(request.method)
                    if request.url.endswith("/api/project-store") and request.method != "GET"
                    else None,
                )
                local_snapshot = {
                    "activeId": PROJECT_ID,
                    "projects": [stale_project],
                    "deletedProjects": [],
                }
                page.add_init_script(
                    script=f"""
                    localStorage.setItem("graphicTextLayoutProjects.v1", {json.dumps(json.dumps(local_snapshot, ensure_ascii=False))});
                    localStorage.setItem("writeThenPublishActiveProject.v1", {json.dumps(PROJECT_ID)});
                    """
                )
                page.goto(base_url, wait_until="networkidle")
                page.wait_for_function(
                    "document.querySelector('#projectTitleInput')?.value === '恢复后的绿色原稿'"
                )
                page.wait_for_function(
                    "document.querySelector('#accentColorInput')?.value?.toLowerCase() === '#b9db16'"
                )
                titles = page.locator(".history-item .history-open span").all_text_contents()
                assert "恢复后的绿色原稿" in titles, titles
                assert any("冲突备份" in title for title in titles), titles
                assert write_requests == [], write_requests
                browser.close()

            legacy_payload = {
                "activeId": PROJECT_ID,
                "projects": [{**stale_project, "updatedAt": 5000}],
                "deletedProjects": [],
            }
            request = urllib.request.Request(
                base_url + "/api/project-store",
                method="PUT",
                headers={"Content-Type": "application/json"},
                data=json.dumps(legacy_payload).encode("utf-8"),
            )
            try:
                urllib.request.urlopen(request, timeout=10)
                raise AssertionError("legacy write unexpectedly succeeded")
            except urllib.error.HTTPError as error:
                assert error.code == 428, error.code
                assert json.load(error).get("code") == "SAVE_PROTOCOL_REQUIRED"

            saved = read_json(base_url + "/api/project-store")
            project = next(item for item in saved["projects"] if item["id"] == PROJECT_ID)
            assert project["data"]["content"] == "# 服务器绿色版本"
            assert project["data"]["cardTheme"] == "swiss-green"
            print(
                json.dumps(
                    {
                        "activeTitle": "恢复后的绿色原稿",
                        "conflictCopyPreserved": True,
                        "legacyWriteStatus": 428,
                        "serverTheme": project["data"]["cardTheme"],
                    },
                    ensure_ascii=False,
                )
            )
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


if __name__ == "__main__":
    main()
