#!/usr/bin/env python3
"""Private, local creator preferences shared by the app's Agent skills."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = 1
PLATFORM = "小红书"
ALLOWED_CATEGORIES = ("identity", "layout", "writing", "visual", "workflow", "device")
SECRET_KEY_PATTERN = re.compile(
    r"password|passwd|secret|token|api[ _-]?key|cookie|credential|密码|密钥|令牌|验证码",
    re.IGNORECASE,
)
SECRET_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b"),
)


class MemoryError(RuntimeError):
    pass


def memory_home() -> Path:
    configured = os.environ.get("SAY_THEN_PUBLISH_HOME", "").strip()
    return Path(configured).expanduser().resolve() if configured else (Path.home() / ".say-then-publish").resolve()


def memory_file() -> Path:
    return memory_home() / "creator-memory.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def empty_memory() -> dict[str, Any]:
    return {"schema": SCHEMA, "platform": PLATFORM, "entries": [], "updatedAt": utc_now()}


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def load_memory(*, create: bool = True) -> dict[str, Any]:
    path = memory_file()
    if not path.is_file():
        payload = empty_memory()
        if create:
            atomic_write(path, payload)
        return payload
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MemoryError("个人创作记忆无法读取，请检查本地文件。") from error
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA or not isinstance(payload.get("entries"), list):
        raise MemoryError("个人创作记忆格式不兼容。")
    return payload


def validate_entry(category: str, key: str, value: str) -> tuple[str, str, str]:
    category = category.strip().lower()
    key = " ".join(key.split())
    value = value.strip()
    if category not in ALLOWED_CATEGORIES:
        raise MemoryError(f"不支持的记忆分类：{category}")
    if not key or len(key) > 80 or not value or len(value) > 1000:
        raise MemoryError("记忆名称或内容长度不正确。")
    if SECRET_KEY_PATTERN.search(key):
        raise MemoryError("创作记忆拒绝保存密码、Token、Cookie 或 API Key。")
    if any(pattern.search(value) for pattern in SECRET_VALUE_PATTERNS):
        raise MemoryError("检测到疑似凭据；创作记忆拒绝保存。")
    return category, key, value


def remember(category: str, key: str, value: str, *, source: str = "user-explicit") -> dict[str, Any]:
    category, key, value = validate_entry(category, key, value)
    payload = load_memory()
    entries = [
        entry
        for entry in payload["entries"]
        if not (
            isinstance(entry, dict)
            and entry.get("category") == category
            and str(entry.get("key", "")).casefold() == key.casefold()
        )
    ]
    entry = {"category": category, "key": key, "value": value, "source": source, "updatedAt": utc_now()}
    entries.append(entry)
    payload.update({"entries": entries, "updatedAt": entry["updatedAt"]})
    atomic_write(memory_file(), payload)
    return entry


def initialize_identity(account_name: str) -> dict[str, Any]:
    cleaned = " ".join(account_name.split())
    if not cleaned:
        raise MemoryError("小红书账号名称不能为空。")
    return remember("identity", "小红书账号名称", cleaned, source="onboarding")


def forget(category: str, key: str) -> bool:
    category = category.strip().lower()
    key = " ".join(key.split())
    payload = load_memory()
    before = len(payload["entries"])
    payload["entries"] = [
        entry
        for entry in payload["entries"]
        if not (
            isinstance(entry, dict)
            and entry.get("category") == category
            and str(entry.get("key", "")).casefold() == key.casefold()
        )
    ]
    removed = len(payload["entries"]) != before
    if removed:
        payload["updatedAt"] = utc_now()
        atomic_write(memory_file(), payload)
    return removed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="管理说了就发的本地个人创作记忆")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("show", help="读取全部创作偏好")
    init_parser = subparsers.add_parser("init", help="初始化小红书身份")
    init_parser.add_argument("--account-name", required=True)
    remember_parser = subparsers.add_parser("remember", help="记住一条明确偏好")
    remember_parser.add_argument("--category", choices=ALLOWED_CATEGORIES, required=True)
    remember_parser.add_argument("--key", required=True)
    remember_parser.add_argument("--value", required=True)
    forget_parser = subparsers.add_parser("forget", help="忘记一条偏好")
    forget_parser.add_argument("--category", choices=ALLOWED_CATEGORIES, required=True)
    forget_parser.add_argument("--key", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "show":
            result: Any = load_memory()
        elif args.command == "init":
            result = {"ok": True, "remembered": initialize_identity(args.account_name)}
        elif args.command == "remember":
            result = {"ok": True, "remembered": remember(args.category, args.key, args.value)}
        elif args.command == "forget":
            result = {"ok": True, "forgotten": forget(args.category, args.key)}
        else:
            raise MemoryError("未知命令。")
    except (MemoryError, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
