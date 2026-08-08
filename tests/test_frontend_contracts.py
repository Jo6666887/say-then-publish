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
        self.assertIn("冲突备份", conflict)
        self.assertIn("__localConflictOf", conflict)
        self.assertIn("cloudBaseUpdatedAt: 0", conflict)

    def test_deleted_original_also_removes_stale_conflict_descendants(self):
        resolve = function_body("resolveProjectDeletionWinners")

        self.assertIn("__localConflictOf", resolve)
        self.assertIn("deletedIds.has(conflictRoot)", resolve)

    def test_shared_saves_require_protocol_and_server_base_revision(self):
        start = APP.index("async function saveProjectStoreToSharedServer(")
        end = APP.index("function imageReferenceSignature", start)
        save = APP[start:end]

        self.assertIn("SHARED_SAVE_PROTOCOL_HEADER", save)
        self.assertIn("SHARED_SAVE_PROTOCOL_VERSION", save)
        self.assertIn("sharedProjectVersions.get", save)
        self.assertIn('headers["X-WTP-Expected-Project-Updated-At"]', save)
        self.assertIn("projects: targetProject ? [targetProject] : []", save)

    def test_live_conflict_refreshes_canonical_and_forks_local_work_before_retry(self):
        save_start = APP.index("async function saveProjectStoreToSharedServer(")
        save_end = APP.index("function imageReferenceSignature", save_start)
        save = APP[save_start:save_end]
        recover = function_body("recoverSharedProjectConflict")
        flush = function_body("flushProjectStoreToIndexedDb")
        merge = function_body("mergeProjectWithSharedBase")

        self.assertIn('response.status === 409', save)
        self.assertIn('payload?.code === "DRAFT_VERSION_CONFLICT"', save)
        self.assertIn("loadProjectStoreFromSharedServer()", recover)
        self.assertIn("reconcileLocalProjectsWithShared", recover)
        self.assertIn("__localConflictOf", recover)
        self.assertIn("saveProjectStoreToSharedServer(recoveredSnapshot)", recover)
        self.assertIn("mergeProjectWithSharedBase(base, localActive, sharedActive)", recover)
        self.assertIn("没有创建重复副本", recover)
        self.assertIn("draftValuesMatch(normalizedLocal.title, base.title)", merge)
        self.assertIn("draftValuesMatch(sharedValue, baseValue)", merge)
        self.assertIn("recoverSharedProjectConflict(snapshot)", flush)

    def test_unchanged_draft_switch_never_creates_a_new_revision_or_shared_write(self):
        save_state = function_body("saveState")
        open_project = function_body("openProject")
        rename = function_body("updateCurrentProjectTitle")

        self.assertIn("stableJsonStringify(current.data) === stableJsonStringify(data)", save_state)
        self.assertIn("return { changed: false, project: current }", save_state)
        self.assertNotIn("saveProjectStore()", open_project)
        self.assertIn("render({ persist: false })", open_project)
        self.assertIn("restoreCachedProjectPreview(project)", open_project)
        self.assertIn("scheduleStateSave()", rename)
        self.assertNotIn("current.title =", rename)

    def test_typing_only_schedules_a_low_frequency_local_draft(self):
        schedule_database = function_body("scheduleProjectStoreToIndexedDb")
        local_flush = function_body("flushProjectStoreToLocalDatabase")
        manual_save = function_body("saveProjectNow")

        self.assertIn("LOCAL_STATE_SAVE_DELAY = 1500", APP)
        self.assertIn("LOCAL_DATABASE_SAVE_DELAY = 3000", APP)
        self.assertIn("flushProjectStoreToLocalDatabase", schedule_database)
        self.assertIn("saveProjectStoreToIndexedDb(snapshot)", local_flush)
        self.assertNotIn("saveProjectStoreToSharedServer", local_flush)
        self.assertIn("flushProjectStoreToIndexedDb()", manual_save)
        self.assertNotIn("saveCurrentProjectTextToSharedServer({ keepalive: true })", APP)

    def test_history_keeps_more_projects_and_compacts_conflict_backups(self):
        compact = function_body("compactHistoryProjects")
        history = function_body("updateProjectHistory")

        self.assertIn("MAX_PROJECTS = 120", APP)
        self.assertIn('data-history-filter="backups"', HTML)
        self.assertIn("latestConflictByRoot", compact)
        self.assertIn('state.historyFilter === "backups"', history)
        self.assertIn("compactHistoryProjects(allHistoryProjects())", history)

    def test_project_delete_requires_explicit_confirmation_before_any_tombstone(self):
        request = function_body("requestProjectDeletion")
        remove = function_body("deleteProject")

        self.assertNotIn("window.confirm", remove)
        self.assertIn("pendingHistoryDeleteProjectId === project.id", request)
        self.assertIn("确认删除", request)
        self.assertIn("deleteProject(project.id, { confirmed: true })", request)
        self.assertIn("confirmed !== true", remove)
        self.assertLess(remove.index("confirmed !== true"), remove.index("markPendingProjectDeletion"))


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

    def test_preview_images_open_a_centered_lightbox_on_double_click(self):
        image_layer = function_body("createImageEditLayer")
        open_preview = function_body("openImagePreviewFromCard")
        close_preview = function_body("closeImagePreview")

        self.assertIn('addEventListener("dblclick", openImagePreviewFromCard)', image_layer)
        self.assertIn('event.key === "Enter"', function_body("handlePreviewImageOrderKeydown"))
        self.assertIn('id="imagePreviewModal"', HTML)
        self.assertIn("imagePreviewModal.classList.remove", open_preview)
        self.assertIn('setAttribute("inert", "")', open_preview)
        self.assertIn('removeAttribute("inert")', close_preview)
        self.assertIn(".image-preview-stage", STYLES)


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


class EditorTypingPerformanceContractTests(unittest.TestCase):
    def test_editor_uses_a_slower_input_specific_preview_scheduler(self):
        request_editor = function_body("requestEditorRender")
        idle_render = function_body("runEditorPreviewRenderWhenIdle")

        self.assertIn("EDITOR_PREVIEW_RENDER_DELAY = 520", APP)
        self.assertIn("EDITOR_STATE_SAVE_DELAY = 900", APP)
        self.assertIn("scheduleStateSave(EDITOR_STATE_SAVE_DELAY)", request_editor)
        self.assertIn("prioritizeEditorInput()", request_editor)
        self.assertIn("debouncedEditorRender()", request_editor)
        self.assertIn('"requestIdleCallback" in window', idle_render)
        self.assertIn("EDITOR_PREVIEW_IDLE_TIMEOUT", idle_render)

    def test_ime_composition_never_starts_preview_rendering(self):
        content_input = function_body("handleContentInput")
        composition_start = function_body("handleContentCompositionStart")
        composition_end = function_body("handleContentCompositionEnd")
        bind = function_body("bindEvents")

        self.assertIn("editorCompositionActive", content_input)
        self.assertIn("event?.isComposing === true", content_input)
        composing_branch = content_input[content_input.index("if (composing)") : content_input.index("if (imageReferencesChanged)")]
        self.assertIn("prioritizeEditorInput()", composing_branch)
        self.assertNotIn("requestEditorRender()", composing_branch)
        self.assertIn("editorCompositionActive = true", composition_start)
        self.assertIn("editorCompositionActive = false", composition_end)
        self.assertIn("requestEditorRender()", composition_end)
        self.assertIn('addEventListener("compositionstart", handleContentCompositionStart)', bind)
        self.assertIn('addEventListener("compositionend", handleContentCompositionEnd)', bind)
        self.assertIn('addEventListener("input", handleContentInput)', bind)

    def test_debounce_can_cancel_stale_preview_work(self):
        debounce_body = function_body("debounce")
        prioritize = function_body("prioritizeEditorInput")

        self.assertIn("debounced.cancel", debounce_body)
        self.assertIn("renderGeneration += 1", prioritize)
        self.assertIn("debouncedRender.cancel()", prioritize)
        self.assertIn("cancelEditorPreviewRender()", prioritize)


class AgentNativeLayoutContractTests(unittest.TestCase):
    def test_external_ai_layout_controls_are_not_exposed(self):
        for element_id in (
            "aiOptimizeBtn",
            "aiUndoBtn",
            "aiOptimizeModal",
            "aiOptimizeGenerateBtn",
            "aiOptimizeApplyBtn",
        ):
            self.assertNotIn(f'id="{element_id}"', HTML)
        self.assertNotIn('data-api-tab="ai"', HTML)
        self.assertNotIn('data-api-panel="ai"', HTML)

    def test_help_routes_layout_work_to_the_agent(self):
        self.assertIn("把当前项目整理为 8 张图文卡片", HTML)
        self.assertIn("Agent 会读取当前项目、按版本安全修改", HTML)


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

    def test_theme_layout_allows_safe_image_bleed_without_leaving_canvas(self):
        image_size = function_body("imageBlockSize")
        self.assertIn("Math.min(requestedWidth, maxWidth, maxHeight * aspect)", image_size)
        self.assertIn("imageOffsetForAlignment", image_size)
        self.assertIn("safeBleed", function_body("imageOffsetForAlignment"))
        self.assertIn("MAX_IMAGE_FIXED_WIDTH", APP)
        self.assertIn("imageMaxWidthForBounds(page.bounds)", function_body("buildPages"))
        self.assertIn('max="125"', HTML)
        self.assertIn("allowExtendedHeight: true", function_body("resizeImageLayout"))
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

    def test_card_dock_has_accessible_numbered_navigation(self):
        self.assertIn('id="pageDock"', HTML)
        self.assertIn('role="tablist"', HTML)
        self.assertIn('id="previewViewSwitch"', HTML)
        self.assertIn('data-preview-view="grid"', HTML)
        self.assertIn('data-preview-view="dock"', HTML)
        render_dock = function_body("renderPageDock")
        self.assertIn('button.setAttribute("role", "tab")', render_dock)
        self.assertIn('button.setAttribute("aria-controls"', render_dock)
        # The dock is now a compact numbered position bar, not a thumbnail strip.
        self.assertIn('padStart(2, "0")', render_dock)
        self.assertNotIn("context.drawImage(canvas", render_dock)
        self.assertIn("handlePageDockKeydown", render_dock)

    def test_single_card_view_has_side_navigation(self):
        # Clickable left/right edge controls to flip between cards in 逐张 view.
        self.assertIn('id="stageNavPrev"', HTML)
        self.assertIn('id="stageNavNext"', HTML)
        self.assertIn('class="stage-nav prev"', HTML)
        self.assertIn('class="stage-nav next"', HTML)
        move = function_body("movePreviewPage")
        self.assertIn("clamp(activePreviewPageIndex + delta", move)
        apply_page = function_body("applyActivePreviewPage")
        self.assertIn("els.stageNavPrev", apply_page)
        self.assertIn("els.stageNavNext", apply_page)
        self.assertIn('.preview-panel[data-card-view="dock"] .stage-nav', STYLES)

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
