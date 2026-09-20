#!/bin/zsh
set -euo pipefail

APP_DIR="${0:A:h}"
PREFERRED_PYTHON="${DOUYIN_RECONCILIATION_PYTHON:-}"

if [[ -n "$PREFERRED_PYTHON" && -x "$PREFERRED_PYTHON" ]]; then
  APP_PYTHON="$PREFERRED_PYTHON"
elif command -v python3 >/dev/null 2>&1; then
  APP_PYTHON="$(command -v python3)"
else
  print -u2 "没有找到Python 3，无法恢复。"
  exit 1
fi

if command -v osascript >/dev/null 2>&1; then
  if ! BACKUP_ARCHIVE="$(osascript -e 'POSIX path of (choose file with prompt "选择抖店对账备份ZIP")' 2>/dev/null)"; then
    print "没有选择备份文件，已取消。"
    exit 0
  fi
else
  read -r "BACKUP_ARCHIVE?请输入备份ZIP完整路径："
fi

if [[ -z "$BACKUP_ARCHIVE" ]]; then
  print "没有选择备份文件，已取消。"
  exit 0
fi

print "将恢复备份：$BACKUP_ARCHIVE"
print "当前数据会先移动到recovery-before-restore目录，不会直接删除。"
read -r "CONFIRM_TEXT?请输入“恢复”并按回车继续："
if [[ "$CONFIRM_TEXT" != "恢复" ]]; then
  print "输入不一致，已取消恢复。"
  exit 0
fi

"$APP_PYTHON" "$APP_DIR/app.py" --restore "$BACKUP_ARCHIVE"
print "恢复完成。请重新启动抖店对账。按回车关闭窗口。"
read -r
