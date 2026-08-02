#!/usr/bin/env python3
"""Verify live team conflicts fork local work and draft switching stays read-only."""

from __future__ import annotations

import json
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright


PROJECT_ID = "project-live-conflict"


def request_json(url: str, *, method: str = "GET", payload: dict | None = None, headers: dict | None = None) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        method=method,
        data=body,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def main() -> None:
    base_url = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5173").rstrip("/")
    initial = {
        "activeId": PROJECT_ID,
        "projects": [
            {
                "id": PROJECT_ID,
                "title": "团队原稿",
                "updatedAt": 100,
                "data": {"content": "# 初始版本", "images": {}},
            }
        ],
        "deletedProjects": [],
    }
    request_json(
        base_url + "/api/project-store",
        method="PUT",
        payload=initial,
        headers={"X-WTP-Save-Protocol": "2"},
    )

    writes: list[tuple[str, int | None]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        )
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.on(
            "response",
            lambda response: writes.append((response.request.method, response.status))
            if response.url.endswith("/api/project-store") and response.request.method == "PUT"
            else None,
        )
        page.goto(base_url, wait_until="networkidle")
        page.wait_for_function(
            "document.querySelector('#projectTitleInput')?.value === '团队原稿'"
        )
        page.wait_for_function("window.state === undefined || true")
        full_data = page.evaluate("() => ({ ...readForm(), content: '# 团队成员刚保存的新版本' })")

        teammate = {
            "activeId": PROJECT_ID,
            "projects": [
                {
                    "id": PROJECT_ID,
                    "title": "团队原稿",
                    "updatedAt": 200,
                    "data": full_data,
                }
            ],
            "deletedProjects": [],
        }
        request_json(
            base_url + "/api/project-store",
            method="PUT",
            payload=teammate,
            headers={
                "X-WTP-Save-Protocol": "2",
                "X-WTP-Expected-Project-Id": PROJECT_ID,
                "X-WTP-Expected-Project-Updated-At": "100",
            },
        )

        page.locator("#contentInput").fill("# 我正在编辑的本地版本")
        page.wait_for_function(
            "document.querySelector('#projectTitleInput')?.value.includes('本地未同步副本')",
            timeout=15000,
        )
        page.wait_for_function(
            "document.querySelector('#statusText')?.textContent.includes('团队成员的新版本')",
            timeout=15000,
        )
        page.wait_for_timeout(2500)

        saved = request_json(base_url + "/api/project-store")
        canonical = next(project for project in saved["projects"] if project["id"] == PROJECT_ID)
        copies = [
            project
            for project in saved["projects"]
            if project.get("data", {}).get("__localConflictOf") == PROJECT_ID
        ]
        assert canonical["data"]["content"] == "# 团队成员刚保存的新版本", canonical
        assert len(copies) == 1, copies
        assert copies[0]["data"]["content"] == "# 我正在编辑的本地版本", copies[0]
        assert any(status == 409 for _, status in writes), writes
        assert any(status == 200 for _, status in writes), writes

        writes_before_switch = len(writes)
        page.locator(f'.history-item[data-project-id="{PROJECT_ID}"] .history-open').evaluate(
            "button => button.click()"
        )
        page.wait_for_function(
            "document.querySelector('#contentInput')?.value === '# 团队成员刚保存的新版本'",
            timeout=10000,
        )
        copy_id = copies[0]["id"]
        started = time.perf_counter()
        page.locator(f'.history-item[data-project-id="{copy_id}"] .history-open').evaluate(
            "button => button.click()"
        )
        page.wait_for_function(
            "document.querySelector('#contentInput')?.value === '# 我正在编辑的本地版本'",
            timeout=10000,
        )
        switch_ms = (time.perf_counter() - started) * 1000
        page.wait_for_timeout(2500)
        assert len(writes) == writes_before_switch, writes

        print(
            json.dumps(
                {
                    "canonicalPreserved": True,
                    "localCopyPreserved": True,
                    "conflictStatusObserved": 409,
                    "switchGeneratedWrites": 0,
                    "cachedReturnMs": round(switch_ms, 1),
                },
                ensure_ascii=False,
            )
        )
        browser.close()


if __name__ == "__main__":
    main()
