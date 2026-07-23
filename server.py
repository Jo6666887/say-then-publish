#!/usr/bin/env python3
"""Static server plus a small disk-backed project store shared by all browsers."""

from __future__ import annotations

import json
import os
import logging
import threading
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
from errno import EADDRINUSE
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from cloud_store import AssetInUseError, CloudStore, CloudStoreError
from local_asset_store import LocalAssetStore, LocalAssetStoreError
from ai_layout import (
    AILayoutDisabledError,
    AILayoutError,
    AILayoutProviderError,
    AILayoutResponseError,
    AILayoutService,
    AILayoutValidationError,
)


ROOT = Path(__file__).resolve().parent
DATA_DIR_SETTING = os.getenv("WRITE_THEN_PUBLISH_DATA_DIR", "runtime-data").strip() or "runtime-data"
DATA_DIR = Path(DATA_DIR_SETTING).expanduser()
if not DATA_DIR.is_absolute():
    DATA_DIR = ROOT / DATA_DIR
DATA_DIR = DATA_DIR.resolve()
STORE_FILE = DATA_DIR / "project-store.json"
MAX_BODY_BYTES = 64 * 1024 * 1024
MAX_TEXT_PATCH_BYTES = 2 * 1024 * 1024
MAX_AI_TEXT_BYTES = 2 * 1024 * 1024
STORE_LOCK = threading.Lock()
APP_URL = "http://127.0.0.1:5173/"
APP_SERVICE = "write-then-publish"
APP_HEALTH_SCHEMA = 1
CLOUD = CloudStore.from_root(ROOT)
AI_LAYOUT = AILayoutService.from_env()
LOCAL_ASSETS = LocalAssetStore(ROOT, data_dir=DATA_DIR)
AI_OPTIMIZE_LOCK = threading.Lock()
CLOUD_SYNC_LOCK = threading.Lock()
CLOUD_STATUS_LOCK = threading.Lock()
CLOUD_SYNC_TIMER_LOCK = threading.Lock()
CLOUD_SYNC_TIMER: threading.Timer | None = None
CLOUD_SYNC_PENDING = False
CLOUD_SYNC_WORKER_ACTIVE = False
CLOUD_SYNC_WAIT_SECONDS = 30.0
CLOUD_INITIAL_SYNC_WAIT_SECONDS = 5.0
CLOUD_INITIAL_SYNC_DONE = threading.Event()
# Module imports (including tests and embedded use) must never block API reads.
# The standalone launcher clears this immediately before it starts the initial
# background cloud reconciliation.
CLOUD_INITIAL_SYNC_DONE.set()
CLOUD_STATUS = {
    "enabled": CLOUD.enabled,
    "workspaceId": CLOUD.config.workspace_id,
    "backend": "supabase+tos" if CLOUD.enabled else None,
    "syncing": False,
    "syncingProjectId": None,
    "syncingUpdatedAt": None,
    "lastSuccessAt": None,
    "projectId": None,
    "syncedUpdatedAt": None,
    "lastError": CLOUD.disabled_reason or None,
    "fallbackToLocal": not CLOUD.enabled,
}
LOGGER = logging.getLogger("write-then-publish")
PUBLIC_STATIC_FILES = {"index.html"}
PUBLIC_STATIC_ROOTS = {"src", "docs/screenshots"}
PUBLIC_STATIC_SUFFIXES = {".css", ".gif", ".jpeg", ".jpg", ".js", ".png", ".svg", ".webp", ".woff2"}


def empty_store() -> dict:
    return {"activeId": None, "projects": [], "deletedProjects": []}


def read_store() -> dict:
    if not STORE_FILE.exists():
        return empty_store()
    try:
        payload = json.loads(STORE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_store()
    if not isinstance(payload, dict) or not isinstance(payload.get("projects"), list):
        return empty_store()
    return payload


def project_timestamp(project: dict) -> float:
    try:
        return float(project.get("updatedAt") or 0)
    except (TypeError, ValueError):
        return 0


def deletion_timestamp(deletion: dict) -> int:
    try:
        value = float(deletion.get("deletedAt") or 0)
    except (AttributeError, TypeError, ValueError):
        return 0
    return int(value) if value > 0 and value.is_integer() else 0


def normalized_deletions(store: dict) -> list[dict]:
    deletions: dict[str, dict] = {}
    source = store.get("deletedProjects") if isinstance(store, dict) else None
    for deletion in source if isinstance(source, list) else []:
        project_id = deletion.get("id") if isinstance(deletion, dict) else None
        deleted_at = deletion_timestamp(deletion)
        if not isinstance(project_id, str) or not project_id or not deleted_at:
            continue
        previous = deletions.get(project_id)
        if previous is None or deleted_at > deletion_timestamp(previous):
            deletions[project_id] = {"id": project_id, "deletedAt": deleted_at}
    return sorted(deletions.values(), key=deletion_timestamp, reverse=True)


def find_deletion(store: dict, project_id: str | None) -> dict | None:
    if not isinstance(project_id, str) or not project_id:
        return None
    return next(
        (deletion for deletion in normalized_deletions(store) if deletion["id"] == project_id),
        None,
    )


def project_checkpoint(store: dict, project_id: str | None = None) -> dict:
    """Return a public, content-free checkpoint for one saved project."""

    projects = store.get("projects") if isinstance(store, dict) else None
    if not isinstance(projects, list):
        return {"projectId": None, "updatedAt": None}
    requested_id = project_id or store.get("activeId")
    project = next(
        (
            candidate
            for candidate in projects
            if isinstance(candidate, dict) and candidate.get("id") == requested_id
        ),
        None,
    )
    if project is None:
        project = next((candidate for candidate in projects if isinstance(candidate, dict)), None)
    if project is None or not isinstance(project.get("id"), str):
        return {"projectId": None, "updatedAt": None}
    return {
        "projectId": project["id"],
        "updatedAt": int(project_timestamp(project)),
    }


def find_project(store: dict, project_id: str | None) -> dict | None:
    if not isinstance(project_id, str) or not project_id:
        return None
    projects = store.get("projects") if isinstance(store, dict) else None
    if not isinstance(projects, list):
        return None
    return next(
        (
            project
            for project in projects
            if isinstance(project, dict) and project.get("id") == project_id
        ),
        None,
    )


def project_content(project: dict | None) -> str | None:
    data = project.get("data") if isinstance(project, dict) else None
    content = data.get("content") if isinstance(data, dict) else None
    return content if isinstance(content, str) else None


def parse_updated_at(value: object) -> int | None:
    """Accept the millisecond integer used as the project revision token."""

    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not numeric.is_integer() or numeric <= 0:
        return None
    try:
        return int(numeric)
    except (OverflowError, ValueError):
        return None


def project_revision_matches(
    project: dict | None,
    *,
    project_id: str,
    updated_at: int,
    content: str,
) -> bool:
    return (
        isinstance(project, dict)
        and project.get("id") == project_id
        and parse_updated_at(project.get("updatedAt")) == updated_at
        and project_content(project) == content
    )


def project_payload_matches(first: dict | None, second: dict | None) -> bool:
    if not isinstance(first, dict) or not isinstance(second, dict):
        return False
    try:
        # Storage backends enrich an otherwise immutable revision with derived
        # cloud/local asset indexes. Compare the logical project (including image
        # bytes and layout), not those transport-only keys.
        return CloudStore._project_payload(first) == CloudStore._project_payload(second)
    except (CloudStoreError, TypeError, ValueError):
        return False


def store_confirms_snapshot(current: dict, incoming: dict) -> bool:
    incoming_projects = incoming.get("projects") if isinstance(incoming, dict) else None
    for project in incoming_projects if isinstance(incoming_projects, list) else []:
        if not isinstance(project, dict) or not isinstance(project.get("id"), str):
            return False
        if not project_payload_matches(find_project(current, project["id"]), project):
            return False
    for deletion in normalized_deletions(incoming):
        confirmed = find_deletion(current, deletion["id"])
        if confirmed is None or deletion_timestamp(confirmed) < deletion_timestamp(deletion):
            return False
    return True


def save_conflict_payload(project: dict | None) -> dict:
    return {
        "error": "本机已有不同版本，请刷新后再保存",
        "code": "DRAFT_VERSION_CONFLICT",
        "current": {
            "projectId": project.get("id") if isinstance(project, dict) else None,
            "updatedAt": parse_updated_at(project.get("updatedAt")) if isinstance(project, dict) else None,
        },
    }


def merge_store(current: dict, incoming: dict) -> dict:
    merged: dict[str, dict] = {}
    for project in [*(current.get("projects") or []), *(incoming.get("projects") or [])]:
        if not isinstance(project, dict) or not isinstance(project.get("id"), str):
            continue
        previous = merged.get(project["id"])
        # Equal revisions are immutable. Keeping the existing complete object avoids
        # a late text-only/cache response replacing images or layout at the same time.
        if previous is None or project_timestamp(project) > project_timestamp(previous):
            merged[project["id"]] = project

    deletions: dict[str, dict] = {}
    for deletion in [*normalized_deletions(current), *normalized_deletions(incoming)]:
        previous = deletions.get(deletion["id"])
        if previous is None or deletion_timestamp(deletion) > deletion_timestamp(previous):
            deletions[deletion["id"]] = deletion

    winning_deletions = {
        project_id: deletion
        for project_id, deletion in deletions.items()
        if project_id not in merged
        or deletion_timestamp(deletion) >= project_timestamp(merged[project_id])
    }
    projects = [
        project
        for project_id, project in merged.items()
        if project_id not in winning_deletions
    ]
    projects = sorted(projects, key=project_timestamp, reverse=True)[:24]
    project_ids = {project["id"] for project in projects}
    incoming_active = incoming.get("activeId")
    current_active = current.get("activeId")
    active_id = incoming_active if incoming_active in project_ids else current_active if current_active in project_ids else (projects[0]["id"] if projects else None)
    return {
        "activeId": active_id,
        "projects": projects,
        "deletedProjects": sorted(
            winning_deletions.values(),
            key=deletion_timestamp,
            reverse=True,
        ),
    }


def write_store(payload: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = STORE_FILE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, STORE_FILE)


def cloud_status() -> dict:
    with CLOUD_STATUS_LOCK:
        return dict(CLOUD_STATUS)


def safe_cloud_error(error: Exception) -> str:
    """Keep operational errors useful without returning configured credentials."""

    message = str(error)
    config = getattr(CLOUD, "config", None)
    secrets = (
        getattr(config, "supabase_secret_key", ""),
        getattr(config, "tos_access_key", ""),
        getattr(config, "tos_secret_key", ""),
    )
    for secret in secrets:
        if isinstance(secret, str) and secret:
            message = message.replace(secret, "[REDACTED]")
    return message[:1000]


def record_cloud_failure(error: Exception) -> None:
    with CLOUD_STATUS_LOCK:
        CLOUD_STATUS["lastError"] = safe_cloud_error(error)
        CLOUD_STATUS["fallbackToLocal"] = True


def sync_local_asset_store() -> dict:
    """Persist embedded project images in the trusted server-side directory."""
    with STORE_LOCK:
        current = read_store()
        enriched = LOCAL_ASSETS.sync_store(current)
        if enriched != current:
            write_store(enriched)
        return json.loads(json.dumps(enriched, ensure_ascii=False))


def local_asset_library_payload(*, reason: str | None = None) -> dict:
    status = cloud_status()
    if reason:
        status["lastError"] = reason
    if LOCAL_ASSETS.directory_selection_required:
        return {
            "assets": [],
            "cloudEnabled": False,
            "storageMode": "local-server",
            "folderName": "",
            "directorySelectionRequired": True,
            "status": status,
        }
    store = sync_local_asset_store()
    return {
        "assets": LOCAL_ASSETS.list_assets(store),
        "cloudEnabled": False,
        "storageMode": "local-server",
        "folderName": LOCAL_ASSETS.folder_name,
        "directorySelectionRequired": False,
        "status": status,
    }


def checkpoint_is_confirmed(status: dict, project_id: str | None, updated_at: int | None) -> bool:
    if not project_id or updated_at is None:
        return False
    try:
        synced_updated_at = int(status.get("syncedUpdatedAt"))
    except (TypeError, ValueError):
        return False
    return (
        status.get("projectId") == project_id
        and synced_updated_at == int(updated_at)
        and status.get("fallbackToLocal") is not True
        and not status.get("lastError")
    )


def sync_cloud_store(
    *,
    wait_for_existing: bool = False,
    target_project_id: str | None = None,
    target_updated_at: int | None = None,
    wait_timeout: float | None = CLOUD_SYNC_WAIT_SECONDS,
) -> bool:
    if not CLOUD.enabled:
        return False
    if wait_for_existing:
        acquired = (
            CLOUD_SYNC_LOCK.acquire()
            if wait_timeout is None
            else CLOUD_SYNC_LOCK.acquire(timeout=max(0.0, wait_timeout))
        )
    else:
        acquired = CLOUD_SYNC_LOCK.acquire(blocking=False)
    if not acquired:
        return False

    local_store = empty_store()
    try:
        # A manual save may arrive while the debounced background sync is still
        # running. Reuse it only when it explicitly confirms this project version.
        if wait_for_existing and checkpoint_is_confirmed(
            cloud_status(),
            target_project_id,
            target_updated_at,
        ):
            return True

        with STORE_LOCK:
            local_store = json.loads(json.dumps(read_store(), ensure_ascii=False))
        target = project_checkpoint(local_store, target_project_id)
        if target_project_id and (
            target["projectId"] != target_project_id
            or target_updated_at is None
            or target["updatedAt"] != int(target_updated_at)
        ):
            return False
        with CLOUD_STATUS_LOCK:
            CLOUD_STATUS["syncing"] = True
            CLOUD_STATUS["syncingProjectId"] = target["projectId"]
            CLOUD_STATUS["syncingUpdatedAt"] = target["updatedAt"]
            CLOUD_STATUS["lastError"] = None
        merged = CLOUD.sync_store(local_store)
        synced = project_checkpoint(merged, target_project_id or target["projectId"])
        with STORE_LOCK:
            current_store = read_store()
            write_store(merged if current_store == local_store else merge_store(current_store, merged))
        with CLOUD_STATUS_LOCK:
            CLOUD_STATUS["lastSuccessAt"] = datetime_now_iso()
            CLOUD_STATUS["projectId"] = synced["projectId"]
            CLOUD_STATUS["syncedUpdatedAt"] = synced["updatedAt"]
            CLOUD_STATUS["fallbackToLocal"] = False
        if target_project_id and (
            synced["projectId"] != target_project_id
            or synced["updatedAt"] is None
            or target_updated_at is None
            or synced["updatedAt"] != int(target_updated_at)
        ):
            return False
        return True
    except Exception as error:
        LOGGER.exception("Cloud sync failed")
        record_cloud_failure(error)
        try:
            merged = LOCAL_ASSETS.sync_store(local_store)
            with STORE_LOCK:
                current_store = read_store()
                write_store(merged if current_store == local_store else merge_store(current_store, merged))
        except LocalAssetStoreError:
            LOGGER.exception("Local asset fallback sync failed")
        return False
    finally:
        with CLOUD_STATUS_LOCK:
            CLOUD_STATUS["syncing"] = False
            CLOUD_STATUS["syncingProjectId"] = None
            CLOUD_STATUS["syncingUpdatedAt"] = None
        CLOUD_SYNC_LOCK.release()


def datetime_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def public_static_path(path: str) -> bool:
    """Only expose browser assets, never the project root or local data."""
    decoded = unquote(path or "/")
    if decoded == "/":
        return True
    parts = [part for part in decoded.split("/") if part]
    if not parts or any(part in {".", ".."} or part.startswith(".") for part in parts):
        return False
    relative = "/".join(parts)
    if relative in PUBLIC_STATIC_FILES:
        candidate = (ROOT / relative).resolve()
        return candidate.parent == ROOT.resolve()
    if Path(relative).suffix.lower() not in PUBLIC_STATIC_SUFFIXES:
        return False
    candidate = (ROOT / relative).resolve()
    return any(
        relative.startswith(f"{root}/") and candidate.is_relative_to((ROOT / root).resolve())
        for root in PUBLIC_STATIC_ROOTS
    )


def _start_cloud_sync_timer_locked(delay: float) -> None:
    global CLOUD_SYNC_TIMER
    if CLOUD_SYNC_TIMER:
        CLOUD_SYNC_TIMER.cancel()
    CLOUD_SYNC_TIMER = threading.Timer(max(0.0, delay), _run_scheduled_cloud_sync)
    CLOUD_SYNC_TIMER.daemon = True
    CLOUD_SYNC_TIMER.start()


def _run_scheduled_cloud_sync() -> None:
    """Drain one debounced save without dropping changes behind a busy sync."""

    global CLOUD_SYNC_PENDING, CLOUD_SYNC_TIMER, CLOUD_SYNC_WORKER_ACTIVE
    with CLOUD_SYNC_TIMER_LOCK:
        if CLOUD_SYNC_TIMER is not threading.current_thread():
            return
        CLOUD_SYNC_TIMER = None
        if CLOUD_SYNC_WORKER_ACTIVE:
            CLOUD_SYNC_PENDING = True
            return
        if not CLOUD.enabled:
            CLOUD_SYNC_PENDING = False
            return
        if not CLOUD_SYNC_PENDING:
            return
        CLOUD_SYNC_PENDING = False
        CLOUD_SYNC_WORKER_ACTIVE = True

    try:
        # A scheduler worker may wait behind startup/manual sync. It then reads
        # the latest disk snapshot, so the final edit is never discarded merely
        # because CLOUD_SYNC_LOCK was busy when the debounce timer fired.
        sync_cloud_store(wait_for_existing=True, wait_timeout=None)
    finally:
        with CLOUD_SYNC_TIMER_LOCK:
            CLOUD_SYNC_WORKER_ACTIVE = False
            if CLOUD_SYNC_PENDING and CLOUD.enabled:
                _start_cloud_sync_timer_locked(0.15)


def schedule_cloud_sync(delay: float = 1.2) -> None:
    global CLOUD_SYNC_PENDING
    if not CLOUD.enabled:
        return
    with CLOUD_SYNC_TIMER_LOCK:
        CLOUD_SYNC_PENDING = True
        if not CLOUD_SYNC_WORKER_ACTIVE:
            _start_cloud_sync_timer_locked(delay)


def cancel_scheduled_cloud_sync() -> None:
    global CLOUD_SYNC_PENDING, CLOUD_SYNC_TIMER
    with CLOUD_SYNC_TIMER_LOCK:
        timer = CLOUD_SYNC_TIMER
        CLOUD_SYNC_TIMER = None
        CLOUD_SYNC_PENDING = False
    if timer:
        timer.cancel()


class WriteThenPublishHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        if not urlparse(self.path).path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        super().end_headers()

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def send_bytes(self, payload: bytes, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "private, max-age=300")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "sandbox; default-src 'none'")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.end_headers()
        self.wfile.write(payload)

    def read_json_body(self, maximum: int = MAX_BODY_BYTES) -> dict | None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if content_length <= 0 or content_length > maximum:
            return None
        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def reject_cross_origin_mutation(self) -> bool:
        """Block browser cross-site form/fetch requests to the localhost service."""

        origin = self.headers.get("Origin", "").strip()
        fetch_site = self.headers.get("Sec-Fetch-Site", "").strip().lower()
        host = self.headers.get("Host", "").strip()
        if fetch_site == "cross-site":
            self.send_json({"error": "已拒绝跨站请求"}, HTTPStatus.FORBIDDEN)
            return True
        if origin:
            parsed = urlparse(origin)
            if parsed.scheme not in {"http", "https"} or parsed.netloc != host:
                self.send_json({"error": "已拒绝跨站请求"}, HTTPStatus.FORBIDDEN)
                return True
        return False

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        path = urlparse(self.path).path
        if path == "/api/health":
            self.send_json(
                {
                    "ok": True,
                    "service": APP_SERVICE,
                    "schema": APP_HEALTH_SCHEMA,
                }
            )
            return
        if path == "/api/project-store":
            if CLOUD.enabled and not CLOUD_INITIAL_SYNC_DONE.is_set():
                CLOUD_INITIAL_SYNC_DONE.wait(timeout=CLOUD_INITIAL_SYNC_WAIT_SECONDS)
            with STORE_LOCK:
                payload = read_store()
            self.send_json(payload)
            return
        if path == "/api/cloud-status":
            self.send_json(cloud_status())
            return
        if path == "/api/ai/status":
            self.send_json(AI_LAYOUT.status())
            return
        if path == "/api/assets":
            if not CLOUD.enabled or cloud_status().get("fallbackToLocal"):
                try:
                    reason = cloud_status().get("lastError") or CLOUD.disabled_reason
                    self.send_json(local_asset_library_payload(reason=reason))
                except LocalAssetStoreError as error:
                    self.send_json({"error": str(error)}, HTTPStatus.BAD_GATEWAY)
                return
            try:
                with STORE_LOCK:
                    store = json.loads(json.dumps(read_store(), ensure_ascii=False))
                assets = CLOUD.list_assets(store)
            except CloudStoreError as error:
                record_cloud_failure(error)
                try:
                    self.send_json(local_asset_library_payload(reason=safe_cloud_error(error)))
                except LocalAssetStoreError as local_error:
                    self.send_json({"error": str(local_error)}, HTTPStatus.BAD_GATEWAY)
                return
            self.send_json({"assets": assets, "cloudEnabled": True, "status": cloud_status()})
            return
        if path.startswith("/api/assets/"):
            parts = path.removeprefix("/api/assets/").split("/")
            asset_id = unquote(parts[0])
            backend = LOCAL_ASSETS if asset_id.startswith("local-") else CLOUD
            try:
                if len(parts) == 2 and parts[1] == "content":
                    asset, raw = backend.get_asset(asset_id)
                    self.send_bytes(raw, asset.get("mime_type") or "application/octet-stream")
                    return
                if len(parts) == 1:
                    with STORE_LOCK:
                        store = json.loads(json.dumps(read_store(), ensure_ascii=False))
                    self.send_json(backend.get_asset_payload(asset_id, store))
                    return
            except CloudStoreError as error:
                missing = str(error) == "找不到该资源"
                if backend is CLOUD and not missing:
                    record_cloud_failure(error)
                    try:
                        sync_local_asset_store()
                    except LocalAssetStoreError:
                        LOGGER.exception("Local asset fallback sync failed")
                self.send_json(
                    {
                        "error": safe_cloud_error(error)
                        if backend is CLOUD
                        else str(error)
                    },
                    HTTPStatus.NOT_FOUND if missing else HTTPStatus.BAD_GATEWAY,
                )
                return
        if not public_static_path(path):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        return super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib handler API
        path = urlparse(self.path).path
        if path.startswith("/api/") or not public_static_path(path):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        return super().do_HEAD()

    def do_PUT(self) -> None:  # noqa: N802 - stdlib handler API
        if self.reject_cross_origin_mutation():
            return
        if urlparse(self.path).path != "/api/project-store":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if content_length <= 0 or content_length > MAX_BODY_BYTES:
            self.send_json({"error": "草稿数据大小无效"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        try:
            incoming = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json({"error": "草稿 JSON 无效"}, HTTPStatus.BAD_REQUEST)
            return
        if not isinstance(incoming, dict) or not isinstance(incoming.get("projects"), list):
            self.send_json({"error": "草稿结构无效"}, HTTPStatus.BAD_REQUEST)
            return

        incoming_project_id = incoming.get("activeId")
        incoming_project = find_project(incoming, incoming_project_id)
        incoming_updated_at = (
            parse_updated_at(incoming_project.get("updatedAt"))
            if incoming_project is not None
            else None
        )
        incoming_content = project_content(incoming_project)
        if incoming_project is not None and (
            incoming_updated_at is None or incoming_content is None
        ):
            self.send_json({"error": "当前草稿版本无效"}, HTTPStatus.BAD_REQUEST)
            return

        with STORE_LOCK:
            current_store = read_store()
            current_project = find_project(current_store, incoming_project_id)
            current_updated_at = (
                parse_updated_at(current_project.get("updatedAt"))
                if current_project is not None
                else None
            )
            if incoming_project is not None and current_project is not None and (
                current_updated_at is not None
                and (
                    incoming_updated_at < current_updated_at
                    or (
                        incoming_updated_at == current_updated_at
                        and not project_payload_matches(current_project, incoming_project)
                    )
                )
            ):
                self.send_json(save_conflict_payload(current_project), HTTPStatus.CONFLICT)
                return
            merged = merge_store(current_store, incoming)
            write_store(merged)

        response_store = merged
        local_fallback = not CLOUD.enabled or cloud_status().get("fallbackToLocal")
        if local_fallback and not LOCAL_ASSETS.directory_selection_required:
            try:
                enriched = LOCAL_ASSETS.sync_store(merged)
                with STORE_LOCK:
                    current_store = read_store()
                    response_store = enriched if current_store == merged else merge_store(current_store, enriched)
                    write_store(response_store)
            except LocalAssetStoreError:
                # A missing/unwritable asset folder must never block draft persistence.
                LOGGER.exception("Local asset fallback sync failed after draft save")

        with STORE_LOCK:
            response_store = json.loads(json.dumps(read_store(), ensure_ascii=False))
        confirmed_project = find_project(response_store, incoming_project_id)
        revision_confirmed = bool(
            incoming_project is not None
            and incoming_updated_at is not None
            and incoming_content is not None
            and project_payload_matches(confirmed_project, incoming_project)
        )
        snapshot_confirmed = store_confirms_snapshot(response_store, incoming)
        if not snapshot_confirmed:
            self.send_json(save_conflict_payload(confirmed_project), HTTPStatus.CONFLICT)
            return

        schedule_cloud_sync()
        response_payload = dict(response_store)
        response_payload["saveMeta"] = {
            "saved": snapshot_confirmed,
            "snapshotSaved": snapshot_confirmed,
            "destination": "local-server",
            "savedAt": datetime_now_iso(),
            "projectId": incoming_project_id if revision_confirmed else None,
            "savedUpdatedAt": incoming_updated_at if revision_confirmed else None,
            "deletedProjects": normalized_deletions(incoming),
            "cloudSyncScheduled": CLOUD.enabled,
        }
        self.send_json(response_payload)

    def do_PATCH(self) -> None:  # noqa: N802 - stdlib handler API
        if self.reject_cross_origin_mutation():
            return
        if urlparse(self.path).path != "/api/project-store/current-text":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if content_length <= 0 or content_length > MAX_TEXT_PATCH_BYTES:
            self.send_json({"error": "正文数据大小无效"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        try:
            incoming = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json({"error": "正文 JSON 无效"}, HTTPStatus.BAD_REQUEST)
            return

        project_id = incoming.get("id") if isinstance(incoming, dict) else None
        content = incoming.get("content") if isinstance(incoming, dict) else None
        incoming_updated_at = (
            parse_updated_at(incoming.get("updatedAt"))
            if isinstance(incoming, dict)
            else None
        )
        if (
            not isinstance(project_id, str)
            or not isinstance(content, str)
            or incoming_updated_at is None
        ):
            self.send_json({"error": "正文草稿结构无效"}, HTTPStatus.BAD_REQUEST)
            return

        with STORE_LOCK:
            store = read_store()
            projects = store.get("projects") or []
            matched = False
            for index, project in enumerate(projects):
                if not isinstance(project, dict) or project.get("id") != project_id:
                    continue
                current_updated_at = parse_updated_at(project.get("updatedAt")) or 0
                if incoming_updated_at < current_updated_at or (
                    incoming_updated_at == current_updated_at
                    and project_content(project) != content
                ):
                    self.send_json(save_conflict_payload(project), HTTPStatus.CONFLICT)
                    return
                if incoming_updated_at > current_updated_at:
                    patched = dict(project)
                    patched_data = dict(project.get("data") or {})
                    patched_data["content"] = content
                    patched["data"] = patched_data
                    title = incoming.get("title")
                    if isinstance(title, str) and title.strip():
                        patched["title"] = title.strip()[:40]
                    patched["updatedAt"] = incoming_updated_at
                    projects[index] = patched
                matched = True
                break

            if not matched:
                self.send_json({"error": "找不到对应草稿"}, HTTPStatus.NOT_FOUND)
                return

            projects = sorted(projects, key=project_timestamp, reverse=True)[:24]
            store = {
                "activeId": project_id,
                "projects": projects,
                "deletedProjects": normalized_deletions(store),
            }
            write_store(store)

        confirmed_project = find_project(store, project_id)
        if not project_revision_matches(
            confirmed_project,
            project_id=project_id,
            updated_at=incoming_updated_at,
            content=content,
        ):
            self.send_json(save_conflict_payload(confirmed_project), HTTPStatus.CONFLICT)
            return
        # Do not publish a text-only object as a complete cloud revision. The
        # debounced full-store PUT carries text, images and layout atomically.
        self.send_json(
            {
                "ok": True,
                "id": project_id,
                "saveMeta": {
                    "saved": True,
                    "destination": "local-server",
                    "savedAt": datetime_now_iso(),
                    "projectId": project_id,
                    "savedUpdatedAt": incoming_updated_at,
                    "cloudSyncScheduled": CLOUD.enabled,
                },
            }
        )

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if self.reject_cross_origin_mutation():
            return
        path = urlparse(self.path).path
        if path == "/api/ai/optimize-layout":
            payload = self.read_json_body(maximum=MAX_AI_TEXT_BYTES)
            if not payload:
                self.send_json({"error": "AI 优化请求无效", "code": "INVALID_REQUEST"}, HTTPStatus.BAD_REQUEST)
                return
            content = payload.get("content")
            project_id = payload.get("projectId")
            mode = payload.get("mode", "layout")
            accent_color = payload.get("accentColor", "#5B5FEF")
            try:
                base_updated_at = int(payload.get("baseUpdatedAt"))
            except (TypeError, ValueError):
                base_updated_at = 0
            if not isinstance(content, str) or not isinstance(project_id, str) or not project_id or base_updated_at <= 0:
                self.send_json({"error": "请先保存当前草稿，再使用 AI 优化", "code": "UNSAVED_DRAFT"}, HTTPStatus.CONFLICT)
                return
            if not isinstance(mode, str):
                self.send_json({"error": "不支持的 AI 优化模式", "code": "INVALID_MODE"}, HTTPStatus.BAD_REQUEST)
                return
            if not isinstance(accent_color, str):
                self.send_json({"error": "主题色格式无效", "code": "INVALID_ACCENT_COLOR"}, HTTPStatus.BAD_REQUEST)
                return

            with STORE_LOCK:
                before_store = read_store()
                before_project = next(
                    (item for item in before_store.get("projects", []) if isinstance(item, dict) and item.get("id") == project_id),
                    None,
                )
            before_content = (before_project.get("data") or {}).get("content") if before_project else None
            if (
                before_project is None
                or int(project_timestamp(before_project)) != base_updated_at
                or before_content != content
            ):
                self.send_json({"error": "正文已有新修改，请保存后重新优化", "code": "DRAFT_VERSION_CONFLICT"}, HTTPStatus.CONFLICT)
                return

            if not AI_OPTIMIZE_LOCK.acquire(blocking=False):
                self.send_json(
                    {
                        "error": "上一条 AI 优化仍在生成，请稍后再试",
                        "code": "AI_REQUEST_IN_PROGRESS",
                    },
                    HTTPStatus.CONFLICT,
                )
                return
            try:
                try:
                    result = AI_LAYOUT.optimize(content, mode=mode, accent_color=accent_color)
                except AILayoutDisabledError as error:
                    self.send_json({"error": str(error), "code": error.code}, HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                except AILayoutValidationError as error:
                    self.send_json({"error": str(error), "code": error.code}, HTTPStatus.BAD_REQUEST)
                    return
                except (AILayoutProviderError, AILayoutResponseError) as error:
                    self.send_json({"error": str(error), "code": error.code}, HTTPStatus.BAD_GATEWAY)
                    return
                except AILayoutError as error:
                    self.send_json({"error": str(error), "code": error.code}, HTTPStatus.BAD_GATEWAY)
                    return
            finally:
                AI_OPTIMIZE_LOCK.release()

            with STORE_LOCK:
                after_store = read_store()
                after_project = next(
                    (item for item in after_store.get("projects", []) if isinstance(item, dict) and item.get("id") == project_id),
                    None,
                )
            after_content = (after_project.get("data") or {}).get("content") if after_project else None
            if (
                after_project is None
                or int(project_timestamp(after_project)) != base_updated_at
                or after_content != content
            ):
                self.send_json({"error": "AI 生成期间正文已更新，结果未应用", "code": "DRAFT_VERSION_CONFLICT"}, HTTPStatus.CONFLICT)
                return
            response = result.as_dict()
            response["requestId"] = uuid.uuid4().hex
            response["baseUpdatedAt"] = base_updated_at
            self.send_json(response)
            return
        if path == "/api/local-assets/select-directory":
            try:
                result = LOCAL_ASSETS.select_asset_directory()
                if result.get("cancelled"):
                    self.send_json(result, HTTPStatus.CONFLICT)
                    return
                store = sync_local_asset_store()
                result["assetCount"] = len(LOCAL_ASSETS.list_assets(store))
                self.send_json(result)
            except LocalAssetStoreError as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_GATEWAY)
            return
        if path != "/api/cloud-sync":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not CLOUD.enabled:
            self.send_json({"error": CLOUD.disabled_reason}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        with STORE_LOCK:
            target = project_checkpoint(read_store())
        cancel_scheduled_cloud_sync()
        success = sync_cloud_store(
            wait_for_existing=True,
            target_project_id=target["projectId"],
            target_updated_at=target["updatedAt"],
        )
        status = cloud_status()
        self.send_json(
            {
                "ok": success,
                "status": status,
                "checkpoint": {
                    "projectId": target["projectId"],
                    "requestedUpdatedAt": target["updatedAt"],
                    "confirmed": checkpoint_is_confirmed(
                        status,
                        target["projectId"],
                        target["updatedAt"],
                    ),
                },
            },
            HTTPStatus.OK if success else HTTPStatus.BAD_GATEWAY,
        )

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib handler API
        if self.reject_cross_origin_mutation():
            return
        path = urlparse(self.path).path
        if path.startswith("/api/project-store/") and "/" not in path.removeprefix("/api/project-store/"):
            payload = self.read_json_body(maximum=4096)
            if not payload or payload.get("confirm") is not True:
                self.send_json({"error": "必须明确确认删除"}, HTTPStatus.BAD_REQUEST)
                return
            project_id = unquote(path.removeprefix("/api/project-store/"))
            if not project_id or project_id.startswith("guide_"):
                self.send_json({"error": "该项目不可删除"}, HTTPStatus.BAD_REQUEST)
                return

            requested_deleted_at = parse_updated_at(payload.get("deletedAt")) or 0
            with STORE_LOCK:
                current = read_store()
                project = find_project(current, project_id)
                previous_deletion = find_deletion(current, project_id)
                deleted_at = max(
                    int(time.time() * 1000),
                    requested_deleted_at,
                    int(project_timestamp(project)) + 1 if project else 0,
                    deletion_timestamp(previous_deletion) if previous_deletion else 0,
                )
                incoming = {
                    "activeId": payload.get("activeId"),
                    "projects": [],
                    "deletedProjects": [{"id": project_id, "deletedAt": deleted_at}],
                }
                store = merge_store(current, incoming)
                write_store(store)

            cloud_deleted = False
            cloud_error = None
            if CLOUD.enabled:
                try:
                    confirmed_deleted_at = CLOUD.delete_project(
                        project_id,
                        deleted_at,
                        active_id=store.get("activeId"),
                    )
                    if confirmed_deleted_at > deleted_at:
                        with STORE_LOCK:
                            store = merge_store(
                                read_store(),
                                {
                                    "activeId": store.get("activeId"),
                                    "projects": [],
                                    "deletedProjects": [
                                        {"id": project_id, "deletedAt": confirmed_deleted_at}
                                    ],
                                },
                            )
                            write_store(store)
                        deleted_at = confirmed_deleted_at
                    cloud_deleted = True
                except Exception as error:
                    LOGGER.exception("Cloud project deletion failed")
                    record_cloud_failure(error)
                    cloud_error = safe_cloud_error(error)

            # A single tombstone confirmation does not prove the complete store
            # is healthy. Reconcile the whole snapshot before clearing cloud errors.
            schedule_cloud_sync()
            self.send_json(
                {
                    "ok": True,
                    "store": store,
                    "deletionMeta": {
                        "projectId": project_id,
                        "deletedAt": deleted_at,
                        "localSaved": True,
                        "cloudDeleted": cloud_deleted,
                        "cloudError": cloud_error,
                    },
                }
            )
            return
        if not path.startswith("/api/assets/") or "/" in path.removeprefix("/api/assets/"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        payload = self.read_json_body(maximum=4096)
        if not payload or payload.get("confirm") is not True:
            self.send_json({"error": "必须明确确认删除"}, HTTPStatus.BAD_REQUEST)
            return
        asset_id = unquote(path.removeprefix("/api/assets/"))
        backend = LOCAL_ASSETS if asset_id.startswith("local-") else CLOUD
        try:
            with STORE_LOCK:
                store = json.loads(json.dumps(read_store(), ensure_ascii=False))
            backend.delete_asset(asset_id, store, force=payload.get("force") is True)
        except AssetInUseError as error:
            self.send_json(
                {"error": str(error), "referenceCount": error.reference_count},
                HTTPStatus.CONFLICT,
            )
            return
        except CloudStoreError as error:
            if backend is CLOUD:
                record_cloud_failure(error)
            self.send_json(
                {
                    "error": safe_cloud_error(error)
                    if backend is CLOUD
                    else str(error)
                },
                HTTPStatus.BAD_GATEWAY,
            )
            return
        self.send_json({"ok": True})


def existing_app_is_healthy() -> bool:
    try:
        with urllib.request.urlopen(f"{APP_URL}api/health", timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("ok") is True
        and payload.get("service") == APP_SERVICE
        and payload.get("schema") == APP_HEALTH_SCHEMA
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    handler = partial(WriteThenPublishHandler, directory=str(ROOT))
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 5173), handler)
    except OSError as error:
        if error.errno == EADDRINUSE and existing_app_is_healthy():
            print(f"写了就发已经在运行：{APP_URL}", flush=True)
            print("正在打开浏览器……", flush=True)
            webbrowser.open(APP_URL)
            raise SystemExit(0)
        raise
    print(f"Write Then Publish: {APP_URL}", flush=True)
    print(f"共享草稿库: {STORE_FILE}", flush=True)
    if CLOUD.enabled:
        print("正在后台核对 Supabase + TOS 云端版本……", flush=True)
        CLOUD_INITIAL_SYNC_DONE.clear()

        def initial_cloud_sync() -> None:
            try:
                if sync_cloud_store(wait_for_existing=True, wait_timeout=None):
                    print("云端版本核对完成。", flush=True)
                else:
                    print("云端暂不可用，已降级为本机副本。", flush=True)
            finally:
                CLOUD_INITIAL_SYNC_DONE.set()

        threading.Thread(target=initial_cloud_sync, name="cloud-sync-startup", daemon=True).start()
    else:
        print(f"云同步未启用：{CLOUD.disabled_reason}", flush=True)
    threading.Timer(0.4, webbrowser.open, args=(APP_URL,)).start()
    server.serve_forever()
