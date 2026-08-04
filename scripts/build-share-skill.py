#!/usr/bin/env python3
"""Build a deterministic, privacy-scrubbed, self-contained Skill archive."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_SOURCE = ROOT / "skill-package" / "say-then-publish"
ARCHIVE_ROOT = "say-then-publish"
DEFAULT_OUTPUT = ROOT / "outputs"

SKILL_FILES = (
    "SKILL.md",
    "agents/openai.yaml",
    "references/layout-language.md",
    "scripts/bootstrap.py",
    "scripts/creator_memory.py",
)

APP_FILES = (
    ".env.example",
    "LICENSE",
    "NOTICE.md",
    "index.html",
    "server.py",
    "cloud_store.py",
    "local_asset_store.py",
    "ai_layout.py",
    "web_image_search.py",
    "requirements.txt",
    "src/app.js",
    "src/styles.css",
    "src/user-profile.js",
    "scripts/start-server.zsh",
    "scripts/wtp.py",
    "sql/20260722_write_then_publish_cloud.sql",
    "sql/20260722_write_then_publish_cloud_hardening.sql",
    "启动说了就发.command",
)

FORBIDDEN_PATH_PARTS = {
    ".env",
    ".git",
    ".venv",
    "__pycache__",
    "backups",
    "runtime-data",
    "node_modules",
}

PRIVATE_PATTERNS = {
    "absolute macOS user path": re.compile(r"/Users/[^/\s]+/"),
    "current maintainer account": re.compile(r"junwenzheng|Jo6666887|Jo8888s|科技米线", re.IGNORECASE),
    "Supabase service token": re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"),
    "private key block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "populated secret assignment": re.compile(
        r"(?m)^(?:SUPABASE_SECRET_KEY|TOS_ACCESS_KEY|TOS_SECRET_KEY|WTP_AI_API_KEY|WTP_AI_APP_ID)[ \t]*=[ \t]*\S+"
    ),
}


class BuildError(RuntimeError):
    pass


def copy_file(source: Path, target: Path) -> None:
    if not source.is_file() or source.is_symlink():
        raise BuildError(f"缺少或拒绝打包文件：{source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def build_stage(stage: Path) -> Path:
    skill_target = stage / ARCHIVE_ROOT
    for relative in SKILL_FILES:
        copy_file(SKILL_SOURCE / relative, skill_target / relative)
    app_target = skill_target / "assets" / "app"
    for relative in APP_FILES:
        copy_file(ROOT / relative, app_target / relative)
    return skill_target


def validate_stage(skill_root: Path) -> list[Path]:
    files = sorted(path for path in skill_root.rglob("*") if path.is_file())
    if not files:
        raise BuildError("分享包为空。")

    for path in files:
        relative = path.relative_to(skill_root)
        if path.is_symlink() or FORBIDDEN_PATH_PARTS.intersection(relative.parts):
            raise BuildError(f"分享包包含禁止路径：{relative}")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in PRIVATE_PATTERNS.items():
            if pattern.search(text):
                raise BuildError(f"隐私扫描命中 {label}：{relative}")

    html = (skill_root / "assets" / "app" / "index.html").read_text(encoding="utf-8")
    for removed_control in ("aiOptimizeBtn", "aiOptimizeModal", "aiSettingsPanel", "AI Key", "AI 优化排版"):
        if removed_control in html:
            raise BuildError(f"已删除的外接 AI 控件重新出现：{removed_control}")

    profile = (skill_root / "assets" / "app" / "src" / "user-profile.js").read_text(encoding="utf-8")
    if "你的小红书账号" not in profile:
        raise BuildError("分享包的默认用户资料不是匿名模板。")
    return files


def write_archive(skill_root: Path, archive: Path, files: list[Path]) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive.with_suffix(archive.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for path in files:
                relative = Path(ARCHIVE_ROOT) / path.relative_to(skill_root)
                info = zipfile.ZipInfo(relative.as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
                executable = bool(path.stat().st_mode & stat.S_IXUSR)
                mode = 0o755 if executable else 0o644
                info.external_attr = (stat.S_IFREG | mode) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                bundle.writestr(info, path.read_bytes())
        os.replace(temporary, archive)
    finally:
        temporary.unlink(missing_ok=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="构建不含个人信息的说了就发 Skill 分享包")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output_dir = args.output_dir.expanduser().resolve()
    archive = output_dir / "say-then-publish-skill.zip"

    with tempfile.TemporaryDirectory(prefix="say-then-publish-share-") as temporary:
        skill_root = build_stage(Path(temporary))
        files = validate_stage(skill_root)
        write_archive(skill_root, archive, files)

    print(f"archive={archive}")
    print(f"files={len(files)}")
    print(f"bytes={archive.stat().st_size}")
    print(f"sha256={sha256(archive)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
