import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import wtp


class FakeClient:
    def __init__(self):
        self.calls = []

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if method == "GET" and path == "/api/projects/project-1":
            return {
                "project": {
                    "id": "project-1",
                    "updatedAt": 200,
                    "data": {"content": "旧正文", "published": False},
                }
            }
        return {
            "ok": True,
            "project": {
                "id": "project-1",
                "updatedAt": 201,
                "data": payload or {},
            },
            "localSaved": True,
            "cloudSynced": True,
        }


class WtpCliTests(unittest.TestCase):
    def test_get_omits_large_embedded_image_data_by_default(self):
        client = FakeClient()
        client.request = mock.Mock(return_value={
            "project": {
                "id": "project-1",
                "data": {
                    "content": "正文",
                    "images": {"img": {"src": "data:image/png;base64,dGVzdA=="}},
                },
            }
        })
        args = wtp.build_parser().parse_args(["get", "project-1"])
        with mock.patch.object(wtp, "Client", return_value=client):
            result = wtp.run(args)

        self.assertEqual(
            result["project"]["data"]["images"]["img"]["src"],
            "embedded:image/png:<30 characters omitted>",
        )

    def test_update_reads_latest_revision_before_conditional_patch(self):
        client = FakeClient()
        args = wtp.build_parser().parse_args(
            ["update", "project-1", "--content", "新正文", "--published"]
        )
        with mock.patch.object(wtp, "Client", return_value=client):
            result = wtp.run(args)

        self.assertTrue(result["cloudSynced"])
        self.assertEqual(client.calls[0], ("GET", "/api/projects/project-1", None))
        self.assertEqual(
            client.calls[1],
            (
                "PATCH",
                "/api/projects/project-1",
                {
                    "expectedUpdatedAt": 200,
                    "content": "新正文",
                    "published": True,
                },
            ),
        )

    def test_create_reads_utf8_markdown_file(self):
        client = FakeClient()
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "draft.md"
            source.write_text("# 标题\n\n正文", encoding="utf-8")
            args = wtp.build_parser().parse_args(
                ["create", "--title", "新项目", "--from-file", str(source)]
            )
            with mock.patch.object(wtp, "Client", return_value=client):
                wtp.run(args)

        self.assertEqual(
            client.calls,
            [("POST", "/api/projects", {"title": "新项目", "content": "# 标题\n\n正文"})],
        )

    def test_update_without_changes_is_rejected(self):
        client = FakeClient()
        args = wtp.build_parser().parse_args(["update", "project-1"])
        with mock.patch.object(wtp, "Client", return_value=client):
            with self.assertRaisesRegex(wtp.CliError, "没有需要更新"):
                wtp.run(args)

    def test_add_image_uses_exact_line_and_conditional_project_patch(self):
        client = FakeClient()
        client.request = mock.Mock(side_effect=[
            {
                "project": {
                    "id": "project-1",
                    "updatedAt": 200,
                    "data": {
                        "content": "# 标题\n\n## 第一节\n\n正文",
                        "images": {},
                    },
                }
            },
            {
                "ok": True,
                "project": {"id": "project-1", "updatedAt": 201},
                "localSaved": True,
                "cloudSynced": True,
            },
        ])
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "agent.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"test-image")
            args = wtp.build_parser().parse_args([
                "add-image",
                "project-1",
                "--file",
                str(image),
                "--after-line",
                "## 第一节",
                "--width-percent",
                "80",
            ])
            with mock.patch.object(wtp, "Client", return_value=client):
                result = wtp.run(args)

        self.assertTrue(result["cloudSynced"])
        get_call, patch_call = client.request.call_args_list
        self.assertEqual(get_call.args, ("GET", "/api/projects/project-1"))
        self.assertEqual(patch_call.args[:2], ("PATCH", "/api/projects/project-1"))
        payload = patch_call.args[2]
        self.assertEqual(payload["expectedUpdatedAt"], 200)
        marker = result["image"]["marker"]
        self.assertIn(f"## 第一节\n\n{marker}\n\n正文", payload["content"])
        self.assertEqual(payload["addImage"]["id"], result["image"]["id"])
        image_payload = payload["addImage"]["image"]
        self.assertTrue(image_payload["src"].startswith("data:image/png;base64,"))
        self.assertEqual(image_payload["layout"]["widthPercent"], 80)

    def test_add_image_rejects_ambiguous_anchor_before_patch(self):
        client = FakeClient()
        client.request = mock.Mock(return_value={
            "project": {
                "id": "project-1",
                "updatedAt": 200,
                "data": {"content": "重复\n重复", "images": {}},
            }
        })
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "agent.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"test-image")
            args = wtp.build_parser().parse_args([
                "add-image", "project-1", "--file", str(image), "--after-line", "重复",
            ])
            with mock.patch.object(wtp, "Client", return_value=client):
                with self.assertRaisesRegex(wtp.CliError, "多行完全相同"):
                    wtp.run(args)

        self.assertEqual(client.request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
