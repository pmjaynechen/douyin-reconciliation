#!/bin/zsh
set -euo pipefail

APP_DIR="${0:A:h}"
PREFERRED_PYTHON="${DOUYIN_RECONCILIATION_PYTHON:-}"

if [[ -n "$PREFERRED_PYTHON" && -x "$PREFERRED_PYTHON" ]]; then
  APP_PYTHON="$PREFERRED_PYTHON"
elif command -v python3 >/dev/null 2>&1; then
  APP_PYTHON="$(command -v python3)"
else
  print -u2 "没有找到Python 3，无法备份。"
  exit 1
fi

print "正在检查并备份抖店对账数据……"
"$APP_PYTHON" "$APP_DIR/app.py" --backup
print "备份完成。按回车关闭窗口。"
read -r
