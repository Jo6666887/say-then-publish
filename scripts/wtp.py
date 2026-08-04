#!/usr/bin/env python3
"""Agent-friendly CLI for the local Write Then Publish service."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from pathlib import Path
from typing import Any


DEFAULT_URL = "http://127.0.0.1:5173"
CONFLICT_EXIT = 3
MAX_AGENT_IMAGE_BYTES = 12 * 1024 * 1024


class CliError(RuntimeError):
    def __init__(self, message: str, *, status: int = 1, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


def read_text(path: str | None, inline: str | None) -> str | None:
    if path and inline is not None:
        raise CliError("--from-file 和 --content 只能使用一个")
    if path:
        return Path(path).expanduser().resolve().read_text(encoding="utf-8")
    return inline


def image_mime_type(raw: bytes) -> str:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    raise CliError("仅支持 PNG、JPEG 或 WebP 图片")


def read_image(path: str) -> tuple[Path, str, str]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise CliError(f"找不到图片文件：{source}")
    raw = source.read_bytes()
    if not raw:
        raise CliError("图片文件为空")
    if len(raw) > MAX_AGENT_IMAGE_BYTES:
        raise CliError("单张图片不能超过 12 MB")
    mime_type = image_mime_type(raw)
    data_url = f"data:{mime_type};base64,{base64.b64encode(raw).decode('ascii')}"
    return source, mime_type, data_url


def exact_line_offsets(content: str, target: str) -> list[tuple[int, int]]:
    offsets = []
    cursor = 0
    for line in content.splitlines(keepends=True):
        if line.rstrip("\r\n") == target:
            offsets.append((cursor, cursor + len(line)))
        cursor += len(line)
    return offsets


def insert_image_marker(
    content: str,
    marker: str,
    *,
    after_line: str | None,
    before_line: str | None,
    at_end: bool,
) -> str:
    if at_end:
        separator = "" if not content else ("\n" if content.endswith(("\n", "\r")) else "\n\n")
        return f"{content}{separator}{marker}\n"

    target = after_line if after_line is not None else before_line
    matches = exact_line_offsets(content, target or "")
    if not matches:
        raise CliError(f"正文中找不到完全一致的行：{target}")
    if len(matches) > 1:
        raise CliError(f"正文中有多行完全相同，无法确定插图位置：{target}")
    start, end = matches[0]
    offset = end if after_line is not None else start
    prefix = content[:offset]
    suffix = content[offset:]
    before = "\n" if prefix.endswith(("\n", "\r")) else ("" if not prefix else "\n\n")
    after = "\n" if suffix.startswith(("\n", "\r")) else ("" if not suffix else "\n\n")
    return f"{prefix}{before}{marker}{after}{suffix}"


def omit_project_image_bytes(payload: dict) -> dict:
    project = payload.get("project") if isinstance(payload, dict) else None
    data = project.get("data") if isinstance(project, dict) and isinstance(project.get("data"), dict) else None
    if data is None:
        return payload
    avatar = data.get("avatar")
    if isinstance(avatar, str) and avatar.startswith("data:image/"):
        data["avatar"] = f"embedded-avatar:<{len(avatar)} characters omitted>"
    images = data.get("images")
    if isinstance(images, dict):
        for image in images.values():
            src = image.get("src") if isinstance(image, dict) else None
            if isinstance(src, str) and src.startswith("data:image/"):
                mime_type = src[5:].split(";", 1)[0]
                image["src"] = f"embedded:{mime_type}:<{len(src)} characters omitted>"
    return payload


class Client:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.user = os.getenv("WTP_CLI_USER") or os.getenv("WTP_BASIC_AUTH_USER") or ""
        self.password = os.getenv("WTP_CLI_PASSWORD") or os.getenv("WTP_BASIC_AUTH_PASSWORD") or ""

    def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        headers = {"Accept": "application/json"}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if self.user and self.password:
            token = base64.b64encode(f"{self.user}:{self.password}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(body)
            except json.JSONDecodeError:
                detail = {"error": body or error.reason}
            exit_status = CONFLICT_EXIT if error.code == 409 else 1
            raise CliError(
                detail.get("error") or f"请求失败（HTTP {error.code}）",
                status=exit_status,
                payload=detail,
            ) from error
        except urllib.error.URLError as error:
            raise CliError(
                f"无法连接写了就发本地服务：{error.reason}。请先运行 zsh scripts/start-server.zsh",
            ) from error


def add_content_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--from-file", help="读取 UTF-8 Markdown 文件")
    parser.add_argument("--content", help="直接传入正文")


def add_creator_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--display-name", help="卡片展示的创作者名称")
    parser.add_argument("--handle", help="卡片展示的账号 ID")
    parser.add_argument("--card-theme", help="卡片主题 ID，例如 swiss-blue")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wtp", description="Codex 操作写了就发的稳定本地入口")
    parser.add_argument("--url", default=os.getenv("WTP_URL", DEFAULT_URL), help="本地服务地址")
    parser.add_argument("--compact", action="store_true", help="输出单行 JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="列出项目")

    get_parser = subparsers.add_parser("get", help="读取一个项目")
    get_parser.add_argument("project_id")
    get_parser.add_argument("--include-image-data", action="store_true", help="同时输出体积很大的图片 Data URL")

    create_parser = subparsers.add_parser("create", help="创建项目并进入现有云同步")
    create_parser.add_argument("--title", required=True)
    add_content_arguments(create_parser)
    add_creator_arguments(create_parser)

    update_parser = subparsers.add_parser("update", help="基于读取到的版本安全更新项目")
    update_parser.add_argument("project_id")
    update_parser.add_argument("--title")
    add_content_arguments(update_parser)
    add_creator_arguments(update_parser)
    publish_group = update_parser.add_mutually_exclusive_group()
    publish_group.add_argument("--published", action="store_true")
    publish_group.add_argument("--unpublished", action="store_true")

    image_parser = subparsers.add_parser(
        "add-image",
        help="把 Agent 生成的本地图片安全插入项目并进入云同步",
    )
    image_parser.add_argument("project_id")
    image_parser.add_argument("--file", required=True, help="PNG、JPEG 或 WebP 绝对路径")
    image_parser.add_argument("--name", help="图片在资源库中的名称")
    position_group = image_parser.add_mutually_exclusive_group(required=True)
    position_group.add_argument("--after-line", help="插入到这行正文之后；必须完全匹配且唯一")
    position_group.add_argument("--before-line", help="插入到这行正文之前；必须完全匹配且唯一")
    position_group.add_argument("--at-end", action="store_true", help="插入到正文末尾")
    image_parser.add_argument("--width-percent", type=int, default=100, choices=range(25, 101))
    image_parser.add_argument("--align", choices=("left", "center", "right"), default="center")

    subparsers.add_parser("status", help="查看本地和云端保存状态")

    subparsers.add_parser("sync", help="立即同步当前项目并等待确认")

    open_parser = subparsers.add_parser("open", help="在浏览器打开写了就发")
    open_parser.add_argument("project_id", nargs="?")
    return parser


def run(args: argparse.Namespace) -> dict:
    client = Client(args.url)
    if args.command == "list":
        return client.request("GET", "/api/projects")
    if args.command == "get":
        project_id = urllib.parse.quote(args.project_id, safe="")
        result = client.request("GET", f"/api/projects/{project_id}")
        return result if args.include_image_data else omit_project_image_bytes(result)
    if args.command == "create":
        content = read_text(args.from_file, args.content)
        payload = {"title": args.title, "content": content or ""}
        for field, value in (
            ("displayName", args.display_name),
            ("handle", args.handle),
            ("cardTheme", args.card_theme),
        ):
            if value is not None:
                payload[field] = value
        return client.request(
            "POST",
            "/api/projects",
            payload,
        )
    if args.command == "update":
        project_id = urllib.parse.quote(args.project_id, safe="")
        current = client.request("GET", f"/api/projects/{project_id}")["project"]
        payload: dict[str, Any] = {"expectedUpdatedAt": current["updatedAt"]}
        content = read_text(args.from_file, args.content)
        if content is not None:
            payload["content"] = content
        if args.title is not None:
            payload["title"] = args.title
        if args.display_name is not None:
            payload["displayName"] = args.display_name
        if args.handle is not None:
            payload["handle"] = args.handle
        if args.card_theme is not None:
            payload["cardTheme"] = args.card_theme
        if args.published:
            payload["published"] = True
        elif args.unpublished:
            payload["published"] = False
        if len(payload) == 1:
            raise CliError("没有需要更新的字段")
        return client.request("PATCH", f"/api/projects/{project_id}", payload)
    if args.command == "add-image":
        project_id = urllib.parse.quote(args.project_id, safe="")
        current = client.request("GET", f"/api/projects/{project_id}")["project"]
        data = current.get("data") if isinstance(current.get("data"), dict) else {}
        content = data.get("content") if isinstance(data.get("content"), str) else ""
        source, _mime_type, data_url = read_image(args.file)
        image_id = f"img_agent_{uuid.uuid4().hex[:12]}"
        marker = f"[[image:{image_id}]]"
        next_content = insert_image_marker(
            content,
            marker,
            after_line=args.after_line,
            before_line=args.before_line,
            at_end=args.at_end,
        )
        image = {
            "src": data_url,
            "name": (args.name or source.name)[:160],
            "sourcePath": "Codex Agent 生成",
            "crop": None,
            "layout": {
                "widthPercent": args.width_percent,
                "align": args.align,
            },
        }
        result = client.request(
            "PATCH",
            f"/api/projects/{project_id}",
            {
                "expectedUpdatedAt": current["updatedAt"],
                "content": next_content,
                "addImage": {"id": image_id, "image": image},
            },
        )
        result["image"] = {
            "id": image_id,
            "marker": marker,
            "name": image["name"],
        }
        return omit_project_image_bytes(result)
    if args.command == "status":
        return {
            "health": client.request("GET", "/api/health"),
            "cloud": client.request("GET", "/api/cloud-status"),
        }
    if args.command == "sync":
        return client.request("POST", "/api/cloud-sync", {})
    if args.command == "open":
        url = args.url
        if args.project_id:
            url = f"{url.rstrip('/')}?project={urllib.parse.quote(args.project_id, safe='')}"
        opened = webbrowser.open(url)
        return {"ok": bool(opened), "url": url}
    raise CliError("未知命令")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = run(args)
        print(json.dumps(result, ensure_ascii=False, indent=None if args.compact else 2))
        return 0
    except (CliError, OSError) as error:
        payload = error.payload if isinstance(error, CliError) and error.payload is not None else {
            "ok": False,
            "error": str(error),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=None if args.compact else 2))
        return error.status if isinstance(error, CliError) else 1


if __name__ == "__main__":
    raise SystemExit(main())
