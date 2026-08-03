#!/usr/bin/env python3
"""Browser regression for preview/source tracking and in-card editing."""

import os
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.environ.get("WTP_E2E_BASE_URL", "http://127.0.0.1:5174")
CHROME = os.environ.get(
    "WTP_E2E_CHROME",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)
SCREENSHOT = os.environ.get("WTP_E2E_SCREENSHOT", "/tmp/write-then-publish-preview-ux.png")
INLINE_SCREENSHOT = os.environ.get(
    "WTP_E2E_INLINE_SCREENSHOT",
    "/tmp/write-then-publish-preview-inline-editor.png",
)
INLINE_DETAIL_SCREENSHOT = os.environ.get(
    "WTP_E2E_INLINE_DETAIL_SCREENSHOT",
    "/tmp/write-then-publish-preview-inline-editor-detail.png",
)


def select_text(page, selector: str, start: int, end: int) -> None:
    page.evaluate(
        """
        ({ selector, start, end }) => {
          const root = document.querySelector(selector);
          const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
          let offset = 0;
          let startNode = null;
          let endNode = null;
          let startOffset = 0;
          let endOffset = 0;
          while (walker.nextNode()) {
            const node = walker.currentNode;
            const length = node.nodeValue?.length || 0;
            if (!startNode && start <= offset + length) {
              startNode = node;
              startOffset = Math.max(0, Math.min(length, start - offset));
            }
            if (!endNode && end <= offset + length) {
              endNode = node;
              endOffset = Math.max(0, Math.min(length, end - offset));
              break;
            }
            offset += length;
          }
          const range = document.createRange();
          range.setStart(startNode, startOffset);
          range.setEnd(endNode || startNode, endNode ? endOffset : startOffset);
          const selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
        }
        """,
        {"selector": selector, "start": start, "end": end},
    )


def main() -> None:
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=CHROME)
        page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
        page.on("console", lambda message: errors.append(f"console: {message.text}") if message.type == "error" else None)

        page.goto(BASE_URL)
        page.wait_for_load_state("networkidle")
        page.locator("#newProjectBtn").click()

        paragraphs = [
            f"第 {index:02d} 段用于验证长内容定位。这里故意写得更长一些，让输入框发生自动换行，并检验右侧点击后左侧仍能准确滚动到对应文字。"
            for index in range(1, 31)
        ]
        content = "# 预览交互测试\n\n" + "\n\n".join(paragraphs) + "\n\n末尾定位测试文字"
        textarea = page.locator("#contentInput")
        textarea.fill(content)
        page.wait_for_timeout(900)

        image_file = ROOT / "docs" / "screenshots" / "cards-mode.png"
        page.locator("#contentImageInput").set_input_files(str(image_file))
        page.locator(".preview-image-box").first.wait_for(state="visible")
        page.wait_for_timeout(700)

        final_text_hit = page.locator(".preview-text-hit").last
        source_start = int(final_text_hit.get_attribute("data-start"))
        source_end = int(final_text_hit.get_attribute("data-end"))
        final_text_hit.click()
        editor = page.locator(".preview-inline-editor")
        editor.wait_for(state="visible")

        editor_bounds = editor.bounding_box()
        frame_bounds = editor.locator("xpath=..").bounding_box()
        assert editor_bounds and frame_bounds
        assert editor_bounds["x"] >= frame_bounds["x"] - 1
        assert editor_bounds["x"] + editor_bounds["width"] <= frame_bounds["x"] + frame_bounds["width"] + 1
        page.screenshot(path=INLINE_SCREENSHOT, full_page=False)
        editor.screenshot(path=INLINE_DETAIL_SCREENSHOT)

        selection = textarea.evaluate("el => ({start: el.selectionStart, end: el.selectionEnd, top: el.scrollTop})")
        assert selection["start"] == source_start and selection["end"] == source_end
        assert selection["top"] > 0, "long-document source tracking did not scroll the editor"

        inline_content = page.locator(".preview-inline-content")
        inline_content.fill("右侧直接编辑成功")
        select_text(page, ".preview-inline-content", 2, 6)
        page.locator("[data-preview-format='bold']").click()
        assert inline_content.locator("strong, b").count() == 1
        page.locator("[data-preview-action='done']").click()
        editor.wait_for(state="detached")
        page.wait_for_function("document.querySelector('#contentInput').value.includes('右侧**直接编辑**成功')")

        image_box = page.locator(".preview-image-box").first
        image_box.wait_for(state="visible")
        image_start = int(image_box.get_attribute("data-source-start"))
        image_end = int(image_box.get_attribute("data-source-end"))
        marker = textarea.input_value()[image_start:image_end]
        assert marker.startswith("[[image:")
        image_box.click(position={"x": 80, "y": 80})
        image_selection = textarea.evaluate("el => ({start: el.selectionStart, end: el.selectionEnd})")
        assert image_selection == {"start": image_start, "end": image_end}
        assert image_box.evaluate("el => el.classList.contains('is-source-linked')")

        image_box.hover()
        image_box.locator(".preview-image-delete").click()
        page.wait_for_function("document.querySelectorAll('.preview-image-box').length === 0")
        assert marker not in textarea.input_value()

        textarea.focus()
        page.keyboard.press("Meta+z")
        page.locator(".preview-image-box").first.wait_for(state="visible")
        assert marker in textarea.input_value(), "image deletion should remain undoable"

        page.screenshot(path=SCREENSHOT, full_page=False)
        browser.close()

    assert not errors, "browser errors: " + " | ".join(errors)
    print("preview UX browser regression passed")
    print(f"screenshot={SCREENSHOT}")
    print(f"inline_screenshot={INLINE_SCREENSHOT}")
    print(f"inline_detail_screenshot={INLINE_DETAIL_SCREENSHOT}")


if __name__ == "__main__":
    main()
