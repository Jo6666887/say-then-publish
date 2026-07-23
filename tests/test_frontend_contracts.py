import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "src" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


def function_body(name):
    match = re.search(
        rf"^(?:async\s+)?function\s+{re.escape(name)}\([^\n]*\)\s*\{{\n"
        rf"(?P<body>.*?)^\}}\n",
        APP,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise AssertionError(f"missing JS function: {name}")
    return match.group("body")


def constant_object(name):
    match = re.search(
        rf"^const\s+{re.escape(name)}\s*=\s*\{{\n(?P<body>.*?)^\}};",
        APP,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise AssertionError(f"missing JS object: {name}")
    return match.group("body")


def button_tag(element_id):
    match = re.search(
        rf'<button\b(?=[^>]*\bid="{re.escape(element_id)}")[^>]*>',
        HTML,
        re.DOTALL,
    )
    if not match:
        raise AssertionError(f"missing button: {element_id}")
    return match.group(0)


class AiOptimizeInteractionContractTests(unittest.TestCase):
    def test_modal_starts_unselected_and_requires_explicit_generate(self):
        for element_id in ("aiModeLayout", "aiModePolish"):
            tag = button_tag(element_id)
            self.assertIn('role="radio"', tag)
            self.assertIn('aria-checked="false"', tag)
            self.assertNotRegex(tag, r'class="[^"]*\bactive\b')

        generate = button_tag("aiOptimizeGenerateBtn")
        self.assertIn("disabled", generate)
        self.assertIn('type="button"', generate)

        apply_button = button_tag("aiOptimizeApplyBtn")
        self.assertIn("disabled", apply_button)
        self.assertIn("hidden", apply_button)

    def test_opening_modal_never_starts_or_saves_ai_request(self):
        body = function_body("openAiOptimizeModal")
        self.assertNotIn("runAiOptimization(", body)
        self.assertNotIn("fetch(", body)
        self.assertNotIn("saveState(", body)
        self.assertIn("setAiOptimizeMode(null)", body)
        self.assertIn('els.workspace?.setAttribute("inert", "")', body)
        self.assertIn('els.workspace?.removeAttribute("inert")', function_body("closeAiOptimizeModal"))

    def test_modes_only_select_and_generate_button_is_only_request_trigger(self):
        bind = function_body("bindEvents")
        mode_binding = re.search(
            r"\[els\.aiModeLayout,\s*els\.aiModePolish\]\.forEach\(\(button\)\s*=>\s*\{"
            r"(?P<body>.*?)^\s*\}\);",
            bind,
            re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(mode_binding)
        self.assertIn("chooseAiOptimizeMode", mode_binding.group("body"))
        self.assertNotIn("runAiOptimization", mode_binding.group("body"))

        generate_start = bind.index("els.aiOptimizeGenerate")
        generate_binding = bind[generate_start : generate_start + 260]
        self.assertIn('addEventListener("click"', generate_binding)
        self.assertIn("runAiOptimization(", generate_binding)
        self.assertEqual(
            APP.count("runAiOptimization("),
            2,
            "AI requests must only have the function definition and explicit Generate binding",
        )

    def test_no_mode_selection_cannot_fall_back_to_layout(self):
        selected = function_body("selectedAiOptimizeMode")
        self.assertIn("return null", selected)
        run = function_body("runAiOptimization")
        self.assertIn("!requestedMode", run)
        self.assertIn("fetch(AI_OPTIMIZE_URL", run)


class CardThemeContractTests(unittest.TestCase):
    def test_card_theme_round_trips_with_compatible_default(self):
        self.assertIn('const CARD_THEME_DEFAULT = "social-clean"', APP)
        self.assertIn("cardTheme: CARD_THEME_DEFAULT", function_body("defaultFormState"))
        self.assertIn("cardTheme: normalizeCardTheme(state.cardTheme)", function_body("readForm"))
        self.assertIn("state.cardTheme = normalizeCardTheme(data.cardTheme)", function_body("applyForm"))
        self.assertIn("data.cardTheme = normalizeCardTheme(data.cardTheme)", function_body("migrateStoredState"))
        self.assertIn("CARD_THEME_DEFAULT", function_body("normalizeCardTheme"))

    def test_theme_catalog_has_structural_not_just_color_differences(self):
        themes = constant_object("CARD_THEMES")
        theme_ids = set(re.findall(r'data-card-theme="([^"]+)"', HTML))
        self.assertGreaterEqual(len(theme_ids), 5)
        self.assertIn('identityPlacement: "top"', themes)
        self.assertIn('identityPlacement: "bottom"', themes)
        self.assertIn('pageNumber: "top-right"', themes)
        self.assertIn("openingQuote: true", themes)
        self.assertGreaterEqual(len(set(re.findall(r'zhFont: "([^"]+)"', themes))), 3)

    def test_theme_reaches_layout_typography_and_canvas_export(self):
        self.assertIn("cardThemeFor(settings)", function_body("contentBoundsForPage"))
        self.assertIn("contentBoundsForPage(settings", function_body("buildPages"))
        self.assertIn("cardThemeFor(settings)", function_body("styleForBlock"))
        renderer = function_body("drawPageToContext")
        self.assertIn("drawCardThemeChrome", renderer)
        self.assertIn("drawCardThemeHeader", renderer)
        self.assertIn("drawCardThemeFooter", renderer)
        signature = function_body("pageRenderSignature")
        self.assertIn("pageIndex", signature)
        self.assertIn("totalPages", signature)
        self.assertIn("table: item.table", signature)

    def test_theme_layout_keeps_images_inside_content_bounds(self):
        image_size = function_body("imageBlockSize")
        self.assertIn("Math.min(requestedWidth, maxWidth, maxHeight * aspect)", image_size)
        themes = constant_object("CARD_THEMES")
        magazine = themes[themes.index("magazine:") :]
        self.assertIn("imageHeight: 400", magazine)
        self.assertNotIn('String(data.imageHeight) === "380"', function_body("applyForm"))
        self.assertNotIn('String(data.imageHeight) === "380"', function_body("migrateStoredState"))
        image_hits = function_body("collectImageHits")
        self.assertIn("actualHeight: item.height", image_hits)

    def test_theme_selector_is_bound_to_persistable_action(self):
        bind = function_body("bindEvents")
        self.assertIn("cardThemeButtons", bind)
        self.assertIn("applyCardTheme", bind)
        apply_theme = function_body("applyCardTheme")
        self.assertIn("state.cardTheme = themeId", apply_theme)
        self.assertIn("flushAppearanceSaveIfHydrated()", apply_theme)


if __name__ == "__main__":
    unittest.main()
