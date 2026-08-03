#!/usr/bin/env python3
import json

from playwright.sync_api import sync_playwright


BASE_URL = "http://127.0.0.1:5187"


def select_text(page, start, end):
    page.locator("#contentInput").evaluate(
        """(textarea, range) => {
            textarea.focus();
            textarea.setSelectionRange(range.start, range.end);
        }""",
        {"start": start, "end": end},
    )


def release_selection(page):
    page.evaluate(
        "document.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }))"
    )
    page.wait_for_timeout(80)


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    page.locator("#newProjectBtn").click()
    content = page.locator("#contentInput")
    content.fill("alpha beta gamma")

    background_tool = page.locator(".bg-color-tool")
    background_tool.click()
    page.locator("#bgColorConfirmBtn").click()
    assert background_tool.get_attribute("aria-pressed") == "true"

    select_text(page, 0, 5)
    release_selection(page)
    first_background_value = content.input_value()
    assert first_background_value == "{{bg:#fff3a3|alpha}} beta gamma"
    assert first_background_value.count("{{bg:") == 1
    assert background_tool.get_attribute("aria-pressed") == "false"

    beta_start = first_background_value.index("beta")
    select_text(page, beta_start, beta_start + 4)
    release_selection(page)
    assert content.input_value() == first_background_value

    background_tool.click()
    page.locator("#bgColorConfirmBtn").click()
    assert background_tool.get_attribute("aria-pressed") == "true"
    background_tool.click()
    assert background_tool.get_attribute("aria-pressed") == "false"
    assert page.locator("#bgColorMenu").get_attribute("open") is None

    content.fill("red blue")
    color_tool = page.locator(".color-tool")
    color_tool.click()
    page.locator("#colorConfirmBtn").click()
    assert color_tool.get_attribute("aria-pressed") == "true"
    select_text(page, 0, 3)
    release_selection(page)
    assert content.input_value() == "{{color:#2563eb|red}} blue"
    assert color_tool.get_attribute("aria-pressed") == "false"

    content.fill("hello world")
    select_text(page, 0, 5)
    page.locator('[data-format="bold"]').click()
    assert content.input_value() == "**hello** world"
    assert content.evaluate("el => [el.selectionStart, el.selectionEnd]") == [2, 7]

    page.locator('[data-format="bold"]').click()
    assert content.input_value() == "hello world"
    assert content.evaluate("el => [el.selectionStart, el.selectionEnd]") == [0, 5]

    assert not page_errors, page_errors
    print(
        json.dumps(
            {
                "backgroundSingleUse": True,
                "textColorSingleUse": True,
                "sameButtonCancels": True,
                "boldToggles": True,
                "pageErrors": page_errors,
            },
            ensure_ascii=False,
        )
    )
    browser.close()
