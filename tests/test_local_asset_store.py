import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cloud_store import AssetInUseError
from local_asset_store import LocalAssetStore, LocalAssetStoreError


def data_url(raw: bytes = b"hello", mime_type: str = "image/png") -> str:
    return f"data:{mime_type};base64,{base64.b64encode(raw).decode('ascii')}"


def project_store(*, first: bytes = b"hello", second: bytes = b"hello") -> dict:
    return {
        "activeId": "project-1",
        "projects": [
            {
                "id": "project-1",
                "title": "测试",
                "updatedAt": 1,
                "data": {
                    "content": "[[image:image-1]]\n[[image:image-2]]",
                    "images": {
                        "image-1": {"src": data_url(first), "name": "第一张.png"},
                        "image-2": {"src": data_url(second), "name": "第二张.png"},
                    },
                },
            }
        ],
    }


class LocalAssetStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "project"
        self.data_dir = Path(self.temporary.name) / "isolated-data"
        self.asset_dir = Path(self.temporary.name) / "explicit-assets"
        self.root.mkdir()
        self.store = LocalAssetStore(
            self.root,
            data_dir=self.data_dir,
            env={"WRITE_THEN_PUBLISH_ASSET_DIR": str(self.asset_dir)},
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_zero_config_uses_managed_local_directory_without_prompt(self):
        default_store = LocalAssetStore(self.root, data_dir=self.data_dir, env={})
        self.assertEqual(default_store.asset_dir, (self.data_dir / "assets").resolve())
        self.assertEqual(default_store.settings_file, self.data_dir.resolve() / "storage-settings.json")
        self.assertFalse(default_store.directory_selection_required)

        source = project_store()
        enriched = default_store.sync_store(source)
        first = enriched["projects"][0]["data"]["images"]["image-1"]
        second = enriched["projects"][0]["data"]["images"]["image-2"]

        self.assertTrue(default_store.asset_dir.is_dir())
        self.assertEqual(first["localAssetId"], second["localAssetId"])
        self.assertTrue((default_store.asset_dir / first["localAssetName"]).is_file())
        self.assertTrue(default_store.manifest_file.is_file())

    def test_env_directory_takes_priority_over_settings(self):
        setting_directory = Path(self.temporary.name) / "from-setting"
        env_directory = Path(self.temporary.name) / "from-env"
        self.data_dir.mkdir()
        self.store.settings_file.write_text(
            json.dumps({"assetDirectory": str(setting_directory)}),
            encoding="utf-8",
        )
        configured = LocalAssetStore(
            self.root,
            data_dir=self.data_dir,
            env={"WRITE_THEN_PUBLISH_ASSET_DIR": str(env_directory)},
        )
        self.assertEqual(configured.asset_dir, env_directory.resolve())

    def test_sync_deduplicates_and_enriches_a_copy(self):
        source = project_store()
        enriched = self.store.sync_store(source)
        first = enriched["projects"][0]["data"]["images"]["image-1"]
        second = enriched["projects"][0]["data"]["images"]["image-2"]

        self.assertNotIn("localAssetId", source["projects"][0]["data"]["images"]["image-1"])
        self.assertEqual(first["localAssetId"], second["localAssetId"])
        self.assertEqual(first["localAssetName"], second["localAssetName"])
        visible_files = [path for path in self.store.asset_dir.iterdir() if not path.name.startswith(".")]
        self.assertEqual(len(visible_files), 1)

        assets = self.store.list_assets(enriched)
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["referenceCount"], 1)
        self.assertEqual(assets[0]["storageMode"], "local-server")
        self.assertEqual(assets[0]["folderName"], "explicit-assets")
        self.assertEqual(assets[0]["localFileName"], first["localAssetName"])

        payload = self.store.get_asset_payload(first["localAssetId"], enriched)
        self.assertEqual(payload["dataUrl"], data_url())
        self.assertEqual(payload["asset"]["storageMode"], "local-server")

    def test_web_source_metadata_survives_local_manifest_and_reinsert_payload(self):
        source = project_store()
        provenance = {
            "kind": "web",
            "provider": "wikimedia",
            "sourcePageUrl": "https://commons.wikimedia.org/wiki/File:Safe.jpg",
            "creator": "Alice",
            "license": "CC BY-SA 4.0",
            "licenseUrl": "https://creativecommons.org/licenses/by-sa/4.0/",
        }
        source["projects"][0]["data"]["images"]["image-1"]["source"] = provenance
        enriched = self.store.sync_store(source)
        asset = self.store.list_assets(enriched)[0]
        self.assertEqual(asset["source"], provenance)
        payload = self.store.get_asset_payload(asset["assetId"], enriched)
        self.assertEqual(payload["asset"]["source"], provenance)
        manifest = json.loads(self.store.manifest_file.read_text(encoding="utf-8"))
        self.assertEqual(
            next(iter(manifest["assets"].values()))["source"],
            provenance,
        )

    def test_delete_requires_force_when_referenced_and_writes_tombstone(self):
        enriched = self.store.sync_store(project_store())
        asset = self.store.list_assets(enriched)[0]
        asset_id = asset["assetId"]
        asset_file = self.store.asset_dir / asset["localFileName"]

        with self.assertRaises(AssetInUseError) as raised:
            self.store.delete_asset(asset_id, enriched)
        self.assertEqual(raised.exception.reference_count, 1)
        self.assertTrue(asset_file.exists())

        self.store.delete_asset(asset_id, enriched, force=True)
        self.assertFalse(asset_file.exists())
        self.assertEqual(self.store.list_assets(enriched), [])
        tombstones = json.loads(self.store.tombstones_file.read_text(encoding="utf-8"))
        self.assertIn(asset_id, tombstones["assets"])
        with self.assertRaises(LocalAssetStoreError):
            self.store.get_asset(asset_id)

    def test_unreferenced_asset_can_be_deleted_without_force(self):
        enriched = self.store.sync_store(project_store())
        enriched["projects"][0]["data"]["content"] = "正文已移除图片标记"
        asset_id = self.store.list_assets(enriched)[0]["assetId"]
        self.store.delete_asset(asset_id, enriched)
        self.assertEqual(self.store.list_assets(enriched), [])

    def test_deleted_bytes_do_not_reappear_from_embedded_project_copy(self):
        enriched = self.store.sync_store(project_store())
        original_id = self.store.list_assets(enriched)[0]["assetId"]
        enriched["projects"][0]["data"]["content"] = ""
        self.store.delete_asset(original_id, enriched)

        replacement = self.store.sync_store(project_store())
        self.assertEqual(self.store.list_assets(replacement), [])

    def test_missing_managed_file_is_repaired_from_embedded_copy(self):
        enriched = self.store.sync_store(project_store())
        asset = self.store.list_assets(enriched)[0]
        managed_file = self.store.asset_dir / asset["localFileName"]
        managed_file.unlink()

        repaired = self.store.sync_store(enriched)
        self.assertTrue(managed_file.exists())
        self.assertEqual(self.store.get_asset_payload(asset["assetId"], repaired)["dataUrl"], data_url())

    def test_directory_switch_migrates_active_assets_and_tombstones(self):
        enriched = self.store.sync_store(project_store(first=b"one", second=b"two"))
        assets = self.store.list_assets(enriched)
        deleted = assets[0]
        enriched["projects"][0]["data"]["content"] = ""
        self.store.delete_asset(deleted["assetId"], enriched)

        selected = Path(self.temporary.name) / "migrated-assets"
        selected.mkdir()
        self.store._directory_selector = lambda: selected
        result = self.store.select_asset_directory()
        self.assertFalse(result["directorySelectionRequired"])

        migrated = self.store.sync_store(enriched)
        migrated_ids = {asset["assetId"] for asset in self.store.list_assets(migrated)}
        self.assertNotIn(deleted["assetId"], migrated_ids)
        tombstones = json.loads(self.store.tombstones_file.read_text(encoding="utf-8"))
        self.assertIn(deleted["assetId"], tombstones["assets"])

    def test_native_picker_rejects_project_directory(self):
        selected = self.root / "src"
        selected.mkdir()
        store = LocalAssetStore(
            self.root,
            data_dir=self.data_dir,
            env={},
            directory_selector=lambda: selected,
        )
        with self.assertRaises(LocalAssetStoreError):
            store.select_asset_directory()

    def test_native_picker_is_only_source_for_persisted_directory(self):
        selected = Path(self.temporary.name) / "chosen-by-os"
        selected.mkdir()
        store = LocalAssetStore(
            self.root,
            data_dir=self.data_dir,
            env={},
            directory_selector=lambda: selected,
        )
        result = store.select_asset_directory()

        self.assertFalse(result["cancelled"])
        self.assertEqual(result["folderName"], selected.name)
        self.assertNotIn("assetDirectory", result)
        settings = json.loads(store.settings_file.read_text(encoding="utf-8"))
        self.assertEqual(settings["assetDirectory"], str(selected.resolve()))
        reloaded = LocalAssetStore(self.root, data_dir=self.data_dir, env={})
        self.assertEqual(reloaded.asset_dir, selected.resolve())
        self.assertFalse(reloaded.directory_selection_required)

    def test_native_picker_cancel_does_not_write_settings(self):
        store = LocalAssetStore(
            self.root,
            data_dir=self.data_dir,
            env={},
            directory_selector=lambda: None,
        )
        result = store.select_asset_directory()
        self.assertTrue(result["cancelled"])
        self.assertFalse(store.settings_file.exists())

    def test_server_cloud_failure_flag_selects_local_fallback(self):
        import server

        isolated = LocalAssetStore(self.root, data_dir=self.data_dir, env={})
        with mock.patch.object(server, "LOCAL_ASSETS", isolated), mock.patch.object(
            server, "DATA_DIR", self.data_dir
        ), mock.patch.object(server, "STORE_FILE", self.data_dir / "project-store.json"):
            with server.CLOUD_STATUS_LOCK:
                previous = dict(server.CLOUD_STATUS)
            try:
                server.record_cloud_failure(LocalAssetStoreError("TOS 读取资源失败"))
                self.assertTrue(server.cloud_status()["fallbackToLocal"])
                payload = server.local_asset_library_payload(reason="TOS 读取资源失败")
                self.assertFalse(payload["cloudEnabled"])
                self.assertEqual(payload["storageMode"], "local-server")
                self.assertEqual(payload["folderName"], "assets")
                self.assertFalse(payload["directorySelectionRequired"])
            finally:
                with server.CLOUD_STATUS_LOCK:
                    server.CLOUD_STATUS.clear()
                    server.CLOUD_STATUS.update(previous)


if __name__ == "__main__":
    unittest.main()
