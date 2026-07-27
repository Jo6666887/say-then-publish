#!/usr/bin/env bash
set -Eeuo pipefail

PUBLIC_HOST="${1:-}"
PUBLIC_PORT="${2:-8517}"
TRANSPORT="${3:-https}"
APP_ROOT="/opt/write-then-publish"
CONFIG_DIR="/etc/write-then-publish"
STATE_DIR="/var/lib/write-then-publish"
SERVICE_USER="write-then-publish"
BUILD_USER="write-then-publish-build"
UNIT_PATH="/etc/systemd/system/write-then-publish.service"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "必须由 root 执行首次安装。" >&2
  exit 1
fi
if [[ ! "$PUBLIC_HOST" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "公网 IP 或主机名格式无效。" >&2
  exit 1
fi
if [[ ! "$PUBLIC_PORT" =~ ^[0-9]+$ ]] || (( PUBLIC_PORT < 1024 || PUBLIC_PORT > 65535 )); then
  echo "端口必须是 1024-65535 之间的整数。" >&2
  exit 1
fi
if [[ "$TRANSPORT" != "http" && "$TRANSPORT" != "https" ]]; then
  echo "传输模式必须是 http 或 https。" >&2
  exit 1
fi
if ss -ltnH "sport = :${PUBLIC_PORT}" | grep -q .; then
  echo "端口 ${PUBLIC_PORT} 已被占用，未执行安装。" >&2
  exit 1
fi
if [[ ! -f "$CONFIG_DIR/app.env" ]]; then
  echo "缺少 $CONFIG_DIR/app.env；请先安全上传服务端密钥。" >&2
  exit 1
fi
if [[ ! -f "$SCRIPT_DIR/write-then-publish.service" ]]; then
  echo "首次安装脚本旁缺少 systemd unit 模板。" >&2
  exit 1
fi
for command_name in python3 openssl systemctl ss runuser; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "缺少系统命令：$command_name" >&2
    exit 1
  fi
done

known_install_files=(
  "$CONFIG_DIR/server.env"
  "$CONFIG_DIR/tls.key"
  "$CONFIG_DIR/tls.crt"
  "$CONFIG_DIR/access-credentials.txt"
  "$UNIT_PATH"
)
required_install_files=(
  "$CONFIG_DIR/server.env"
  "$CONFIG_DIR/access-credentials.txt"
  "$UNIT_PATH"
)
if [[ "$TRANSPORT" == "https" ]]; then
  required_install_files+=("$CONFIG_DIR/tls.key" "$CONFIG_DIR/tls.crt")
fi
existing_count=0
for existing_file in "${known_install_files[@]}"; do
  [[ -e "$existing_file" ]] && existing_count=$((existing_count + 1))
done
required_count=0
for required_install_file in "${required_install_files[@]}"; do
  [[ -e "$required_install_file" ]] && required_count=$((required_count + 1))
done
if (( required_count == ${#required_install_files[@]} )); then
  echo "首次安装配置已经完整存在，未覆盖任何凭据。"
  exit 0
fi
if (( existing_count != 0 )); then
  echo "检测到不完整的首次安装文件；为避免误覆盖，已停止。" >&2
  exit 1
fi

VENV_CHECK_DIR="$(mktemp -d /tmp/write-then-publish-venv-check.XXXXXX)"
cleanup_venv_check() {
  case "$VENV_CHECK_DIR" in
    /tmp/write-then-publish-venv-check.*)
      [[ -d "$VENV_CHECK_DIR" ]] && rm -rf -- "$VENV_CHECK_DIR"
      ;;
  esac
}
trap cleanup_venv_check EXIT
python3 -m venv "$VENV_CHECK_DIR/venv"
"$VENV_CHECK_DIR/venv/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 10) else 1)'
cleanup_venv_check

if ! getent passwd "$SERVICE_USER" >/dev/null; then
  useradd \
    --system \
    --home-dir "$STATE_DIR" \
    --shell /usr/sbin/nologin \
    --user-group \
    "$SERVICE_USER"
fi
if ! getent passwd "$BUILD_USER" >/dev/null; then
  useradd \
    --system \
    --home-dir /nonexistent \
    --shell /usr/sbin/nologin \
    --user-group \
    "$BUILD_USER"
fi

install -d -m 0755 -o root -g root "$APP_ROOT" "$APP_ROOT/releases"
install -d -m 0700 -o root -g root "$APP_ROOT/incoming"
install -d -m 0750 -o root -g "$SERVICE_USER" "$CONFIG_DIR"
install -d -m 0700 -o "$SERVICE_USER" -g "$SERVICE_USER" \
  "$STATE_DIR" "$STATE_DIR/runtime-data" "$STATE_DIR/assets" "$STATE_DIR/backups"
chown root:root "$CONFIG_DIR/app.env"
chmod 0600 "$CONFIG_DIR/app.env"

STAGING_DIR="$(mktemp -d "$CONFIG_DIR/.bootstrap.XXXXXX")"
BOOTSTRAP_COMPLETE=0
installed_files=()
cleanup_bootstrap() {
  if [[ -d "$STAGING_DIR" ]]; then
    case "$STAGING_DIR" in
      "$CONFIG_DIR"/.bootstrap.*)
        rm -rf -- "$STAGING_DIR"
        ;;
    esac
  fi
  if [[ "$BOOTSTRAP_COMPLETE" -ne 1 ]]; then
    for installed_file in "${installed_files[@]}"; do
      rm -f -- "$installed_file"
    done
    systemctl disable write-then-publish.service >/dev/null 2>&1 || true
    systemctl daemon-reload || true
  fi
}
trap cleanup_bootstrap EXIT

ACCESS_USER="junwen"
ACCESS_PASSWORD="$(openssl rand -hex 18)"
SERVER_ENV_CONTENT="WRITE_THEN_PUBLISH_DATA_DIR=$STATE_DIR/runtime-data
WRITE_THEN_PUBLISH_ASSET_DIR=$STATE_DIR/assets
WTP_BIND_HOST=0.0.0.0
WTP_PORT=$PUBLIC_PORT
WTP_ALLOWED_HOSTS=$PUBLIC_HOST,127.0.0.1,localhost,::1
WTP_OPEN_BROWSER=0
WTP_BASIC_AUTH_USER=$ACCESS_USER
WTP_BASIC_AUTH_PASSWORD=$ACCESS_PASSWORD"
if [[ "$TRANSPORT" == "https" ]]; then
  if python3 -c 'import ipaddress, sys; ipaddress.ip_address(sys.argv[1])' "$PUBLIC_HOST" \
      >/dev/null 2>&1; then
    TLS_SUBJECT_ALT_NAME="IP:${PUBLIC_HOST}"
  else
    TLS_SUBJECT_ALT_NAME="DNS:${PUBLIC_HOST}"
  fi
  openssl req \
    -x509 \
    -nodes \
    -newkey rsa:3072 \
    -sha256 \
    -days 825 \
    -keyout "$STAGING_DIR/tls.key" \
    -out "$STAGING_DIR/tls.crt" \
    -subj "/CN=${PUBLIC_HOST}" \
    -addext "subjectAltName=${TLS_SUBJECT_ALT_NAME}" \
    >/dev/null 2>&1
  openssl x509 -in "$STAGING_DIR/tls.crt" -noout -checkend 86400 >/dev/null
  SERVER_ENV_CONTENT="${SERVER_ENV_CONTENT}
WTP_TLS_CERT_FILE=$CONFIG_DIR/tls.crt
WTP_TLS_KEY_FILE=$CONFIG_DIR/tls.key"
  ACCESS_NOTICE="说明=这是自签 HTTPS；首次访问确认浏览器证书提醒后，再输入以上独立访问凭据。"
else
  SERVER_ENV_CONTENT="${SERVER_ENV_CONTENT}
WTP_ALLOW_INSECURE_HTTP=1"
  ACCESS_NOTICE="说明=按部署要求使用纯 HTTP；独立密码仍会校验，但网络传输内容不加密。"
fi
printf '%s\n' "$SERVER_ENV_CONTENT" >"$STAGING_DIR/server.env"
cat >"$STAGING_DIR/access-credentials.txt" <<EOF
URL=${TRANSPORT}://${PUBLIC_HOST}:${PUBLIC_PORT}/
用户名=$ACCESS_USER
密码=$ACCESS_PASSWORD
$ACCESS_NOTICE
EOF

if [[ "$TRANSPORT" == "https" ]]; then
  install -m 0640 -o root -g "$SERVICE_USER" "$STAGING_DIR/tls.key" "$CONFIG_DIR/tls.key"
  installed_files+=("$CONFIG_DIR/tls.key")
  install -m 0644 -o root -g root "$STAGING_DIR/tls.crt" "$CONFIG_DIR/tls.crt"
  installed_files+=("$CONFIG_DIR/tls.crt")
fi
install -m 0600 -o root -g root "$STAGING_DIR/server.env" "$CONFIG_DIR/server.env"
installed_files+=("$CONFIG_DIR/server.env")
install -m 0600 -o root -g root \
  "$STAGING_DIR/access-credentials.txt" \
  "$CONFIG_DIR/access-credentials.txt"
installed_files+=("$CONFIG_DIR/access-credentials.txt")
install -m 0644 -o root -g root "$SCRIPT_DIR/write-then-publish.service" "$UNIT_PATH"
installed_files+=("$UNIT_PATH")

systemctl daemon-reload
systemctl enable write-then-publish.service >/dev/null
BOOTSTRAP_COMPLETE=1

echo "首次安装骨架完成；尚未启动服务。"
echo "访问模式：$TRANSPORT"
echo "独立访问凭据保存在：$CONFIG_DIR/access-credentials.txt"
echo "下一步上传并激活一个经过校验的 release。"
