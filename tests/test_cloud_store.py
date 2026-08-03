import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cloud_store import CloudConfig, CloudStore, CloudStoreError


def test_config() -> CloudConfig:
    return CloudConfig(
        enabled=False,
        supabase_url="",
        supabase_secret_key="",
        workspace_id="test-workspace",
        tos_access_key="",
        tos_secret_key="",
        tos_endpoint="",
        tos_region="",
        tos_bucket="",
        tos_key_prefix="write-then-publish/assets/",
    )


def ready_test_config() -> CloudConfig:
    return CloudConfig(
        enabled=True,
        supabase_url="https://example.supabase.co",
        supabase_secret_key="test-secret",
        workspace_id="test-workspace",
        tos_access_key="test-ak",
        tos_secret_key="test-sk",
        tos_endpoint="tos.example.com",
        tos_region="test-region",
        tos_bucket="test-bucket",
        tos_key_prefix="write-then-publish/assets/",
    )


class RecordingCloudStore(CloudStore):
    def __init__(self):
        super().__init__(test_config())
        self.seen_images = []
        self.seen_metadata = []

    def _ensure_asset(self, image, **kwargs):
        self.seen_images.append(copy.deepcopy(image))
        self.seen_metadata.append(copy.deepcopy(kwargs.get("metadata")))
        return {
            "asset_id": "asset-1",
            "object_key": "write-then-publish/assets/aa/image.png",
        }


class FakeDeletionRest:
    def __init__(self, events):
        self.events = events

    def request(self, method, path, *, query=None, payload=None, prefer=None):
        if payload and payload.get("delete_pending_at"):
            self.events.append("db:pending")
            return [{"delete_pending_at": payload["delete_pending_at"]}]
        if payload and payload.get("delete_error"):
            self.events.append("db:error")
            return None
        if payload and payload.get("deleted_at"):
            self.events.append("db:final")
            return None
        raise AssertionError(f"Unexpected request: {method} {path} {query} {payload} {prefer}")


class FakeTosClient:
    def __init__(self, events, *, fail=False):
        self.events = events
        self.fail = fail

    def delete_object(self, **kwargs):
        self.events.append("tos:delete")
        if self.fail:
            raise RuntimeError("temporary failure")


class FakeMetadataRest:
    def __init__(self):
        self.calls = []

    def request(self, method, path, *, query=None, payload=None, prefer=None):
        self.calls.append((method, path, query, payload, prefer))
        if method != "PATCH":
            raise AssertionError(f"Unexpected request: {method} {path}")
        return [
            {
                "asset_id": query["asset_id"].removeprefix("eq."),
                "sha256": "existing-sha",
                "object_key": "existing.png",
                "metadata": copy.deepcopy(payload["metadata"]),
            }
        ]


class CloudStoreTests(unittest.TestCase):
    def test_zero_config_stays_local_without_requiring_cloud_credentials(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {}, clear=True):
            config = CloudConfig.from_env(Path(temporary))

        store = CloudStore(config)
        self.assertFalse(config.enabled)
        self.assertFalse(config.ready)
        self.assertFalse(store.enabled)
        self.assertEqual(store.disabled_reason, "WRITE_THEN_PUBLISH_CLOUD_SYNC 未开启")

    def test_data_uri_round_trip(self):
        source = "data:image/png;base64,aGVsbG8="
        mime_type, raw = CloudStore._parse_data_uri(source)
        self.assertEqual(mime_type, "image/png")
        self.assertEqual(raw, b"hello")
        self.assertEqual(CloudStore._data_uri(mime_type, raw), source)

    def test_decode_project_keeps_content_images_lazy(self):
        store = CloudStore(test_config())
        store._download_object = lambda asset: self.fail("content image was downloaded eagerly")
        project = store._decode_project(
            {
                "project_id": "project-1",
                "title": "test",
                "updated_at_ms": 1,
                "project_data": {
                    "content": "[[image:image-1]]",
                    "images": {"image-1": {"src": "tos://asset-1"}},
                },
            },
            {
                "asset-1": {
                    "asset_id": "asset-1",
                    "object_key": "private/image.png",
                    "mime_type": "image/png",
                }
            },
        )

        image = project["data"]["images"]["image-1"]
        self.assertEqual(image["src"], "/api/assets/asset-1/content")
        self.assertEqual(image["cloudAssetId"], "asset-1")

    def test_embedded_and_lazy_cloud_asset_sources_compare_equally(self):
        embedded = {
            "data": {
                "images": {
                    "image-1": {
                        "src": "data:image/png;base64,aGVsbG8=",
                        "cloudAssetId": "asset-1",
                    }
                }
            }
        }
        lazy = {
            "data": {
                "images": {
                    "image-1": {
                        "src": "/api/assets/asset-1/content",
                        "cloudAssetId": "asset-1",
                    }
                }
            }
        }

        self.assertEqual(
            CloudStore._project_payload(embedded),
            CloudStore._project_payload(lazy),
        )

    def test_image_without_text_reference_is_still_encoded_for_cloud(self):
        store = RecordingCloudStore()
        project = {
            "id": "project-1",
            "title": "test",
            "updatedAt": 1,
            "data": {
                "content": "正文中已经删掉图片标记",
                "images": {
                    "image-1": {
                        "src": "data:image/png;base64,aGVsbG8=",
                        "name": "image.png",
                    }
                },
            },
        }

        local_project, cloud_project = store._encode_project(
            project,
            known_by_sha={},
            known_by_id={},
            all_by_id={},
        )

        self.assertEqual(len(store.seen_images), 1)
        self.assertTrue(local_project["data"]["images"]["image-1"]["src"].startswith("data:image/png"))
        self.assertEqual(cloud_project["data"]["images"]["image-1"]["src"], "tos://asset-1")
        self.assertEqual(project["data"]["images"]["image-1"].get("cloudAssetId"), None)

    def test_web_source_metadata_is_preserved_for_resource_library_round_trip(self):
        store = RecordingCloudStore()
        source = {
            "kind": "web",
            "provider": "wikimedia",
            "sourcePageUrl": "https://commons.wikimedia.org/wiki/File:Safe.jpg",
            "creator": "Alice",
            "license": "CC BY-SA 4.0",
            "licenseUrl": "https://creativecommons.org/licenses/by-sa/4.0/",
        }
        project = {
            "id": "project-1",
            "updatedAt": 1,
            "data": {
                "content": "[[image:image-1]]",
                "images": {
                    "image-1": {
                        "src": "data:image/png;base64,aGVsbG8=",
                        "name": "image.png",
                        "source": source,
                    }
                },
            },
        }
        store._encode_project(
            project,
            known_by_sha={},
            known_by_id={},
            all_by_id={},
        )
        self.assertEqual(store.seen_metadata[-1]["source"], source)
        public = CloudStore._public_asset(
            {
                "asset_id": "asset-1",
                "metadata": {"kind": "content", "source": source},
            },
            1,
        )
        self.assertEqual(public["source"], source)

    def test_cloud_dedup_backfills_missing_web_source_metadata(self):
        store = CloudStore(ready_test_config())
        store.rest = FakeMetadataRest()
        source = {
            "kind": "web",
            "provider": "wikimedia",
            "sourcePageUrl": "https://commons.wikimedia.org/wiki/File:Safe.jpg",
            "creator": "Alice",
            "license": "CC BY-SA 4.0",
        }
        existing = {
            "asset_id": "asset-1",
            "sha256": "existing-sha",
            "object_key": "existing.png",
            "metadata": {"kind": "content"},
        }
        asset = store._ensure_asset(
            {"cloudAssetId": "asset-1", "source": source},
            original_name="safe.jpg",
            known_by_sha={"existing-sha": existing},
            known_by_id={"asset-1": existing},
            all_by_id={"asset-1": existing},
            metadata={"kind": "content", "source": source},
        )
        self.assertEqual(asset["metadata"]["source"], source)
        self.assertEqual(len(store.rest.calls), 1)
        self.assertEqual(store.rest.calls[0][0], "PATCH")

    def test_reference_count_changes_without_deleting_asset(self):
        store = CloudStore(test_config())
        asset = {"asset_id": "asset-1", "sha256": "unused"}
        project = {
            "id": "project-1",
            "data": {
                "content": "[[image:image-1]]",
                "images": {"image-1": {"cloudAssetId": "asset-1"}},
            },
        }

        self.assertEqual(store._reference_counts({"projects": [project]}, [asset])["asset-1"], 1)
        project["data"]["content"] = "图片标记已经从文字框删除"
        self.assertEqual(store._reference_counts({"projects": [project]}, [asset])["asset-1"], 0)
        self.assertIn("image-1", project["data"]["images"])

    def test_permanent_delete_persists_pending_state_before_tos(self):
        events = []
        store = CloudStore(ready_test_config())
        store.rest = FakeDeletionRest(events)
        store._select_asset = lambda asset_id: {"asset_id": asset_id, "object_key": "asset.png"}
        store._reference_counts = lambda local_store, assets: {"asset-1": 0}
        store._get_tos_client = lambda: FakeTosClient(events)

        store.delete_asset("asset-1", {"projects": []})

        self.assertEqual(events, ["db:pending", "tos:delete", "db:final"])

    def test_failed_tos_delete_keeps_retry_marker(self):
        events = []
        store = CloudStore(ready_test_config())
        store.rest = FakeDeletionRest(events)
        store._select_asset = lambda asset_id: {"asset_id": asset_id, "object_key": "asset.png"}
        store._reference_counts = lambda local_store, assets: {"asset-1": 0}
        store._get_tos_client = lambda: FakeTosClient(events, fail=True)

        with self.assertRaises(CloudStoreError):
            store.delete_asset("asset-1", {"projects": []})

        self.assertEqual(events, ["db:pending", "tos:delete", "db:error"])

    def test_merge_stores_tombstone_prevents_deleted_project_resurrection(self):
        local = {
            "activeId": "project-live",
            "projects": [
                {
                    "id": "project-live",
                    "updatedAt": 300,
                    "data": {"content": "保留"},
                }
            ],
            "deletedProjects": [{"id": "project-deleted", "deletedAt": 200}],
        }
        remote = {
            "activeId": "project-deleted",
            "projects": [
                {
                    "id": "project-deleted",
                    "updatedAt": 100,
                    "data": {"content": "旧云端副本"},
                }
            ],
        }

        merged = CloudStore._merge_stores(local, remote)

        self.assertEqual(
            [project["id"] for project in merged["projects"]],
            ["project-live"],
        )
        self.assertEqual(merged["activeId"], "project-live")
        self.assertEqual(
            merged["deletedProjects"],
            [{"id": "project-deleted", "deletedAt": 200}],
        )

    def test_merge_stores_cloud_tombstone_beats_stale_local_cache(self):
        local = {
            "activeId": "project-deleted",
            "projects": [
                {
                    "id": "project-deleted",
                    "updatedAt": 100,
                    "data": {"content": "浏览器旧缓存"},
                }
            ],
        }
        remote = {
            "activeId": "project-live",
            "projects": [
                {
                    "id": "project-live",
                    "updatedAt": 300,
                    "data": {"content": "云端保留"},
                }
            ],
            "deletedProjects": [{"id": "project-deleted", "deletedAt": 200}],
        }

        merged = CloudStore._merge_stores(local, remote)

        self.assertEqual(
            [project["id"] for project in merged["projects"]],
            ["project-live"],
        )
        self.assertEqual(merged["activeId"], "project-live")
        self.assertEqual(
            merged["deletedProjects"],
            [{"id": "project-deleted", "deletedAt": 200}],
        )

    def test_merge_stores_accepts_linear_edit_from_known_cloud_base(self):
        local = {
            "activeId": "project-1",
            "projects": [
                {
                    "id": "project-1",
                    "title": "本机继续编辑",
                    "updatedAt": 201,
                    "cloudBaseUpdatedAt": 200,
                    "data": {"content": "本机新版"},
                }
            ],
        }
        remote = {
            "activeId": "project-1",
            "projects": [
                {
                    "id": "project-1",
                    "title": "共同基线",
                    "updatedAt": 200,
                    "cloudBaseUpdatedAt": 200,
                    "data": {"content": "共同基线"},
                }
            ],
        }

        merged = CloudStore._merge_stores(local, remote)

        self.assertEqual(merged["projects"][0]["data"]["content"], "本机新版")
        self.assertEqual(merged["conflicts"], [])

    def test_merge_stores_preserves_both_sides_when_cloud_changed_from_base(self):
        local = {
            "activeId": "project-1",
            "projects": [
                {
                    "id": "project-1",
                    "title": "本机稿",
                    "updatedAt": 220,
                    "cloudBaseUpdatedAt": 200,
                    "data": {"content": "本机修改"},
                }
            ],
        }
        remote = {
            "activeId": "project-1",
            "projects": [
                {
                    "id": "project-1",
                    "title": "云端稿",
                    "updatedAt": 210,
                    "cloudBaseUpdatedAt": 210,
                    "data": {"content": "伙伴修改"},
                }
            ],
        }

        merged = CloudStore._merge_stores(local, remote)

        by_id = {project["id"]: project for project in merged["projects"]}
        conflict_id = merged["conflicts"][0]["conflictProjectId"]
        self.assertEqual(by_id["project-1"]["data"]["content"], "伙伴修改")
        self.assertEqual(by_id[conflict_id]["data"]["content"], "本机修改")
        self.assertEqual(by_id[conflict_id]["data"]["__localConflictOf"], "project-1")
        self.assertEqual(by_id[conflict_id]["cloudBaseUpdatedAt"], 0)
        self.assertEqual(merged["activeId"], conflict_id)

    def test_merge_stores_does_not_duplicate_conflict_copies_on_resync(self):
        def diverging(local_content, remote_content, local_ts, remote_ts, extra_local=None):
            local = {
                "activeId": "project-1",
                "projects": [
                    {
                        "id": "project-1",
                        "title": "本机稿",
                        "updatedAt": local_ts,
                        "cloudBaseUpdatedAt": 200,
                        "data": {"content": local_content},
                    }
                ]
                + (extra_local or []),
            }
            remote = {
                "activeId": "project-1",
                "projects": [
                    {
                        "id": "project-1",
                        "title": "云端稿",
                        "updatedAt": remote_ts,
                        "cloudBaseUpdatedAt": remote_ts,
                        "data": {"content": remote_content},
                    }
                ],
            }
            return CloudStore._merge_stores(local, remote)

        merged_first = diverging("本机修改", "伙伴修改", 220, 210)
        copies_first = [p for p in merged_first["projects"] if "_local_conflict_" in p["id"]]
        self.assertEqual(len(copies_first), 1)
        conflict_copy = copies_first[0]

        # A later sync where the same unsynced local content meets an advanced
        # cloud must reuse the existing copy, not mint a second one.
        merged_second = diverging("本机修改", "伙伴又改", 240, 230, extra_local=[conflict_copy])
        copies_second = [p for p in merged_second["projects"] if "_local_conflict_" in p["id"]]
        self.assertEqual(len(copies_second), 1)
        self.assertEqual(copies_second[0]["id"], conflict_copy["id"])
        self.assertEqual(merged_second["conflicts"], [])

    def test_merge_stores_conflict_copy_divergence_stays_rooted(self):
        conflict_copy_id = "project-1_local_conflict_abc123"
        local = {
            "activeId": conflict_copy_id,
            "projects": [
                {
                    "id": conflict_copy_id,
                    "title": "副本",
                    "updatedAt": 320,
                    "cloudBaseUpdatedAt": 300,
                    "data": {"content": "副本又改", "__localConflictOf": "project-1"},
                }
            ],
        }
        remote = {
            "activeId": conflict_copy_id,
            "projects": [
                {
                    "id": conflict_copy_id,
                    "title": "副本云端",
                    "updatedAt": 310,
                    "cloudBaseUpdatedAt": 310,
                    "data": {"content": "副本伙伴改", "__localConflictOf": "project-1"},
                }
            ],
        }

        merged = CloudStore._merge_stores(local, remote)

        new_conflict_id = merged["conflicts"][0]["conflictProjectId"]
        self.assertTrue(new_conflict_id.startswith("project-1_local_conflict_"))
        self.assertNotIn("abc123_local_conflict_", new_conflict_id)
        by_id = {project["id"]: project for project in merged["projects"]}
        self.assertEqual(by_id[new_conflict_id]["data"]["__localConflictOf"], "project-1")

    def test_cloud_base_cursor_is_not_written_into_publishable_cloud_project(self):
        store = RecordingCloudStore()
        _, cloud_project = store._encode_project(
            {
                "id": "project-1",
                "title": "测试",
                "updatedAt": 201,
                "cloudBaseUpdatedAt": 200,
                "data": {"content": "正文", "images": {}},
            },
            known_by_sha={},
            known_by_id={},
            all_by_id={},
        )

        self.assertNotIn("cloudBaseUpdatedAt", cloud_project)


if __name__ == "__main__":
    unittest.main()
