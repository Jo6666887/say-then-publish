"""Disk-backed image asset library used when Supabase/TOS is unavailable.

The browser never supplies a filesystem path.  The storage directory is
resolved from trusted server configuration or selected by a native directory
picker launched by the server process.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote_to_bytes

from cloud_store import AssetInUseError, CloudStoreError


DATA_URI_RE = re.compile(r"^data:([^,]*?),(.*)$", re.DOTALL)
IMAGE_TOKEN_RE = re.compile(r"\[\[image:([^\]]+)\]\]")
SAFE_FILENAME_RE = re.compile(r"[^\w.()\-\u4e00-\u9fff ]+", re.UNICODE)
MANIFEST_FILENAME = ".write-then-publish-manifest.json"
TOMBSTONES_FILENAME = ".write-then-publish-tombstones.json"


class LocalAssetStoreError(CloudStoreError):
    """A local asset cannot be stored, read, or removed safely."""


def choose_native_directory() -> Path | None:
    """Ask the local OS for a directory without accepting a browser path."""

    if sys.platform == "darwin":
        script = 'POSIX path of (choose folder with prompt "选择图片资源存储文件夹")'
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise LocalAssetStoreError(f"无法打开系统文件夹选择器：{error}") from error
        if result.returncode != 0:
            # AppleScript returns -128 when the user presses Cancel.
            if "-128" in result.stderr or "User canceled" in result.stderr:
                return None
            raise LocalAssetStoreError("系统文件夹选择器未能完成")
        selected = result.stdout.strip()
        return Path(selected) if selected else None

    try:
        import tkinter
        from tkinter import filedialog

        root = tkinter.Tk()
        root.withdraw()
        try:
            selected = filedialog.askdirectory(title="选择图片资源存储文件夹", mustexist=True)
        finally:
            root.destroy()
    except (ImportError, OSError) as error:
        raise LocalAssetStoreError(f"当前系统无法打开文件夹选择器：{error}") from error
    except Exception as error:
        # TclError is unavailable when importing tkinter itself fails.
        raise LocalAssetStoreError(f"当前系统无法打开文件夹选择器：{error}") from error
    return Path(selected) if selected else None


class LocalAssetStore:
    """SHA-deduplicated local image library with CloudStore-compatible APIs."""

    def __init__(
        self,
        root: Path,
        data_dir: Path | None = None,
        *,
        env: Mapping[str, str] | None = None,
        directory_selector: Callable[[], Path | None] | None = None,
    ):
        self.root = Path(root).expanduser().resolve()
        self.data_dir = Path(data_dir).expanduser().resolve() if data_dir else self.root / "runtime-data"
        self.settings_file = self.data_dir / "storage-settings.json"
        self._env = os.environ if env is None else env
        self._directory_selector = directory_selector or choose_native_directory
        self._lock = threading.RLock()
        self._asset_dir, self._directory_source = self._resolve_asset_directory()

    @classmethod
    def from_root(
        cls,
        root: Path,
        data_dir: Path | None = None,
        **kwargs: Any,
    ) -> "LocalAssetStore":
        return cls(root, data_dir=data_dir, **kwargs)

    @property
    def enabled(self) -> bool:
        return True

    @property
    def asset_dir(self) -> Path:
        return self._asset_dir

    @property
    def folder_name(self) -> str:
        return self.asset_dir.name or str(self.asset_dir)

    @property
    def directory_selection_required(self) -> bool:
        """True until a user or environment explicitly chooses a directory."""

        return self._directory_source == "default"

    @property
    def directory_source(self) -> str:
        return self._directory_source

    @property
    def manifest_file(self) -> Path:
        return self.asset_dir / MANIFEST_FILENAME

    @property
    def tombstones_file(self) -> Path:
        return self.asset_dir / TOMBSTONES_FILENAME

    def _resolve_asset_directory(self) -> tuple[Path, str]:
        configured = str(self._env.get("WRITE_THEN_PUBLISH_ASSET_DIR", "")).strip()
        if configured:
            path = Path(configured).expanduser()
            return (path if path.is_absolute() else self.root / path).resolve(), "environment"

        settings = self._read_settings()
        configured = settings.get("assetDirectory")
        if isinstance(configured, str) and configured.strip():
            path = Path(configured).expanduser()
            return (path if path.is_absolute() else self.root / path).resolve(), "selected"
        return (self.data_dir / "assets").resolve(), "default"

    def _read_settings(self) -> dict[str, Any]:
        if not self.settings_file.exists():
            return {}
        try:
            payload = json.loads(self.settings_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(temporary, path)
        except OSError as error:
            raise LocalAssetStoreError("无法写入本地资源索引") from error
        finally:
            try:
                temporary.unlink()
            except OSError:
                pass

    def select_asset_directory(self) -> dict[str, Any]:
        """Select and persist a directory using only the native trusted picker."""

        selected = self._directory_selector()
        if selected is None:
            return {
                "cancelled": True,
                "folderName": "" if self.directory_selection_required else self.folder_name,
                "storageMode": "local-server",
                "directorySelectionRequired": self.directory_selection_required,
            }

        with self._lock:
            selected = Path(selected).expanduser().resolve()
            if not selected.is_dir():
                raise LocalAssetStoreError("所选资源存储位置不是文件夹")
            if not os.access(selected, os.R_OK | os.W_OK):
                raise LocalAssetStoreError("所选资源存储文件夹不可读写")
            if selected == self.root or self.root in selected.parents:
                raise LocalAssetStoreError("请选择项目目录以外的资源文件夹，避免图片进入 Git 或被本地网页公开")

            old_directory = self.asset_dir
            self._migrate_asset_directory(old_directory, selected)
            self._atomic_json_write(
                self.settings_file,
                {
                    "version": 1,
                    "assetDirectory": str(selected),
                    "updatedAt": self._now(),
                },
            )
            self._asset_dir = selected
            self._directory_source = "selected"
            return {
                "cancelled": False,
                "folderName": self.folder_name,
                "storageMode": "local-server",
                "directorySelectionRequired": False,
            }

    @staticmethod
    def _safe_file_in(directory: Path, file_name: str) -> Path:
        directory = Path(directory).expanduser().resolve()
        if not isinstance(file_name, str) or not file_name or Path(file_name).name != file_name:
            raise LocalAssetStoreError("本地资源索引包含不安全的文件名")
        path = directory / file_name
        if path.resolve().parent != directory:
            raise LocalAssetStoreError("本地资源路径越界")
        return path

    @classmethod
    def _atomic_bytes_write(cls, directory: Path, file_name: str, raw: bytes) -> None:
        path = cls._safe_file_in(directory, file_name)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                if hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(raw).digest():
                    return
        except OSError as error:
            raise LocalAssetStoreError("现有本地资源文件无法校验") from error
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(raw)
            os.replace(temporary, path)
        except OSError as error:
            raise LocalAssetStoreError("无法写入本地资源文件夹") from error
        finally:
            try:
                temporary.unlink()
            except OSError:
                pass

    def _migrate_asset_directory(self, old_directory: Path, selected: Path) -> None:
        """Copy managed assets and deletion records before switching folders."""

        old_directory = Path(old_directory).expanduser().resolve()
        selected = Path(selected).expanduser().resolve()
        if old_directory == selected:
            return

        old_manifest = self._read_index(old_directory / MANIFEST_FILENAME, "索引")
        old_tombstones = self._read_index(old_directory / TOMBSTONES_FILENAME, "删除记录")
        target_manifest = self._read_index(selected / MANIFEST_FILENAME, "索引")
        target_tombstones = self._read_index(selected / TOMBSTONES_FILENAME, "删除记录")

        merged_assets = dict(target_manifest["assets"])
        merged_tombstones = dict(target_tombstones["assets"])
        merged_tombstones.update(old_tombstones["assets"])

        for asset_id, asset in old_manifest["assets"].items():
            if asset_id in old_tombstones["assets"] or not isinstance(asset, dict):
                continue
            file_name = str(asset.get("file_name") or "")
            try:
                raw = self._safe_file_in(old_directory, file_name).read_bytes()
            except OSError as error:
                raise LocalAssetStoreError(f"旧资源无法迁移：{file_name or asset_id}") from error
            expected_sha = str(asset.get("sha256") or "")
            if expected_sha and hashlib.sha256(raw).hexdigest() != expected_sha:
                raise LocalAssetStoreError(f"旧资源校验失败，未切换文件夹：{file_name or asset_id}")
            self._atomic_bytes_write(selected, file_name, raw)
            merged_assets[asset_id] = copy.deepcopy(asset)

        for asset_id, tombstone in merged_tombstones.items():
            merged_assets.pop(asset_id, None)
            if not isinstance(tombstone, dict):
                continue
            file_name = str(tombstone.get("file_name") or "")
            if file_name:
                try:
                    self._safe_file_in(selected, file_name).unlink(missing_ok=True)
                except OSError as error:
                    raise LocalAssetStoreError("无法迁移本地资源删除记录") from error

        now = self._now()
        self._atomic_json_write(
            selected / MANIFEST_FILENAME,
            {"version": 1, "assets": merged_assets, "updatedAt": now},
        )
        self._atomic_json_write(
            selected / TOMBSTONES_FILENAME,
            {"version": 1, "assets": merged_tombstones, "updatedAt": now},
        )

    @staticmethod
    def _read_index(path: Path, label: str) -> dict[str, Any]:
        if not path.exists():
            return {"version": 1, "assets": {}}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise LocalAssetStoreError(f"本地资源{label}无法读取") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("assets"), dict):
            raise LocalAssetStoreError(f"本地资源{label}格式无效")
        return payload

    def _read_manifest(self) -> dict[str, Any]:
        return self._read_index(self.manifest_file, "索引")

    def _read_tombstones(self) -> dict[str, Any]:
        return self._read_index(self.tombstones_file, "删除记录")

    def _write_manifest(self, payload: dict[str, Any]) -> None:
        self._atomic_json_write(self.manifest_file, payload)

    def _write_tombstones(self, payload: dict[str, Any]) -> None:
        self._atomic_json_write(self.tombstones_file, payload)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

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
            raise LocalAssetStoreError("图片 Data URL 无法解析") from error
        return (mime_type, raw) if raw else None

    @staticmethod
    def _data_uri(mime_type: str, raw: bytes) -> str:
        encoded = base64.b64encode(raw).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    @staticmethod
    def _extension(mime_type: str, original_name: str) -> str:
        known = {
            "image/avif": ".avif",
            "image/bmp": ".bmp",
            "image/gif": ".gif",
            "image/heic": ".heic",
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/svg+xml": ".svg",
            "image/webp": ".webp",
        }
        guessed = known.get(mime_type) or mimetypes.guess_extension(mime_type)
        extension = guessed or Path(original_name).suffix.lower() or ".bin"
        return extension if re.fullmatch(r"\.[a-z0-9]{1,8}", extension) else ".bin"

    @classmethod
    def _safe_original_name(cls, original_name: str, mime_type: str) -> str:
        name = Path(str(original_name or "图片").replace("\\", "/")).name
        name = SAFE_FILENAME_RE.sub("-", name).lstrip(".").strip() or "图片"
        extension = cls._extension(mime_type, name)
        if Path(name).suffix.lower() != extension:
            name = f"{Path(name).stem or '图片'}{extension}"
        return name[-96:]

    def _safe_asset_file(self, file_name: str) -> Path:
        return self._safe_file_in(self.asset_dir, file_name)

    def _write_asset_bytes(self, file_name: str, raw: bytes) -> None:
        self._atomic_bytes_write(self.asset_dir, file_name, raw)

    def _ensure_asset(
        self,
        image: dict[str, Any],
        assets: dict[str, dict[str, Any]],
        tombstones: dict[str, Any],
        by_sha: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        existing_id = image.get("localAssetId")
        existing = None
        if isinstance(existing_id, str):
            if existing_id in tombstones:
                return None
            existing = assets.get(existing_id)
            if not isinstance(existing, dict):
                existing = None

        src = image.get("src")
        if not isinstance(src, str):
            if existing:
                image["localAssetName"] = existing.get("file_name")
                return existing
            return None
        parsed = self._parse_data_uri(src)
        if not parsed:
            return None
        mime_type, raw = parsed
        if not mime_type.startswith("image/"):
            return None
        sha256 = hashlib.sha256(raw).hexdigest()
        if existing and str(existing.get("sha256") or "") == sha256:
            self._write_asset_bytes(str(existing.get("file_name") or ""), raw)
            existing["last_used_at"] = self._now()
            image["localAssetName"] = existing.get("file_name")
            return existing

        deleted_hashes = {
            str(tombstone.get("sha256"))
            for tombstone in tombstones.values()
            if isinstance(tombstone, dict) and tombstone.get("sha256")
        }
        if sha256 in deleted_hashes:
            return None

        existing = by_sha.get(sha256)
        now = self._now()
        if existing:
            self._write_asset_bytes(str(existing.get("file_name") or ""), raw)
            existing["last_used_at"] = now
            return existing

        original_name = str(image.get("name") or image.get("sourcePath") or "图片")
        safe_name = self._safe_original_name(original_name, mime_type)
        file_name = f"{sha256[:24]}__{safe_name}"
        self._write_asset_bytes(file_name, raw)
        asset_id = f"local-{uuid.uuid4()}"
        asset = {
            "asset_id": asset_id,
            "sha256": sha256,
            "file_name": file_name,
            "original_name": safe_name,
            "mime_type": mime_type,
            "byte_size": len(raw),
            "created_at": now,
            "last_used_at": now,
        }
        assets[asset_id] = asset
        by_sha[sha256] = asset
        return asset

    def sync_store(self, local_store: dict[str, Any]) -> dict[str, Any]:
        """Copy data:image resources to disk and enrich the copied store."""

        with self._lock:
            enriched = copy.deepcopy(local_store)
            if self.directory_selection_required:
                return enriched
            manifest = self._read_manifest()
            tombstones = self._read_tombstones().get("assets", {})
            assets = manifest["assets"]
            active_assets = {
                asset_id: asset
                for asset_id, asset in assets.items()
                if asset_id not in tombstones and isinstance(asset, dict)
            }
            by_sha = {
                str(asset.get("sha256")): asset
                for asset in active_assets.values()
                if isinstance(asset.get("sha256"), str)
            }
            changed = False
            for project in enriched.get("projects") or []:
                if not isinstance(project, dict):
                    continue
                data = project.get("data") if isinstance(project.get("data"), dict) else {}
                images = data.get("images") if isinstance(data.get("images"), dict) else {}
                for image in images.values():
                    if not isinstance(image, dict):
                        continue
                    before = (image.get("localAssetId"), image.get("localAssetName"))
                    asset = self._ensure_asset(image, assets, tombstones, by_sha)
                    if not asset:
                        continue
                    image["localAssetId"] = asset["asset_id"]
                    image["localAssetName"] = asset["file_name"]
                    changed = changed or before != (image["localAssetId"], image["localAssetName"])
            if assets or changed:
                manifest["version"] = 1
                manifest["updatedAt"] = self._now()
                self._write_manifest(manifest)
            return enriched

    sync_project_store = sync_store
    sync_from_project_store = sync_store

    @staticmethod
    def _src_sha256(src: Any) -> str | None:
        if not isinstance(src, str):
            return None
        parsed = LocalAssetStore._parse_data_uri(src)
        return hashlib.sha256(parsed[1]).hexdigest() if parsed else None

    def _reference_counts(self, store: dict[str, Any], assets: list[dict[str, Any]]) -> dict[str, int]:
        by_id = {str(asset["asset_id"]): asset for asset in assets}
        by_name = {str(asset.get("file_name")): str(asset["asset_id"]) for asset in assets}
        by_sha = {str(asset.get("sha256")): str(asset["asset_id"]) for asset in assets}
        projects_by_asset: dict[str, set[str]] = {asset_id: set() for asset_id in by_id}
        for project in store.get("projects") or []:
            if not isinstance(project, dict):
                continue
            project_id = str(project.get("id") or "")
            data = project.get("data") if isinstance(project.get("data"), dict) else {}
            content = str(data.get("content") or "")
            images = data.get("images") if isinstance(data.get("images"), dict) else {}
            for image_id in IMAGE_TOKEN_RE.findall(content):
                image = images.get(image_id)
                if not isinstance(image, dict):
                    continue
                asset_id = image.get("localAssetId")
                if not isinstance(asset_id, str) or asset_id not in by_id:
                    asset_id = by_name.get(str(image.get("localAssetName") or ""))
                if not asset_id:
                    asset_id = by_sha.get(self._src_sha256(image.get("src")) or "")
                if asset_id:
                    projects_by_asset.setdefault(asset_id, set()).add(project_id)
        return {asset_id: len(project_ids) for asset_id, project_ids in projects_by_asset.items()}

    def _active_assets(self) -> list[dict[str, Any]]:
        manifest = self._read_manifest()
        tombstones = self._read_tombstones().get("assets", {})
        return [
            asset
            for asset_id, asset in manifest["assets"].items()
            if asset_id not in tombstones and isinstance(asset, dict)
        ]

    def _public_asset(self, asset: dict[str, Any], reference_count: int) -> dict[str, Any]:
        asset_id = str(asset["asset_id"])
        file_name = str(asset.get("file_name") or "")
        return {
            "assetId": asset_id,
            "originalName": asset.get("original_name") or "图片",
            "mimeType": asset.get("mime_type") or "application/octet-stream",
            "byteSize": int(asset.get("byte_size") or 0),
            "createdAt": asset.get("created_at"),
            "lastUsedAt": asset.get("last_used_at"),
            "referenceCount": reference_count,
            "previewUrl": f"/api/assets/{quote(asset_id)}/content",
            "localFileName": file_name,
            "folderName": self.folder_name,
            "storageMode": "local-server",
        }

    def list_assets(self, local_store: dict[str, Any]) -> list[dict[str, Any]]:
        with self._lock:
            assets = self._active_assets()
            counts = self._reference_counts(local_store, assets)
            assets.sort(key=lambda asset: str(asset.get("last_used_at") or ""), reverse=True)
            return [self._public_asset(asset, counts.get(str(asset["asset_id"]), 0)) for asset in assets]

    def _select_asset(self, asset_id: str) -> dict[str, Any] | None:
        if not isinstance(asset_id, str):
            return None
        manifest = self._read_manifest()
        tombstones = self._read_tombstones().get("assets", {})
        if asset_id in tombstones:
            return None
        asset = manifest["assets"].get(asset_id)
        return asset if isinstance(asset, dict) else None

    def get_asset(self, asset_id: str) -> tuple[dict[str, Any], bytes]:
        with self._lock:
            asset = self._select_asset(asset_id)
            if not asset:
                raise LocalAssetStoreError("找不到该资源")
            try:
                raw = self._safe_asset_file(str(asset.get("file_name") or "")).read_bytes()
            except OSError as error:
                raise LocalAssetStoreError("本地资源文件无法读取") from error
            expected_sha = str(asset.get("sha256") or "")
            if expected_sha and hashlib.sha256(raw).hexdigest() != expected_sha:
                raise LocalAssetStoreError("本地资源文件校验失败")
            return asset, raw

    def get_asset_payload(self, asset_id: str, local_store: dict[str, Any]) -> dict[str, Any]:
        asset, raw = self.get_asset(asset_id)
        counts = self._reference_counts(local_store, [asset])
        public = self._public_asset(asset, counts.get(asset_id, 0))
        return {"asset": public, "dataUrl": self._data_uri(str(asset["mime_type"]), raw)}

    def delete_asset(self, asset_id: str, local_store: dict[str, Any], *, force: bool = False) -> None:
        with self._lock:
            manifest = self._read_manifest()
            tombstones = self._read_tombstones()
            asset = manifest["assets"].get(asset_id)
            if not isinstance(asset, dict) or asset_id in tombstones["assets"]:
                raise LocalAssetStoreError("找不到该资源")
            reference_count = self._reference_counts(local_store, [asset]).get(asset_id, 0)
            if reference_count and not force:
                raise AssetInUseError(reference_count)

            deleted_at = self._now()
            tombstones["assets"][asset_id] = {
                **asset,
                "deleted_at": deleted_at,
            }
            tombstones["updatedAt"] = deleted_at
            self._write_tombstones(tombstones)
            try:
                self._safe_asset_file(str(asset.get("file_name") or "")).unlink(missing_ok=True)
            except OSError as error:
                tombstones["assets"].pop(asset_id, None)
                self._write_tombstones(tombstones)
                raise LocalAssetStoreError("本地资源文件删除失败") from error
            manifest["assets"].pop(asset_id, None)
            manifest["updatedAt"] = deleted_at
            self._write_manifest(manifest)


__all__ = [
    "AssetInUseError",
    "LocalAssetStore",
    "LocalAssetStoreError",
    "choose_native_directory",
]
