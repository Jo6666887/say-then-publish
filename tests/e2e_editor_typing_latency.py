#!/usr/bin/env python3
import json

from playwright.sync_api import sync_playwright


BASE_URL = "http://127.0.0.1:5188"


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    page.locator("#newProjectBtn").click()
    content = page.locator("#contentInput")
    large_content = "\n\n".join(
        f"## 第 {index + 1} 节\n这是一段用于验证长内容输入性能的正文。连续修改左侧文字时，输入框必须优先响应，右侧预览稍后合并刷新。"
        for index in range(90)
    )
    content.fill(large_content)
    page.wait_for_function(
        "Number(document.querySelector('#pageCount').textContent.match(/\\d+/)?.[0] || 0) >= 8",
        timeout=15_000,
    )
    page.wait_for_timeout(1_200)

    page.evaluate(
        """() => {
            window.__previewMutations = 0;
            window.__previewMutationDetails = [];
            window.__previewObserver?.disconnect();
            window.__previewObserver = new MutationObserver((records) => {
                window.__previewMutations += records.length;
                window.__previewMutationDetails.push(...records.map((record) => ({
                    target: record.target.id || record.target.className || record.target.nodeName,
                    added: record.addedNodes.length,
                    removed: record.removedNodes.length,
                })));
            });
            window.__previewObserver.observe(document.querySelector('#pages'), {
                childList: true,
            });
        }"""
    )

    composition_result = page.evaluate(
        """async () => {
            const textarea = document.querySelector('#contentInput');
            textarea.focus();
            textarea.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }));
            const handlerDurations = [];
            const timerIntervals = [];
            let previous = performance.now();
            for (const character of '即时输入') {
                await new Promise((resolve) => setTimeout(resolve, 240));
                const now = performance.now();
                timerIntervals.push(now - previous);
                previous = now;
                textarea.value += character;
                const startedAt = performance.now();
                textarea.dispatchEvent(new InputEvent('input', {
                    bubbles: true,
                    data: character,
                    inputType: 'insertCompositionText',
                    isComposing: true,
                }));
                handlerDurations.push(performance.now() - startedAt);
            }
            return {
                handlerDurations,
                timerIntervals,
                previewMutations: window.__previewMutations,
                previewMutationDetails: window.__previewMutationDetails,
                valueEndsCorrectly: textarea.value.endsWith('即时输入'),
            };
        }"""
    )
    assert composition_result["valueEndsCorrectly"] is True
    assert composition_result["previewMutations"] == 0, composition_result
    assert max(composition_result["handlerDurations"]) < 50

    page.evaluate(
        """() => {
            const textarea = document.querySelector('#contentInput');
            textarea.dispatchEvent(new CompositionEvent('compositionend', {
                bubbles: true,
                data: '即时输入',
            }));
        }"""
    )
    page.wait_for_timeout(250)
    assert page.evaluate("window.__previewMutations") == 0
    page.wait_for_function("window.__previewMutations > 0", timeout=8_000)

    page.evaluate("window.__previewMutations = 0")
    rapid_input_result = page.evaluate(
        """async () => {
            const textarea = document.querySelector('#contentInput');
            const handlerDurations = [];
            for (const character of '不卡顿') {
                await new Promise((resolve) => setTimeout(resolve, 120));
                textarea.value += character;
                const startedAt = performance.now();
                textarea.dispatchEvent(new InputEvent('input', {
                    bubbles: true,
                    data: character,
                    inputType: 'insertText',
                }));
                handlerDurations.push(performance.now() - startedAt);
            }
            return {
                handlerDurations,
                previewMutations: window.__previewMutations,
                valueEndsCorrectly: textarea.value.endsWith('不卡顿'),
            };
        }"""
    )
    assert rapid_input_result["valueEndsCorrectly"] is True
    assert rapid_input_result["previewMutations"] == 0
    assert max(rapid_input_result["handlerDurations"]) < 50
    page.wait_for_timeout(250)
    assert page.evaluate("window.__previewMutations") == 0
    page.wait_for_function("window.__previewMutations > 0", timeout=8_000)

    assert not page_errors, page_errors
    print(
        json.dumps(
            {
                "imePreviewMutationsWhileTyping": composition_result["previewMutations"],
                "imeMaxHandlerMs": round(max(composition_result["handlerDurations"]), 2),
                "imeMaxTimerIntervalMs": round(max(composition_result["timerIntervals"]), 2),
                "rapidPreviewMutationsWhileTyping": rapid_input_result["previewMutations"],
                "rapidMaxHandlerMs": round(max(rapid_input_result["handlerDurations"]), 2),
                "previewUpdatedAfterIdle": True,
                "pageErrors": page_errors,
            },
            ensure_ascii=False,
        )
    )
    browser.close()
