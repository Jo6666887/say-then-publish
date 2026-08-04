#!/usr/bin/env python3
"""Static server plus a small disk-backed project store shared by all browsers."""

from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import os
import logging
import secrets
import ssl
import threading
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
from dataclasses import dataclass
from errno import EADDRINUSE
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Mapping
from urllib.parse import quote, unquote, urlparse

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
from web_image_search import (
    IllustrationError,
    IllustrationNotFoundError,
    IllustrationProviderError,
    IllustrationSecurityError,
    IllustrationValidationError,
    WebImageSearchService,
)


ROOT = Path(__file__).resolve().parent
DATA_DIR_SETTING = os.getenv("WRITE_THEN_PUBLISH_DATA_DIR", "runtime-data").strip() or "runtime-data"
DATA_DIR = Path(DATA_DIR_SETTING).expanduser()
if not DATA_DIR.is_absolute():
    DATA_DIR = ROOT / DATA_DIR
DATA_DIR = DATA_DIR.resolve()
STORE_FILE = DATA_DIR / "project-store.json"
# Image-heavy creator projects keep private image bytes in the local revision
# until cloud asset synchronization has confirmed TOS storage. The active user
# store can exceed 200 MB when several preserved conflict copies reference their
# own embedded image bytes. Keep a bounded ceiling, but leave enough room for a
# complete recovery snapshot instead of misreporting it as an unsaved draft.
MAX_BODY_BYTES = 384 * 1024 * 1024
MAX_TEXT_PATCH_BYTES = 2 * 1024 * 1024
MAX_AI_TEXT_BYTES = 2 * 1024 * 1024
SAVE_PROTOCOL_HEADER = "X-WTP-Save-Protocol"
SAVE_PROTOCOL_VERSION = "2"
STORE_LOCK = threading.Lock()
APP_SERVICE = "write-then-publish"
APP_HEALTH_SCHEMA = 1
CLOUD = CloudStore.from_root(ROOT)


@dataclass(frozen=True)
class ServerRuntimeConfig:
    bind_host: str
    port: int
    allowed_hosts: tuple[str, ...]
    allowed_hosts_explicit: bool
    open_browser: bool
    basic_auth_user: str
    basic_auth_password: str
    tls_cert_file: Path | None
    tls_key_file: Path | None
    allow_insecure_http: bool

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "ServerRuntimeConfig":
        values = os.environ if environ is None else environ
        bind_host = str(values.get("WTP_BIND_HOST") or "127.0.0.1").strip()
        port = _read_server_port(values.get("WTP_PORT"))
        raw_allowed_hosts = values.get("WTP_ALLOWED_HOSTS")
        allowed_hosts_explicit = bool(
            isinstance(raw_allowed_hosts, str) and raw_allowed_hosts.strip()
        )
        allowed_hosts = (
            _parse_allowed_hosts(raw_allowed_hosts)
            if allowed_hosts_explicit
            else ("127.0.0.1", "localhost", "::1")
        )
        cert_setting = str(values.get("WTP_TLS_CERT_FILE") or "").strip()
        key_setting = str(values.get("WTP_TLS_KEY_FILE") or "").strip()
        return cls(
            bind_host=bind_host,
            port=port,
            allowed_hosts=allowed_hosts,
            allowed_hosts_explicit=allowed_hosts_explicit,
            open_browser=_read_server_boolean(
                values.get("WTP_OPEN_BROWSER"),
                default=True,
                name="WTP_OPEN_BROWSER",
            ),
            basic_auth_user=str(values.get("WTP_BASIC_AUTH_USER") or "").strip(),
            basic_auth_password=str(values.get("WTP_BASIC_AUTH_PASSWORD") or ""),
            tls_cert_file=_resolve_server_path(cert_setting) if cert_setting else None,
            tls_key_file=_resolve_server_path(key_setting) if key_setting else None,
            allow_insecure_http=_read_server_boolean(
                values.get("WTP_ALLOW_INSECURE_HTTP"),
                default=False,
                name="WTP_ALLOW_INSECURE_HTTP",
            ),
        )

    @property
    def bind_is_loopback(self) -> bool:
        return _host_is_loopback(self.bind_host)

    @property
    def tls_enabled(self) -> bool:
        return self.tls_cert_file is not None and self.tls_key_file is not None

    @property
    def basic_auth_enabled(self) -> bool:
        return bool(self.basic_auth_user and self.basic_auth_password)

    @property
    def scheme(self) -> str:
        return "https" if self.tls_enabled else "http"

    @property
    def public_host(self) -> str:
        normalized_bind = _normalize_allowed_host(self.bind_host)
        if normalized_bind not in {"0.0.0.0", "::"}:
            return normalized_bind
        return next(
            (
                host
                for host in self.allowed_hosts
                if not _host_is_loopback(host) and host not in {"0.0.0.0", "::"}
            ),
            "127.0.0.1",
        )

    @property
    def local_health_host(self) -> str:
        normalized_bind = _normalize_allowed_host(self.bind_host)
        if normalized_bind == "0.0.0.0":
            return "127.0.0.1"
        if normalized_bind == "::":
            return "::1"
        return normalized_bind

    @property
    def app_url(self) -> str:
        return _server_url(self.scheme, self.public_host, self.port)

    @property
    def health_url(self) -> str:
        return (
            _server_url(self.scheme, self.local_health_host, self.port)
            + "api/health"
        )

    @property
    def health_host_header(self) -> str:
        return _format_host_header(self.public_host, self.port)

    def validate(self) -> None:
        normalized_bind = _normalize_allowed_host(self.bind_host)
        if not normalized_bind:
            raise ValueError("WTP_BIND_HOST 无效")
        if bool(self.tls_cert_file) != bool(self.tls_key_file):
            raise ValueError("WTP_TLS_CERT_FILE 与 WTP_TLS_KEY_FILE 必须同时配置")
        for path, label in (
            (self.tls_cert_file, "WTP_TLS_CERT_FILE"),
            (self.tls_key_file, "WTP_TLS_KEY_FILE"),
        ):
            if path is not None and not path.is_file():
                raise ValueError(f"{label} 指向的文件不存在")
        if bool(self.basic_auth_user) != bool(self.basic_auth_password):
            raise ValueError(
                "WTP_BASIC_AUTH_USER 与 WTP_BASIC_AUTH_PASSWORD 必须同时配置"
            )
        if ":" in self.basic_auth_user:
            raise ValueError("WTP_BASIC_AUTH_USER 不能包含冒号")
        if (
            normalized_bind not in {"0.0.0.0", "::"}
            and normalized_bind not in self.allowed_hosts
        ):
            raise ValueError("WTP_ALLOWED_HOSTS 必须包含 WTP_BIND_HOST")
        if self.bind_is_loopback:
            return
        if not self.allowed_hosts_explicit:
            raise ValueError("非本机监听必须显式配置 WTP_ALLOWED_HOSTS")
        deploy_hosts = [
            host
            for host in self.allowed_hosts
            if not _host_is_loopback(host) and host not in {"0.0.0.0", "::"}
        ]
        if not deploy_hosts:
            raise ValueError("WTP_ALLOWED_HOSTS 必须包含精确的部署 IP 或主机名")
        if not self.basic_auth_enabled:
            raise ValueError("非本机监听必须配置 HTTP Basic Auth")
        if not self.tls_enabled and not self.allow_insecure_http:
            raise ValueError(
                "非本机监听必须配置 TLS；受限测试网络可显式设置 "
                "WTP_ALLOW_INSECURE_HTTP=1"
            )


def _read_server_port(value: object) -> int:
    raw = "5173" if value in (None, "") else str(value).strip()
    try:
        port = int(raw)
    except (TypeError, ValueError):
        raise ValueError("WTP_PORT 必须是 1-65535 的整数") from None
    if not 1 <= port <= 65535:
        raise ValueError("WTP_PORT 必须是 1-65535 的整数")
    return port


def _read_server_boolean(value: object, *, default: bool, name: str) -> bool:
    if value in (None, ""):
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} 必须是 1 或 0")


def _resolve_server_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def _normalize_allowed_host(value: object) -> str:
    host = str(value or "").strip().lower().rstrip(".")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if (
        not host
        or any(character.isspace() or ord(character) < 32 for character in host)
        or any(token in host for token in ("*", "/", "\\", "@", ","))
    ):
        return ""
    try:
        return ipaddress.ip_address(host).compressed.lower()
    except ValueError:
        pass
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return ""
    labels = ascii_host.split(".")
    if any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or not all(character.isalnum() or character == "-" for character in label)
        for label in labels
    ):
        return ""
    return ascii_host


def _parse_allowed_hosts(value: object) -> tuple[str, ...]:
    entries = str(value or "").split(",")
    normalized = []
    for entry in entries:
        host = _normalize_allowed_host(entry)
        if not host:
            raise ValueError("WTP_ALLOWED_HOSTS 包含无效主机名")
        if host not in normalized:
            normalized.append(host)
    if not normalized:
        raise ValueError("WTP_ALLOWED_HOSTS 不能为空")
    return tuple(normalized)


def _host_is_loopback(value: object) -> bool:
    host = _normalize_allowed_host(value)
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _format_host_header(host: str, port: int) -> str:
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def _server_url(scheme: str, host: str, port: int) -> str:
    return f"{scheme}://{_format_host_header(host, port)}/"


def client_address_is_loopback(client_address: object) -> bool:
    host = (
        client_address[0]
        if isinstance(client_address, (tuple, list)) and client_address
        else ""
    )
    try:
        return ipaddress.ip_address(str(host)).is_loopback
    except ValueError:
        return False


class _NoHealthRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never forward an internal health probe or its Basic credentials."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


RUNTIME_CONFIG = ServerRuntimeConfig.from_env()
APP_URL = RUNTIME_CONFIG.app_url
AI_LAYOUT = AILayoutService.from_env()
ILLUSTRATIONS = WebImageSearchService.from_env(ai_layout=AI_LAYOUT)
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
    "conflicts": [],
}
LOGGER = logging.getLogger("write-then-publish")

# Loopback-only settings that the local UI may write into the gitignored .env.
ENV_PATH = ROOT / ".env"
ENV_WRITE_LOCK = threading.Lock()
SETTINGS_ENV_GROUPS = {
    "supabase": ["SUPABASE_URL", "SUPABASE_SECRET_KEY", "WRITE_THEN_PUBLISH_WORKSPACE_ID", "WRITE_THEN_PUBLISH_CLOUD_SYNC"],
    "tos": ["TOS_ACCESS_KEY", "TOS_SECRET_KEY", "TOS_ENDPOINT", "TOS_REGION", "TOS_BUCKET", "TOS_KEY_PREFIX"],
}
SETTINGS_ENV_ALLOWED = {key for keys in SETTINGS_ENV_GROUPS.values() for key in keys}
# Values that must never be echoed back to the browser once stored.
SETTINGS_ENV_SECRET = {"SUPABASE_SECRET_KEY", "TOS_ACCESS_KEY", "TOS_SECRET_KEY"}


def read_env_file_map(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            result[key] = value
    return result


def write_env_updates(path: Path, updates: Mapping[str, str]) -> None:
    """Merge `updates` into `.env`, preserving existing lines and comments, then
    rewrite the file with owner-only permissions. Callers must reject values that
    contain newlines so a single value cannot inject extra assignments."""
    existing_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(updates)
    out_lines: list[str] = []
    for raw_line in existing_lines:
        stripped = raw_line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                out_lines.append(f"{key}={remaining.pop(key)}")
                continue
        out_lines.append(raw_line)
    for key, value in remaining.items():
        out_lines.append(f"{key}={value}")
    text = "\n".join(out_lines).strip("\n") + "\n"
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


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


def browser_store_payload(payload: dict) -> dict:
    """Replace embedded cloud image bytes with authenticated same-origin URLs."""

    if not CLOUD.enabled or cloud_status().get("fallbackToLocal"):
        return payload
    projects = payload.get("projects") if isinstance(payload, dict) else None
    for project in projects if isinstance(projects, list) else []:
        data = project.get("data") if isinstance(project, dict) else None
        images = data.get("images") if isinstance(data, dict) else None
        for image in images.values() if isinstance(images, dict) else []:
            asset_id = image.get("cloudAssetId") if isinstance(image, dict) else None
            if isinstance(asset_id, str) and asset_id:
                image["src"] = f"/api/assets/{quote(asset_id, safe='')}/content"
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


def project_summary(project: dict) -> dict:
    data = project.get("data") if isinstance(project.get("data"), dict) else {}
    cloud_base_updated_at = parse_updated_at(project.get("cloudBaseUpdatedAt"))
    return {
        "id": project.get("id"),
        "title": project.get("title") or "未命名项目",
        "updatedAt": parse_updated_at(project.get("updatedAt")),
        "cloudBaseUpdatedAt": cloud_base_updated_at or 0,
        "published": data.get("published") is True,
        "conflictOf": data.get("__localConflictOf"),
    }


def next_server_revision(project: dict | None = None) -> int:
    return max(
        int(time.time() * 1000),
        int(project_timestamp(project)) + 1 if isinstance(project, dict) else 1,
    )


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
            CLOUD_STATUS["conflicts"] = []
        merged = CLOUD.sync_store(local_store)
        conflicts = merged.get("conflicts") if isinstance(merged, dict) else None
        synced = project_checkpoint(merged, target_project_id or target["projectId"])
        with STORE_LOCK:
            current_store = read_store()
            write_store(merged if current_store == local_store else merge_store(current_store, merged))
        with CLOUD_STATUS_LOCK:
            CLOUD_STATUS["lastSuccessAt"] = datetime_now_iso()
            CLOUD_STATUS["projectId"] = synced["projectId"]
            CLOUD_STATUS["syncedUpdatedAt"] = synced["updatedAt"]
            CLOUD_STATUS["fallbackToLocal"] = False
            CLOUD_STATUS["conflicts"] = conflicts if isinstance(conflicts, list) else []
        if target_project_id and (
            synced["projectId"] != target_project_id
            or synced["updatedAt"] is None
            or target_updated_at is None
            or synced["updatedAt"] != int(target_updated_at)
        ):
            return False
        if target_project_id and target_updated_at is not None:
            with STORE_LOCK:
                confirmed_store = read_store()
                confirmed_project = find_project(confirmed_store, target_project_id)
                if confirmed_project is not None:
                    confirmed_project["cloudBaseUpdatedAt"] = int(target_updated_at)
                    write_store(confirmed_store)
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

    def send_illustration_error(self, error: IllustrationError) -> None:
        if isinstance(error, IllustrationNotFoundError):
            status = HTTPStatus.NOT_FOUND
        elif (
            isinstance(error, IllustrationValidationError)
            and error.code == "DRAFT_VERSION_CONFLICT"
        ):
            status = HTTPStatus.CONFLICT
        elif isinstance(error, IllustrationValidationError):
            status = HTTPStatus.BAD_REQUEST
        elif isinstance(error, IllustrationSecurityError):
            status = HTTPStatus.UNPROCESSABLE_ENTITY
        elif isinstance(error, IllustrationProviderError):
            status = HTTPStatus.BAD_GATEWAY
        else:
            status = HTTPStatus.BAD_GATEWAY
        self.send_json(
            {
                "ok": False,
                "error": {
                    "code": error.code,
                    "message": str(error),
                },
            },
            status,
        )

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

    def runtime_config(self) -> ServerRuntimeConfig:
        config = getattr(self.server, "runtime_config", None)
        return config if isinstance(config, ServerRuntimeConfig) else RUNTIME_CONFIG

    def settings_endpoint_allowed(self) -> bool:
        """Reading or writing .env secrets is only ever allowed from a loopback
        client on a loopback-bound server, never from a public deployment."""
        return self.runtime_config().bind_is_loopback and client_address_is_loopback(self.client_address)

    def settings_env_status(self) -> dict:
        stored = read_env_file_map(ENV_PATH)

        def resolve(key: str) -> str:
            value = stored.get(key)
            if value is None:
                value = os.environ.get(key, "")
            return value or ""

        groups: dict[str, dict] = {}
        for group, keys in SETTINGS_ENV_GROUPS.items():
            groups[group] = {}
            for key in keys:
                value = resolve(key)
                entry = {"configured": bool(value.strip())}
                if key not in SETTINGS_ENV_SECRET:
                    entry["value"] = value  # non-secret values may prefill the form
                groups[group][key] = entry
        return {"fields": groups, "cloudSyncOn": bool(CLOUD.enabled), "envFile": ".env"}

    def reject_untrusted_host(self) -> bool:
        """Reject DNS-rebinding requests before any local data is read."""

        raw_host = self.headers.get("Host", "").strip()
        parsed = None
        try:
            parsed = urlparse(f"//{raw_host}")
            hostname = _normalize_allowed_host(parsed.hostname)
            port = parsed.port
        except ValueError:
            hostname = ""
            port = None
        expected_port = int(getattr(self.server, "server_port", 0) or 0)
        config = self.runtime_config()
        if (
            not raw_host
            or parsed is None
            or parsed.username is not None
            or parsed.password is not None
            or hostname not in config.allowed_hosts
            or port is None
            or (expected_port and port != expected_port)
        ):
            self.send_json({"error": "已拒绝未授权的 Host 请求"}, HTTPStatus.FORBIDDEN)
            return True
        return False

    def reject_unauthenticated(self, path: str) -> bool:
        config = self.runtime_config()
        if not config.basic_auth_enabled:
            return False
        if (
            path == "/api/health"
            and self.command in {"GET", "HEAD"}
            and client_address_is_loopback(self.client_address)
        ):
            return False
        authorization = self.headers.get("Authorization", "")
        supplied_user = ""
        supplied_password = ""
        if authorization.startswith("Basic "):
            encoded = authorization[6:].strip()
            try:
                decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
                supplied_user, supplied_password = decoded.split(":", 1)
            except (binascii.Error, UnicodeDecodeError, ValueError):
                supplied_user = ""
                supplied_password = ""
        authorized = secrets.compare_digest(
            supplied_user.encode("utf-8"),
            config.basic_auth_user.encode("utf-8"),
        ) & secrets.compare_digest(
            supplied_password.encode("utf-8"),
            config.basic_auth_password.encode("utf-8"),
        )
        if authorized:
            return False
        payload = json.dumps(
            {"error": "需要身份验证"},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header(
            "WWW-Authenticate",
            'Basic realm="Write Then Publish", charset="UTF-8"',
        )
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)
        return True

    def send_health(self, *, include_body: bool) -> None:
        encoded = json.dumps(
            {
                "ok": True,
                "service": APP_SERVICE,
                "schema": APP_HEALTH_SCHEMA,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if include_body:
            self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.reject_untrusted_host():
            return
        path = urlparse(self.path).path
        if self.reject_unauthenticated(path):
            return
        if path == "/api/health":
            self.send_health(include_body=True)
            return
        if path == "/api/settings/env-status":
            if not self.settings_endpoint_allowed():
                self.send_json({"error": "仅本机可访问设置"}, HTTPStatus.FORBIDDEN)
                return
            self.send_json(self.settings_env_status())
            return
        if path == "/api/project-store":
            if CLOUD.enabled and not CLOUD_INITIAL_SYNC_DONE.is_set():
                CLOUD_INITIAL_SYNC_DONE.wait(timeout=CLOUD_INITIAL_SYNC_WAIT_SECONDS)
            with STORE_LOCK:
                payload = read_store()
            self.send_json(browser_store_payload(payload))
            return
        if path == "/api/projects":
            if CLOUD.enabled and not CLOUD_INITIAL_SYNC_DONE.is_set():
                CLOUD_INITIAL_SYNC_DONE.wait(timeout=CLOUD_INITIAL_SYNC_WAIT_SECONDS)
            with STORE_LOCK:
                store = read_store()
            self.send_json(
                {
                    "projects": [
                        project_summary(project)
                        for project in store.get("projects") or []
                        if isinstance(project, dict)
                    ],
                    "activeId": store.get("activeId"),
                    "status": cloud_status(),
                }
            )
            return
        projects_prefix = "/api/projects/"
        if path.startswith(projects_prefix) and "/" not in path.removeprefix(projects_prefix):
            project_id = unquote(path.removeprefix(projects_prefix))
            with STORE_LOCK:
                project = find_project(read_store(), project_id)
            if project is None:
                self.send_json({"error": "找不到对应项目"}, HTTPStatus.NOT_FOUND)
                return
            self.send_json({"project": project, "status": cloud_status()})
            return
        if path == "/api/cloud-status":
            self.send_json(cloud_status())
            return
        if path == "/api/ai/status":
            self.send_json(AI_LAYOUT.status())
            return
        if path == "/api/illustrations/status":
            self.send_json(ILLUSTRATIONS.status())
            return
        illustration_preview_prefix = "/api/illustrations/candidates/"
        if path.startswith(illustration_preview_prefix) and path.endswith("/preview"):
            candidate_id = unquote(
                path.removeprefix(illustration_preview_prefix).removesuffix("/preview")
            )
            if "/" in candidate_id:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                raw, mime_type = ILLUSTRATIONS.preview(candidate_id)
            except IllustrationError as error:
                self.send_illustration_error(error)
                return
            self.send_bytes(raw, mime_type)
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
        if self.reject_untrusted_host():
            return
        path = urlparse(self.path).path
        if self.reject_unauthenticated(path):
            return
        if path == "/api/health":
            self.send_health(include_body=False)
            return
        if path.startswith("/api/") or not public_static_path(path):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        return super().do_HEAD()

    def do_PUT(self) -> None:  # noqa: N802 - stdlib handler API
        if self.reject_untrusted_host():
            return
        path = urlparse(self.path).path
        if self.reject_unauthenticated(path):
            return
        if self.reject_cross_origin_mutation():
            return
        if path != "/api/project-store":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if self.headers.get(SAVE_PROTOCOL_HEADER, "").strip() != SAVE_PROTOCOL_VERSION:
            self.send_json(
                {
                    "error": "页面版本过旧，请刷新后再保存",
                    "code": "SAVE_PROTOCOL_REQUIRED",
                },
                HTTPStatus.PRECONDITION_REQUIRED,
            )
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
        expected_project_id = self.headers.get("X-WTP-Expected-Project-Id", "").strip()
        expected_updated_header = self.headers.get(
            "X-WTP-Expected-Project-Updated-At",
            "",
        ).strip()
        conditional_save_requested = bool(expected_project_id or expected_updated_header)
        expected_updated_at = (
            parse_updated_at(expected_updated_header)
            if conditional_save_requested
            else None
        )
        if conditional_save_requested and (
            not expected_project_id
            or expected_project_id != incoming_project_id
            or expected_updated_at is None
        ):
            self.send_json({"error": "条件保存版本无效"}, HTTPStatus.BAD_REQUEST)
            return

        with STORE_LOCK:
            current_store = read_store()
            current_project = find_project(current_store, incoming_project_id)
            current_updated_at = (
                parse_updated_at(current_project.get("updatedAt"))
                if current_project is not None
                else None
            )
            if conditional_save_requested and (
                current_project is None or current_updated_at != expected_updated_at
            ):
                self.send_json(save_conflict_payload(current_project), HTTPStatus.CONFLICT)
                return
            if current_project is not None and not conditional_save_requested:
                self.send_json(
                    {
                        "error": "缺少服务器基础版本，请刷新页面后重试",
                        "code": "SAVE_BASE_REQUIRED",
                    },
                    HTTPStatus.PRECONDITION_REQUIRED,
                )
                return
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
        if self.reject_untrusted_host():
            return
        path = urlparse(self.path).path
        if self.reject_unauthenticated(path):
            return
        if self.reject_cross_origin_mutation():
            return
        projects_prefix = "/api/projects/"
        if path.startswith(projects_prefix) and "/" not in path.removeprefix(projects_prefix):
            project_id = unquote(path.removeprefix(projects_prefix))
            incoming = self.read_json_body(maximum=MAX_BODY_BYTES)
            if incoming is None:
                self.send_json({"error": "项目修改请求无效"}, HTTPStatus.BAD_REQUEST)
                return
            expected_updated_at = parse_updated_at(incoming.get("expectedUpdatedAt"))
            if expected_updated_at is None:
                self.send_json(
                    {"error": "缺少 expectedUpdatedAt，无法安全避免覆盖他人修改"},
                    HTTPStatus.BAD_REQUEST,
                )
                return

            with STORE_LOCK:
                store = read_store()
                current = find_project(store, project_id)
                current_updated_at = (
                    parse_updated_at(current.get("updatedAt"))
                    if current is not None
                    else None
                )
                if current is None:
                    self.send_json({"error": "找不到对应项目"}, HTTPStatus.NOT_FOUND)
                    return
                if current_updated_at != expected_updated_at:
                    self.send_json(save_conflict_payload(current), HTTPStatus.CONFLICT)
                    return

                project = json.loads(json.dumps(current, ensure_ascii=False))
                data = project.get("data") if isinstance(project.get("data"), dict) else {}
                if "content" in incoming:
                    if not isinstance(incoming.get("content"), str):
                        self.send_json({"error": "正文必须是字符串"}, HTTPStatus.BAD_REQUEST)
                        return
                    data["content"] = incoming["content"]
                if "published" in incoming:
                    if not isinstance(incoming.get("published"), bool):
                        self.send_json({"error": "published 必须是布尔值"}, HTTPStatus.BAD_REQUEST)
                        return
                    data["published"] = incoming["published"]
                if "addImage" in incoming:
                    addition = incoming.get("addImage")
                    image_id = addition.get("id") if isinstance(addition, dict) else None
                    image = addition.get("image") if isinstance(addition, dict) else None
                    src = image.get("src") if isinstance(image, dict) else None
                    if (
                        not isinstance(image_id, str)
                        or not image_id
                        or len(image_id) > 160
                        or not isinstance(image, dict)
                        or not isinstance(src, str)
                        or not src.startswith(("data:image/png;base64,", "data:image/jpeg;base64,", "data:image/webp;base64,"))
                    ):
                        self.send_json({"error": "新增图片资源结构无效"}, HTTPStatus.BAD_REQUEST)
                        return
                    images = dict(data.get("images") or {}) if isinstance(data.get("images"), dict) else {}
                    if image_id in images:
                        self.send_json({"error": "新增图片 ID 已存在"}, HTTPStatus.CONFLICT)
                        return
                    images[image_id] = image
                    data["images"] = images
                if "title" in incoming:
                    if not isinstance(incoming.get("title"), str) or not incoming["title"].strip():
                        self.send_json({"error": "项目标题不能为空"}, HTTPStatus.BAD_REQUEST)
                        return
                    project["title"] = incoming["title"].strip()[:40]
                project["data"] = data
                project["updatedAt"] = next_server_revision(current)
                next_store = merge_store(
                    store,
                    {"activeId": project_id, "projects": [project], "deletedProjects": []},
                )
                write_store(next_store)

            cloud_synced = sync_cloud_store(
                wait_for_existing=True,
                target_project_id=project_id,
                target_updated_at=int(project["updatedAt"]),
                wait_timeout=None,
            ) if CLOUD.enabled else False
            if not CLOUD.enabled:
                try:
                    sync_local_asset_store()
                except LocalAssetStoreError:
                    # Project JSON already contains the embedded image bytes.
                    # A local asset-library write failure must not roll back the
                    # creator's successfully saved project revision.
                    LOGGER.exception("Local asset sync failed after Agent project update")
            with STORE_LOCK:
                confirmed_store = read_store()
                confirmed_project = find_project(confirmed_store, project_id)
            status = cloud_status()
            conflict_info = next(
                (
                    item
                    for item in status.get("conflicts") or []
                    if isinstance(item, dict) and item.get("projectId") == project_id
                ),
                None,
            )
            conflict_project = (
                find_project(confirmed_store, conflict_info.get("conflictProjectId"))
                if conflict_info is not None
                else None
            )
            if conflict_project is not None and not cloud_synced:
                payload = save_conflict_payload(confirmed_project)
                payload.update(
                    {
                        "error": "云端伙伴已编辑同一项目；你的修改已保留为冲突副本",
                        "conflictProject": project_summary(conflict_project),
                        "localSaved": True,
                        "cloudSynced": False,
                    }
                )
                self.send_json(payload, HTTPStatus.CONFLICT)
                return
            response_status = HTTPStatus.OK if cloud_synced or not CLOUD.enabled else HTTPStatus.ACCEPTED
            self.send_json(
                {
                    "ok": True,
                    "project": confirmed_project or project,
                    "localSaved": True,
                    "cloudSynced": cloud_synced,
                    "status": status,
                },
                response_status,
            )
            return

        if path != "/api/project-store/current-text":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if self.headers.get(SAVE_PROTOCOL_HEADER, "").strip() != SAVE_PROTOCOL_VERSION:
            self.send_json(
                {
                    "error": "页面版本过旧，请刷新后再保存",
                    "code": "SAVE_PROTOCOL_REQUIRED",
                },
                HTTPStatus.PRECONDITION_REQUIRED,
            )
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
        if self.reject_untrusted_host():
            return
        path = urlparse(self.path).path
        if self.reject_unauthenticated(path):
            return
        if self.reject_cross_origin_mutation():
            return
        if path == "/api/settings/env":
            if not self.settings_endpoint_allowed():
                self.send_json({"error": "仅本机可写入配置"}, HTTPStatus.FORBIDDEN)
                return
            payload = self.read_json_body(maximum=65536)
            values = payload.get("values") if isinstance(payload, dict) else None
            if not isinstance(values, dict):
                self.send_json({"error": "配置格式无效"}, HTTPStatus.BAD_REQUEST)
                return
            updates: dict[str, str] = {}
            for key, value in values.items():
                if key not in SETTINGS_ENV_ALLOWED:
                    self.send_json({"error": f"不允许写入的字段：{key}"}, HTTPStatus.BAD_REQUEST)
                    return
                if value is None:
                    value = ""
                if not isinstance(value, str):
                    self.send_json({"error": f"字段值必须是文本：{key}"}, HTTPStatus.BAD_REQUEST)
                    return
                if "\n" in value or "\r" in value:
                    self.send_json({"error": f"字段值不能包含换行：{key}"}, HTTPStatus.BAD_REQUEST)
                    return
                updates[key] = value.strip()
            if not updates:
                self.send_json({"error": "没有要保存的字段"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                with ENV_WRITE_LOCK:
                    write_env_updates(ENV_PATH, updates)
            except OSError:
                self.send_json({"error": "写入 .env 失败，请检查文件权限"}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self.send_json({"saved": sorted(updates.keys()), "restartRequired": True})
            return
        if path == "/api/projects":
            incoming = self.read_json_body(maximum=MAX_BODY_BYTES)
            if incoming is None:
                self.send_json({"error": "项目创建请求无效"}, HTTPStatus.BAD_REQUEST)
                return
            content = incoming.get("content", "")
            title = incoming.get("title") or "未命名项目"
            if not isinstance(content, str) or not isinstance(title, str):
                self.send_json({"error": "标题或正文格式无效"}, HTTPStatus.BAD_REQUEST)
                return
            now = next_server_revision()
            project_id = f"project_{now:x}_{uuid.uuid4().hex[:6]}"
            project = {
                "id": project_id,
                "title": title.strip()[:40] or "未命名项目",
                "updatedAt": now,
                "cloudBaseUpdatedAt": 0,
                "data": {
                    "content": content,
                    "published": incoming.get("published") is True,
                    "images": {},
                },
            }
            with STORE_LOCK:
                store = read_store()
                next_store = merge_store(
                    store,
                    {"activeId": project_id, "projects": [project], "deletedProjects": []},
                )
                write_store(next_store)
            cloud_synced = sync_cloud_store(
                wait_for_existing=True,
                target_project_id=project_id,
                target_updated_at=now,
                wait_timeout=None,
            ) if CLOUD.enabled else False
            with STORE_LOCK:
                confirmed = find_project(read_store(), project_id) or project
            self.send_json(
                {
                    "ok": True,
                    "project": confirmed,
                    "localSaved": True,
                    "cloudSynced": cloud_synced,
                    "status": cloud_status(),
                },
                HTTPStatus.CREATED if cloud_synced or not CLOUD.enabled else HTTPStatus.ACCEPTED,
            )
            return
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
        if path == "/api/illustrations/search":
            payload = self.read_json_body(maximum=MAX_AI_TEXT_BYTES)
            if not payload:
                self.send_json(
                    {
                        "ok": False,
                        "error": {
                            "code": "INVALID_REQUEST",
                            "message": "配图请求无效",
                        },
                    },
                    HTTPStatus.BAD_REQUEST,
                )
                return
            content = payload.get("content")
            project_id = payload.get("projectId")
            base_updated_at = parse_updated_at(payload.get("baseUpdatedAt"))
            if (
                not isinstance(content, str)
                or not isinstance(project_id, str)
                or not project_id
                or base_updated_at is None
            ):
                self.send_json(
                    {
                        "ok": False,
                        "error": {
                            "code": "UNSAVED_DRAFT",
                            "message": "请先保存当前草稿，再使用一键配图",
                        },
                    },
                    HTTPStatus.CONFLICT,
                )
                return
            with STORE_LOCK:
                saved_project = find_project(read_store(), project_id)
            if not project_revision_matches(
                saved_project,
                project_id=project_id,
                updated_at=base_updated_at,
                content=content,
            ):
                self.send_json(
                    {
                        "ok": False,
                        "error": {
                            "code": "DRAFT_VERSION_CONFLICT",
                            "message": "正文已有新修改，请保存后重新配图",
                        },
                    },
                    HTTPStatus.CONFLICT,
                )
                return
            try:
                result = ILLUSTRATIONS.search(
                    project_id=project_id,
                    updated_at=base_updated_at,
                    content=content,
                    blocks=payload.get("blocks"),
                    provider=payload.get("provider", "auto"),
                    max_images=payload.get("maxImages", 2),
                    max_candidates=payload.get("maxCandidates", 3),
                )
            except IllustrationError as error:
                self.send_illustration_error(error)
                return
            with STORE_LOCK:
                after_project = find_project(read_store(), project_id)
            if not project_revision_matches(
                after_project,
                project_id=project_id,
                updated_at=base_updated_at,
                content=content,
            ):
                self.send_json(
                    {
                        "ok": False,
                        "error": {
                            "code": "DRAFT_VERSION_CONFLICT",
                            "message": "找图期间正文已有新修改，请保存后重新配图",
                        },
                    },
                    HTTPStatus.CONFLICT,
                )
                return
            result["baseUpdatedAt"] = base_updated_at
            self.send_json(result)
            return
        if path == "/api/illustrations/import":
            payload = self.read_json_body(maximum=MAX_AI_TEXT_BYTES)
            if not payload:
                self.send_json(
                    {
                        "ok": False,
                        "error": {
                            "code": "INVALID_REQUEST",
                            "message": "配图导入请求无效",
                        },
                    },
                    HTTPStatus.BAD_REQUEST,
                )
                return
            content = payload.get("content")
            project_id = payload.get("projectId")
            candidate_id = payload.get("candidateId")
            base_updated_at = parse_updated_at(payload.get("baseUpdatedAt"))
            if (
                not isinstance(content, str)
                or not isinstance(project_id, str)
                or not project_id
                or not isinstance(candidate_id, str)
                or not candidate_id
                or base_updated_at is None
            ):
                self.send_json(
                    {
                        "ok": False,
                        "error": {
                            "code": "UNSAVED_DRAFT",
                            "message": "请先保存当前草稿，再导入配图",
                        },
                    },
                    HTTPStatus.CONFLICT,
                )
                return
            with STORE_LOCK:
                saved_project = find_project(read_store(), project_id)
            if not project_revision_matches(
                saved_project,
                project_id=project_id,
                updated_at=base_updated_at,
                content=content,
            ):
                self.send_json(
                    {
                        "ok": False,
                        "error": {
                            "code": "DRAFT_VERSION_CONFLICT",
                            "message": "正文已有新修改，请保存后重新配图",
                        },
                    },
                    HTTPStatus.CONFLICT,
                )
                return
            try:
                result = ILLUSTRATIONS.import_candidate(
                    candidate_id,
                    project_id=project_id,
                    updated_at=base_updated_at,
                    content=content,
                )
            except IllustrationError as error:
                self.send_illustration_error(error)
                return
            with STORE_LOCK:
                after_project = find_project(read_store(), project_id)
            if not project_revision_matches(
                after_project,
                project_id=project_id,
                updated_at=base_updated_at,
                content=content,
            ):
                self.send_json(
                    {
                        "ok": False,
                        "error": {
                            "code": "DRAFT_VERSION_CONFLICT",
                            "message": "图片下载期间正文已有新修改，本次没有插入",
                        },
                    },
                    HTTPStatus.CONFLICT,
                )
                return
            result["baseUpdatedAt"] = base_updated_at
            self.send_json(result)
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
        if self.reject_untrusted_host():
            return
        path = urlparse(self.path).path
        if self.reject_unauthenticated(path):
            return
        if self.reject_cross_origin_mutation():
            return
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


def existing_app_is_healthy(
    config: ServerRuntimeConfig | None = None,
) -> bool:
    config = config or RUNTIME_CONFIG
    headers = {"Host": config.health_host_header}
    if config.basic_auth_enabled:
        token = base64.b64encode(
            f"{config.basic_auth_user}:{config.basic_auth_password}".encode("utf-8")
        ).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    request = urllib.request.Request(config.health_url, headers=headers)
    handlers: list[object] = [
        urllib.request.ProxyHandler({}),
        _NoHealthRedirectHandler(),
    ]
    if config.tls_enabled:
        # This is a process-local liveness probe only.  User-facing clients must
        # still validate or explicitly trust the configured certificate.
        handlers.append(
            urllib.request.HTTPSHandler(
                context=ssl._create_unverified_context(),
            )
        )
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(request, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("ok") is True
        and payload.get("service") == APP_SERVICE
        and payload.get("schema") == APP_HEALTH_SCHEMA
    )


def create_runtime_server(
    config: ServerRuntimeConfig,
    handler: object,
) -> ThreadingHTTPServer:
    config.validate()
    server = ThreadingHTTPServer((config.bind_host, config.port), handler)
    server.runtime_config = config
    if not config.tls_enabled:
        return server
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        context.load_cert_chain(
            certfile=str(config.tls_cert_file),
            keyfile=str(config.tls_key_file),
        )
        server.socket = context.wrap_socket(server.socket, server_side=True)
    except Exception:
        server.server_close()
        raise
    return server


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    RUNTIME_CONFIG.validate()
    handler = partial(WriteThenPublishHandler, directory=str(ROOT))
    try:
        server = create_runtime_server(RUNTIME_CONFIG, handler)
    except OSError as error:
        if error.errno == EADDRINUSE and existing_app_is_healthy(RUNTIME_CONFIG):
            print(f"写了就发已经在运行：{APP_URL}", flush=True)
            if RUNTIME_CONFIG.open_browser:
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
    if RUNTIME_CONFIG.open_browser:
        threading.Timer(0.4, webbrowser.open, args=(APP_URL,)).start()
    server.serve_forever()
