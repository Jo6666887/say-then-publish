#!/usr/bin/env python3
"""Static server plus a small disk-backed project store shared by all browsers."""

from __future__ import annotations

import json
import os
import logging
import threading
import urllib.error
import urllib.request
import webbrowser
from errno import EADDRINUSE
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from cloud_store import AssetInUseError, CloudStore, CloudStoreError
from local_asset_store import LocalAssetStore, LocalAssetStoreError


ROOT = Path(__file__).resolve().parent
DATA_DIR_SETTING = os.getenv("WRITE_THEN_PUBLISH_DATA_DIR", "runtime-data").strip() or "runtime-data"
DATA_DIR = Path(DATA_DIR_SETTING).expanduser()
if not DATA_DIR.is_absolute():
    DATA_DIR = ROOT / DATA_DIR
DATA_DIR = DATA_DIR.resolve()
STORE_FILE = DATA_DIR / "project-store.json"
MAX_BODY_BYTES = 64 * 1024 * 1024
MAX_TEXT_PATCH_BYTES = 2 * 1024 * 1024
STORE_LOCK = threading.Lock()
APP_URL = "http://127.0.0.1:5173/"
CLOUD = CloudStore.from_root(ROOT)
LOCAL_ASSETS = LocalAssetStore(ROOT, data_dir=DATA_DIR)
CLOUD_SYNC_LOCK = threading.Lock()
CLOUD_STATUS_LOCK = threading.Lock()
CLOUD_SYNC_TIMER_LOCK = threading.Lock()
CLOUD_SYNC_TIMER: threading.Timer | None = None
CLOUD_STATUS = {
    "enabled": CLOUD.enabled,
    "workspaceId": CLOUD.config.workspace_id,
    "backend": "supabase+tos" if CLOUD.enabled else None,
    "syncing": False,
    "lastSuccessAt": None,
    "lastError": CLOUD.disabled_reason or None,
    "fallbackToLocal": not CLOUD.enabled,
}
LOGGER = logging.getLogger("write-then-publish")
PUBLIC_STATIC_FILES = {"index.html"}
PUBLIC_STATIC_ROOTS = {"src", "docs/screenshots"}
PUBLIC_STATIC_SUFFIXES = {".css", ".gif", ".jpeg", ".jpg", ".js", ".png", ".svg", ".webp", ".woff2"}


def empty_store() -> dict:
    return {"activeId": None, "projects": []}


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


def merge_store(current: dict, incoming: dict) -> dict:
    merged: dict[str, dict] = {}
    for project in [*(current.get("projects") or []), *(incoming.get("projects") or [])]:
        if not isinstance(project, dict) or not isinstance(project.get("id"), str):
            continue
        previous = merged.get(project["id"])
        if previous is None or project_timestamp(project) >= project_timestamp(previous):
            merged[project["id"]] = project

    projects = sorted(merged.values(), key=project_timestamp, reverse=True)[:24]
    project_ids = {project["id"] for project in projects}
    incoming_active = incoming.get("activeId")
    current_active = current.get("activeId")
    active_id = incoming_active if incoming_active in project_ids else current_active if current_active in project_ids else (projects[0]["id"] if projects else None)
    return {"activeId": active_id, "projects": projects}


def write_store(payload: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = STORE_FILE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, STORE_FILE)


def cloud_status() -> dict:
    with CLOUD_STATUS_LOCK:
        return dict(CLOUD_STATUS)


def record_cloud_failure(error: Exception) -> None:
    with CLOUD_STATUS_LOCK:
        CLOUD_STATUS["lastError"] = str(error)
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


def sync_cloud_store() -> bool:
    if not CLOUD.enabled or not CLOUD_SYNC_LOCK.acquire(blocking=False):
        return False
    local_store = empty_store()
    with CLOUD_STATUS_LOCK:
        CLOUD_STATUS["syncing"] = True
        CLOUD_STATUS["lastError"] = None
    try:
        with STORE_LOCK:
            local_store = json.loads(json.dumps(read_store(), ensure_ascii=False))
        merged = CLOUD.sync_store(local_store)
        with STORE_LOCK:
            write_store(merge_store(read_store(), merged))
        with CLOUD_STATUS_LOCK:
            CLOUD_STATUS["lastSuccessAt"] = datetime_now_iso()
            CLOUD_STATUS["fallbackToLocal"] = False
        return True
    except Exception as error:
        LOGGER.exception("Cloud sync failed")
        record_cloud_failure(error)
        try:
            merged = LOCAL_ASSETS.sync_store(local_store)
            with STORE_LOCK:
                write_store(merge_store(read_store(), merged))
        except LocalAssetStoreError:
            LOGGER.exception("Local asset fallback sync failed")
        return False
    finally:
        with CLOUD_STATUS_LOCK:
            CLOUD_STATUS["syncing"] = False
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


def schedule_cloud_sync(delay: float = 1.2) -> None:
    global CLOUD_SYNC_TIMER
    if not CLOUD.enabled:
        return
    with CLOUD_SYNC_TIMER_LOCK:
        if CLOUD_SYNC_TIMER:
            CLOUD_SYNC_TIMER.cancel()
        CLOUD_SYNC_TIMER = threading.Timer(delay, sync_cloud_store)
        CLOUD_SYNC_TIMER.daemon = True
        CLOUD_SYNC_TIMER.start()


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
        if path == "/api/project-store":
            with STORE_LOCK:
                payload = read_store()
            self.send_json(payload)
            return
        if path == "/api/cloud-status":
            self.send_json(cloud_status())
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
                    self.send_json(local_asset_library_payload(reason=str(error)))
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
                    {"error": str(error)},
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
        with STORE_LOCK:
            merged = merge_store(read_store(), incoming)
            write_store(merged)

        response_store = merged
        local_fallback = not CLOUD.enabled or cloud_status().get("fallbackToLocal")
        if local_fallback and not LOCAL_ASSETS.directory_selection_required:
            try:
                enriched = LOCAL_ASSETS.sync_store(merged)
                with STORE_LOCK:
                    response_store = merge_store(read_store(), enriched)
                    write_store(response_store)
            except LocalAssetStoreError:
                # A missing/unwritable asset folder must never block draft persistence.
                LOGGER.exception("Local asset fallback sync failed after draft save")
        schedule_cloud_sync()
        self.send_json(response_store)

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
        if not isinstance(project_id, str) or not isinstance(content, str):
            self.send_json({"error": "正文草稿结构无效"}, HTTPStatus.BAD_REQUEST)
            return

        with STORE_LOCK:
            store = read_store()
            projects = store.get("projects") or []
            matched = False
            for index, project in enumerate(projects):
                if not isinstance(project, dict) or project.get("id") != project_id:
                    continue
                patched = dict(project)
                patched_data = dict(project.get("data") or {})
                patched_data["content"] = content
                patched["data"] = patched_data
                title = incoming.get("title")
                if isinstance(title, str) and title.strip():
                    patched["title"] = title.strip()[:40]
                try:
                    incoming_updated_at = float(incoming.get("updatedAt") or 0)
                except (TypeError, ValueError):
                    incoming_updated_at = 0
                patched["updatedAt"] = max(project_timestamp(project), incoming_updated_at)
                projects[index] = patched
                matched = True
                break

            if not matched:
                self.send_json({"error": "找不到对应草稿"}, HTTPStatus.NOT_FOUND)
                return

            projects = sorted(projects, key=project_timestamp, reverse=True)[:24]
            store = {"activeId": project_id, "projects": projects}
            write_store(store)
        schedule_cloud_sync()
        self.send_json({"ok": True, "id": project_id})

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if self.reject_cross_origin_mutation():
            return
        path = urlparse(self.path).path
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
        success = sync_cloud_store()
        status = cloud_status()
        self.send_json({"ok": success, "status": status}, HTTPStatus.OK if success else HTTPStatus.BAD_GATEWAY)

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib handler API
        if self.reject_cross_origin_mutation():
            return
        path = urlparse(self.path).path
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
            self.send_json({"error": str(error)}, HTTPStatus.BAD_GATEWAY)
            return
        self.send_json({"ok": True})


def existing_app_is_healthy() -> bool:
    try:
        with urllib.request.urlopen(f"{APP_URL}api/project-store", timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and isinstance(payload.get("projects"), list)


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
        print("Supabase + TOS 云端副本正在后台同步……", flush=True)
        threading.Thread(target=sync_cloud_store, name="cloud-sync-startup", daemon=True).start()
    else:
        print(f"云同步未启用：{CLOUD.disabled_reason}", flush=True)
    threading.Timer(0.4, webbrowser.open, args=(APP_URL,)).start()
    server.serve_forever()
