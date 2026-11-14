"""Supabase metadata + private Volcengine TOS asset storage.

Local browser/disk copies remain the primary offline cache. This module adds a
cloud replica without ever placing Supabase/TOS secrets in browser JavaScript.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import mimetypes
import os
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import quote, unquote_to_bytes


DATA_URI_RE = re.compile(r"^data:([^,]*?),(.*)$", re.DOTALL)
IMAGE_TOKEN_RE = re.compile(r"\[\[image:([^\]]+)\]\]")
TOS_ASSET_PREFIX = "tos://"
TOS_DELETED_PREFIX = "tos-deleted://"
PROJECT_TOMBSTONE_FIELD = "__writeThenPublishDeletedAt"
CLOUD_BASE_UPDATED_AT_FIELD = "cloudBaseUpdatedAt"
LOCAL_CONFLICT_OF_FIELD = "__localConflictOf"
MAX_PROJECTS = 120


def _safe_asset_source(image: dict[str, Any]) -> dict[str, str] | None:
    source = image.get("source") if isinstance(image, dict) else None
    if not isinstance(source, dict) or source.get("kind") != "web":
        return None
    limits = {
        "provider": 40,
        "title": 240,
        "sourcePageUrl": 1000,
        "creator": 240,
        "license": 160,
        "licenseUrl": 1000,
        "query": 240,
        "fetchedAt": 80,
    }
    normalized = {"kind": "web"}
    for field, maximum in limits.items():
        value = source.get(field)
        if isinstance(value, str) and value.strip():
            normalized[field] = value.strip()[:maximum]
    return normalized


class CloudStoreError(RuntimeError):
    pass


class AssetInUseError(CloudStoreError):
    def __init__(self, reference_count: int):
        super().__init__(f"该资源仍被 {reference_count} 篇草稿引用")
        self.reference_count = reference_count


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
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
            os.environ.setdefault(key, value)


@dataclass(frozen=True)
class CloudConfig:
    enabled: bool
    supabase_url: str
    supabase_secret_key: str
    workspace_id: str
    tos_access_key: str
    tos_secret_key: str
    tos_endpoint: str
    tos_region: str
    tos_bucket: str
    tos_key_prefix: str

    @classmethod
    def from_env(cls, root: Path) -> "CloudConfig":
        load_env_file(root / ".env")
        enabled = os.getenv("WRITE_THEN_PUBLISH_CLOUD_SYNC", "0").strip().lower() in {"1", "true", "yes", "on"}
        return cls(
            enabled=enabled,
            supabase_url=os.getenv("SUPABASE_URL", "").strip().rstrip("/"),
            supabase_secret_key=(os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip(),
            workspace_id=os.getenv("WRITE_THEN_PUBLISH_WORKSPACE_ID", "default-workspace").strip() or "default-workspace",
            tos_access_key=os.getenv("TOS_ACCESS_KEY", "").strip(),
            tos_secret_key=os.getenv("TOS_SECRET_KEY", "").strip(),
            tos_endpoint=os.getenv("TOS_ENDPOINT", "tos-cn-beijing.volces.com").strip(),
            tos_region=os.getenv("TOS_REGION", "cn-beijing").strip(),
            tos_bucket=os.getenv("TOS_BUCKET", "").strip(),
            tos_key_prefix=os.getenv("TOS_KEY_PREFIX", "write-then-publish/assets/").strip().strip("/") + "/",
        )

    @property
    def missing(self) -> list[str]:
        values = {
            "SUPABASE_URL": self.supabase_url,
            "SUPABASE_SECRET_KEY": self.supabase_secret_key,
            "TOS_ACCESS_KEY": self.tos_access_key,
            "TOS_SECRET_KEY": self.tos_secret_key,
            "TOS_BUCKET": self.tos_bucket,
        }
        return [key for key, value in values.items() if not value]

    @property
    def ready(self) -> bool:
        return self.enabled and not self.missing


class SupabaseRest:
    def __init__(self, config: CloudConfig):
        self.base_url = config.supabase_url
        self.secret_key = config.supabase_secret_key
        self.session = requests.Session()
        retries = Retry(
            total=4,
            connect=4,
            read=4,
            status=4,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST", "PATCH", "DELETE"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("https://", adapter)

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        payload: Any = None,
        prefer: str | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        headers = {
            "apikey": self.secret_key,
            "Authorization": f"Bearer {self.secret_key}",
            "Accept": "application/json",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if prefer:
            headers["Prefer"] = prefer
        try:
            response = self.session.request(
                method,
                url,
                params=query,
                headers=headers,
                json=payload if payload is not None else None,
                timeout=(10, 60),
            )
        except requests.RequestException as error:
            raise CloudStoreError(f"Supabase 连接失败：{error}") from error
        if response.status_code >= 400:
            detail = response.text[:800]
            raise CloudStoreError(f"Supabase {method} {path} 失败（{response.status_code}）：{detail}")
        if not response.content:
            return None
        try:
            return response.json()
        except requests.JSONDecodeError as error:
            raise CloudStoreError("Supabase 返回了无法解析的数据") from error


class CloudStore:
    def __init__(self, config: CloudConfig):
        self.config = config
        self.rest = SupabaseRest(config) if config.ready else None
        self._tos_client = None
        self._lock = threading.RLock()
        self._asset_bytes: dict[str, bytes] = {}
        # Asset rows are immutable per asset_id, so reads can be cached and served
        # without waiting on the global sync lock (which may be held by a long sync).
        self._asset_rows: dict[str, dict] = {}
        self._cache_lock = threading.Lock()
        self.cache_dir: Path | None = None

    @classmethod
    def from_root(cls, root: Path) -> "CloudStore":
        return cls(CloudConfig.from_env(root))

    @property
    def enabled(self) -> bool:
        return self.config.ready

    @property
    def disabled_reason(self) -> str:
        if not self.config.enabled:
            return "WRITE_THEN_PUBLISH_CLOUD_SYNC 未开启"
        if self.config.missing:
            return "缺少环境变量：" + ", ".join(self.config.missing)
        return ""

    def _require_enabled(self) -> None:
        if not self.enabled or not self.rest:
            raise CloudStoreError(self.disabled_reason or "云同步未配置")

    def _get_tos_client(self):
        if self._tos_client is not None:
            return self._tos_client
        try:
            import tos
        except ImportError as error:
            raise CloudStoreError("缺少 TOS SDK，请安装 requirements.txt") from error
        self._tos_client = tos.TosClientV2(
            ak=self.config.tos_access_key,
            sk=self.config.tos_secret_key,
            endpoint=self.config.tos_endpoint,
            region=self.config.tos_region,
            enable_crc=True,
        )
        return self._tos_client

    def _select_projects(self) -> list[dict]:
        self._require_enabled()
        rows = self.rest.request(
            "GET",
            "/rest/v1/write_then_publish_projects",
            query={
                "workspace_id": f"eq.{self.config.workspace_id}",
                "select": "workspace_id,project_id,title,project_data,updated_at_ms,is_active",
                "order": "updated_at_ms.desc",
            },
        )
        return rows if isinstance(rows, list) else []

    def _select_project(self, project_id: str) -> dict | None:
        self._require_enabled()
        rows = self.rest.request(
            "GET",
            "/rest/v1/write_then_publish_projects",
            query={
                "workspace_id": f"eq.{self.config.workspace_id}",
                "project_id": f"eq.{project_id}",
                "select": "workspace_id,project_id,title,project_data,updated_at_ms,is_active",
                "limit": "1",
            },
        )
        return rows[0] if isinstance(rows, list) and rows else None

    @staticmethod
    def _deletion_timestamp(deletion: dict) -> int:
        try:
            value = float(deletion.get("deletedAt") or 0)
        except (AttributeError, TypeError, ValueError):
            return 0
        return int(value) if value > 0 and value.is_integer() else 0

    @classmethod
    def _normalize_deletions(cls, store: dict) -> list[dict]:
        merged: dict[str, dict] = {}
        source = store.get("deletedProjects") if isinstance(store, dict) else None
        for deletion in source if isinstance(source, list) else []:
            project_id = deletion.get("id") if isinstance(deletion, dict) else None
            deleted_at = cls._deletion_timestamp(deletion)
            if not isinstance(project_id, str) or not project_id or not deleted_at:
                continue
            previous = merged.get(project_id)
            if previous is None or deleted_at > cls._deletion_timestamp(previous):
                merged[project_id] = {"id": project_id, "deletedAt": deleted_at}
        return sorted(merged.values(), key=cls._deletion_timestamp, reverse=True)

    @staticmethod
    def _row_deletion(row: dict) -> dict | None:
        data = row.get("project_data") if isinstance(row, dict) else None
        deleted_at = data.get(PROJECT_TOMBSTONE_FIELD) if isinstance(data, dict) else None
        try:
            deleted_at = int(float(deleted_at or 0))
        except (TypeError, ValueError, OverflowError):
            return None
        project_id = row.get("project_id") if isinstance(row, dict) else None
        if not isinstance(project_id, str) or not project_id or deleted_at <= 0:
            return None
        return {"id": project_id, "deletedAt": deleted_at}

    def _select_assets(self, *, include_deleted: bool = False) -> list[dict]:
        self._require_enabled()
        query = {
            "workspace_id": f"eq.{self.config.workspace_id}",
            "select": "asset_id,workspace_id,sha256,object_key,original_name,mime_type,byte_size,created_at,last_used_at,delete_pending_at,delete_error,deleted_at,metadata",
            "order": "created_at.desc",
        }
        if not include_deleted:
            query["deleted_at"] = "is.null"
            query["delete_pending_at"] = "is.null"
        rows = self.rest.request("GET", "/rest/v1/write_then_publish_assets", query=query)
        return rows if isinstance(rows, list) else []

    def _select_asset(self, asset_id: str, *, include_deleted: bool = False) -> dict | None:
        query = {
            "workspace_id": f"eq.{self.config.workspace_id}",
            "asset_id": f"eq.{asset_id}",
            "select": "asset_id,workspace_id,sha256,object_key,original_name,mime_type,byte_size,created_at,last_used_at,delete_pending_at,delete_error,deleted_at,metadata",
            "limit": "1",
        }
        if not include_deleted:
            query["deleted_at"] = "is.null"
            query["delete_pending_at"] = "is.null"
        rows = self.rest.request("GET", "/rest/v1/write_then_publish_assets", query=query)
        return rows[0] if isinstance(rows, list) and rows else None

    def _select_pending_assets(self) -> list[dict]:
        self._require_enabled()
        rows = self.rest.request(
            "GET",
            "/rest/v1/write_then_publish_assets",
            query={
                "workspace_id": f"eq.{self.config.workspace_id}",
                "delete_pending_at": "not.is.null",
                "deleted_at": "is.null",
                "select": "asset_id,workspace_id,sha256,object_key,original_name,mime_type,byte_size,created_at,last_used_at,delete_pending_at,delete_error,deleted_at,metadata",
                "order": "delete_pending_at.asc",
            },
        )
        return rows if isinstance(rows, list) else []

    @staticmethod
    def _parse_data_uri(src: str) -> tuple[str, bytes] | None:
        match = DATA_URI_RE.match(src)
        if not match:
            return None
        header, encoded = match.groups()
        parts = header.split(";") if header else []
        mime_type = (parts[0] if parts and "/" in parts[0] else "application/octet-stream").lower()
        try:
            if any(part.lower() == "base64" for part in parts[1:]):
                raw = base64.b64decode(encoded, validate=False)
            else:
                raw = unquote_to_bytes(encoded)
        except (ValueError, TypeError) as error:
            raise CloudStoreError("图片 Data URL 无法解析") from error
        if not raw:
            return None
        return mime_type, raw

    @staticmethod
    def _data_uri(mime_type: str, raw: bytes) -> str:
        return f"data:{mime_type};base64,{base64.b64encode(raw).decode('ascii')}"

    @staticmethod
    def _extension(mime_type: str, original_name: str) -> str:
        known = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
            "image/svg+xml": ".svg",
            "image/avif": ".avif",
            "image/bmp": ".bmp",
        }
        extension = known.get(mime_type) or mimetypes.guess_extension(mime_type) or Path(original_name).suffix.lower() or ".bin"
        return extension if re.fullmatch(r"\.[a-z0-9]{1,8}", extension) else ".bin"

    def _upload_private_object(self, key: str, raw: bytes, mime_type: str) -> None:
        import tos

        client = self._get_tos_client()
        try:
            client.head_object(bucket=self.config.tos_bucket, key=key)
            return
        except tos.exceptions.TosServerError as error:
            if getattr(error, "status_code", None) != 404:
                raise CloudStoreError(f"TOS 检查对象失败：{getattr(error, 'code', '')}") from error
        try:
            client.put_object(
                bucket=self.config.tos_bucket,
                key=key,
                content=raw,
                content_length=len(raw),
                content_type=mime_type,
                acl=tos.ACLType.ACL_Private,
                forbid_overwrite=True,
            )
        except tos.exceptions.TosServerError as error:
            if getattr(error, "status_code", None) not in {409, 412}:
                raise CloudStoreError(f"TOS 上传失败：{getattr(error, 'code', '')}") from error
        except tos.exceptions.TosClientError as error:
            raise CloudStoreError(f"TOS 上传失败：{error}") from error

    def _download_object(self, asset: dict) -> bytes:
        asset_id = str(asset["asset_id"])
        cached = self._asset_bytes.get(asset_id)
        if cached is not None:
            return cached
        try:
            output = self._get_tos_client().get_object(bucket=self.config.tos_bucket, key=asset["object_key"])
            raw = output.read()
        except Exception as error:
            raise CloudStoreError(f"TOS 读取资源失败：{asset_id}") from error
        self._asset_bytes[asset_id] = raw
        return raw

    def _insert_asset(self, row: dict) -> dict:
        try:
            rows = self.rest.request(
                "POST",
                "/rest/v1/write_then_publish_assets",
                payload=row,
                prefer="return=representation",
            )
        except CloudStoreError:
            matches = [asset for asset in self._select_assets() if asset.get("sha256") == row["sha256"]]
            if matches:
                return matches[0]
            raise
        if not isinstance(rows, list) or not rows:
            raise CloudStoreError("Supabase 未返回新资源记录")
        return rows[0]

    def _backfill_asset_metadata(self, asset: dict, metadata: dict) -> dict:
        """Add missing provenance fields to a deduplicated cloud asset."""

        current = (
            copy.deepcopy(asset.get("metadata"))
            if isinstance(asset.get("metadata"), dict)
            else {}
        )
        merged = copy.deepcopy(current)
        for key, value in metadata.items():
            if value in (None, "", {}, []):
                continue
            if key == "source" and isinstance(value, dict):
                existing_source = (
                    merged.get("source")
                    if isinstance(merged.get("source"), dict)
                    else {}
                )
                next_source = copy.deepcopy(existing_source)
                for source_key, source_value in value.items():
                    if source_value not in (None, "") and not next_source.get(source_key):
                        next_source[source_key] = source_value
                if next_source:
                    merged["source"] = next_source
            elif key not in merged:
                merged[key] = copy.deepcopy(value)
        if merged == current:
            return asset

        rows = self.rest.request(
            "PATCH",
            "/rest/v1/write_then_publish_assets",
            query={
                "workspace_id": f"eq.{self.config.workspace_id}",
                "asset_id": f"eq.{asset['asset_id']}",
                "deleted_at": "is.null",
                "delete_pending_at": "is.null",
            },
            payload={"metadata": merged},
            prefer="return=representation",
        )
        if isinstance(rows, list) and rows:
            updated = rows[0]
            asset.clear()
            asset.update(updated)
        else:
            asset["metadata"] = merged
        return asset

    def _ensure_asset(
        self,
        image: dict,
        *,
        original_name: str,
        known_by_sha: dict[str, dict],
        known_by_id: dict[str, dict],
        all_by_id: dict[str, dict],
        metadata: dict,
    ) -> dict | None:
        existing_id = image.get("cloudAssetId")
        if isinstance(existing_id, str):
            existing = all_by_id.get(existing_id)
            if existing and (existing.get("deleted_at") or existing.get("delete_pending_at")):
                return None
            if existing:
                return self._backfill_asset_metadata(existing, metadata)

        src = image.get("src")
        if not isinstance(src, str):
            return None
        if src.startswith(TOS_ASSET_PREFIX):
            existing = known_by_id.get(src[len(TOS_ASSET_PREFIX) :])
            return self._backfill_asset_metadata(existing, metadata) if existing else None
        parsed = self._parse_data_uri(src)
        if not parsed:
            return None
        mime_type, raw = parsed
        if not mime_type.startswith("image/"):
            return None
        sha256 = hashlib.sha256(raw).hexdigest()
        existing = known_by_sha.get(sha256)
        if existing:
            return self._backfill_asset_metadata(existing, metadata)

        extension = self._extension(mime_type, original_name)
        object_key = f"{self.config.tos_key_prefix}{sha256[:2]}/{sha256}{extension}"
        self._upload_private_object(object_key, raw, mime_type)
        asset_id = str(uuid.uuid4())
        asset = self._insert_asset(
            {
                "asset_id": asset_id,
                "workspace_id": self.config.workspace_id,
                "sha256": sha256,
                "object_key": object_key,
                "original_name": (original_name or "image")[:255],
                "mime_type": mime_type,
                "byte_size": len(raw),
                "metadata": metadata,
            }
        )
        self._store_cached_asset(str(asset["asset_id"]), asset, raw)
        known_by_sha[sha256] = asset
        known_by_id[str(asset["asset_id"])] = asset
        all_by_id[str(asset["asset_id"])] = asset
        return asset

    def _encode_project(
        self,
        project: dict,
        *,
        known_by_sha: dict[str, dict],
        known_by_id: dict[str, dict],
        all_by_id: dict[str, dict],
    ) -> tuple[dict, dict]:
        local_project = copy.deepcopy(project)
        cloud_project = copy.deepcopy(project)
        # This is a local synchronization cursor. It must not become publishable
        # project data or participate in cloud payload equality.
        cloud_project.pop(CLOUD_BASE_UPDATED_AT_FIELD, None)
        local_data = local_project.get("data") if isinstance(local_project.get("data"), dict) else {}
        cloud_data = cloud_project.get("data") if isinstance(cloud_project.get("data"), dict) else {}
        local_project["data"] = local_data
        cloud_project["data"] = cloud_data

        avatar = local_data.get("avatar")
        if isinstance(avatar, str):
            avatar_asset = self._ensure_asset(
                {"src": avatar},
                original_name="avatar",
                known_by_sha=known_by_sha,
                known_by_id=known_by_id,
                all_by_id=all_by_id,
                metadata={"kind": "avatar", "firstProjectId": project.get("id")},
            )
            if avatar_asset:
                cloud_data["avatar"] = TOS_ASSET_PREFIX + str(avatar_asset["asset_id"])

        local_images = local_data.get("images") if isinstance(local_data.get("images"), dict) else {}
        cloud_images = cloud_data.get("images") if isinstance(cloud_data.get("images"), dict) else {}
        local_data["images"] = local_images
        cloud_data["images"] = cloud_images
        for image_id, local_image in local_images.items():
            if not isinstance(local_image, dict):
                continue
            cloud_image = cloud_images.get(image_id)
            if not isinstance(cloud_image, dict):
                cloud_image = copy.deepcopy(local_image)
                cloud_images[image_id] = cloud_image
            asset_metadata = {
                "kind": "content",
                "firstProjectId": project.get("id"),
                "firstImageId": image_id,
            }
            source_metadata = _safe_asset_source(local_image)
            if source_metadata:
                asset_metadata["source"] = source_metadata
            asset = self._ensure_asset(
                local_image,
                original_name=str(local_image.get("name") or local_image.get("sourcePath") or image_id),
                known_by_sha=known_by_sha,
                known_by_id=known_by_id,
                all_by_id=all_by_id,
                metadata=asset_metadata,
            )
            if asset:
                asset_id = str(asset["asset_id"])
                for target in (local_image, cloud_image):
                    target["cloudAssetId"] = asset_id
                    target["cloudObjectKey"] = asset["object_key"]
                cloud_image["src"] = TOS_ASSET_PREFIX + asset_id
            elif isinstance(local_image.get("cloudAssetId"), str):
                cloud_image["src"] = TOS_DELETED_PREFIX + local_image["cloudAssetId"]
        return local_project, cloud_project

    def _decode_project(self, row: dict, assets_by_id: dict[str, dict]) -> dict:
        data = copy.deepcopy(row.get("project_data") if isinstance(row.get("project_data"), dict) else {})
        avatar = data.get("avatar")
        if isinstance(avatar, str) and avatar.startswith(TOS_ASSET_PREFIX):
            asset = assets_by_id.get(avatar[len(TOS_ASSET_PREFIX) :])
            if asset:
                data["avatar"] = self._data_uri(asset["mime_type"], self._download_object(asset))
        images = data.get("images") if isinstance(data.get("images"), dict) else {}
        data["images"] = images
        for image in images.values():
            if not isinstance(image, dict):
                continue
            src = image.get("src")
            if not isinstance(src, str) or not src.startswith(TOS_ASSET_PREFIX):
                continue
            asset_id = src[len(TOS_ASSET_PREFIX) :]
            asset = assets_by_id.get(asset_id)
            if not asset:
                continue
            # Keep the project-store response small and fetch private images only
            # when the browser actually renders them.
            image["src"] = f"/api/assets/{quote(asset_id)}/content"
            image["cloudAssetId"] = asset_id
            image["cloudObjectKey"] = asset["object_key"]
        return {
            "id": row["project_id"],
            "title": row.get("title") or "未命名项目",
            "updatedAt": int(row.get("updated_at_ms") or 0),
            CLOUD_BASE_UPDATED_AT_FIELD: int(row.get("updated_at_ms") or 0),
            "data": data,
        }

    def _store_from_rows(self, rows: list[dict], assets_by_id: dict[str, dict]) -> dict:
        projects = []
        deletions = []
        for row in rows:
            deletion = self._row_deletion(row)
            if deletion:
                deletions.append(deletion)
            else:
                projects.append(self._decode_project(row, assets_by_id))
        active_id = next(
            (
                row["project_id"]
                for row in rows
                if row.get("is_active") and self._row_deletion(row) is None
            ),
            None,
        )
        return {
            "activeId": active_id,
            "projects": projects,
            "deletedProjects": self._normalize_deletions({"deletedProjects": deletions}),
        }

    @staticmethod
    def _project_timestamp(project: dict | None) -> int:
        try:
            return int(float(project.get("updatedAt") or 0)) if project else 0
        except (AttributeError, TypeError, ValueError, OverflowError):
            return 0

    @classmethod
    def _logical_project_value(cls, value: Any) -> Any:
        if isinstance(value, dict):
            cloud_asset_id = value.get("cloudAssetId")
            derived_keys = {
                "cloudAssetId",
                "cloudObjectKey",
                "localAssetId",
                "localAssetName",
                CLOUD_BASE_UPDATED_AT_FIELD,
            }
            return {
                key: (
                    f"cloud-asset:{cloud_asset_id}"
                    if key == "src" and isinstance(cloud_asset_id, str) and cloud_asset_id
                    else cls._logical_project_value(item)
                )
                for key, item in value.items()
                if key not in derived_keys
            }
        if isinstance(value, list):
            return [cls._logical_project_value(item) for item in value]
        if isinstance(value, str):
            parsed = cls._parse_data_uri(value)
            if parsed:
                _, raw = parsed
                # Historical browser imports sometimes labelled PNG bytes as
                # image/jpeg. The bytes, not that advisory label, define identity.
                return f"data-sha256:{hashlib.sha256(raw).hexdigest()}"
        return value

    @classmethod
    def _project_payload(cls, project: dict) -> str:
        return json.dumps(
            cls._logical_project_value(project),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def _cloud_base_timestamp(cls, project: dict | None) -> int | None:
        if not isinstance(project, dict) or CLOUD_BASE_UPDATED_AT_FIELD not in project:
            return None
        try:
            value = int(float(project.get(CLOUD_BASE_UPDATED_AT_FIELD) or 0))
        except (TypeError, ValueError, OverflowError):
            return None
        return value if value >= 0 else None

    @classmethod
    def _conflict_signature(cls, project: dict) -> str:
        """Content fingerprint of a project's document, independent of id,
        updatedAt, title and conflict bookkeeping. Re-syncing the same unsynced
        local edits therefore maps to one conflict copy instead of a new one
        every sync cycle."""
        data = project.get("data") if isinstance(project.get("data"), dict) else {}
        logical = cls._logical_project_value(data)
        if isinstance(logical, dict):
            logical = {key: item for key, item in logical.items() if key != LOCAL_CONFLICT_OF_FIELD}
        blob = json.dumps(logical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]

    @classmethod
    def _conflict_copy(cls, project: dict, *, original_id: str) -> dict:
        copy_project = copy.deepcopy(project)
        # Content-derived id: the same unsynced local state always maps to the
        # same conflict copy, so repeated syncs stop piling up duplicates.
        copy_project["id"] = f"{original_id}_local_conflict_{cls._conflict_signature(project)}"
        title = str(copy_project.get("title") or "未命名项目")
        if not title.endswith("（冲突副本）"):
            copy_project["title"] = f"{title[:32]}（冲突副本）"
        data = copy_project.get("data") if isinstance(copy_project.get("data"), dict) else {}
        data[LOCAL_CONFLICT_OF_FIELD] = original_id
        copy_project["data"] = data
        # A conflict copy is a new cloud project, not a descendant of the
        # original project's current cloud revision.
        copy_project[CLOUD_BASE_UPDATED_AT_FIELD] = 0
        return copy_project

    @classmethod
    def _merge_stores(cls, local: dict, remote: dict) -> dict:
        remote_projects = {
            project["id"]: project
            for project in remote.get("projects") or []
            if isinstance(project, dict) and isinstance(project.get("id"), str)
        }
        local_projects = {
            project["id"]: project
            for project in local.get("projects") or []
            if isinstance(project, dict) and isinstance(project.get("id"), str)
        }
        merged: dict[str, dict] = {}
        conflicts: list[dict[str, Any]] = []
        active_conflict_id: str | None = None
        for project_id in remote_projects.keys() | local_projects.keys():
            remote_project = remote_projects.get(project_id)
            local_project = local_projects.get(project_id)
            if remote_project is None:
                merged[project_id] = local_project
                continue
            if local_project is None:
                merged[project_id] = remote_project
                continue
            remote_timestamp = cls._project_timestamp(remote_project)
            local_timestamp = cls._project_timestamp(local_project)
            local_base = cls._cloud_base_timestamp(local_project)
            payload_matches = cls._project_payload(local_project) == cls._project_payload(remote_project)

            if payload_matches:
                winner = local_project if local_timestamp >= remote_timestamp else remote_project
                winner[CLOUD_BASE_UPDATED_AT_FIELD] = max(local_timestamp, remote_timestamp)
                merged[project_id] = winner
                continue

            local_has_unsynced_changes = local_base is not None and local_timestamp > local_base
            remote_changed_from_base = local_base is not None and remote_timestamp != local_base
            if local_has_unsynced_changes and remote_changed_from_base:
                merged[project_id] = remote_project
                # Anchor the copy to the ROOT original so a conflict copy that
                # itself diverges cannot spawn nested "_local_conflict_" chains.
                local_data = local_project.get("data") if isinstance(local_project.get("data"), dict) else {}
                root_original_id = local_data.get(LOCAL_CONFLICT_OF_FIELD) or project_id
                conflict_copy = cls._conflict_copy(local_project, original_id=root_original_id)
                conflict_id = conflict_copy["id"]
                # A copy with this id already carries the same content signature,
                # so reuse it instead of re-minting and re-flagging every sync.
                existing = (
                    merged.get(conflict_id)
                    or remote_projects.get(conflict_id)
                    or local_projects.get(conflict_id)
                )
                if existing is None:
                    merged[conflict_id] = conflict_copy
                    conflicts.append(
                        {
                            "projectId": project_id,
                            "conflictProjectId": conflict_id,
                            "localUpdatedAt": local_timestamp,
                            "remoteUpdatedAt": remote_timestamp,
                        }
                    )
                else:
                    merged[conflict_id] = existing
                if local.get("activeId") == project_id:
                    active_conflict_id = conflict_id
                continue

            if local_timestamp > remote_timestamp:
                merged[project_id] = local_project
            elif remote_timestamp > local_timestamp:
                merged[project_id] = remote_project
            elif local_base is None:
                # Legacy projects do not yet carry a cloud base cursor. Preserve
                # the previous strict behavior until one successful sync adds it.
                raise CloudStoreError(f"项目 {project_id} 存在同版本不同内容，请重新保存后再同步")
            else:
                merged[project_id] = remote_project

        remote_deletions = {item["id"]: item for item in cls._normalize_deletions(remote)}
        local_deletions = {item["id"]: item for item in cls._normalize_deletions(local)}
        # A local tombstone is an explicit offline delete intent. If cloud has a
        # later live cache, advance the tombstone once so reconnect cannot revive it.
        for project_id, deletion in local_deletions.items():
            remote_project = remote_projects.get(project_id)
            if remote_project and cls._deletion_timestamp(deletion) <= cls._project_timestamp(remote_project):
                deletion = dict(deletion)
                deletion["deletedAt"] = cls._project_timestamp(remote_project) + 1
                local_deletions[project_id] = deletion

        deletions: dict[str, dict] = {}
        for project_id in remote_deletions.keys() | local_deletions.keys():
            remote_deletion = remote_deletions.get(project_id)
            local_deletion = local_deletions.get(project_id)
            deletions[project_id] = max(
                (item for item in (remote_deletion, local_deletion) if item is not None),
                key=cls._deletion_timestamp,
            )

        winning_deletions = {
            project_id: deletion
            for project_id, deletion in deletions.items()
            if project_id not in merged
            or cls._deletion_timestamp(deletion) >= cls._project_timestamp(merged[project_id])
        }
        projects = [
            project for project_id, project in merged.items() if project_id not in winning_deletions
        ]
        projects = sorted(projects, key=cls._project_timestamp, reverse=True)[:MAX_PROJECTS]
        project_ids = {project["id"] for project in projects}
        active_id = active_conflict_id if active_conflict_id in project_ids else local.get("activeId") if local.get("activeId") in project_ids else remote.get("activeId")
        if active_id not in project_ids:
            active_id = projects[0]["id"] if projects else None
        return {
            "activeId": active_id,
            "projects": projects,
            "deletedProjects": sorted(
                winning_deletions.values(),
                key=cls._deletion_timestamp,
                reverse=True,
            ),
            "conflicts": conflicts,
        }

    def fetch_store(self) -> dict:
        with self._lock:
            assets = self._select_assets()
            assets_by_id = {str(asset["asset_id"]): asset for asset in assets}
            rows = self._select_projects()
            return self._store_from_rows(rows, assets_by_id)

    def sync_store(self, local_store: dict) -> dict:
        with self._lock:
            self._require_enabled()
            self.cleanup_pending_deletions()
            active_assets = self._select_assets()
            all_assets = self._select_assets(include_deleted=True)
            known_by_sha = {asset["sha256"]: asset for asset in active_assets}
            known_by_id = {str(asset["asset_id"]): asset for asset in active_assets}
            all_by_id = {str(asset["asset_id"]): asset for asset in all_assets}
            rows = self._select_projects()
            remote_store = self._store_from_rows(rows, known_by_id)
            merged = self._merge_stores(local_store, remote_store)
            cloud_rows = []
            enriched_projects = []
            for project in merged["projects"]:
                local_project, cloud_project = self._encode_project(
                    project,
                    known_by_sha=known_by_sha,
                    known_by_id=known_by_id,
                    all_by_id=all_by_id,
                )
                enriched_projects.append(local_project)
                cloud_rows.append(
                    {
                        "workspace_id": self.config.workspace_id,
                        "project_id": cloud_project["id"],
                        "title": str(cloud_project.get("title") or "未命名项目")[:255],
                        "project_data": cloud_project.get("data") or {},
                        "updated_at_ms": int(float(cloud_project.get("updatedAt") or 0)),
                        "is_active": cloud_project["id"] == merged.get("activeId"),
                        "synced_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
            for deletion in merged.get("deletedProjects") or []:
                deleted_at = self._deletion_timestamp(deletion)
                if not deleted_at:
                    continue
                cloud_rows.append(
                    {
                        "workspace_id": self.config.workspace_id,
                        "project_id": deletion["id"],
                        "title": "",
                        "project_data": {PROJECT_TOMBSTONE_FIELD: deleted_at},
                        "updated_at_ms": deleted_at,
                        "is_active": False,
                        "synced_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
            if cloud_rows:
                self.rest.request(
                    "POST",
                    "/rest/v1/rpc/sync_write_then_publish_projects",
                    payload={
                        "p_workspace_id": self.config.workspace_id,
                        "p_active_id": merged.get("activeId"),
                        "p_projects": cloud_rows,
                    },
                )
                verified_rows = {row["project_id"]: row for row in self._select_projects()}
                for expected in cloud_rows:
                    actual = verified_rows.get(expected["project_id"])
                    if (
                        actual is None
                        or int(actual.get("updated_at_ms") or 0) != expected["updated_at_ms"]
                        or (actual.get("title") or "") != expected["title"]
                        or self._logical_project_value(actual.get("project_data") or {})
                        != self._logical_project_value(expected["project_data"])
                    ):
                        raise CloudStoreError(
                            f"Supabase 未精确确认项目 {expected['project_id']} 的完整版本"
                        )
                for project in enriched_projects:
                    project[CLOUD_BASE_UPDATED_AT_FIELD] = int(
                        float(project.get("updatedAt") or 0)
                    )
                active_rows = [
                    row["project_id"]
                    for row in verified_rows.values()
                    if row.get("is_active") and self._row_deletion(row) is None
                ]
                if active_rows != ([merged.get("activeId")] if merged.get("activeId") else []):
                    raise CloudStoreError("Supabase 未精确确认当前项目")
            return {
                "activeId": merged.get("activeId"),
                "projects": enriched_projects,
                "deletedProjects": merged.get("deletedProjects") or [],
                "conflicts": merged.get("conflicts") or [],
            }

    def delete_project(self, project_id: str, deleted_at: int, *, active_id: str | None = None) -> int:
        with self._lock:
            self._require_enabled()
            existing = self._select_project(project_id)
            remote_updated_at = int(existing.get("updated_at_ms") or 0) if existing else 0
            confirmed_deleted_at = max(int(deleted_at), remote_updated_at + 1)
            tombstone = {
                "workspace_id": self.config.workspace_id,
                "project_id": project_id,
                "title": "",
                "project_data": {PROJECT_TOMBSTONE_FIELD: confirmed_deleted_at},
                "updated_at_ms": confirmed_deleted_at,
                "is_active": False,
                "synced_at": datetime.now(timezone.utc).isoformat(),
            }
            self.rest.request(
                "POST",
                "/rest/v1/rpc/sync_write_then_publish_projects",
                payload={
                    "p_workspace_id": self.config.workspace_id,
                    "p_active_id": active_id,
                    "p_projects": [tombstone],
                },
            )
            verified = self._select_project(project_id)
            if (
                verified is None
                or int(verified.get("updated_at_ms") or 0) != confirmed_deleted_at
                or self._row_deletion(verified) != {"id": project_id, "deletedAt": confirmed_deleted_at}
            ):
                raise CloudStoreError("Supabase 未确认项目删除")
            return confirmed_deleted_at

    @staticmethod
    def _src_sha256(src: Any) -> str | None:
        if not isinstance(src, str):
            return None
        parsed = CloudStore._parse_data_uri(src)
        return hashlib.sha256(parsed[1]).hexdigest() if parsed else None

    def _reference_counts(self, store: dict, assets: list[dict]) -> dict[str, int]:
        by_sha = {asset["sha256"]: str(asset["asset_id"]) for asset in assets}
        projects_by_asset: dict[str, set[str]] = {str(asset["asset_id"]): set() for asset in assets}
        for project in store.get("projects") or []:
            if not isinstance(project, dict):
                continue
            project_id = str(project.get("id") or "")
            data = project.get("data") if isinstance(project.get("data"), dict) else {}
            avatar_id = by_sha.get(self._src_sha256(data.get("avatar")) or "")
            if avatar_id:
                projects_by_asset.setdefault(avatar_id, set()).add(project_id)
            content = str(data.get("content") or "")
            images = data.get("images") if isinstance(data.get("images"), dict) else {}
            for image_id in IMAGE_TOKEN_RE.findall(content):
                image = images.get(image_id)
                if not isinstance(image, dict):
                    continue
                asset_id = image.get("cloudAssetId")
                if not isinstance(asset_id, str):
                    asset_id = by_sha.get(self._src_sha256(image.get("src")) or "")
                if asset_id:
                    projects_by_asset.setdefault(asset_id, set()).add(project_id)
        return {asset_id: len(project_ids) for asset_id, project_ids in projects_by_asset.items()}

    @staticmethod
    def _public_asset(asset: dict, reference_count: int) -> dict:
        asset_id = str(asset["asset_id"])
        metadata = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
        source = metadata.get("source") if isinstance(metadata.get("source"), dict) else None
        return {
            "assetId": asset_id,
            "originalName": asset.get("original_name") or "image",
            "mimeType": asset.get("mime_type") or "application/octet-stream",
            "byteSize": int(asset.get("byte_size") or 0),
            "createdAt": asset.get("created_at"),
            "lastUsedAt": asset.get("last_used_at"),
            "referenceCount": reference_count,
            "previewUrl": f"/api/assets/{quote(asset_id)}/content",
            "cloudObjectKey": asset.get("object_key"),
            **({"source": source} if source else {}),
        }

    def list_assets(self, local_store: dict) -> list[dict]:
        with self._lock:
            self.cleanup_pending_deletions()
            assets = self._select_assets()
            counts = self._reference_counts(local_store, assets)
            return [self._public_asset(asset, counts.get(str(asset["asset_id"]), 0)) for asset in assets]

    def _disk_cache_paths(self, asset_id: str) -> tuple[Path, Path] | None:
        if self.cache_dir is None or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", asset_id):
            return None
        return self.cache_dir / f"{asset_id}.bin", self.cache_dir / f"{asset_id}.json"

    def _read_cached_asset(self, asset_id: str) -> tuple[dict, bytes] | None:
        with self._cache_lock:
            row = self._asset_rows.get(asset_id)
            raw = self._asset_bytes.get(asset_id)
        if row is not None and raw is not None:
            return row, raw
        paths = self._disk_cache_paths(asset_id)
        if not paths or not paths[0].is_file() or not paths[1].is_file():
            return None
        try:
            row = json.loads(paths[1].read_text("utf-8"))
            raw = paths[0].read_bytes()
        except (OSError, ValueError):
            return None
        expected = str(row.get("sha256") or "")
        if expected and hashlib.sha256(raw).hexdigest() != expected:
            return None
        with self._cache_lock:
            self._asset_rows[asset_id] = row
            self._asset_bytes[asset_id] = raw
        return row, raw

    def _store_cached_asset(self, asset_id: str, row: dict, raw: bytes) -> None:
        with self._cache_lock:
            self._asset_rows[asset_id] = row
            self._asset_bytes[asset_id] = raw
        paths = self._disk_cache_paths(asset_id)
        if not paths:
            return
        try:
            paths[0].parent.mkdir(parents=True, exist_ok=True)
            tmp = paths[0].with_suffix(".bin.tmp")
            tmp.write_bytes(raw)
            os.replace(tmp, paths[0])
            tmp = paths[1].with_suffix(".json.tmp")
            tmp.write_text(json.dumps(row, ensure_ascii=False), "utf-8")
            os.replace(tmp, paths[1])
        except OSError:
            pass

    def _forget_cached_asset(self, asset_id: str) -> None:
        with self._cache_lock:
            self._asset_rows.pop(asset_id, None)
            self._asset_bytes.pop(asset_id, None)
        paths = self._disk_cache_paths(asset_id)
        if paths:
            for path in paths:
                try:
                    path.unlink()
                except OSError:
                    pass

    def get_asset(self, asset_id: str) -> tuple[dict, bytes]:
        self._require_enabled()
        cached = self._read_cached_asset(asset_id)
        if cached is not None:
            return cached
        # Network fetch happens outside self._lock so image loads never queue
        # behind a running project sync.
        asset = self._select_asset(asset_id)
        if not asset:
            raise CloudStoreError("找不到该资源")
        with self._cache_lock:
            raw = self._asset_bytes.get(asset_id)
        if raw is None:
            try:
                output = self._get_tos_client().get_object(bucket=self.config.tos_bucket, key=asset["object_key"])
                raw = output.read()
            except Exception as error:
                raise CloudStoreError(f"TOS 读取资源失败：{asset_id}") from error
        self._store_cached_asset(asset_id, asset, raw)
        return asset, raw

    def get_asset_payload(self, asset_id: str, local_store: dict) -> dict:
        asset, raw = self.get_asset(asset_id)
        counts = self._reference_counts(local_store, [asset])
        public = self._public_asset(asset, counts.get(asset_id, 0))
        return {"asset": public, "dataUrl": self._data_uri(asset["mime_type"], raw)}

    def _finish_pending_deletion(self, asset: dict) -> None:
        asset_id = str(asset["asset_id"])
        try:
            self._get_tos_client().delete_object(bucket=self.config.tos_bucket, key=asset["object_key"])
        except Exception as error:
            try:
                self.rest.request(
                    "PATCH",
                    "/rest/v1/write_then_publish_assets",
                    query={
                        "workspace_id": f"eq.{self.config.workspace_id}",
                        "asset_id": f"eq.{asset_id}",
                        "delete_pending_at": "not.is.null",
                        "deleted_at": "is.null",
                    },
                    payload={"delete_error": str(error)[:500]},
                    prefer="return=minimal",
                )
            except CloudStoreError:
                pass
            raise CloudStoreError("TOS 资源清理失败，已保留待重试状态") from error

        self._forget_cached_asset(asset_id)
        self.rest.request(
            "PATCH",
            "/rest/v1/write_then_publish_assets",
            query={
                "workspace_id": f"eq.{self.config.workspace_id}",
                "asset_id": f"eq.{asset_id}",
                "delete_pending_at": "not.is.null",
                "deleted_at": "is.null",
            },
            payload={
                "deleted_at": datetime.now(timezone.utc).isoformat(),
                "delete_pending_at": None,
                "delete_error": None,
            },
            prefer="return=minimal",
        )

    def cleanup_pending_deletions(self) -> int:
        with self._lock:
            completed = 0
            for asset in self._select_pending_assets():
                try:
                    self._finish_pending_deletion(asset)
                except CloudStoreError:
                    continue
                completed += 1
            return completed

    def delete_asset(self, asset_id: str, local_store: dict, *, force: bool = False) -> None:
        with self._lock:
            self._require_enabled()
            asset = self._select_asset(asset_id)
            if not asset:
                raise CloudStoreError("找不到该资源")
            reference_count = self._reference_counts(local_store, [asset]).get(asset_id, 0)
            if reference_count and not force:
                raise AssetInUseError(reference_count)

            rows = self.rest.request(
                "PATCH",
                "/rest/v1/write_then_publish_assets",
                query={
                    "workspace_id": f"eq.{self.config.workspace_id}",
                    "asset_id": f"eq.{asset_id}",
                    "delete_pending_at": "is.null",
                    "deleted_at": "is.null",
                },
                payload={
                    "delete_pending_at": datetime.now(timezone.utc).isoformat(),
                    "delete_error": None,
                },
                prefer="return=representation",
            )
            if not isinstance(rows, list) or not rows:
                raise CloudStoreError("资源删除状态未能保存")
            self._finish_pending_deletion({**asset, **rows[0]})
