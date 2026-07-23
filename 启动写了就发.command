#!/bin/zsh
set -e

SCRIPT_DIR="${0:A:h}"
PORT=5173
URL="http://127.0.0.1:${PORT}/"

cd "$SCRIPT_DIR"
mkdir -p runtime-data

is_write_then_publish_healthy() {
  [[ "$(/usr/bin/curl -fsS --max-time 2 "${URL}api/health" 2>/dev/null)" == '{"ok":true,"service":"write-then-publish","schema":1}' ]]
}

if ! is_write_then_publish_healthy; then
  STALE_PID=$(/usr/sbin/lsof -tiTCP:${PORT} -sTCP:LISTEN | head -n 1)
  if [[ -n "$STALE_PID" ]]; then
    STALE_CWD=$(/usr/sbin/lsof -a -p "$STALE_PID" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')
    if [[ "$STALE_CWD" == "$SCRIPT_DIR" ]]; then
      kill "$STALE_PID"
      for _ in {1..20}; do
        /usr/sbin/lsof -nP -iTCP:${PORT} -sTCP:LISTEN >/dev/null 2>&1 || break
        sleep 0.1
      done
    else
      echo "端口 ${PORT} 被其他程序占用，无法安全重启。"
      read -k 1 "?按任意键退出……"
      exit 1
    fi
  fi

  nohup /bin/zsh scripts/start-server.zsh > runtime-data/write-then-publish.log 2>&1 &

  for _ in {1..30}; do
    if is_write_then_publish_healthy; then
      break
    fi
    sleep 0.2
  done
fi

if ! is_write_then_publish_healthy; then
  echo "写了就发启动失败，请查看：$SCRIPT_DIR/runtime-data/write-then-publish.log"
  read -k 1 "?按任意键退出……"
  exit 1
fi

open "$URL"
