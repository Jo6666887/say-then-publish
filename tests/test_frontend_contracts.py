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


class ProjectDuplicateContractTests(unittest.TestCase):
    def test_history_duplicate_creates_a_new_revision_and_persists_it(self):
        history = function_body("updateProjectHistory")
        duplicate = function_body("duplicateProject")

        self.assertIn('class="history-duplicate"', history)
        self.assertIn('data-lucide="copy-plus"', history)
        self.assertIn("duplicateProject(project.id)", history)
        self.assertIn("JSON.parse(JSON.stringify(source.data))", duplicate)
        self.assertIn("createProject(copiedData)", duplicate)
        self.assertIn("flushProjectStoreToIndexedDb()", duplicate)
        self.assertIn('phase: "saving-local"', duplicate)

    def test_builtin_guides_do_not_offer_duplicate_action(self):
        history = function_body("updateProjectHistory")
        duplicate = function_body("duplicateProject")

        self.assertIn("builtIn", history)
        self.assertIn("history-lock", history)
        self.assertIn("isBuiltInProjectId(projectId)", duplicate)
        self.assertIn("内置说明书不可复制", duplicate)


class SharedProjectConflictContractTests(unittest.TestCase):
    def test_shared_revision_keeps_original_id_and_forks_newer_local_cache(self):
        reconcile = function_body("reconcileLocalProjectsWithShared")
        conflict = function_body("localConflictProject")

        self.assertIn("normalizedShared", reconcile)
        self.assertIn("projectRevisionMatches", reconcile)
        self.assertIn("localConflictProject", reconcile)
        self.assertIn("本地未同步副本", conflict)
        self.assertIn("__localConflictOf", conflict)

    def test_shared_saves_require_protocol_and_server_base_revision(self):
        start = APP.index("async function saveProjectStoreToSharedServer(")
        end = APP.index("function imageReferenceSignature", start)
        save = APP[start:end]

        self.assertIn("SHARED_SAVE_PROTOCOL_HEADER", save)
        self.assertIn("SHARED_SAVE_PROTOCOL_VERSION", save)
        self.assertIn("sharedProjectVersions.get", save)
        self.assertIn('headers["X-WTP-Expected-Project-Updated-At"]', save)


class PreviewDirectEditingContractTests(unittest.TestCase):
    def test_preview_text_uses_wrapping_aware_source_tracking(self):
        focus = function_body("focusEditorRange")
        scroll = function_body("scrollTextareaToRange")

        self.assertIn("scrollTextareaToRange(start)", focus)
        self.assertIn('mirror.className = "textarea-scroll-mirror"', scroll)
        self.assertIn("marker.offsetTop", scroll)
        self.assertNotIn('split("\\n").length', scroll)

    def test_card_text_opens_a_visual_editor_and_serializes_formatting(self):
        target = function_body("handlePreviewTextTarget")
        editor = function_body("openPreviewInlineEditor")
        finish = function_body("finishPreviewInlineEditor")
        serialize = function_body("serializePreviewInlineNode")

        self.assertIn("openPreviewInlineEditor", target)
        self.assertIn('contentEditable = "true"', editor)
        self.assertIn('data-preview-format="bold"', editor)
        self.assertIn("applyProgrammaticContent", finish)
        self.assertIn('value = `**${value}**`', serialize)

    def test_preview_images_link_to_source_and_delete_only_the_reference(self):
        image_layer = function_body("createImageEditLayer")
        focus = function_body("handlePreviewImageTarget")
        remove = function_body("deletePreviewImageReference")

        self.assertIn('className = "preview-image-delete"', image_layer)
        self.assertIn("handlePreviewImageTarget", image_layer)
        self.assertIn("focusEditorRange(start, end, true)", focus)
        self.assertIn("removeContentLineAtRange", remove)
        self.assertIn("applyProgrammaticContent", remove)
        self.assertNotIn("delete state.images", remove)


class InlineFormattingInteractionContractTests(unittest.TestCase):
    def test_bold_and_italic_buttons_toggle_existing_wrappers(self):
        wrap = function_body("wrapSelection")

        self.assertIn('const marker = kind === "bold" ? "**" : "*"', wrap)
        self.assertIn("selectedHasMarkers", wrap)
        self.assertIn("selectionIsWrapped", wrap)
        self.assertIn("setSelectionRange(unwrappedStart", wrap)

    def test_color_tools_can_exit_from_the_same_toolbar_button(self):
        toggle = function_body("toggleActiveBrushFromTool")
        bind = function_body("bindEvents")

        self.assertIn("event.preventDefault()", toggle)
        self.assertIn("disableColorBrush(true)", toggle)
        self.assertIn("disableBackgroundBrush(true)", toggle)
        self.assertIn('toggleActiveBrushFromTool(event, "color")', bind)
        self.assertIn('toggleActiveBrushFromTool(event, "background")', bind)

    def test_both_color_brushes_are_single_use_and_do_not_double_apply(self):
        color = function_body("applyColorBrushToSelection")
        background = function_body("applyBackgroundBrushToSelection")
        bind = function_body("bindEvents")

        self.assertIn("disableColorBrush()", color)
        self.assertIn("disableBackgroundBrush()", background)
        self.assertNotIn('els.content.addEventListener("mouseup", applyActiveBrushToSelection)', bind)
        self.assertIn('document.addEventListener("pointerup", applyActiveBrushToSelection)', bind)
        self.assertIn("应用一次后自动结束", HTML)


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

    def test_layout_mode_rechecks_copy_before_showing_preview(self):
        signature = function_body("layoutOnlyCopySignature")
        preserves = function_body("layoutOnlyPreservesCopy")
        run = function_body("runAiOptimization")

        self.assertIn("color|bg", signature)
        self.assertIn("layoutOnlyCopySignature(before)", preserves)
        self.assertIn("layoutOnlyCopySignature(after)", preserves)
        self.assertIn('nextMode === "layout"', run)
        self.assertIn("layoutOnlyPreservesCopy(before, payload.optimizedContent)", run)
        self.assertIn("已阻止进入预览", run)


class IllustrationInteractionContractTests(unittest.TestCase):
    def test_opening_illustration_modal_is_read_only_until_explicit_search(self):
        body = function_body("openIllustrationModal")
        self.assertNotIn("fetch(", body)
        self.assertNotIn("saveState(", body)
        self.assertNotIn("runIllustrationSearch(", body)
        self.assertIn('els.workspace?.setAttribute("inert", "")', body)
        self.assertIn('els.workspace?.removeAttribute("inert")', function_body("closeIllustrationModal"))

    def test_search_and_apply_are_separate_explicit_actions(self):
        bind = function_body("bindEvents")
        self.assertIn('els.illustrationSearch?.addEventListener("click"', bind)
        self.assertIn("runIllustrationSearch()", bind)
        self.assertIn('els.illustrationApply?.addEventListener("click"', bind)
        self.assertIn("applyIllustrationSelection()", bind)
        self.assertEqual(
            APP.count("runIllustrationSearch("),
            2,
            "online search must only have its function definition and explicit button binding",
        )

    def test_search_locks_saved_project_content_and_revision(self):
        body = function_body("runIllustrationSearch")
        self.assertIn("saveState()", body)
        self.assertIn("flushProjectStoreToIndexedDb()", body)
        self.assertIn("baseUpdatedAt", body)
        self.assertIn("content: before", body)
        self.assertIn("els.content.value !== before", body)
        self.assertNotIn("state.images =", body)

    def test_import_is_all_or_nothing_and_never_keeps_remote_urls(self):
        body = function_body("applyIllustrationSelection")
        self.assertIn("for (const { candidate, block } of selected)", body)
        self.assertIn("/^data:image\\/", body)
        self.assertIn("commitIllustrationRevision", body)
        self.assertNotIn("state.images =", body)
        self.assertIn("ILLUSTRATION_MAX_TOTAL_BYTES", body)
        self.assertIn("pending.beforeContent", body)
        self.assertIn("pending.baseUpdatedAt", body)

    def test_final_project_commit_is_conditional_and_mutates_state_only_after_server_save(self):
        body = function_body("commitIllustrationRevision")
        save_at = body.index("await saveProjectStoreToSharedServer")
        mutation_at = body.index("state.projects =")
        self.assertLess(save_at, mutation_at)
        self.assertIn("expectedProjectId: pending.projectId", body)
        self.assertIn("expectedUpdatedAt: pending.baseUpdatedAt", body)
        self.assertIn("if (!committed.saved)", body)
        self.assertIn("saveProjectStoreToIndexedDb", body)

    def test_web_source_and_license_survive_resource_library_reinsert(self):
        render_library = function_body("renderAssetLibrary")
        self.assertIn("normalizeWebAssetSource(asset.source)", render_library)
        self.assertIn("asset-library-source-link", render_library)
        insert = function_body("insertAssetFromLibrary")
        self.assertIn("normalizeWebAssetSource(detail.source || asset.source)", insert)
        self.assertIn("...(source ? { source } : {})", insert)

    def test_marker_insertion_verifies_original_text_byte_for_byte(self):
        body = function_body("insertIllustrationMarkers")
        self.assertIn("originalContent.slice", body)
        self.assertIn("insertedRanges", body)
        self.assertIn("restored !== originalContent", body)
        self.assertNotIn(".trim(", body)
        self.assertNotIn(".replaceAll(", body)


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
        for theme_id in (
            "paper-ink",
            "porcelain-tech",
            "forest-note",
            "kraft-memory",
            "dune-gallery",
            "midnight-gilt",
            "swiss-blue",
            "swiss-yellow",
            "swiss-green",
            "swiss-orange",
        ):
            self.assertIn(f'"{theme_id}"', themes)
        self.assertIn('group: "editorial"', APP)
        self.assertIn('group: "swiss"', APP)
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
        self.assertIn("applyCardThemeId", apply_theme)
        apply_theme_id = function_body("applyCardThemeId")
        self.assertIn("state.cardTheme = themeId", apply_theme_id)
        self.assertIn("flushAppearanceSaveIfHydrated()", apply_theme_id)

    def test_full_theme_library_is_filterable_and_does_not_touch_content(self):
        self.assertIn('id="themeLibraryModal"', HTML)
        self.assertIn('data-theme-filter="editorial"', HTML)
        self.assertIn('data-theme-filter="swiss"', HTML)
        render = function_body("renderThemeLibrary")
        self.assertIn("Object.entries(CARD_THEMES)", render)
        self.assertIn("theme-library-item", render)
        apply_theme_id = function_body("applyCardThemeId")
        self.assertNotIn("els.content.value =", apply_theme_id)
        self.assertNotIn("state.images =", apply_theme_id)


if __name__ == "__main__":
    unittest.main()
