import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "src" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
STYLES = (ROOT / "src" / "styles.css").read_text(encoding="utf-8")


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


class IllustrationInteractionContractTests(unittest.TestCase):
    def test_online_image_search_is_not_exposed_in_the_editor(self):
        self.assertNotIn('id="illustrationBtn"', HTML)
        self.assertNotIn('id="illustrationModal"', HTML)
        self.assertNotIn("开始找图", HTML)

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


class CompactWorkbenchContractTests(unittest.TestCase):
    def test_topbar_download_keeps_scale_inside_one_menu_and_removes_scroll_shot(self):
        self.assertIn('id="downloadMenu"', HTML)
        self.assertIn('id="exportScaleSelect"', HTML)
        download_menu = HTML[HTML.index('id="downloadMenu"') : HTML.index('id="downloadMenu"') + 2200]
        self.assertIn('id="exportScaleSelect"', download_menu)
        self.assertIn('id="downloadZipBtn"', download_menu)
        self.assertNotIn('id="scrollModeBtn"', HTML)

    def test_project_actions_are_flat_and_low_frequency_ui_moves_to_left_rail(self):
        self.assertIn('id="importProjectsBtn"', HTML)
        self.assertNotIn('project-actions-menu', HTML)
        self.assertNotIn('id="convertModeBtn"', HTML)
        self.assertNotIn('id="themeToggleBtn"', HTML)
        self.assertIn('class="workspace-utilities"', HTML)
        self.assertIn('id="uiThemeSwitch"', HTML)
        self.assertIn('role="switch"', HTML)

    def test_guides_are_hidden_from_history_and_help_is_agent_friendly(self):
        history = function_body("allHistoryProjects")
        self.assertIn("state.projects", history)
        self.assertNotIn("builtInGuideProjects", history)
        self.assertIn('id="helpModal"', HTML)
        self.assertIn("[[pagebreak]]", HTML)
        self.assertIn("直接对 Codex 说", HTML)
        self.assertIn("data-copy-prompt", HTML)

    def test_article_settings_are_collapsed_until_explicitly_opened(self):
        self.assertIn('id="articleSettingsToggleBtn"', HTML)
        self.assertIn('id="articleSettings"', HTML)
        self.assertIn("let articleSettingsOpen = false", APP)
        render_article = function_body("renderArticlePreview")
        self.assertIn("!articleSettingsOpen", render_article)
        toggle = function_body("toggleArticleSettings")
        self.assertIn("articleSettingsOpen = !articleSettingsOpen", toggle)

    def test_cloud_conflict_banner_only_matches_the_exact_original_revision(self):
        update_controls = function_body("updatePersistenceControls")
        self.assertNotIn('phase: "conflict"', update_controls)
        conflict = function_body("cloudConflictForProject")
        self.assertIn("item?.projectId !== projectId", conflict)
        self.assertNotIn("conflictProjectId === projectId", conflict)
        self.assertIn("item.localUpdatedAt", conflict)
        self.assertIn("item.remoteUpdatedAt", conflict)
        checkpoint = function_body("renderSaveCheckpoint")
        self.assertIn("已保留两个版本", checkpoint)
        self.assertNotIn("检测到云端同时编辑", checkpoint)

    def test_card_dock_has_accessible_navigation_and_real_thumbnails(self):
        self.assertIn('id="pageDock"', HTML)
        self.assertIn('role="tablist"', HTML)
        self.assertIn('id="previewViewSwitch"', HTML)
        self.assertIn('data-preview-view="grid"', HTML)
        self.assertIn('data-preview-view="dock"', HTML)
        render_dock = function_body("renderPageDock")
        self.assertIn('button.setAttribute("role", "tab")', render_dock)
        self.assertIn('button.setAttribute("aria-controls"', render_dock)
        self.assertIn('context.drawImage(canvas', render_dock)
        self.assertIn("handlePageDockKeydown", render_dock)

    def test_preview_switch_is_explicit_persistent_and_keeps_grid_pages_accessible(self):
        apply_page = function_body("applyActivePreviewPage")
        self.assertIn('dataset.cardView === "dock"', apply_page)
        self.assertIn('shell.classList.toggle("is-active"', apply_page)
        self.assertIn('shell.removeAttribute("aria-hidden")', apply_page)
        self.assertIn('button.setAttribute("aria-selected"', apply_page)

        adaptive = function_body("updatePreviewCardView")
        self.assertIn("previewViewMode", adaptive)
        self.assertIn('cardView !== "dock"', adaptive)
        self.assertNotIn("getBoundingClientRect().width", adaptive)
        switch = function_body("setPreviewViewMode")
        self.assertIn("PREVIEW_VIEW_STORAGE_KEY", switch)
        self.assertIn("updatePreviewCardView()", switch)

    def test_page_style_is_promoted_to_the_front_of_the_toolbar(self):
        bind = function_body("bindEvents")
        self.assertIn("els.toolbar.prepend(els.settingsMenu)", bind)

    def test_codex_breakpoint_keeps_the_editor_resizer_and_allows_three_card_columns(self):
        self.assertIn('(min-width: 701px) and (max-width: 1800px)', STYLES)
        self.assertIn('(min-width: 701px) and (max-width: 1280px)', STYLES)
        self.assertIn("zoom: 0.82", STYLES)
        self.assertIn("grid-template-columns: 44px minmax(280px, var(--editor-width, 500px)) 6px minmax(300px, 1fr)", STYLES)
        self.assertIn('.panel-resizer[data-panel-resize="editor"]', STYLES)
        self.assertIn('.preview-panel[data-card-view="dock"] .page-dock:not([hidden])', STYLES)
        self.assertIn('.preview-panel[data-card-view="grid"] .page-dock', STYLES)
        self.assertIn('.preview-panel[data-card-view="dock"] .pages .page-shell.is-active', STYLES)
        self.assertIn('@container (min-width: 620px)', STYLES)
        self.assertIn('@container (min-width: 920px)', STYLES)
        self.assertIn('grid-template-columns: repeat(3, minmax(0, 1fr))', STYLES)

    def test_source_editor_can_be_collapsed_without_changing_project_content(self):
        self.assertIn('id="editorPanel"', HTML)
        self.assertIn('id="editorPanelToggleBtn"', HTML)
        toggle = function_body("toggleEditorPanel")
        self.assertIn("state.panelLayout.editorCollapsed", toggle)
        self.assertIn("savePanelLayout()", toggle)
        self.assertNotIn("saveState(", toggle)
        apply_layout = function_body("applyPanelLayout")
        self.assertIn('classList.toggle("editor-collapsed"', apply_layout)
        self.assertIn("els.editorPanel.hidden", apply_layout)


if __name__ == "__main__":
    unittest.main()
