#!/bin/zsh
set -euo pipefail

PROJECT_DIR="${0:A:h:h}"
DEPLOY_HOST="${WTP_DEPLOY_HOST:-}"
APP_ROOT="/opt/write-then-publish"
COMMIT_SHA="$(git -C "$PROJECT_DIR" rev-parse HEAD)"
SHORT_SHA="${COMMIT_SHA[1,12]}"
TEMP_DIR="$(mktemp -d)"
ARCHIVE_NAME="write-then-publish-${COMMIT_SHA}.tar.gz"
ARCHIVE_PATH="$TEMP_DIR/$ARCHIVE_NAME"

cleanup() {
  case "$TEMP_DIR" in
    /tmp/*|/private/tmp/*|/private/var/folders/*|/var/folders/*)
      [[ -d "$TEMP_DIR" ]] && rm -rf -- "$TEMP_DIR"
      ;;
  esac
}
trap cleanup EXIT

if [[ -z "$DEPLOY_HOST" ]]; then
  echo "必须显式设置 WTP_DEPLOY_HOST，例如 root@服务器IP。" >&2
  exit 1
fi
if [[ "$DEPLOY_HOST" != (#b)([A-Za-z0-9._-]##)@([A-Za-z0-9.-]##) ]]; then
  echo "WTP_DEPLOY_HOST 格式无效，应为 用户名@主机名或IP。" >&2
  exit 1
fi
if [[ -n "$(git -C "$PROJECT_DIR" status --porcelain)" ]]; then
  echo "工作区不是干净状态；请先测试并提交，再部署精确提交。" >&2
  exit 1
fi

git -C "$PROJECT_DIR" archive --format=tar.gz --output="$ARCHIVE_PATH" "$COMMIT_SHA"
if tar -tzf "$ARCHIVE_PATH" \
    | grep -Eq '(^|/)(\\.env|\\.git|\\.venv|runtime-data|backups)(/|$)'; then
  echo "部署包意外包含密钥、运行数据或本地环境。" >&2
  exit 1
fi
ARCHIVE_SHA256="$(shasum -a 256 "$ARCHIVE_PATH" | awk '{print $1}')"

echo "准备发布提交：$SHORT_SHA"
echo "目标服务器：$DEPLOY_HOST"
echo "部署包不会包含 .env、运行数据、备份、.git 或本机虚拟环境。"

ssh "$DEPLOY_HOST" "install -d -m 0700 '$APP_ROOT/incoming'"
scp "$ARCHIVE_PATH" "$PROJECT_DIR/deploy/activate-release.sh" \
  "$DEPLOY_HOST:$APP_ROOT/incoming/"
ssh "$DEPLOY_HOST" \
  "bash '$APP_ROOT/incoming/activate-release.sh' '$COMMIT_SHA' '$ARCHIVE_SHA256' '$APP_ROOT/incoming/$ARCHIVE_NAME'"
