#!/bin/zsh
set -euo pipefail

APP_DIR="${0:A:h}"
PREFERRED_PYTHON="${DOUYIN_RECONCILIATION_PYTHON:-}"
APP_URL="http://127.0.0.1:8766"

if [[ -n "$PREFERRED_PYTHON" && -x "$PREFERRED_PYTHON" ]]; then
  APP_PYTHON="$PREFERRED_PYTHON"
elif command -v python3 >/dev/null 2>&1; then
  APP_PYTHON="$(command -v python3)"
else
  print -u2 "没有找到Python 3，无法启动。"
  exit 1
fi

mkdir -p "$APP_DIR/var/uploads"

if curl -fsS --max-time 1 "$APP_URL/api/health" >/dev/null 2>&1; then
  print "抖店对账已在运行：$APP_URL"
  print "直接刷新浏览器即可继续使用。"
  exit 0
fi

if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:8766 -sTCP:LISTEN >/dev/null 2>&1; then
  print -u2 "8766端口已被其他程序占用，对账服务未启动。"
  exit 1
fi

print "抖店对账将在本机启动：$APP_URL"
print "数据目录：$APP_DIR/var"
exec "$APP_PYTHON" -u "$APP_DIR/app.py" --host 127.0.0.1 --port 8766
