const CANVAS_WIDTH = 864;
const CANVAS_HEIGHT = 1152;
const CARD_SIDE_PADDING = 42;
const CARD_CONTENT_WIDTH = CANVAS_WIDTH - CARD_SIDE_PADDING * 2;
const EXPORT_IMAGE_MIME = "image/png";
const EXPORT_IMAGE_EXTENSION = ".png";
const EXPORT_ZIP_COMPRESSION = "STORE";
const OBSIDIAN_VAULT_DB = "writeThenPublishObsidianVault";
const OBSIDIAN_VAULT_STORE = "settings";
const OBSIDIAN_VAULT_KEY = "directoryHandle";
const STORAGE_KEY = "graphicTextLayoutState.v1";
const PROJECTS_STORAGE_KEY = "graphicTextLayoutProjects.v1";
const ACTIVE_PROJECT_STORAGE_KEY = "writeThenPublishActiveProject.v1";
const PENDING_PROJECT_DELETIONS_STORAGE_KEY = "writeThenPublishPendingProjectDeletions.v1";
const PANEL_LAYOUT_STORAGE_KEY = "writeThenPublishPanelLayout.v1";
const EXPORT_SCALE_STORAGE_KEY = "writeThenPublishExportScale.v1";
const UI_THEME_STORAGE_KEY = "writeThenPublishUiTheme.v1";
const PREVIEW_VIEW_STORAGE_KEY = "writeThenPublishPreviewView.v1";
const PROJECT_BACKUP_SCHEMA = "write-then-publish-projects";
const PROJECT_BACKUP_VERSION = 1;
const LOCAL_DATABASE_NAME = "writeThenPublishLocal.v1";
const LOCAL_DATABASE_STORE = "snapshots";
const LOCAL_DATABASE_PROJECTS_KEY = "projects";
const LOCAL_DATABASE_PENDING_PROJECT_DELETIONS_KEY = "pendingProjectDeletions";
const LOCAL_ASSET_DIRECTORY_KEY = "assetLibraryDirectoryHandle";
const LOCAL_STATE_SAVE_DELAY = 450;
const LOCAL_STATE_SAVE_MAX_WAIT = 5000;
const LOCAL_DATABASE_SAVE_DELAY = 1200;
const HISTORY_DELETE_CONFIRM_TIMEOUT = 5000;
const EDITOR_STATE_SAVE_DELAY = 900;
const CONTROL_PREVIEW_RENDER_DELAY = 180;
const EDITOR_PREVIEW_RENDER_DELAY = 520;
const EDITOR_PREVIEW_IDLE_TIMEOUT = 900;
const AUTO_SAVE_EXPLANATION = "停笔约 2 秒写入共享库，约 3–5 秒确认云端";
const SHARED_PROJECT_STORE_URL = "/api/project-store";
const SHARED_PROJECT_TEXT_URL = "/api/project-store/current-text";
const SHARED_SAVE_PROTOCOL_HEADER = "X-WTP-Save-Protocol";
const SHARED_SAVE_PROTOCOL_VERSION = "2";
const CLOUD_STATUS_URL = "/api/cloud-status";
const CLOUD_SYNC_URL = "/api/cloud-sync";
const AI_OPTIMIZE_STATUS_URL = "/api/ai/status";
const AI_OPTIMIZE_URL = "/api/ai/optimize-layout";
const ILLUSTRATION_STATUS_URL = "/api/illustrations/status";
const ILLUSTRATION_SEARCH_URL = "/api/illustrations/search";
const ILLUSTRATION_IMPORT_URL = "/api/illustrations/import";
const ILLUSTRATION_MAX_TOTAL_BYTES = 12 * 1024 * 1024;
const ASSET_LIBRARY_URL = "/api/assets";
const MAX_DECODED_IMAGE_CACHE = 64;
const MAX_PROJECT_PREVIEW_CACHE = 2;
const MAX_PROJECTS = 24;
const BUILT_IN_PROJECT_PREFIX = "guide_";
const GUIDE_CARDS_PROJECT_ID = `${BUILT_IN_PROJECT_PREFIX}cards`;
const GUIDE_ARTICLE_PROJECT_ID = `${BUILT_IN_PROJECT_PREFIX}article`;
const PANEL_LIMITS = {
  history: { min: 210, max: 380, fallback: 260 },
  editor: { min: 280, max: 1200, fallback: 500 },
};

let previewEditorPin = null;
let previewInlineEditor = null;
let lastEditorImageReferenceSignature = "";
let sharedTextSaveTimer = 0;
let persistenceMode = "detecting";
let assetLibraryMode = "unknown";
let localAssetDirectoryHandle = null;
let assetLibraryReturnFocus = null;
let localAssetPreviewUrls = [];
let saveCheckpointPollGeneration = 0;
let manualSaveGeneration = 0;
let pendingAiOptimization = null;
let aiOptimizeReturnFocus = null;
let aiOptimizeRequestGeneration = 0;
let aiOptimizeAbortController = null;
let aiOptimizeUiState = "closed";
let illustrationReturnFocus = null;
let illustrationRequestGeneration = 0;
let illustrationAbortController = null;
let illustrationUiState = "closed";
let pendingIllustrationSearch = null;
let themeLibraryReturnFocus = null;
let themeLibraryFilter = "all";
let helpReturnFocus = null;
let imageReorderDrag = null;
let imageReorderBusy = false;
let articleSettingsOpen = false;
let activePreviewPageIndex = 0;
let previewViewMode = "grid";

const saveCheckpoint = {
  phase: "loading",
  projectId: null,
  targetUpdatedAt: 0,
  localSavedAt: null,
  serverSavedAt: null,
  cloudSavedAt: null,
  cloudUpdatedAt: 0,
  destination: "正在确认保存位置",
  confirmation: "auto",
  error: "",
};

const $ = (selector) => document.querySelector(selector);

const els = {
  workspace: $(".workspace"),
  editorPanel: $(".editor-panel"),
  editorPanelToggle: $("#editorPanelToggleBtn"),
  previewPanel: $(".preview-panel"),
  previewFooter: $(".preview-footer"),
  toolbar: $(".toolbar"),
  settingsMenu: $(".settings-menu"),
  content: $("#contentInput"),
  pages: $("#pages"),
  pageDock: $("#pageDock"),
  pageDockTrack: $("#pageDockTrack"),
  pageDockStatus: $("#pageDockStatus"),
  stageNavPrev: $("#stageNavPrev"),
  stageNavNext: $("#stageNavNext"),
  previewViewSwitch: $("#previewViewSwitch"),
  previewViewButtons: document.querySelectorAll("[data-preview-view]"),
  pageCount: $("#pageCount"),
  projectTitle: $("#projectTitleInput"),
  projectPublishStatus: $("#projectPublishStatus"),
  status: $("#statusText"),
  saveCheckpoint: $("#saveCheckpoint"),
  saveCheckpointLabel: $("#saveCheckpointLabel"),
  saveCheckpointMeta: $("#saveCheckpointMeta"),
  saveNow: $("#saveNowBtn"),
  historySidebar: $("#historySidebar"),
  historyDrawer: $(".history-drawer"),
  historyNote: $("#historyNote"),
  historyToggle: $("#historyToggleBtn"),
  historyClose: $("#historyCloseBtn"),
  help: $("#helpBtn"),
  helpModal: $("#helpModal"),
  helpClose: $("#helpCloseBtn"),
  workspaceSettingsMenu: $("#workspaceSettingsMenu"),
  uiThemeSwitch: $("#uiThemeSwitch"),
  apiConfig: $("#apiConfig"),
  apiConfigSaveBtn: $("#apiConfigSaveBtn"),
  apiConfigStatus: $("#apiConfigStatus"),
  newProject: $("#newProjectBtn"),
  exportProjects: $("#exportProjectsBtn"),
  exportProjectsLabel: $("#exportProjectsLabel"),
  importProjects: $("#importProjectsBtn"),
  projectBackupInput: $("#projectBackupInput"),
  importPreviewModal: $("#importPreviewModal"),
  importPreviewClose: $("#importPreviewCloseBtn"),
  importPreviewCancel: $("#importPreviewCancelBtn"),
  importPreviewConfirm: $("#importPreviewConfirmBtn"),
  importPreviewFile: $("#importPreviewFile"),
  importPreviewSource: $("#importPreviewSource"),
  importPreviewSummary: $("#importPreviewSummary"),
  importPreviewList: $("#importPreviewList"),
  assetLibrary: $("#assetLibraryBtn"),
  assetLibraryModal: $("#assetLibraryModal"),
  assetLibraryDescription: $("#assetLibraryDescription"),
  assetLibraryClose: $("#assetLibraryCloseBtn"),
  assetLibraryFolder: $("#assetLibraryFolderBtn"),
  assetLibraryRefresh: $("#assetLibraryRefreshBtn"),
  assetLibraryStatus: $("#assetLibraryStatus"),
  assetLibraryGrid: $("#assetLibraryGrid"),
  aiOptimize: $("#aiOptimizeBtn"),
  aiUndo: $("#aiUndoBtn"),
  aiOptimizeModal: $("#aiOptimizeModal"),
  aiOptimizeClose: $("#aiOptimizeCloseBtn"),
  aiOptimizeStatus: $("#aiOptimizeStatus"),
  aiModeLayout: $("#aiModeLayout"),
  aiModePolish: $("#aiModePolish"),
  aiBeforePreview: $("#aiBeforePreview"),
  aiAfterPreview: $("#aiAfterPreview"),
  aiChangeList: $("#aiChangeList"),
  aiOptimizeCancel: $("#aiOptimizeCancelBtn"),
  aiOptimizeGenerate: $("#aiOptimizeGenerateBtn"),
  aiOptimizeApply: $("#aiOptimizeApplyBtn"),
  illustration: $("#illustrationBtn"),
  illustrationModal: $("#illustrationModal"),
  illustrationClose: $("#illustrationCloseBtn"),
  illustrationCancel: $("#illustrationCancelBtn"),
  illustrationStatus: $("#illustrationStatus"),
  illustrationCount: $("#illustrationCountSelect"),
  illustrationProvider: $("#illustrationProviderSelect"),
  illustrationEmpty: $("#illustrationEmpty"),
  illustrationResults: $("#illustrationResults"),
  illustrationSearch: $("#illustrationSearchBtn"),
  illustrationApply: $("#illustrationApplyBtn"),
  themeLibrary: $("#themeLibraryBtn"),
  themeLibraryModal: $("#themeLibraryModal"),
  themeLibraryClose: $("#themeLibraryCloseBtn"),
  themeLibraryGrid: $("#themeLibraryGrid"),
  themeLibraryFilters: document.querySelectorAll("[data-theme-filter]"),
  projectHistory: $("#projectHistory"),
  historyFilterButtons: document.querySelectorAll("[data-history-filter]"),
  panelResizers: document.querySelectorAll("[data-panel-resize]"),
  modeButtons: document.querySelectorAll(".mode-switch [data-app-mode]"),
  convertMode: $("#convertModeBtn"),
  headerModeToggle: $("#headerModeToggleBtn"),
  themeToggle: $("#themeToggleBtn"),
  downloadMenu: $("#downloadMenu"),
  downloadMenuLabel: $("#downloadMenuLabel"),
  downloadZip: $("#downloadZipBtn"),
  downloadArticle: $("#downloadArticleBtn"),
  exportScale: $("#exportScaleSelect"),
  scrollMode: $("#scrollModeBtn"),
  articleSettings: $("#articleSettings"),
  articleSettingsToggle: $("#articleSettingsToggleBtn"),
  articleThemeButtons: document.querySelectorAll("[data-article-theme]"),
  articleFontButtons: document.querySelectorAll("[data-article-font]"),
  articleSizeButtons: document.querySelectorAll("[data-article-size]"),
  articleColorButtons: document.querySelectorAll("[data-article-color]"),
  contentImage: $("#contentImageInput"),
  obsidianImportMenu: $("#obsidianImportMenu"),
  connectObsidianVault: $("#connectObsidianVaultBtn"),
  obsidianVaultFolder: $("#obsidianVaultFolderInput"),
  obsidianVaultStatus: $("#obsidianVaultStatus"),
  inlineColor: $("#inlineColorInput"),
  inlineBgColor: $("#inlineBgColorInput"),
  colorMenu: $("#colorMenu"),
  bgColorMenu: $("#bgColorMenu"),
  colorTool: $(".color-tool"),
  bgColorTool: $(".bg-color-tool"),
  colorGuide: $("#colorGuide"),
  colorConfirm: $("#colorConfirmBtn"),
  colorCancel: $("#colorCancelBtn"),
  bgColorConfirm: $("#bgColorConfirmBtn"),
  bgColorCancel: $("#bgColorCancelBtn"),
  find: $("#findInput"),
  replace: $("#replaceInput"),
  findNext: $("#findNextBtn"),
  replaceOne: $("#replaceOneBtn"),
  replaceAll: $("#replaceAllBtn"),
  avatarInput: $("#avatarInput"),
  avatarPreview: $("#avatarPreview"),
  cropAvatar: $("#cropAvatarBtn"),
  imageList: $("#imageList"),
  imageWidthPercent: $("#imageWidthPercentInput"),
  applyImageWidth: $("#applyImageWidthBtn"),
  fixedImageWidth: $("#fixedImageWidthInput"),
  fixedImageHeight: $("#fixedImageHeightInput"),
  applyFixedImageSize: $("#applyFixedImageSizeBtn"),
  displayName: $("#displayNameInput"),
  handle: $("#handleInput"),
  textColor: $("#textColorInput"),
  accentColor: $("#accentColorInput"),
  bgColor: $("#bgColorInput"),
  cardThemeButtons: document.querySelectorAll("[data-card-theme]"),
  cardPaletteButtons: document.querySelectorAll("[data-card-palette]"),
  fontSize: $("#fontSizeInput"),
  lineHeight: $("#lineHeightInput"),
  zhFont: $("#zhFontInput"),
  enFont: $("#enFontInput"),
  imageHeight: $("#imageHeightInput"),
  cropModal: $("#cropModal"),
  cropCanvas: $("#cropCanvas"),
  cropTitle: $("#cropTitle"),
  cropSubtitle: $("#cropSubtitle"),
  cropClose: $("#cropCloseBtn"),
  cropApply: $("#cropApplyBtn"),
  cropReset: $("#cropResetBtn"),
  ratioButtons: document.querySelectorAll("[data-ratio]"),
};

const sampleAvatar =
  "data:image/svg+xml;charset=utf-8," +
  encodeURIComponent(`
<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160" viewBox="0 0 160 160">
  <rect width="160" height="160" fill="#b8dd8a"/>
  <circle cx="80" cy="82" r="55" fill="#f5f3d8" stroke="#223622" stroke-width="7"/>
  <path d="M42 48c16-15 56-16 76 1" fill="none" stroke="#223622" stroke-width="8" stroke-linecap="round"/>
  <circle cx="59" cy="75" r="7" fill="#223622"/>
  <circle cx="100" cy="75" r="7" fill="#223622"/>
  <path d="M63 105c10 9 25 9 35 0" fill="none" stroke="#223622" stroke-width="7" stroke-linecap="round"/>
  <rect x="39" y="62" width="31" height="20" rx="6" fill="none" stroke="#223622" stroke-width="5"/>
  <rect x="90" y="62" width="31" height="20" rx="6" fill="none" stroke="#223622" stroke-width="5"/>
  <path d="M70 72h20" stroke="#223622" stroke-width="5"/>
</svg>`);

const sampleImage =
  "data:image/svg+xml;charset=utf-8," +
  encodeURIComponent(`
<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="650" viewBox="0 0 1200 650">
  <defs>
    <linearGradient id="g" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0" stop-color="#f3efe6"/>
      <stop offset="0.48" stop-color="#d9e8e0"/>
      <stop offset="1" stop-color="#efc8a2"/>
    </linearGradient>
  </defs>
  <rect width="1200" height="650" fill="url(#g)"/>
  <rect x="95" y="95" width="1010" height="460" rx="34" fill="#ffffff" opacity=".45"/>
  <circle cx="735" cy="305" r="132" fill="#222831"/>
  <circle cx="735" cy="230" r="62" fill="#f5d8c9"/>
  <path d="M605 502c23-111 234-113 260 0" fill="#111827"/>
  <rect x="210" y="318" width="305" height="25" rx="12" fill="#243447"/>
  <circle cx="538" cy="331" r="45" fill="#111827"/>
  <path d="M190 420h370" stroke="#ffffff" stroke-width="9" opacity=".65"/>
  <path d="M190 462h330" stroke="#ffffff" stroke-width="9" opacity=".65"/>
  <text x="600" y="598" text-anchor="middle" font-size="36" fill="#ffffff" font-family="Arial, sans-serif">Image placeholder</text>
</svg>`);

const creatorProfile = Object.freeze({
  platform: String(window.SAY_THEN_PUBLISH_PROFILE?.platform || "小红书").trim() || "小红书",
  displayName: String(window.SAY_THEN_PUBLISH_PROFILE?.displayName || "你的小红书账号").trim() || "你的小红书账号",
  handle: String(window.SAY_THEN_PUBLISH_PROFILE?.handle || "小红书").trim() || "小红书",
});

const verifiedBadgeSrc =
  "data:image/svg+xml;charset=utf-8," +
  encodeURIComponent(`
<svg xmlns="http://www.w3.org/2000/svg" width="112" height="112" viewBox="0 0 112 112">
  <g fill="#1d9bf0">
    <circle cx="56" cy="56" r="34"/>
    <circle cx="56" cy="25" r="18"/>
    <circle cx="78" cy="34" r="18"/>
    <circle cx="87" cy="56" r="18"/>
    <circle cx="78" cy="78" r="18"/>
    <circle cx="56" cy="87" r="18"/>
    <circle cx="34" cy="78" r="18"/>
    <circle cx="25" cy="56" r="18"/>
    <circle cx="34" cy="34" r="18"/>
  </g>
  <path d="M34 55.5 48.5 70 79 36" fill="none" stroke="#fff" stroke-width="11" stroke-linecap="square" stroke-linejoin="miter"/>
</svg>`);

const FONT_STACKS = {
  "zh-system": '"PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif',
  "zh-song": '"Songti SC", SimSun, "Noto Serif CJK SC", serif',
  "zh-kai": '"Kaiti SC", KaiTi, STKaiti, serif',
  "zh-hei": 'STHeiti, "Heiti SC", "Microsoft YaHei", sans-serif',
  "en-system": '-apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif',
  "en-serif": 'Georgia, "Times New Roman", Times, serif',
  "en-rounded": '"Arial Rounded MT Bold", "Avenir Next", Arial, sans-serif',
  "en-mono": '"SFMono-Regular", Menlo, Consolas, monospace',
};

const UI_THEMES = ["light", "dark"];

const UI_THEME_LABELS = {
  light: "白色",
  dark: "黑色",
};

const CARD_PALETTES = {
  paper: {
    label: "纯白",
    textColor: "#202938",
    accentColor: "#2563eb",
    bgColor: "#ffffff",
  },
  warm: {
    label: "暖纸",
    textColor: "#302820",
    accentColor: "#b45309",
    bgColor: "#fff8ed",
  },
  mist: {
    label: "雾蓝",
    textColor: "#202938",
    accentColor: "#4f46e5",
    bgColor: "#f2f5ff",
  },
  sage: {
    label: "青苔",
    textColor: "#243229",
    accentColor: "#15803d",
    bgColor: "#f1f7f1",
  },
  blush: {
    label: "淡粉",
    textColor: "#35252b",
    accentColor: "#be185d",
    bgColor: "#fff3f6",
  },
  night: {
    label: "深夜",
    textColor: "#f8fafc",
    accentColor: "#a5b4fc",
    bgColor: "#111827",
  },
};

const CARD_THEME_DEFAULT = "social-clean";

function createEditorialCardTheme({
  id,
  label,
  description,
  textColor,
  accentColor,
  bgColor,
  secondaryColor,
  dark = false,
}) {
  return {
    id,
    label,
    description,
    group: "editorial",
    family: "editorial",
    previewColors: [bgColor, textColor, accentColor],
    backgroundStyle: "flat",
    secondaryColor,
    identityPlacement: "bottom",
    geometry: { sidePadding: 58, topWithAuthor: 78, topWithoutAuthor: 78, bottom: 1014 },
    identity: { x: 58, y: 1062, avatarSize: 36, nameSize: 18, handleSize: 15 },
    typography: {
      h1: { scale: 1.45, lineHeight: 1.42, weight: 500, marginTop: 27, marginBottom: 13, headingFont: "zh-song" },
      h2: { scale: 1.18, lineHeight: 1.5, weight: 520, marginTop: 24, marginBottom: 8, headingFont: "zh-song" },
      h3: { scale: 1.05, lineHeight: 1.54, weight: 580, marginTop: 19, marginBottom: 6, headingFont: "zh-song" },
      paragraph: { marginTop: 8 },
    },
    imageRadius: 2,
    emphasis: "editorial",
    pageNumber: "bottom-right",
    footer: "author",
    openingQuote: true,
    defaults: {
      textColor,
      accentColor,
      bgColor,
      fontSize: 30,
      lineHeight: 1.78,
      zhFont: "zh-song",
      enFont: "en-serif",
      imageHeight: 430,
      headerMode: "every",
    },
  };
}

function createSwissCardTheme({
  id,
  label,
  description,
  accentColor,
  accentOn,
}) {
  return {
    id,
    label,
    description,
    group: "swiss",
    family: "swiss",
    previewColors: ["#fafaf8", "#0a0a0a", accentColor],
    backgroundStyle: "swiss-grid",
    accentOn,
    identityPlacement: "top",
    geometry: { sidePadding: 54, topWithAuthor: 142, topWithoutAuthor: 60, bottom: 1078 },
    identity: { x: 54, y: 42, avatarSize: 56, nameSize: 23, handleSize: 18, accentName: false },
    typography: {
      h1: { scale: 1.58, lineHeight: 1.28, weight: 300, marginTop: 28, marginBottom: 15 },
      h2: { scale: 1.22, lineHeight: 1.42, weight: 380, marginTop: 24, marginBottom: 9 },
      h3: { scale: 1.08, lineHeight: 1.48, weight: 580, marginTop: 18, marginBottom: 6 },
      paragraph: { marginTop: 7 },
    },
    imageRadius: 0,
    emphasis: "swiss",
    pageNumber: "top-right",
    footer: "hairline",
    openingQuote: false,
    defaults: {
      textColor: "#0a0a0a",
      accentColor,
      bgColor: "#fafaf8",
      fontSize: 30,
      lineHeight: 1.68,
      zhFont: "zh-system",
      enFont: "en-system",
      imageHeight: 470,
      headerMode: "first",
    },
  };
}

const CARD_THEMES = {
  "social-clean": {
    label: "社交原生",
    description: "熟悉的社交卡片结构，作者信息置顶。",
    group: "native",
    family: "social",
    previewColors: ["#ffffff", "#202938", "#2563eb"],
    backgroundStyle: "flat",
    identityPlacement: "top",
    geometry: { sidePadding: 42, topWithAuthor: 158, topWithoutAuthor: 42, bottom: 1090 },
    identity: { x: 42, y: 38, avatarSize: 82, nameSize: 30, handleSize: 29 },
    typography: {
      h1: { scale: 1.36, lineHeight: 1.45, weight: 650, marginTop: 22, marginBottom: 10 },
      h2: { scale: 1.12, lineHeight: 1.55, weight: 560, marginTop: 20, marginBottom: 6 },
      h3: { scale: 1.02, lineHeight: 1.55, weight: 620, marginTop: 16, marginBottom: 4 },
      paragraph: { marginTop: 5 },
    },
    imageRadius: 13,
    emphasis: "pill",
    pageNumber: "none",
    footer: "none",
    defaults: {
      textColor: "#202938",
      accentColor: "#2563eb",
      bgColor: "#ffffff",
      fontSize: 31,
      lineHeight: 1.65,
      zhFont: "zh-system",
      enFont: "en-system",
      imageHeight: 520,
      headerMode: "every",
    },
  },
  "creator-white": {
    label: "创作者白",
    description: "轻盈白底、橙色作者名与右上页码。",
    group: "native",
    family: "social",
    previewColors: ["#ffffff", "#282824", "#ef6b35"],
    backgroundStyle: "flat",
    identityPlacement: "top",
    geometry: { sidePadding: 52, topWithAuthor: 150, topWithoutAuthor: 58, bottom: 1078 },
    identity: { x: 52, y: 42, avatarSize: 64, nameSize: 25, handleSize: 20, accentName: true },
    typography: {
      h1: { scale: 1.42, lineHeight: 1.34, weight: 720, marginTop: 25, marginBottom: 12 },
      h2: { scale: 1.16, lineHeight: 1.48, weight: 680, marginTop: 24, marginBottom: 8 },
      h3: { scale: 1.05, lineHeight: 1.52, weight: 650, marginTop: 18, marginBottom: 5 },
      paragraph: { marginTop: 7 },
    },
    imageRadius: 10,
    emphasis: "accent-underline",
    pageNumber: "top-right",
    footer: "hairline",
    defaults: {
      textColor: "#282824",
      accentColor: "#ef6b35",
      bgColor: "#ffffff",
      fontSize: 30,
      lineHeight: 1.72,
      zhFont: "zh-system",
      enFont: "en-rounded",
      imageHeight: 500,
      headerMode: "first",
    },
  },
  "highlight-note": {
    label: "荧光笔记",
    description: "暖白纸张与马克笔式重点，适合教程清单。",
    group: "native",
    family: "social",
    previewColors: ["#fffdf7", "#2d2b25", "#6f7f29"],
    backgroundStyle: "flat",
    identityPlacement: "top",
    geometry: { sidePadding: 50, topWithAuthor: 150, topWithoutAuthor: 56, bottom: 1072 },
    identity: { x: 50, y: 42, avatarSize: 64, nameSize: 25, handleSize: 20, accentName: true },
    typography: {
      h1: { scale: 1.4, lineHeight: 1.36, weight: 720, marginTop: 24, marginBottom: 12 },
      h2: { scale: 1.16, lineHeight: 1.5, weight: 680, marginTop: 22, marginBottom: 8 },
      h3: { scale: 1.05, lineHeight: 1.52, weight: 650, marginTop: 18, marginBottom: 5 },
      paragraph: { marginTop: 7 },
    },
    imageRadius: 7,
    emphasis: "marker",
    pageNumber: "bottom-right",
    footer: "double-line",
    defaults: {
      textColor: "#2d2b25",
      accentColor: "#6f7f29",
      bgColor: "#fffdf7",
      fontSize: 30,
      lineHeight: 1.68,
      zhFont: "zh-system",
      enFont: "en-system",
      imageHeight: 480,
      headerMode: "first",
    },
  },
  "minimal-opinion": {
    label: "极简观点",
    description: "克制留白与粗细对比，突出短观点。",
    group: "native",
    family: "social",
    previewColors: ["#ffffff", "#292823", "#292823"],
    backgroundStyle: "flat",
    identityPlacement: "top",
    geometry: { sidePadding: 64, topWithAuthor: 154, topWithoutAuthor: 64, bottom: 1068 },
    identity: { x: 64, y: 44, avatarSize: 62, nameSize: 24, handleSize: 19 },
    typography: {
      h1: { scale: 1.34, lineHeight: 1.4, weight: 720, marginTop: 30, marginBottom: 14 },
      h2: { scale: 1.1, lineHeight: 1.56, weight: 700, marginTop: 28, marginBottom: 10 },
      h3: { scale: 1.02, lineHeight: 1.58, weight: 680, marginTop: 22, marginBottom: 7 },
      paragraph: { marginTop: 9 },
    },
    imageRadius: 3,
    emphasis: "bold-line",
    pageNumber: "bottom-center",
    footer: "none",
    defaults: {
      textColor: "#292823",
      accentColor: "#292823",
      bgColor: "#ffffff",
      fontSize: 31,
      lineHeight: 1.82,
      zhFont: "zh-hei",
      enFont: "en-system",
      imageHeight: 470,
      headerMode: "first",
    },
  },
  magazine: {
    label: "观点杂志",
    description: "原有宋体长文模板，底部保留作者署名。",
    group: "native",
    family: "social",
    previewColors: ["#fffdfa", "#2f2b28", "#4f7d43"],
    backgroundStyle: "flat",
    identityPlacement: "bottom",
    geometry: { sidePadding: 58, topWithAuthor: 86, topWithoutAuthor: 86, bottom: 1018 },
    identity: { x: 58, y: 1060, avatarSize: 38, nameSize: 19, handleSize: 16 },
    typography: {
      h1: { scale: 1.38, lineHeight: 1.38, weight: 720, marginTop: 26, marginBottom: 12, headingFont: "zh-hei" },
      h2: { scale: 1.14, lineHeight: 1.5, weight: 680, marginTop: 24, marginBottom: 8, headingFont: "zh-hei" },
      h3: { scale: 1.04, lineHeight: 1.54, weight: 650, marginTop: 20, marginBottom: 6, headingFont: "zh-hei" },
      paragraph: { marginTop: 8 },
    },
    imageRadius: 14,
    emphasis: "editorial",
    pageNumber: "bottom-right",
    footer: "author",
    openingQuote: true,
    defaults: {
      textColor: "#2f2b28",
      accentColor: "#4f7d43",
      bgColor: "#fffdfa",
      fontSize: 30,
      lineHeight: 1.82,
      zhFont: "zh-song",
      enFont: "en-serif",
      imageHeight: 400,
      headerMode: "every",
    },
  },
  "paper-ink": createEditorialCardTheme({
    id: "paper-ink",
    label: "纸墨经典",
    description: "黑墨与暖纸，适合商业评论、AI 随笔与产品思考。",
    textColor: "#1c1b18",
    accentColor: "#45423b",
    bgColor: "#f7f6f2",
    secondaryColor: "#dedad0",
  }),
  "porcelain-tech": createEditorialCardTheme({
    id: "porcelain-tech",
    label: "瓷蓝研究",
    description: "冷静瓷白与深蓝，适合科技、研究、数据与 AI。",
    textColor: "#14263d",
    accentColor: "#3f678f",
    bgColor: "#f4f7f8",
    secondaryColor: "#dce5eb",
  }),
  "forest-note": createEditorialCardTheme({
    id: "forest-note",
    label: "森林手记",
    description: "柔暖纸色与森林绿，适合自然、户外与生活观察。",
    textColor: "#1b2b22",
    accentColor: "#3f7057",
    bgColor: "#f1f4ee",
    secondaryColor: "#dbe5dc",
  }),
  "kraft-memory": createEditorialCardTheme({
    id: "kraft-memory",
    label: "牛皮记忆",
    description: "旧纸与棕墨质感，适合手作、阅读、记忆和人物故事。",
    textColor: "#30251b",
    accentColor: "#9b6742",
    bgColor: "#f0e2cc",
    secondaryColor: "#ddc5a3",
  }),
  "dune-gallery": createEditorialCardTheme({
    id: "dune-gallery",
    label: "沙丘画廊",
    description: "低饱和沙色，适合作品集、设计与物件研究。",
    textColor: "#29241d",
    accentColor: "#877354",
    bgColor: "#f1e9dc",
    secondaryColor: "#ddd0ba",
  }),
  "midnight-gilt": createEditorialCardTheme({
    id: "midnight-gilt",
    label: "午夜鎏金",
    description: "唯一深色纸墨主题，适合夜景、影视与暗色题材。",
    textColor: "#f0e8da",
    accentColor: "#caa15a",
    bgColor: "#151513",
    secondaryColor: "#332b20",
    dark: true,
  }),
  "swiss-blue": createSwissCardTheme({
    id: "swiss-blue",
    label: "瑞士蓝",
    description: "严格网格与高纯度蓝，适合 AI、产品、工程与方法论。",
    accentColor: "#123bb6",
    accentOn: "#ffffff",
  }),
  "swiss-yellow": createSwissCardTheme({
    id: "swiss-yellow",
    label: "瑞士柠黄",
    description: "高亮黄色与黑色大字，适合年轻消费、零售和运动。",
    accentColor: "#f3cf00",
    accentOn: "#0a0a0a",
  }),
  "swiss-green": createSwissCardTheme({
    id: "swiss-green",
    label: "瑞士新绿",
    description: "现代荧光绿，适合健康、生态、未来与新兴科技。",
    accentColor: "#b9db16",
    accentOn: "#0a0a0a",
  }),
  "swiss-orange": createSwissCardTheme({
    id: "swiss-orange",
    label: "瑞士安全橙",
    description: "高警示橙色，适合风险、纠偏、工业与决策信息。",
    accentColor: "#f26a3d",
    accentOn: "#ffffff",
  }),
};

function normalizeCardTheme(value) {
  return CARD_THEMES[value] ? value : CARD_THEME_DEFAULT;
}

function cardThemeFor(settings = state) {
  return CARD_THEMES[normalizeCardTheme(settings.cardTheme)];
}

const defaultText = `[[image:sample]]

她说，如果你无聊的时候，不想只是刷手机，可以让 AI 做一件事：

“请你从某个领域里，选择一个研究生水平的概念。然后写一个寓言故事，用间接的方式把这个概念讲清楚。不要一开始就说答案，尽量到故事快结束的时候，才让人意识到原来讲的是这个概念。故事结束后，再解释这个概念，以及故事里的隐喻分别对应什么。”

## 你可以继续补充你的长文本

系统会根据每一页能容纳的行数自动切割，保留大标题、小标题、加粗、斜体、颜色和图片。`;

const state = {
  avatar: sampleAvatar,
  avatarCrop: null,
  images: {
    sample: {
      src: sampleImage,
      name: "sample",
    },
  },
  canvases: [],
  lastFindIndex: -1,
  mode: "auto",
  scrollOffset: 0,
  scrollMax: 0,
  colorBrush: false,
  bgColorBrush: false,
  uiTheme: "light",
  cardTheme: CARD_THEME_DEFAULT,
  headerMode: "every",
  appMode: "cards",
  articleTheme: "wechat",
  articleFont: "sans",
  articleSize: "normal",
  articleColor: "#0f766e",
  currentProjectId: null,
  projects: [],
  deletedProjects: [],
  historyFilter: "all",
  exportScale: 2,
  localDatabaseHydrated: false,
  lastAiRevision: null,
  panelLayout: {
    history: PANEL_LIMITS.history.fallback,
    editor: PANEL_LIMITS.editor.fallback,
    editorCollapsed: false,
  },
};

let localDatabaseSaveTimer = 0;
let localDatabaseSaveChain = Promise.resolve(true);
let pendingProjectDeletionSaveChain = Promise.resolve({ saved: true, deletions: [] });
let pendingProjectDeletionsCache = null;
let pendingHistoryDeleteProjectId = null;
let pendingHistoryDeleteTimer = 0;
let legacyStateLocalStorageUnavailable = false;
let projectStoreLocalStorageUnavailable = false;
let sharedProjectStoreAvailable = null;
const sharedProjectVersions = new Map();
const sharedProjectIds = new Set();
const sharedProjectBases = new Map();
let localStateSaveTimer = 0;
let localStateSaveMaxTimer = 0;
let renderGeneration = 0;
let editorCompositionActive = false;
let editorRenderIdleCallback = 0;
const decodedImageCache = new Map();
const projectPreviewCache = new Map();
let pendingProjectImport = null;

const textHistory = {
  stack: [],
  index: -1,
  timer: null,
  restoring: false,
  max: 80,
};

const cropper = {
  target: null,
  image: null,
  rect: null,
  aspect: null,
  display: null,
  drag: null,
};

let imageEditDrag = null;
const obsidianVault = {
  handle: null,
  fileLookup: null,
  loading: false,
  importing: false,
};

function defaultFormState() {
  return {
    content: defaultText,
    published: false,
    displayName: creatorProfile.displayName,
    handle: creatorProfile.handle,
    textColor: "#202938",
    accentColor: "#2563eb",
    bgColor: "#ffffff",
    fontSize: "31",
    lineHeight: "1.65",
    zhFont: "zh-system",
    enFont: "en-system",
    imageHeight: "520",
    cardTheme: CARD_THEME_DEFAULT,
    headerMode: "every",
    appMode: "cards",
    articleTheme: "wechat",
    articleFont: "sans",
    articleSize: "normal",
    articleColor: "#0f766e",
    avatar: sampleAvatar,
    avatarCrop: null,
    images: defaultImages(),
    lastAiRevision: null,
  };
}

function blankFormState() {
  return {
    ...defaultFormState(),
    content: "",
    images: {},
  };
}

const cardsGuideText = `# 图文卡片说明书

这是一份内置说明书，用来快速看懂图文卡片模式。它不会被修改，也不能删除。

## 适合什么内容

- 小红书图文
- X 长帖截图
- 知识卡片
- 长文拆条
- 带图片的教程内容

## 基本流程

1. 在左侧输入或粘贴正文。
2. 使用 H1、H2、加粗、斜体、引用、颜色和文字背景色整理重点。
3. 点击图片按钮插入正文图片。
4. 选择“每页头像”或“仅首页头像”。
5. 在右侧检查分页效果。
6. 点击单张下载或批量下载。

## 常用写法

用 \`# 标题\` 生成大标题。

用 \`## 小标题\` 生成段落标题。

用 \`**重点文字**\` 加粗。

用 \`*斜体文字*\` 倾斜。

用 \`> 引用内容\` 做引用块。

用颜色刷和背景色刷突出重点。

## 图片规则

插入图片后，编辑框里会出现类似：

\`[[image:img_xxxxx]]\`

这行代表图片位置。你可以把它移动到任意段落之间。

在右侧预览里点击图片，可以调节图片宽度和对齐方式。

## 分页建议

如果某一页太满，优先减少长段落，而不是缩小字号。图文卡片的重点是“读起来不累”，不是把所有字塞进去。

单次回车会在同一段内手动换行。

空出来的行会在右侧图文卡片里保留为空白行。你想留几行，就在左侧留几行。

## 头像显示

默认每一页都显示头像、名称和昵称。

如果你只想第一张显示个人信息，点击“仅首页头像”。`;

const articleGuideText = `# 长文说明书

这是一份内置说明书，用来快速看懂长文模式。它不会被修改，也不能删除。

长文模式适合把内容整理成完整文章，而不是拆成多张图。

## 适合什么内容

- 公众号文章草稿
- Markdown 长文
- 方法论文章
- 产品介绍
- 图文内容沉淀

## 基本流程

1. 切换到“长文”。
2. 在左侧输入 Markdown 内容。
3. 在右侧查看长文预览。
4. 调整主题、字体、字号和主题色。
5. 需要拆成图文时，点击“转图文”。

## 推荐结构

# 主标题

开头先讲清楚这篇文章解决什么问题。

## 第一部分

用短段落展开观点。每段尽量只讲一件事。

> 可以用引用块放关键判断、金句或提醒。

## 第二部分

中间可以插入图片，辅助说明复杂内容。

## 结尾

最后做总结，给读者一个明确动作。

## Markdown 写法

- \`#\` 一级标题
- \`##\` 二级标题
- \`###\` 三级标题
- \`**文字**\` 加粗
- \`*文字*\` 斜体
- \`> 内容\` 引用
- \`- 内容\` 列表
- \`[[image:img_xxxxx]]\` 图片

## 和图文模式互转

长文没写完也可以转图文。

图文没排完也可以转长文。

转换只改变排版方式，不会替你重写内容。`;

function builtInGuideProjects() {
  const cardsData = migrateStoredState({
    ...defaultFormState(),
    content: cardsGuideText,
    appMode: "cards",
    headerMode: "every",
    images: {},
  });
  const articleData = migrateStoredState({
    ...defaultFormState(),
    content: articleGuideText,
    appMode: "article",
    images: {},
  });
  return [
    {
      id: GUIDE_CARDS_PROJECT_ID,
      title: "图文卡片说明书",
      updatedAt: 0,
      data: cardsData,
      builtIn: true,
    },
    {
      id: GUIDE_ARTICLE_PROJECT_ID,
      title: "长文说明书",
      updatedAt: 0,
      data: articleData,
      builtIn: true,
    },
  ];
}

function isBuiltInProjectId(projectId) {
  return String(projectId || "").startsWith(BUILT_IN_PROJECT_PREFIX);
}

function isBuiltInProject(project) {
  return Boolean(project?.builtIn || isBuiltInProjectId(project?.id));
}

function allHistoryProjects() {
  return [...state.projects];
}

function findHistoryProject(projectId) {
  return allHistoryProjects().find((project) => project.id === projectId) || null;
}

function syncGuideReadOnlyMode() {
  const readOnly = isBuiltInProjectId(state.currentProjectId);
  document.body.dataset.guideReadonly = readOnly ? "true" : "false";
  els.content.readOnly = readOnly;
  els.content.setAttribute("aria-readonly", readOnly ? "true" : "false");
  if (els.projectTitle) {
    els.projectTitle.disabled = readOnly;
    els.projectTitle.setAttribute("aria-disabled", readOnly ? "true" : "false");
  }

  document
    .querySelectorAll(
      ".mode-switch button, #projectPublishStatus, #convertModeBtn, #headerModeToggleBtn, #themeToggleBtn, .editor-controls button, .editor-controls input, .editor-controls select, .editor-controls summary",
    )
    .forEach((control) => {
      if (control instanceof HTMLDetailsElement) return;
      if ("disabled" in control) control.disabled = readOnly;
      control.setAttribute("aria-disabled", readOnly ? "true" : "false");
      if (readOnly) {
        control.dataset.previousTabIndex = control.getAttribute("tabindex") || "";
        control.setAttribute("tabindex", "-1");
      } else {
        const previousTabIndex = control.dataset.previousTabIndex;
        if (previousTabIndex) {
          control.setAttribute("tabindex", previousTabIndex);
        } else {
          control.removeAttribute("tabindex");
        }
        delete control.dataset.previousTabIndex;
      }
    });

  if (readOnly) {
    document.querySelectorAll(".editor-controls details[open]").forEach((details) => details.removeAttribute("open"));
  }
}

function readForm() {
  return {
    content: els.content.value,
    published: els.projectPublishStatus?.value === "published",
    displayName: els.displayName.value.trim() || "未命名作者",
    handle: normalizeHandle(els.handle.value),
    textColor: normalizeHexColor(els.textColor.value, "#202938"),
    accentColor: normalizeHexColor(els.accentColor.value, "#2563eb"),
    bgColor: normalizeHexColor(els.bgColor.value, "#ffffff"),
    fontSize: clamp(Number(els.fontSize.value) || 31, 24, 40),
    lineHeight: clamp(Number(els.lineHeight.value) || 1.65, 1, 2.4),
    zhFont: FONT_STACKS[els.zhFont.value] ? els.zhFont.value : "zh-system",
    enFont: FONT_STACKS[els.enFont.value] ? els.enFont.value : "en-system",
    imageHeight: clamp(Number(els.imageHeight.value) || 520, 220, 760),
    cardTheme: normalizeCardTheme(state.cardTheme),
    headerMode: state.headerMode === "first" ? "first" : "every",
    appMode: state.appMode === "article" ? "article" : "cards",
    articleTheme: normalizeArticleTheme(state.articleTheme),
    articleFont: normalizeArticleFont(state.articleFont),
    articleSize: normalizeArticleSize(state.articleSize),
    articleColor: normalizeArticleColor(state.articleColor),
    avatar: state.avatar,
    avatarCrop: state.avatarCrop,
    images: state.images,
    lastAiRevision: state.lastAiRevision,
  };
}

function applyForm(data) {
  manualSaveGeneration += 1;
  disableActiveBrushes();
  els.content.value = data.content ?? defaultText;
  if (els.projectPublishStatus) {
    els.projectPublishStatus.value = data.published === true ? "published" : "unpublished";
  }
  els.displayName.value = data.displayName ?? creatorProfile.displayName;
  els.handle.value = data.handle ?? creatorProfile.handle;
  els.textColor.value = normalizeHexColor(data.textColor, "#202938");
  els.accentColor.value = normalizeHexColor(data.accentColor, "#2563eb");
  els.bgColor.value = normalizeHexColor(data.bgColor, "#ffffff");
  els.fontSize.value = data.fontSize ?? "31";
  els.lineHeight.value = data.lineHeight ?? "1.65";
  els.zhFont.value = FONT_STACKS[data.zhFont] ? data.zhFont : "zh-system";
  els.enFont.value = FONT_STACKS[data.enFont] ? data.enFont : "en-system";
  els.imageHeight.value = data.imageHeight ?? "520";
  state.cardTheme = normalizeCardTheme(data.cardTheme);
  state.headerMode = data.headerMode === "first" ? "first" : "every";
  state.appMode = data.appMode === "article" ? "article" : "cards";
  state.articleTheme = normalizeArticleTheme(data.articleTheme);
  state.articleFont = normalizeArticleFont(data.articleFont);
  state.articleSize = normalizeArticleSize(data.articleSize);
  state.articleColor = normalizeArticleColor(data.articleColor);
  updateAppMode();
  updateHeaderModeButton();
  updateArticleControls();
  state.avatar = data.avatar || sampleAvatar;
  state.avatarCrop = data.avatarCrop || null;
  state.images = normalizeImagesForContent(data.content, data.images);
  state.lastAiRevision = normalizeAiRevision(data.lastAiRevision);
  lastEditorImageReferenceSignature = imageReferenceSignature(els.content.value);
  updateAvatarPreview();
  document.documentElement.style.setProperty("--brush-color", els.inlineColor.value);
  document.documentElement.style.setProperty("--text-bg-brush-color", els.inlineBgColor.value);
  updateImageList();
  syncCardThemeControls();
  syncCardPaletteControls();
  syncAiUndoAvailability();
  const currentProject = findHistoryProject(state.currentProjectId);
  if (els.projectTitle) {
    els.projectTitle.value = isBuiltInProject(currentProject)
      ? currentProject?.title || ""
      : currentProject?.title || (state.currentProjectId ? projectTitleFromData(data) : "");
  }
}

function normalizeHexColor(value, fallback = "#000000") {
  const match = String(value || "").trim().match(/^#?([0-9a-f]{6})$/i);
  if (match) return `#${match[1].toLowerCase()}`;
  const fallbackMatch = String(fallback || "").trim().match(/^#?([0-9a-f]{6})$/i);
  return fallbackMatch ? `#${fallbackMatch[1].toLowerCase()}` : "#000000";
}

function loadUiTheme(fallback = "light") {
  try {
    const stored = localStorage.getItem(UI_THEME_STORAGE_KEY);
    if (UI_THEMES.includes(stored)) return stored;
  } catch {
    // 界面偏好读取失败不影响项目内容。
  }
  return UI_THEMES.includes(fallback) ? fallback : "light";
}

function loadPreviewViewMode() {
  try {
    return localStorage.getItem(PREVIEW_VIEW_STORAGE_KEY) === "dock" ? "dock" : "grid";
  } catch {
    return "grid";
  }
}

function syncPreviewViewControls() {
  els.previewViewButtons.forEach((button) => {
    const active = button.dataset.previewView === previewViewMode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function setPreviewViewMode(mode, { announce = false, persist = true } = {}) {
  previewViewMode = mode === "dock" ? "dock" : "grid";
  if (persist) {
    try {
      localStorage.setItem(PREVIEW_VIEW_STORAGE_KEY, previewViewMode);
    } catch {
      // 预览偏好保存失败不影响项目内容。
    }
  }
  syncPreviewViewControls();
  updatePreviewCardView();
  if (announce && els.status) {
    els.status.textContent = previewViewMode === "grid" ? "已切换为网格浏览" : "已切换为逐张预览";
  }
}

function setUiTheme(theme, announce = false, persist = true) {
  const normalizedTheme = theme === "ink" ? "dark" : theme === "paper" ? "light" : theme;
  const nextTheme = UI_THEMES.includes(normalizedTheme) ? normalizedTheme : "light";
  state.uiTheme = nextTheme;
  document.documentElement.dataset.uiTheme = nextTheme;
  if (persist) {
    try {
      localStorage.setItem(UI_THEME_STORAGE_KEY, nextTheme);
    } catch {
      // 界面偏好写入失败不影响当前会话。
    }
  }
  if (els.themeToggle) {
    const label = UI_THEME_LABELS[nextTheme];
    els.themeToggle.title = `切换软件界面明暗：当前${label}界面`;
    els.themeToggle.setAttribute("aria-label", `切换软件界面明暗，当前${label}界面`);
  }
  if (els.uiThemeSwitch) {
    const dark = nextTheme === "dark";
    els.uiThemeSwitch.checked = dark;
    els.uiThemeSwitch.setAttribute("aria-label", dark ? "切换为浅色界面" : "切换为深色界面");
  }
  if (announce) {
    els.status.textContent = `软件界面已切换为${UI_THEME_LABELS[nextTheme]}，卡片成品颜色保持不变`;
  }
}

function setupApiConfig() {
  const root = els.apiConfig;
  if (!root) return;
  root.querySelectorAll("[data-api-tab]").forEach((tab) => {
    tab.addEventListener("click", () => {
      const name = tab.dataset.apiTab;
      root.querySelectorAll("[data-api-tab]").forEach((other) => {
        const active = other === tab;
        other.classList.toggle("active", active);
        other.setAttribute("aria-selected", String(active));
      });
      root.querySelectorAll("[data-api-panel]").forEach((panel) => {
        panel.hidden = panel.dataset.apiPanel !== name;
      });
    });
  });
  els.apiConfigSaveBtn?.addEventListener("click", () => void saveApiConfig());
  els.workspaceSettingsMenu?.addEventListener("toggle", () => {
    if (els.workspaceSettingsMenu.open) void loadApiConfig();
  });
}

async function loadApiConfig() {
  const root = els.apiConfig;
  if (!root) return;
  try {
    const response = await fetch("/api/settings/env-status");
    if (!response.ok) throw new Error(String(response.status));
    const data = await response.json();
    Object.values(data.fields || {}).forEach((group) => {
      Object.entries(group).forEach(([key, info]) => {
        const input = root.querySelector(`[data-env-key="${key}"]`);
        if (!input) return;
        if (input.type === "checkbox") {
          input.checked = ["1", "true", "yes", "on"].includes(String(info.value || "").toLowerCase());
        } else if (input.hasAttribute("data-env-secret")) {
          input.value = "";
          input.placeholder = info.configured ? "已配置（留空表示不修改）" : "未配置";
        } else if (typeof info.value === "string") {
          input.value = info.value;
        }
      });
    });
    if (els.apiConfigStatus) els.apiConfigStatus.textContent = data.cloudSyncOn ? "云端同步：已开启" : "";
  } catch (error) {
    if (els.apiConfigStatus) els.apiConfigStatus.textContent = "无法读取当前配置";
  }
}

async function saveApiConfig() {
  const root = els.apiConfig;
  if (!root || !els.apiConfigSaveBtn) return;
  const values = {};
  root.querySelectorAll("[data-env-key]").forEach((input) => {
    const key = input.dataset.envKey;
    if (input.type === "checkbox") {
      values[key] = input.checked ? "1" : "0";
    } else {
      const value = input.value.trim();
      // Skip blanks so an empty secret field never wipes a stored value.
      if (value) values[key] = value;
    }
  });
  if (!Object.keys(values).length) {
    if (els.apiConfigStatus) els.apiConfigStatus.textContent = "没有要保存的内容";
    return;
  }
  els.apiConfigSaveBtn.disabled = true;
  if (els.apiConfigStatus) els.apiConfigStatus.textContent = "正在写入 .env…";
  try {
    const response = await fetch("/api/settings/env", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || String(response.status));
    if (els.apiConfigStatus) els.apiConfigStatus.textContent = "已保存到 .env，重启服务后生效";
    void loadApiConfig();
  } catch (error) {
    if (els.apiConfigStatus) els.apiConfigStatus.textContent = `保存失败：${error.message || error}`;
  } finally {
    els.apiConfigSaveBtn.disabled = false;
  }
}

function colorChannels(hex) {
  const normalized = normalizeHexColor(hex);
  return [1, 3, 5].map((start) => Number.parseInt(normalized.slice(start, start + 2), 16) / 255);
}

function relativeLuminance(hex) {
  const channels = colorChannels(hex).map((channel) =>
    channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4,
  );
  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
}

function colorContrast(first, second) {
  const firstLuminance = relativeLuminance(first);
  const secondLuminance = relativeLuminance(second);
  const lighter = Math.max(firstLuminance, secondLuminance);
  const darker = Math.min(firstLuminance, secondLuminance);
  return (lighter + 0.05) / (darker + 0.05);
}

function highestContrastColor(background, candidates) {
  return candidates.reduce(
    (best, color) => {
      const contrast = colorContrast(background, color);
      return contrast > best.contrast ? { color, contrast } : best;
    },
    { color: candidates[0], contrast: -1 },
  ).color;
}

function syncCardPaletteControls() {
  const current = {
    textColor: normalizeHexColor(els.textColor?.value, "#202938"),
    accentColor: normalizeHexColor(els.accentColor?.value, "#2563eb"),
    bgColor: normalizeHexColor(els.bgColor?.value, "#ffffff"),
  };
  els.cardPaletteButtons.forEach((button) => {
    const palette = CARD_PALETTES[button.dataset.cardPalette];
    const active = Boolean(
      palette
        && current.textColor === palette.textColor
        && current.accentColor === palette.accentColor
        && current.bgColor === palette.bgColor,
    );
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function syncCardThemeControls() {
  const currentTheme = normalizeCardTheme(state.cardTheme);
  document.querySelectorAll("[data-card-theme]").forEach((button) => {
    const active = button.dataset.cardTheme === currentTheme;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function flushAppearanceSaveIfHydrated() {
  if (state.localDatabaseHydrated) flushStateSave();
}

function applyCardThemeId(value) {
  const themeId = normalizeCardTheme(value);
  const theme = CARD_THEMES[themeId];
  if (!theme) return;
  state.cardTheme = themeId;
  const defaults = theme.defaults;
  els.textColor.value = defaults.textColor;
  els.accentColor.value = defaults.accentColor;
  els.bgColor.value = defaults.bgColor;
  els.fontSize.value = String(defaults.fontSize);
  els.lineHeight.value = String(defaults.lineHeight);
  els.zhFont.value = defaults.zhFont;
  els.enFont.value = defaults.enFont;
  els.imageHeight.value = String(defaults.imageHeight);
  state.headerMode = defaults.headerMode;
  syncCardThemeControls();
  syncCardPaletteControls();
  updateHeaderModeButton();
  requestRender();
  flushAppearanceSaveIfHydrated();
  els.status.textContent = `已应用「${theme.label}」模板；正文和图片顺序未改变，模板将随当前项目自动保存`;
}

function applyCardTheme(event) {
  applyCardThemeId(event.currentTarget.dataset.cardTheme);
}

function renderThemeLibrary(filter = themeLibraryFilter) {
  if (!els.themeLibraryGrid) return;
  themeLibraryFilter = ["all", "native", "editorial", "swiss"].includes(filter) ? filter : "all";
  const entries = Object.entries(CARD_THEMES).filter(([, theme]) =>
    themeLibraryFilter === "all" || theme.group === themeLibraryFilter,
  );
  const currentTheme = normalizeCardTheme(state.cardTheme);
  els.themeLibraryGrid.replaceChildren(
    ...entries.map(([themeId, theme]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "theme-library-item";
      button.dataset.cardTheme = themeId;
      const active = themeId === currentTheme;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));

      const preview = document.createElement("span");
      preview.className = `theme-library-preview theme-library-preview-${theme.family || "social"}`;
      preview.setAttribute("aria-hidden", "true");
      const colors = Array.isArray(theme.previewColors) ? theme.previewColors : [
        theme.defaults.bgColor,
        theme.defaults.textColor,
        theme.defaults.accentColor,
      ];
      preview.style.setProperty("--theme-paper", colors[0]);
      preview.style.setProperty("--theme-ink", colors[1]);
      preview.style.setProperty("--theme-accent", colors[2]);
      preview.append(document.createElement("i"), document.createElement("b"), document.createElement("em"));

      const copy = document.createElement("span");
      copy.className = "theme-library-copy";
      const heading = document.createElement("span");
      heading.className = "theme-library-item-heading";
      const name = document.createElement("strong");
      name.textContent = theme.label;
      const group = document.createElement("small");
      group.textContent = theme.group === "editorial" ? "纸墨" : theme.group === "swiss" ? "瑞士" : "原有";
      heading.append(name, group);
      const description = document.createElement("span");
      description.className = "theme-library-description";
      description.textContent = theme.description || "卡片视觉主题";
      const swatches = document.createElement("span");
      swatches.className = "theme-library-swatches";
      colors.forEach((color) => {
        const swatch = document.createElement("i");
        swatch.style.background = color;
        swatches.append(swatch);
      });
      copy.append(heading, description, swatches);
      button.append(preview, copy);
      return button;
    }),
  );
  els.themeLibraryFilters.forEach((button) => {
    const active = button.dataset.themeFilter === themeLibraryFilter;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function openThemeLibrary() {
  themeLibraryReturnFocus = document.activeElement;
  renderThemeLibrary("all");
  els.workspace?.setAttribute("inert", "");
  els.themeLibraryModal?.classList.remove("hidden");
  els.themeLibraryFilters[0]?.focus();
}

function closeThemeLibrary() {
  els.themeLibraryModal?.classList.add("hidden");
  els.workspace?.removeAttribute("inert");
  themeLibraryReturnFocus?.focus?.();
  themeLibraryReturnFocus = null;
}

function openHelp() {
  helpReturnFocus = document.activeElement;
  els.workspace?.setAttribute("inert", "");
  els.helpModal?.classList.remove("hidden");
  els.helpClose?.focus();
}

function closeHelp() {
  els.helpModal?.classList.add("hidden");
  els.workspace?.removeAttribute("inert");
  helpReturnFocus?.focus?.();
  helpReturnFocus = null;
}

function trapHelpFocus(event) {
  if (event.key !== "Tab" || els.helpModal?.classList.contains("hidden")) return;
  trapModalFocus(event, els.helpModal);
}

async function copyAgentPrompt(button) {
  const prompt = button?.dataset?.copyPrompt || "";
  if (!prompt) return;
  try {
    await navigator.clipboard.writeText(prompt);
    els.status.textContent = "已复制这句 Agent 指令，可直接发给 Codex";
    button.classList.add("copied");
    window.setTimeout(() => button.classList.remove("copied"), 1200);
  } catch {
    els.status.textContent = "浏览器未允许复制，请直接选中帮助里的示例文字";
  }
}

function handleThemeLibrarySelection(event) {
  const button = event.target.closest("[data-card-theme]");
  if (!button || !els.themeLibraryGrid?.contains(button)) return;
  applyCardThemeId(button.dataset.cardTheme);
  closeThemeLibrary();
}

function trapThemeLibraryFocus(event) {
  if (event.key !== "Tab" || els.themeLibraryModal?.classList.contains("hidden")) return;
  trapModalFocus(event, els.themeLibraryModal);
}

function applyCardPalette(event) {
  const palette = CARD_PALETTES[event.currentTarget.dataset.cardPalette];
  if (!palette) return;
  els.textColor.value = palette.textColor;
  els.accentColor.value = palette.accentColor;
  els.bgColor.value = palette.bgColor;
  syncCardPaletteControls();
  requestRender();
  flushAppearanceSaveIfHydrated();
  els.status.textContent = `页面配色已切换为「${palette.label}」，将随当前项目自动保存`;
}

function ensureCardColorContrast(source = "background") {
  const background = normalizeHexColor(els.bgColor.value, "#ffffff");
  els.bgColor.value = background;
  const adjusted = [];
  if (colorContrast(background, els.textColor.value) < 4.5) {
    els.textColor.value = highestContrastColor(background, ["#000000", "#ffffff"]);
    adjusted.push("文字色");
  }
  if (colorContrast(background, els.accentColor.value) < 3) {
    els.accentColor.value = highestContrastColor(background, ["#1d4ed8", "#312e81", "#fde68a", "#ffffff", "#000000"]);
    adjusted.push("强调色");
  }
  syncCardPaletteControls();
  requestRender();
  flushAppearanceSaveIfHydrated();
  if (adjusted.length) {
    els.status.textContent = `已自动修正${adjusted.join("和")}，避免页面配色影响阅读`;
  } else {
    els.status.textContent = source === "background"
      ? "已使用自定义页面背景，将随当前项目自动保存"
      : "页面文字配色已更新，将随当前项目自动保存";
  }
}

function closeProjectActionsMenu() {
  document.querySelector(".project-actions-menu")?.removeAttribute("open");
}

function toggleUiTheme() {
  const index = UI_THEMES.indexOf(state.uiTheme);
  const nextTheme = UI_THEMES[(index + 1) % UI_THEMES.length];
  setUiTheme(nextTheme, true, true);
  closeProjectActionsMenu();
}

function updateHeaderModeButton() {
  if (!els.headerModeToggle) return;
  const firstOnly = state.headerMode === "first";
  els.headerModeToggle.classList.toggle("active", firstOnly);
  els.headerModeToggle.innerHTML = `<i data-lucide="${firstOnly ? "user-round-check" : "user-round"}"></i>${firstOnly ? "仅首页作者" : "每页作者"}`;
  els.headerModeToggle.title = firstOnly ? "当前仅首页显示作者信息，点击改为每页显示" : "当前每页显示作者信息，点击改为仅首页显示";
  els.headerModeToggle.setAttribute("aria-label", els.headerModeToggle.title);
  if (window.lucide) window.lucide.createIcons();
}

async function toggleHeaderMode() {
  closeProjectActionsMenu();
  state.headerMode = state.headerMode === "first" ? "every" : "first";
  updateHeaderModeButton();
  await render();
  els.status.textContent = state.headerMode === "first" ? "仅首页显示作者信息" : "每张图片都显示作者信息";
}

function updateAppMode() {
  document.body.dataset.appMode = state.appMode;
  els.modeButtons.forEach((button) => {
    const active = button.dataset.appMode === state.appMode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  const articleMode = state.appMode === "article";
  state.mode = "auto";
  if (!articleMode) articleSettingsOpen = false;
  if (els.articleSettings) els.articleSettings.hidden = !articleMode || !articleSettingsOpen;
  if (els.articleSettingsToggle) {
    els.articleSettingsToggle.hidden = !articleMode;
    els.articleSettingsToggle.setAttribute("aria-expanded", String(articleMode && articleSettingsOpen));
    els.articleSettingsToggle.classList.toggle("active", articleMode && articleSettingsOpen);
  }
  if (els.downloadMenuLabel) els.downloadMenuLabel.textContent = articleMode ? "下载长图" : "批量下载";
  els.downloadZip.hidden = state.appMode === "article";
  els.downloadArticle.hidden = state.appMode !== "article";
  els.headerModeToggle.hidden = state.appMode === "article";
  if (els.previewViewSwitch) els.previewViewSwitch.hidden = articleMode;
  updatePreviewCardView();
}

async function setAppMode(mode) {
  const nextMode = mode === "article" ? "article" : "cards";
  if (state.appMode === nextMode) return;
  state.appMode = nextMode;
  articleSettingsOpen = false;
  state.scrollOffset = 0;
  updateAppMode();
  await render();
}

async function convertCurrentMode() {
  const nextMode = state.appMode === "article" ? "cards" : "article";
  await setAppMode(nextMode);
  els.status.textContent = nextMode === "article" ? "已转为长文" : "已转为图文卡片，并自动分页排版";
}

function toggleArticleSettings() {
  if (state.appMode !== "article") return;
  articleSettingsOpen = !articleSettingsOpen;
  updateAppMode();
  if (articleSettingsOpen) els.articleSettings?.querySelector("button")?.focus();
}

function updateArticleControls() {
  els.articleThemeButtons.forEach((button) => button.classList.toggle("active", button.dataset.articleTheme === state.articleTheme));
  els.articleFontButtons.forEach((button) => button.classList.toggle("active", button.dataset.articleFont === state.articleFont));
  els.articleSizeButtons.forEach((button) => button.classList.toggle("active", button.dataset.articleSize === state.articleSize));
  els.articleColorButtons.forEach((button) => button.classList.toggle("active", button.dataset.articleColor?.toLowerCase() === state.articleColor.toLowerCase()));
}

async function setArticleOption(type, value) {
  if (type === "theme") state.articleTheme = normalizeArticleTheme(value);
  if (type === "font") state.articleFont = normalizeArticleFont(value);
  if (type === "size") state.articleSize = normalizeArticleSize(value);
  if (type === "color") state.articleColor = normalizeArticleColor(value);
  updateArticleControls();
  await render();
}

function normalizeHandle(value) {
  const trimmed = (value || "").trim();
  if (!trimmed) return "@profile";
  return trimmed.startsWith("@") ? trimmed : `@${trimmed}`;
}

function normalizeExportScale(value) {
  const scale = Number(value);
  return [1, 2, 3].includes(scale) ? scale : 2;
}

function loadExportScale() {
  try {
    return normalizeExportScale(localStorage.getItem(EXPORT_SCALE_STORAGE_KEY));
  } catch {
    return 2;
  }
}

function setExportScale(value, announce = true) {
  state.exportScale = normalizeExportScale(value);
  if (els.exportScale) els.exportScale.value = String(state.exportScale);
  try {
    localStorage.setItem(EXPORT_SCALE_STORAGE_KEY, String(state.exportScale));
  } catch {
    // 清晰度选项写入失败不影响当前导出。
  }
  if (announce) {
    els.status.textContent = `导出清晰度：${state.exportScale}×（${CANVAS_WIDTH * state.exportScale}x${CANVAS_HEIGHT * state.exportScale}）`;
  }
}

function normalizeArticleTheme(value) {
  return ["classic", "elegant", "clean", "wechat", "colorful"].includes(value) ? value : "wechat";
}

function normalizeArticleFont(value) {
  return ["sans", "serif", "mono"].includes(value) ? value : "sans";
}

function normalizeArticleSize(value) {
  return ["small", "normal", "large"].includes(value) ? value : "normal";
}

function normalizeArticleColor(value) {
  return /^#[0-9a-fA-F]{6}$/.test(String(value || "")) ? value : "#0f766e";
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function loadPanelLayout() {
  try {
    const stored = JSON.parse(localStorage.getItem(PANEL_LAYOUT_STORAGE_KEY) || "{}");
    state.panelLayout.history = clamp(Number(stored.history) || PANEL_LIMITS.history.fallback, PANEL_LIMITS.history.min, PANEL_LIMITS.history.max);
    state.panelLayout.editor = clamp(Number(stored.editor) || PANEL_LIMITS.editor.fallback, PANEL_LIMITS.editor.min, PANEL_LIMITS.editor.max);
    state.panelLayout.editorCollapsed = stored.editorCollapsed === true;
  } catch {
    state.panelLayout.history = PANEL_LIMITS.history.fallback;
    state.panelLayout.editor = PANEL_LIMITS.editor.fallback;
    state.panelLayout.editorCollapsed = false;
  }
}

function savePanelLayout() {
  localStorage.setItem(PANEL_LAYOUT_STORAGE_KEY, JSON.stringify(state.panelLayout));
}

function applyPanelLayout() {
  const editorCollapsed = state.panelLayout.editorCollapsed === true;
  els.workspace?.style.setProperty("--history-width", `${Math.round(state.panelLayout.history)}px`);
  els.workspace?.style.setProperty("--editor-width", `${Math.round(state.panelLayout.editor)}px`);
  els.workspace?.classList.toggle("editor-collapsed", editorCollapsed);
  if (els.editorPanel) els.editorPanel.hidden = editorCollapsed;
  els.panelResizers.forEach((resizer) => {
    const target = resizer.dataset.panelResize;
    const limits = PANEL_LIMITS[target];
    if (!limits) return;
    if (target === "editor") resizer.hidden = editorCollapsed;
    resizer.setAttribute("role", "separator");
    resizer.setAttribute("aria-orientation", "vertical");
    resizer.setAttribute("aria-valuemin", String(limits.min));
    resizer.setAttribute("aria-valuemax", String(limits.max));
    resizer.setAttribute("aria-valuenow", String(Math.round(state.panelLayout[target])));
  });
  if (els.editorPanelToggle) {
    const action = editorCollapsed ? "显示" : "隐藏";
    els.editorPanelToggle.setAttribute("aria-expanded", String(!editorCollapsed));
    els.editorPanelToggle.setAttribute("aria-label", `${action}源码编辑区`);
    els.editorPanelToggle.title = `${action}源码编辑区`;
    els.editorPanelToggle.innerHTML = `<i data-lucide="${editorCollapsed ? "panel-left-open" : "panel-left-close"}"></i>`;
  }
  if (window.lucide) window.lucide.createIcons();
}

function toggleEditorPanel() {
  state.panelLayout.editorCollapsed = !state.panelLayout.editorCollapsed;
  applyPanelLayout();
  savePanelLayout();
  els.status.textContent = state.panelLayout.editorCollapsed ? "已收起源码编辑区" : "已展开源码编辑区，可拖动中线调整宽度";
}

function resizePanelWithKeyboard(event) {
  const target = event.currentTarget.dataset.panelResize;
  const limits = PANEL_LIMITS[target];
  if (!limits || window.matchMedia("(max-width: 700px)").matches) return;
  const keys = ["ArrowLeft", "ArrowRight", "Home", "End"];
  if (!keys.includes(event.key)) return;
  event.preventDefault();
  if (target === "history" && !els.historySidebar?.classList.contains("open")) setHistoryOpen(true);
  if (event.key === "Home") state.panelLayout[target] = limits.min;
  if (event.key === "End") state.panelLayout[target] = limits.max;
  if (event.key === "ArrowLeft") state.panelLayout[target] = clamp(state.panelLayout[target] - 16, limits.min, limits.max);
  if (event.key === "ArrowRight") state.panelLayout[target] = clamp(state.panelLayout[target] + 16, limits.min, limits.max);
  applyPanelLayout();
  savePanelLayout();
  els.status.textContent = `${target === "history" ? "历史栏" : "编辑区"}宽度 ${Math.round(state.panelLayout[target])} 像素`;
}

function startPanelResize(event) {
  const target = event.currentTarget.dataset.panelResize;
  if (!["history", "editor"].includes(target)) return;
  if (window.matchMedia("(max-width: 700px)").matches) return;

  event.preventDefault();
  if (target === "history" && !els.historySidebar?.classList.contains("open")) {
    setHistoryOpen(true);
  }

  const startX = event.clientX;
  const startEditor = state.panelLayout.editor;
  const workspaceRect = els.workspace.getBoundingClientRect();
  const resizeHandle = event.currentTarget;
  resizeHandle.classList.add("active");
  document.body.classList.add("resizing-panels");
  resizeHandle.setPointerCapture?.(event.pointerId);

  const move = (moveEvent) => {
    if (target === "history") {
      const nextHistory = moveEvent.clientX - workspaceRect.left;
      state.panelLayout.history = clamp(nextHistory, PANEL_LIMITS.history.min, PANEL_LIMITS.history.max);
    } else {
      const nextEditor = startEditor + moveEvent.clientX - startX;
      state.panelLayout.editor = clamp(nextEditor, PANEL_LIMITS.editor.min, PANEL_LIMITS.editor.max);
    }
    applyPanelLayout();
  };

  const stop = (upEvent) => {
    resizeHandle.classList.remove("active");
    document.body.classList.remove("resizing-panels");
    resizeHandle.releasePointerCapture?.(upEvent.pointerId);
    savePanelLayout();
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", stop);
    window.removeEventListener("pointercancel", stop);
  };

  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", stop);
  window.addEventListener("pointercancel", stop);
}

function debounce(fn, wait = 140) {
  let id = 0;
  const debounced = (...args) => {
    window.clearTimeout(id);
    id = window.setTimeout(() => {
      id = 0;
      fn(...args);
    }, wait);
  };
  debounced.cancel = () => {
    window.clearTimeout(id);
    id = 0;
  };
  return debounced;
}

function nextProjectTimestamp(project) {
  return Math.max(Date.now(), Number(project?.updatedAt || 0) + 1);
}

function formatCheckpointVersion(value) {
  const date = value ? new Date(Number(value)) : null;
  if (!date || Number.isNaN(date.getTime())) return "当前版本";
  const pad = (part) => String(part).padStart(2, "0");
  return `当前版本 ${pad(date.getMonth() + 1)}/${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function lastConfirmedCheckpointText() {
  const confirmedAt = saveCheckpoint.cloudSavedAt || saveCheckpoint.serverSavedAt || saveCheckpoint.localSavedAt;
  return confirmedAt ? `上次确认 ${formatSavedTime(confirmedAt)}` : "尚无已确认保存";
}

function renderSaveCheckpoint() {
  if (!els.saveCheckpoint || !els.saveCheckpointLabel || !els.saveCheckpointMeta) return;
  const phase = saveCheckpoint.phase || "loading";
  const version = formatCheckpointVersion(saveCheckpoint.targetUpdatedAt);
  let label = "正在确认保存位置";
  let meta = "请稍候，正文不会因为状态检测而停止本地保存";

  if (isBuiltInProjectId(state.currentProjectId)) {
    label = "内置说明书 · 只读";
    meta = "这里不会覆盖你的草稿；新建项目后会自动保存";
  } else if (phase === "dirty") {
    label = "有未保存修改";
    meta = `${AUTO_SAVE_EXPLANATION} · ${lastConfirmedCheckpointText()}`;
  } else if (phase === "saving-local") {
    label = "正在保存当前版本…";
    meta = `${version} · 正在写入浏览器副本与共享库`;
  } else if (phase === "saved-local") {
    label = "当前版本已保存到本机";
    meta = `${version} · ${formatSavedTime(saveCheckpoint.serverSavedAt || saveCheckpoint.localSavedAt)} · ${saveCheckpoint.destination}`;
  } else if (phase === "syncing-cloud") {
    label = "本机已保存，正在同步云端…";
    meta = `${version} · ${saveCheckpoint.destination}`;
  } else if (phase === "saved-cloud") {
    label = saveCheckpoint.confirmation === "manual" ? "已手动确认云端最新版" : "当前版本已保存到云端";
    meta = `${version} · 确认于 ${formatSavedTime(saveCheckpoint.cloudSavedAt)} · ${AUTO_SAVE_EXPLANATION}`;
  } else if (phase === "degraded") {
    label = "当前版本已保存到本机";
    meta = `${version} · 云端不可用 · ${saveCheckpoint.destination}${saveCheckpoint.error ? ` · ${saveCheckpoint.error}` : ""}`;
  } else if (phase === "error") {
    label = "本次保存尚未确认";
    meta = `${lastConfirmedCheckpointText()}${saveCheckpoint.error ? ` · ${saveCheckpoint.error}` : ""}`;
  } else if (phase === "conflict") {
    label = "已保留两个版本";
    meta = saveCheckpoint.error || "另一端也修改了同一基础版本；两边都未被覆盖，可在历史记录中比较";
  }

  els.saveCheckpoint.dataset.phase = isBuiltInProjectId(state.currentProjectId) ? "readonly" : phase;
  const visualState = isBuiltInProjectId(state.currentProjectId)
    ? "local"
    : phase === "saved-cloud"
      ? "synced"
      : phase === "saved-local"
        ? "saved"
        : phase === "saving-local" || phase === "syncing-cloud"
          ? "saving"
          : phase === "degraded"
            ? "warning"
            : phase === "conflict"
              ? "warning"
              : phase === "loading"
                ? "checking"
                : phase;
  els.saveCheckpoint.dataset.state = visualState;
  els.saveCheckpointLabel.textContent = label;
  els.saveCheckpointMeta.textContent = meta;
  els.saveCheckpoint.setAttribute("aria-label", `${label}。${meta}`);
  const icon = els.saveCheckpoint.querySelector("[data-lucide]");
  if (icon) {
    const iconName = visualState === "synced" ? "cloud-check" : visualState === "saving" ? "loader-circle" : visualState === "dirty" ? "circle-dot-dashed" : visualState === "error" ? "triangle-alert" : visualState === "warning" ? "hard-drive-download" : "save";
    if (icon.getAttribute("data-lucide") !== iconName) {
      icon.setAttribute("data-lucide", iconName);
      if (window.lucide) window.lucide.createIcons();
    }
  }
  if (els.saveNow) {
    const busy = phase === "saving-local" || phase === "syncing-cloud";
    els.saveNow.disabled = busy || isBuiltInProjectId(state.currentProjectId);
    els.saveNow.setAttribute("aria-busy", String(busy));
  }
}

function setSaveCheckpoint(patch = {}) {
  Object.assign(saveCheckpoint, patch);
  renderSaveCheckpoint();
}

function markSaveDirty() {
  manualSaveGeneration += 1;
  if (persistenceMode === "cloud") setPrimarySaveButtonFeedback("保存", "save");
  if (!state.localDatabaseHydrated || isBuiltInProjectId(state.currentProjectId)) return;
  saveCheckpointPollGeneration += 1;
  const current = state.projects.find((project) => project.id === state.currentProjectId);
  setSaveCheckpoint({
    phase: "dirty",
    projectId: state.currentProjectId,
    targetUpdatedAt: Number(current?.updatedAt || saveCheckpoint.targetUpdatedAt || Date.now()),
    confirmation: "auto",
    error: "",
  });
}

function flushStateSave() {
  window.clearTimeout(localStateSaveTimer);
  window.clearTimeout(localStateSaveMaxTimer);
  localStateSaveTimer = 0;
  localStateSaveMaxTimer = 0;
  saveState();
}

function scheduleStateSave(delay = LOCAL_STATE_SAVE_DELAY) {
  // 首屏必须先让 IndexedDB 与 LocalStorage 完成合并。否则旧的 LocalStorage
  // 草稿会被首屏渲染误标成“刚刚更新”，反过来覆盖数据库里的新图片。
  if (!state.localDatabaseHydrated) return;
  markSaveDirty();
  window.clearTimeout(localStateSaveTimer);
  localStateSaveTimer = window.setTimeout(flushStateSave, delay);
  if (!localStateSaveMaxTimer) {
    localStateSaveMaxTimer = window.setTimeout(flushStateSave, LOCAL_STATE_SAVE_MAX_WAIT);
  }
}

function saveState() {
  window.clearTimeout(localStateSaveTimer);
  window.clearTimeout(localStateSaveMaxTimer);
  localStateSaveTimer = 0;
  localStateSaveMaxTimer = 0;
  try {
    const data = readForm();
    if (isBuiltInProjectId(state.currentProjectId)) {
      updateProjectHistory();
      renderSaveCheckpoint();
      return;
    }

    let current = state.projects.find((project) => project.id === state.currentProjectId);
    const created = !current;
    if (typeof current?.data?.__localConflictOf === "string") {
      data.__localConflictOf = current.data.__localConflictOf;
    }
    if (!current) {
      current = createProject(data);
      state.currentProjectId = current.id;
      state.projects.unshift(current);
    }
    const title = normalizeProjectTitle(els.projectTitle?.value) || current.title || projectTitleFromData(data);
    let unchanged = !created && current.title === title;
    if (unchanged) {
      try {
        unchanged = stableJsonStringify(current.data) === stableJsonStringify(data);
      } catch {
        unchanged = false;
      }
    }
    if (unchanged) {
      updateProjectHistory();
      return { changed: false, project: current };
    }
    const now = nextProjectTimestamp(current);
    current.data = data;
    current.title = title;
    current.updatedAt = now;
    setSaveCheckpoint({
      phase: "saving-local",
      projectId: current.id,
      targetUpdatedAt: now,
      error: "",
    });
    state.projects = [
      current,
      ...state.projects.filter((project) => project.id !== current.id),
    ].slice(0, MAX_PROJECTS);
    let legacyStateSaved = !legacyStateLocalStorageUnavailable;
    if (!legacyStateLocalStorageUnavailable) {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
      } catch (error) {
        legacyStateSaved = false;
        legacyStateLocalStorageUnavailable = true;
        console.warn("LocalStorage 当前草稿写入失败，后续改用 IndexedDB", error);
      }
    }
    const projectStoreSaved = saveProjectStore();
    updateProjectHistory();
    if (!legacyStateSaved || !projectStoreSaved) {
      els.status.textContent = "内容较大，已改用本地数据库保存；建议再导出一份备份";
    }
    return { changed: true, project: current };
  } catch (error) {
    console.error(error);
    setSaveCheckpoint({ phase: "error", error: "请点击“立即保存”重试" });
    els.status.textContent = "本次内容未能自动保存，请立即导出草稿备份";
    return { changed: false, project: null, error };
  }
}

function loadState() {
  const store = loadProjectStore();
  state.projects = store.projects;
  state.deletedProjects = store.deletedProjects || [];
  state.currentProjectId = store.activeId || store.projects[0]?.id || null;
  return findHistoryProject(state.currentProjectId)?.data || blankFormState();
}

function migrateStoredState(data) {
  const oldBoldQuote =
    "**“请你从某个领域里，选择一个研究生水平的概念。然后写一个寓言故事，用间接的方式把这个概念讲清楚。不要一开始就说答案，尽量到故事快结束的时候，才让人意识到原来讲的是这个概念。故事结束后，再解释这个概念，以及故事里的隐喻分别对应什么。”**";
  if (typeof data.content !== "string") data.content = defaultText;
  data.published = data.published === true;
  data.content = data.content.replace(
    oldBoldQuote,
    "“请你从某个领域里，选择一个研究生水平的概念。然后写一个寓言故事，用间接的方式把这个概念讲清楚。不要一开始就说答案，尽量到故事快结束的时候，才让人意识到原来讲的是这个概念。故事结束后，再解释这个概念，以及故事里的隐喻分别对应什么。”",
  );
  if (!Number.isFinite(Number(data.lineHeight))) data.lineHeight = "1.65";
  if (Math.abs(Number(data.lineHeight) - 1.85) < 0.001) data.lineHeight = "1.65";
  data.cardTheme = normalizeCardTheme(data.cardTheme);
  data.headerMode = data.headerMode === "first" ? "first" : "every";
  data.appMode = data.appMode === "article" ? "article" : "cards";
  data.articleTheme = normalizeArticleTheme(data.articleTheme);
  data.articleFont = normalizeArticleFont(data.articleFont);
  data.articleSize = normalizeArticleSize(data.articleSize);
  data.articleColor = normalizeArticleColor(data.articleColor);
  // UI appearance is a browser preference, not part of a publishable project.
  delete data.uiTheme;
  data.images = normalizeImagesForContent(data.content, data.images);
  return data;
}

function defaultImages() {
  return {
    sample: {
      src: sampleImage,
      name: "sample",
    },
  };
}

function normalizeImagesForContent(content, images) {
  const nextImages = images && typeof images === "object" ? { ...images } : {};
  if (String(content || "").includes("[[image:sample]]") && !nextImages.sample) {
    nextImages.sample = defaultImages().sample;
  }
  return nextImages;
}

function createProject(data = defaultFormState()) {
  const normalized = migrateStoredState({ ...defaultFormState(), ...data });
  const now = Date.now();
  return {
    id: `project_${now.toString(36)}_${Math.random().toString(36).slice(2, 7)}`,
    title: String(normalized.content || "").trim() ? projectTitleFromData(normalized) : "未命名图文",
    updatedAt: now,
    cloudBaseUpdatedAt: 0,
    data: normalized,
  };
}

function projectStoreSnapshot() {
  return {
    activeId: state.currentProjectId,
    projects: state.projects.filter((project) => !isBuiltInProject(project)).slice(0, MAX_PROJECTS),
    deletedProjects: normalizeProjectDeletions(state.deletedProjects),
  };
}

function openLocalDatabase() {
  if (!window.indexedDB) return Promise.resolve(null);
  return new Promise((resolve, reject) => {
    const request = window.indexedDB.open(LOCAL_DATABASE_NAME, 1);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(LOCAL_DATABASE_STORE)) {
        database.createObjectStore(LOCAL_DATABASE_STORE);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error("无法打开本地草稿数据库"));
  });
}

async function saveLocalAssetDirectoryHandle(handle) {
  const database = await openLocalDatabase();
  if (!database) return false;
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(LOCAL_DATABASE_STORE, "readwrite");
    try {
      transaction.objectStore(LOCAL_DATABASE_STORE).put(handle, LOCAL_ASSET_DIRECTORY_KEY);
    } catch (error) {
      database.close();
      reject(error);
      return;
    }
    transaction.oncomplete = () => {
      database.close();
      resolve(true);
    };
    transaction.onerror = () => {
      const error = transaction.error || new Error("本地资源文件夹授权保存失败");
      database.close();
      reject(error);
    };
  });
}

async function readLocalAssetDirectoryHandle() {
  const database = await openLocalDatabase();
  if (!database) return null;
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(LOCAL_DATABASE_STORE, "readonly");
    const request = transaction.objectStore(LOCAL_DATABASE_STORE).get(LOCAL_ASSET_DIRECTORY_KEY);
    let handle = null;
    request.onsuccess = () => {
      handle = request.result || null;
    };
    request.onerror = () => reject(request.error || new Error("本地资源文件夹授权读取失败"));
    transaction.oncomplete = () => {
      database.close();
      resolve(handle);
    };
    transaction.onerror = () => {
      const error = transaction.error || new Error("本地资源文件夹授权读取失败");
      database.close();
      reject(error);
    };
  });
}

async function saveProjectStoreToIndexedDb(snapshot) {
  const database = await openLocalDatabase();
  if (!database) return false;
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(LOCAL_DATABASE_STORE, "readwrite");
    transaction.objectStore(LOCAL_DATABASE_STORE).put(snapshot, LOCAL_DATABASE_PROJECTS_KEY);
    transaction.oncomplete = () => {
      database.close();
      resolve(true);
    };
    transaction.onerror = () => {
      const error = transaction.error || new Error("本地草稿数据库写入失败");
      database.close();
      reject(error);
    };
  });
}

function markProjectCloudBase(projectId, updatedAt) {
  const revision = Number(updatedAt || 0);
  const project = state.projects.find((item) => item.id === projectId);
  if (!project || !Number.isSafeInteger(revision) || revision <= 0) return;
  if (Number(project.cloudBaseUpdatedAt || 0) === revision) return;
  project.cloudBaseUpdatedAt = revision;
  const snapshot = projectStoreSnapshot();
  if (!projectStoreLocalStorageUnavailable) {
    try {
      localStorage.setItem(PROJECTS_STORAGE_KEY, JSON.stringify(snapshot));
    } catch (error) {
      projectStoreLocalStorageUnavailable = true;
      console.warn("云端基线写入 LocalStorage 失败", error);
    }
  }
  if (state.localDatabaseHydrated) {
    void saveProjectStoreToIndexedDb(snapshot).catch((error) => {
      console.warn("云端基线写入 IndexedDB 失败", error);
    });
  }
}

async function savePendingProjectDeletionsToIndexedDb(deletions) {
  const database = await openLocalDatabase();
  if (!database) return false;
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(LOCAL_DATABASE_STORE, "readwrite");
    transaction.objectStore(LOCAL_DATABASE_STORE).put(
      normalizeProjectDeletions(deletions),
      LOCAL_DATABASE_PENDING_PROJECT_DELETIONS_KEY,
    );
    transaction.oncomplete = () => {
      database.close();
      resolve(true);
    };
    transaction.onerror = () => {
      const error = transaction.error || new Error("待重试删除记录写入失败");
      database.close();
      reject(error);
    };
  });
}

async function loadPendingProjectDeletionsFromIndexedDb() {
  const database = await openLocalDatabase();
  if (!database) return [];
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(LOCAL_DATABASE_STORE, "readonly");
    const request = transaction.objectStore(LOCAL_DATABASE_STORE).get(
      LOCAL_DATABASE_PENDING_PROJECT_DELETIONS_KEY,
    );
    let deletions = [];
    request.onsuccess = () => {
      deletions = normalizeProjectDeletions(request.result);
    };
    request.onerror = () => reject(request.error || new Error("待重试删除记录读取失败"));
    transaction.oncomplete = () => {
      database.close();
      resolve(deletions);
    };
    transaction.onerror = () => {
      const error = transaction.error || new Error("待重试删除记录读取失败");
      database.close();
      reject(error);
    };
  });
}

async function loadProjectStoreFromSharedServer() {
  try {
    const response = await fetch(SHARED_PROJECT_STORE_URL, { cache: "no-store" });
    if (!response.ok) throw new Error(`共享草稿库读取失败（${response.status}）`);
    const payload = await response.json();
    if (!payload || !Array.isArray(payload.projects)) throw new Error("共享草稿库格式无效");
    rememberSharedProjectVersions(payload);
    sharedProjectStoreAvailable = true;
    return payload;
  } catch (error) {
    sharedProjectStoreAvailable = false;
    console.info("共享草稿库暂不可用，继续使用浏览器本地数据库", error);
    return null;
  }
}

async function saveProjectStoreToSharedServer(
  snapshot,
  { expectedProjectId = "", expectedUpdatedAt = 0 } = {},
) {
  try {
    const headers = {
      "Content-Type": "application/json",
      [SHARED_SAVE_PROTOCOL_HEADER]: SHARED_SAVE_PROTOCOL_VERSION,
    };
    const targetProject = snapshot.projects.find((project) => project.id === snapshot.activeId);
    const outboundSnapshot = {
      ...snapshot,
      // A browser only owns the draft it is actively editing. Sending cached
      // background projects would let an unrelated stale cache hitchhike on a
      // valid active-project save and overwrite a teammate's newer draft.
      projects: targetProject ? [targetProject] : [],
    };
    if (expectedProjectId && Number(expectedUpdatedAt) > 0) {
      headers["X-WTP-Expected-Project-Id"] = expectedProjectId;
      headers["X-WTP-Expected-Project-Updated-At"] = String(Number(expectedUpdatedAt));
    } else if (targetProject && sharedProjectIds.has(targetProject.id)) {
      const sharedUpdatedAt = Number(sharedProjectVersions.get(targetProject.id) || 0);
      if (!sharedUpdatedAt) throw new Error("尚未取得服务器基础版本，已停止覆盖保存");
      headers["X-WTP-Expected-Project-Id"] = targetProject.id;
      headers["X-WTP-Expected-Project-Updated-At"] = String(sharedUpdatedAt);
    }
    const response = await fetch(SHARED_PROJECT_STORE_URL, {
      method: "PUT",
      headers,
      body: JSON.stringify(outboundSnapshot),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 409 && payload?.code === "DRAFT_VERSION_CONFLICT") {
        sharedProjectStoreAvailable = true;
        return {
          saved: false,
          conflict: true,
          code: payload.code,
          current: payload.current || null,
          confirmedUpdatedAt: 0,
          error: new Error(payload.error || "检测到团队成员保存的新版本"),
        };
      }
      throw new Error(payload?.error || `共享草稿库写入失败（${response.status}）`);
    }
    const responseStore = payload?.store && Array.isArray(payload.store.projects) ? payload.store : payload;
    const confirmedProject = responseStore?.projects?.find((project) => project.id === snapshot.activeId);
    const targetUpdatedAt = Number(targetProject?.updatedAt || 0);
    const confirmedUpdatedAt = Number(payload?.saveMeta?.savedUpdatedAt || payload?.save?.updatedAt || confirmedProject?.updatedAt || 0);
    const activeRevisionConfirmed = Boolean(
      targetProject
      && payload?.saveMeta?.projectId === snapshot.activeId
      && targetUpdatedAt
      && confirmedUpdatedAt === targetUpdatedAt,
    );
    if (payload?.saveMeta?.saved !== true || payload?.saveMeta?.snapshotSaved !== true || (targetProject && !activeRevisionConfirmed)) {
      throw new Error("本机服务没有精确确认当前草稿版本");
    }
    rememberSharedProjectVersions(responseStore);
    sharedProjectStoreAvailable = true;
    return {
      saved: true,
      conflict: false,
      confirmedUpdatedAt,
      responseStore,
      deletedProjects: payload.saveMeta.deletedProjects || [],
    };
  } catch (error) {
    sharedProjectStoreAvailable = false;
    console.warn("共享草稿库写入失败，已保留浏览器本地副本", error);
    return { saved: false, conflict: false, confirmedUpdatedAt: 0, error };
  }
}

function imageReferenceSignature(content) {
  return (String(content || "").match(/\[\[image:[^\]]+\]\]/g) || []).join("\n");
}

async function saveCurrentProjectTextToSharedServer({ keepalive = false } = {}) {
  window.clearTimeout(sharedTextSaveTimer);
  sharedTextSaveTimer = 0;
  if (isBuiltInProjectId(state.currentProjectId)) return false;
  const current = state.projects.find((project) => project.id === state.currentProjectId);
  if (!current) return false;

  const updatedAt = nextProjectTimestamp(current);
  const title = normalizeProjectTitle(els.projectTitle?.value) || current.title || projectTitleFromData(current.data);
  const content = els.content.value;
  current.title = title;
  current.updatedAt = updatedAt;
  current.data = { ...current.data, content };
  setSaveCheckpoint({
    phase: "saving-local",
    projectId: current.id,
    targetUpdatedAt: updatedAt,
    error: "",
  });

  try {
    const sharedUpdatedAt = Number(sharedProjectVersions.get(current.id) || 0);
    if (sharedProjectIds.has(current.id) && !sharedUpdatedAt) {
      throw new Error("尚未取得服务器基础版本，已停止覆盖保存");
    }
    const headers = {
      "Content-Type": "application/json",
      [SHARED_SAVE_PROTOCOL_HEADER]: SHARED_SAVE_PROTOCOL_VERSION,
    };
    if (sharedUpdatedAt) {
      headers["X-WTP-Expected-Project-Id"] = current.id;
      headers["X-WTP-Expected-Project-Updated-At"] = String(sharedUpdatedAt);
    }
    const response = await fetch(SHARED_PROJECT_TEXT_URL, {
      method: "PATCH",
      headers,
      body: JSON.stringify({ id: current.id, title, content, updatedAt }),
      keepalive,
    });
    if (!response.ok) throw new Error(`正文快速保存失败（${response.status}）`);
    const payload = await response.json();
    if (
      payload?.saveMeta?.saved !== true
      || payload.saveMeta.projectId !== current.id
      || Number(payload.saveMeta.savedUpdatedAt || 0) !== updatedAt
    ) {
      throw new Error("本机服务没有精确确认当前正文版本");
    }
    sharedProjectStoreAvailable = true;
    sharedProjectIds.add(current.id);
    sharedProjectVersions.set(current.id, updatedAt);
    updateProjectHistory();
    const stillCurrent = state.currentProjectId === current.id
      && Number(current.updatedAt) === updatedAt
      && els.content.value === content
      && saveCheckpoint.phase !== "dirty";
    if (stillCurrent) {
      const savedAt = new Date().toISOString();
      setSaveCheckpoint({
        phase: persistenceMode === "cloud" ? "syncing-cloud" : "degraded",
        projectId: current.id,
        targetUpdatedAt: updatedAt,
        serverSavedAt: savedAt,
        destination: persistenceMode === "cloud" ? "Supabase + 私有 TOS" : "本机项目文件",
      });
      if (persistenceMode === "cloud") void confirmCloudCheckpoint(current.id, updatedAt);
    }
    return true;
  } catch (error) {
    console.warn("正文快速保存失败，继续使用完整草稿保存", error);
    return false;
  }
}

function scheduleCurrentProjectTextSave() {
  // Full project snapshots are the only publishable revisions. A text-only
  // revision can otherwise outrank the matching images/layout after refresh.
  window.clearTimeout(sharedTextSaveTimer);
  sharedTextSaveTimer = 0;
}

async function recoverSharedProjectConflict(snapshot) {
  const localActive = snapshot?.projects?.find((project) => project.id === snapshot.activeId);
  if (!localActive) return null;
  const base = sharedProjectBases.get(localActive.id) || null;
  const shared = await loadProjectStoreFromSharedServer();
  if (!shared?.projects) return null;
  const liveProject = state.projects.find((project) => project.id === localActive.id);
  if (
    state.currentProjectId !== localActive.id
    || Number(liveProject?.updatedAt || 0) !== Number(localActive.updatedAt || 0)
    || els.content.value !== localActive.data?.content
  ) {
    return null;
  }

  const sharedActive = shared.projects.find((project) => project.id === localActive.id);
  const rebasedProject = mergeProjectWithSharedBase(base, localActive, sharedActive);
  if (rebasedProject) {
    const reconciledOthers = reconcileLocalProjectsWithShared(
      snapshot.projects.filter((project) => project.id !== localActive.id),
      shared.projects.filter((project) => project.id !== localActive.id),
    );
    const resolved = resolveProjectDeletionWinners(
      [rebasedProject, ...reconciledOthers],
      mergeProjectDeletions(snapshot.deletedProjects, shared.deletedProjects),
    );
    state.projects = resolved.projects;
    state.deletedProjects = resolved.deletedProjects;
    state.currentProjectId = rebasedProject.id;
    rememberActiveProject(rebasedProject.id);
    if (!draftValuesMatch(localActive.data, rebasedProject.data)) {
      const generation = manualSaveGeneration;
      applyForm(rebasedProject.data);
      manualSaveGeneration = generation;
    }
    if (els.projectTitle) els.projectTitle.value = rebasedProject.title;
    updateProjectHistory();
    saveProjectStore({ scheduleDatabase: false });
    const recoveredSnapshot = projectStoreSnapshot();
    let localSaved = false;
    try {
      localSaved = await saveProjectStoreToIndexedDb(recoveredSnapshot);
    } catch (error) {
      console.warn("合并后的草稿写入 IndexedDB 失败", error);
    }
    const sharedResult = await saveProjectStoreToSharedServer(recoveredSnapshot);
    if (!sharedResult.saved) return null;
    return {
      snapshot: recoveredSnapshot,
      localSaved,
      sharedResult,
      rebasedProject,
      notice: "已合并团队最新状态并保存，没有创建重复副本",
    };
  }

  const reconciledProjects = reconcileLocalProjectsWithShared(snapshot.projects, shared.projects);
  const resolved = resolveProjectDeletionWinners(
    reconciledProjects,
    mergeProjectDeletions(snapshot.deletedProjects, shared.deletedProjects),
  );
  const conflictRoot = typeof localActive.data?.__localConflictOf === "string"
    ? localActive.data.__localConflictOf
    : localActive.id;
  const existingIds = new Set(snapshot.projects.map((project) => project.id));
  const conflictCopy = resolved.projects
    .filter((project) => project?.data?.__localConflictOf === conflictRoot && !existingIds.has(project.id))
    .sort((first, second) => Number(second.updatedAt || 0) - Number(first.updatedAt || 0))[0];
  if (!conflictCopy) return null;

  state.projects = resolved.projects;
  state.deletedProjects = resolved.deletedProjects;
  state.currentProjectId = conflictCopy.id;
  rememberActiveProject(conflictCopy.id);
  if (els.projectTitle) els.projectTitle.value = conflictCopy.title;
  projectPreviewCache.delete(localActive.id);
  updateProjectHistory();
  saveProjectStore({ scheduleDatabase: false });

  const recoveredSnapshot = projectStoreSnapshot();
  let localSaved = false;
  try {
    localSaved = await saveProjectStoreToIndexedDb(recoveredSnapshot);
  } catch (error) {
    console.warn("冲突副本写入 IndexedDB 失败", error);
  }
  const sharedResult = await saveProjectStoreToSharedServer(recoveredSnapshot);
  if (!sharedResult.saved) return null;
  return {
    snapshot: recoveredSnapshot,
    localSaved,
    sharedResult,
    conflictCopy,
    notice: `检测到同一字段存在并发修改；你的内容已安全另存为「${conflictCopy.title}」`,
  };
}

async function flushProjectStoreToIndexedDb() {
  if (!state.localDatabaseHydrated) return { localSaved: false, sharedSaved: false, projectUpdatedAt: 0 };
  window.clearTimeout(localDatabaseSaveTimer);
  localDatabaseSaveTimer = 0;
  const queuedSave = localDatabaseSaveChain
    .catch(() => false)
    .then(async () => {
      let snapshot = projectStoreSnapshot();
      let targetProject = snapshot.projects.find((project) => project.id === snapshot.activeId);
      let projectId = targetProject?.id || snapshot.activeId;
      let projectUpdatedAt = Number(targetProject?.updatedAt || 0);
      let localSaved = false;
      let sharedResult = { saved: false, confirmedUpdatedAt: 0 };
      let conflictRecovered = false;
      let conflictNotice = "";
      try {
        // 在真正轮到本次事务时读取最新快照，避免旧的大图事务晚完成后覆盖新图。
        localSaved = await saveProjectStoreToIndexedDb(snapshot);
      } catch (error) {
        console.warn("IndexedDB 草稿写入失败", error);
      }
      sharedResult = await saveProjectStoreToSharedServer(snapshot);
      if (sharedResult.conflict) {
        const recovery = await recoverSharedProjectConflict(snapshot);
        if (recovery) {
          snapshot = recovery.snapshot;
          targetProject = snapshot.projects.find((project) => project.id === snapshot.activeId);
          projectId = targetProject?.id || snapshot.activeId;
          projectUpdatedAt = Number(targetProject?.updatedAt || 0);
          localSaved = localSaved || recovery.localSaved;
          sharedResult = recovery.sharedResult;
          conflictRecovered = true;
          conflictNotice = recovery.notice;
        }
      }
      const result = {
        localSaved,
        sharedSaved: sharedResult.saved === true,
        snapshot,
        projectId,
        projectUpdatedAt,
        confirmedUpdatedAt: Number(sharedResult.confirmedUpdatedAt || 0),
        conflict: sharedResult.conflict === true,
        conflictRecovered,
        conflictNotice,
      };

      const current = state.projects.find((project) => project.id === projectId);
      const stillCurrent = state.currentProjectId === projectId
        && Number(current?.updatedAt || 0) === projectUpdatedAt
        && current?.data?.content === els.content.value
        && saveCheckpoint.phase !== "dirty";
      if (stillCurrent && result.sharedSaved) {
        const savedAt = new Date().toISOString();
        setSaveCheckpoint({
          phase: persistenceMode === "cloud" ? "syncing-cloud" : "degraded",
          projectId,
          targetUpdatedAt: projectUpdatedAt,
          localSavedAt: localSaved ? savedAt : saveCheckpoint.localSavedAt,
          serverSavedAt: savedAt,
          destination: persistenceMode === "cloud" ? "Supabase + 私有 TOS" : "本机项目文件",
          error: "",
        });
        if (persistenceMode === "cloud") void confirmCloudCheckpoint(projectId, projectUpdatedAt);
        if (conflictNotice) els.status.textContent = conflictNotice;
      } else if (stillCurrent && localSaved) {
        setSaveCheckpoint({
          phase: "degraded",
          projectId,
          targetUpdatedAt: projectUpdatedAt,
          localSavedAt: new Date().toISOString(),
          destination: "浏览器本地数据库",
          error: result.conflict
            ? "检测到团队成员的新版本，旧缓存未覆盖云端；请重新打开该稿或另存副本"
            : "本机项目服务暂未确认，刷新前请勿关闭页面",
        });
      } else if (stillCurrent && !localSaved && !result.sharedSaved) {
        setSaveCheckpoint({ phase: "error", error: "浏览器数据库与本机项目文件均未确认写入" });
      }
      return result;
    });
  localDatabaseSaveChain = queuedSave;
  return queuedSave;
}

function scheduleProjectStoreToIndexedDb() {
  if (!state.localDatabaseHydrated) return;
  if (localDatabaseSaveTimer) return;
  localDatabaseSaveTimer = window.setTimeout(flushProjectStoreToIndexedDb, LOCAL_DATABASE_SAVE_DELAY);
}

async function loadProjectStoreFromIndexedDb() {
  const database = await openLocalDatabase();
  if (!database) return null;
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(LOCAL_DATABASE_STORE, "readonly");
    const request = transaction.objectStore(LOCAL_DATABASE_STORE).get(LOCAL_DATABASE_PROJECTS_KEY);
    request.onsuccess = () => resolve(request.result || null);
    request.onerror = () => reject(request.error || new Error("本地草稿数据库读取失败"));
    transaction.oncomplete = () => database.close();
    transaction.onerror = () => {
      const error = transaction.error || new Error("本地草稿数据库读取失败");
      database.close();
      reject(error);
    };
  });
}

function mergeProjectLists(existingProjects, incomingProjects, { preferIncomingOnEqual = false } = {}) {
  const merged = new Map();
  for (const source of [...(existingProjects || []), ...(incomingProjects || [])]) {
    const project = normalizeProject(source);
    if (!project) continue;
    const current = merged.get(project.id);
    if (
      !current
      || project.updatedAt > current.updatedAt
      || (preferIncomingOnEqual && project.updatedAt === current.updatedAt && !projectRevisionMatches(project, current))
    ) {
      merged.set(project.id, project);
    }
  }
  return [...merged.values()]
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .slice(0, MAX_PROJECTS);
}

function projectDeletionTimestamp(deletion) {
  const value = Number(deletion?.deletedAt || 0);
  return Number.isSafeInteger(value) && value > 0 ? value : 0;
}

function normalizeProjectDeletions(source) {
  const merged = new Map();
  for (const deletion of Array.isArray(source) ? source : []) {
    const id = typeof deletion?.id === "string" ? deletion.id : "";
    const deletedAt = projectDeletionTimestamp(deletion);
    if (!id || !deletedAt || isBuiltInProjectId(id)) continue;
    const previous = merged.get(id);
    if (!previous || deletedAt > previous.deletedAt) merged.set(id, { id, deletedAt });
  }
  return [...merged.values()].sort((a, b) => b.deletedAt - a.deletedAt);
}

function mergeProjectDeletions(...sources) {
  return normalizeProjectDeletions(sources.flatMap((source) => Array.isArray(source) ? source : []));
}

function promoteLocalDeletionIntents(deletions, projects) {
  const liveById = new Map((projects || []).map((project) => [project.id, project]));
  return normalizeProjectDeletions(deletions).map((deletion) => {
    const live = liveById.get(deletion.id);
    return live && deletion.deletedAt <= Number(live.updatedAt || 0)
      ? { ...deletion, deletedAt: Number(live.updatedAt || 0) + 1 }
      : deletion;
  });
}

function stableJsonValue(value) {
  if (Array.isArray(value)) return value.map(stableJsonValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, stableJsonValue(value[key])]),
    );
  }
  return value;
}

function stableJsonStringify(value) {
  return JSON.stringify(stableJsonValue(value));
}

function resolveProjectDeletionWinners(projects, deletions) {
  const liveById = new Map((projects || []).map((project) => [project.id, project]));
  const winningDeletions = normalizeProjectDeletions(deletions).filter((deletion) => {
    const live = liveById.get(deletion.id);
    return !live || deletion.deletedAt >= Number(live.updatedAt || 0);
  });
  const deletedIds = new Set(winningDeletions.map((deletion) => deletion.id));
  return {
    projects: (projects || []).filter((project) => !deletedIds.has(project.id)),
    deletedProjects: winningDeletions,
  };
}

function rememberActiveProject(projectId) {
  if (typeof projectId !== "string") return false;
  try {
    if (!projectId) {
      localStorage.removeItem(ACTIVE_PROJECT_STORAGE_KEY);
      return true;
    }
    localStorage.setItem(ACTIVE_PROJECT_STORAGE_KEY, projectId);
    return true;
  } catch (error) {
    console.warn("当前打开项目记录失败", error);
    return false;
  }
}

function loadRememberedActiveProject() {
  try {
    return localStorage.getItem(ACTIVE_PROJECT_STORAGE_KEY) || null;
  } catch {
    return null;
  }
}

function loadPendingProjectDeletionsFromLocalStorage() {
  try {
    return normalizeProjectDeletions(JSON.parse(localStorage.getItem(PENDING_PROJECT_DELETIONS_STORAGE_KEY) || "[]"));
  } catch {
    return [];
  }
}

function loadPendingProjectDeletions() {
  if (pendingProjectDeletionsCache === null) {
    pendingProjectDeletionsCache = loadPendingProjectDeletionsFromLocalStorage();
  }
  return [...pendingProjectDeletionsCache];
}

function savePendingProjectDeletionsToLocalStorage(deletions) {
  try {
    localStorage.setItem(
      PENDING_PROJECT_DELETIONS_STORAGE_KEY,
      JSON.stringify(normalizeProjectDeletions(deletions)),
    );
    return true;
  } catch (error) {
    console.warn("待重试删除记录保存失败", error);
    return false;
  }
}

function updatePendingProjectDeletions(transform) {
  const queuedUpdate = pendingProjectDeletionSaveChain
    .catch(() => ({ saved: false, deletions: loadPendingProjectDeletions() }))
    .then(async () => {
      let indexedDbDeletions = [];
      try {
        indexedDbDeletions = await loadPendingProjectDeletionsFromIndexedDb();
      } catch (error) {
        console.warn("IndexedDB 待重试删除记录读取失败", error);
      }
      const current = mergeProjectDeletions(
        loadPendingProjectDeletions(),
        loadPendingProjectDeletionsFromLocalStorage(),
        indexedDbDeletions,
      );
      const next = normalizeProjectDeletions(transform(current));
      pendingProjectDeletionsCache = next;
      const localStorageSaved = savePendingProjectDeletionsToLocalStorage(next);
      let indexedDbSaved = false;
      try {
        indexedDbSaved = await savePendingProjectDeletionsToIndexedDb(next);
      } catch (error) {
        console.warn("IndexedDB 待重试删除记录写入失败", error);
      }
      return {
        saved: localStorageSaved || indexedDbSaved,
        deletions: [...next],
      };
    });
  pendingProjectDeletionSaveChain = queuedUpdate;
  return queuedUpdate;
}

async function markPendingProjectDeletion(deletion) {
  const result = await updatePendingProjectDeletions((current) =>
    mergeProjectDeletions(current, [deletion]),
  );
  return result.saved;
}

async function clearPendingProjectDeletion(projectIds) {
  const ids = new Set(Array.isArray(projectIds) ? projectIds : [projectIds]);
  const result = await updatePendingProjectDeletions((current) =>
    current.filter((deletion) => !ids.has(deletion.id)),
  );
  return result.saved;
}

function projectRevisionMatches(first, second) {
  if (!first || !second) return false;
  if (
    first.id !== second.id
    || Number(first.updatedAt) !== Number(second.updatedAt)
    || Number(first.cloudBaseUpdatedAt || 0) !== Number(second.cloudBaseUpdatedAt || 0)
    || first.title !== second.title
  ) {
    return false;
  }
  if (first.data === second.data) return true;
  try {
    return stableJsonStringify(first.data) === stableJsonStringify(second.data);
  } catch {
    return false;
  }
}

function comparableDraftValue(value) {
  if (Array.isArray(value)) return value.map(comparableDraftValue);
  if (!value || typeof value !== "object") return value;
  const cloudAssetId = typeof value.cloudAssetId === "string" ? value.cloudAssetId : "";
  const ignored = new Set(["cloudAssetId", "cloudObjectKey", "localAssetId", "localAssetName"]);
  return Object.fromEntries(
    Object.entries(value)
      .filter(([key]) => !ignored.has(key))
      .map(([key, item]) => [
        key,
        key === "src" && cloudAssetId ? `cloud-asset:${cloudAssetId}` : comparableDraftValue(item),
      ]),
  );
}

function draftValuesMatch(first, second) {
  if (first === second) return true;
  try {
    return stableJsonStringify(comparableDraftValue(first))
      === stableJsonStringify(comparableDraftValue(second));
  } catch {
    return false;
  }
}

function sharedProjectBase(project) {
  const normalized = normalizeProject(project);
  if (!normalized) return null;
  return {
    id: normalized.id,
    title: normalized.title,
    updatedAt: Number(project.updatedAt || normalized.updatedAt || 0),
    data: normalized.data,
  };
}

function mergeProjectWithSharedBase(base, localProject, sharedProject) {
  if (!base || !localProject || !sharedProject || localProject.id !== sharedProject.id || base.id !== localProject.id) {
    return null;
  }
  const normalizedLocal = sharedProjectBase(localProject);
  const normalizedShared = sharedProjectBase(sharedProject);
  if (!normalizedLocal || !normalizedShared) return null;

  let title;
  if (draftValuesMatch(normalizedLocal.title, base.title)) title = normalizedShared.title;
  else if (draftValuesMatch(normalizedShared.title, base.title)) title = normalizedLocal.title;
  else if (draftValuesMatch(normalizedLocal.title, normalizedShared.title)) title = normalizedLocal.title;
  else return null;

  const mergedData = {};
  const keys = new Set([
    ...Object.keys(base.data || {}),
    ...Object.keys(normalizedLocal.data || {}),
    ...Object.keys(normalizedShared.data || {}),
  ]);
  for (const key of keys) {
    const baseValue = base.data?.[key];
    const localValue = normalizedLocal.data?.[key];
    const sharedValue = normalizedShared.data?.[key];
    if (draftValuesMatch(localValue, baseValue)) mergedData[key] = sharedValue;
    else if (draftValuesMatch(sharedValue, baseValue)) mergedData[key] = localValue;
    else if (draftValuesMatch(localValue, sharedValue)) mergedData[key] = localValue;
    else return null;
  }
  return {
    ...localProject,
    title,
    updatedAt: Math.max(
      Date.now(),
      Number(localProject.updatedAt || 0) + 1,
      Number(sharedProject.updatedAt || 0) + 1,
    ),
    data: mergedData,
  };
}

function rememberSharedProjectVersions(store) {
  if (!store || !Array.isArray(store.projects)) return;
  sharedProjectIds.clear();
  sharedProjectVersions.clear();
  sharedProjectBases.clear();
  store.projects.forEach((project) => {
    if (!project?.id) return;
    sharedProjectIds.add(project.id);
    const updatedAt = Number(project.updatedAt || 0);
    if (updatedAt > 0) sharedProjectVersions.set(project.id, updatedAt);
    const base = sharedProjectBase(project);
    if (base) sharedProjectBases.set(project.id, base);
  });
}

function localConflictProject(project, occupiedIds) {
  const suffix = Number(project.updatedAt || 0).toString(36);
  const conflictRoot = typeof project.data?.__localConflictOf === "string"
    ? project.data.__localConflictOf
    : project.id;
  const baseId = `${conflictRoot}_local_conflict_${suffix}`;
  let id = baseId;
  let index = 2;
  while (occupiedIds.has(id)) {
    id = `${baseId}_${index}`;
    index += 1;
  }
  occupiedIds.add(id);
  const baseTitle = normalizeConflictDraftTitle(project.title || projectTitleFromData(project.data))
    .replace(/ · 冲突备份$/, "");
  const title = `${baseTitle.slice(0, Math.max(1, 40 - " · 冲突备份".length))} · 冲突备份`;
  return {
    ...project,
    id,
    title: title.slice(0, 40),
    updatedAt: nextProjectTimestamp(project),
    data: { ...project.data, __localConflictOf: conflictRoot },
  };
}

function reconcileLocalProjectsWithShared(localProjects, sharedProjects) {
  const normalizedLocal = mergeProjectLists([], localProjects);
  const normalizedShared = mergeProjectLists([], sharedProjects, { preferIncomingOnEqual: true });
  if (!normalizedShared.length) return normalizedLocal;

  const sharedById = new Map(normalizedShared.map((project) => [project.id, project]));
  const occupiedIds = new Set([
    ...normalizedLocal.map((project) => project.id),
    ...normalizedShared.map((project) => project.id),
  ]);
  const localOnly = [];
  const conflicts = [];
  for (const localProject of normalizedLocal) {
    const sharedProject = sharedById.get(localProject.id);
    if (!sharedProject) {
      localOnly.push(localProject);
      continue;
    }
    if (
      !projectRevisionMatches(localProject, sharedProject)
      && Number(localProject.updatedAt || 0) > Number(sharedProject.updatedAt || 0)
    ) {
      conflicts.push(localConflictProject(localProject, occupiedIds));
    }
  }
  return [...normalizedShared, ...conflicts, ...localOnly]
    .sort((first, second) => Number(second.updatedAt || 0) - Number(first.updatedAt || 0))
    .slice(0, MAX_PROJECTS);
}

function restoreImportedProjects(existingProjects, incomingProjects, deletedProjects = []) {
  const normalizedIncoming = (incomingProjects || []).map(normalizeProject).filter(Boolean);
  const importedIds = new Set(normalizedIncoming.map((project) => project.id));
  const existingById = new Map(
    (existingProjects || []).map((project) => [project.id, project]),
  );
  const deletionById = new Map(
    normalizeProjectDeletions(deletedProjects).map((deletion) => [deletion.id, deletion]),
  );
  let nextRestoredAt = Date.now();
  const restoredProjects = normalizedIncoming.map((project) => {
    const existing = existingById.get(project.id);
    const deletion = deletionById.get(project.id);
    const updatedAt = Math.max(
      nextRestoredAt,
      Number(project.updatedAt || 0) + 1,
      Number(existing?.updatedAt || 0) + 1,
      Number(deletion?.deletedAt || 0) + 1,
    );
    nextRestoredAt = updatedAt + 1;
    return {
      ...project,
      // 用户明确确认导入时，备份必须同时胜过本机旧版本与任何未来时钟墓碑。
      updatedAt,
      cloudBaseUpdatedAt: Number(existing?.cloudBaseUpdatedAt ?? existing?.updatedAt ?? 0),
    };
  });
  const untouchedProjects = (existingProjects || [])
    .map(normalizeProject)
    .filter((project) => project && !importedIds.has(project.id));
  return [...restoredProjects, ...untouchedProjects]
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .slice(0, MAX_PROJECTS);
}

async function hydrateProjectStoreFromIndexedDb() {
  try {
    const [stored, shared, indexedDbPendingDeletions] = await Promise.all([
      loadProjectStoreFromIndexedDb(),
      loadProjectStoreFromSharedServer(),
      loadPendingProjectDeletionsFromIndexedDb().catch((error) => {
        console.warn("IndexedDB 待重试删除记录恢复失败", error);
        return [];
      }),
    ]);
    const storedProjects = stored && Array.isArray(stored.projects) ? stored.projects : [];
    const sharedProjects = shared && Array.isArray(shared.projects) ? shared.projects : [];
    const projectsBeforeHydration = state.projects;
    const activeBeforeHydration = projectsBeforeHydration.find((project) => project.id === state.currentProjectId);
    const mergedCandidates = reconcileLocalProjectsWithShared(
      mergeProjectLists(state.projects, storedProjects),
      sharedProjects,
    );
    const localDeletionIntents = promoteLocalDeletionIntents(
      mergeProjectDeletions(
        loadPendingProjectDeletions(),
        indexedDbPendingDeletions,
      ),
      mergedCandidates,
    );
    if (localDeletionIntents.length) {
      await updatePendingProjectDeletions((current) =>
        mergeProjectDeletions(current, localDeletionIntents),
      );
    }
    const sharedDeletions = normalizeProjectDeletions(shared?.deletedProjects);
    const resolved = resolveProjectDeletionWinners(
      mergedCandidates,
      mergeProjectDeletions(
        state.deletedProjects,
        stored?.deletedProjects,
        localDeletionIntents,
        sharedDeletions,
      ),
    );
    const merged = resolved.projects;
    const changed =
      merged.length !== state.projects.length ||
      merged.some((project, index) => !projectRevisionMatches(project, state.projects[index])) ||
      JSON.stringify(resolved.deletedProjects) !== JSON.stringify(state.deletedProjects);
    state.deletedProjects = resolved.deletedProjects;
    if (changed) {
      state.projects = merged;
      const mergedActive = state.projects.find((project) => project.id === state.currentProjectId);
      // The current browser selection is UI state, not a shared/cloud choice.
      // Only fall back when that project was actually deleted or is unavailable.
      const rememberedActiveId = loadRememberedActiveProject();
      const preferredActiveId = requestedProjectIdFromUrl() || rememberedActiveId || stored?.activeId || shared?.activeId;
      const storedActive = state.projects.find((project) => project.id === preferredActiveId);
      const activeWasReplaced = mergedActive && !projectRevisionMatches(mergedActive, activeBeforeHydration);
      const projectToApply = activeWasReplaced
        ? mergedActive
        : !mergedActive && (!isBuiltInProjectId(state.currentProjectId) || !isBuiltInProjectId(rememberedActiveId))
          ? storedActive || state.projects[0] || null
          : null;
      if (projectToApply) {
        state.currentProjectId = projectToApply.id;
        rememberActiveProject(projectToApply.id);
        applyForm(projectToApply.data);
        syncGuideReadOnlyMode();
        resetTextHistory();
        await render({ persist: false });
      } else if (!state.projects.length && !mergedActive) {
        state.currentProjectId = null;
        rememberActiveProject("");
        applyForm(blankFormState());
        syncGuideReadOnlyMode();
        resetTextHistory();
        await render({ persist: false });
      }
      updateProjectHistory();
    }
    state.localDatabaseHydrated = true;
    saveProjectStore({ scheduleDatabase: false });
    await saveProjectStoreToIndexedDb(projectStoreSnapshot()).catch((error) => {
      console.warn("合并后的共享草稿写入 IndexedDB 失败", error);
    });
    const sharedDeletionById = new Map(sharedDeletions.map((deletion) => [deletion.id, deletion]));
    const pendingDeletionIntents = localDeletionIntents.filter((deletion) => {
      const confirmed = sharedDeletionById.get(deletion.id);
      return !confirmed || confirmed.deletedAt < deletion.deletedAt;
    });
    const confirmedDeletionIds = localDeletionIntents
      .filter((deletion) => !pendingDeletionIntents.some((pending) => pending.id === deletion.id))
      .map((deletion) => deletion.id);
    if (confirmedDeletionIds.length) {
      await clearPendingProjectDeletion(confirmedDeletionIds);
    }
    if (pendingDeletionIntents.length) void retryPendingProjectDeletions(pendingDeletionIntents);
    void refreshPersistenceMode();
    if (sharedProjectStoreAvailable) {
      els.status.textContent = "已连接共享草稿库，Codex 与 Chrome 刷新后会读取同一版本";
    }
  } catch (error) {
    console.warn("IndexedDB 草稿恢复失败", error);
    state.localDatabaseHydrated = true;
    void refreshPersistenceMode();
  }
}

function loadProjectStore() {
  try {
    const raw = localStorage.getItem(PROJECTS_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      const projects = Array.isArray(parsed.projects)
        ? parsed.projects.map(normalizeProject).filter(Boolean).slice(0, MAX_PROJECTS)
        : [];
      const resolved = resolveProjectDeletionWinners(projects, parsed.deletedProjects);
      const rememberedActiveId = loadRememberedActiveProject();
      const preferredActiveId = requestedProjectIdFromUrl() || rememberedActiveId || parsed.activeId;
      const activeId = isBuiltInProjectId(preferredActiveId)
        ? preferredActiveId
        : resolved.projects.some((project) => project.id === preferredActiveId)
          ? preferredActiveId
          : resolved.projects[0]?.id || null;
      return { activeId, projects: resolved.projects, deletedProjects: resolved.deletedProjects };
    }

    const legacyRaw = localStorage.getItem(STORAGE_KEY);
    if (!legacyRaw) return { activeId: null, projects: [], deletedProjects: [] };

    const legacyData = JSON.parse(legacyRaw);
    const project = createProject(legacyData);
    return { activeId: project.id, projects: [project], deletedProjects: [] };
  } catch {
    return { activeId: null, projects: [], deletedProjects: [] };
  }
}

function requestedProjectIdFromUrl() {
  try {
    return new URLSearchParams(window.location.search).get("project") || "";
  } catch {
    return "";
  }
}

function normalizeProject(project) {
  if (!project || typeof project !== "object") return null;
  if (isBuiltInProjectId(project.id)) return null;
  const sourceData = project.data && typeof project.data === "object" ? project.data : {};
  const data = migrateStoredState({ ...defaultFormState(), ...sourceData });
  const sourceUpdatedAt = Number(project.updatedAt) || Date.now();
  let normalizedChanged = false;
  try {
    normalizedChanged = stableJsonStringify(sourceData) !== stableJsonStringify(data);
  } catch {
    normalizedChanged = true;
  }
  // A migration changes the whole project snapshot. Give it a real revision so
  // the server never has to accept different data under an identical timestamp.
  const updatedAt = normalizedChanged ? sourceUpdatedAt + 1 : sourceUpdatedAt;
  const sourceCloudBaseUpdatedAt = Number(project.cloudBaseUpdatedAt);
  const cloudBaseUpdatedAt = Number.isSafeInteger(sourceCloudBaseUpdatedAt) && sourceCloudBaseUpdatedAt >= 0
    ? sourceCloudBaseUpdatedAt
    : sourceUpdatedAt;
  return {
    id: project.id || `project_${updatedAt.toString(36)}`,
    title: normalizeConflictDraftTitle(project.title) || projectTitleFromData(data),
    updatedAt,
    cloudBaseUpdatedAt,
    data,
  };
}

function saveProjectStore({ scheduleDatabase = true } = {}) {
  const snapshot = projectStoreSnapshot();
  rememberActiveProject(snapshot.activeId);
  let localStorageSaved = !projectStoreLocalStorageUnavailable;
  if (!projectStoreLocalStorageUnavailable) {
    try {
      localStorage.setItem(PROJECTS_STORAGE_KEY, JSON.stringify(snapshot));
    } catch (error) {
      localStorageSaved = false;
      projectStoreLocalStorageUnavailable = true;
      console.warn("LocalStorage 草稿写入失败，后续改用 IndexedDB", error);
    }
  }
  if (state.localDatabaseHydrated && scheduleDatabase) {
    scheduleProjectStoreToIndexedDb();
  }
  return localStorageSaved;
}

function backupTimestamp(date = new Date()) {
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

function createProjectBackupPayload() {
  saveState();
  const snapshot = projectStoreSnapshot();
  return {
    schema: PROJECT_BACKUP_SCHEMA,
    version: PROJECT_BACKUP_VERSION,
    exportedAt: new Date().toISOString(),
    sourceOrigin: window.location.origin,
    activeId: snapshot.activeId,
    projects: snapshot.projects,
  };
}

async function exportProjectBackup() {
  const payload = createProjectBackupPayload();
  if (!payload.projects.length) {
    els.status.textContent = "还没有可备份的草稿";
    return;
  }
  if (state.localDatabaseHydrated) {
    await flushProjectStoreToIndexedDb();
  }
  const filename = `write-then-publish-backup-${backupTimestamp()}.json`;
  const blob = new Blob([JSON.stringify(payload)], { type: "application/json" });
  await saveBlob(blob, filename);
  els.status.textContent = `已备份 ${payload.projects.length} 篇草稿（含图片和排版设置）`;
}

function updatePersistenceControls(status = {}) {
  const cloudConnected = status.enabled === true && status.fallbackToLocal !== true;
  persistenceMode = cloudConnected ? "cloud" : "local";
  saveCheckpoint.destination = cloudConnected
    ? "Supabase + 私有 TOS"
    : status.folderName
      ? `本机文件夹 · ${status.folderName}`
      : "本机项目文件";

  if (els.exportProjectsLabel) {
    els.exportProjectsLabel.textContent = cloudConnected ? "保存" : "导出 JSON";
  }
  if (els.exportProjects) {
    els.exportProjects.title = cloudConnected
      ? "当前内容会自动保存；点击可立即保存并同步到 Supabase 与私有 TOS"
      : "导出全部草稿、图片和排版设置，供本地恢复或迁移";
    els.exportProjects.setAttribute("aria-label", cloudConnected ? "立即保存到云端" : "导出 JSON 备份");
    const icon = els.exportProjects.querySelector("[data-lucide]");
    if (icon) icon.setAttribute("data-lucide", cloudConnected ? "save" : "file-down");
  }
  if (els.historyNote) {
    els.historyNote.textContent = cloudConnected
      ? "云端最新版优先 · 停笔约 3–5 秒同步"
      : "自动保存到本机 · 点击稿件恢复";
  }
  renderSaveCheckpoint();
  if (window.lucide) window.lucide.createIcons();
  return persistenceMode;
}

function cloudCheckpointIdentity(status = {}) {
  return {
    projectId: status.projectId || status.syncedProjectId || status.lastProjectId || null,
    updatedAt: Number(status.syncedUpdatedAt || status.projectUpdatedAt || 0),
  };
}

function cloudCheckpointMatches(status, projectId, updatedAt) {
  const checkpoint = cloudCheckpointIdentity(status);
  return checkpoint.projectId === projectId && checkpoint.updatedAt === Number(updatedAt || 0);
}

function cloudConflictForProject(status, projectId, updatedAt = 0) {
  if (!projectId || !Array.isArray(status?.conflicts)) return null;
  const targetUpdatedAt = Number(updatedAt || 0);
  return status.conflicts.find((item) => {
    if (item?.projectId !== projectId) return false;
    if (!targetUpdatedAt) return true;
    return [Number(item.localUpdatedAt || 0), Number(item.remoteUpdatedAt || 0)].includes(targetUpdatedAt);
  }) || null;
}

function delay(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function confirmCloudCheckpoint(projectId, updatedAt, { attempts = 7 } = {}) {
  if (!projectId || !updatedAt || persistenceMode !== "cloud") return false;
  const generation = ++saveCheckpointPollGeneration;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    if (generation !== saveCheckpointPollGeneration) return false;
    if (attempt > 0) await delay(Math.min(1400, 450 + attempt * 180));
    let status;
    try {
      const response = await fetch(CLOUD_STATUS_URL, { cache: "no-store" });
      if (!response.ok) throw new Error(`保存状态读取失败（${response.status}）`);
      status = await response.json();
    } catch (error) {
      if (attempt === attempts - 1 && generation === saveCheckpointPollGeneration) {
        setSaveCheckpoint({
          phase: "degraded",
          destination: "本机项目文件",
          error: "云端状态暂时无法确认",
        });
      }
      continue;
    }

    updatePersistenceControls(status);
    if (generation !== saveCheckpointPollGeneration) return false;
    if (cloudConflictForProject(status, projectId, updatedAt)) {
      setSaveCheckpoint({
        phase: "conflict",
        projectId,
        targetUpdatedAt: updatedAt,
        error: "另一端也改了这个版本；系统已保留两份内容，没有覆盖任何一方",
      });
      return false;
    }
    if (cloudCheckpointMatches(status, projectId, updatedAt)) {
      markProjectCloudBase(projectId, updatedAt);
      setSaveCheckpoint({
        phase: "saved-cloud",
        projectId,
        targetUpdatedAt: updatedAt,
        cloudUpdatedAt: cloudCheckpointIdentity(status).updatedAt,
        cloudSavedAt: status.lastSuccessAt || new Date().toISOString(),
        destination: "Supabase + 私有 TOS",
        confirmation: "auto",
        error: "",
      });
      return true;
    }
    if (status.fallbackToLocal || status.enabled !== true) {
      setSaveCheckpoint({
        phase: "degraded",
        projectId,
        targetUpdatedAt: updatedAt,
        destination: "本机项目文件",
        error: status.lastError ? "云端不可用，已保留本机副本" : "云端未配置，已保留本机副本",
      });
      return false;
    }
    setSaveCheckpoint({ phase: "syncing-cloud", projectId, targetUpdatedAt: updatedAt, error: "" });
  }
  if (generation === saveCheckpointPollGeneration) {
    setSaveCheckpoint({
      phase: "saved-local",
      projectId,
      targetUpdatedAt: updatedAt,
      error: "云端仍在后台同步，可点击“立即保存”确认",
    });
  }
  return false;
}

async function refreshPersistenceMode({ quiet = true } = {}) {
  try {
    const response = await fetch(CLOUD_STATUS_URL, { cache: "no-store" });
    if (!response.ok) throw new Error(`保存状态读取失败（${response.status}）`);
    const status = await response.json();
    updatePersistenceControls(status);
    const current = state.projects.find((project) => project.id === state.currentProjectId);
    if (current && state.localDatabaseHydrated && saveCheckpoint.phase === "loading") {
      const updatedAt = Number(current.updatedAt || 0);
      if (cloudCheckpointMatches(status, current.id, updatedAt)) {
        markProjectCloudBase(current.id, updatedAt);
        setSaveCheckpoint({
          phase: "saved-cloud",
          projectId: current.id,
          targetUpdatedAt: updatedAt,
          cloudUpdatedAt: cloudCheckpointIdentity(status).updatedAt,
          cloudSavedAt: status.lastSuccessAt || updatedAt,
          destination: "Supabase + 私有 TOS",
          error: "",
        });
      } else {
        setSaveCheckpoint({
          phase: status.enabled === true && !status.fallbackToLocal ? "saved-local" : "degraded",
          projectId: current.id,
          targetUpdatedAt: updatedAt,
          serverSavedAt: updatedAt,
          destination: status.enabled === true && !status.fallbackToLocal ? "本机项目文件 · 云端待确认" : "本机项目文件",
          error: status.fallbackToLocal ? "云端不可用，已使用本机副本" : "",
        });
      }
    }
    return status;
  } catch (error) {
    updatePersistenceControls({ enabled: false, fallbackToLocal: true });
    if (saveCheckpoint.phase !== "dirty" && saveCheckpoint.phase !== "saving-local") {
      setSaveCheckpoint({ phase: "degraded", destination: "浏览器本地数据库", error: "无法连接本机保存服务" });
    }
    if (!quiet) els.status.textContent = "无法连接云端，当前按本地模式保存";
    return { enabled: false, fallbackToLocal: true, lastError: error?.message || String(error) };
  }
}

function formatSavedTime(value) {
  const date = value ? new Date(value) : new Date();
  if (Number.isNaN(date.getTime())) return "刚刚";
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function setPrimarySaveButtonFeedback(label, iconName, { busy = false } = {}) {
  if (els.exportProjectsLabel) els.exportProjectsLabel.textContent = label;
  if (!els.exportProjects) return;
  els.exportProjects.classList.toggle("is-saving", busy);
  els.exportProjects.setAttribute("aria-busy", String(busy));
  const icon = els.exportProjects.querySelector("[data-lucide]");
  if (icon) icon.setAttribute("data-lucide", iconName);
  if (window.lucide) window.lucide.createIcons();
}

function currentManualSaveTarget() {
  const project = state.projects.find((item) => item.id === state.currentProjectId);
  if (!project || isBuiltInProject(project)) return null;
  return {
    projectId: project.id,
    projectUpdatedAt: Number(project.updatedAt || 0),
    content: els.content.value,
  };
}

function manualSaveTargetMatches(generation, target) {
  if (generation !== manualSaveGeneration || !target?.projectId || !target.projectUpdatedAt) return false;
  const current = state.projects.find((item) => item.id === target.projectId);
  return Boolean(
    state.currentProjectId === target.projectId
      && Number(current?.updatedAt || 0) === Number(target.projectUpdatedAt)
      && els.content.value === target.content
      && current?.data?.content === target.content,
  );
}

async function fetchCloudStatusSnapshot() {
  const response = await fetch(CLOUD_STATUS_URL, { cache: "no-store" });
  if (!response.ok) throw new Error(`保存状态读取失败（${response.status}）`);
  return response.json();
}

async function saveProjectNow() {
  if (!els.exportProjects) return;
  const generation = ++manualSaveGeneration;
  els.exportProjects.disabled = true;
  if (els.saveNow) els.saveNow.disabled = true;
  setPrimarySaveButtonFeedback("保存中…", "loader-circle", { busy: true });
  let savedToCloud = false;
  let persisted = null;
  let target = null;
  try {
    saveState();
    target = currentManualSaveTarget();
    if (!target) return;
    if (sharedTextSaveTimer) {
      const textSavePromise = saveCurrentProjectTextToSharedServer();
      target = currentManualSaveTarget();
      await textSavePromise;
      if (!manualSaveTargetMatches(generation, target)) return;
    }
    persisted = state.localDatabaseHydrated
      ? await flushProjectStoreToIndexedDb()
      : { localSaved: saveProjectStore(), sharedSaved: false, projectId: state.currentProjectId, projectUpdatedAt: 0 };
    target = {
      projectId: persisted.projectId,
      projectUpdatedAt: Number(persisted.projectUpdatedAt || 0),
      content: persisted.snapshot?.projects?.find((item) => item.id === persisted.projectId)?.data?.content ?? els.content.value,
    };
    if (!manualSaveTargetMatches(generation, target)) return;
    if (!persisted.localSaved && !persisted.sharedSaved) throw new Error("浏览器数据库与本机项目文件均未确认保存");
    if (!persisted.sharedSaved) {
      throw new Error(
        persisted.conflict
          ? "检测到团队成员保存的新版本；旧缓存未覆盖云端，请重新打开该稿后再保存"
          : "共享草稿库尚未确认当前版本，暂不执行云同步",
      );
    }

    els.status.textContent = "已保存本机副本，正在同步云端…";
    setSaveCheckpoint({
      phase: "syncing-cloud",
      projectId: persisted.projectId,
      targetUpdatedAt: persisted.projectUpdatedAt,
      destination: "Supabase + 私有 TOS",
      error: "",
    });
    const response = await fetch(CLOUD_SYNC_URL, { method: "POST" });
    if (!manualSaveTargetMatches(generation, target)) return;
    const payload = await response.json().catch(() => ({}));
    if (!manualSaveTargetMatches(generation, target)) return;
    const status = payload.status || await fetchCloudStatusSnapshot();
    if (!manualSaveTargetMatches(generation, target)) return;
    updatePersistenceControls(status);
    if (!response.ok || payload.ok !== true || status.fallbackToLocal || !cloudCheckpointMatches(status, persisted.projectId, persisted.projectUpdatedAt)) {
      throw new Error(status.lastError || payload.error || `云同步失败（${response.status}）`);
    }
    markProjectCloudBase(persisted.projectId, persisted.projectUpdatedAt);
    setSaveCheckpoint({
      phase: "saved-cloud",
      projectId: persisted.projectId,
      targetUpdatedAt: persisted.projectUpdatedAt,
      cloudUpdatedAt: cloudCheckpointIdentity(status).updatedAt,
      cloudSavedAt: status.lastSuccessAt || new Date().toISOString(),
      destination: "Supabase + 私有 TOS",
      confirmation: "manual",
      error: "",
    });
    els.status.textContent = `已保存到云端 · ${formatSavedTime(status.lastSuccessAt)}`;
    savedToCloud = true;
    setPrimarySaveButtonFeedback("已保存", "check");
  } catch (error) {
    console.warn("手动保存到云端失败", error);
    if (!manualSaveTargetMatches(generation, target)) return;
    let status;
    try {
      status = await fetchCloudStatusSnapshot();
    } catch (statusError) {
      status = {
        enabled: false,
        fallbackToLocal: true,
        lastError: statusError?.message || String(statusError),
      };
    }
    if (!manualSaveTargetMatches(generation, target)) return;
    updatePersistenceControls(status);
    if (status.fallbackToLocal || status.enabled !== true) {
      setSaveCheckpoint({
        phase: persisted?.sharedSaved || persisted?.localSaved ? "degraded" : "error",
        destination: persisted?.sharedSaved ? "本机项目文件" : "浏览器本地数据库",
        error: "云端不可用，当前版本的本机副本已保留",
      });
      els.status.textContent = `已自动保存到本机；云端不可用，可点击“导出 JSON”备份${status.lastError ? `（${status.lastError}）` : ""}`;
    } else {
      setSaveCheckpoint({
        phase: persisted?.sharedSaved || persisted?.localSaved ? "saved-local" : "error",
        destination: persisted?.sharedSaved ? "本机项目文件" : "浏览器本地数据库",
        error: error?.message || "云端保存未确认",
      });
      els.status.textContent = `本机副本已保留，云端保存未确认：${error?.message || "请稍后重试"}`;
    }
  } finally {
    els.exportProjects.disabled = false;
    renderSaveCheckpoint();
    if (savedToCloud && generation === manualSaveGeneration) {
      window.setTimeout(() => {
        if (generation === manualSaveGeneration) updatePersistenceControls({ enabled: true, fallbackToLocal: false });
      }, 1800);
    } else if (generation !== manualSaveGeneration) {
      setPrimarySaveButtonFeedback(persistenceMode === "cloud" ? "保存" : "导出 JSON", persistenceMode === "cloud" ? "save" : "file-down");
    } else if (persistenceMode === "cloud") {
      updatePersistenceControls({ enabled: true, fallbackToLocal: false });
    }
  }
}

async function handlePrimaryPersistenceAction() {
  if (persistenceMode === "detecting") await refreshPersistenceMode({ quiet: false });
  if (persistenceMode === "cloud") {
    await saveProjectNow();
    return;
  }
  await exportProjectBackup();
}

async function importProjectBackupPayload(payload) {
  if (!payload || typeof payload !== "object") throw new Error("备份文件格式无效");
  if (payload.schema && payload.schema !== PROJECT_BACKUP_SCHEMA) throw new Error("不是写了就发的草稿备份");
  const sourceProjects = Array.isArray(payload.projects) ? payload.projects : [];
  const importedProjects = sourceProjects.map(normalizeProject).filter(Boolean);
  if (!importedProjects.length) throw new Error("备份中没有可导入的草稿");

  saveState();
  const beforeById = new Map(state.projects.map((project) => [project.id, project]));
  state.projects = restoreImportedProjects(state.projects, importedProjects, state.deletedProjects);
  const importedIds = new Set(importedProjects.map((project) => project.id));
  state.deletedProjects = normalizeProjectDeletions(state.deletedProjects)
    .filter((deletion) => !importedIds.has(deletion.id));
  await clearPendingProjectDeletion([...importedIds]);
  const addedCount = importedProjects.filter((project) => !beforeById.has(project.id)).length;
  const updatedCount = importedProjects.filter((project) => beforeById.has(project.id)).length;

  const preferredId = importedIds.has(payload.activeId) ? payload.activeId : importedProjects[0].id;
  const preferredProject = state.projects.find((project) => project.id === preferredId) || state.projects[0];
  state.currentProjectId = preferredProject.id;
  state.mode = "auto";
  state.scrollOffset = 0;
  applyForm(preferredProject.data);
  syncGuideReadOnlyMode();
  resetTextHistory();
  saveProjectStore();
  updateProjectHistory();
  const persistenceResult = state.localDatabaseHydrated ? await flushProjectStoreToIndexedDb() : null;
  const databaseSaved = Boolean(persistenceResult?.localSaved || persistenceResult?.sharedSaved);
  await render();
  els.status.textContent = databaseSaved
    ? `已导入并写入本地数据库：${importedProjects.length} 篇（新增 ${addedCount}，恢复覆盖 ${updatedCount}）`
    : `已导入 ${importedProjects.length} 篇（新增 ${addedCount}，恢复覆盖 ${updatedCount}）；建议等待自动保存后再刷新`;
}

function inspectProjectBackupPayload(payload) {
  if (!payload || typeof payload !== "object") throw new Error("备份文件格式无效");
  if (payload.schema && payload.schema !== PROJECT_BACKUP_SCHEMA) throw new Error("不是写了就发的草稿备份");
  const projects = (Array.isArray(payload.projects) ? payload.projects : []).map(normalizeProject).filter(Boolean);
  if (!projects.length) throw new Error("备份中没有可导入的草稿");

  const existingById = new Map(state.projects.map((project) => [project.id, project]));
  const items = projects.map((project) => {
    const existing = existingById.get(project.id);
    let action = "新增";
    if (existing) {
      action = project.updatedAt === existing.updatedAt ? "内容相同" : "覆盖当前版本";
    }
    return { project, action };
  });

  return {
    projects,
    items,
    addedCount: items.filter((item) => item.action === "新增").length,
    updatedCount: items.filter((item) => item.action === "覆盖当前版本").length,
    sameCount: items.filter((item) => item.action === "内容相同").length,
  };
}

function closeProjectImportPreview() {
  pendingProjectImport = null;
  els.importPreviewModal?.classList.add("hidden");
}

function openProjectImportPreview(payload, filename) {
  const inspection = inspectProjectBackupPayload(payload);
  pendingProjectImport = { payload, inspection };
  els.importPreviewFile.textContent = filename || "本地 JSON";
  els.importPreviewSource.textContent = payload.sourceOrigin || "未记录来源地址";
  const summaryParts = [`共 ${inspection.projects.length} 篇`, `新增 ${inspection.addedCount}`, `更新 ${inspection.updatedCount}`];
  if (inspection.sameCount) summaryParts.push(`相同 ${inspection.sameCount}`);
  els.importPreviewSummary.textContent = summaryParts.join(" · ");
  els.importPreviewList.replaceChildren(
    ...inspection.items.map(({ project, action }) => {
      const item = document.createElement("li");
      const title = document.createElement("span");
      const badge = document.createElement("strong");
      title.textContent = project.title;
      badge.textContent = action;
      badge.dataset.action = action;
      item.append(title, badge);
      return item;
    }),
  );
  els.importPreviewModal.classList.remove("hidden");
  els.importPreviewConfirm?.focus();
}

async function confirmProjectBackupImport() {
  const pending = pendingProjectImport;
  if (!pending) return;
  els.importPreviewConfirm.disabled = true;
  try {
    await importProjectBackupPayload(pending.payload);
    closeProjectImportPreview();
  } catch (error) {
    console.error(error);
    els.status.textContent = `导入失败：${error?.message || "无法导入备份文件"}`;
  } finally {
    els.importPreviewConfirm.disabled = false;
  }
}

async function handleProjectBackupImport(event) {
  const input = event.currentTarget;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  try {
    const payload = JSON.parse(await file.text());
    openProjectImportPreview(payload, file.name);
  } catch (error) {
    console.error(error);
    els.status.textContent = `导入失败：${error?.message || "无法读取备份文件"}`;
  }
}

async function restoreProjectBackupFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const backupPath = params.get("restoreBackup");
  if (!backupPath) return;

  try {
    const backupUrl = new URL(backupPath, window.location.origin);
    if (backupUrl.origin !== window.location.origin) throw new Error("只允许恢复当前本地服务中的备份");
    const response = await fetch(backupUrl, { cache: "no-store" });
    if (!response.ok) throw new Error(`备份读取失败（${response.status}）`);
    await importProjectBackupPayload(await response.json());
    if (state.localDatabaseHydrated) {
      await flushProjectStoreToIndexedDb();
    }
    els.status.textContent = `已从本地归档恢复 ${state.projects.length} 篇草稿`;
  } catch (error) {
    console.error(error);
    els.status.textContent = `恢复失败：${error?.message || "无法读取本地归档"}`;
  } finally {
    params.delete("restoreBackup");
    const nextQuery = params.toString();
    window.history.replaceState(null, "", `${window.location.pathname}${nextQuery ? `?${nextQuery}` : ""}${window.location.hash}`);
  }
}

function projectTitleFromData(data) {
  const contentLine = String(data.content || "")
    .split("\n")
    .map((line) =>
      line
        .replace(/^\s*#+\s*/, "")
        .replace(/\{\{(?:color|bg):#[0-9a-f]{3,8}\|([\s\S]*?)\}\}/gi, "$1")
        .replace(/\*\*([^*]+)\*\*/g, "$1")
        .replace(/[`*_~]/g, "")
        .trim(),
    )
    .find((line) => line && !line.startsWith("[[image:"));
  return (contentLine || data.displayName || "未命名图文").slice(0, 24);
}

function normalizeProjectTitle(value) {
  return String(value || "").replace(/\s+/g, " ").trim().slice(0, 40);
}

function normalizeConflictDraftTitle(value) {
  const title = normalizeProjectTitle(value) || "未命名图文";
  const suffixPattern = /(?: · (?:本地未同步副本|冲突备份))+$/;
  if (!suffixPattern.test(title)) return title;
  const suffix = " · 冲突备份";
  const base = title.replace(suffixPattern, "").trim() || "未命名图文";
  return `${base.slice(0, Math.max(1, 40 - suffix.length))}${suffix}`;
}

function duplicateProjectTitle(title) {
  const existingTitles = new Set(state.projects.map((project) => project.title));
  const base = (normalizeProjectTitle(title) || "未命名图文")
    .replace(/ · 副本(?: \d+)?$/, "");
  let copyNumber = 1;
  while (true) {
    const suffix = copyNumber === 1 ? " · 副本" : ` · 副本 ${copyNumber}`;
    const candidate = `${base.slice(0, Math.max(1, 40 - suffix.length))}${suffix}`;
    if (!existingTitles.has(candidate)) return candidate;
    copyNumber += 1;
  }
}

function updateCurrentProjectTitle() {
  if (isBuiltInProjectId(state.currentProjectId)) return;
  // Keep the persisted project untouched until saveState creates a real
  // revision. Mutating it here makes saveState think the new title is already
  // saved, so switching projects restores the old server title.
  scheduleStateSave();
}

function formatProjectTime(time) {
  const date = new Date(time);
  if (Number.isNaN(date.getTime())) return "";
  return `${String(date.getMonth() + 1).padStart(2, "0")}/${String(date.getDate()).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function projectType(project) {
  return project?.data?.appMode === "article" ? "article" : "cards";
}

function projectTypeLabel(type) {
  return type === "article" ? "长文" : "图文";
}

function clearHistoryDeleteConfirmation({ render = true } = {}) {
  if (pendingHistoryDeleteTimer) window.clearTimeout(pendingHistoryDeleteTimer);
  pendingHistoryDeleteTimer = 0;
  pendingHistoryDeleteProjectId = null;
  if (render) updateProjectHistory();
}

function requestProjectDeletion(projectId) {
  const project = state.projects.find((item) => item.id === projectId);
  if (!project || isBuiltInProject(project)) return;
  const projectName = project.title || "未命名图文";
  if (pendingHistoryDeleteProjectId === project.id) {
    clearHistoryDeleteConfirmation({ render: false });
    updateProjectHistory();
    void deleteProject(project.id, { confirmed: true });
    return;
  }

  if (pendingHistoryDeleteTimer) window.clearTimeout(pendingHistoryDeleteTimer);
  pendingHistoryDeleteProjectId = project.id;
  els.status.textContent = `再次点击“确认删除”才会永久删除：${projectName}`;
  updateProjectHistory();
  pendingHistoryDeleteTimer = window.setTimeout(() => {
    if (pendingHistoryDeleteProjectId !== project.id) return;
    pendingHistoryDeleteProjectId = null;
    pendingHistoryDeleteTimer = 0;
    els.status.textContent = `已取消删除：${projectName}`;
    updateProjectHistory();
  }, HISTORY_DELETE_CONFIRM_TIMEOUT);
}

function updateProjectHistory() {
  if (!els.projectHistory) return;
  els.projectHistory.innerHTML = "";
  els.historyFilterButtons.forEach((button) => {
    const active = button.dataset.historyFilter === state.historyFilter;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });

  const visibleProjects = allHistoryProjects().filter((project) => {
    if (state.historyFilter === "all") return true;
    return projectType(project) === state.historyFilter;
  });

  if (!visibleProjects.length) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = state.historyFilter === "article" ? "暂无长文记录" : state.historyFilter === "cards" ? "暂无图文记录" : "暂无历史记录";
    els.projectHistory.append(empty);
    return;
  }

  for (const project of visibleProjects) {
    const type = projectType(project);
    const builtIn = isBuiltInProject(project);
    const confirmingDelete = pendingHistoryDeleteProjectId === project.id;
    const item = document.createElement("div");
    item.className = "history-item";
    item.classList.toggle("built-in", builtIn);
    item.classList.toggle("active", project.id === state.currentProjectId);
    item.dataset.projectType = type;
    item.dataset.projectId = project.id;
    item.innerHTML = `
      <button type="button" class="history-open">
        <span>${escapeHtml(project.title || "未命名图文")}</span>
        <small><b>${builtIn ? "说明" : projectTypeLabel(type)}</b>${builtIn ? projectTypeLabel(type) : formatProjectTime(project.updatedAt)}</small>
      </button>
      ${
        builtIn
          ? '<span class="history-lock" title="内置说明书不可修改"><i data-lucide="lock"></i></span>'
          : `<span class="history-actions${confirmingDelete ? " confirming" : ""}">
              <button type="button" class="history-duplicate" title="复制一份" aria-label="复制 ${escapeHtml(project.title || "未命名图文")}">
                <i data-lucide="copy-plus"></i>
              </button>
              <button type="button" class="history-delete${confirmingDelete ? " confirming" : ""}" title="${confirmingDelete ? "再次点击确认永久删除" : "删除历史记录"}" aria-label="${confirmingDelete ? "确认删除" : "删除"} ${escapeHtml(project.title || "未命名图文")}">
                <i data-lucide="trash-2"></i>
                ${confirmingDelete ? "<span>确认删除</span>" : ""}
              </button>
            </span>`
      }
    `;
    item.querySelector(".history-open").addEventListener("click", () => openProject(project.id));
    item.querySelector(".history-duplicate")?.addEventListener("click", (event) => {
      event.currentTarget.disabled = true;
      void duplicateProject(project.id);
    });
    item.querySelector(".history-delete")?.addEventListener("click", () => requestProjectDeletion(project.id));
    els.projectHistory.append(item);
  }
  if (window.lucide) window.lucide.createIcons();
}

function setHistoryFilter(filter) {
  state.historyFilter = ["all", "cards", "article"].includes(filter) ? filter : "all";
  updateProjectHistory();
}

function setHistoryOpen(open, moveFocus = false) {
  if (!els.historySidebar) return;
  els.historySidebar.classList.toggle("open", open);
  els.workspace?.classList.toggle("history-open", open);
  if (els.historyDrawer) {
    els.historyDrawer.inert = !open;
    els.historyDrawer.setAttribute("aria-hidden", String(!open));
  }
  els.historyToggle?.setAttribute("aria-expanded", String(open));
  els.historyToggle?.setAttribute("aria-label", open ? "收起历史记录" : "打开历史记录");
  els.historyToggle?.setAttribute("title", open ? "收起历史记录" : "打开历史记录");
  if (moveFocus) {
    requestAnimationFrame(() => (open ? els.historyClose : els.historyToggle)?.focus());
  }
}

function toggleHistory() {
  setHistoryOpen(!els.historySidebar?.classList.contains("open"), true);
}

function cacheCurrentProjectPreview() {
  const project = state.projects.find((item) => item.id === state.currentProjectId);
  if (!project || state.appMode !== "cards" || !state.canvases.length) return;
  projectPreviewCache.delete(project.id);
  projectPreviewCache.set(project.id, {
    updatedAt: Number(project.updatedAt || 0),
    mode: state.mode,
    canvases: [...state.canvases],
  });
  while (projectPreviewCache.size > MAX_PROJECT_PREVIEW_CACHE) {
    projectPreviewCache.delete(projectPreviewCache.keys().next().value);
  }
}

function restoreCachedProjectPreview(project) {
  const cached = projectPreviewCache.get(project?.id);
  if (
    !cached
    || project?.data?.appMode === "article"
    || cached.mode !== state.mode
    || Number(cached.updatedAt || 0) !== Number(project?.updatedAt || 0)
  ) {
    return false;
  }
  projectPreviewCache.delete(project.id);
  projectPreviewCache.set(project.id, cached);
  state.canvases = [...cached.canvases];
  drawPreview(state.canvases);
  return true;
}

async function openProject(projectId) {
  if (!projectId || projectId === state.currentProjectId) return;
  saveState();
  cacheCurrentProjectPreview();
  const project = findHistoryProject(projectId);
  if (!project) return;
  state.currentProjectId = project.id;
  rememberActiveProject(project.id);
  state.scrollOffset = 0;
  applyForm(project.data);
  syncGuideReadOnlyMode();
  resetTextHistory();
  updateProjectHistory();
  if (!restoreCachedProjectPreview(project)) {
    // Do not reuse another project's canvases: renderPage mutates canvases in place.
    state.canvases = [];
    await render({ persist: false });
  }
  els.status.textContent = isBuiltInProject(project) ? `已打开内置说明书：${project.title}` : `已打开：${project.title || "未命名图文"}`;
}

async function deleteProjectFromSharedServer(projectId, deletedAt, activeId) {
  const response = await fetch(`${SHARED_PROJECT_STORE_URL}/${encodeURIComponent(projectId)}`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm: true, deletedAt, activeId }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload?.ok !== true || payload?.deletionMeta?.localSaved !== true) {
    throw new Error(payload?.error || `删除保存失败（${response.status}）`);
  }
  return payload;
}

async function retryPendingProjectDeletions(deletions) {
  let changed = false;
  for (const deletion of normalizeProjectDeletions(deletions)) {
    try {
      const payload = await deleteProjectFromSharedServer(
        deletion.id,
        deletion.deletedAt,
        state.currentProjectId,
      );
      state.deletedProjects = mergeProjectDeletions(
        state.deletedProjects,
        [{ id: deletion.id, deletedAt: Number(payload.deletionMeta.deletedAt || deletion.deletedAt) }],
      );
      state.projects = state.projects.filter((project) => project.id !== deletion.id);
      await clearPendingProjectDeletion(deletion.id);
      changed = true;
    } catch (error) {
      console.warn(`项目 ${deletion.id} 的离线删除仍待重试`, error);
    }
  }
  if (!changed) return;
  saveProjectStore();
  updateProjectHistory();
  try {
    await saveProjectStoreToIndexedDb(projectStoreSnapshot());
  } catch (error) {
    console.warn("删除重试结果写入 IndexedDB 失败", error);
  }
}

async function deleteProject(projectId, { confirmed = false } = {}) {
  if (isBuiltInProjectId(projectId)) {
    els.status.textContent = "内置说明书不可删除";
    return;
  }
  const project = state.projects.find((item) => item.id === projectId);
  if (!project) return;
  const projectName = project.title || "未命名图文";
  if (confirmed !== true) {
    els.status.textContent = `删除未执行：请先在历史记录中再次点击“确认删除”`;
    return;
  }
  const deletingCurrent = project.id === state.currentProjectId;
  const deletedAt = Math.max(Date.now(), Number(project.updatedAt || 0) + 1);
  const deletionIntentSaved = await markPendingProjectDeletion({ id: project.id, deletedAt });
  if (!deletionIntentSaved) {
    els.status.textContent = "删除未执行：浏览器无法保存删除记录，请先导出 JSON 备份并释放存储空间";
    return;
  }
  state.deletedProjects = mergeProjectDeletions(
    state.deletedProjects,
    [{ id: project.id, deletedAt }],
  );
  state.projects = state.projects.filter((item) => item.id !== project.id);

  if (!state.projects.length) {
    state.currentProjectId = null;
    state.mode = "auto";
    state.scrollOffset = 0;
    applyForm(blankFormState());
    syncGuideReadOnlyMode();
    resetTextHistory();
  } else if (deletingCurrent) {
    const nextProject = state.projects[0];
    state.currentProjectId = nextProject.id;
    state.mode = "auto";
    state.scrollOffset = 0;
    applyForm(nextProject.data);
    syncGuideReadOnlyMode();
    resetTextHistory();
  }

  rememberActiveProject(state.currentProjectId);
  saveProjectStore();
  updateProjectHistory();
  if (deletingCurrent) await render({ persist: false });
  els.status.textContent = `正在永久删除：${project.title || "未命名图文"}…`;

  try {
    const payload = await deleteProjectFromSharedServer(project.id, deletedAt, state.currentProjectId);
    const confirmedDeletedAt = Number(payload.deletionMeta.deletedAt || deletedAt);
    if (confirmedDeletedAt > deletedAt) {
      state.deletedProjects = mergeProjectDeletions(
        state.deletedProjects,
        [{ id: project.id, deletedAt: confirmedDeletedAt }],
      );
      saveProjectStore();
    }
    await clearPendingProjectDeletion(project.id);
    if (state.localDatabaseHydrated) await flushProjectStoreToIndexedDb();
    els.status.textContent = payload.deletionMeta.cloudDeleted
      ? `已永久删除：${project.title || "未命名图文"}`
      : `已从本机删除：${project.title || "未命名图文"}；云端恢复后会自动重试`;
  } catch (error) {
    console.warn("项目删除尚未得到本机服务确认", error);
    try {
      if (state.localDatabaseHydrated) await saveProjectStoreToIndexedDb(projectStoreSnapshot());
    } catch (databaseError) {
      console.warn("删除墓碑写入 IndexedDB 失败", databaseError);
    }
    els.status.textContent = `已在当前浏览器删除并保留删除记录；本机服务恢复后会重试（${error?.message || "未确认"}）`;
  }
}

async function createNewProject() {
  saveState();
  const project = createProject(blankFormState());
  state.projects = [project, ...state.projects.filter((item) => item.id !== project.id)].slice(0, MAX_PROJECTS);
  state.currentProjectId = project.id;
  rememberActiveProject(project.id);
  state.mode = "auto";
  state.scrollOffset = 0;
  applyForm(project.data);
  syncGuideReadOnlyMode();
  resetTextHistory();
  updateProjectHistory();
  await render();
  els.status.textContent = "已新建图文，上一条已保存在历史记录";
}

async function duplicateProject(projectId) {
  if (isBuiltInProjectId(projectId)) {
    els.status.textContent = "内置说明书不可复制";
    return;
  }
  saveState();
  const source = state.projects.find((project) => project.id === projectId);
  if (!source) {
    els.status.textContent = "未找到要复制的草稿";
    return;
  }

  const copiedData = JSON.parse(JSON.stringify(source.data));
  const duplicate = createProject(copiedData);
  duplicate.title = duplicateProjectTitle(source.title);
  duplicate.updatedAt = Math.max(Date.now(), Number(source.updatedAt || 0) + 1);
  state.projects = [duplicate, ...state.projects].slice(0, MAX_PROJECTS);
  state.currentProjectId = duplicate.id;
  rememberActiveProject(duplicate.id);
  state.mode = "auto";
  state.scrollOffset = 0;
  applyForm(duplicate.data);
  syncGuideReadOnlyMode();
  resetTextHistory();
  setSaveCheckpoint({
    phase: "saving-local",
    projectId: duplicate.id,
    targetUpdatedAt: duplicate.updatedAt,
    error: "",
  });
  saveProjectStore();
  updateProjectHistory();
  await render({ persist: false });

  const persisted = state.localDatabaseHydrated
    ? await flushProjectStoreToIndexedDb()
    : null;
  if (persisted?.sharedSaved) {
    els.status.textContent = persistenceMode === "cloud"
      ? `已复制：${duplicate.title}，正在同步云端`
      : `已复制并保存到本机：${duplicate.title}`;
  } else if (persisted?.localSaved) {
    els.status.textContent = `已复制到本地数据库：${duplicate.title}；服务恢复后将继续同步`;
  } else {
    els.status.textContent = `已复制：${duplicate.title}；请点击保存确认落盘`;
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}

function getTextSnapshot() {
  return {
    value: els.content.value,
    selectionStart: els.content.selectionStart,
    selectionEnd: els.content.selectionEnd,
  };
}

function resetTextHistory() {
  window.clearTimeout(textHistory.timer);
  textHistory.timer = null;
  textHistory.stack = [getTextSnapshot()];
  textHistory.index = 0;
}

function commitTextHistory() {
  if (textHistory.restoring) return;
  window.clearTimeout(textHistory.timer);
  textHistory.timer = null;

  const snapshot = getTextSnapshot();
  const current = textHistory.stack[textHistory.index];
  if (current?.value === snapshot.value) {
    textHistory.stack[textHistory.index] = snapshot;
    return;
  }

  if (textHistory.index < textHistory.stack.length - 1) {
    textHistory.stack = textHistory.stack.slice(0, textHistory.index + 1);
  }

  textHistory.stack.push(snapshot);
  if (textHistory.stack.length > textHistory.max) {
    textHistory.stack.shift();
  } else {
    textHistory.index += 1;
  }
}

function scheduleTextHistoryCommit() {
  if (textHistory.restoring) return;
  window.clearTimeout(textHistory.timer);
  textHistory.timer = window.setTimeout(commitTextHistory, 260);
}

function restoreTextSnapshot(snapshot) {
  textHistory.restoring = true;
  els.content.value = snapshot.value;
  els.content.focus();
  els.content.setSelectionRange(snapshot.selectionStart, snapshot.selectionEnd);
  textHistory.restoring = false;
  lastEditorImageReferenceSignature = imageReferenceSignature(snapshot.value);
  syncAiUndoAvailability();
  requestRender();
}

function undoTextChange() {
  commitTextHistory();
  if (textHistory.index <= 0) return;
  textHistory.index -= 1;
  restoreTextSnapshot(textHistory.stack[textHistory.index]);
}

function redoTextChange() {
  commitTextHistory();
  if (textHistory.index >= textHistory.stack.length - 1) return;
  textHistory.index += 1;
  restoreTextSnapshot(textHistory.stack[textHistory.index]);
}

function normalizeAiRevision(value) {
  if (!value || typeof value !== "object") return null;
  if (typeof value.before !== "string" || typeof value.after !== "string" || !value.after) return null;
  return {
    before: value.before,
    after: value.after,
    appliedAt: typeof value.appliedAt === "string" ? value.appliedAt : new Date().toISOString(),
    projectId: typeof value.projectId === "string" ? value.projectId : null,
    mode: value.mode === "polish" ? "polish" : "layout",
  };
}

function syncAiUndoAvailability() {
  if (!els.aiUndo) return;
  const revision = normalizeAiRevision(state.lastAiRevision);
  const canUndo = Boolean(
    revision
      && revision.projectId === state.currentProjectId
      && els.content
      && els.content.value === revision.after,
  );
  els.aiUndo.hidden = !canUndo;
  els.aiUndo.disabled = !canUndo;
  els.aiUndo.setAttribute("aria-hidden", String(!canUndo));
}

function setAiOptimizeStatus(message, status = "loading") {
  if (!els.aiOptimizeStatus) return;
  els.aiOptimizeStatus.textContent = message;
  els.aiOptimizeStatus.dataset.state = status;
}

function setAiOptimizeRequestBusy(busy) {
  [els.aiModeLayout, els.aiModePolish].forEach((button) => {
    if (button) button.disabled = Boolean(busy);
  });
  if (els.aiOptimizeGenerate) els.aiOptimizeGenerate.disabled = Boolean(busy);
  els.aiOptimizeModal?.setAttribute("aria-busy", String(Boolean(busy)));
}

function selectedAiOptimizeMode() {
  if (els.aiModeLayout?.getAttribute("aria-checked") === "true") return "layout";
  if (els.aiModePolish?.getAttribute("aria-checked") === "true") return "polish";
  return null;
}

function setAiOptimizeMode(mode) {
  const nextMode = ["layout", "polish"].includes(mode) ? mode : null;
  [els.aiModeLayout, els.aiModePolish].forEach((button) => {
    if (!button) return;
    const active = button.dataset.aiMode === nextMode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-checked", String(active));
    button.tabIndex = nextMode ? (active ? 0 : -1) : (button === els.aiModeLayout ? 0 : -1);
  });
  return nextMode;
}

function setAiOptimizeUiState(nextState) {
  aiOptimizeUiState = nextState;
  if (els.aiOptimizeModal) els.aiOptimizeModal.dataset.aiState = nextState;
  const selectedMode = selectedAiOptimizeMode();
  const requesting = nextState === "requesting";
  const success = nextState === "success";
  const error = nextState === "error";
  setAiOptimizeRequestBusy(requesting);
  if (els.aiOptimizeGenerate) {
    els.aiOptimizeGenerate.hidden = false;
    els.aiOptimizeGenerate.disabled = requesting || !selectedMode;
    const label = els.aiOptimizeGenerate.querySelector("span");
    if (label) {
      label.textContent = requesting
        ? "正在生成建议…"
        : success
          ? "重新生成建议"
          : error
            ? "重试生成建议"
            : "开始生成建议";
    }
  }
  if (els.aiOptimizeApply) {
    els.aiOptimizeApply.hidden = !success;
    els.aiOptimizeApply.disabled = !success;
  }
}

function chooseAiOptimizeMode(mode, { focus = false } = {}) {
  if (aiOptimizeUiState === "requesting") return;
  const nextMode = setAiOptimizeMode(mode);
  if (!nextMode) return;
  aiOptimizeRequestGeneration += 1;
  aiOptimizeAbortController?.abort();
  aiOptimizeAbortController = null;
  pendingAiOptimization = null;
  els.aiBeforePreview.textContent = els.content.value;
  els.aiAfterPreview.textContent = "点击“开始生成建议”后，完整结果会显示在这里。";
  renderAiChangeList([
    nextMode === "polish"
      ? "会对少量句子做局部润色，并重新标注视觉重点；确认应用前正文不会改变。"
      : "正文逐字保持不变：主结论加粗，数字、结果和转折使用克制的浅黄底色。",
  ]);
  setAiOptimizeStatus(
    nextMode === "polish"
      ? "已选择「润色并排版」；点击开始后才会保存当前版本并连接 AI。"
      : "已选择「只优化排版」；点击开始后才会保存当前版本并连接 AI。",
    "ready",
  );
  setAiOptimizeUiState("ready");
  if (focus) {
    const target = nextMode === "polish" ? els.aiModePolish : els.aiModeLayout;
    target?.focus();
  }
}

function handleAiModeKeydown(event) {
  if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const nextMode = ["ArrowRight", "ArrowDown", "End"].includes(event.key) ? "polish" : "layout";
  chooseAiOptimizeMode(nextMode, { focus: true });
}

function renderAiChangeList(changes = []) {
  if (!els.aiChangeList) return;
  const items = changes.length ? changes : ["AI 未提供额外说明，请直接对比前后正文。"];
  els.aiChangeList.replaceChildren(
    ...items.map((change) => {
      const item = document.createElement("li");
      item.textContent = change;
      return item;
    }),
  );
}

function layoutOnlyCopySignature(value) {
  let text = String(value || "");
  let previous = null;
  while (previous !== text) {
    previous = text;
    text = text
      .replace(/\{\{(?:color|bg):#[0-9a-fA-F]{3,8}\|([\s\S]*?)\}\}/g, "$1")
      .replace(/\*\*([^*\n]+?)\*\*/g, "$1");
  }
  return text;
}

function layoutOnlyPreservesCopy(before, after) {
  return layoutOnlyCopySignature(before) === layoutOnlyCopySignature(after);
}

async function runAiOptimization(mode) {
  if (!els.aiOptimizeModal || els.aiOptimizeModal.classList.contains("hidden")) return;
  const requestedMode = ["layout", "polish"].includes(mode) ? mode : selectedAiOptimizeMode();
  if (!requestedMode || aiOptimizeUiState === "requesting") {
    setAiOptimizeStatus("请先选择一种优化方式，再点击“开始生成建议”。", "error");
    return;
  }
  const generation = ++aiOptimizeRequestGeneration;
  aiOptimizeAbortController?.abort();
  const abortController = new AbortController();
  aiOptimizeAbortController = abortController;
  const nextMode = setAiOptimizeMode(requestedMode);
  pendingAiOptimization = null;
  setAiOptimizeUiState("requesting");
  els.aiAfterPreview.textContent = "正在安全生成建议，原文不会被改动…";
  renderAiChangeList(["正在识别层级、重点和适合高亮的内容…"]);
  setAiOptimizeStatus("正在保存当前版本并连接 AI…", "loading");

  try {
    saveState();
    const persisted = state.localDatabaseHydrated ? await flushProjectStoreToIndexedDb() : null;
    if (generation !== aiOptimizeRequestGeneration || els.aiOptimizeModal.classList.contains("hidden")) return;
    if (!persisted?.sharedSaved) {
      throw new Error(
        persisted?.conflict
          ? "检测到团队成员保存的新版本；旧缓存没有覆盖云端，请重新打开该稿后再试"
          : "当前版本尚未写入共享草稿库，请稍后重试",
      );
    }
    const project = state.projects.find((item) => item.id === state.currentProjectId);
    const before = els.content.value;
    const baseUpdatedAt = Number(project?.updatedAt || 0);

    const statusResponse = await fetch(AI_OPTIMIZE_STATUS_URL, {
      cache: "no-store",
      signal: abortController.signal,
    });
    const aiStatus = await statusResponse.json().catch(() => ({}));
    if (generation !== aiOptimizeRequestGeneration || els.aiOptimizeModal.classList.contains("hidden")) return;
    if (!statusResponse.ok || aiStatus.enabled !== true) {
      throw new Error(aiStatus.reason || "AI 排版服务尚未配置");
    }

    setAiOptimizeStatus(nextMode === "polish" ? "AI 正在润色并重排，原文仍保持不变…" : "AI 正在识别重点并优化排版，原文仍保持不变…", "loading");
    const response = await fetch(AI_OPTIMIZE_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        content: before,
        mode: nextMode,
        accentColor: els.accentColor.value,
        projectId: state.currentProjectId,
        baseUpdatedAt,
      }),
      signal: abortController.signal,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `AI 优化失败（${response.status}）`);
    if (generation !== aiOptimizeRequestGeneration) return;

    const currentProject = state.projects.find((item) => item.id === state.currentProjectId);
    if (els.content.value !== before || Number(currentProject?.updatedAt || 0) !== baseUpdatedAt) {
      throw new Error("AI 生成期间正文已有新修改，结果未覆盖当前内容");
    }
    if (typeof payload.optimizedContent !== "string" || !payload.optimizedContent.trim()) {
      throw new Error("AI 没有返回可用内容");
    }
    if (nextMode === "layout" && !layoutOnlyPreservesCopy(before, payload.optimizedContent)) {
      throw new Error("AI 排版结果改动了正文，已阻止进入预览");
    }

    pendingAiOptimization = {
      before,
      after: payload.optimizedContent,
      changes: Array.isArray(payload.changes) ? payload.changes : [],
      mode: nextMode,
      projectId: state.currentProjectId,
      baseUpdatedAt,
      requestId: payload.requestId || null,
    };
    els.aiBeforePreview.textContent = before;
    els.aiAfterPreview.textContent = payload.optimizedContent;
    renderAiChangeList(pendingAiOptimization.changes);
    setAiOptimizeUiState("success");
    setAiOptimizeStatus(`建议已生成 · ${payload.model || "Kimi"} · 确认后才会替换正文`, "success");
  } catch (error) {
    if (error?.name === "AbortError") return;
    if (generation !== aiOptimizeRequestGeneration) return;
    pendingAiOptimization = null;
    els.aiAfterPreview.textContent = "本次没有改动正文。解决提示中的问题后，可以重新选择优化方式重试。";
    renderAiChangeList([error?.message || "AI 优化暂时不可用"]);
    setAiOptimizeUiState("error");
    setAiOptimizeStatus(error?.message || "AI 优化暂时不可用", "error");
  } finally {
    if (aiOptimizeAbortController === abortController) aiOptimizeAbortController = null;
    if (generation === aiOptimizeRequestGeneration && aiOptimizeUiState === "requesting") {
      setAiOptimizeUiState("error");
    }
  }
}

function closeAiOptimizeModal() {
  aiOptimizeRequestGeneration += 1;
  aiOptimizeAbortController?.abort();
  aiOptimizeAbortController = null;
  pendingAiOptimization = null;
  setAiOptimizeMode(null);
  setAiOptimizeUiState("closed");
  els.aiOptimizeModal?.classList.add("hidden");
  els.workspace?.removeAttribute("inert");
  aiOptimizeReturnFocus?.focus?.();
  aiOptimizeReturnFocus = null;
}

function trapAiOptimizeModalFocus(event) {
  if (event.key !== "Tab" || els.aiOptimizeModal?.classList.contains("hidden")) return;
  trapModalFocus(event, els.aiOptimizeModal);
}

function trapModalFocus(event, modal) {
  if (!modal) return;
  const focusable = [...modal.querySelectorAll(
    'button:not([disabled]):not([hidden]), [href], input:not([disabled]):not([hidden]), select:not([disabled]):not([hidden]), textarea:not([disabled]):not([hidden]), [tabindex]:not([tabindex="-1"]):not([hidden])',
  )].filter((element) => element.getClientRects().length > 0);
  if (!focusable.length) {
    event.preventDefault();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && (document.activeElement === first || !modal.contains(document.activeElement))) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (document.activeElement === last || !modal.contains(document.activeElement))) {
    event.preventDefault();
    first.focus();
  }
}

function openAiOptimizeModal() {
  if (isBuiltInProjectId(state.currentProjectId)) {
    els.status.textContent = "内置说明书不可修改，请先新建图文";
    return;
  }
  if (!els.content.value.trim()) {
    els.status.textContent = "正文为空，暂时无法使用 AI 优化";
    return;
  }
  aiOptimizeReturnFocus = document.activeElement;
  pendingAiOptimization = null;
  els.aiBeforePreview.textContent = els.content.value;
  els.aiAfterPreview.textContent = "先在上方选择一种方式，再点击“开始生成建议”。";
  renderAiChangeList(["尚未连接 AI，也没有改动正文。"]);
  setAiOptimizeMode(null);
  setAiOptimizeStatus("请选择一种优化方式。只有点击“开始生成建议”后才会连接 AI，正文不会被改动。", "ready");
  setAiOptimizeUiState("choosing");
  els.workspace?.setAttribute("inert", "");
  els.aiOptimizeModal.classList.remove("hidden");
  els.aiModeLayout?.focus();
}

async function applyAiOptimization() {
  const revision = pendingAiOptimization;
  if (!revision || els.aiOptimizeApply.disabled) return;
  const project = state.projects.find((item) => item.id === state.currentProjectId);
  if (
    state.currentProjectId !== revision.projectId
    || els.content.value !== revision.before
    || Number(project?.updatedAt || 0) !== revision.baseUpdatedAt
  ) {
    setAiOptimizeStatus("正文已有新修改，请重新生成；当前内容没有被覆盖", "error");
    els.aiOptimizeApply.disabled = true;
    return;
  }
  state.lastAiRevision = {
    before: revision.before,
    after: revision.after,
    appliedAt: new Date().toISOString(),
    projectId: revision.projectId,
    mode: revision.mode,
  };
  els.aiOptimizeApply.disabled = true;
  await applyProgrammaticContent(revision.after, revision.mode === "polish" ? "AI 润色与排版已应用" : "AI 排版已应用");
  closeAiOptimizeModal();
  syncAiUndoAvailability();
}

async function undoLastAiOptimization() {
  const revision = normalizeAiRevision(state.lastAiRevision);
  if (!revision || revision.projectId !== state.currentProjectId || els.content.value !== revision.after) {
    syncAiUndoAvailability();
    els.status.textContent = "正文已在 AI 优化后继续修改；为避免覆盖新内容，请使用 Command/Ctrl + Z";
    return;
  }
  state.lastAiRevision = null;
  await applyProgrammaticContent(revision.before, "已撤回本次 AI 优化");
  syncAiUndoAvailability();
}

function collectIllustrationBlocks(content) {
  const source = String(content || "");
  const lines = source.split("\n");
  const blocks = [];
  let offset = 0;
  let blockStart = null;
  let blockEnd = null;
  let inFence = false;

  const flush = () => {
    if (blockStart === null || blockEnd === null || blockEnd <= blockStart) {
      blockStart = null;
      blockEnd = null;
      return;
    }
    const exactText = source.slice(blockStart, blockEnd);
    const visibleText = exactText
      .replace(/\[\[image:[^\]]+\]\]/g, "")
      .replace(/\{\{(?:color|bg):#[0-9a-fA-F]{3,8}\|([\s\S]*?)\}\}/g, "$1")
      .replace(/[*_`>#-]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    if (
      visibleText.length >= 6
      && exactText.length <= 2400
      && !exactText.split("\n").every((line) => line.includes("|"))
    ) {
      const index = blocks.length;
      blocks.push({
        blockId: `block-${index}`,
        text: visibleText.slice(0, 520),
        exactText,
        start: blockStart,
        end: blockEnd,
      });
    }
    blockStart = null;
    blockEnd = null;
  };

  lines.forEach((line, index) => {
    const lineStart = offset;
    const lineEnd = lineStart + line.length;
    offset = lineEnd + (index < lines.length - 1 ? 1 : 0);
    const trimmed = line.trim();

    if (/^(?:```|~~~)/.test(trimmed)) {
      flush();
      inFence = !inFence;
      return;
    }
    if (inFence || !trimmed) {
      flush();
      return;
    }
    if (/^\[\[image:[^\]]+\]\]$/.test(trimmed) || isMarkdownTableDivider(trimmed)) {
      flush();
      return;
    }
    if (blockStart === null) blockStart = lineStart;
    blockEnd = lineEnd;
  });
  flush();
  return blocks.slice(0, 24);
}

function setIllustrationStatus(message, status = "ready") {
  if (!els.illustrationStatus) return;
  els.illustrationStatus.textContent = message;
  els.illustrationStatus.dataset.state = status;
}

function setIllustrationUiState(nextState) {
  illustrationUiState = nextState;
  if (els.illustrationModal) els.illustrationModal.dataset.illustrationState = nextState;
  const busy = ["saving", "searching", "importing"].includes(nextState);
  if (els.illustrationSearch) {
    els.illustrationSearch.disabled = busy;
    const label = els.illustrationSearch.querySelector("span");
    if (label) {
      label.textContent = nextState === "saving"
        ? "正在保存…"
        : nextState === "searching"
          ? "正在找图…"
          : nextState === "importing"
            ? "正在下载入库…"
            : pendingIllustrationSearch
              ? "重新找图"
              : "开始找图";
    }
  }
  if (els.illustrationApply) {
    const hasSelection = Boolean(
      pendingIllustrationSearch
      && els.illustrationResults?.querySelector('input[data-candidate-id]:checked'),
    );
    els.illustrationApply.hidden = !pendingIllustrationSearch;
    els.illustrationApply.disabled = busy || !hasSelection;
  }
  if (els.illustrationClose) els.illustrationClose.disabled = nextState === "importing";
  if (els.illustrationCancel) els.illustrationCancel.disabled = nextState === "importing";
  if (els.illustrationCount) els.illustrationCount.disabled = busy;
  if (els.illustrationProvider) els.illustrationProvider.disabled = busy;
  els.illustrationModal?.setAttribute("aria-busy", String(busy));
}

function illustrationErrorMessage(payload, fallback) {
  if (typeof payload?.error === "string" && payload.error.trim()) return payload.error.trim();
  if (typeof payload?.error?.message === "string" && payload.error.message.trim()) return payload.error.message.trim();
  return fallback;
}

function normalizeCandidateCreator(candidate) {
  if (typeof candidate?.creator === "string") return candidate.creator;
  if (typeof candidate?.creator?.name === "string") return candidate.creator.name;
  return "来源作者未注明";
}

function normalizeCandidateLicense(candidate) {
  if (typeof candidate?.license === "string") return candidate.license;
  if (typeof candidate?.license?.name === "string") return candidate.license.name;
  return "许可信息待核对";
}

function renderIllustrationResults(payload, blocks) {
  const planItems = Array.isArray(payload?.plan?.items) ? payload.plan.items : [];
  const candidates = Array.isArray(payload?.candidates) ? payload.candidates : [];
  const blocksById = new Map(blocks.map((block) => [block.blockId, block]));
  const groups = planItems
    .map((item) => ({
      item,
      block: blocksById.get(item.blockId),
      candidates: candidates.filter((candidate) => candidate.blockId === item.blockId),
    }))
    .filter((group) => group.block && group.candidates.length);

  if (!groups.length) {
    pendingIllustrationSearch = null;
    els.illustrationResults?.replaceChildren();
    els.illustrationEmpty?.classList.remove("hidden");
    setIllustrationStatus("没有找到足够可靠的候选图；可换一个图源或减少配图数量后重试。", "error");
    setIllustrationUiState("error");
    return false;
  }

  pendingIllustrationSearch = {
    projectId: state.currentProjectId,
    baseUpdatedAt: Number(findHistoryProject(state.currentProjectId)?.updatedAt || 0),
    beforeContent: els.content.value,
    blocksById,
    planItems,
    candidates,
    expiresAt: payload.expiresAt || null,
  };

  const fragment = document.createDocumentFragment();
  groups.forEach((group, groupIndex) => {
    const section = document.createElement("section");
    section.className = "illustration-slot";
    const head = document.createElement("div");
    head.className = "illustration-slot-head";
    const slotCopy = document.createElement("div");
    const heading = document.createElement("h4");
    heading.textContent = `建议位置 ${groupIndex + 1}`;
    const reason = document.createElement("p");
    reason.textContent = group.item.reason || "在这段之后加入图片，帮助读者理解当前内容。";
    slotCopy.append(heading, reason);
    const query = document.createElement("span");
    query.className = "illustration-query";
    query.textContent = `搜索词：${group.item.query || "相关图片"}`;
    head.append(slotCopy, query);

    const context = document.createElement("blockquote");
    context.textContent = group.block.text;
    const grid = document.createElement("div");
    grid.className = "illustration-candidate-grid";

    group.candidates.forEach((candidate, candidateIndex) => {
      const label = document.createElement("label");
      label.className = "illustration-candidate";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = `illustration-slot-${groupIndex}`;
      input.value = candidate.id;
      input.dataset.candidateId = candidate.id;
      input.dataset.blockId = group.item.blockId;
      input.checked = candidateIndex === 0;
      const image = document.createElement("img");
      image.src = candidate.previewUrl || candidate.thumbnailUrl || "";
      image.alt = candidate.title || "网络配图候选";
      image.loading = "lazy";
      const copy = document.createElement("span");
      copy.className = "illustration-candidate-copy";
      const title = document.createElement("strong");
      title.textContent = candidate.title || "网络图片";
      const meta = document.createElement("small");
      meta.textContent = `${normalizeCandidateCreator(candidate)} · ${normalizeCandidateLicense(candidate)}`;
      const source = document.createElement("a");
      source.href = candidate.sourcePageUrl || "#";
      source.target = "_blank";
      source.rel = "noreferrer noopener";
      source.textContent = `${candidate.provider || "图库"} 来源页`;
      source.addEventListener("click", (event) => event.stopPropagation());
      copy.append(title, meta, source);
      label.append(input, image, copy);
      grid.append(label);
    });

    const skip = document.createElement("label");
    skip.className = "illustration-skip";
    const skipInput = document.createElement("input");
    skipInput.type = "radio";
    skipInput.name = `illustration-slot-${groupIndex}`;
    skipInput.value = "";
    const skipText = document.createElement("span");
    skipText.textContent = "跳过这个位置";
    skip.append(skipInput, skipText);
    section.append(head, context, grid, skip);
    fragment.append(section);
  });

  els.illustrationResults?.replaceChildren(fragment);
  els.illustrationEmpty?.classList.add("hidden");
  els.illustrationResults?.querySelectorAll('input[type="radio"]').forEach((input) => {
    input.addEventListener("change", () => setIllustrationUiState("ready"));
  });
  if (window.lucide) window.lucide.createIcons();
  setIllustrationStatus(
    `已找到 ${groups.length} 个插图位置。请选择候选图；确认前正文和资源库都不会改变。`,
    "success",
  );
  setIllustrationUiState("ready");
  return true;
}

function updateIllustrationProviderOptions(status) {
  const providers = Array.isArray(status?.providers) ? status.providers : [];
  const enabledById = new Map(providers.map((provider) => [provider.id, provider.enabled !== false]));
  [...(els.illustrationProvider?.options || [])].forEach((option) => {
    if (option.value === "auto") return;
    if (enabledById.has(option.value)) option.disabled = !enabledById.get(option.value);
  });
  if (els.illustrationProvider?.selectedOptions[0]?.disabled) {
    els.illustrationProvider.value = "auto";
  }
}

async function runIllustrationSearch() {
  if (illustrationUiState === "saving" || illustrationUiState === "searching" || illustrationUiState === "importing") return;
  const blocks = collectIllustrationBlocks(els.content.value);
  if (!blocks.length) {
    setIllustrationStatus("没有找到适合插图的正文段落；表格、代码和已有图片不会作为插入点。", "error");
    return;
  }
  const generation = ++illustrationRequestGeneration;
  illustrationAbortController?.abort();
  const abortController = new AbortController();
  illustrationAbortController = abortController;
  pendingIllustrationSearch = null;
  els.illustrationResults?.replaceChildren();
  els.illustrationEmpty?.classList.remove("hidden");
  setIllustrationUiState("saving");
  setIllustrationStatus("正在保存当前版本；保存完成后才会分析搜索词。", "loading");

  try {
    saveState();
    const persisted = state.localDatabaseHydrated ? await flushProjectStoreToIndexedDb() : null;
    if (generation !== illustrationRequestGeneration) return;
    if (!persisted?.sharedSaved) {
      throw new Error(
        persisted?.conflict
          ? "检测到团队成员保存的新版本；旧缓存没有覆盖云端，请重新打开该稿后再试"
          : "当前版本尚未写入共享草稿库，请稍后重试",
      );
    }

    const project = findHistoryProject(state.currentProjectId);
    const before = els.content.value;
    const baseUpdatedAt = Number(project?.updatedAt || 0);
    setIllustrationUiState("searching");
    setIllustrationStatus("正在分析段落并从可靠网络图库查找候选图片…", "loading");

    const statusResponse = await fetch(ILLUSTRATION_STATUS_URL, {
      cache: "no-store",
      signal: abortController.signal,
    });
    const status = await statusResponse.json().catch(() => ({}));
    if (!statusResponse.ok || status.enabled === false) {
      throw new Error(illustrationErrorMessage(status, status.message || "在线图源暂时不可用"));
    }
    updateIllustrationProviderOptions(status);

    const response = await fetch(ILLUSTRATION_SEARCH_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        projectId: state.currentProjectId,
        baseUpdatedAt,
        content: before,
        blocks: blocks.map(({ blockId, text }) => ({ blockId, text })),
        maxImages: clamp(Number(els.illustrationCount?.value) || 2, 1, 3),
        maxCandidates: 4,
        provider: els.illustrationProvider?.value || "auto",
      }),
      signal: abortController.signal,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(illustrationErrorMessage(payload, `配图搜索失败（${response.status}）`));
    }
    if (generation !== illustrationRequestGeneration) return;
    const currentProject = findHistoryProject(state.currentProjectId);
    if (
      els.content.value !== before
      || state.currentProjectId !== project?.id
      || Number(currentProject?.updatedAt || 0) !== baseUpdatedAt
    ) {
      throw new Error("找图期间正文已有新修改，候选图未应用");
    }
    renderIllustrationResults(payload, blocks);
  } catch (error) {
    if (error?.name === "AbortError") return;
    if (generation !== illustrationRequestGeneration) return;
    pendingIllustrationSearch = null;
    setIllustrationStatus(error?.message || "在线配图暂时不可用", "error");
    setIllustrationUiState("error");
  } finally {
    if (illustrationAbortController === abortController) illustrationAbortController = null;
  }
}

function selectedIllustrationCandidates() {
  if (!pendingIllustrationSearch || !els.illustrationResults) return [];
  return [...els.illustrationResults.querySelectorAll('input[data-candidate-id]:checked')]
    .map((input) => {
      const candidate = pendingIllustrationSearch.candidates.find((item) => item.id === input.dataset.candidateId);
      const block = pendingIllustrationSearch.blocksById.get(input.dataset.blockId);
      return candidate && block ? { candidate, block } : null;
    })
    .filter(Boolean);
}

function insertIllustrationMarkers(originalContent, placements) {
  const grouped = new Map();
  placements.forEach(({ block, imageId }) => {
    if (!grouped.has(block.end)) grouped.set(block.end, []);
    grouped.get(block.end).push(imageId);
  });
  const patches = [...grouped.entries()]
    .sort(([left], [right]) => left - right)
    .map(([offset, imageIds]) => ({
      offset,
      value: `\n\n${imageIds.map((imageId) => `[[image:${imageId}]]`).join("\n\n")}`,
    }));

  let sourceCursor = 0;
  let nextContent = "";
  const insertedRanges = [];
  patches.forEach((patch) => {
    if (!Number.isInteger(patch.offset) || patch.offset < sourceCursor || patch.offset > originalContent.length) {
      throw new Error("配图插入位置无效，正文未修改");
    }
    nextContent += originalContent.slice(sourceCursor, patch.offset);
    const start = nextContent.length;
    nextContent += patch.value;
    insertedRanges.push({ start, end: nextContent.length, value: patch.value });
    sourceCursor = patch.offset;
  });
  nextContent += originalContent.slice(sourceCursor);

  let restored = nextContent;
  [...insertedRanges].reverse().forEach((range) => {
    if (restored.slice(range.start, range.end) !== range.value) {
      throw new Error("配图插入校验失败，正文未修改");
    }
    restored = `${restored.slice(0, range.start)}${restored.slice(range.end)}`;
  });
  if (restored !== originalContent) {
    throw new Error("配图插入校验失败，正文未修改");
  }
  return nextContent;
}

async function commitIllustrationRevision({ pending, nextContent, nextImages, message }) {
  const baseProject = findHistoryProject(pending.projectId);
  if (
    !baseProject
    || state.currentProjectId !== pending.projectId
    || els.content.value !== pending.beforeContent
    || Number(baseProject.updatedAt || 0) !== pending.baseUpdatedAt
  ) {
    throw new Error("正文或项目版本已经变化，请重新找图");
  }

  const nextData = {
    ...readForm(),
    content: nextContent,
    images: nextImages,
  };
  const nextProject = {
    ...baseProject,
    title: normalizeProjectTitle(els.projectTitle?.value)
      || baseProject.title
      || projectTitleFromData(nextData),
    updatedAt: nextProjectTimestamp(baseProject),
    data: nextData,
  };
  const snapshot = {
    activeId: pending.projectId,
    projects: [
      nextProject,
      ...state.projects.filter(
        (project) => project.id !== pending.projectId && !isBuiltInProject(project),
      ),
    ].slice(0, MAX_PROJECTS),
    deletedProjects: normalizeProjectDeletions(state.deletedProjects),
  };
  const committed = await saveProjectStoreToSharedServer(snapshot, {
    expectedProjectId: pending.projectId,
    expectedUpdatedAt: pending.baseUpdatedAt,
  });
  if (!committed.saved) {
    throw new Error("本机发现了更新版本，本次配图没有覆盖它；请刷新后重新找图");
  }

  const responseProjects = Array.isArray(committed.responseStore?.projects)
    ? committed.responseStore.projects.map(normalizeProject).filter(Boolean)
    : snapshot.projects;
  const committedProject = responseProjects.find((project) => project.id === pending.projectId)
    || nextProject;

  commitTextHistory();
  state.projects = responseProjects;
  state.deletedProjects = normalizeProjectDeletions(
    committed.responseStore?.deletedProjects || snapshot.deletedProjects,
  );
  state.currentProjectId = pending.projectId;
  state.images = committedProject.data.images;
  els.content.value = committedProject.data.content;
  lastEditorImageReferenceSignature = imageReferenceSignature(els.content.value);
  commitTextHistory();
  syncAiUndoAvailability();
  updateImageList();
  updateProjectHistory();
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(committedProject.data));
  } catch (error) {
    console.warn("当前草稿兼容副本写入失败，继续使用本地数据库", error);
  }
  saveProjectStore();
  try {
    await saveProjectStoreToIndexedDb(projectStoreSnapshot());
  } catch (error) {
    console.warn("配图版本的浏览器数据库副本写入失败", error);
  }
  const savedAt = new Date().toISOString();
  setSaveCheckpoint({
    phase: persistenceMode === "cloud" ? "syncing-cloud" : "degraded",
    projectId: pending.projectId,
    targetUpdatedAt: Number(committedProject.updatedAt || nextProject.updatedAt),
    localSavedAt: savedAt,
    serverSavedAt: savedAt,
    destination: persistenceMode === "cloud" ? "Supabase + 私有 TOS" : "本机项目文件",
    error: "",
  });
  try {
    await render({ persist: false });
  } catch (error) {
    console.error("配图版本已保存，但当前预览刷新失败", error);
  }
  if (persistenceMode === "cloud") {
    void confirmCloudCheckpoint(
      pending.projectId,
      Number(committedProject.updatedAt || nextProject.updatedAt),
    );
  }
  els.status.textContent = `${message}，当前完整版本已保存`;
  return true;
}

async function applyIllustrationSelection() {
  const pending = pendingIllustrationSearch;
  const selected = selectedIllustrationCandidates();
  if (!pending || !selected.length || illustrationUiState === "importing") return;
  const project = findHistoryProject(state.currentProjectId);
  if (
    state.currentProjectId !== pending.projectId
    || els.content.value !== pending.beforeContent
    || Number(project?.updatedAt || 0) !== pending.baseUpdatedAt
  ) {
    setIllustrationStatus("正文或项目版本已经变化，请重新找图；当前内容没有被覆盖。", "error");
    setIllustrationUiState("error");
    return;
  }

  const generation = ++illustrationRequestGeneration;
  illustrationAbortController?.abort();
  const abortController = new AbortController();
  illustrationAbortController = abortController;
  setIllustrationUiState("importing");
  setIllustrationStatus(`正在安全下载并清洗 ${selected.length} 张图片；全部成功后才会插入。`, "loading");

  try {
    const imported = [];
    for (const { candidate, block } of selected) {
      const response = await fetch(ILLUSTRATION_IMPORT_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          projectId: pending.projectId,
          baseUpdatedAt: pending.baseUpdatedAt,
          content: pending.beforeContent,
          candidateId: candidate.id,
        }),
        signal: abortController.signal,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(illustrationErrorMessage(payload, `图片下载失败（${response.status}）`));
      }
      const asset = payload.asset;
      if (!asset || typeof asset.dataUrl !== "string" || !/^data:image\/(?:jpeg|png|webp);base64,/i.test(asset.dataUrl)) {
        throw new Error("图库返回了不受支持的图片格式");
      }
      imported.push({ asset, candidate, block });
      if (generation !== illustrationRequestGeneration) return;
    }
    const importedBytes = imported.reduce(
      (total, item) => total + Math.max(0, Number(item.asset.byteSize) || 0),
      0,
    );
    if (importedBytes > ILLUSTRATION_MAX_TOTAL_BYTES) {
      throw new Error("本次选中的图片总量过大，请减少配图数量或更换候选");
    }
    if (generation !== illustrationRequestGeneration) return;
    const currentProject = findHistoryProject(state.currentProjectId);
    if (
      state.currentProjectId !== pending.projectId
      || els.content.value !== pending.beforeContent
      || Number(currentProject?.updatedAt || 0) !== pending.baseUpdatedAt
    ) {
      throw new Error("下载期间正文已有新修改，图片没有插入");
    }

    const addedImages = {};
    const placements = imported.map(({ asset, candidate, block }, index) => {
      const imageId = createImportedImageId(index);
      addedImages[imageId] = {
        src: asset.dataUrl,
        name: asset.fileName || candidate.title || `网络配图-${index + 1}`,
        sourcePath: asset.source?.sourcePageUrl || candidate.sourcePageUrl || "网络图库",
        source: normalizeWebAssetSource(asset.source) || {
          kind: "web",
          provider: candidate.provider,
          sourcePageUrl: candidate.sourcePageUrl,
          creator: normalizeCandidateCreator(candidate),
          license: normalizeCandidateLicense(candidate),
        },
        crop: null,
        layout: defaultNewImageLayout(),
      };
      return { block, imageId };
    });
    const nextContent = insertIllustrationMarkers(pending.beforeContent, placements);
    await commitIllustrationRevision({
      pending,
      nextContent,
      nextImages: { ...state.images, ...addedImages },
      message: `已插入 ${placements.length} 张网络配图，原有文字逐字保留`,
    });
    closeIllustrationModal({ force: true });
  } catch (error) {
    if (error?.name === "AbortError") return;
    if (generation !== illustrationRequestGeneration) return;
    setIllustrationStatus(error?.message || "图片入库失败；正文和资源库均未改变", "error");
    setIllustrationUiState("error");
  } finally {
    if (illustrationAbortController === abortController) illustrationAbortController = null;
  }
}

function openIllustrationModal() {
  if (isBuiltInProjectId(state.currentProjectId)) {
    els.status.textContent = "内置说明书不可修改，请先新建图文";
    return;
  }
  if (!els.content.value.trim()) {
    els.status.textContent = "正文为空，暂时无法自动配图";
    return;
  }
  illustrationReturnFocus = document.activeElement;
  pendingIllustrationSearch = null;
  els.illustrationResults?.replaceChildren();
  els.illustrationEmpty?.classList.remove("hidden");
  setIllustrationStatus("设置配图数量后点击“开始找图”；打开窗口不会联网，也不会修改正文。", "ready");
  setIllustrationUiState("ready");
  els.workspace?.setAttribute("inert", "");
  els.illustrationModal?.classList.remove("hidden");
  els.illustrationSearch?.focus();
}

function closeIllustrationModal({ force = false } = {}) {
  if (illustrationUiState === "importing" && !force) {
    setIllustrationStatus("正在下载并条件保存完整版本，完成前暂不能关闭。", "loading");
    return;
  }
  illustrationRequestGeneration += 1;
  illustrationAbortController?.abort();
  illustrationAbortController = null;
  pendingIllustrationSearch = null;
  illustrationUiState = "closed";
  els.illustrationModal?.classList.add("hidden");
  els.workspace?.removeAttribute("inert");
  illustrationReturnFocus?.focus?.();
  illustrationReturnFocus = null;
}

function trapIllustrationModalFocus(event) {
  if (event.key !== "Tab" || els.illustrationModal?.classList.contains("hidden")) return;
  trapModalFocus(event, els.illustrationModal);
}

function handleTextShortcut(event) {
  const key = event.key.toLowerCase();
  const isModifierShortcut = (event.metaKey || event.ctrlKey) && !event.altKey;
  if (!isModifierShortcut) return;

  if (key === "b" && !event.shiftKey) {
    event.preventDefault();
    wrapSelection("bold");
    return;
  }

  if (key === "i" && !event.shiftKey) {
    event.preventDefault();
    wrapSelection("italic");
    return;
  }

  const isUndoKey = key === "z";
  if (!isUndoKey) return;
  event.preventDefault();
  if (event.shiftKey) {
    redoTextChange();
  } else {
    undoTextChange();
  }
}

function insertAtSelection(textarea, value, selectOffset = null) {
  commitTextHistory();
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const current = textarea.value;
  textarea.value = `${current.slice(0, start)}${value}${current.slice(end)}`;
  const cursor = selectOffset === null ? start + value.length : start + selectOffset;
  textarea.focus();
  textarea.setSelectionRange(cursor, cursor);
  commitTextHistory();
  requestRender();
}

function wrapSelection(kind) {
  commitTextHistory();
  const textarea = els.content;
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const current = textarea.value;
  const selected = current.slice(start, end) || "文字";
  let next = selected;
  let cursorOffset = null;

  if (kind === "bold" || kind === "italic") {
    const marker = kind === "bold" ? "**" : "*";
    const markerLength = marker.length;
    const italicMarkersAreStandalone =
      kind !== "italic" ||
      (!selected.startsWith("**") &&
        !selected.endsWith("**") &&
        current.slice(start - 2, start - 1) !== "*" &&
        current.slice(end + 1, end + 2) !== "*");
    const selectedHasMarkers =
      italicMarkersAreStandalone &&
      selected.length >= markerLength * 2 &&
      selected.startsWith(marker) &&
      selected.endsWith(marker);
    const selectionIsWrapped =
      italicMarkersAreStandalone &&
      start >= markerLength &&
      current.slice(start - markerLength, start) === marker &&
      current.slice(end, end + markerLength) === marker;

    if (selectedHasMarkers) {
      const unwrapped = selected.slice(markerLength, -markerLength);
      textarea.value = `${current.slice(0, start)}${unwrapped}${current.slice(end)}`;
      textarea.focus();
      textarea.setSelectionRange(start, start + unwrapped.length);
    } else if (selectionIsWrapped) {
      const unwrappedStart = start - markerLength;
      textarea.value = `${current.slice(0, unwrappedStart)}${selected}${current.slice(end + markerLength)}`;
      textarea.focus();
      textarea.setSelectionRange(unwrappedStart, unwrappedStart + selected.length);
    } else {
      next = `${marker}${selected}${marker}`;
      textarea.value = `${current.slice(0, start)}${next}${current.slice(end)}`;
      textarea.focus();
      textarea.setSelectionRange(start + markerLength, start + markerLength + selected.length);
    }
    commitTextHistory();
    requestRender();
    return;
  } else if (kind === "h1" || kind === "h2" || kind === "quote") {
    const prefix = kind === "h1" ? "# " : kind === "h2" ? "## " : "> ";
    const lineStart = current.lastIndexOf("\n", Math.max(0, start - 1)) + 1;
    textarea.value = `${current.slice(0, lineStart)}${prefix}${current.slice(lineStart)}`;
    textarea.focus();
    textarea.setSelectionRange(start + prefix.length, end + prefix.length);
    commitTextHistory();
    requestRender();
    return;
  }

  textarea.value = `${current.slice(0, start)}${next}${current.slice(end)}`;
  if (cursorOffset !== null) {
    textarea.setSelectionRange(start + cursorOffset, start + cursorOffset + selected.length);
  } else {
    textarea.setSelectionRange(start + next.length, start + next.length);
  }
  textarea.focus();
  commitTextHistory();
  requestRender();
}

function wrapSelectionWithColor() {
  commitTextHistory();
  const textarea = els.content;
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const selected = textarea.value.slice(start, end) || "彩色文字";
  const color = els.inlineColor.value;
  const next = `{{color:${color}|${selected}}}`;
  textarea.value = `${textarea.value.slice(0, start)}${next}${textarea.value.slice(end)}`;
  textarea.focus();
  textarea.setSelectionRange(start + next.length, start + next.length);
  commitTextHistory();
  requestRender();
}

function wrapSelectionWithBackground() {
  commitTextHistory();
  const textarea = els.content;
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const selected = textarea.value.slice(start, end) || "底色文字";
  const color = els.inlineBgColor.value;
  const next = `{{bg:${color}|${selected}}}`;
  textarea.value = `${textarea.value.slice(0, start)}${next}${textarea.value.slice(end)}`;
  textarea.focus();
  textarea.setSelectionRange(start + next.length, start + next.length);
  commitTextHistory();
  requestRender();
}

function enableColorBrush() {
  state.colorBrush = true;
  state.bgColorBrush = false;
  document.documentElement.style.setProperty("--brush-color", els.inlineColor.value);
  els.colorTool?.classList.add("active");
  els.bgColorTool?.classList.remove("active");
  els.colorTool?.setAttribute("aria-pressed", "true");
  els.bgColorTool?.setAttribute("aria-pressed", "false");
  els.colorMenu.open = false;
  els.bgColorMenu.open = false;
  els.status.textContent = "刷色已开启，选中一段文字即可上色";
}

function disableColorBrush(announce = false) {
  state.colorBrush = false;
  els.colorTool?.classList.remove("active");
  els.colorTool?.setAttribute("aria-pressed", "false");
  els.colorMenu.open = false;
  if (announce) els.status.textContent = "文字上色已退出";
}

function enableBackgroundBrush() {
  state.bgColorBrush = true;
  state.colorBrush = false;
  document.documentElement.style.setProperty("--text-bg-brush-color", els.inlineBgColor.value);
  els.bgColorTool?.classList.add("active");
  els.colorTool?.classList.remove("active");
  els.bgColorTool?.setAttribute("aria-pressed", "true");
  els.colorTool?.setAttribute("aria-pressed", "false");
  els.bgColorMenu.open = false;
  els.colorMenu.open = false;
  els.status.textContent = "背景上色已开启，选中一段文字即可加底色";
}

function disableBackgroundBrush(announce = false) {
  state.bgColorBrush = false;
  els.bgColorTool?.classList.remove("active");
  els.bgColorTool?.setAttribute("aria-pressed", "false");
  els.bgColorMenu.open = false;
  if (announce) els.status.textContent = "背景上色已退出";
}

function toggleActiveBrushFromTool(event, kind) {
  const isActive = kind === "color" ? state.colorBrush : state.bgColorBrush;
  if (isActive) {
    event.preventDefault();
    if (kind === "color") {
      disableColorBrush(true);
    } else {
      disableBackgroundBrush(true);
    }
    return;
  }

  if (kind === "color") disableBackgroundBrush();
  else disableColorBrush();
}

function disableActiveBrushes() {
  disableColorBrush();
  disableBackgroundBrush();
}

function applyColorBrushToSelection() {
  if (!state.colorBrush) return;
  if (document.activeElement !== els.content) return;
  if (els.content.selectionStart === els.content.selectionEnd) return;
  wrapSelectionWithColor();
  disableColorBrush();
  els.status.textContent = "已应用选中文字颜色";
}

function applyBackgroundBrushToSelection() {
  if (!state.bgColorBrush) return;
  if (document.activeElement !== els.content) return;
  if (els.content.selectionStart === els.content.selectionEnd) return;
  wrapSelectionWithBackground();
  disableBackgroundBrush();
  els.status.textContent = "已应用背景色，工具已自动退出";
}

function applyActiveBrushToSelection() {
  window.setTimeout(() => {
    applyColorBrushToSelection();
    applyBackgroundBrushToSelection();
  }, 0);
}

function findNext() {
  const needle = els.find.value;
  if (!needle) return;
  const haystack = els.content.value;
  const from = Math.max(els.content.selectionEnd, state.lastFindIndex + needle.length, 0);
  let index = haystack.indexOf(needle, from);
  if (index === -1) index = haystack.indexOf(needle, 0);
  if (index === -1) {
    els.status.textContent = "没有找到匹配文本";
    return;
  }
  state.lastFindIndex = index;
  els.content.focus();
  els.content.setSelectionRange(index, index + needle.length);
  els.status.textContent = `已选中第 ${index + 1} 个字符处`;
}

function replaceCurrent() {
  const needle = els.find.value;
  if (!needle) return;
  let start = els.content.selectionStart;
  let end = els.content.selectionEnd;
  let selected = els.content.value.slice(start, end);
  if (selected !== needle) {
    findNext();
    start = els.content.selectionStart;
    end = els.content.selectionEnd;
    selected = els.content.value.slice(start, end);
    if (selected !== needle) return;
  }
  insertAtSelection(els.content, els.replace.value);
  state.lastFindIndex = start;
}

function replaceAll() {
  const needle = els.find.value;
  if (!needle) return;
  const replacement = els.replace.value;
  const pieces = els.content.value.split(needle);
  const count = pieces.length - 1;
  if (count < 1) {
    els.status.textContent = "没有找到匹配文本";
    return;
  }
  commitTextHistory();
  els.content.value = pieces.join(replacement);
  els.content.focus();
  els.content.setSelectionRange(0, 0);
  commitTextHistory();
  els.status.textContent = `已替换 ${count} 处`;
  requestRender();
}

async function readFileAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function loadImage(src) {
  if (decodedImageCache.has(src)) {
    const cached = decodedImageCache.get(src);
    decodedImageCache.delete(src);
    decodedImageCache.set(src, cached);
    return cached;
  }

  const pending = new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });
  decodedImageCache.set(src, pending);
  while (decodedImageCache.size > MAX_DECODED_IMAGE_CACHE) {
    decodedImageCache.delete(decodedImageCache.keys().next().value);
  }
  pending.catch(() => {
    if (decodedImageCache.get(src) === pending) decodedImageCache.delete(src);
  });
  return pending;
}

function isImageFile(file) {
  return file?.type?.startsWith("image/") || /\.(avif|bmp|gif|heic|jpe?g|png|svg|webp)$/i.test(file?.name || "");
}

function createImportedImageId(index = 0) {
  const random = window.crypto?.randomUUID?.().slice(0, 8) || Math.random().toString(36).slice(2, 10);
  return `img_${Date.now().toString(36)}_${index.toString(36)}_${random}`;
}

function sourcePathForFile(file) {
  return file.webkitRelativePath || file.name || "图片";
}

async function addImageFiles(files, sourcePaths = null) {
  const imageFiles = Array.from(files || []).filter(isImageFile);
  const tags = [];
  const ids = [];

  for (const [index, file] of imageFiles.entries()) {
    const src = await readFileAsDataURL(file);
    const id = createImportedImageId(index);
    const image = {
      src,
      name: file.name || "图片",
      sourcePath: sourcePaths?.get(file) || sourcePathForFile(file),
      crop: null,
      layout: defaultNewImageLayout(),
    };
    const browserLocalMode = assetLibraryMode === "local"
      || (assetLibraryMode === "unknown" && localAssetDirectoryHandle);
    if (browserLocalMode && localAssetDirectoryHandle) {
      try {
        image.localAssetName = await writeDataUrlToLocalAssetDirectory(src, image.name);
      } catch (error) {
        console.warn("图片已保留在草稿，但未能写入本地资源文件夹", error);
        els.status.textContent = "图片已保留在草稿，但本地资源文件夹写入失败";
      }
    }
    state.images[id] = image;
    ids.push(id);
    tags.push(`[[image:${id}]]`);
  }

  return { ids, tags, skipped: Array.from(files || []).length - imageFiles.length };
}

function insertImageTagsAtCursor(tags) {
  if (!tags.length) return;
  insertAtSelection(els.content, `\n${tags.join("\n\n")}\n`);
  updateImageList();
}

async function handleContentImage(event) {
  const result = await addImageFiles(event.target.files);
  event.target.value = "";
  if (!result.tags.length) return;
  insertImageTagsAtCursor(result.tags);
  els.status.textContent = `已插入 ${result.tags.length} 张图片`;
}

function canUseLocalAssetDirectoryPicker() {
  return Boolean(window.showDirectoryPicker && window.isSecureContext);
}

async function loadLocalAssetDirectoryConnection() {
  if (!canUseLocalAssetDirectoryPicker()) return;
  try {
    const handle = await readLocalAssetDirectoryHandle();
    if (handle?.kind === "directory") localAssetDirectoryHandle = handle;
  } catch (error) {
    console.info("没有可恢复的本地资源文件夹授权", error);
  }
}

async function ensureLocalAssetDirectoryPermission({ request = false } = {}) {
  const handle = localAssetDirectoryHandle;
  if (!handle) return false;
  const options = { mode: "readwrite" };
  try {
    if (await handle.queryPermission(options) === "granted") return true;
    return request && await handle.requestPermission(options) === "granted";
  } catch (error) {
    console.warn("本地资源文件夹授权检查失败", error);
    return false;
  }
}

function cleanupLocalAssetPreviewUrls() {
  for (const url of localAssetPreviewUrls) URL.revokeObjectURL(url);
  localAssetPreviewUrls = [];
}

function localAssetOriginalName(filename) {
  const marker = String(filename || "").indexOf("__");
  return marker >= 0 ? filename.slice(marker + 2) : filename;
}

function isManagedLocalAssetFilename(filename) {
  return /^[0-9a-f]{24}__.+\.(avif|bmp|gif|heic|jpe?g|png|svg|webp)$/i.test(String(filename || ""));
}

function sanitizeLocalAssetFilename(name, mimeType = "") {
  const extensionByMime = {
    "image/avif": ".avif",
    "image/bmp": ".bmp",
    "image/gif": ".gif",
    "image/heic": ".heic",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/svg+xml": ".svg",
    "image/webp": ".webp",
  };
  let filename = String(name || "图片")
    .split(/[\\/]/)
    .pop()
    .replace(/[\u0000-\u001f<>:"|?*]/g, "-")
    .replace(/^\.+/, "")
    .replace(/\s+/g, " ")
    .trim();
  if (!filename) filename = "图片";
  if (!/\.(avif|bmp|gif|heic|jpe?g|png|svg|webp)$/i.test(filename)) {
    filename += extensionByMime[mimeType] || ".png";
  }
  return filename.slice(-96);
}

async function sha256Hex(blob) {
  if (!window.crypto?.subtle) throw new Error("当前浏览器不支持图片去重");
  const bytes = await blob.arrayBuffer();
  const digest = await window.crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
}

async function findLocalAssetByHashPrefix(directory, prefix) {
  for await (const [name, entry] of directory.entries()) {
    if (entry.kind === "file" && name.startsWith(prefix) && isImageFile({ name })) return name;
  }
  return "";
}

async function writeDataUrlToLocalAssetDirectory(dataUrl, originalName) {
  if (!localAssetDirectoryHandle || !(await ensureLocalAssetDirectoryPermission())) {
    throw new Error("本地资源文件夹尚未授权");
  }
  const response = await fetch(dataUrl);
  const blob = await response.blob();
  if (!blob.type.startsWith("image/")) throw new Error("资源不是受支持的图片");
  const hash = await sha256Hex(blob);
  const prefix = `${hash.slice(0, 24)}__`;
  const existingName = await findLocalAssetByHashPrefix(localAssetDirectoryHandle, prefix);
  if (existingName) return existingName;

  const filename = `${prefix}${sanitizeLocalAssetFilename(originalName, blob.type)}`;
  const fileHandle = await localAssetDirectoryHandle.getFileHandle(filename, { create: true });
  const writable = await fileHandle.createWritable();
  try {
    await writable.write(blob);
  } finally {
    await writable.close();
  }
  return filename;
}

function localAssetReferenceCount(filename) {
  const referencedProjects = new Set();
  for (const project of state.projects) {
    if (!project || isBuiltInProject(project)) continue;
    const data = project.id === state.currentProjectId ? readForm() : project.data || {};
    const images = data.images && typeof data.images === "object" ? data.images : {};
    for (const imageId of String(data.content || "").matchAll(/\[\[image:([^\]]+)\]\]/g)) {
      if (images[imageId[1]]?.localAssetName === filename) {
        referencedProjects.add(project.id);
        break;
      }
    }
  }
  return referencedProjects.size;
}

function normalizeWebAssetSource(value) {
  if (!value || typeof value !== "object" || value.kind !== "web") return null;
  const source = { kind: "web" };
  for (const field of [
    "provider",
    "title",
    "sourcePageUrl",
    "creator",
    "license",
    "licenseUrl",
    "query",
    "fetchedAt",
  ]) {
    if (typeof value[field] === "string" && value[field].trim()) {
      source[field] = value[field].trim();
    }
  }
  return source;
}

function safeExternalSourceUrl(value) {
  try {
    const url = new URL(String(value || ""));
    if (
      url.protocol !== "https:"
      || url.username
      || url.password
      || (url.port && url.port !== "443")
    ) return "";
    return url.href;
  } catch {
    return "";
  }
}

function localAssetSource(filename) {
  for (const project of state.projects) {
    const images = project?.data?.images;
    if (!images || typeof images !== "object") continue;
    for (const image of Object.values(images)) {
      if (image?.localAssetName !== filename) continue;
      const source = normalizeWebAssetSource(image.source);
      if (source) return source;
    }
  }
  return null;
}

async function syncProjectImagesToLocalAssetDirectory() {
  if (!(await ensureLocalAssetDirectoryPermission())) return { stored: 0, failed: 0 };
  if (!isBuiltInProjectId(state.currentProjectId)) saveState();
  let stored = 0;
  let failed = 0;
  for (const project of state.projects) {
    const images = project?.data?.images;
    if (!images || typeof images !== "object") continue;
    for (const image of Object.values(images)) {
      if (!image || typeof image.src !== "string" || !image.src.startsWith("data:image/")) continue;
      if (image.localAssetDeletedAt) continue;
      try {
        image.localAssetName = await writeDataUrlToLocalAssetDirectory(image.src, image.name || image.sourcePath || "图片");
        stored += 1;
      } catch (error) {
        failed += 1;
        console.warn("本地资源图片写入失败", error);
      }
    }
  }
  saveProjectStore();
  if (state.localDatabaseHydrated) await flushProjectStoreToIndexedDb();
  return { stored, failed };
}

async function listLocalAssetDirectory() {
  if (!localAssetDirectoryHandle || !(await ensureLocalAssetDirectoryPermission())) return [];
  cleanupLocalAssetPreviewUrls();
  const assets = [];
  for await (const [name, entry] of localAssetDirectoryHandle.entries()) {
    // Never expose or delete ordinary photos if a user selects a broad folder.
    if (entry.kind !== "file" || !isManagedLocalAssetFilename(name)) continue;
    try {
      const file = await entry.getFile();
      const previewUrl = URL.createObjectURL(file);
      localAssetPreviewUrls.push(previewUrl);
      const source = localAssetSource(name);
      assets.push({
        assetId: `local:${name}`,
        originalName: localAssetOriginalName(name),
        byteSize: file.size,
        createdAt: file.lastModified,
        lastUsedAt: file.lastModified,
        referenceCount: localAssetReferenceCount(name),
        previewUrl,
        localFileName: name,
        storageMode: "local",
        ...(source ? { source } : {}),
      });
    } catch (error) {
      console.warn(`无法读取本地资源 ${name}`, error);
    }
  }
  return assets.sort((left, right) => Number(right.lastUsedAt || 0) - Number(left.lastUsedAt || 0));
}

function formatAssetByteSize(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) return "大小未知";
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  const units = ["KB", "MB", "GB"];
  let size = bytes / 1024;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size >= 10 ? size.toFixed(0) : size.toFixed(1)} ${units[unitIndex]}`;
}

function formatAssetDate(value) {
  const date = new Date(value);
  if (!value || Number.isNaN(date.getTime())) return "时间未知";
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function setAssetLibraryStatus(message, kind = "") {
  if (!els.assetLibraryStatus) return;
  els.assetLibraryStatus.textContent = message;
  els.assetLibraryStatus.dataset.kind = kind;
}

async function readAssetApiPayload(response) {
  try {
    return await response.json();
  } catch {
    return {};
  }
}

function assetApiError(payload, fallback) {
  return String(payload?.error || payload?.message || fallback);
}

function setAssetLibraryStorageMode(mode, folderName = "") {
  assetLibraryMode = mode;
  const local = String(mode).startsWith("local");
  if (els.assetLibraryFolder) {
    els.assetLibraryFolder.hidden = !local;
    els.assetLibraryFolder.innerHTML = localAssetDirectoryHandle || folderName
      ? '<i data-lucide="folder-cog"></i> 更换本地文件夹'
      : '<i data-lucide="folder-open"></i> 选择本地文件夹';
  }
  if (els.assetLibraryDescription) {
    els.assetLibraryDescription.textContent = local
      ? folderName
        ? `TOS 不可用，图片保存在你授权的“${folderName}”文件夹。`
        : "TOS 不可用，请选择一个只保存在本机的图片资源文件夹。"
      : "拖入或粘贴的图片会保存到私有 TOS；只有在这里确认删除，才会从云端移除。";
  }
  if (window.lucide) window.lucide.createIcons();
}

function renderLocalAssetDirectoryPrompt(reason = "") {
  if (!els.assetLibraryGrid) return;
  cleanupLocalAssetPreviewUrls();
  setAssetLibraryStorageMode("local", localAssetDirectoryHandle?.name || "");
  els.assetLibraryGrid.innerHTML = "";
  const empty = document.createElement("div");
  empty.className = "asset-library-empty";
  if (canUseLocalAssetDirectoryPicker()) {
    empty.innerHTML = '<i data-lucide="folder-open"></i><strong>选择本地资源文件夹</strong><span>文件夹路径和授权只保存在这个浏览器，不会上传到 GitHub 或服务器。</span>';
    setAssetLibraryStatus("无法连接 TOS，已降级为本地存储 · 请选择资源文件夹", "warning");
  } else {
    empty.innerHTML = '<i data-lucide="monitor-up"></i><strong>当前浏览器不能选择可写文件夹</strong><span>请通过 npm start 打开 127.0.0.1，并使用最新版 Chrome 或 Edge。</span>';
    setAssetLibraryStatus("无法连接 TOS，已降级为本地存储，但当前浏览器不支持文件夹授权", "error");
  }
  if (reason) empty.title = reason;
  els.assetLibraryGrid.append(empty);
  if (window.lucide) window.lucide.createIcons();
}

function renderServerLocalDirectoryPrompt(reason = "") {
  if (!els.assetLibraryGrid) return;
  cleanupLocalAssetPreviewUrls();
  setAssetLibraryStorageMode("local-server", "");
  els.assetLibraryGrid.innerHTML = "";
  const empty = document.createElement("div");
  empty.className = "asset-library-empty";
  empty.innerHTML = '<i data-lucide="folder-open"></i><strong>选择本地资源存储文件夹</strong><span>文件夹位置只会保存在这台电脑，不会上传到 GitHub、Supabase 或 TOS。</span>';
  if (reason) empty.title = reason;
  els.assetLibraryGrid.append(empty);
  setAssetLibraryStatus("无法连接 TOS，已降级为本地存储 · 请选择资源存储文件夹", "warning");
  if (window.lucide) window.lucide.createIcons();
}

function renderAssetLibrary(payload) {
  if (!els.assetLibraryGrid) return;
  const assets = Array.isArray(payload?.assets) ? payload.assets : [];
  const local = String(payload?.storageMode || "").startsWith("local");
  els.assetLibraryGrid.innerHTML = "";

  const connection = local
    ? `无法连接 TOS，已降级为本地存储 · ${payload.folderName || "本地文件夹"}`
    : "TOS 云端存储已连接";
  setAssetLibraryStatus(`${connection} · 共 ${assets.length} 张图片`, local ? "warning" : "success");

  if (!assets.length) {
    const empty = document.createElement("div");
    empty.className = "asset-library-empty";
    empty.innerHTML = `<i data-lucide="image-off"></i><strong>资源库还是空的</strong><span>${local ? "拖入、粘贴或上传图片后，会自动写入这个文件夹。" : "拖入或粘贴图片后，它们会出现在这里。"}</span>`;
    els.assetLibraryGrid.append(empty);
    if (window.lucide) window.lucide.createIcons();
    return;
  }

  for (const asset of assets) {
    const assetId = String(asset?.assetId || "");
    if (!assetId) continue;
    const name = String(asset.originalName || "未命名图片");
    const referenceCount = Math.max(0, Number(asset.referenceCount) || 0);
    const item = document.createElement("article");
    item.className = "asset-library-item";

    const preview = document.createElement("div");
    preview.className = "asset-library-preview";
    const fallback = document.createElement("div");
    fallback.className = "asset-library-preview-fallback";
    fallback.innerHTML = '<i data-lucide="image"></i>';
    preview.append(fallback);
    if (asset.previewUrl) {
      const image = document.createElement("img");
      image.src = asset.previewUrl;
      image.alt = name;
      image.loading = "lazy";
      image.addEventListener("load", () => fallback.classList.add("hidden"));
      image.addEventListener("error", () => image.remove());
      preview.append(image);
    }

    const meta = document.createElement("div");
    meta.className = "asset-library-meta";
    const title = document.createElement("strong");
    title.textContent = name;
    title.title = name;
    const details = document.createElement("span");
    details.textContent = `${formatAssetByteSize(asset.byteSize)} · ${referenceCount} 处引用`;
    const time = document.createElement("span");
    time.textContent = `最近使用 ${formatAssetDate(asset.lastUsedAt || asset.createdAt)}`;
    meta.append(title, details, time);
    const source = normalizeWebAssetSource(asset.source);
    if (source) {
      const provenance = document.createElement("span");
      provenance.className = "asset-library-provenance";
      provenance.textContent = [
        source.creator || source.provider || "网络图库",
        source.license || "许可见来源页",
      ].join(" · ");
      meta.append(provenance);
      const sourceUrl = safeExternalSourceUrl(source.sourcePageUrl);
      if (sourceUrl) {
        const sourceLink = document.createElement("a");
        sourceLink.className = "asset-library-source-link";
        sourceLink.href = sourceUrl;
        sourceLink.target = "_blank";
        sourceLink.rel = "noreferrer noopener";
        sourceLink.textContent = "查看原图与许可";
        meta.append(sourceLink);
      }
    }

    const actions = document.createElement("div");
    actions.className = "asset-library-actions";
    const insertButton = document.createElement("button");
    insertButton.type = "button";
    insertButton.className = "secondary-button";
    insertButton.disabled = isBuiltInProjectId(state.currentProjectId);
    insertButton.title = insertButton.disabled ? "说明书不可编辑，请先新建图文" : `插入 ${name}`;
    insertButton.innerHTML = '<i data-lucide="plus"></i>插入';
    insertButton.addEventListener("click", () => insertAssetFromLibrary(asset, insertButton));

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "asset-delete-button";
    const deleteLocation = String(asset.storageMode || "").startsWith("local") ? "本地资源文件夹" : "云端";
    deleteButton.title = `从${deleteLocation}永久删除 ${name}`;
    deleteButton.setAttribute("aria-label", `从${deleteLocation}永久删除 ${name}`);
    deleteButton.innerHTML = '<i data-lucide="trash-2"></i>';
    deleteButton.addEventListener("click", () => deleteAssetFromLibrary(asset, deleteButton));
    actions.append(insertButton, deleteButton);

    item.append(preview, meta, actions);
    els.assetLibraryGrid.append(item);
  }

  if (window.lucide) window.lucide.createIcons();
}

async function loadLocalAssetLibrary(reason = "") {
  setAssetLibraryStorageMode("local", localAssetDirectoryHandle?.name || "");
  if (!localAssetDirectoryHandle) await loadLocalAssetDirectoryConnection();
  if (!canUseLocalAssetDirectoryPicker() || !localAssetDirectoryHandle || !(await ensureLocalAssetDirectoryPermission())) {
    renderLocalAssetDirectoryPrompt(reason);
    return;
  }
  try {
    setAssetLibraryStatus(`正在同步“${localAssetDirectoryHandle.name}”中的本地资源…`, "loading");
    await syncProjectImagesToLocalAssetDirectory();
    const assets = await listLocalAssetDirectory();
    setAssetLibraryStorageMode("local", localAssetDirectoryHandle.name);
    renderAssetLibrary({
      assets,
      cloudEnabled: false,
      storageMode: "local",
      folderName: localAssetDirectoryHandle.name,
    });
  } catch (error) {
    console.error(error);
    renderLocalAssetDirectoryPrompt(error.message || reason || "本地资源文件夹无法读取");
    setAssetLibraryStatus("无法连接 TOS，本地资源文件夹也无法读取 · 请重新选择文件夹", "error");
  }
}

async function selectLocalAssetDirectory() {
  if (assetLibraryMode === "local-server") {
    setAssetLibraryStatus("正在打开本机文件夹选择器…", "loading");
    try {
      const response = await fetch("/api/local-assets/select-directory", { method: "POST" });
      const payload = await readAssetApiPayload(response);
      if (response.status === 409 && payload?.cancelled) {
        setAssetLibraryStatus("已取消选择，本地草稿仍安全保留。", "warning");
        return;
      }
      if (!response.ok) throw new Error(assetApiError(payload, `文件夹选择失败（${response.status}）`));
      await loadAssetLibrary();
      setAssetLibraryStatus(`无法连接 TOS，已降级为本地存储 · 已切换到“${payload.folderName || "所选文件夹"}”`, "success");
      return;
    } catch (error) {
      console.error(error);
      setAssetLibraryStatus(error.message || "本地资源文件夹连接失败", "error");
      return;
    }
  }
  if (!canUseLocalAssetDirectoryPicker()) {
    renderLocalAssetDirectoryPrompt("showDirectoryPicker unavailable");
    return;
  }
  try {
    const handle = await window.showDirectoryPicker({
      id: "write-then-publish-assets",
      mode: "readwrite",
      startIn: "pictures",
    });
    localAssetDirectoryHandle = handle;
    setAssetLibraryStorageMode("local", handle.name);
    await saveLocalAssetDirectoryHandle(handle);
    setAssetLibraryStatus(`正在把现有草稿图片写入“${handle.name}”…`, "loading");
    const result = await syncProjectImagesToLocalAssetDirectory();
    await loadLocalAssetLibrary();
    const suffix = result.failed ? `，${result.failed} 张写入失败` : "";
    setAssetLibraryStatus(`无法连接 TOS，已降级为本地存储 · 已保存 ${result.stored} 张草稿图片到“${handle.name}”${suffix}`, result.failed ? "warning" : "success");
  } catch (error) {
    if (error?.name === "AbortError") {
      setAssetLibraryStatus("已取消选择，本地草稿仍安全保留。", "warning");
      return;
    }
    console.error(error);
    setAssetLibraryStatus(error.message || "本地资源文件夹连接失败", "error");
  }
}

async function loadAssetLibrary() {
  if (!els.assetLibraryGrid) return;
  setAssetLibraryStatus("正在读取资源库…", "loading");
  els.assetLibraryGrid.setAttribute("aria-busy", "true");
  if (els.assetLibraryRefresh) els.assetLibraryRefresh.disabled = true;
  try {
    const response = await fetch(ASSET_LIBRARY_URL, { cache: "no-store" });
    const payload = await readAssetApiPayload(response);
    if (!response.ok) {
      await loadLocalAssetLibrary(assetApiError(payload, `资源库读取失败（${response.status}）`));
      return;
    }
    if (payload?.storageMode === "local-server") {
      cleanupLocalAssetPreviewUrls();
      if (payload.directorySelectionRequired) {
        renderServerLocalDirectoryPrompt(payload?.status?.lastError || "TOS 未配置");
        return;
      }
      setAssetLibraryStorageMode("local-server", payload.folderName || "本地资源文件夹");
      renderAssetLibrary(payload);
      return;
    }
    if (!payload?.cloudEnabled) {
      await loadLocalAssetLibrary(payload?.status?.lastError || "TOS 未配置");
      return;
    }
    cleanupLocalAssetPreviewUrls();
    setAssetLibraryStorageMode("cloud");
    renderAssetLibrary(payload);
  } catch (error) {
    console.error(error);
    await loadLocalAssetLibrary(error.message || "TOS 连接失败");
  } finally {
    els.assetLibraryGrid.removeAttribute("aria-busy");
    if (els.assetLibraryRefresh) els.assetLibraryRefresh.disabled = false;
  }
}

function openAssetLibrary() {
  if (!els.assetLibraryModal) return;
  assetLibraryReturnFocus = document.activeElement;
  els.assetLibraryModal.classList.remove("hidden");
  els.workspace?.setAttribute("inert", "");
  window.requestAnimationFrame(() => {
    if (!els.assetLibraryModal?.classList.contains("hidden")) els.assetLibraryClose?.focus();
  });
  void loadAssetLibrary();
}

function closeAssetLibrary() {
  els.assetLibraryModal?.classList.add("hidden");
  els.workspace?.removeAttribute("inert");
  cleanupLocalAssetPreviewUrls();
  if (assetLibraryReturnFocus instanceof HTMLElement) assetLibraryReturnFocus.focus();
  assetLibraryReturnFocus = null;
}

async function insertAssetFromLibrary(asset, button) {
  if (isBuiltInProjectId(state.currentProjectId)) {
    setAssetLibraryStatus("说明书不可编辑，请先新建图文后再插入。", "warning");
    return;
  }
  const assetId = String(asset?.assetId || "");
  if (!assetId) return;
  button.disabled = true;
  setAssetLibraryStatus(`正在读取 ${asset.originalName || "图片"}…`, "loading");
  try {
    let dataUrl = "";
    let detail = asset;
    if (asset.storageMode === "local") {
      if (!(await ensureLocalAssetDirectoryPermission({ request: true }))) {
        throw new Error("需要重新授权本地资源文件夹");
      }
      const filename = String(asset.localFileName || assetId.replace(/^local:/, ""));
      const fileHandle = await localAssetDirectoryHandle.getFileHandle(filename);
      dataUrl = await readFileAsDataURL(await fileHandle.getFile());
    } else {
      const response = await fetch(`${ASSET_LIBRARY_URL}/${encodeURIComponent(assetId)}`, { cache: "no-store" });
      const payload = await readAssetApiPayload(response);
      if (!response.ok) throw new Error(assetApiError(payload, `图片读取失败（${response.status}）`));
      dataUrl = payload.dataUrl;
      detail = payload.asset && typeof payload.asset === "object" ? payload.asset : asset;
    }
    if (typeof dataUrl !== "string" || !dataUrl.startsWith("data:image/")) throw new Error("资源库返回的图片数据无效");
    const localStorageMode = String(asset.storageMode || detail.storageMode || "").startsWith("local");
    const localAssetName = String(
      asset.localFileName || detail.localFileName || detail.localAssetName || assetId.replace(/^local:/, ""),
    );
    const localId = createImportedImageId();
    const source = normalizeWebAssetSource(detail.source || asset.source);
    state.images[localId] = {
      src: dataUrl,
      name: String(detail.originalName || asset.originalName || "资源库图片"),
      sourcePath: localStorageMode ? `local-folder://${localAssetName}` : `cloud://${assetId}`,
      ...(localStorageMode
        ? { localAssetId: assetId, localAssetName }
        : { cloudAssetId: assetId, ...(detail.cloudObjectKey ? { cloudObjectKey: detail.cloudObjectKey } : {}) }),
      ...(source ? { source } : {}),
      crop: null,
      layout: defaultNewImageLayout(),
    };
    insertImageTagsAtCursor([`[[image:${localId}]]`]);
    closeAssetLibrary();
    const saved = await persistCurrentDraftImmediately();
    els.status.textContent = saved ? "已从资源库插入图片并保存" : "已从资源库插入图片，正在自动保存";
  } catch (error) {
    console.error(error);
    setAssetLibraryStatus(error.message || "图片插入失败", "error");
    button.disabled = false;
  }
}

async function requestAssetDeletion(assetId, force) {
  const response = await fetch(`${ASSET_LIBRARY_URL}/${encodeURIComponent(assetId)}`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm: true, force }),
  });
  return { response, payload: await readAssetApiPayload(response) };
}

async function markLocalAssetDeleted(filename) {
  if (!isBuiltInProjectId(state.currentProjectId)) saveState();
  const deletedAt = new Date().toISOString();
  for (const project of state.projects) {
    const images = project?.data?.images;
    if (!images || typeof images !== "object") continue;
    for (const image of Object.values(images)) {
      if (image?.localAssetName === filename) image.localAssetDeletedAt = deletedAt;
    }
  }
  for (const image of Object.values(state.images || {})) {
    if (image?.localAssetName === filename) image.localAssetDeletedAt = deletedAt;
  }
  saveProjectStore();
  if (state.localDatabaseHydrated) await flushProjectStoreToIndexedDb();
}

async function deleteLocalAssetFromLibrary(asset, button) {
  const filename = String(asset.localFileName || asset.assetId?.replace(/^local:/, ""));
  if (!isManagedLocalAssetFilename(filename)) {
    setAssetLibraryStatus("该文件不是写了就发管理的资源，已拒绝删除。", "error");
    return;
  }
  const name = String(asset.originalName || filename);
  const confirmed = window.confirm(`确认从本地资源文件夹永久删除“${name}”？\n\n正文引用和草稿内嵌副本不会被删除。`);
  if (!confirmed) return;
  const referenceCount = Math.max(0, Number(asset.referenceCount) || 0);
  if (referenceCount) {
    const forceConfirmed = window.confirm(`这张图片仍被 ${referenceCount} 篇草稿引用。\n\n仍要从本地资源文件夹永久删除吗？草稿中的内嵌图片仍会保留。`);
    if (!forceConfirmed) {
      setAssetLibraryStatus("已取消删除，图片仍保留在本地资源文件夹。", "warning");
      return;
    }
  }
  button.disabled = true;
  setAssetLibraryStatus(`正在从本地文件夹删除 ${name}…`, "loading");
  try {
    if (!(await ensureLocalAssetDirectoryPermission({ request: true }))) throw new Error("需要重新授权本地资源文件夹");
    await localAssetDirectoryHandle.removeEntry(filename);
    await markLocalAssetDeleted(filename);
    await loadLocalAssetLibrary();
    setAssetLibraryStatus(`已从本地资源文件夹永久删除“${name}”；正文和草稿内嵌副本未改动。`, "success");
  } catch (error) {
    console.error(error);
    setAssetLibraryStatus(error.message || "本地图片删除失败", "error");
    button.disabled = false;
  }
}

async function deleteAssetFromLibrary(asset, button) {
  if (asset.storageMode === "local") {
    await deleteLocalAssetFromLibrary(asset, button);
    return;
  }
  const assetId = String(asset?.assetId || "");
  if (!assetId) return;
  const name = String(asset.originalName || "未命名图片");
  const localServer = String(asset.storageMode || "").startsWith("local");
  const storageLabel = localServer ? "本地资源文件夹" : "云端资源库";
  const confirmed = window.confirm(`确认从${storageLabel}永久删除“${name}”？\n\n当前文字框里的图片引用和本地草稿不会被改动。`);
  if (!confirmed) return;

  button.disabled = true;
  setAssetLibraryStatus(`正在删除 ${name}…`, "loading");
  try {
    let result = await requestAssetDeletion(assetId, false);
    if (result.response.status === 409) {
      const referenceCount = Math.max(0, Number(result.payload.referenceCount ?? asset.referenceCount) || 0);
      const forceConfirmed = window.confirm(`这张图片仍有 ${referenceCount} 处引用。\n\n仍要从${localServer ? "本地资源文件夹" : " TOS"}永久删除吗？引用文字不会被自动删除。`);
      if (!forceConfirmed) {
        setAssetLibraryStatus(`已取消删除，图片仍保留在${storageLabel}。`, "warning");
        button.disabled = false;
        return;
      }
      result = await requestAssetDeletion(assetId, true);
    }
    if (!result.response.ok) {
      throw new Error(assetApiError(result.payload, `图片删除失败（${result.response.status}）`));
    }
    await loadAssetLibrary();
    setAssetLibraryStatus(`已从${storageLabel}永久删除“${name}”；文字框和本地草稿未改动。`, "success");
  } catch (error) {
    console.error(error);
    setAssetLibraryStatus(error.message || "图片删除失败", "error");
    button.disabled = false;
  }
}

function normalizeObsidianImagePath(value) {
  let path = String(value || "").trim().replace(/^<|>$/g, "");
  try {
    path = decodeURIComponent(path);
  } catch {
    // Keep the original text when the reference contains an incomplete escape sequence.
  }
  return path
    .replace(/\\/g, "/")
    .replace(/^\.\//, "")
    .replace(/[?#].*$/, "")
    .replace(/^\/+/, "")
    .toLowerCase();
}

function imageReferenceKeys(reference) {
  const path = normalizeObsidianImagePath(reference);
  if (!path) return [];
  const name = path.split("/").filter(Boolean).pop();
  return name && name !== path ? [path, name] : [path];
}

function buildImageReferenceLookup(images) {
  const lookup = new Map();
  Object.entries(images || {}).forEach(([id, image]) => {
    imageReferenceKeys(image?.sourcePath || image?.name).forEach((key) => {
      if (!lookup.has(key)) lookup.set(key, []);
      lookup.get(key).push(id);
    });
  });
  return lookup;
}

function resolveObsidianImageReference(reference, lookup) {
  const keys = imageReferenceKeys(reference);
  for (const key of keys) {
    const ids = lookup.get(key) || [];
    if (ids.length === 1) return { id: ids[0] };
    if (ids.length > 1) return { ambiguous: true };
  }
  return { missing: true };
}

function convertObsidianImageReferences(markdown, images) {
  const lookup = buildImageReferenceLookup(images);
  const unresolved = new Set();
  let matched = 0;
  const replaceReference = (whole, reference) => {
    const target = String(reference || "").split("|")[0].trim();
    const result = resolveObsidianImageReference(target, lookup);
    if (result.id) {
      matched += 1;
      return `[[image:${result.id}]]`;
    }
    unresolved.add(`${result.ambiguous ? "重复文件名：" : "未找到："}${target}`);
    return whole;
  };

  let content = String(markdown || "").replace(/!\[\[([^\]\n]+)\]\]/g, replaceReference);
  content = content.replace(/!\[[^\]\n]*\]\((?:<([^>]+)>|([^\s)]+))(?:\s+[^)]*)?\)/g, (whole, wrappedPath, plainPath) => {
    return replaceReference(whole, wrappedPath || plainPath);
  });
  return { content, matched, unresolved: Array.from(unresolved) };
}

function countMarkdownImageReferences(markdown) {
  const text = String(markdown || "");
  return (text.match(/!\[\[[^\]\n]+\]\]/g) || []).length + (text.match(/!\[[^\]\n]*\]\([^)]*\)/g) || []).length;
}

function openObsidianVaultDatabase() {
  return new Promise((resolve, reject) => {
    if (!window.indexedDB) {
      reject(new Error("浏览器不支持本地仓库授权保存"));
      return;
    }
    const request = window.indexedDB.open(OBSIDIAN_VAULT_DB, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(OBSIDIAN_VAULT_STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function readStoredObsidianVault() {
  const db = await openObsidianVaultDatabase();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(OBSIDIAN_VAULT_STORE, "readonly");
    const request = transaction.objectStore(OBSIDIAN_VAULT_STORE).get(OBSIDIAN_VAULT_KEY);
    request.onsuccess = () => resolve(request.result || null);
    request.onerror = () => reject(request.error);
  });
}

async function saveObsidianVault(handle) {
  const db = await openObsidianVaultDatabase();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(OBSIDIAN_VAULT_STORE, "readwrite");
    transaction.objectStore(OBSIDIAN_VAULT_STORE).put(handle, OBSIDIAN_VAULT_KEY);
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
  });
}

function setObsidianVaultStatus(message, connected = false) {
  const statusText = String(message || "");
  if (statusText.startsWith("已连接：")) {
    els.obsidianVaultStatus.innerHTML = `已连接：<b>${escapeHtml(statusText.replace(/^已连接：/, ""))}</b>`;
  } else {
    els.obsidianVaultStatus.textContent = statusText;
  }
  els.obsidianVaultStatus.parentElement?.classList.toggle("is-connected", connected);
  els.obsidianImportMenu?.classList.toggle("is-vault-connected", Boolean(obsidianVault.handle));
  els.connectObsidianVault.innerHTML = connected
    ? '<i data-lucide="folder-cog"></i> 更换仓库'
    : '<i data-lucide="folder-open"></i> 连接 Obsidian 仓库';
  if (window.lucide) window.lucide.createIcons();
}

async function persistCurrentDraftImmediately() {
  flushStateSave();
  if (!state.localDatabaseHydrated) return false;
  const result = await flushProjectStoreToIndexedDb();
  return Boolean(result.localSaved || result.sharedSaved);
}

function canUseDirectoryPickerSafely() {
  const userAgent = navigator.userAgent || "";
  const embeddedBrowser = /Electron|Codex|ChatGPT|OpenAI/i.test(userAgent);
  const localPage = ["localhost", "127.0.0.1", ""].includes(window.location.hostname) || window.location.protocol === "file:";
  return Boolean(window.showDirectoryPicker && window.isSecureContext && !embeddedBrowser && !localPage);
}

function hasConnectedObsidianVault() {
  return Boolean(obsidianVault.handle || obsidianVault.fileLookup);
}

function buildVaultFileLookup(files) {
  const lookup = new Map();
  Array.from(files || []).filter(isImageFile).forEach((file) => {
    imageReferenceKeys(sourcePathForFile(file)).forEach((key) => {
      if (!lookup.has(key)) lookup.set(key, []);
      lookup.get(key).push(file);
    });
  });
  return lookup;
}

function findFileInSelectedVault(reference) {
  if (!obsidianVault.fileLookup) return null;
  for (const key of imageReferenceKeys(reference)) {
    const files = obsidianVault.fileLookup.get(key) || [];
    if (files.length === 1) return files[0];
  }
  return null;
}

async function loadObsidianVaultConnection() {
  if (!canUseDirectoryPickerSafely()) {
    setObsidianVaultStatus("点击连接仓库后选择 Obsidian 文件夹");
    return;
  }
  try {
    const handle = await readStoredObsidianVault();
    if (!handle) return;
    obsidianVault.handle = handle;
    const permission = await handle.queryPermission({ mode: "read" });
    setObsidianVaultStatus(permission === "granted" ? `已连接：${handle.name}` : `已记住：${handle.name}（首次粘贴时确认读取）`, permission === "granted");
  } catch {
    setObsidianVaultStatus("尚未连接仓库");
  }
}

async function connectObsidianVault() {
  if (!canUseDirectoryPickerSafely()) {
    els.obsidianVaultFolder?.click();
    return;
  }
  try {
    const handle = await window.showDirectoryPicker({ mode: "read" });
    obsidianVault.handle = handle;
    obsidianVault.fileLookup = null;
    await saveObsidianVault(handle);
    setObsidianVaultStatus(`已连接：${handle.name}`, true);
    els.status.textContent = "仓库已连接。以后直接把 Obsidian Markdown 粘贴到正文编辑区即可。";
  } catch (error) {
    if (error?.name !== "AbortError") setObsidianVaultStatus("连接失败，请重新选择 Obsidian 仓库根目录。");
  }
}

function handleObsidianVaultFolder(event) {
  const files = Array.from(event.target.files || []);
  event.target.value = "";
  if (!files.length) return;
  const rootName = files[0]?.webkitRelativePath?.split("/")?.[0] || "已选择的仓库";
  obsidianVault.handle = null;
  obsidianVault.fileLookup = buildVaultFileLookup(files);
  setObsidianVaultStatus(`已连接：${rootName}`, true);
  els.status.textContent = "仓库已连接。以后直接把 Obsidian Markdown 粘贴到正文编辑区即可。";
}

async function ensureObsidianVaultPermission() {
  if (obsidianVault.fileLookup) return true;
  if (!obsidianVault.handle) return false;
  let permission = await obsidianVault.handle.queryPermission({ mode: "read" });
  if (permission !== "granted") permission = await obsidianVault.handle.requestPermission({ mode: "read" });
  const granted = permission === "granted";
  setObsidianVaultStatus(granted ? `已连接：${obsidianVault.handle.name}` : `需要允许读取：${obsidianVault.handle.name}`, granted);
  return granted;
}

function extractMarkdownImageReferences(markdown) {
  const references = new Set();
  const text = String(markdown || "");
  for (const match of text.matchAll(/!\[\[([^\]\n]+)\]\]/g)) {
    references.add(match[1].split("|")[0].trim());
  }
  for (const match of text.matchAll(/!\[[^\]\n]*\]\((?:<([^>]+)>|([^\s)]+))(?:\s+[^)]*)?\)/g)) {
    references.add((match[1] || match[2] || "").trim());
  }
  return Array.from(references).filter(Boolean);
}

function vaultReferenceParts(reference) {
  let path = String(reference || "").trim().replace(/^<|>$/g, "");
  try {
    path = decodeURIComponent(path);
  } catch {
    // Keep the original text when the reference contains an incomplete escape sequence.
  }
  return path
    .replace(/\\/g, "/")
    .replace(/^\.\//, "")
    .replace(/[?#].*$/, "")
    .replace(/^\/+/, "")
    .split("/")
    .filter(Boolean);
}

async function findFileInObsidianVault(reference) {
  if (/^https?:/i.test(String(reference || ""))) return null;
  const parts = vaultReferenceParts(reference);
  if (!parts.length) return null;
  try {
    let directory = obsidianVault.handle;
    for (const part of parts.slice(0, -1)) directory = await directory.getDirectoryHandle(part);
    return await directory.getFileHandle(parts[parts.length - 1]);
  } catch {
    return findObsidianFileByName(obsidianVault.handle, parts[parts.length - 1]);
  }
}

async function findObsidianFileByName(directory, name) {
  if (!directory || !name) return null;
  for await (const [entryName, handle] of directory.entries()) {
    if (handle.kind === "file" && entryName.toLowerCase() === name.toLowerCase()) return handle;
    if (handle.kind === "directory" && ![".git", ".obsidian", "node_modules"].includes(entryName)) {
      const found = await findObsidianFileByName(handle, name);
      if (found) return found;
    }
  }
  return null;
}

function replaceEditorContent(content) {
  commitTextHistory();
  els.content.value = content;
  els.content.focus();
  els.content.setSelectionRange(0, 0);
  commitTextHistory();
  updateImageList();
  requestRender();
}

function closeObsidianImportMenu() {
  els.obsidianImportMenu.open = false;
}

async function importMarkdownFromConnectedVault(markdown) {
  if (!hasConnectedObsidianVault() || obsidianVault.importing) return false;
  obsidianVault.importing = true;
  els.status.textContent = "正在从 Obsidian 仓库读取图片…";
  try {
    if (!(await ensureObsidianVaultPermission())) {
      els.status.textContent = "未获得仓库读取权限，请重新连接后再试。";
      return true;
    }
    const lookup = buildImageReferenceLookup(state.images);
    const files = [];
    const sourcePaths = new Map();
    const missing = [];
    for (const reference of extractMarkdownImageReferences(markdown)) {
      if (resolveObsidianImageReference(reference, lookup).id) continue;
      const selectedFile = findFileInSelectedVault(reference);
      if (selectedFile) {
        files.push(selectedFile);
        sourcePaths.set(selectedFile, reference);
        continue;
      }
      const handle = obsidianVault.handle ? await findFileInObsidianVault(reference) : null;
      if (!handle) {
        missing.push(reference);
        continue;
      }
      const file = await handle.getFile();
      files.push(file);
      sourcePaths.set(file, reference);
    }
    if (missing.length) {
      const message = `仓库已连接，但没有找到 ${missing.length} 张图片：${missing.slice(0, 3).join("、")}。请确认选择的是包含这些路径的 Obsidian 仓库根目录。`;
      replaceEditorContent(markdown);
      els.obsidianImportMenu.open = true;
      els.status.textContent = message;
      return true;
    }
    const imported = await addImageFiles(files, sourcePaths);
    const converted = convertObsidianImageReferences(markdown, state.images);
    if (converted.unresolved.length) {
      els.status.textContent = "发现重名图片，暂时无法自动判断该用哪一张。";
      return true;
    }
    replaceEditorContent(markdown);
    els.status.textContent = `已从仓库自动读取 ${imported.ids.length} 张图片并完成导入`;
    closeObsidianImportMenu();
    return true;
  } catch (error) {
    console.error(error);
    replaceEditorContent(markdown);
    els.status.textContent = "读取 Obsidian 仓库失败，请重新连接仓库后再试。";
    return true;
  } finally {
    obsidianVault.importing = false;
  }
}

function readDroppedEntry(entry) {
  if (!entry) return Promise.resolve([]);
  if (entry.isFile) {
    return new Promise((resolve) => entry.file((file) => resolve([file]), () => resolve([])));
  }
  if (!entry.isDirectory) return Promise.resolve([]);
  const reader = entry.createReader();
  const readBatch = () => new Promise((resolve) => reader.readEntries(resolve, () => resolve([])));
  const readAll = async () => {
    const entries = [];
    let batch;
    do {
      batch = await readBatch();
      entries.push(...batch);
    } while (batch.length);
    return (await Promise.all(entries.map(readDroppedEntry))).flat();
  };
  return readAll();
}

async function getDroppedFiles(dataTransfer) {
  const entries = Array.from(dataTransfer?.items || [])
    .map((item) => item.webkitGetAsEntry?.())
    .filter(Boolean);
  if (entries.length) return (await Promise.all(entries.map(readDroppedEntry))).flat();
  return Array.from(dataTransfer?.files || []);
}

async function handleEditorPaste(event) {
  const files = Array.from(event.clipboardData?.items || [])
    .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
    .map((item) => item.getAsFile())
    .filter(Boolean);
  if (!files.length) {
    const markdown = event.clipboardData?.getData("text/plain") || "";
    const references = countMarkdownImageReferences(markdown);
    if (!references) return;
    event.preventDefault();
    if (hasConnectedObsidianVault()) {
      await importMarkdownFromConnectedVault(markdown);
      return;
    }
    els.obsidianImportMenu.open = true;
    els.status.textContent = `检测到 ${references} 个 Obsidian 图片引用。请先连接 Obsidian 仓库后再粘贴。`;
    requestAnimationFrame(() => positionToolPopover(els.obsidianImportMenu));
    return;
  }
  event.preventDefault();
  const imported = await addImageFiles(files);
  insertImageTagsAtCursor(imported.tags);
  const databaseSaved = await persistCurrentDraftImmediately();
  els.status.textContent = databaseSaved
    ? `已粘贴 ${imported.tags.length} 张图片，并已写入本地数据库`
    : `已粘贴 ${imported.tags.length} 张图片；请稍候再刷新`;
}

async function handleEditorDrop(event) {
  const hasFiles = Array.from(event.dataTransfer?.types || []).includes("Files");
  if (!hasFiles) return;
  event.preventDefault();
  const files = await getDroppedFiles(event.dataTransfer);
  if (!files.some(isImageFile)) return;
  const imported = await addImageFiles(files);
  insertImageTagsAtCursor(imported.tags);
  const databaseSaved = await persistCurrentDraftImmediately();
  els.status.textContent = databaseSaved
    ? `已插入 ${imported.tags.length} 张图片，并已写入本地数据库`
    : `已插入 ${imported.tags.length} 张图片；请稍候再刷新`;
}

async function handleAvatar(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  state.avatar = await readFileAsDataURL(file);
  state.avatarCrop = null;
  updateAvatarPreview();
  updateImageList();
  requestRender();
  await openCropper("avatar");
  event.target.value = "";
}

async function updateAvatarPreview() {
  if (!els.avatarPreview) return;
  if (!state.avatarCrop) {
    els.avatarPreview.src = state.avatar;
    return;
  }

  try {
    const image = await loadImage(state.avatar);
    const crop = clampCropRect(state.avatarCrop, image);
    const canvas = document.createElement("canvas");
    canvas.width = 160;
    canvas.height = 160;
    const ctx = canvas.getContext("2d");
    ctx.imageSmoothingQuality = "high";
    drawSourceCoverImage(ctx, image, crop, 0, 0, canvas.width, canvas.height);
    els.avatarPreview.src = canvas.toDataURL("image/png");
  } catch {
    els.avatarPreview.src = state.avatar;
  }
}

function updateImageList() {
  if (!els.imageList) return;
  els.imageList.innerHTML = "";
  const entries = Object.entries(state.images);

  if (!entries.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "插入图片后可在这里裁剪";
    els.imageList.append(empty);
    return;
  }

  for (const [id, image] of entries) {
    const row = document.createElement("div");
    row.className = "image-row";

    const thumb = document.createElement("img");
    thumb.className = "image-thumb";
    thumb.src = image.src;
    thumb.alt = image.name || id;

    const meta = document.createElement("div");
    meta.className = "image-meta";
    const name = document.createElement("strong");
    name.textContent = image.name || id;
    const status = document.createElement("span");
    const layout = normalizeImageLayout(image.layout);
    const widthLabel = layout.fixedWidth && layout.fixedHeight
      ? `固定框 ${Math.round(layout.fixedWidth)}x${Math.round(layout.fixedHeight)}`
      : layout.widthPercent
        ? `${Math.round(layout.widthPercent)}%`
        : "自适应";
    status.textContent = `${image.crop ? "已裁剪" : "原图比例"} · ${widthLabel}`;
    meta.append(name, status);

    const actions = document.createElement("div");
    actions.className = "image-row-actions";
    const cropButton = document.createElement("button");
    cropButton.type = "button";
    cropButton.title = "裁剪图片";
    cropButton.setAttribute("aria-label", `裁剪 ${image.name || id}`);
    cropButton.innerHTML = '<i data-lucide="crop"></i>';
    cropButton.addEventListener("click", () => openCropper("image", id));

    const resetButton = document.createElement("button");
    resetButton.type = "button";
    resetButton.title = "恢复原图";
    resetButton.setAttribute("aria-label", `恢复 ${image.name || id}`);
    resetButton.innerHTML = '<i data-lucide="rotate-ccw"></i>';
    resetButton.disabled = !image.crop;
    resetButton.addEventListener("click", () => {
      image.crop = null;
      updateImageList();
      requestRender();
    });
    actions.append(cropButton, resetButton);

    row.append(thumb, meta, actions);
    els.imageList.append(row);
  }

  if (window.lucide) window.lucide.createIcons();
}

function defaultNewImageLayout() {
  const fixedWidth = normalizeFixedImageDimension(els.fixedImageWidth?.value, CARD_CONTENT_WIDTH);
  const fixedHeight = normalizeFixedImageDimension(els.fixedImageHeight?.value, 760);
  if (fixedWidth && fixedHeight) {
    return {
      fixedWidth,
      fixedHeight,
      align: "center",
    };
  }

  const percent = Number(els.imageWidthPercent?.value);
  if (!Number.isFinite(percent)) return null;
  return {
    widthPercent: clamp(percent, 25, 100),
    align: "center",
  };
}

function applyImageWidthToAll() {
  const entries = Object.entries(state.images);
  if (!entries.length) {
    els.status.textContent = "还没有插入图片";
    return;
  }

  const widthPercent = clamp(Number(els.imageWidthPercent?.value) || 100, 25, 100);
  if (els.imageWidthPercent) els.imageWidthPercent.value = String(Math.round(widthPercent));

  for (const [, image] of entries) {
    image.layout = {
      ...normalizeImageLayout(image.layout),
      widthPercent,
      fixedWidth: null,
      fixedHeight: null,
    };
  }

  updateImageList();
  saveState();
  render();
  els.status.textContent = `已将 ${entries.length} 张图片设置为 ${Math.round(widthPercent)}% 宽度`;
}

function applyFixedImageSizeToAll() {
  const entries = Object.entries(state.images);
  if (!entries.length) {
    els.status.textContent = "还没有插入图片";
    return;
  }

  const fixedWidth = normalizeFixedImageDimension(els.fixedImageWidth?.value, CARD_CONTENT_WIDTH);
  const fixedHeight = normalizeFixedImageDimension(els.fixedImageHeight?.value, 760);
  if (!fixedWidth || !fixedHeight) {
    els.status.textContent = "请输入固定宽度和固定高度";
    return;
  }

  if (els.fixedImageWidth) els.fixedImageWidth.value = String(Math.round(fixedWidth));
  if (els.fixedImageHeight) els.fixedImageHeight.value = String(Math.round(fixedHeight));

  for (const [, image] of entries) {
    image.layout = {
      ...normalizeImageLayout(image.layout),
      fixedWidth,
      fixedHeight,
      widthPercent: null,
    };
  }

  updateImageList();
  saveState();
  render();
  els.status.textContent = `已将 ${entries.length} 张图片设置为 ${Math.round(fixedWidth)}x${Math.round(fixedHeight)}`;
}

function normalizeFixedImageDimension(value, max) {
  const dimension = Number(value);
  if (!Number.isFinite(dimension) || dimension <= 0) return null;
  return clamp(dimension, 80, max);
}

async function openCropper(kind, id = null) {
  const targetImage = kind === "avatar" ? { src: state.avatar, name: "头像", crop: state.avatarCrop } : state.images[id];
  if (!targetImage?.src) return;

  cropper.image = await loadImage(targetImage.src).catch(() => null);
  if (!cropper.image) return;

  cropper.target = { kind, id };
  cropper.aspect = null;
  cropper.drag = null;
  cropper.rect = clampCropRect(targetImage.crop, cropper.image);
  els.cropTitle.textContent = kind === "avatar" ? "裁剪头像" : `裁剪 ${targetImage.name || id}`;
  els.cropSubtitle.textContent = kind === "avatar" ? "头像最终会显示为圆形，建议使用 1:1" : "不裁剪时会按原图比例放入页面";
  setActiveRatioButton("free");
  els.cropModal.classList.remove("hidden");
  drawCropper();
  if (window.lucide) window.lucide.createIcons();
}

function closeCropper() {
  els.cropModal.classList.add("hidden");
  cropper.target = null;
  cropper.image = null;
  cropper.rect = null;
  cropper.drag = null;
}

function applyCropper() {
  if (!cropper.target || !cropper.image || !cropper.rect) return;
  const crop = isFullCrop(cropper.rect, cropper.image)
    ? null
    : {
        x: Math.round(cropper.rect.x),
        y: Math.round(cropper.rect.y),
        width: Math.round(cropper.rect.width),
        height: Math.round(cropper.rect.height),
      };

  if (cropper.target.kind === "avatar") {
    state.avatarCrop = crop;
    updateAvatarPreview();
  } else if (state.images[cropper.target.id]) {
    state.images[cropper.target.id].crop = crop;
  }
  updateImageList();
  closeCropper();
  requestRender();
}

function resetCropperTarget() {
  if (!cropper.target) return;
  if (cropper.target.kind === "avatar") {
    state.avatarCrop = null;
    updateAvatarPreview();
  } else if (state.images[cropper.target.id]) {
    state.images[cropper.target.id].crop = null;
  }
  updateImageList();
  closeCropper();
  requestRender();
}

function setCropAspect(value) {
  if (!cropper.image || !cropper.rect) return;
  let aspect = null;
  if (value === "original") aspect = cropper.image.width / cropper.image.height;
  if (value !== "free" && value !== "original") aspect = Number(value);
  cropper.aspect = Number.isFinite(aspect) && aspect > 0 ? aspect : null;
  cropper.rect = fitRectToAspect(cropper.rect, cropper.image, cropper.aspect);
  setActiveRatioButton(value);
  drawCropper();
}

function setActiveRatioButton(value) {
  els.ratioButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.ratio === value);
  });
}

function fullCropRect(image) {
  return { x: 0, y: 0, width: image.width, height: image.height };
}

function clampCropRect(crop, image) {
  if (!crop) return fullCropRect(image);
  const width = clamp(Number(crop.width) || image.width, 20, image.width);
  const height = clamp(Number(crop.height) || image.height, 20, image.height);
  return {
    x: clamp(Number(crop.x) || 0, 0, image.width - width),
    y: clamp(Number(crop.y) || 0, 0, image.height - height),
    width,
    height,
  };
}

function isFullCrop(rect, image) {
  return rect.x <= 1 && rect.y <= 1 && Math.abs(rect.width - image.width) <= 1 && Math.abs(rect.height - image.height) <= 1;
}

function fitRectToAspect(rect, image, aspect) {
  if (!aspect) return clampCropRect(rect, image);
  const centerX = rect.x + rect.width / 2;
  const centerY = rect.y + rect.height / 2;
  let width = rect.width;
  let height = width / aspect;
  if (height > rect.height) {
    height = rect.height;
    width = height * aspect;
  }
  if (width > image.width) {
    width = image.width;
    height = width / aspect;
  }
  if (height > image.height) {
    height = image.height;
    width = height * aspect;
  }
  width = Math.max(20, width);
  height = Math.max(20, height);
  return {
    x: clamp(centerX - width / 2, 0, image.width - width),
    y: clamp(centerY - height / 2, 0, image.height - height),
    width,
    height,
  };
}

function getCropDisplay() {
  const canvas = els.cropCanvas;
  const image = cropper.image;
  const padding = 26;
  const scale = Math.min((canvas.width - padding * 2) / image.width, (canvas.height - padding * 2) / image.height);
  const width = image.width * scale;
  const height = image.height * scale;
  return {
    x: (canvas.width - width) / 2,
    y: (canvas.height - height) / 2,
    width,
    height,
    scale,
  };
}

function sourceToCanvasRect(rect) {
  const display = cropper.display;
  return {
    x: display.x + rect.x * display.scale,
    y: display.y + rect.y * display.scale,
    width: rect.width * display.scale,
    height: rect.height * display.scale,
  };
}

function canvasPointFromEvent(event) {
  const bounds = els.cropCanvas.getBoundingClientRect();
  return {
    x: ((event.clientX - bounds.left) / bounds.width) * els.cropCanvas.width,
    y: ((event.clientY - bounds.top) / bounds.height) * els.cropCanvas.height,
  };
}

function sourcePointFromCanvas(point) {
  const display = cropper.display;
  return {
    x: clamp((point.x - display.x) / display.scale, 0, cropper.image.width),
    y: clamp((point.y - display.y) / display.scale, 0, cropper.image.height),
  };
}

function drawCropper() {
  if (!cropper.image || !cropper.rect) return;
  const canvas = els.cropCanvas;
  const ctx = canvas.getContext("2d");
  cropper.display = getCropDisplay();
  const display = cropper.display;
  const crop = sourceToCanvasRect(cropper.rect);

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#0b1020";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(cropper.image, display.x, display.y, display.width, display.height);

  ctx.fillStyle = "rgba(2, 6, 23, 0.58)";
  ctx.fillRect(display.x, display.y, display.width, crop.y - display.y);
  ctx.fillRect(display.x, crop.y + crop.height, display.width, display.y + display.height - crop.y - crop.height);
  ctx.fillRect(display.x, crop.y, crop.x - display.x, crop.height);
  ctx.fillRect(crop.x + crop.width, crop.y, display.x + display.width - crop.x - crop.width, crop.height);

  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 3;
  ctx.strokeRect(crop.x, crop.y, crop.width, crop.height);

  ctx.strokeStyle = "rgba(255, 255, 255, 0.76)";
  ctx.lineWidth = 1;
  for (let i = 1; i < 3; i += 1) {
    const gx = crop.x + (crop.width * i) / 3;
    const gy = crop.y + (crop.height * i) / 3;
    ctx.beginPath();
    ctx.moveTo(gx, crop.y);
    ctx.lineTo(gx, crop.y + crop.height);
    ctx.moveTo(crop.x, gy);
    ctx.lineTo(crop.x + crop.width, gy);
    ctx.stroke();
  }

  ctx.fillStyle = "#ffffff";
  const handles = [
    [crop.x, crop.y],
    [crop.x + crop.width, crop.y],
    [crop.x, crop.y + crop.height],
    [crop.x + crop.width, crop.y + crop.height],
  ];
  for (const [x, y] of handles) {
    ctx.fillRect(x - 5, y - 5, 10, 10);
  }
}

function detectCropHit(point) {
  const crop = sourceToCanvasRect(cropper.rect);
  const corners = {
    nw: [crop.x, crop.y],
    ne: [crop.x + crop.width, crop.y],
    sw: [crop.x, crop.y + crop.height],
    se: [crop.x + crop.width, crop.y + crop.height],
  };
  for (const [handle, [x, y]] of Object.entries(corners)) {
    if (Math.hypot(point.x - x, point.y - y) <= 16) return handle;
  }
  if (point.x >= crop.x && point.x <= crop.x + crop.width && point.y >= crop.y && point.y <= crop.y + crop.height) {
    return "move";
  }
  return "move-new";
}

function startCropDrag(event) {
  if (!cropper.image || !cropper.rect) return;
  cropper.display = getCropDisplay();
  const canvasPoint = canvasPointFromEvent(event);
  const display = cropper.display;
  if (
    canvasPoint.x < display.x ||
    canvasPoint.x > display.x + display.width ||
    canvasPoint.y < display.y ||
    canvasPoint.y > display.y + display.height
  ) {
    return;
  }

  const sourcePoint = sourcePointFromCanvas(canvasPoint);
  const action = detectCropHit(canvasPoint);
  if (action === "move-new") {
    cropper.rect = clampMovedRect(
      {
        ...cropper.rect,
        x: sourcePoint.x - cropper.rect.width / 2,
        y: sourcePoint.y - cropper.rect.height / 2,
      },
      cropper.image,
    );
  }

  cropper.drag = {
    action: action === "move-new" ? "move" : action,
    startX: sourcePoint.x,
    startY: sourcePoint.y,
    startRect: { ...cropper.rect },
  };
  drawCropper();
}

function moveCropDrag(event) {
  if (!cropper.drag || !cropper.image) return;
  const point = sourcePointFromCanvas(canvasPointFromEvent(event));
  const drag = cropper.drag;

  if (drag.action === "move") {
    cropper.rect = clampMovedRect(
      {
        ...drag.startRect,
        x: drag.startRect.x + point.x - drag.startX,
        y: drag.startRect.y + point.y - drag.startY,
      },
      cropper.image,
    );
  } else {
    cropper.rect = resizeCropRect(drag.action, drag.startRect, point, cropper.image, cropper.aspect);
  }
  drawCropper();
}

function stopCropDrag() {
  cropper.drag = null;
}

function clampMovedRect(rect, image) {
  return {
    ...rect,
    x: clamp(rect.x, 0, image.width - rect.width),
    y: clamp(rect.y, 0, image.height - rect.height),
  };
}

function resizeCropRect(handle, startRect, point, image, aspect) {
  const anchorX = handle.includes("w") ? startRect.x + startRect.width : startRect.x;
  const anchorY = handle.includes("n") ? startRect.y + startRect.height : startRect.y;
  let width = Math.max(20, Math.abs(point.x - anchorX));
  let height = Math.max(20, Math.abs(point.y - anchorY));

  if (aspect) {
    if (width / height > aspect) width = height * aspect;
    else height = width / aspect;
  }

  width = Math.min(width, image.width);
  height = Math.min(height, image.height);
  let x = handle.includes("w") ? anchorX - width : anchorX;
  let y = handle.includes("n") ? anchorY - height : anchorY;

  if (x < 0) x = 0;
  if (y < 0) y = 0;
  if (x + width > image.width) x = image.width - width;
  if (y + height > image.height) y = image.height - height;
  return fitRectToAspect({ x, y, width, height }, image, aspect);
}

function resolveMarkdownImageBlock(line, imageLookup) {
  const internal = line.match(/^\[\[image:([\w-]+)\]\]$/);
  if (internal) return internal[1];

  const obsidian = line.match(/^!\[\[([^\]\n]+)\]\]$/);
  if (obsidian) return resolveObsidianImageReference(obsidian[1].split("|")[0].trim(), imageLookup).id || null;

  const markdown = line.match(/^!\[[^\]\n]*\]\((?:<([^>]+)>|([^\s)]+))(?:\s+[^)]*)?\)$/);
  if (markdown) return resolveObsidianImageReference(markdown[1] || markdown[2], imageLookup).id || null;
  return null;
}

function isMarkdownImageBlock(line) {
  return /^\[\[image:[\w-]+\]\]$/.test(line)
    || /^!\[\[[^\]\n]+\]\]$/.test(line)
    || /^!\[[^\]\n]*\]\((?:<[^>]+>|[^\s)]+)(?:\s+[^)]*)?\)$/.test(line);
}

function parseBlocks(content, images = {}) {
  const normalized = content.replace(/\r\n/g, "\n");
  const lines = normalized.split("\n");
  const imageLookup = buildImageReferenceLookup(images);
  const lineOffsets = [];
  let runningOffset = 0;
  lines.forEach((line) => {
    lineOffsets.push(runningOffset);
    runningOffset += line.length + 1;
  });
  const blocks = [];
  let paragraphLines = [];

  const flushParagraph = () => {
    if (!paragraphLines.length) return;
    blocks.push({ type: "p", lines: paragraphLines });
    paragraphLines = [];
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const hasContentBeforeLine = blocks.length > 0 || paragraphLines.length > 0;
    const leading = line.match(/^\s*/)[0].length;
    const trailing = line.match(/\s*$/)[0].length;
    const trimmed = line.slice(leading, line.length - trailing);
    const trimmedStart = lineOffsets[index] + leading;

    if (trimmed) {
      if (trimmed === "[[pagebreak]]") {
        flushParagraph();
        blocks.push({ type: "pagebreak" });
        continue;
      }
      const imageId = resolveMarkdownImageBlock(trimmed, imageLookup);
      if (isMarkdownImageBlock(trimmed)) {
        flushParagraph();
        if (imageId) {
          blocks.push({
            type: "image",
            id: imageId,
            sourceStart: lineOffsets[index],
            sourceEnd: lineOffsets[index] + line.length,
            occurrenceKey: `${imageId}:${lineOffsets[index]}`,
          });
        }
      } else if (isMarkdownTableHeader(trimmed, lines[index + 1])) {
        flushParagraph();
        const headerCells = splitMarkdownTableRow(trimmed);
        const rows = [];
        let rowIndex = index + 2;
        while (rowIndex < lines.length) {
          const cells = splitMarkdownTableRow(lines[rowIndex].trim());
          if (!cells || !cells.length) break;
          rows.push(cells.map((cell) => parseInline(cell)));
          rowIndex += 1;
        }
        blocks.push({ type: "table", header: headerCells.map((cell) => parseInline(cell)), rows });
        index = rowIndex - 1;
      } else {
        const heading = trimmed.match(/^(#{1,6})\s+(.+)$/);
        if (heading) {
          flushParagraph();
          const level = heading[1].length;
          const contentStart = trimmedStart + heading[1].length + 1;
          blocks.push({ type: level === 1 ? "h1" : level === 2 ? "h2" : "h3", tokens: parseInline(heading[2].trim(), contentStart) });
        } else if (trimmed.startsWith("> ")) {
          flushParagraph();
          const contentStart = trimmedStart + 2 + countLeadingSpaces(trimmed.slice(2));
          blocks.push({ type: "quote", tokens: parseInline(trimmed.slice(2).trim(), contentStart) });
        } else if (/^([-*+]\s+|\d+[.)]\s+)/.test(trimmed)) {
          const text = trimmed.replace(/^([-*+]\s+|\d+[.)]\s+)/, "• ");
          paragraphLines.push(parseInline(text, trimmedStart));
        } else if (/^([-*_])(?:\s*\1){2,}\s*$/.test(trimmed)) {
          flushParagraph();
          blocks.push({ type: "spacer" });
        } else {
          paragraphLines.push(parseInline(trimmed, trimmedStart));
        }
      }
    } else {
      flushParagraph();
      if (hasContentBeforeLine) {
        blocks.push({ type: "spacer" });
      }
    }
  }

  flushParagraph();
  return blocks;
}

function splitMarkdownTableRow(line) {
  const value = String(line || "").trim();
  if (!value.includes("|")) return null;
  const cells = value.replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
  return cells.length > 1 ? cells : null;
}

function isMarkdownTableDivider(line) {
  const cells = splitMarkdownTableRow(line);
  return Boolean(cells?.length) && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function isMarkdownTableHeader(line, nextLine) {
  return Boolean(splitMarkdownTableRow(line)?.length) && isMarkdownTableDivider(nextLine);
}

function countLeadingSpaces(text) {
  return text.match(/^\s*/)[0].length;
}

function applyInlineStyle(tokens, style) {
  return tokens.map((token) => {
    const next = { ...token };
    for (const [key, value] of Object.entries(style)) {
      if (next[key] === undefined) next[key] = value;
    }
    return next;
  });
}

function parseInline(text, baseStart = 0) {
  const tokens = [];
  let i = 0;

  while (i < text.length) {
    const colorMatch = text.slice(i).match(/^\{\{color:(#[0-9a-fA-F]{3,8})\|([\s\S]*?)\}\}/);
    if (colorMatch) {
      const textStart = baseStart + i + colorMatch[0].indexOf("|") + 1;
      tokens.push(...applyInlineStyle(parseInline(colorMatch[2], textStart), { color: colorMatch[1] }));
      i += colorMatch[0].length;
      continue;
    }

    const bgMatch = text.slice(i).match(/^\{\{bg:(#[0-9a-fA-F]{3,8})\|([\s\S]*?)\}\}/);
    if (bgMatch) {
      const textStart = baseStart + i + bgMatch[0].indexOf("|") + 1;
      tokens.push(...applyInlineStyle(parseInline(bgMatch[2], textStart), { bgColor: bgMatch[1] }));
      i += bgMatch[0].length;
      continue;
    }

    if (text.startsWith("**", i)) {
      const close = text.indexOf("**", i + 2);
      if (close !== -1) {
        tokens.push(...applyInlineStyle(parseInline(text.slice(i + 2, close), baseStart + i + 2), { bold: true }));
        i = close + 2;
        continue;
      }
    }

    if (text.startsWith("*", i)) {
      const close = text.indexOf("*", i + 1);
      if (close !== -1) {
        tokens.push(...applyInlineStyle(parseInline(text.slice(i + 1, close), baseStart + i + 1), { italic: true }));
        i = close + 1;
        continue;
      }
    }

    const nextMarkers = ["{{color:", "{{bg:", "**", "*"]
      .map((marker) => text.indexOf(marker, i + 1))
      .filter((index) => index !== -1);
    const next = nextMarkers.length ? Math.min(...nextMarkers) : text.length;
    tokens.push({ text: text.slice(i, next), sourceStart: baseStart + i, sourceEnd: baseStart + next });
    i = next;
  }

  return tokens.filter((token) => token.text.length > 0);
}

function styleForBlock(type, settings) {
  const baseSize = settings.fontSize;
  const theme = cardThemeFor(settings);
  const themeRole = theme.typography[type] || null;
  const fontSettings = {
    zhFont: themeRole?.headingFont || settings.zhFont,
    enFont: settings.enFont,
  };
  if (type === "h1") {
    const role = theme.typography.h1;
    return {
      ...fontSettings,
      size: Math.round(baseSize * role.scale),
      lineHeight: role.lineHeight,
      weight: role.weight,
      italic: false,
      marginTop: role.marginTop,
      marginBottom: role.marginBottom,
      color: settings.textColor,
    };
  }
  if (type === "h2") {
    const role = theme.typography.h2;
    return {
      ...fontSettings,
      size: Math.round(baseSize * role.scale),
      lineHeight: role.lineHeight,
      weight: role.weight,
      italic: false,
      marginTop: role.marginTop,
      marginBottom: role.marginBottom,
      color: settings.textColor,
    };
  }
  if (type === "h3") {
    const role = theme.typography.h3;
    return {
      ...fontSettings,
      size: Math.round(baseSize * role.scale),
      lineHeight: role.lineHeight,
      weight: role.weight,
      italic: false,
      marginTop: role.marginTop,
      marginBottom: role.marginBottom,
      color: settings.textColor,
    };
  }
  if (type === "quote") {
    return {
      ...fontSettings,
      size: baseSize,
      lineHeight: settings.lineHeight,
      weight: theme.emphasis === "editorial" ? 540 : 400,
      italic: theme.emphasis === "editorial",
      marginTop: 18,
      marginBottom: 10,
      color: settings.textColor,
      quote: true,
    };
  }
  return {
    ...fontSettings,
    size: baseSize,
    lineHeight: settings.lineHeight,
    weight: 400,
    italic: false,
    marginTop: theme.typography.paragraph.marginTop,
    marginBottom: 0,
    color: settings.textColor,
  };
}

function fontString(style, token = {}) {
  const italic = token.italic || style.italic ? "italic " : "";
  const weight = token.bold ? 650 : style.weight;
  return `${italic}${weight} ${style.size}px ${fontFamilyForText(token.text, style)}`;
}

function fontFamilyForText(text, settings) {
  const zhFont = FONT_STACKS[settings.zhFont] || FONT_STACKS["zh-system"];
  const enFont = FONT_STACKS[settings.enFont] || FONT_STACKS["en-system"];
  const emojiFont = '"Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji"';
  return /[A-Za-z0-9_@#%+./:-]/.test(text || "") ? `${enFont}, ${zhFont}, ${emojiFont}` : `${zhFont}, ${enFont}, ${emojiFont}`;
}

function splitTokenText(token) {
  const text = token.text || "";
  const segments = graphemeSegments(text);
  const units = [];
  let word = null;

  function flushWord() {
    if (!word) return;
    units.push(word);
    word = null;
  }

  for (const segment of segments) {
    if (/^[A-Za-z0-9_@#%+./:-]$/.test(segment.text)) {
      if (!word) word = { text: "", start: segment.start, end: segment.end };
      word.text += segment.text;
      word.end = segment.end;
      continue;
    }
    flushWord();
    units.push(segment);
  }

  flushWord();
  return units;
}

function graphemeSegments(text) {
  if (window.Intl?.Segmenter) {
    const segmenter = new Intl.Segmenter("zh", { granularity: "grapheme" });
    return Array.from(segmenter.segment(text), (part) => ({
      text: part.segment,
      start: part.index,
      end: part.index + part.segment.length,
    }));
  }

  const result = [];
  let index = 0;
  for (const char of Array.from(text)) {
    result.push({ text: char, start: index, end: index + char.length });
    index += char.length;
  }
  return result;
}

function isNoLineStartPunctuation(text) {
  return /^[,.;:!?，。！？；：、…）\])}】》〉」』”’"'、]+$/.test(text);
}

function isNoLineEndPunctuation(text) {
  return /^[（\[(【《〈「『“‘"']+$/.test(text);
}

function wrapTokens(ctx, tokens, style, maxWidth) {
  const lines = [];
  let line = [];
  let width = 0;

  function pushLine() {
    while (line.length && /^\s+$/.test(line[0].text)) {
      width -= measureToken(ctx, line[0], style);
      line.shift();
    }
    while (line.length && /^\s+$/.test(line[line.length - 1].text)) {
      width -= measureToken(ctx, line[line.length - 1], style);
      line.pop();
    }
    if (line.length) lines.push(line);
    line = [];
    width = 0;
  }

  for (const token of tokens) {
    for (const unit of splitTokenText(token)) {
      const part = {
        ...token,
        text: unit.text,
        sourceStart: token.sourceStart + unit.start,
        sourceEnd: token.sourceStart + unit.end,
      };
      const measured = measureToken(ctx, part, style);
      const shouldStayWithPrevious = isNoLineStartPunctuation(unit.text);
      const previousText = line.length ? line[line.length - 1].text : "";
      const previousNeedsNext = isNoLineEndPunctuation(previousText);

      if (width + measured > maxWidth && line.length && !shouldStayWithPrevious && !previousNeedsNext) {
        pushLine();
      }
      if (!line.length && /^\s+$/.test(unit.text)) continue;
      if (!line.length && shouldStayWithPrevious && lines.length) {
        lines[lines.length - 1].push(part);
        continue;
      }
      line.push(part);
      width += measured;
    }
  }

  pushLine();
  return lines;
}

function wrapBlockLines(ctx, block, style, maxWidth) {
  if (!block.lines) return wrapTokens(ctx, block.tokens, style, maxWidth);
  const lines = [];
  for (const sourceLine of block.lines) {
    lines.push(...wrapTokens(ctx, sourceLine, style, maxWidth));
  }
  return lines;
}

function buildTableLayout(ctx, block, settings, maxWidth) {
  const columns = Math.max(1, block.header.length, ...block.rows.map((row) => row.length));
  const cellWidth = maxWidth / columns;
  const headerStyle = {
    ...styleForBlock("h3", settings),
    size: Math.max(18, Math.round(settings.fontSize * 0.76)),
    lineHeight: 1.35,
  };
  const bodyStyle = {
    ...styleForBlock("p", settings),
    size: Math.max(17, Math.round(settings.fontSize * 0.72)),
    lineHeight: 1.4,
  };
  const rowPadding = 10;
  const makeRow = (cells, style) => {
    const lines = Array.from({ length: columns }, (_, index) => wrapTokens(ctx, cells[index] || [], style, Math.max(34, cellWidth - rowPadding * 2)));
    const lineHeight = Math.ceil(style.size * style.lineHeight);
    return {
      cells: lines,
      style,
      lineHeight,
      height: Math.max(lineHeight, ...lines.map((cellLines) => cellLines.length * lineHeight)) + rowPadding * 2,
    };
  };
  const rows = [makeRow(block.header, headerStyle), ...block.rows.map((row) => makeRow(row, bodyStyle))];
  return {
    columns,
    cellWidth,
    rows,
    height: rows.reduce((total, row) => total + row.height, 0),
  };
}

function blankLineGap(settings) {
  return Math.max(18, Math.ceil(settings.fontSize * 0.8));
}

function measureToken(ctx, token, style) {
  ctx.font = fontString(style, token);
  return ctx.measureText(token.text).width;
}

function getImageSourceRect(image, crop) {
  return clampCropRect(crop, image);
}

function imageBlockSize(sourceRect, maxWidth, maxHeight, layout = null) {
  const normalized = normalizeImageLayout(layout);
  const aspect = sourceRect.width / sourceRect.height;
  const baseWidth = Math.min(maxWidth, maxHeight * aspect);
  const legacyMaxScale = baseWidth > 0 ? maxWidth / baseWidth : 1;
  const fixedWidth = normalized.fixedWidth && normalized.fixedHeight ? clamp(normalized.fixedWidth, 80, maxWidth) : null;
  const fixedHeight = normalized.fixedWidth && normalized.fixedHeight ? clamp(normalized.fixedHeight, 80, maxHeight) : null;
  const requestedWidth = normalized.widthPercent
    ? maxWidth * (normalized.widthPercent / 100)
    : baseWidth * clamp(normalized.widthScale, 0.25, legacyMaxScale);
  const width = fixedWidth || Math.min(requestedWidth, maxWidth, maxHeight * aspect);
  const height = fixedHeight || width / aspect;
  const maxOffset = Math.max(0, maxWidth - width);
  let offsetX = maxOffset / 2;

  if (normalized.align === "left") {
    offsetX = 0;
  } else if (normalized.align === "right") {
    offsetX = maxOffset;
  }

  return {
    width,
    height,
    offsetX,
    baseWidth,
    maxWidth,
  };
}

function normalizeImageLayout(layout = {}) {
  const value = layout || {};
  const align = ["left", "center", "right"].includes(value.align) ? value.align : "center";
  const rawPercent = Number(value.widthPercent);
  const widthPercent = Number.isFinite(rawPercent) && rawPercent > 0 ? clamp(rawPercent, 25, 100) : null;
  const rawFixedWidth = Number(value.fixedWidth);
  const rawFixedHeight = Number(value.fixedHeight);
  const fixedWidth = Number.isFinite(rawFixedWidth) && rawFixedWidth > 0 ? clamp(rawFixedWidth, 80, CARD_CONTENT_WIDTH) : null;
  const fixedHeight = Number.isFinite(rawFixedHeight) && rawFixedHeight > 0 ? clamp(rawFixedHeight, 80, 760) : null;
  return {
    widthScale: clamp(Number(value.widthScale) || 1, 0.25, 20),
    widthPercent,
    fixedWidth,
    fixedHeight,
    align,
  };
}

function imageMaxHeightForLayout(layout, fallbackMaxHeight, absoluteMaxHeight = fallbackMaxHeight) {
  const normalized = normalizeImageLayout(layout);
  if (!normalized.fixedHeight) return fallbackMaxHeight;
  return clamp(normalized.fixedHeight, 80, Math.max(80, absoluteMaxHeight));
}

function contentBoundsForPage(settings, showIdentity) {
  const theme = cardThemeFor(settings);
  const { geometry } = theme;
  const top = theme.identityPlacement === "top" && showIdentity
    ? geometry.topWithAuthor
    : geometry.topWithoutAuthor;
  return {
    left: geometry.sidePadding,
    right: CANVAS_WIDTH - geometry.sidePadding,
    top,
    bottom: geometry.bottom,
  };
}

async function buildPages(settings) {
  const measureCanvas = document.createElement("canvas");
  const ctx = measureCanvas.getContext("2d");
  const blocks = parseBlocks(settings.content, settings.images);
  const avatar = await loadImage(settings.avatar).catch(() => null);
  const badge = await loadImage(verifiedBadgeSrc).catch(() => null);
  const imageCache = {};
  const pages = [];
  let page = createPage();
  const contentWidth = page.bounds.right - page.bounds.left;
  let y = page.bounds.top;
  let hasContent = false;
  let previousBlockType = null;

  function createPage() {
    const theme = cardThemeFor(settings);
    const showIdentity = settings.headerMode !== "first" || pages.length === 0;
    const bounds = contentBoundsForPage(settings, showIdentity);
    return {
      avatar,
      badge,
      settings,
      pageIndex: pages.length,
      totalPages: 0,
      showIdentity,
      showHeader: showIdentity && theme.identityPlacement === "top",
      showFooterAuthor: showIdentity && theme.identityPlacement === "bottom",
      bounds,
      items: [],
    };
  }

  function finishPage() {
    if (page.items.length) {
      pages.push(page);
    }
    page = createPage();
    y = page.bounds.top;
    hasContent = false;
    previousBlockType = null;
  }

  function ensureSpace(height, topMargin = 0) {
    if (hasContent && y + topMargin + height > page.bounds.bottom) {
      finishPage();
    }
    if (!hasContent) topMargin = 0;
    y += topMargin;
  }

  for (const block of blocks) {
    if (block.type === "pagebreak") {
      finishPage();
      continue;
    }

    if (block.type === "spacer") {
      const spacerHeight = blankLineGap(settings);
      ensureSpace(spacerHeight, 0);
      y += spacerHeight;
      previousBlockType = "spacer";
      continue;
    }

    if (block.type === "table") {
      const table = buildTableLayout(ctx, block, settings, contentWidth);
      ensureSpace(table.height, hasContent && previousBlockType !== "spacer" ? 18 : 0);
      page.items.push({ type: "table", x: page.bounds.left, y, width: contentWidth, table });
      y += table.height + 18;
      hasContent = true;
      previousBlockType = "table";
      continue;
    }

    if (block.type === "image") {
      const data = settings.images[block.id];
      if (!data) continue;
      if (!imageCache[block.id]) {
        imageCache[block.id] = await loadImage(data.src).catch(() => null);
      }
      const img = imageCache[block.id];
      if (!img) continue;
      const sourceRect = getImageSourceRect(img, data.crop);
      const size = imageBlockSize(sourceRect, contentWidth, imageMaxHeightForLayout(data.layout, Math.min(settings.imageHeight, page.bounds.bottom - page.bounds.top), page.bounds.bottom - page.bounds.top), data.layout);
      const height = size.height;
      ensureSpace(height, hasContent && previousBlockType !== "spacer" ? 24 : 0);
      page.items.push({
        type: "image",
        imageId: block.id,
        sourceStart: block.sourceStart,
        sourceEnd: block.sourceEnd,
        occurrenceKey: block.occurrenceKey,
        image: img,
        sourceRect,
        baseWidth: size.baseWidth,
        maxWidth: size.maxWidth,
        x: page.bounds.left + size.offsetX,
        y,
        width: size.width,
        height,
        radius: cardThemeFor(settings).imageRadius,
      });
      y += height + 34;
      hasContent = true;
      previousBlockType = "image";
      continue;
    }

    const style = styleForBlock(block.type, settings);
    const lineHeight = Math.ceil(style.size * style.lineHeight);
    const textWidth = style.quote ? contentWidth - 28 : contentWidth;
    const lines = wrapBlockLines(ctx, block, style, textWidth);
    let firstLine = true;

    for (const line of lines) {
      const topMargin = firstLine ? (hasContent && previousBlockType !== "spacer" ? style.marginTop : 0) : 0;
      ensureSpace(lineHeight, topMargin);
      page.items.push({
        type: "text",
        blockType: block.type,
        line,
        style,
        x: page.bounds.left + (style.quote ? 28 : 0),
        y,
        lineHeight,
      });
      y += lineHeight;
      firstLine = false;
      hasContent = true;
    }

    if (lines.length) {
      y += style.marginBottom;
      previousBlockType = block.type;
    }
  }

  finishPage();
  const result = pages.length ? pages : [createPage()];
  result.forEach((item, index) => {
    item.pageIndex = index;
    item.totalPages = result.length;
  });
  return result;
}

async function buildScrollPage(settings) {
  const measureCanvas = document.createElement("canvas");
  const ctx = measureCanvas.getContext("2d");
  const blocks = parseBlocks(settings.content, settings.images);
  const avatar = await loadImage(settings.avatar).catch(() => null);
  const badge = await loadImage(verifiedBadgeSrc).catch(() => null);
  const imageCache = {};
  const theme = cardThemeFor(settings);
  const showIdentity = true;
  const bounds = contentBoundsForPage(settings, showIdentity);
  const contentWidth = bounds.right - bounds.left;
  const viewportHeight = bounds.bottom - bounds.top;
  const page = {
    avatar,
    badge,
    settings,
    pageIndex: 0,
    totalPages: 1,
    showIdentity,
    showHeader: theme.identityPlacement === "top",
    showFooterAuthor: theme.identityPlacement === "bottom",
    items: [],
    bounds,
    scrollOffset: 0,
    scrollMax: 0,
  };
  let y = 0;
  let hasContent = false;
  let previousBlockType = null;

  for (const block of blocks) {
    if (block.type === "pagebreak") {
      continue;
    }

    if (block.type === "spacer") {
      y += blankLineGap(settings);
      previousBlockType = "spacer";
      continue;
    }

    if (block.type === "table") {
      const table = buildTableLayout(ctx, block, settings, contentWidth);
      y += hasContent && previousBlockType !== "spacer" ? 18 : 0;
      page.items.push({ type: "table", x: bounds.left, y, width: contentWidth, table });
      y += table.height + 18;
      hasContent = true;
      previousBlockType = "table";
      continue;
    }

    if (block.type === "image") {
      const data = settings.images[block.id];
      if (!data) continue;
      if (!imageCache[block.id]) {
        imageCache[block.id] = await loadImage(data.src).catch(() => null);
      }
      const img = imageCache[block.id];
      if (!img) continue;
      const sourceRect = getImageSourceRect(img, data.crop);
      const size = imageBlockSize(sourceRect, contentWidth, imageMaxHeightForLayout(data.layout, settings.imageHeight, 760), data.layout);
      y += hasContent && previousBlockType !== "spacer" ? 24 : 0;
      page.items.push({
        type: "image",
        imageId: block.id,
        sourceStart: block.sourceStart,
        sourceEnd: block.sourceEnd,
        occurrenceKey: block.occurrenceKey,
        image: img,
        sourceRect,
        baseWidth: size.baseWidth,
        maxWidth: size.maxWidth,
        x: bounds.left + size.offsetX,
        y,
        width: size.width,
        height: size.height,
        radius: theme.imageRadius,
      });
      y += size.height + 34;
      hasContent = true;
      previousBlockType = "image";
      continue;
    }

    const style = styleForBlock(block.type, settings);
    const lineHeight = Math.ceil(style.size * style.lineHeight);
    const textWidth = style.quote ? contentWidth - 28 : contentWidth;
    const lines = wrapBlockLines(ctx, block, style, textWidth);
    let firstLine = true;

    for (const line of lines) {
      y += firstLine && hasContent && previousBlockType !== "spacer" ? style.marginTop : 0;
      page.items.push({
        type: "text",
        blockType: block.type,
        line,
        style,
        x: bounds.left + (style.quote ? 28 : 0),
        y,
        lineHeight,
      });
      y += lineHeight;
      firstLine = false;
      hasContent = true;
    }

    if (lines.length) {
      y += style.marginBottom;
      previousBlockType = block.type;
    }
  }

  page.scrollMax = Math.max(0, y - viewportHeight);
  state.scrollMax = page.scrollMax;
  state.scrollOffset = clamp(state.scrollOffset, 0, page.scrollMax);
  page.scrollOffset = state.scrollOffset;
  return page;
}

function imageSourceFingerprint(source) {
  const value = String(source || "");
  return `${value.length}:${value.slice(0, 48)}:${value.slice(-48)}`;
}

function pageRenderSignature(page, scrollPage = false) {
  const { content, images, avatar, ...settings } = page.settings;
  const items = page.items.map((item) => {
    if (item.type === "image") {
      return {
        type: item.type,
        imageId: item.imageId,
        sourceStart: item.sourceStart,
        sourceEnd: item.sourceEnd,
        occurrenceKey: item.occurrenceKey,
        imageSource: imageSourceFingerprint(images?.[item.imageId]?.src),
        sourceRect: item.sourceRect,
        baseWidth: item.baseWidth,
        maxWidth: item.maxWidth,
        x: item.x,
        y: item.y,
        width: item.width,
        height: item.height,
        radius: item.radius,
      };
    }
    if (item.type === "table") {
      return {
        type: item.type,
        x: item.x,
        y: item.y,
        width: item.width,
        table: item.table,
      };
    }
    return {
      type: item.type,
      blockType: item.blockType,
      line: item.line,
      style: item.style,
      x: item.x,
      y: item.y,
      lineHeight: item.lineHeight,
    };
  });
  return JSON.stringify({
    scrollPage,
    scrollOffset: scrollPage ? page.scrollOffset : 0,
    showHeader: page.showHeader,
    showFooterAuthor: page.showFooterAuthor,
    pageIndex: page.pageIndex,
    totalPages: page.totalPages,
    bounds: page.bounds,
    avatar: imageSourceFingerprint(avatar),
    settings,
    items,
  });
}

function renderPage(page, index, total, previousCanvas = null) {
  const signature = pageRenderSignature(page, false);
  if (previousCanvas?._renderSignature === signature) {
    previousCanvas.dataset.page = String(index + 1);
    previousCanvas._page = page;
    return previousCanvas;
  }

  const canvas = document.createElement("canvas");
  canvas.width = CANVAS_WIDTH;
  canvas.height = CANVAS_HEIGHT;
  canvas.dataset.page = String(index + 1);
  canvas._page = page;
  canvas._scrollPage = false;
  canvas._renderSignature = signature;
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingQuality = "high";

  drawPageToContext(ctx, page, false);
  canvas._textHits = collectTextHits(ctx, page, false);
  canvas._imageHits = collectImageHits(page, false);
  return canvas;
}

function renderScrollPage(page, previousCanvas = null) {
  const signature = pageRenderSignature(page, true);
  if (previousCanvas?._renderSignature === signature) {
    previousCanvas._page = page;
    return previousCanvas;
  }

  const canvas = document.createElement("canvas");
  canvas.width = CANVAS_WIDTH;
  canvas.height = CANVAS_HEIGHT;
  canvas.dataset.page = "scroll";
  canvas._page = page;
  canvas._scrollPage = true;
  canvas._renderSignature = signature;
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingQuality = "high";

  drawPageToContext(ctx, page, true);
  canvas._textHits = collectTextHits(ctx, page, true);
  canvas._imageHits = collectImageHits(page, true);
  return canvas;
}

function createExportCanvas(sourceCanvas) {
  const scale = normalizeExportScale(state.exportScale);
  if (scale === 1) return sourceCanvas;

  const canvas = document.createElement("canvas");
  canvas.width = CANVAS_WIDTH * scale;
  canvas.height = CANVAS_HEIGHT * scale;
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.scale(scale, scale);
  drawPageToContext(ctx, sourceCanvas._page, sourceCanvas._scrollPage === true);
  return canvas;
}

function drawPageToContext(ctx, page, scrollPage = false) {
  drawBackground(ctx, page.settings);
  drawCardThemeChrome(ctx, page);
  if (page.showHeader !== false) {
    drawCardThemeHeader(ctx, page);
  }

  if (!scrollPage) {
    for (const item of page.items) {
      if (item.type === "image") drawImageBlock(ctx, item);
      if (item.type === "table") drawTableBlock(ctx, item, page.settings);
      if (item.type === "text") drawTextLine(ctx, item, page.settings);
    }
  } else {
    const { bounds } = page;
    ctx.save();
    ctx.beginPath();
    ctx.rect(bounds.left, bounds.top, bounds.right - bounds.left, bounds.bottom - bounds.top);
    ctx.clip();
    ctx.translate(0, bounds.top - page.scrollOffset);
    for (const item of page.items) {
      if (item.type === "image") drawImageBlock(ctx, item);
      if (item.type === "table") drawTableBlock(ctx, item, page.settings);
      if (item.type === "text") drawTextLine(ctx, item, page.settings);
    }
    ctx.restore();

    if (page.showHeader !== false) {
      ctx.strokeStyle = isDarkHexColor(page.settings.bgColor) ? "rgba(255,255,255,.12)" : "rgba(23,32,47,.06)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(bounds.left, bounds.top - 10);
      ctx.lineTo(bounds.right, bounds.top - 10);
      ctx.stroke();
    }
  }
  drawCardThemeFooter(ctx, page);
}

function collectTextHits(ctx, page, scrollPage = false) {
  const hits = [];
  const bounds = page.bounds || null;

  for (const item of page.items) {
    if (item.type !== "text") continue;
    let cursor = item.x;
    const y = scrollPage ? (bounds?.top || 0) + item.y - page.scrollOffset : item.y;
    if (scrollPage && bounds && (y + item.lineHeight < bounds.top || y > bounds.bottom)) {
      continue;
    }

    for (const token of item.line) {
      ctx.font = fontString(item.style, token);
      const width = ctx.measureText(token.text).width;
      if (!/^\s+$/.test(token.text) && Number.isFinite(token.sourceStart) && Number.isFinite(token.sourceEnd)) {
        const top = Math.max(y, scrollPage && bounds ? bounds.top : y);
        const bottom = Math.min(y + item.lineHeight, scrollPage && bounds ? bounds.bottom : y + item.lineHeight);
        hits.push({
          x: cursor,
          y: top,
          width,
          height: Math.max(0, bottom - top),
          sourceStart: token.sourceStart,
          sourceEnd: token.sourceEnd,
        });
      }
      cursor += width;
    }
  }

  return hits;
}

function collectImageHits(page, scrollPage = false) {
  const bounds = page.bounds || null;
  return page.items
    .filter((item) => item.type === "image" && item.imageId)
    .map((item) => {
      const y = scrollPage ? (bounds?.top || 0) + item.y - page.scrollOffset : item.y;
      const top = scrollPage && bounds ? Math.max(y, bounds.top) : y;
      const bottom = scrollPage && bounds ? Math.min(y + item.height, bounds.bottom) : y + item.height;
      return {
        imageId: item.imageId,
        sourceStart: item.sourceStart,
        sourceEnd: item.sourceEnd,
        occurrenceKey: item.occurrenceKey,
        x: item.x,
        y: top,
        width: item.width,
        height: Math.max(0, bottom - top),
        actualHeight: item.height,
        baseWidth: item.baseWidth || item.width,
        maxWidth: item.maxWidth || CARD_CONTENT_WIDTH,
      };
    })
    .filter((hit) => hit.height > 0 && hit.width > 0);
}

function drawBackground(ctx, settings) {
  const theme = cardThemeFor(settings);
  ctx.fillStyle = settings.bgColor;
  ctx.fillRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);

  if (theme.backgroundStyle === "paper-wash" || theme.backgroundStyle === "midnight-paper") {
    const dark = theme.backgroundStyle === "midnight-paper";
    const first = ctx.createRadialGradient(150, 110, 10, 150, 110, 520);
    first.addColorStop(0, colorWithAlpha(settings.accentColor, dark ? 0.13 : 0.085));
    first.addColorStop(1, colorWithAlpha(settings.accentColor, 0));
    ctx.fillStyle = first;
    ctx.fillRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);

    const secondary = normalizeHexColor(theme.secondaryColor, settings.accentColor);
    const second = ctx.createRadialGradient(735, 1010, 20, 735, 1010, 570);
    second.addColorStop(0, colorWithAlpha(secondary, dark ? 0.2 : 0.16));
    second.addColorStop(1, colorWithAlpha(secondary, 0));
    ctx.fillStyle = second;
    ctx.fillRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);

    drawDeterministicPaperGrain(ctx, settings.cardTheme, dark);
  } else if (theme.backgroundStyle === "swiss-grid") {
    ctx.fillStyle = settings.accentColor;
    ctx.fillRect(0, 0, CANVAS_WIDTH, 8);
    ctx.save();
    ctx.strokeStyle = colorWithAlpha(settings.textColor, 0.07);
    ctx.lineWidth = 1;
    [theme.geometry.sidePadding, CANVAS_WIDTH / 2, CANVAS_WIDTH - theme.geometry.sidePadding].forEach((x) => {
      ctx.beginPath();
      ctx.moveTo(x + 0.5, 8);
      ctx.lineTo(x + 0.5, CANVAS_HEIGHT);
      ctx.stroke();
    });
    ctx.restore();
  }
}

function colorWithAlpha(hex, alpha) {
  const normalized = normalizeHexColor(hex);
  const red = Number.parseInt(normalized.slice(1, 3), 16);
  const green = Number.parseInt(normalized.slice(3, 5), 16);
  const blue = Number.parseInt(normalized.slice(5, 7), 16);
  return `rgba(${red}, ${green}, ${blue}, ${clamp(Number(alpha) || 0, 0, 1)})`;
}

function drawDeterministicPaperGrain(ctx, seedText, dark = false) {
  let seed = 2166136261;
  for (const char of String(seedText || "paper")) {
    seed ^= char.codePointAt(0);
    seed = Math.imul(seed, 16777619);
  }
  const next = () => {
    seed += 0x6d2b79f5;
    let value = seed;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
  ctx.save();
  ctx.fillStyle = dark ? "rgba(255,244,219,.08)" : "rgba(28,24,18,.055)";
  for (let index = 0; index < 150; index += 1) {
    const size = next() > 0.84 ? 1.6 : 0.9;
    ctx.fillRect(Math.round(next() * CANVAS_WIDTH), Math.round(next() * CANVAS_HEIGHT), size, size);
  }
  ctx.restore();
}

function drawCardThemeChrome(ctx, page) {
  const theme = cardThemeFor(page.settings);
  if (!theme.openingQuote) return;
  ctx.save();
  ctx.globalAlpha = isDarkHexColor(page.settings.bgColor) ? 0.34 : 0.22;
  ctx.fillStyle = page.settings.accentColor;
  ctx.font = `700 94px ${FONT_STACKS["en-serif"]}`;
  ctx.textBaseline = "alphabetic";
  ctx.fillText("“", theme.geometry.sidePadding - 4, 91);
  ctx.restore();
}

function drawCardThemeHeader(ctx, page) {
  drawHeader(ctx, page.settings, page.avatar, page.badge);
}

function drawHeader(ctx, settings, avatar, badge) {
  const theme = cardThemeFor(settings);
  const identity = theme.identity;
  const x = identity.x;
  const y = identity.y;
  const size = identity.avatarSize;
  const darkCard = isDarkHexColor(settings.bgColor);

  ctx.save();
  ctx.beginPath();
  ctx.arc(x + size / 2, y + size / 2, size / 2, 0, Math.PI * 2);
  ctx.clip();
  if (avatar) {
    drawSourceCoverImage(ctx, avatar, getImageSourceRect(avatar, settings.avatarCrop), x, y, size, size);
  } else {
    ctx.fillStyle = "#d8edc0";
    ctx.fillRect(x, y, size, size);
  }
  ctx.restore();

  ctx.lineWidth = 2;
  ctx.strokeStyle = darkCard ? "rgba(255,255,255,.2)" : "rgba(32,41,56,.12)";
  ctx.beginPath();
  ctx.arc(x + size / 2, y + size / 2, size / 2, 0, Math.PI * 2);
  ctx.stroke();

  const textX = x + size + (size >= 80 ? 28 : 18);
  const nameBaseline = y + Math.round(size * (size >= 80 ? 0.42 : 0.43));
  const handleBaseline = y + Math.round(size * (size >= 80 ? 0.91 : 0.86));
  ctx.fillStyle = identity.accentName ? settings.accentColor : settings.textColor;
  ctx.font = `650 ${identity.nameSize}px ${fontFamilyForText(settings.displayName, settings)}`;
  ctx.textBaseline = "alphabetic";
  const name = clampText(ctx, settings.displayName, size >= 80 ? 430 : 360);
  ctx.fillText(name, textX, nameBaseline);

  const nameWidth = ctx.measureText(name).width;
  drawVerifiedBadge(
    ctx,
    badge,
    textX + nameWidth + (size >= 80 ? 24 : 18),
    nameBaseline - (size >= 80 ? 13 : 8),
    size >= 80 ? 34 : 24,
  );

  ctx.fillStyle = darkCard ? "rgba(255,255,255,.72)" : "#6f7785";
  ctx.font = `400 ${identity.handleSize}px ${fontFamilyForText(settings.handle, settings)}`;
  ctx.fillText(clampText(ctx, settings.handle, size >= 80 ? 480 : 390), textX, handleBaseline);

  if (normalizeCardTheme(settings.cardTheme) === "social-clean") {
    ctx.fillStyle = darkCard ? "rgba(255,255,255,.5)" : "#9aa2af";
    for (let i = 0; i < 3; i += 1) {
      ctx.beginPath();
      ctx.arc(769 + i * 16, 79, 5, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

function isDarkHexColor(hex) {
  const match = String(hex || "").match(/^#?([0-9a-fA-F]{6})$/);
  if (!match) return false;
  const value = match[1];
  const red = Number.parseInt(value.slice(0, 2), 16);
  const green = Number.parseInt(value.slice(2, 4), 16);
  const blue = Number.parseInt(value.slice(4, 6), 16);
  return (red * 299 + green * 587 + blue * 114) / 1000 < 128;
}

function drawVerifiedBadge(ctx, badge, x, y, size = 34) {
  ctx.save();
  if (badge) {
    ctx.drawImage(badge, x - size / 2, y - size / 2, size, size);
  } else {
    const scale = size / 34;
    ctx.fillStyle = "#1d9bf0";
    ctx.beginPath();
    ctx.arc(x, y, 16 * scale, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = 4.7 * scale;
    ctx.lineCap = "square";
    ctx.lineJoin = "miter";
    ctx.beginPath();
    ctx.moveTo(x - 8.4 * scale, y - 0.7 * scale);
    ctx.lineTo(x - 2.2 * scale, y + 5.8 * scale);
    ctx.lineTo(x + 9.6 * scale, y - 8 * scale);
    ctx.stroke();
  }
  ctx.restore();
}

function drawCardThemeFooter(ctx, page) {
  const { settings } = page;
  const theme = cardThemeFor(settings);
  const darkCard = isDarkHexColor(settings.bgColor);
  const subtle = darkCard ? "rgba(255,255,255,.42)" : "rgba(42,45,52,.38)";
  const faint = darkCard ? "rgba(255,255,255,.16)" : "rgba(42,45,52,.12)";
  const pageLabel = `${String((page.pageIndex || 0) + 1).padStart(2, "0")} / ${String(page.totalPages || 1).padStart(2, "0")}`;
  ctx.save();

  if (theme.footer === "hairline") {
    ctx.strokeStyle = faint;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(theme.geometry.sidePadding, 1103);
    ctx.lineTo(CANVAS_WIDTH - theme.geometry.sidePadding, 1103);
    ctx.stroke();
  } else if (theme.footer === "double-line") {
    ctx.strokeStyle = faint;
    ctx.lineWidth = 1;
    [1092, 1098].forEach((y) => {
      ctx.beginPath();
      ctx.moveTo(theme.geometry.sidePadding, y);
      ctx.lineTo(CANVAS_WIDTH - theme.geometry.sidePadding, y);
      ctx.stroke();
    });
  }

  if (page.showFooterAuthor) {
    const x = theme.identity.x;
    const y = theme.identity.y;
    const size = theme.identity.avatarSize;
    ctx.save();
    ctx.beginPath();
    ctx.arc(x + size / 2, y + size / 2, size / 2, 0, Math.PI * 2);
    ctx.clip();
    if (page.avatar) {
      drawSourceCoverImage(ctx, page.avatar, getImageSourceRect(page.avatar, settings.avatarCrop), x, y, size, size);
    } else {
      ctx.fillStyle = "#d8edc0";
      ctx.fillRect(x, y, size, size);
    }
    ctx.restore();
    ctx.fillStyle = settings.textColor;
    ctx.font = `650 ${theme.identity.nameSize}px ${fontFamilyForText(settings.displayName, settings)}`;
    ctx.textBaseline = "alphabetic";
    const name = clampText(ctx, settings.displayName, 290);
    ctx.fillText(name, x + size + 13, y + 24);
    const nameWidth = ctx.measureText(name).width;
    ctx.fillStyle = subtle;
    ctx.font = `400 ${theme.identity.handleSize}px ${fontFamilyForText(settings.handle, settings)}`;
    ctx.fillText(clampText(ctx, settings.handle, 210), x + size + nameWidth + 25, y + 24);
  }

  ctx.fillStyle = subtle;
  ctx.textBaseline = "alphabetic";
  ctx.font = `600 17px ${FONT_STACKS["en-system"]}`;
  if (theme.pageNumber === "top-right") {
    ctx.textAlign = "right";
    ctx.fillText(pageLabel, CANVAS_WIDTH - theme.geometry.sidePadding, 70);
  } else if (theme.pageNumber === "bottom-center") {
    ctx.textAlign = "center";
    ctx.fillText(pageLabel, CANVAS_WIDTH / 2, 1103);
  } else if (theme.pageNumber === "bottom-right") {
    ctx.textAlign = "right";
    ctx.fillText(pageLabel, CANVAS_WIDTH - theme.geometry.sidePadding, theme.footer === "double-line" ? 1124 : 1103);
  }
  ctx.restore();
}

function drawImageBlock(ctx, item) {
  ctx.save();
  roundedRect(ctx, item.x, item.y, item.width, item.height, item.radius);
  ctx.clip();
  drawSourceCoverImage(ctx, item.image, item.sourceRect, item.x, item.y, item.width, item.height);
  ctx.restore();
}

function drawTableBlock(ctx, item, settings) {
  const { table } = item;
  let y = item.y;
  const darkCard = isDarkHexColor(settings.bgColor);
  ctx.save();
  for (const [rowIndex, row] of table.rows.entries()) {
    if (rowIndex === 0) {
      ctx.fillStyle = darkCard ? "rgba(255,255,255,.16)" : "rgba(43,127,216,.13)";
      ctx.fillRect(item.x, y, item.width, row.height);
    }
    for (let column = 0; column < table.columns; column += 1) {
      const x = item.x + column * table.cellWidth;
      ctx.strokeStyle = darkCard ? "rgba(255,255,255,.24)" : "rgba(32,41,56,.18)";
      ctx.lineWidth = 1;
      ctx.strokeRect(x + 0.5, y + 0.5, table.cellWidth, row.height);
      let lineY = y + 10;
      for (const line of row.cells[column]) {
        drawTextLine(ctx, {
          style: row.style,
          line,
          x: x + 10,
          y: lineY,
          lineHeight: row.lineHeight,
        }, settings);
        lineY += row.lineHeight;
      }
    }
    y += row.height;
  }
  ctx.restore();
}

function drawTextLine(ctx, item, settings) {
  const { style, line, x, y, lineHeight } = item;
  const theme = cardThemeFor(settings);
  if (style.quote) {
    if (theme.emphasis === "editorial") {
      ctx.save();
      ctx.globalAlpha = 0.32;
      ctx.fillStyle = settings.accentColor;
      ctx.font = `700 ${Math.max(34, Math.round(lineHeight * 0.9))}px ${FONT_STACKS["en-serif"]}`;
      ctx.fillText("“", x - 32, y + Math.round(lineHeight * 0.72));
      ctx.restore();
    } else {
      ctx.fillStyle = settings.accentColor;
      roundedRect(ctx, x - 28, y + 7, 7, lineHeight - 13, 4);
      ctx.fill();
    }
  }

  let cursor = x;
  const baseline = y + Math.round(lineHeight * 0.75);
  for (const token of line) {
    ctx.font = fontString(style, token);
    const width = ctx.measureText(token.text).width;
    if (token.bgColor) {
      if (theme.emphasis === "marker") {
        ctx.save();
        ctx.globalAlpha = 0.72;
        ctx.fillStyle = token.bgColor;
        ctx.beginPath();
        const markerTop = y + Math.round(lineHeight * 0.48);
        const markerBottom = y + Math.round(lineHeight * 0.86);
        ctx.moveTo(cursor - 4, markerTop + 2);
        ctx.lineTo(cursor + width + 5, markerTop);
        ctx.lineTo(cursor + width + 3, markerBottom - 2);
        ctx.lineTo(cursor - 2, markerBottom);
        ctx.closePath();
        ctx.fill();
        ctx.restore();
      } else if (["accent-underline", "bold-line", "editorial", "swiss"].includes(theme.emphasis)) {
        ctx.save();
        ctx.globalAlpha = theme.emphasis === "bold-line" ? 0.72 : 0.52;
        ctx.fillStyle = token.bgColor;
        const underlineHeight = theme.emphasis === "editorial" ? 3 : 5;
        ctx.fillRect(cursor, y + Math.round(lineHeight * 0.82), width, underlineHeight);
        ctx.restore();
      } else {
        ctx.fillStyle = token.bgColor;
        roundedRect(ctx, cursor - 3, y + Math.round(lineHeight * 0.14), width + 6, Math.round(lineHeight * 0.72), 7);
        ctx.fill();
      }
    }
    ctx.fillStyle = token.color || style.color;
    ctx.fillText(token.text, cursor, baseline);
    cursor += width;
  }
}

function drawCoverImage(ctx, image, x, y, width, height) {
  const scale = Math.max(width / image.width, height / image.height);
  const drawWidth = image.width * scale;
  const drawHeight = image.height * scale;
  const dx = x + (width - drawWidth) / 2;
  const dy = y + (height - drawHeight) / 2;
  ctx.drawImage(image, dx, dy, drawWidth, drawHeight);
}

function drawSourceImage(ctx, image, sourceRect, x, y, width, height) {
  ctx.drawImage(image, sourceRect.x, sourceRect.y, sourceRect.width, sourceRect.height, x, y, width, height);
}

function drawSourceCoverImage(ctx, image, sourceRect, x, y, width, height) {
  const sourceAspect = sourceRect.width / sourceRect.height;
  const destAspect = width / height;
  let sx = sourceRect.x;
  let sy = sourceRect.y;
  let sw = sourceRect.width;
  let sh = sourceRect.height;

  if (sourceAspect > destAspect) {
    sw = sourceRect.height * destAspect;
    sx = sourceRect.x + (sourceRect.width - sw) / 2;
  } else {
    sh = sourceRect.width / destAspect;
    sy = sourceRect.y + (sourceRect.height - sh) / 2;
  }
  ctx.drawImage(image, sx, sy, sw, sh, x, y, width, height);
}

function roundedRect(ctx, x, y, width, height, radius) {
  const r = Math.min(radius, width / 2, height / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + width, y, x + width, y + height, r);
  ctx.arcTo(x + width, y + height, x, y + height, r);
  ctx.arcTo(x, y + height, x, y, r);
  ctx.arcTo(x, y, x + width, y, r);
  ctx.closePath();
}

function clampText(ctx, text, maxWidth) {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let result = text;
  while (result.length > 1 && ctx.measureText(`${result}...`).width > maxWidth) {
    result = result.slice(0, -1);
  }
  return `${result}...`;
}

function renderArticlePreview(settings) {
  state.canvases = [];
  state.scrollOffset = 0;
  state.scrollMax = 0;
  els.pages.innerHTML = "";
  els.pages.className = "pages article-mode";
  clearPageDock();
  if (els.articleSettings) els.articleSettings.hidden = !articleSettingsOpen;

  const article = document.createElement("article");
  article.className = `article-preview article-theme-${settings.articleTheme} article-font-${settings.articleFont} article-size-${settings.articleSize}`;
  article.style.setProperty("--article-accent", settings.articleColor);
  article.innerHTML = markdownToArticleHtml(settings.content, settings.images);
  els.pages.append(article);

  const wordCount = settings.content.replace(/\s/g, "").length;
  els.pageCount.textContent = "长文";
  els.status.textContent = `已生成长文预览，约 ${wordCount} 字`;
  if (window.lucide) window.lucide.createIcons();
}

function markdownToArticleHtml(markdown, images = {}) {
  const lines = String(markdown || "").replace(/\r\n/g, "\n").split("\n");
  const imageLookup = buildImageReferenceLookup(images);
  const html = [];
  let paragraph = [];
  let list = [];
  let code = [];
  let inCode = false;

  const flushParagraph = () => {
    if (!paragraph.length) return;
    html.push(`<p>${renderArticleInline(paragraph.join(" "))}</p>`);
    paragraph = [];
  };
  const flushList = () => {
    if (!list.length) return;
    html.push(`<ul>${list.map((item) => `<li>${renderArticleInline(item)}</li>`).join("")}</ul>`);
    list = [];
  };
  const flushCode = () => {
    if (!code.length) return;
    html.push(`<pre><code>${escapeHtml(code.join("\n"))}</code></pre>`);
    code = [];
  };

  const flushTable = (header, rows) => {
    html.push(`<div class="article-table-wrap"><table><thead><tr>${header.map((cell) => `<th>${renderArticleInline(cell)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${header.map((_, index) => `<td>${renderArticleInline(row[index] || "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const trimmed = line.trim();
    if (trimmed.startsWith("```")) {
      if (inCode) {
        flushCode();
        inCode = false;
      } else {
        flushParagraph();
        flushList();
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      code.push(line);
      continue;
    }
    if (!trimmed) {
      flushParagraph();
      flushList();
      continue;
    }

    if (isMarkdownTableHeader(trimmed, lines[index + 1])) {
      flushParagraph();
      flushList();
      const header = splitMarkdownTableRow(trimmed);
      const rows = [];
      let rowIndex = index + 2;
      while (rowIndex < lines.length) {
        const row = splitMarkdownTableRow(lines[rowIndex].trim());
        if (!row) break;
        rows.push(row);
        rowIndex += 1;
      }
      flushTable(header, rows);
      index = rowIndex - 1;
      continue;
    }

    const imageId = resolveMarkdownImageBlock(trimmed, imageLookup);
    if (isMarkdownImageBlock(trimmed)) {
      flushParagraph();
      flushList();
      const image = images[imageId];
      if (image?.src) html.push(`<figure><img src="${escapeAttribute(image.src)}" alt="${escapeAttribute(image.name || "图片")}" /></figure>`);
      continue;
    }

    const heading = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      flushList();
      const level = Math.min(3, heading[1].length);
      html.push(`<h${level}>${renderArticleInline(heading[2])}</h${level}>`);
      continue;
    }

    if (trimmed.startsWith("> ")) {
      flushParagraph();
      flushList();
      html.push(`<blockquote>${renderArticleInline(trimmed.slice(2))}</blockquote>`);
      continue;
    }

    const listMatch = trimmed.match(/^[-*+]\s+(.+)$/);
    if (listMatch) {
      flushParagraph();
      list.push(listMatch[1]);
      continue;
    }

    paragraph.push(trimmed);
  }

  flushParagraph();
  flushList();
  flushCode();
  return html.length ? html.join("") : '<p class="article-empty">在左侧输入 Markdown，右侧会生成长文预览。</p>';
}

function renderArticleInline(text) {
  return parseInline(String(text || ""))
    .map((token) => {
      let inner = escapeHtml(token.text).replace(/`([^`]+)`/g, "<code>$1</code>");
      if (token.bold) inner = `<strong>${inner}</strong>`;
      if (token.italic) inner = `<em>${inner}</em>`;

      const styles = [];
      if (token.color) styles.push(`color: ${token.color}`);
      if (token.bgColor) {
        styles.push(`background-color: ${token.bgColor}`);
        styles.push("border-radius: 4px");
        styles.push("box-decoration-break: clone");
        styles.push("-webkit-box-decoration-break: clone");
        styles.push("padding: 0 3px");
      }

      return styles.length ? `<span style="${escapeAttribute(styles.join("; "))}">${inner}</span>` : inner;
    })
    .join("");
}

function escapeAttribute(value) {
  return escapeHtml(value).replace(/`/g, "&#96;");
}

async function render({ persist = true } = {}) {
  const generation = ++renderGeneration;
  const settings = readForm();
  const previousCanvases = state.canvases;
  if (persist) scheduleStateSave();
  updateAppMode();
  updateArticleControls();
  if (state.appMode === "article") {
    if (generation !== renderGeneration) return;
    renderArticlePreview(settings);
    return;
  }
  if (state.mode === "scroll") {
    const page = await buildScrollPage(settings);
    if (generation !== renderGeneration) return;
    state.canvases = [renderScrollPage(page, previousCanvases[0])];
  } else {
    const pages = await buildPages(settings);
    if (generation !== renderGeneration) return;
    state.canvases = pages.map((page, index) => renderPage(page, index, pages.length, previousCanvases[index]));
    state.scrollOffset = 0;
    state.scrollMax = 0;
  }
  drawPreview(state.canvases);
}

function drawPreview(canvases) {
  previewInlineEditor = null;
  els.pages.innerHTML = "";
  els.pages.className = "pages";
  els.pages.classList.toggle("scroll-mode", state.mode === "scroll");
  els.articleSettings.hidden = true;
  els.scrollMode?.classList.toggle("active", state.mode === "scroll");
  if (!canvases.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "暂无内容";
    els.pages.append(empty);
  }

  canvases.forEach((canvas, index) => {
    const shell = document.createElement("article");
    shell.className = "page-shell";
    shell.id = `preview-page-${index + 1}`;
    shell.dataset.pageIndex = String(index);
    const frame = document.createElement("div");
    frame.className = "page-frame";
    if (state.mode === "scroll") {
      frame.classList.add("scrollable");
      attachScrollFrameHandlers(frame);
    }
    frame.append(canvas);
    frame.append(createImageEditLayer(canvas));
    frame.append(createTextHitLayer(canvas));

    const actions = document.createElement("div");
    actions.className = "page-actions";
    const label = document.createElement("span");
    label.textContent = state.mode === "scroll" ? "滑动截图" : `图片 ${String(index + 1).padStart(2, "0")}`;
    const button = document.createElement("button");
    button.type = "button";
    button.title = "下载单张";
    button.setAttribute("aria-label", `下载第 ${index + 1} 张`);
    button.innerHTML = '<i data-lucide="download"></i>';
    const filename = state.mode === "scroll" ? "layout-scroll-shot.png" : `layout-page-${String(index + 1).padStart(2, "0")}.png`;
    button.addEventListener("click", () => downloadCanvas(canvas, filename));
    actions.append(label, button);
    shell.append(frame, actions);
    els.pages.append(shell);
  });

  renderPageDock(canvases);
  updatePreviewCardView();

  els.pageCount.textContent = state.mode === "scroll" ? "滑动截图模式" : `${canvases.length} 张图片`;
  els.status.textContent =
    state.mode === "scroll"
      ? `滑动截图模式：预览 ${CANVAS_WIDTH}x${CANVAS_HEIGHT}，导出 ${CANVAS_WIDTH * state.exportScale}x${CANVAS_HEIGHT * state.exportScale}`
      : `已生成 ${canvases.length} 张；预览 ${CANVAS_WIDTH}x${CANVAS_HEIGHT}，导出 ${CANVAS_WIDTH * state.exportScale}x${CANVAS_HEIGHT * state.exportScale}`;
  if (window.lucide) window.lucide.createIcons();
}

function clearPageDock() {
  if (!els.pageDock || !els.pageDockTrack || !els.pageDockStatus) return;
  els.pageDock.hidden = true;
  els.pageDockTrack.innerHTML = "";
  els.pageDockStatus.textContent = "0 / 0";
  els.pages.querySelectorAll(".page-shell").forEach((shell) => {
    shell.removeAttribute("role");
    shell.removeAttribute("aria-labelledby");
  });
}

function renderPageDock(canvases) {
  if (!els.pageDock || !els.pageDockTrack || !els.pageDockStatus) return;
  els.pageDockTrack.innerHTML = "";
  const dockCanvases = state.mode === "auto" ? canvases : [];
  if (!dockCanvases.length) {
    clearPageDock();
    return;
  }

  activePreviewPageIndex = clamp(activePreviewPageIndex, 0, dockCanvases.length - 1);
  els.pageDock.hidden = false;
  dockCanvases.forEach((canvas, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "page-dock-button";
    button.id = `page-dock-tab-${index + 1}`;
    button.dataset.pageIndex = String(index);
    button.setAttribute("role", "tab");
    button.setAttribute("aria-controls", `preview-page-${index + 1}`);
    button.setAttribute("aria-label", `切换到第 ${index + 1} 张卡片`);
    button.title = `第 ${index + 1} 张卡片`;

    const number = document.createElement("span");
    number.textContent = String(index + 1).padStart(2, "0");
    button.append(number);
    button.addEventListener("click", () => setActivePreviewPage(index));
    button.addEventListener("keydown", handlePageDockKeydown);
    els.pageDockTrack.append(button);
    const shell = els.pages.querySelector(`#preview-page-${index + 1}`);
    if (shell) {
      shell.setAttribute("role", "tabpanel");
      shell.setAttribute("aria-labelledby", button.id);
    }
  });
}

function applyActivePreviewPage({ focus = false } = {}) {
  const shells = Array.from(els.pages.querySelectorAll(".page-shell"));
  const buttons = els.pageDockTrack ? Array.from(els.pageDockTrack.querySelectorAll(".page-dock-button")) : [];
  if (!shells.length) return;
  activePreviewPageIndex = clamp(activePreviewPageIndex, 0, shells.length - 1);
  const compact = els.previewPanel?.dataset.cardView === "dock";

  shells.forEach((shell, index) => {
    const active = index === activePreviewPageIndex;
    shell.classList.toggle("is-active", active);
    if (compact) {
      shell.setAttribute("role", "tabpanel");
      shell.setAttribute("aria-labelledby", `page-dock-tab-${index + 1}`);
      shell.setAttribute("aria-hidden", String(!active));
    } else {
      shell.removeAttribute("role");
      shell.removeAttribute("aria-labelledby");
      shell.removeAttribute("aria-hidden");
    }
  });
  buttons.forEach((button, index) => {
    const active = index === activePreviewPageIndex;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  if (els.pageDockStatus) {
    els.pageDockStatus.textContent = `${activePreviewPageIndex + 1} / ${shells.length}`;
  }
  const dockActive = els.previewPanel?.dataset.cardView === "dock";
  const hasSiblings = shells.length > 1;
  [els.stageNavPrev, els.stageNavNext].forEach((navButton) => {
    if (navButton) navButton.hidden = !dockActive || !hasSiblings;
  });
  if (els.stageNavPrev) els.stageNavPrev.disabled = activePreviewPageIndex <= 0;
  if (els.stageNavNext) els.stageNavNext.disabled = activePreviewPageIndex >= shells.length - 1;
  const activeButton = buttons[activePreviewPageIndex];
  if (activeButton) {
    activeButton.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
      block: "nearest",
      inline: "center",
    });
    if (focus) activeButton.focus();
  }
}

function updatePreviewCardView() {
  if (!els.previewPanel) return;
  const supportsCardViews = state.appMode === "cards" && state.mode === "auto";
  const cardView = supportsCardViews ? previewViewMode : "grid";
  els.previewPanel.dataset.cardView = cardView;
  if (els.previewFooter) els.previewFooter.hidden = !supportsCardViews;
  if (els.previewViewSwitch) els.previewViewSwitch.hidden = !supportsCardViews;
  if (els.pageDock) {
    const hasDockPages = Boolean(els.pageDockTrack?.children.length);
    els.pageDock.hidden = cardView !== "dock" || !hasDockPages;
  }
  syncPreviewViewControls();
  applyActivePreviewPage();
}

function setActivePreviewPage(index, { focus = false } = {}) {
  if (!Number.isInteger(index)) return;
  activePreviewPageIndex = index;
  applyActivePreviewPage({ focus });
}

function movePreviewPage(delta, { focus = false } = {}) {
  const total = els.pages ? els.pages.querySelectorAll(".page-shell").length : 0;
  if (total < 2) return;
  const next = clamp(activePreviewPageIndex + delta, 0, total - 1);
  if (next === activePreviewPageIndex) return;
  setActivePreviewPage(next, { focus });
}

function handlePageDockKeydown(event) {
  const buttons = els.pageDockTrack ? Array.from(els.pageDockTrack.querySelectorAll(".page-dock-button")) : [];
  if (!buttons.length) return;
  const current = Number(event.currentTarget.dataset.pageIndex);
  let next = current;
  if (event.key === "ArrowLeft") next = Math.max(0, current - 1);
  else if (event.key === "ArrowRight") next = Math.min(buttons.length - 1, current + 1);
  else if (event.key === "Home") next = 0;
  else if (event.key === "End") next = buttons.length - 1;
  else return;
  event.preventDefault();
  setActivePreviewPage(next, { focus: true });
}

function createImageEditLayer(canvas) {
  const layer = document.createElement("div");
  layer.className = "preview-image-edit-layer";

  for (const hit of canvas._imageHits || []) {
    const box = document.createElement("div");
    box.className = "preview-image-box";
    box.dataset.imageId = hit.imageId;
    box.dataset.sourceStart = String(hit.sourceStart);
    box.dataset.sourceEnd = String(hit.sourceEnd);
    box.dataset.occurrenceKey = hit.occurrenceKey || `${hit.imageId}:${hit.sourceStart}`;
    box.dataset.baseWidth = String(hit.baseWidth || hit.width);
    box.dataset.maxWidth = String(hit.maxWidth || CARD_CONTENT_WIDTH);
    box.dataset.actualHeight = String(hit.actualHeight || hit.height);
    box.tabIndex = 0;
    box.setAttribute("role", "group");
    box.setAttribute("aria-label", `图片 ${state.images[hit.imageId]?.name || hit.imageId}；点击定位源码，可拖动调整顺序，Alt 加上下方向键也可移动`);
    box.title = "点击定位左侧图片标记；悬浮后可移动、删除或调整大小";
    if (previewEditorPin?.start === hit.sourceStart && previewEditorPin?.end === hit.sourceEnd) {
      box.classList.add("is-source-linked");
    }
    applyImageBoxStyle(box, hit);

    const dragHandle = document.createElement("button");
    dragHandle.type = "button";
    dragHandle.className = "preview-image-drag-handle";
    dragHandle.title = "拖动调整图片上下顺序";
    dragHandle.setAttribute("aria-label", "拖动调整图片上下顺序");
    dragHandle.innerHTML = '<i data-lucide="grip-vertical"></i>';
    dragHandle.addEventListener("pointerdown", startPreviewImageReorder);

    const orderBar = document.createElement("div");
    orderBar.className = "preview-image-order";
    [
      [-1, "arrow-up", "上移一项"],
      [1, "arrow-down", "下移一项"],
    ].forEach(([direction, icon, label]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.direction = String(direction);
      button.title = label;
      button.setAttribute("aria-label", label);
      button.innerHTML = `<i data-lucide="${icon}"></i>`;
      button.addEventListener("click", movePreviewImageByStep);
      orderBar.append(button);
    });

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "preview-image-delete";
    deleteButton.title = "从正文删除（资源库仍保留）";
    deleteButton.setAttribute("aria-label", "从正文删除这张图片，资源库仍保留");
    deleteButton.innerHTML = '<i data-lucide="trash-2"></i>';
    deleteButton.disabled = isBuiltInProjectId(state.currentProjectId);
    deleteButton.addEventListener("click", deletePreviewImageReference);
    orderBar.append(deleteButton);

    const alignBar = document.createElement("div");
    alignBar.className = "preview-image-align";
    [
      ["left", "align-start-horizontal", "左对齐"],
      ["center", "align-center-horizontal", "居中"],
      ["right", "align-end-horizontal", "右对齐"],
    ].forEach(([align, icon, label]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.align = align;
      button.title = label;
      button.setAttribute("aria-label", label);
      button.innerHTML = `<i data-lucide="${icon}"></i>`;
      button.addEventListener("click", setPreviewImageAlign);
      alignBar.append(button);
    });

    const resize = document.createElement("span");
    resize.className = "preview-image-resize";
    resize.dataset.action = "resize";
    resize.addEventListener("pointerdown", startPreviewImageResize);

    box.addEventListener("keydown", handlePreviewImageOrderKeydown);
    box.addEventListener("click", handlePreviewImageTarget);
    box.append(dragHandle, orderBar, alignBar, resize);
    layer.append(box);
  }

  return layer;
}

function applyImageBoxStyle(box, hit) {
  box.style.left = `${(hit.x / CANVAS_WIDTH) * 100}%`;
  box.style.top = `${(hit.y / CANVAS_HEIGHT) * 100}%`;
  box.style.width = `${(hit.width / CANVAS_WIDTH) * 100}%`;
  box.style.height = `${(hit.height / CANVAS_HEIGHT) * 100}%`;
}

function createTextHitLayer(canvas) {
  const layer = document.createElement("div");
  layer.className = "preview-hit-layer";

  for (const hit of canvas._textHits || []) {
    if (hit.width <= 0 || hit.height <= 0) continue;
    const target = document.createElement("button");
    target.type = "button";
    target.className = "preview-text-hit";
    target.style.left = `${(hit.x / CANVAS_WIDTH) * 100}%`;
    target.style.top = `${(hit.y / CANVAS_HEIGHT) * 100}%`;
    target.style.width = `${(hit.width / CANVAS_WIDTH) * 100}%`;
    target.style.height = `${(hit.height / CANVAS_HEIGHT) * 100}%`;
    target.dataset.start = String(hit.sourceStart);
    target.dataset.end = String(hit.sourceEnd);
    target.title = "点击定位源码并直接编辑卡片文字";
    if (previewEditorPin?.start === hit.sourceStart && previewEditorPin?.end === hit.sourceEnd) {
      target.classList.add("is-pinned");
      target.setAttribute("aria-pressed", "true");
    } else {
      target.setAttribute("aria-pressed", "false");
    }
    target.addEventListener("pointerenter", handlePreviewTextTarget);
    target.addEventListener("click", handlePreviewTextTarget);
    layer.append(target);
  }

  return layer;
}

function handlePreviewTextTarget(event) {
  const start = Number(event.currentTarget.dataset.start);
  const end = Number(event.currentTarget.dataset.end);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start >= end) return;
  if (event.type === "pointerenter" && previewEditorPin) return;
  const shouldPin = event.type === "click";
  if (shouldPin && previewInlineEditor?.target === event.currentTarget) {
    previewInlineEditor.editable.focus({ preventScroll: true });
    return;
  }
  if (shouldPin && previewInlineEditor?.dirty) {
    els.status.textContent = "当前卡片文字尚未完成，请先点“完成”或按 Esc 取消";
    previewInlineEditor.editable.focus({ preventScroll: true });
    return;
  }
  focusEditorRange(start, end, shouldPin);
  if (shouldPin) openPreviewInlineEditor(event.currentTarget, start, end);
}

function focusEditorRange(start, end, pin = false) {
  if (pin) {
    previewEditorPin = { start, end };
    document.querySelectorAll(".preview-text-hit").forEach((target) => {
      const matches = Number(target.dataset.start) === start && Number(target.dataset.end) === end;
      target.classList.toggle("is-pinned", matches);
      target.setAttribute("aria-pressed", String(matches));
    });
    document.querySelectorAll(".preview-image-box").forEach((target) => {
      const matches = Number(target.dataset.sourceStart) === start && Number(target.dataset.sourceEnd) === end;
      target.classList.toggle("is-source-linked", matches);
    });
  }
  els.content.focus({ preventScroll: true });
  els.content.setSelectionRange(start, end);
  scrollTextareaToRange(start);
  if (pin) els.status.textContent = "已锁定编辑位置；点击其他预览文字可切换，点击编辑框可解除";
}

function clearPreviewEditorPin() {
  if (!previewEditorPin) return;
  previewEditorPin = null;
  document.querySelectorAll(".preview-text-hit.is-pinned").forEach((target) => {
    target.classList.remove("is-pinned");
    target.setAttribute("aria-pressed", "false");
  });
  document.querySelectorAll(".preview-image-box.is-source-linked").forEach((target) => {
    target.classList.remove("is-source-linked");
  });
}

function scrollTextareaToRange(index) {
  const textarea = els.content;
  const computed = getComputedStyle(textarea);
  const mirror = document.createElement("div");
  const copiedProperties = [
    "boxSizing", "fontFamily", "fontSize", "fontStyle", "fontWeight", "fontVariant",
    "letterSpacing", "lineHeight", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
    "borderTopWidth", "borderRightWidth", "borderBottomWidth", "borderLeftWidth",
    "wordBreak", "overflowWrap", "textTransform", "textIndent", "tabSize",
  ];
  mirror.className = "textarea-scroll-mirror";
  mirror.style.width = `${textarea.offsetWidth}px`;
  copiedProperties.forEach((property) => {
    mirror.style[property] = computed[property];
  });
  mirror.append(document.createTextNode(textarea.value.slice(0, index)));
  const marker = document.createElement("span");
  marker.textContent = textarea.value.slice(index, index + 1) || "\u200b";
  mirror.append(marker);
  document.body.append(mirror);
  const targetTop = marker.offsetTop - textarea.clientHeight * 0.38;
  const maxScrollTop = Math.max(0, textarea.scrollHeight - textarea.clientHeight);
  textarea.scrollTop = clamp(targetTop, 0, maxScrollTop);
  mirror.remove();
}

function handlePreviewImageTarget(event) {
  if (event.target.closest("button, [data-action='resize']")) return;
  if (previewInlineEditor?.dirty) {
    els.status.textContent = "当前卡片文字尚未完成，请先点“完成”或按 Esc 取消";
    previewInlineEditor.editable.focus({ preventScroll: true });
    return;
  }
  const box = event.currentTarget;
  const start = Number(box.dataset.sourceStart);
  const end = Number(box.dataset.sourceEnd);
  if (!Number.isFinite(start) || !Number.isFinite(end)) return;
  focusEditorRange(start, end, true);
  els.status.textContent = "已定位左侧图片标记；可在图片右上角直接删除";
}

function sourceLineEditorModel(content, sourceIndex) {
  const lineStart = content.lastIndexOf("\n", Math.max(0, sourceIndex - 1)) + 1;
  const nextBreak = content.indexOf("\n", sourceIndex);
  const lineEnd = nextBreak === -1 ? content.length : nextBreak;
  const rawLine = content.slice(lineStart, lineEnd);
  const leading = rawLine.match(/^\s*/)?.[0] || "";
  const afterLeading = rawLine.slice(leading.length);
  const markerMatch = afterLeading.match(/^(#{1,6}\s+|>\s+|(?:[-*+]|\d+[.)])\s+)/);
  const marker = markerMatch?.[0] || "";
  const body = afterLeading.slice(marker.length);
  let blockType = "p";
  if (/^#\s+$/.test(marker)) blockType = "h1";
  else if (/^##\s+$/.test(marker)) blockType = "h2";
  else if (/^#{3,6}\s+$/.test(marker)) blockType = "h3";
  else if (/^>\s+$/.test(marker)) blockType = "quote";
  else if (marker) blockType = "list";
  return {
    lineStart,
    lineEnd,
    leading,
    marker,
    body,
    bodyStart: lineStart + leading.length + marker.length,
    blockType,
  };
}

function renderPreviewInlineEditorHtml(value) {
  return parseInline(value)
    .map((token) => {
      let inner = escapeHtml(token.text);
      if (token.bold) inner = `<strong>${inner}</strong>`;
      if (token.italic) inner = `<em>${inner}</em>`;
      if (token.color) inner = `<span data-inline-color="${escapeAttribute(token.color)}" style="color:${escapeAttribute(token.color)}">${inner}</span>`;
      if (token.bgColor) inner = `<span data-inline-bg="${escapeAttribute(token.bgColor)}" style="background-color:${escapeAttribute(token.bgColor)}">${inner}</span>`;
      return inner;
    })
    .join("");
}

function serializePreviewInlineNode(node) {
  if (node.nodeType === Node.TEXT_NODE) return node.nodeValue || "";
  if (node.nodeType !== Node.ELEMENT_NODE) return "";
  if (node.tagName === "BR") return " ";
  let value = Array.from(node.childNodes, serializePreviewInlineNode).join("");
  if (["STRONG", "B"].includes(node.tagName)) value = `**${value}**`;
  if (["EM", "I"].includes(node.tagName)) value = `*${value}*`;
  if (node.dataset.inlineColor) value = `{{color:${node.dataset.inlineColor}|${value}}}`;
  if (node.dataset.inlineBg) value = `{{bg:${node.dataset.inlineBg}|${value}}}`;
  return value;
}

function previewInlineVisibleRange(model, sourceStart, sourceEnd) {
  let visibleOffset = 0;
  let visibleStart = null;
  let visibleEnd = null;
  for (const token of parseInline(model.body, model.bodyStart)) {
    if (visibleStart === null && sourceStart >= token.sourceStart && sourceStart <= token.sourceEnd) {
      visibleStart = visibleOffset + clamp(sourceStart - token.sourceStart, 0, token.text.length);
    }
    if (visibleEnd === null && sourceEnd >= token.sourceStart && sourceEnd <= token.sourceEnd) {
      visibleEnd = visibleOffset + clamp(sourceEnd - token.sourceStart, 0, token.text.length);
    }
    visibleOffset += token.text.length;
  }
  return {
    start: visibleStart ?? visibleOffset,
    end: visibleEnd ?? visibleStart ?? visibleOffset,
  };
}

function setContentEditableSelection(root, start, end) {
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
      startOffset = clamp(start - offset, 0, length);
    }
    if (!endNode && end <= offset + length) {
      endNode = node;
      endOffset = clamp(end - offset, 0, length);
      break;
    }
    offset += length;
  }
  if (!startNode) return;
  const range = document.createRange();
  range.setStart(startNode, startOffset);
  range.setEnd(endNode || startNode, endNode ? endOffset : startOffset);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
}

function closePreviewInlineEditor({ restoreFocus = false } = {}) {
  const current = previewInlineEditor;
  if (!current) return;
  current.root.remove();
  previewInlineEditor = null;
  if (restoreFocus) current.target?.focus({ preventScroll: true });
}

function updatePreviewInlineBlockButtons() {
  if (!previewInlineEditor) return;
  previewInlineEditor.root.querySelectorAll("[data-preview-block]").forEach((button) => {
    const active = button.dataset.previewBlock === previewInlineEditor.model.blockType;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function setPreviewInlineBlock(blockType) {
  if (!previewInlineEditor) return;
  const model = previewInlineEditor.model;
  const requestedMarker = blockType === "h1" ? "# " : blockType === "h2" ? "## " : "";
  if (model.blockType === blockType) {
    model.blockType = "p";
    model.marker = "";
  } else {
    model.blockType = blockType;
    model.marker = requestedMarker;
  }
  previewInlineEditor.dirty = true;
  previewInlineEditor.editable.className = `preview-inline-content is-${model.blockType}`;
  updatePreviewInlineBlockButtons();
  previewInlineEditor.editable.focus();
}

function applyPreviewInlineFormat(command) {
  if (!previewInlineEditor || !["bold", "italic"].includes(command)) return;
  previewInlineEditor.editable.focus();
  document.execCommand(command, false, null);
  previewInlineEditor.dirty = true;
}

const PREVIEW_INLINE_SWATCHES = {
  color: ["#2563eb", "#e11d48", "#15803d", "#b45309", "#7c3aed", "#111827"],
  bg: ["#fff3a3", "#d6efd0", "#d6e6ff", "#ffd9e2", "#ffe1b8", "#ececec"],
};

function rememberPreviewInlineRange() {
  const editor = previewInlineEditor;
  if (!editor) return;
  const selection = window.getSelection();
  if (selection && selection.rangeCount) {
    const range = selection.getRangeAt(0);
    if (editor.editable.contains(range.commonAncestorContainer)) {
      editor.savedRange = range.cloneRange();
    }
  }
}

function togglePreviewInlineSwatches(kind) {
  const editor = previewInlineEditor;
  if (!editor || !editor.swatchTray) return;
  const tray = editor.swatchTray;
  const toggles = editor.root.querySelectorAll("[data-preview-swatch]");
  if (editor.swatchMode === kind && !tray.hidden) {
    tray.hidden = true;
    editor.swatchMode = null;
    toggles.forEach((button) => button.setAttribute("aria-expanded", "false"));
    editor.editable.focus();
    return;
  }
  rememberPreviewInlineRange();
  editor.swatchMode = kind;
  const label = kind === "color" ? "文字颜色" : "背景高亮";
  tray.innerHTML = "";
  const caption = document.createElement("span");
  caption.className = "preview-inline-swatch-label";
  caption.textContent = label;
  tray.append(caption);
  PREVIEW_INLINE_SWATCHES[kind].forEach((color) => {
    const dot = document.createElement("button");
    dot.type = "button";
    dot.className = "preview-inline-swatch";
    dot.title = color;
    dot.setAttribute("aria-label", `${label} ${color}`);
    if (kind === "color") {
      dot.style.color = color;
      dot.textContent = "A";
    } else {
      dot.style.background = color;
    }
    dot.addEventListener("pointerdown", (event) => event.preventDefault());
    dot.addEventListener("click", () => applyPreviewInlineColor(kind, color));
    tray.append(dot);
  });
  const custom = document.createElement("label");
  custom.className = "preview-inline-swatch preview-inline-swatch-custom";
  custom.title = "自定义颜色";
  const customInput = document.createElement("input");
  customInput.type = "color";
  customInput.value = kind === "color" ? "#2563eb" : "#fff3a3";
  customInput.addEventListener("input", () => applyPreviewInlineColor(kind, customInput.value));
  custom.append(customInput);
  tray.append(custom);
  const clear = document.createElement("button");
  clear.type = "button";
  clear.className = "preview-inline-swatch preview-inline-swatch-clear";
  clear.textContent = "去掉";
  clear.setAttribute("aria-label", kind === "color" ? "去掉文字颜色" : "去掉背景高亮");
  clear.addEventListener("pointerdown", (event) => event.preventDefault());
  clear.addEventListener("click", () => clearPreviewInlineColor(kind));
  tray.append(clear);
  tray.hidden = false;
  toggles.forEach((button) => button.setAttribute("aria-expanded", String(button.dataset.previewSwatch === kind)));
}

function previewInlineNodeTextLength(node) {
  if (node.nodeType === Node.TEXT_NODE) return node.nodeValue?.length || 0;
  if (node.nodeType !== Node.ELEMENT_NODE) return 0;
  if (node.tagName === "BR") return 1;
  return Array.from(node.childNodes, previewInlineNodeTextLength).reduce((sum, value) => sum + value, 0);
}

function previewInlineOffsetOf(editable, container, offset) {
  if (!editable.contains(container)) return null;
  let total = 0;
  const walker = document.createTreeWalker(editable, NodeFilter.SHOW_TEXT);
  if (container.nodeType === Node.ELEMENT_NODE) {
    // Boundary sits between child nodes; count text length of preceding children.
    for (let i = 0; i < offset && i < container.childNodes.length; i += 1) {
      total += previewInlineNodeTextLength(container.childNodes[i]);
    }
    if (container === editable) return total;
    // Add the text length preceding `container` itself.
    let before = 0;
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (container.contains(node)) break;
      before += node.nodeValue?.length || 0;
    }
    return before + total;
  }
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (node === container) return total + offset;
    total += node.nodeValue?.length || 0;
  }
  return total;
}

function previewInlineSelectionOffsets(editable) {
  const selection = window.getSelection();
  let range = selection && selection.rangeCount ? selection.getRangeAt(0) : null;
  if ((!range || !editable.contains(range.commonAncestorContainer)) && previewInlineEditor?.savedRange) {
    range = previewInlineEditor.savedRange;
  }
  if (!range || !editable.contains(range.commonAncestorContainer)) return [null, null];
  let start = previewInlineOffsetOf(editable, range.startContainer, range.startOffset);
  let end = previewInlineOffsetOf(editable, range.endContainer, range.endOffset);
  if (start == null || end == null) return [null, null];
  if (start > end) [start, end] = [end, start];
  return [start, end];
}

function styleInlineTokensRange(tokens, from, to, patch) {
  const out = [];
  let offset = 0;
  for (const token of tokens) {
    const start = offset;
    const end = offset + token.text.length;
    offset = end;
    const overlapStart = Math.max(start, from);
    const overlapEnd = Math.min(end, to);
    if (overlapEnd <= overlapStart) {
      out.push(token);
      continue;
    }
    if (start < overlapStart) out.push({ ...token, text: token.text.slice(0, overlapStart - start) });
    const middle = { ...token, text: token.text.slice(overlapStart - start, overlapEnd - start) };
    // Color and background are mutually exclusive on one span: the parser can
    // only round-trip one macro per run, so applying one clears the other.
    delete middle.color;
    delete middle.bgColor;
    if (patch.color) middle.color = patch.color;
    else if (patch.bgColor) middle.bgColor = patch.bgColor;
    out.push(middle);
    if (end > overlapEnd) out.push({ ...token, text: token.text.slice(overlapEnd - start) });
  }
  return out;
}

function mergeInlineTokens(tokens) {
  const out = [];
  for (const token of tokens) {
    const last = out[out.length - 1];
    if (
      last &&
      !!last.bold === !!token.bold &&
      !!last.italic === !!token.italic &&
      (last.color || "") === (token.color || "") &&
      (last.bgColor || "") === (token.bgColor || "")
    ) {
      last.text += token.text;
    } else {
      out.push({ ...token });
    }
  }
  return out;
}

function inlineTokensToSource(tokens) {
  return tokens
    .map((token) => {
      let value = token.text;
      if (token.bold) value = `**${value}**`;
      if (token.italic) value = `*${value}*`;
      if (token.color) value = `{{color:${token.color}|${value}}}`;
      else if (token.bgColor) value = `{{bg:${token.bgColor}|${value}}}`;
      return value;
    })
    .join("");
}

function updatePreviewInlineRange(patch) {
  const editor = previewInlineEditor;
  if (!editor) return false;
  const [from, to] = previewInlineSelectionOffsets(editor.editable);
  if (from == null || from === to) {
    els.status.textContent = "请先选中要上色的文字";
    return false;
  }
  const body = Array.from(editor.editable.childNodes, serializePreviewInlineNode).join("");
  const tokens = mergeInlineTokens(styleInlineTokensRange(parseInline(body), from, to, patch));
  editor.editable.innerHTML = renderPreviewInlineEditorHtml(inlineTokensToSource(tokens));
  setContentEditableSelection(editor.editable, from, to);
  const selection = window.getSelection();
  editor.savedRange = selection.rangeCount ? selection.getRangeAt(0).cloneRange() : null;
  editor.dirty = true;
  editor.editable.focus();
  return true;
}

function applyPreviewInlineColor(kind, color) {
  updatePreviewInlineRange(kind === "color" ? { color } : { bgColor: color });
}

function clearPreviewInlineColor() {
  updatePreviewInlineRange({});
}

async function finishPreviewInlineEditor() {
  const current = previewInlineEditor;
  if (!current || current.busy) return;
  current.busy = true;
  const serializedBody = Array.from(current.editable.childNodes, serializePreviewInlineNode).join("").replace(/\s*\n\s*/g, " ");
  const nextLine = `${current.model.leading}${current.model.marker}${serializedBody}`;
  const previousLine = els.content.value.slice(current.model.lineStart, current.model.lineEnd);
  const nextContent = `${els.content.value.slice(0, current.model.lineStart)}${nextLine}${els.content.value.slice(current.model.lineEnd)}`;
  const nextStart = current.model.lineStart + current.model.leading.length + current.model.marker.length;
  closePreviewInlineEditor();
  if (nextLine === previousLine) {
    focusEditorRange(nextStart, nextStart + serializedBody.length, true);
    els.status.textContent = "卡片文字未改动";
    return;
  }
  const applied = await applyProgrammaticContent(nextContent, "卡片文字已更新");
  if (applied) focusEditorRange(nextStart, Math.min(nextContent.length, nextStart + serializedBody.length), true);
}

function openPreviewInlineEditor(target, sourceStart, sourceEnd) {
  if (isBuiltInProjectId(state.currentProjectId)) {
    els.status.textContent = "内置说明书不可修改，请先复制或新建图文";
    return;
  }
  if (previewInlineEditor?.target === target) return;
  if (previewInlineEditor?.dirty) {
    els.status.textContent = "当前卡片文字尚未完成，请先点“完成”或按 Esc 取消";
    previewInlineEditor.editable.focus({ preventScroll: true });
    return;
  }
  closePreviewInlineEditor();
  const frame = target.closest(".page-frame");
  if (!frame) return;
  const model = sourceLineEditorModel(els.content.value, sourceStart);
  if (!model.body.trim() || isMarkdownImageBlock(els.content.value.slice(model.lineStart, model.lineEnd).trim())) return;

  const root = document.createElement("section");
  root.className = "preview-inline-editor";
  root.setAttribute("aria-label", "卡片内文字编辑器");
  const toolbar = document.createElement("div");
  toolbar.className = "preview-inline-toolbar";
  toolbar.innerHTML = `
    <span class="preview-inline-label"><i data-lucide="square-pen"></i> 卡片内编辑</span>
    <span class="preview-inline-format-group">
      <button type="button" data-preview-block="h1" aria-label="设为一级标题" aria-pressed="false">H1</button>
      <button type="button" data-preview-block="h2" aria-label="设为二级标题" aria-pressed="false">H2</button>
      <button type="button" data-preview-format="bold" aria-label="加粗"><strong>B</strong></button>
      <button type="button" data-preview-format="italic" aria-label="斜体"><em>I</em></button>
      <button type="button" data-preview-swatch="color" aria-label="文字上色" title="文字上色" aria-expanded="false"><span class="preview-inline-chip preview-inline-chip-text">A</span></button>
      <button type="button" data-preview-swatch="bg" aria-label="背景高亮" title="背景高亮" aria-expanded="false"><span class="preview-inline-chip preview-inline-chip-bg">A</span></button>
    </span>
    <span class="preview-inline-actions">
      <button type="button" data-preview-action="cancel" aria-label="取消编辑"><i data-lucide="x"></i></button>
      <button type="button" class="preview-inline-done" data-preview-action="done"><i data-lucide="check"></i> 完成</button>
    </span>`;
  const swatchTray = document.createElement("div");
  swatchTray.className = "preview-inline-swatches";
  swatchTray.hidden = true;
  const editable = document.createElement("div");
  editable.className = `preview-inline-content is-${model.blockType}`;
  editable.contentEditable = "true";
  editable.spellcheck = true;
  editable.setAttribute("role", "textbox");
  editable.setAttribute("aria-label", "直接编辑卡片文字；选中文字后可加粗或斜体");
  editable.innerHTML = renderPreviewInlineEditorHtml(model.body);
  root.append(toolbar, swatchTray, editable);
  frame.append(root);

  const targetRect = target.getBoundingClientRect();
  const frameRect = frame.getBoundingClientRect();
  const preferredTop = targetRect.bottom - frameRect.top + 8;
  root.style.left = "12px";
  root.style.right = "12px";
  root.style.top = `${clamp(preferredTop, 12, Math.max(12, frameRect.height - 190))}px`;
  previewInlineEditor = { root, target, editable, model, dirty: false, busy: false, swatchTray, swatchMode: null, savedRange: null };

  toolbar.querySelectorAll("button").forEach((button) => {
    button.addEventListener("pointerdown", (event) => event.preventDefault());
  });
  toolbar.querySelectorAll("[data-preview-block]").forEach((button) => {
    button.addEventListener("click", () => setPreviewInlineBlock(button.dataset.previewBlock));
  });
  toolbar.querySelectorAll("[data-preview-format]").forEach((button) => {
    button.addEventListener("click", () => applyPreviewInlineFormat(button.dataset.previewFormat));
  });
  toolbar.querySelectorAll("[data-preview-swatch]").forEach((button) => {
    button.addEventListener("click", () => togglePreviewInlineSwatches(button.dataset.previewSwatch));
  });
  toolbar.querySelector("[data-preview-action='cancel']").addEventListener("click", () => closePreviewInlineEditor({ restoreFocus: true }));
  toolbar.querySelector("[data-preview-action='done']").addEventListener("click", () => void finishPreviewInlineEditor());
  editable.addEventListener("input", () => {
    if (previewInlineEditor) previewInlineEditor.dirty = true;
  });
  editable.addEventListener("paste", (event) => {
    event.preventDefault();
    const text = (event.clipboardData?.getData("text/plain") || "").replace(/\s*\n+\s*/g, " ");
    document.execCommand("insertText", false, text);
  });
  editable.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closePreviewInlineEditor({ restoreFocus: true });
    } else if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void finishPreviewInlineEditor();
    } else if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "b") {
      event.preventDefault();
      applyPreviewInlineFormat("bold");
    }
  });
  updatePreviewInlineBlockButtons();
  if (window.lucide) window.lucide.createIcons();
  editable.focus({ preventScroll: true });
  const visibleRange = previewInlineVisibleRange(model, sourceStart, sourceEnd);
  setContentEditableSelection(editable, visibleRange.start, visibleRange.end);
  els.status.textContent = "正在卡片内编辑；选中文字可加粗，按 Enter 完成，Esc 取消";
}

function removeContentLineAtRange(content, sourceStart, sourceEnd) {
  let removeStart = content.lastIndexOf("\n", Math.max(0, sourceStart - 1)) + 1;
  let removeEnd = content.indexOf("\n", Math.max(sourceEnd, sourceStart));
  if (removeEnd === -1) {
    removeEnd = content.length;
    if (removeStart > 0) removeStart -= 1;
  } else {
    removeEnd += 1;
  }
  return {
    content: `${content.slice(0, removeStart)}${content.slice(removeEnd)}`,
    selection: removeStart,
  };
}

function deletePreviewImageReference(event) {
  event.preventDefault();
  event.stopPropagation();
  if (imageReorderBusy || isBuiltInProjectId(state.currentProjectId)) return;
  if (previewInlineEditor?.dirty) {
    els.status.textContent = "当前卡片文字尚未完成，请先点“完成”或按 Esc 取消";
    previewInlineEditor.editable.focus({ preventScroll: true });
    return;
  }
  const box = event.currentTarget.closest(".preview-image-box");
  const sourceStart = Number(box?.dataset.sourceStart);
  const sourceEnd = Number(box?.dataset.sourceEnd);
  if (!Number.isFinite(sourceStart) || !Number.isFinite(sourceEnd)) return;
  const next = removeContentLineAtRange(els.content.value, sourceStart, sourceEnd);
  closePreviewInlineEditor();
  els.content.setSelectionRange(next.selection, next.selection);
  void applyProgrammaticContent(next.content, "图片已从正文移除，资源库仍保留；可撤销");
}

function contentLineModel(content) {
  const lines = String(content || "").replace(/\r\n/g, "\n").split("\n");
  const offsets = [];
  let offset = 0;
  for (const line of lines) {
    offsets.push(offset);
    offset += line.length + 1;
  }
  return { lines, offsets };
}

function lineIndexForSourceOffset(offsets, sourceOffset) {
  const target = Math.max(0, Number(sourceOffset) || 0);
  let low = 0;
  let high = offsets.length - 1;
  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    if (offsets[middle] <= target) low = middle + 1;
    else high = middle - 1;
  }
  return Math.max(0, Math.min(offsets.length - 1, high));
}

function reorderNonEmptyLine(content, sourceStart, targetStart, placeAfter) {
  const { lines, offsets } = contentLineModel(content);
  const sourceLineIndex = lineIndexForSourceOffset(offsets, sourceStart);
  const targetLineIndex = lineIndexForSourceOffset(offsets, targetStart);
  if (sourceLineIndex === targetLineIndex || !isMarkdownImageBlock(lines[sourceLineIndex]?.trim() || "")) return content;

  const nonEmptyIndices = lines.map((line, index) => (line.trim() ? index : -1)).filter((index) => index >= 0);
  const sourceSlot = nonEmptyIndices.indexOf(sourceLineIndex);
  const targetSlot = nonEmptyIndices.indexOf(targetLineIndex);
  if (sourceSlot < 0 || targetSlot < 0) return content;

  const values = nonEmptyIndices.map((index) => lines[index]);
  const [moving] = values.splice(sourceSlot, 1);
  const targetAfterRemoval = targetSlot - (sourceSlot < targetSlot ? 1 : 0);
  const insertionIndex = Math.max(0, Math.min(values.length, targetAfterRemoval + (placeAfter ? 1 : 0)));
  values.splice(insertionIndex, 0, moving);
  nonEmptyIndices.forEach((lineIndex, slot) => {
    lines[lineIndex] = values[slot];
  });
  return lines.join("\n");
}

function adjacentNonEmptyTarget(content, sourceStart, direction) {
  const { lines, offsets } = contentLineModel(content);
  const sourceLineIndex = lineIndexForSourceOffset(offsets, sourceStart);
  const nonEmptyIndices = lines.map((line, index) => (line.trim() ? index : -1)).filter((index) => index >= 0);
  const sourceSlot = nonEmptyIndices.indexOf(sourceLineIndex);
  const targetSlot = sourceSlot + direction;
  if (sourceSlot < 0 || targetSlot < 0 || targetSlot >= nonEmptyIndices.length) return null;
  const targetLineIndex = nonEmptyIndices[targetSlot];
  return offsets[targetLineIndex];
}

async function applyProgrammaticContent(nextContent, message) {
  if (nextContent === els.content.value || isBuiltInProjectId(state.currentProjectId)) return false;
  commitTextHistory();
  els.content.value = nextContent;
  const selection = Math.min(nextContent.length, els.content.selectionStart || 0);
  els.content.setSelectionRange(selection, selection);
  commitTextHistory();
  lastEditorImageReferenceSignature = imageReferenceSignature(nextContent);
  syncAiUndoAvailability();
  markSaveDirty();
  await render({ persist: false });
  const saved = await persistCurrentDraftImmediately();
  els.status.textContent = saved ? `${message}，当前版本已保存` : `${message}；本机保存仍在重试`;
  return true;
}

function setImageReorderBusy(busy) {
  imageReorderBusy = Boolean(busy);
  document.body.classList.toggle("preview-image-reorder-busy", imageReorderBusy);
  els.pages?.setAttribute("aria-busy", String(imageReorderBusy));
  document.querySelectorAll(".preview-image-drag-handle, .preview-image-order button").forEach((control) => {
    control.disabled = imageReorderBusy;
  });
}

async function applyPreviewImageReorder(nextContent, message) {
  if (imageReorderBusy || nextContent === els.content.value) return false;
  setImageReorderBusy(true);
  try {
    return await applyProgrammaticContent(nextContent, message);
  } finally {
    setImageReorderBusy(false);
  }
}

function movePreviewImageByStep(event) {
  event.preventDefault();
  event.stopPropagation();
  if (imageReorderBusy) return;
  const box = event.currentTarget.closest(".preview-image-box");
  const sourceStart = Number(box?.dataset.sourceStart);
  const direction = Number(event.currentTarget.dataset.direction);
  if (!Number.isFinite(sourceStart) || ![-1, 1].includes(direction)) return;
  const targetStart = adjacentNonEmptyTarget(els.content.value, sourceStart, direction);
  if (targetStart === null) {
    els.status.textContent = direction < 0 ? "这张图片已经在最前面" : "这张图片已经在最后面";
    return;
  }
  const next = reorderNonEmptyLine(els.content.value, sourceStart, targetStart, direction > 0);
  void applyPreviewImageReorder(next, direction < 0 ? "图片已上移一项" : "图片已下移一项");
}

function handlePreviewImageOrderKeydown(event) {
  if (imageReorderBusy || !event.altKey || !["ArrowUp", "ArrowDown"].includes(event.key)) return;
  event.preventDefault();
  const sourceStart = Number(event.currentTarget.dataset.sourceStart);
  const direction = event.key === "ArrowUp" ? -1 : 1;
  const targetStart = adjacentNonEmptyTarget(els.content.value, sourceStart, direction);
  if (targetStart === null) return;
  const next = reorderNonEmptyLine(els.content.value, sourceStart, targetStart, direction > 0);
  void applyPreviewImageReorder(next, direction < 0 ? "图片已上移一项" : "图片已下移一项");
}

function pageItemSourceStart(item) {
  if (Number.isFinite(item.sourceStart)) return item.sourceStart;
  if (item.type !== "text") return null;
  const starts = (item.line || []).map((token) => token.sourceStart).filter(Number.isFinite);
  return starts.length ? Math.min(...starts) : null;
}

function previewImageReorderTargets(sourceStart) {
  const targets = [];
  document.querySelectorAll(".page-frame canvas").forEach((canvas) => {
    const frame = canvas.closest(".page-frame");
    const rect = canvas.getBoundingClientRect();
    const page = canvas._page;
    if (!frame || !page || rect.width <= 0 || rect.height <= 0) return;
    const scaleY = rect.height / CANVAS_HEIGHT;
    for (const item of page.items || []) {
      const targetStart = pageItemSourceStart(item);
      if (!Number.isFinite(targetStart) || targetStart === sourceStart) continue;
      const rawY = canvas._scrollPage ? (page.bounds?.top || 0) + item.y - page.scrollOffset : item.y;
      const height = item.type === "image" ? item.height : item.lineHeight || 30;
      const top = rect.top + rawY * scaleY;
      const bottom = rect.top + (rawY + height) * scaleY;
      if (bottom < rect.top || top > rect.bottom) continue;
      targets.push({
        frame,
        rect,
        sourceStart: targetStart,
        top: Math.max(rect.top, top),
        bottom: Math.min(rect.bottom, bottom),
        center: (Math.max(rect.top, top) + Math.min(rect.bottom, bottom)) / 2,
      });
    }
  });
  return targets;
}

function closestPreviewImageReorderTarget(clientX, clientY, sourceStart) {
  let best = null;
  for (const target of previewImageReorderTargets(sourceStart)) {
    const horizontalDistance = clientX < target.rect.left
      ? target.rect.left - clientX
      : clientX > target.rect.right
        ? clientX - target.rect.right
        : 0;
    const distance = Math.abs(clientY - target.center) + horizontalDistance * 0.35;
    if (!best || distance < best.distance) {
      best = { ...target, distance, placeAfter: clientY >= target.center };
    }
  }
  return best;
}

function showPreviewImageDropIndicator(target) {
  document.querySelectorAll(".preview-image-drop-indicator").forEach((indicator) => indicator.remove());
  if (!target?.frame) return;
  const indicator = document.createElement("div");
  indicator.className = "preview-image-drop-indicator";
  const boundary = target.placeAfter ? target.bottom : target.top;
  indicator.style.top = `${clamp(((boundary - target.rect.top) / target.rect.height) * 100, 0.5, 99.5)}%`;
  target.frame.append(indicator);
}

function startPreviewImageReorder(event) {
  if (imageReorderBusy || isBuiltInProjectId(state.currentProjectId) || event.button !== 0) return;
  const box = event.currentTarget.closest(".preview-image-box");
  const sourceStart = Number(box?.dataset.sourceStart);
  const sourceEnd = Number(box?.dataset.sourceEnd);
  if (!box || !Number.isFinite(sourceStart) || !Number.isFinite(sourceEnd)) return;
  event.preventDefault();
  event.stopPropagation();
  imageReorderDrag = {
    pointerId: event.pointerId,
    handle: event.currentTarget,
    box,
    sourceStart,
    sourceEnd,
    startX: event.clientX,
    startY: event.clientY,
    active: false,
    target: null,
  };
  event.currentTarget.setPointerCapture?.(event.pointerId);
  document.addEventListener("pointermove", movePreviewImageReorder);
  document.addEventListener("pointerup", stopPreviewImageReorder);
  document.addEventListener("pointercancel", cancelPreviewImageReorder);
}

function movePreviewImageReorder(event) {
  if (!imageReorderDrag || event.pointerId !== imageReorderDrag.pointerId) return;
  event.preventDefault();
  const distance = Math.hypot(event.clientX - imageReorderDrag.startX, event.clientY - imageReorderDrag.startY);
  if (!imageReorderDrag.active && distance < 6) return;
  if (!imageReorderDrag.active) {
    imageReorderDrag.active = true;
    imageReorderDrag.box.classList.add("is-dragging");
    document.body.classList.add("preview-image-reordering");
  }
  imageReorderDrag.target = closestPreviewImageReorderTarget(event.clientX, event.clientY, imageReorderDrag.sourceStart);
  showPreviewImageDropIndicator(imageReorderDrag.target);
  if (event.clientY < 72) window.scrollBy({ top: -18, behavior: "auto" });
  if (event.clientY > window.innerHeight - 72) window.scrollBy({ top: 18, behavior: "auto" });
}

function cleanupPreviewImageReorder() {
  if (!imageReorderDrag) return null;
  const drag = imageReorderDrag;
  drag.handle.releasePointerCapture?.(drag.pointerId);
  drag.box.classList.remove("is-dragging");
  document.body.classList.remove("preview-image-reordering");
  document.querySelectorAll(".preview-image-drop-indicator").forEach((indicator) => indicator.remove());
  document.removeEventListener("pointermove", movePreviewImageReorder);
  document.removeEventListener("pointerup", stopPreviewImageReorder);
  document.removeEventListener("pointercancel", cancelPreviewImageReorder);
  imageReorderDrag = null;
  return drag;
}

function stopPreviewImageReorder(event) {
  if (!imageReorderDrag || event.pointerId !== imageReorderDrag.pointerId) return;
  const drag = cleanupPreviewImageReorder();
  if (!drag?.active || !drag.target) return;
  const next = reorderNonEmptyLine(els.content.value, drag.sourceStart, drag.target.sourceStart, drag.target.placeAfter);
  void applyPreviewImageReorder(next, "图片顺序已调整");
}

function cancelPreviewImageReorder() {
  if (!imageReorderDrag) return;
  cleanupPreviewImageReorder();
  els.status.textContent = "已取消图片顺序调整";
}

function setPreviewImageAlign(event) {
  event.preventDefault();
  event.stopPropagation();
  const align = event.currentTarget.dataset.align;
  const box = event.currentTarget.closest(".preview-image-box");
  const imageId = box?.dataset.imageId;
  if (!imageId || !state.images[imageId] || !["left", "center", "right"].includes(align)) return;

  state.images[imageId].layout = {
    ...normalizeImageLayout(state.images[imageId].layout),
    align,
  };
  saveState();
  render();
  els.status.textContent = align === "left" ? "图片已左对齐" : align === "right" ? "图片已右对齐" : "图片已居中";
}

function startPreviewImageResize(event) {
  const box = event.currentTarget.closest(".preview-image-box");
  const frame = box?.closest(".page-frame");
  const imageId = box?.dataset.imageId;
  if (!box || !frame || !imageId || !state.images[imageId]) return;

  event.preventDefault();
  event.stopPropagation();
  markSaveDirty();
  const frameRect = frame.getBoundingClientRect();
  imageEditDrag = {
    imageId,
    box,
    startX: event.clientX,
    startY: event.clientY,
    startLayout: normalizeImageLayout(state.images[imageId].layout),
    startBox: {
      x: (Number.parseFloat(box.style.left) / 100) * CANVAS_WIDTH,
      y: (Number.parseFloat(box.style.top) / 100) * CANVAS_HEIGHT,
      width: (Number.parseFloat(box.style.width) / 100) * CANVAS_WIDTH,
      height: Number(box.dataset.actualHeight) || (Number.parseFloat(box.style.height) / 100) * CANVAS_HEIGHT,
      visibleHeight: (Number.parseFloat(box.style.height) / 100) * CANVAS_HEIGHT,
      baseWidth: Number(box.dataset.baseWidth) || (Number.parseFloat(box.style.width) / 100) * CANVAS_WIDTH,
      maxWidth: Number(box.dataset.maxWidth) || CARD_CONTENT_WIDTH,
    },
    canvasScaleX: CANVAS_WIDTH / frameRect.width,
    canvasScaleY: CANVAS_HEIGHT / frameRect.height,
  };
  box.classList.add("is-resizing");
  box.setPointerCapture?.(event.pointerId);
  document.addEventListener("pointermove", movePreviewImageResize);
  document.addEventListener("pointerup", stopPreviewImageResize, { once: true });
}

function movePreviewImageResize(event) {
  if (!imageEditDrag) return;
  event.preventDefault();
  const dx = (event.clientX - imageEditDrag.startX) * imageEditDrag.canvasScaleX;
  const dy = (event.clientY - imageEditDrag.startY) * imageEditDrag.canvasScaleY;
  const nextLayout = resizeImageLayout(imageEditDrag.startLayout, imageEditDrag.startBox, dx, dy);
  state.images[imageEditDrag.imageId].layout = nextLayout;

  const nextWidth = imageEditDrag.startBox.baseWidth * nextLayout.widthScale;
  const nextHeight = nextWidth * (imageEditDrag.startBox.height / imageEditDrag.startBox.width);
  const visibleRatio = imageEditDrag.startBox.visibleHeight / Math.max(1, imageEditDrag.startBox.height);
  const nextVisibleHeight = nextHeight * visibleRatio;
  const maxOffset = Math.max(0, imageEditDrag.startBox.maxWidth - nextWidth);
  const sidePadding = cardThemeFor(state).geometry.sidePadding;
  const nextX = nextLayout.align === "left" ? sidePadding : nextLayout.align === "right" ? sidePadding + maxOffset : sidePadding + maxOffset / 2;
  applyImageBoxStyle(imageEditDrag.box, {
    x: nextX,
    y: imageEditDrag.startBox.y,
    width: nextWidth,
    height: nextVisibleHeight,
  });
}

function stopPreviewImageResize() {
  if (!imageEditDrag) return;
  document.removeEventListener("pointermove", movePreviewImageResize);
  const imageId = imageEditDrag.imageId;
  imageEditDrag.box.classList.remove("is-resizing");
  imageEditDrag = null;
  saveState();
  render();
  els.status.textContent = `已调整图片 ${state.images[imageId]?.name || imageId}`;
}

function resizeImageLayout(startLayout, startBox, dx, dy) {
  const heightDrivenDelta = dy * (startBox.width / Math.max(1, startBox.height));
  const deltaWidth = Math.abs(dx) >= Math.abs(heightDrivenDelta) ? dx : heightDrivenDelta;
  const nextWidth = clamp(startBox.width + deltaWidth, startBox.maxWidth * 0.25, startBox.maxWidth);
  return {
    ...startLayout,
    widthScale: nextWidth / startBox.baseWidth,
    widthPercent: (nextWidth / startBox.maxWidth) * 100,
    fixedWidth: null,
    fixedHeight: null,
  };
}

function attachScrollFrameHandlers(frame) {
  let startY = 0;
  let startOffset = 0;

  frame.addEventListener(
    "wheel",
    (event) => {
      if (state.mode !== "scroll" || state.scrollMax <= 0) return;
      event.preventDefault();
      setScrollOffset(state.scrollOffset + event.deltaY);
    },
    { passive: false },
  );

  frame.addEventListener(
    "touchstart",
    (event) => {
      startY = event.touches[0]?.clientY || 0;
      startOffset = state.scrollOffset;
    },
    { passive: true },
  );

  frame.addEventListener(
    "touchmove",
    (event) => {
      if (state.mode !== "scroll" || state.scrollMax <= 0) return;
      event.preventDefault();
      const y = event.touches[0]?.clientY || startY;
      setScrollOffset(startOffset + startY - y);
    },
    { passive: false },
  );
}

function setScrollOffset(value) {
  state.scrollOffset = clamp(value, 0, state.scrollMax);
  render();
}

async function downloadCanvas(canvas, filename) {
  const writable = await chooseSaveTarget(filename, EXPORT_IMAGE_MIME, EXPORT_IMAGE_EXTENSION);
  if (writable === false) {
    els.status.textContent = "已取消下载";
    return;
  }
  const exportCanvas = createExportCanvas(canvas);
  const blob = await canvasToLosslessPngBlob(exportCanvas);
  if (!blob) {
    els.status.textContent = "图片生成失败，请调整内容后再试";
    return;
  }
  await saveBlob(blob, filename, writable);
  const dimensions = `${exportCanvas.width}x${exportCanvas.height}`;
  els.status.textContent = writable ? `已保存 ${filename}（${dimensions}）` : `已交给浏览器下载 ${filename}（${dimensions}）`;
}

async function chooseSaveTarget(filename, mimeType, extension) {
  if (!window.showSaveFilePicker) return null;
  try {
    const handle = await window.showSaveFilePicker({
      suggestedName: filename,
      types: [
        {
          description: extension === ".zip" ? "ZIP 压缩包" : "PNG 图片",
          accept: {
            [mimeType]: [extension],
          },
        },
      ],
    });
    return await handle.createWritable();
  } catch (error) {
    if (error?.name === "AbortError") return false;
    throw error;
  }
}

async function saveBlob(blob, filename, writable = null) {
  if (writable) {
    await writable.write(blob);
    await writable.close();
    return;
  }
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.download = filename;
  link.href = url;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function downloadArticleImage() {
  const settings = readForm();
  if (state.appMode !== "article") {
    state.appMode = "article";
    updateAppMode();
  }
  renderArticlePreview(settings);

  const article = els.pages.querySelector(".article-preview");
  if (!article) {
    els.status.textContent = "长文生成失败，请先检查内容";
    return;
  }

  if (!window.html2canvas) {
    els.status.textContent = "长图下载组件未加载，请刷新页面后重试";
    return;
  }

  const filename = "write-then-publish-article.png";
  const writable = await chooseSaveTarget(filename, EXPORT_IMAGE_MIME, EXPORT_IMAGE_EXTENSION);
  if (writable === false) {
    els.status.textContent = "已取消下载";
    return;
  }

  els.status.textContent = "正在生成长图...";
  const canvas = await window.html2canvas(article, {
    backgroundColor: null,
    scale: normalizeExportScale(state.exportScale),
    useCORS: true,
    imageTimeout: 15000,
    width: article.scrollWidth,
    height: article.scrollHeight,
    windowWidth: Math.max(document.documentElement.clientWidth, article.scrollWidth),
    windowHeight: Math.max(document.documentElement.clientHeight, article.scrollHeight),
  });
  const blob = await canvasToLosslessPngBlob(canvas);
  if (!blob) {
    els.status.textContent = "长图生成失败，请调整内容后再试";
    return;
  }
  await saveBlob(blob, filename, writable);
  els.status.textContent = writable ? `已保存 ${filename}` : `已交给浏览器下载 ${filename}`;
}

function canvasToLosslessPngBlob(canvas) {
  return new Promise((resolve) => canvas.toBlob((blob) => resolve(blob), EXPORT_IMAGE_MIME));
}

async function isZipBlob(blob) {
  const header = new Uint8Array(await blob.slice(0, 4).arrayBuffer());
  return header[0] === 0x50 && header[1] === 0x4b && (header[2] === 0x03 || header[2] === 0x05 || header[2] === 0x07);
}

async function downloadCanvasesIndividually() {
  for (const [index, canvas] of state.canvases.entries()) {
    const filename = state.mode === "scroll" ? "layout-scroll-shot.png" : `layout-page-${String(index + 1).padStart(2, "0")}.png`;
    window.setTimeout(() => downloadCanvas(canvas, filename), index * 180);
  }
}

async function downloadAll() {
  if (!state.canvases.length) return;

  if (!window.JSZip) {
    els.status.textContent = "当前环境不支持打包，将逐张下载";
    await downloadCanvasesIndividually();
    return;
  }

  const scaleSuffix = state.exportScale > 1 ? `-${state.exportScale}x` : "";
  const zipFilename = state.mode === "scroll" ? `graphic-layout-scroll-shot${scaleSuffix}.zip` : `graphic-layout-pages${scaleSuffix}.zip`;
  els.status.textContent = `正在按 ${state.exportScale}× 清晰度重新绘制并打包...`;
  try {
    const zip = new window.JSZip();
    for (const [index, canvas] of state.canvases.entries()) {
      const exportCanvas = createExportCanvas(canvas);
      const blob = await canvasToLosslessPngBlob(exportCanvas);
      if (!blob) {
        els.status.textContent = "图片生成失败，请调整内容后再试";
        return;
      }
      const filename = state.mode === "scroll" ? "layout-scroll-shot.png" : `layout-page-${String(index + 1).padStart(2, "0")}.png`;
      zip.file(filename, blob);
    }
    const blob = await zip.generateAsync({
      type: "blob",
      compression: EXPORT_ZIP_COMPRESSION,
      mimeType: "application/zip",
    });

    if (!(await isZipBlob(blob))) {
      els.status.textContent = "打包文件异常，已改为逐张下载";
      await downloadCanvasesIndividually();
      return;
    }

    await saveBlob(blob, zipFilename);
    const dimensions = `${CANVAS_WIDTH * state.exportScale}x${CANVAS_HEIGHT * state.exportScale}`;
    els.status.textContent = state.mode === "scroll" ? `已下载 ${state.exportScale}× 滑动截图压缩包` : `已下载 ${state.canvases.length} 张 ${state.exportScale}× 图片，尺寸 ${dimensions}`;
  } catch (error) {
    console.error(error);
    els.status.textContent = "打包失败，已改为逐张下载";
    await downloadCanvasesIndividually();
  }
}

const debouncedRender = debounce(() => render({ persist: false }), CONTROL_PREVIEW_RENDER_DELAY);

function runEditorPreviewRenderWhenIdle() {
  const run = () => {
    editorRenderIdleCallback = 0;
    void render({ persist: false });
  };
  if ("requestIdleCallback" in window) {
    editorRenderIdleCallback = window.requestIdleCallback(run, { timeout: EDITOR_PREVIEW_IDLE_TIMEOUT });
  } else {
    run();
  }
}

const debouncedEditorRender = debounce(runEditorPreviewRenderWhenIdle, EDITOR_PREVIEW_RENDER_DELAY);

function cancelEditorPreviewRender() {
  debouncedEditorRender.cancel();
  if (editorRenderIdleCallback && "cancelIdleCallback" in window) {
    window.cancelIdleCallback(editorRenderIdleCallback);
  }
  editorRenderIdleCallback = 0;
}

function prioritizeEditorInput() {
  renderGeneration += 1;
  debouncedRender.cancel();
  cancelEditorPreviewRender();
}

function requestRender() {
  scheduleStateSave();
  renderGeneration += 1;
  cancelEditorPreviewRender();
  debouncedRender();
}

function requestEditorRender() {
  scheduleStateSave(EDITOR_STATE_SAVE_DELAY);
  prioritizeEditorInput();
  debouncedEditorRender();
}

function handleContentCompositionStart() {
  editorCompositionActive = true;
  prioritizeEditorInput();
}

function handleContentCompositionEnd() {
  editorCompositionActive = false;
  requestEditorRender();
}

function handleContentInput(event) {
  scheduleTextHistoryCommit();
  syncAiUndoAvailability();
  const nextImageReferenceSignature = imageReferenceSignature(els.content.value);
  const imageReferencesChanged = nextImageReferenceSignature !== lastEditorImageReferenceSignature;
  lastEditorImageReferenceSignature = nextImageReferenceSignature;
  scheduleCurrentProjectTextSave();
  const composing = editorCompositionActive || event?.isComposing === true;

  if (composing) {
    scheduleStateSave(EDITOR_STATE_SAVE_DELAY);
    prioritizeEditorInput();
    return;
  }
  if (imageReferencesChanged) {
    prioritizeEditorInput();
    flushStateSave();
    void render({ persist: false });
    return;
  }
  requestEditorRender();
}

function positionToolPopover(menu) {
  const popover = menu.querySelector(".tool-popover");
  if (!popover) return;

  if (window.matchMedia("(max-width: 620px)").matches) {
    ["position", "top", "bottom", "left", "right", "max-height", "overflow-y"].forEach((property) => popover.style.removeProperty(property));
    return;
  }

  const margin = 12;
  const menuRect = menu.getBoundingClientRect();
  const popoverRect = popover.getBoundingClientRect();
  const panelRect = menu.closest(".editor-panel")?.getBoundingClientRect();
  const fitsInsidePanel = panelRect && popoverRect.width <= panelRect.width - margin * 2;
  const leftBoundary = fitsInsidePanel ? panelRect.left + margin : margin;
  const rightBoundary = fitsInsidePanel ? panelRect.right - margin : window.innerWidth - margin;
  const preferredLeft = menu.classList.contains("project-actions-menu")
    ? menuRect.right - popoverRect.width
    : menuRect.left;
  const left = clamp(preferredLeft, leftBoundary, Math.max(leftBoundary, rightBoundary - popoverRect.width));
  const naturalHeight = popover.scrollHeight || popoverRect.height;
  const belowTop = menuRect.bottom + 8;
  const availableBelow = Math.max(0, window.innerHeight - margin - belowTop);
  const availableAbove = Math.max(0, menuRect.top - margin - 8);
  const placeBelow = availableBelow >= Math.min(naturalHeight, 240) || availableBelow >= availableAbove;
  const availableHeight = placeBelow ? availableBelow : availableAbove;
  const maxHeight = Math.max(120, Math.min(naturalHeight, availableHeight));

  popover.style.position = "fixed";
  popover.style.left = `${Math.round(left)}px`;
  popover.style.right = "auto";
  popover.style.maxHeight = `${Math.round(maxHeight)}px`;
  popover.style.overflowY = "auto";
  if (placeBelow) {
    // Anchor the top just under the trigger so it hangs down from it.
    popover.style.top = `${Math.round(belowTop)}px`;
    popover.style.bottom = "auto";
  } else {
    // Anchor the bottom just above the trigger so it always hugs it, no matter
    // how short the actual content ends up being.
    popover.style.top = "auto";
    popover.style.bottom = `${Math.round(window.innerHeight - menuRect.top + 8)}px`;
  }
}

function positionOpenToolPopovers() {
  document.querySelectorAll(".tool-menu[open]").forEach(positionToolPopover);
}

function bindEvents() {
  if (els.toolbar && els.settingsMenu) {
    els.toolbar.prepend(els.settingsMenu);
  }
  document.querySelectorAll(".tool-menu").forEach((menu) => {
    const summary = menu.querySelector("summary");
    const popover = menu.querySelector(".tool-popover");
    summary?.addEventListener("click", () => {
      if (menu.open) return;
      document.querySelectorAll(".tool-menu").forEach((other) => {
        if (other !== menu) other.open = false;
      });
    });
    menu.addEventListener("toggle", () => {
      if (!menu.open) return;
      document.querySelectorAll(".tool-menu").forEach((other) => {
        if (other !== menu) other.open = false;
      });
      requestAnimationFrame(() => positionToolPopover(menu));
    });
    if (menu.classList.contains("settings-menu")) {
      popover?.addEventListener("mouseleave", () => {
        menu.open = false;
      });
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const openMenus = [...document.querySelectorAll(".tool-menu[open]")];
    if (!openMenus.length) return;
    event.preventDefault();
    openMenus.forEach((menu) => menu.removeAttribute("open"));
    openMenus.at(-1)?.querySelector("summary")?.focus();
  });

  window.addEventListener("resize", positionOpenToolPopovers);
  window.addEventListener("scroll", positionOpenToolPopovers, { passive: true });
  els.editorPanel?.addEventListener("scroll", positionOpenToolPopovers, { passive: true });
  window.addEventListener("resize", applyPanelLayout);

  els.panelResizers.forEach((resizer) => {
    resizer.addEventListener("pointerdown", startPanelResize);
    resizer.addEventListener("keydown", resizePanelWithKeyboard);
  });
  els.editorPanelToggle?.addEventListener("click", toggleEditorPanel);

  document.querySelectorAll("[data-format]").forEach((button) => {
    button.addEventListener("click", () => {
      disableActiveBrushes();
      wrapSelection(button.dataset.format);
    });
  });

  els.modeButtons.forEach((button) => {
    button.addEventListener("click", (event) => setAppMode(event.currentTarget.dataset.appMode));
  });
  els.previewViewButtons.forEach((button) => {
    button.addEventListener("click", () => {
      setPreviewViewMode(button.dataset.previewView, { announce: true });
    });
  });
  els.stageNavPrev?.addEventListener("click", () => movePreviewPage(-1));
  els.stageNavNext?.addEventListener("click", () => movePreviewPage(1));

  els.articleThemeButtons.forEach((button) => {
    button.addEventListener("click", (event) => setArticleOption("theme", event.currentTarget.dataset.articleTheme));
  });
  els.articleFontButtons.forEach((button) => {
    button.addEventListener("click", (event) => setArticleOption("font", event.currentTarget.dataset.articleFont));
  });
  els.articleSizeButtons.forEach((button) => {
    button.addEventListener("click", (event) => setArticleOption("size", event.currentTarget.dataset.articleSize));
  });
  els.articleColorButtons.forEach((button) => {
    button.addEventListener("click", (event) => setArticleOption("color", event.currentTarget.dataset.articleColor));
  });

  els.content.addEventListener("compositionstart", handleContentCompositionStart);
  els.content.addEventListener("compositionend", handleContentCompositionEnd);
  els.content.addEventListener("input", handleContentInput);
  els.projectTitle?.addEventListener("input", updateCurrentProjectTitle);
  els.projectPublishStatus?.addEventListener("change", scheduleStateSave);
  els.content.addEventListener("pointerdown", clearPreviewEditorPin);
  els.content.addEventListener("keydown", handleTextShortcut);
  els.content.addEventListener("paste", handleEditorPaste);
  els.content.addEventListener("dragover", (event) => {
    if (Array.from(event.dataTransfer?.types || []).includes("Files")) event.preventDefault();
  });
  els.content.addEventListener("drop", handleEditorDrop);

  [
    els.displayName,
    els.handle,
    els.textColor,
    els.accentColor,
    els.fontSize,
    els.lineHeight,
    els.zhFont,
    els.enFont,
    els.imageHeight,
  ].forEach((input) => {
    input.addEventListener("input", () => {
      if (input === els.textColor || input === els.accentColor) syncCardPaletteControls();
      requestRender();
    });
    input.addEventListener("change", () => {
      if (input === els.textColor || input === els.accentColor) {
        ensureCardColorContrast("foreground");
      } else {
        requestRender();
      }
    });
  });

  els.bgColor.addEventListener("input", () => {
    syncCardPaletteControls();
    requestRender();
  });
  els.bgColor.addEventListener("change", () => ensureCardColorContrast("background"));
  els.cardThemeButtons.forEach((button) => button.addEventListener("click", applyCardTheme));
  els.cardPaletteButtons.forEach((button) => button.addEventListener("click", applyCardPalette));

  els.inlineColor.addEventListener("input", () => {
    document.documentElement.style.setProperty("--brush-color", els.inlineColor.value);
  });
  els.inlineBgColor.addEventListener("input", () => {
    document.documentElement.style.setProperty("--text-bg-brush-color", els.inlineBgColor.value);
  });
  els.colorConfirm.addEventListener("click", enableColorBrush);
  els.colorCancel.addEventListener("click", disableColorBrush);
  els.bgColorConfirm.addEventListener("click", enableBackgroundBrush);
  els.bgColorCancel.addEventListener("click", disableBackgroundBrush);
  els.colorTool?.addEventListener("click", (event) => toggleActiveBrushFromTool(event, "color"));
  els.bgColorTool?.addEventListener("click", (event) => toggleActiveBrushFromTool(event, "background"));
  document.addEventListener("pointerup", applyActiveBrushToSelection);
  els.content.addEventListener("keyup", (event) => {
    if (event.key.startsWith("Arrow") || event.key === "Shift") {
      applyActiveBrushToSelection();
    }
  });
  els.contentImage.addEventListener("change", handleContentImage);
  els.connectObsidianVault?.addEventListener("click", connectObsidianVault);
  els.obsidianVaultFolder?.addEventListener("change", handleObsidianVaultFolder);
  els.applyImageWidth?.addEventListener("click", applyImageWidthToAll);
  els.applyFixedImageSize?.addEventListener("click", applyFixedImageSizeToAll);
  els.avatarInput.addEventListener("change", handleAvatar);
  els.cropAvatar.addEventListener("click", () => openCropper("avatar"));
  els.cropClose.addEventListener("click", closeCropper);
  els.cropApply.addEventListener("click", applyCropper);
  els.cropReset.addEventListener("click", resetCropperTarget);
  els.cropModal.addEventListener("click", (event) => {
    if (event.target === els.cropModal) closeCropper();
  });
  els.ratioButtons.forEach((button) => {
    button.addEventListener("click", () => setCropAspect(button.dataset.ratio));
  });
  els.cropCanvas.addEventListener("mousedown", startCropDrag);
  window.addEventListener("mousemove", moveCropDrag);
  window.addEventListener("mouseup", stopCropDrag);
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !els.cropModal.classList.contains("hidden")) closeCropper();
    if (event.key === "Escape" && !els.importPreviewModal?.classList.contains("hidden")) closeProjectImportPreview();
    if (event.key === "Escape" && !els.assetLibraryModal?.classList.contains("hidden")) closeAssetLibrary();
    if (event.key === "Escape" && !els.illustrationModal?.classList.contains("hidden")) closeIllustrationModal();
    if (event.key === "Escape" && !els.themeLibraryModal?.classList.contains("hidden")) closeThemeLibrary();
    if (event.key === "Escape" && !els.helpModal?.classList.contains("hidden")) closeHelp();
    if (event.key === "Escape" && imageReorderDrag) cancelPreviewImageReorder();
    if (event.key === "Escape") clearPreviewEditorPin();
  });
  els.findNext.addEventListener("click", findNext);
  els.replaceOne.addEventListener("click", replaceCurrent);
  els.replaceAll.addEventListener("click", replaceAll);
  els.historyToggle.addEventListener("click", toggleHistory);
  els.historyClose.addEventListener("click", () => setHistoryOpen(false, true));
  els.help?.addEventListener("click", openHelp);
  els.helpClose?.addEventListener("click", closeHelp);
  els.helpModal?.addEventListener("click", (event) => {
    if (event.target === els.helpModal) closeHelp();
  });
  els.helpModal?.addEventListener("keydown", trapHelpFocus);
  els.helpModal?.querySelectorAll("[data-copy-prompt]").forEach((button) => {
    button.addEventListener("click", () => void copyAgentPrompt(button));
  });
  els.historyFilterButtons.forEach((button) => {
    button.addEventListener("click", () => setHistoryFilter(button.dataset.historyFilter));
  });
  els.newProject.addEventListener("click", createNewProject);
  els.exportProjects?.addEventListener("click", handlePrimaryPersistenceAction);
  els.saveNow?.addEventListener("click", handlePrimaryPersistenceAction);
  els.aiOptimize?.addEventListener("click", openAiOptimizeModal);
  els.aiUndo?.addEventListener("click", undoLastAiOptimization);
  els.aiOptimizeClose?.addEventListener("click", closeAiOptimizeModal);
  els.aiOptimizeCancel?.addEventListener("click", closeAiOptimizeModal);
  els.aiOptimizeGenerate?.addEventListener("click", () => void runAiOptimization(selectedAiOptimizeMode()));
  els.aiOptimizeApply?.addEventListener("click", applyAiOptimization);
  [els.aiModeLayout, els.aiModePolish].forEach((button) => {
    button?.addEventListener("click", () => chooseAiOptimizeMode(button.dataset.aiMode));
    button?.addEventListener("keydown", handleAiModeKeydown);
  });
  els.aiOptimizeModal?.addEventListener("click", (event) => {
    if (event.target === els.aiOptimizeModal) closeAiOptimizeModal();
  });
  els.aiOptimizeModal?.addEventListener("keydown", trapAiOptimizeModalFocus);
  els.illustration?.addEventListener("click", openIllustrationModal);
  els.illustrationClose?.addEventListener("click", closeIllustrationModal);
  els.illustrationCancel?.addEventListener("click", closeIllustrationModal);
  els.illustrationSearch?.addEventListener("click", () => void runIllustrationSearch());
  els.illustrationApply?.addEventListener("click", () => void applyIllustrationSelection());
  els.illustrationModal?.addEventListener("click", (event) => {
    if (event.target === els.illustrationModal) closeIllustrationModal();
  });
  els.illustrationModal?.addEventListener("keydown", trapIllustrationModalFocus);
  els.themeLibrary?.addEventListener("click", openThemeLibrary);
  els.themeLibraryClose?.addEventListener("click", closeThemeLibrary);
  els.themeLibraryModal?.addEventListener("click", (event) => {
    if (event.target === els.themeLibraryModal) closeThemeLibrary();
  });
  els.themeLibraryModal?.addEventListener("keydown", trapThemeLibraryFocus);
  els.themeLibraryGrid?.addEventListener("click", handleThemeLibrarySelection);
  els.themeLibraryFilters.forEach((button) => {
    button.addEventListener("click", () => renderThemeLibrary(button.dataset.themeFilter));
  });
  els.importProjects?.addEventListener("click", () => {
    closeProjectActionsMenu();
    els.projectBackupInput?.click();
  });
  els.projectBackupInput?.addEventListener("change", handleProjectBackupImport);
  els.importPreviewClose?.addEventListener("click", closeProjectImportPreview);
  els.importPreviewCancel?.addEventListener("click", closeProjectImportPreview);
  els.importPreviewConfirm?.addEventListener("click", confirmProjectBackupImport);
  els.importPreviewModal?.addEventListener("click", (event) => {
    if (event.target === els.importPreviewModal) closeProjectImportPreview();
  });
  els.assetLibrary?.addEventListener("click", openAssetLibrary);
  els.assetLibraryClose?.addEventListener("click", closeAssetLibrary);
  els.assetLibraryFolder?.addEventListener("click", selectLocalAssetDirectory);
  els.assetLibraryRefresh?.addEventListener("click", loadAssetLibrary);
  els.assetLibraryModal?.addEventListener("click", (event) => {
    if (event.target === els.assetLibraryModal) closeAssetLibrary();
  });
  els.headerModeToggle.addEventListener("click", toggleHeaderMode);
  els.uiThemeSwitch?.addEventListener("change", () => {
    setUiTheme(els.uiThemeSwitch.checked ? "dark" : "light", true, true);
  });
  setupApiConfig();
  els.articleSettingsToggle?.addEventListener("click", toggleArticleSettings);
  els.exportScale?.addEventListener("change", () => setExportScale(els.exportScale.value));
  els.downloadZip.addEventListener("click", async () => {
    await downloadAll();
    if (els.downloadMenu) els.downloadMenu.open = false;
  });
  els.downloadArticle.addEventListener("click", async () => {
    await downloadArticleImage();
    if (els.downloadMenu) els.downloadMenu.open = false;
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      if (localStateSaveTimer || localStateSaveMaxTimer) flushStateSave();
      if (localDatabaseSaveTimer) void flushProjectStoreToIndexedDb();
      if (sharedTextSaveTimer) void saveCurrentProjectTextToSharedServer({ keepalive: true });
    }
  });
  window.addEventListener("pagehide", () => {
    if (localStateSaveTimer || localStateSaveMaxTimer) flushStateSave();
    if (localDatabaseSaveTimer) void flushProjectStoreToIndexedDb();
    if (sharedTextSaveTimer) void saveCurrentProjectTextToSharedServer({ keepalive: true });
  });
}

loadPanelLayout();
applyPanelLayout();
setExportScale(loadExportScale(), false);
const initialFormState = loadState();
setUiTheme(loadUiTheme(initialFormState.uiTheme), false, true);
applyForm(initialFormState);
setPreviewViewMode(loadPreviewViewMode(), { persist: false });
syncGuideReadOnlyMode();
resetTextHistory();
updateProjectHistory();
bindEvents();
renderSaveCheckpoint();
syncAiUndoAvailability();
render({ persist: false })
  .then(hydrateProjectStoreFromIndexedDb)
  .then(restoreProjectBackupFromUrl);
void refreshPersistenceMode();
void loadObsidianVaultConnection();
void loadLocalAssetDirectoryConnection();
if (window.lucide) {
  window.lucide.createIcons();
}
