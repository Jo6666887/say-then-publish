import copy
import unittest

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

    def _ensure_asset(self, image, **kwargs):
        self.seen_images.append(copy.deepcopy(image))
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


class CloudStoreTests(unittest.TestCase):
    def test_data_uri_round_trip(self):
        source = "data:image/png;base64,aGVsbG8="
        mime_type, raw = CloudStore._parse_data_uri(source)
        self.assertEqual(mime_type, "image/png")
        self.assertEqual(raw, b"hello")
        self.assertEqual(CloudStore._data_uri(mime_type, raw), source)

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


if __name__ == "__main__":
    unittest.main()
