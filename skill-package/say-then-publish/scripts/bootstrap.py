#!/usr/bin/env python3
"""Install and operate the application embedded in the shareable Skill."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

from creator_memory import MemoryError as CreatorMemoryError
from creator_memory import initialize_identity, load_memory


SKILL_ROOT = Path(__file__).resolve().parents[1]
BUNDLED_APP = SKILL_ROOT / "assets" / "app"
PLATFORM = "小红书"
DEFAULT_PORT = 5173
CONFIG_SCHEMA = 1


class BootstrapError(RuntimeError):
    pass


def config_home() -> Path:
    configured = os.environ.get("SAY_THEN_PUBLISH_HOME", "").strip()
    return Path(configured).expanduser().resolve() if configured else (Path.home() / ".say-then-publish").resolve()


def config_file() -> Path:
    return config_home() / "install.json"


def read_config() -> dict[str, Any]:
    path = config_file()
    if not path.is_file():
        raise BootstrapError("尚未初始化。请先提供小红书账号名称和常用内容文件夹。")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BootstrapError("本地初始化配置无法读取，请重新运行 init。") from error
    if not isinstance(payload, dict) or payload.get("schema") != CONFIG_SCHEMA:
        raise BootstrapError("本地初始化配置版本不兼容，请重新运行 init。")
    app_dir = Path(str(payload.get("appDir", ""))).expanduser()
    if not app_dir.is_dir():
        raise BootstrapError("已配置的应用目录不存在，请重新运行 init。")
    return payload


def is_application_directory(path: Path) -> bool:
    """Return whether path is an unpacked Say Then Publish application."""
    return all(
        marker.is_file()
        for marker in (
            path / "server.py",
            path / "index.html",
            path / "requirements.txt",
            path / "scripts" / "wtp.py",
            path / "src" / "app.js",
        )
    )


def find_current_application() -> Path | None:
    """Find an existing application at or above the Agent's working directory."""
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if is_application_directory(candidate):
            return candidate
        if candidate == Path.home().resolve():
            break
    return None


def remembered_account_name() -> str | None:
    """Reuse a public display name without exposing the rest of creator memory."""
    try:
        entries = load_memory(create=False).get("entries", [])
    except (CreatorMemoryError, OSError, ValueError):
        return None
    preferred_keys = ("小红书账号名称", "小红书名称")
    for preferred_key in preferred_keys:
        for entry in reversed(entries):
            if not isinstance(entry, dict) or entry.get("category") != "identity":
                continue
            if str(entry.get("key", "")).strip() != preferred_key:
                continue
            value = " ".join(str(entry.get("value", "")).split())
            if value and not value.startswith(("http://", "https://")):
                return value
    return None


def remembered_creator_defaults() -> dict[str, str]:
    """Return non-secret card defaults that may be injected into a new project."""
    try:
        entries = load_memory(create=False).get("entries", [])
    except (CreatorMemoryError, OSError, ValueError):
        return {}
    latest: dict[tuple[str, str], str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        category = str(entry.get("category", "")).strip()
        key = str(entry.get("key", "")).strip()
        value = str(entry.get("value", "")).strip()
        if value:
            latest[(category, key)] = value
    defaults: dict[str, str] = {}
    display_name = latest.get(("identity", "小红书账号名称")) or latest.get(("identity", "小红书名称"))
    handle = latest.get(("device", "小红书账号 ID")) or latest.get(("device", "当前设备的小红书账号"))
    theme = latest.get(("layout", "默认卡片主题"))
    if display_name:
        defaults["--display-name"] = display_name
    if handle:
        defaults["--handle"] = handle if handle.startswith("@") else f"@{handle}"
    if theme:
        match = re.search(r"\(([a-z0-9-]+)\)\s*$", theme, re.IGNORECASE)
        defaults["--card-theme"] = match.group(1) if match else theme
    return defaults


def write_config(config: dict[str, Any]) -> None:
    atomic_write(config_file(), json.dumps(config, ensure_ascii=False, indent=2) + "\n")


def recover_config_from_current_directory() -> dict[str, Any] | None:
    """Adopt an existing local checkout instead of onboarding the user again."""
    app_dir = find_current_application()
    if app_dir is None:
        return None
    config = {
        "schema": CONFIG_SCHEMA,
        "platform": PLATFORM,
        "accountName": remembered_account_name() or "小红书创作者",
        "contentDir": str(app_dir),
        "appDir": str(app_dir),
        "port": DEFAULT_PORT,
        "installationMode": "existing-app",
        "recoveredFrom": "current-directory",
    }
    write_config(config)
    return config


def resolve_config(*, recover: bool = True) -> tuple[dict[str, Any], bool]:
    try:
        return read_config(), False
    except BootstrapError as error:
        if recover:
            recovered = recover_config_from_current_directory()
            if recovered is not None:
                return recovered, True
        raise error


def atomic_write(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
    finally:
        if temporary.exists():
            temporary.unlink()


def prompt_value(label: str, value: str | None, default: str | None = None) -> str:
    if value and value.strip():
        return value.strip()
    if not sys.stdin.isatty():
        raise BootstrapError(f"缺少{label}；请由 Agent 询问用户后通过参数传入。")
    suffix = f" [{default}]" if default else ""
    answer = input(f"{label}{suffix}: ").strip()
    return answer or (default or "")


def validate_account_name(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise BootstrapError("小红书账号名称不能为空。")
    if len(cleaned) > 80 or any(ord(character) < 32 for character in cleaned):
        raise BootstrapError("小红书账号名称格式不正确。")
    return cleaned


def resolve_content_dir(value: str) -> Path:
    target = Path(value).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    if not target.is_dir():
        raise BootstrapError("常用内容文件夹不可用。")
    return target


def copy_bundled_app(target: Path) -> None:
    if not BUNDLED_APP.is_dir() or not (BUNDLED_APP / "server.py").is_file():
        raise BootstrapError("Skill 包不完整：缺少内置应用代码。")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(BUNDLED_APP, target, dirs_exist_ok=True)
    for protected in (".env", "runtime-data", "backups", ".venv"):
        if (BUNDLED_APP / protected).exists():
            raise BootstrapError(f"Skill 包包含不应分发的个人数据：{protected}")


def write_profile(app_dir: Path, account_name: str) -> None:
    payload = {
        "platform": PLATFORM,
        "displayName": account_name,
        "handle": PLATFORM,
    }
    script = f"window.SAY_THEN_PUBLISH_PROFILE = Object.freeze({json.dumps(payload, ensure_ascii=False)});\n"
    atomic_write(app_dir / "src" / "user-profile.js", script)


def venv_python(app_dir: Path) -> Path:
    return app_dir / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python3")


def ensure_dependencies(app_dir: Path) -> Path:
    python = venv_python(app_dir)
    if not python.is_file():
        subprocess.run([sys.executable, "-m", "venv", str(app_dir / ".venv")], check=True)
    probe = subprocess.run(
        [str(python), "-c", "import PIL, requests, tos"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if probe.returncode != 0:
        try:
            subprocess.run(
                [str(python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(app_dir / "requirements.txt")],
                check=True,
            )
        except subprocess.CalledProcessError as error:
            raise BootstrapError("Python 依赖安装失败。请确认网络可访问 Python 包源后重试。") from error
    return python


def base_url(config: dict[str, Any]) -> str:
    return f"http://127.0.0.1:{int(config.get('port', DEFAULT_PORT))}"


def health(url: str, timeout: float = 1.5) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None
    return payload if payload.get("ok") is True and payload.get("service") == "write-then-publish" else None


def start_application(config: dict[str, Any], *, open_browser: bool) -> dict[str, Any]:
    url = base_url(config)
    if health(url):
        if open_browser:
            webbrowser.open(url)
        return {"ok": True, "alreadyRunning": True, "url": url, "appDir": config["appDir"]}

    app_dir = Path(config["appDir"])
    python = ensure_dependencies(app_dir)
    log_path = config_home() / "server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update({"WTP_OPEN_BROWSER": "0", "WTP_PORT": str(config.get("port", DEFAULT_PORT))})
    with log_path.open("ab") as log_handle:
        options: dict[str, Any] = {
            "cwd": str(app_dir),
            "env": environment,
            "stdin": subprocess.DEVNULL,
            "stdout": log_handle,
            "stderr": subprocess.STDOUT,
        }
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        else:
            options["start_new_session"] = True
        process = subprocess.Popen([str(python), str(app_dir / "server.py")], **options)
    atomic_write(config_home() / "server.pid", f"{process.pid}\n")

    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise BootstrapError(f"本地服务启动失败，请查看 {log_path}")
        if health(url):
            if open_browser:
                webbrowser.open(url)
            return {"ok": True, "alreadyRunning": False, "url": url, "appDir": str(app_dir)}
        time.sleep(0.25)
    raise BootstrapError(f"等待本地服务启动超时，请查看 {log_path}")


def initialize(args: argparse.Namespace) -> dict[str, Any]:
    if not 1 <= int(args.port) <= 65535:
        raise BootstrapError("端口必须在 1 到 65535 之间。")
    account_name = validate_account_name(prompt_value("小红书账号名称", args.account_name or remembered_account_name()))
    initialize_identity(account_name)
    default_content = str(Path.home() / "Documents" / "小红书内容")
    content_input = prompt_value("常用内容文件夹", args.content_dir, default_content)
    content_dir = resolve_content_dir(content_input)
    app_dir = content_dir / ".say-then-publish" / "app"
    copy_bundled_app(app_dir)
    write_profile(app_dir, account_name)
    config = {
        "schema": CONFIG_SCHEMA,
        "platform": PLATFORM,
        "accountName": account_name,
        "contentDir": str(content_dir),
        "appDir": str(app_dir),
        "port": int(args.port),
    }
    write_config(config)
    result: dict[str, Any] = {
        "ok": True,
        "initialized": True,
        "platform": PLATFORM,
        "accountName": account_name,
        "contentDir": str(content_dir),
        "appDir": str(app_dir),
    }
    if not args.no_start:
        result["service"] = start_application(config, open_browser=not args.no_open)
    return result


def stop_application() -> dict[str, Any]:
    pid_path = config_home() / "server.pid"
    if not pid_path.is_file():
        return {"ok": True, "stopped": False, "reason": "没有记录运行中的服务"}
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
        os.kill(pid, signal.SIGTERM)
    except (OSError, ValueError):
        pid_path.unlink(missing_ok=True)
        return {"ok": True, "stopped": False, "reason": "服务已经停止"}
    pid_path.unlink(missing_ok=True)
    return {"ok": True, "stopped": True, "pid": pid}


def run_cli(config: dict[str, Any], arguments: list[str]) -> int:
    if not arguments:
        raise BootstrapError("cli 后需要提供 list、get、create、update 等命令。")
    if not health(base_url(config)):
        start_application(config, open_browser=False)
    operation = arguments[0]
    effective_arguments = list(arguments)
    if operation == "create":
        for flag, value in remembered_creator_defaults().items():
            if flag not in effective_arguments:
                effective_arguments.extend((flag, value))
    app_dir = Path(config["appDir"])
    python = ensure_dependencies(app_dir)
    command = [str(python), str(app_dir / "scripts" / "wtp.py"), "--url", base_url(config), *effective_arguments]
    completed = subprocess.run(command, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.stdout:
        sys.stdout.write(completed.stdout)
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    if completed.returncode == 0 and operation in {"create", "update", "add-image"}:
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            payload = {}
        project = payload.get("project") if isinstance(payload, dict) else None
        project_id = project.get("id") if isinstance(project, dict) else None
        if not project_id and operation in {"update", "add-image"} and len(arguments) > 1:
            project_id = arguments[1]
        if isinstance(project_id, str) and project_id:
            url = f"{base_url(config).rstrip('/')}?project={urllib.parse.quote(project_id, safe='')}"
            webbrowser.open(url)
    return completed.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="初始化和启动说了就发自包含 Skill")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="初始化小红书账号和常用内容文件夹")
    init_parser.add_argument("--account-name")
    init_parser.add_argument("--content-dir")
    init_parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    init_parser.add_argument("--no-start", action="store_true")
    init_parser.add_argument("--no-open", action="store_true")

    start_parser = subparsers.add_parser("start", help="启动本地工作台")
    start_parser.add_argument("--no-open", action="store_true")
    subparsers.add_parser("status", help="读取安装与服务状态")
    subparsers.add_parser("stop", help="停止由本 Skill 启动的服务")
    cli_parser = subparsers.add_parser("cli", help="调用内置 Agent CLI")
    cli_parser.add_argument("arguments", nargs=argparse.REMAINDER)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "init":
            result = initialize(args)
        elif args.command == "start":
            config, recovered = resolve_config()
            result = start_application(config, open_browser=not args.no_open)
            result["recoveredExistingApp"] = recovered
        elif args.command == "status":
            config, recovered = resolve_config()
            result = {
                "ok": True,
                "installed": True,
                "recoveredExistingApp": recovered,
                "serviceHealthy": bool(health(base_url(config))),
                **config,
                "url": base_url(config),
            }
        elif args.command == "stop":
            result = stop_application()
        elif args.command == "cli":
            return run_cli(read_config(), args.arguments)
        else:
            raise BootstrapError("未知命令。")
    except (BootstrapError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
