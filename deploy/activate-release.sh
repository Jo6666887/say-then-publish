#!/usr/bin/env bash
set -Eeuo pipefail

COMMIT_SHA="${1:-}"
EXPECTED_SHA256="${2:-}"
ARCHIVE_PATH="${3:-}"
APP_ROOT="/opt/write-then-publish"
RELEASES_DIR="$APP_ROOT/releases"
CURRENT_LINK="$APP_ROOT/current"
NEXT_LINK="$APP_ROOT/current.next"
LOCK_FILE="$APP_ROOT/deploy.lock"
STATE_DIR="/var/lib/write-then-publish"
BACKUP_DIR="$STATE_DIR/backups"
SERVER_ENV="/etc/write-then-publish/server.env"
APP_ENV="/etc/write-then-publish/app.env"
UNIT_PATH="/etc/systemd/system/write-then-publish.service"
SERVICE_NAME="write-then-publish.service"
SERVICE_USER="write-then-publish"
BUILD_USER="write-then-publish-build"
MINIMUM_FREE_KB=$((2 * 1024 * 1024))

if [[ "$(id -u)" -ne 0 ]]; then
  echo "必须由 root 激活服务器版本。" >&2
  exit 1
fi
if [[ ! "$COMMIT_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "提交号必须是完整的 40 位小写 SHA。" >&2
  exit 1
fi
if [[ ! "$EXPECTED_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
  echo "部署包 SHA256 格式无效。" >&2
  exit 1
fi
if [[ "$ARCHIVE_PATH" != "$APP_ROOT/incoming/"* || ! -f "$ARCHIVE_PATH" ]]; then
  echo "部署包必须位于独立 incoming 目录。" >&2
  exit 1
fi
for required_path in "$UNIT_PATH" "$SERVER_ENV" "$APP_ENV"; do
  if [[ ! -f "$required_path" ]]; then
    echo "缺少首次安装文件：$required_path" >&2
    exit 1
  fi
done
for required_user in "$SERVICE_USER" "$BUILD_USER"; do
  if ! getent passwd "$required_user" >/dev/null; then
    echo "缺少隔离系统用户：$required_user" >&2
    exit 1
  fi
done

PUBLIC_PORT="$(awk -F= '$1 == "WTP_PORT" { value=$2 } END { print value }' "$SERVER_ENV")"
BASIC_USER="$(awk -F= '$1 == "WTP_BASIC_AUTH_USER" { value=substr($0, index($0, "=") + 1) } END { print value }' "$SERVER_ENV")"
BASIC_PASSWORD="$(awk -F= '$1 == "WTP_BASIC_AUTH_PASSWORD" { value=substr($0, index($0, "=") + 1) } END { print value }' "$SERVER_ENV")"
TLS_CERT_FILE="$(awk -F= '$1 == "WTP_TLS_CERT_FILE" { value=substr($0, index($0, "=") + 1) } END { print value }' "$SERVER_ENV")"
ALLOW_INSECURE_HTTP="$(awk -F= '$1 == "WTP_ALLOW_INSECURE_HTTP" { value=$2 } END { print value }' "$SERVER_ENV")"
if [[ ! "$PUBLIC_PORT" =~ ^[0-9]+$ ]] || (( PUBLIC_PORT < 1024 || PUBLIC_PORT > 65535 )); then
  echo "服务器端口配置无效。" >&2
  exit 1
fi
if [[ -z "$BASIC_USER" || -z "$BASIC_PASSWORD" ]]; then
  echo "服务器访问凭据配置不完整。" >&2
  exit 1
fi
if [[ -n "$TLS_CERT_FILE" ]]; then
  URL_SCHEME="https"
  CURL_TRANSPORT_ARGS=(--insecure)
elif [[ "$ALLOW_INSECURE_HTTP" == "1" ]]; then
  URL_SCHEME="http"
  CURL_TRANSPORT_ARGS=()
else
  echo "服务器既未启用 TLS，也未明确允许纯 HTTP，已停止发布。" >&2
  exit 1
fi
HEALTH_URL="${URL_SCHEME}://127.0.0.1:${PUBLIC_PORT}/api/health"
BASE_URL="${URL_SCHEME}://127.0.0.1:${PUBLIC_PORT}"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "已有另一个发布任务正在执行。" >&2
  exit 1
fi

AVAILABLE_KB="$(df -Pk "$APP_ROOT" | awk 'NR == 2 { print $4 }')"
if [[ ! "$AVAILABLE_KB" =~ ^[0-9]+$ ]] || (( AVAILABLE_KB < MINIMUM_FREE_KB )); then
  echo "可用磁盘空间不足 2 GiB，已停止发布。" >&2
  exit 1
fi

ACTUAL_SHA256="$(sha256sum "$ARCHIVE_PATH" | awk '{print $1}')"
if [[ "$ACTUAL_SHA256" != "$EXPECTED_SHA256" ]]; then
  echo "部署包完整性校验失败。" >&2
  exit 1
fi
while IFS= read -r archive_entry; do
  case "$archive_entry" in
    /*|../*|*/../*|*/..)
      echo "部署包包含不安全路径：$archive_entry" >&2
      exit 1
      ;;
  esac
done < <(tar -tzf "$ARCHIVE_PATH")
if tar -tvzf "$ARCHIVE_PATH" \
    | awk 'substr($1, 1, 1) == "l" || substr($1, 1, 1) == "h" { found=1 } END { exit found ? 0 : 1 }'; then
  echo "部署包不能包含符号链接或硬链接。" >&2
  exit 1
fi

install -d -m 0700 -o "$SERVICE_USER" -g "$SERVICE_USER" "$BACKUP_DIR"
BACKUP_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PREVIOUS_SHA="$(basename "$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)")"
[[ "$PREVIOUS_SHA" =~ ^[0-9a-f]{40}$ ]] || PREVIOUS_SHA="initial"
STATE_SNAPSHOT="$BACKUP_DIR/pre-release-${BACKUP_STAMP}-${PREVIOUS_SHA}"
install -d -m 0700 -o "$SERVICE_USER" -g "$SERVICE_USER" "$STATE_SNAPSHOT"
if [[ -d "$STATE_DIR/runtime-data" ]]; then
  cp -a --reflink=auto "$STATE_DIR/runtime-data" "$STATE_SNAPSHOT/"
fi
if [[ -d "$STATE_DIR/assets" ]]; then
  if ! cp -al "$STATE_DIR/assets" "$STATE_SNAPSHOT/"; then
    cp -a --reflink=auto "$STATE_DIR/assets" "$STATE_SNAPSHOT/"
  fi
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$STATE_SNAPSHOT"
find "$STATE_SNAPSHOT" -type d -exec chmod 0700 {} +
find "$STATE_SNAPSHOT" -type f -exec chmod 0600 {} +

PRE_DEPLOY_PROJECT_COUNT=0
if [[ -f "$STATE_DIR/runtime-data/project-store.json" ]]; then
  PRE_DEPLOY_PROJECT_COUNT="$(
    python3 -c \
      'import json,sys; value=json.load(open(sys.argv[1], encoding="utf-8")); print(len(value.get("projects", [])))' \
      "$STATE_DIR/runtime-data/project-store.json"
  )"
fi
if [[ ! "$PRE_DEPLOY_PROJECT_COUNT" =~ ^[0-9]+$ ]]; then
  echo "部署前草稿库无法校验，已停止发布。" >&2
  exit 1
fi

RELEASE_DIR="$RELEASES_DIR/$COMMIT_SHA"
CREATED_RELEASE=0
cleanup_incomplete_release() {
  if [[ "$CREATED_RELEASE" -eq 1 && -d "$RELEASE_DIR" ]]; then
    case "$RELEASE_DIR" in
      "$RELEASES_DIR"/[0-9a-f][0-9a-f][0-9a-f][0-9a-f]*)
        rm -rf -- "$RELEASE_DIR"
        ;;
    esac
  fi
}
trap cleanup_incomplete_release EXIT

if [[ -d "$RELEASE_DIR" ]]; then
  if [[ ! -x "$RELEASE_DIR/.venv/bin/python" ]] \
      || [[ "$(cat "$RELEASE_DIR/.release-sha256" 2>/dev/null || true)" != "$EXPECTED_SHA256" ]]; then
    echo "同名 release 已存在但未通过完整性检查，拒绝覆盖。" >&2
    exit 1
  fi
else
  install -d -m 0750 -o "$BUILD_USER" -g "$BUILD_USER" "$RELEASE_DIR"
  CREATED_RELEASE=1
  tar -xzf "$ARCHIVE_PATH" -C "$RELEASE_DIR"
  if find "$RELEASE_DIR" -maxdepth 2 \
      \( -name .env -o -name .git -o -name .venv -o -name runtime-data -o -name backups \) \
      -print -quit | grep -q .; then
    echo "部署包包含不应发布的本地文件。" >&2
    exit 1
  fi
  chown -R "$BUILD_USER:$BUILD_USER" "$RELEASE_DIR"
  runuser -u "$BUILD_USER" -- \
    env HOME="$RELEASE_DIR/.build-home" PIP_DISABLE_PIP_VERSION_CHECK=1 \
    python3 -m venv "$RELEASE_DIR/.venv"
  runuser -u "$BUILD_USER" -- \
    env HOME="$RELEASE_DIR/.build-home" PIP_DISABLE_PIP_VERSION_CHECK=1 \
    "$RELEASE_DIR/.venv/bin/python" -m pip install \
      --no-cache-dir \
      --requirement "$RELEASE_DIR/requirements.txt"
  runuser -u "$BUILD_USER" -- \
    "$RELEASE_DIR/.venv/bin/python" -m py_compile \
      "$RELEASE_DIR/server.py" \
      "$RELEASE_DIR/cloud_store.py" \
      "$RELEASE_DIR/local_asset_store.py" \
      "$RELEASE_DIR/ai_layout.py" \
      "$RELEASE_DIR/web_image_search.py"
  runuser -u "$BUILD_USER" -- \
    "$RELEASE_DIR/.venv/bin/python" -m pip freeze --all \
    >"$RELEASE_DIR/.resolved-requirements.txt"
  printf '%s\n' "$EXPECTED_SHA256" >"$RELEASE_DIR/.release-sha256"
  rm -rf -- "$RELEASE_DIR/.build-home"
  chown -R root:"$SERVICE_USER" "$RELEASE_DIR"
  find "$RELEASE_DIR" -type d -exec chmod 0755 {} +
  find "$RELEASE_DIR" -type f -exec chmod u=rw,go=r {} +
  find "$RELEASE_DIR/.venv/bin" -type f -exec chmod 0755 {} +
  CREATED_RELEASE=0
fi

VERIFY_UNIT="$(mktemp /run/write-then-publish-verify.XXXXXX.service)"
cleanup_verify_unit() {
  [[ -f "$VERIFY_UNIT" ]] && rm -f -- "$VERIFY_UNIT"
}
trap 'cleanup_verify_unit; cleanup_incomplete_release' EXIT
sed "s|/opt/write-then-publish/current|$RELEASE_DIR|g" "$UNIT_PATH" >"$VERIFY_UNIT"
if ! systemd-analyze verify "$VERIFY_UNIT"; then
  echo "候选 systemd 服务配置校验失败，current 尚未切换。" >&2
  exit 1
fi
cleanup_verify_unit

application_is_ready() {
  local health_body cloud_body project_body current_python cloud_required
  health_body="$(curl --fail --silent --show-error "${CURL_TRANSPORT_ARGS[@]}" --max-time 3 "$HEALTH_URL")" \
    || return 1
  [[ "$health_body" == '{"ok":true,"service":"write-then-publish","schema":1}' ]] \
    || return 1
  curl --fail --silent --show-error "${CURL_TRANSPORT_ARGS[@]}" --max-time 5 \
    --user "$BASIC_USER:$BASIC_PASSWORD" \
    --output /dev/null \
    "$BASE_URL/" \
    || return 1
  project_body="$(
    curl --fail --silent --show-error "${CURL_TRANSPORT_ARGS[@]}" --max-time 15 \
      --user "$BASIC_USER:$BASIC_PASSWORD" \
      "$BASE_URL/api/project-store"
  )" || return 1
  current_python="$CURRENT_LINK/.venv/bin/python"
  printf '%s' "$project_body" | "$current_python" -c \
    'import json,sys
data=json.load(sys.stdin)
projects=data.get("projects")
minimum=int(sys.argv[1])
raise SystemExit(0 if isinstance(projects,list) and len(projects)>=minimum else 1)' \
    "$PRE_DEPLOY_PROJECT_COUNT" \
    || return 1
  cloud_required="$(
    awk -F= '$1 == "WRITE_THEN_PUBLISH_CLOUD_SYNC" { value=$2 } END { print value }' "$APP_ENV"
  )"
  cloud_body="$(
    curl --fail --silent --show-error "${CURL_TRANSPORT_ARGS[@]}" --max-time 10 \
      --user "$BASIC_USER:$BASIC_PASSWORD" \
      "$BASE_URL/api/cloud-status"
  )" || return 1
  if [[ "$cloud_required" == "1" ]]; then
    printf '%s' "$cloud_body" | "$current_python" -c \
      'import json,sys
data=json.load(sys.stdin)
ok=(data.get("enabled") is True and data.get("fallbackToLocal") is False
    and data.get("syncing") is False and data.get("lastError") is None)
raise SystemExit(0 if ok else 1)' \
      || return 1
  fi
  runuser -u "$SERVICE_USER" -- test -r "$STATE_DIR/runtime-data/project-store.json" \
    || return 1
  runuser -u "$SERVICE_USER" -- test -w "$STATE_DIR/runtime-data" \
    || return 1
  return 0
}

wait_for_application() {
  for _ in {1..120}; do
    if application_is_ready; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

PREVIOUS_RELEASE="$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)"
if [[ -L "$NEXT_LINK" ]]; then
  unlink "$NEXT_LINK"
elif [[ -e "$NEXT_LINK" ]]; then
  echo "$NEXT_LINK 已存在且不是软链接，拒绝覆盖。" >&2
  exit 1
fi
ln -s "$RELEASE_DIR" "$NEXT_LINK"
mv -Tf -- "$NEXT_LINK" "$CURRENT_LINK"

rollback_current() {
  if [[ -z "$PREVIOUS_RELEASE" || ! -d "$PREVIOUS_RELEASE" ]]; then
    systemctl stop "$SERVICE_NAME" || true
    return 1
  fi
  [[ -L "$NEXT_LINK" ]] && unlink "$NEXT_LINK"
  ln -s "$PREVIOUS_RELEASE" "$NEXT_LINK"
  mv -Tf -- "$NEXT_LINK" "$CURRENT_LINK"
  systemctl restart "$SERVICE_NAME" || return 1
  wait_for_application
}

deployment_failed() {
  local reason="$1"
  if rollback_current; then
    echo "$reason；已验证恢复上一版本。" >&2
  else
    echo "$reason；自动回滚也未通过健康检查，需要人工处理独立服务。" >&2
  fi
  exit 1
}

systemctl restart "$SERVICE_NAME" || deployment_failed "新版本启动失败"
wait_for_application || deployment_failed "新版本完整健康检查失败"

unlink "$ARCHIVE_PATH"

CURRENT_RELEASE="$(readlink -f "$CURRENT_LINK")"
kept_unprotected=0
while IFS= read -r candidate_release; do
  candidate_name="$(basename "$candidate_release")"
  [[ "$candidate_name" =~ ^[0-9a-f]{40}$ ]] || continue
  if [[ "$candidate_release" == "$CURRENT_RELEASE" || "$candidate_release" == "$PREVIOUS_RELEASE" ]]; then
    continue
  fi
  kept_unprotected=$((kept_unprotected + 1))
  if (( kept_unprotected > 2 )); then
    rm -rf -- "$candidate_release"
  fi
done < <(
  find "$RELEASES_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' \
    | sort -rn \
    | cut -d' ' -f2-
)

echo "已激活版本：$COMMIT_SHA"
echo "当前目录：$CURRENT_RELEASE"
echo "部署前状态备份：$STATE_SNAPSHOT"
systemctl is-active "$SERVICE_NAME"
