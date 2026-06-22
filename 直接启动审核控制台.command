#!/bin/zsh

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

PORT="$(python3 -c 'import json; print(json.load(open("config.json")).get("console", {}).get("port", 8877))' 2>/dev/null || echo 8877)"
URL="http://127.0.0.1:${PORT}/"

if curl --max-time 1 -fsS "$URL/api/status" >/dev/null 2>&1; then
  echo "审核控制台已经在运行，直接打开浏览器..."
  open "$URL"
  echo ""
  echo "可以关闭这个窗口。"
  read -k 1
  exit 0
fi

echo "启动 iOS 审核控制台..."
echo "浏览器地址：$URL"
echo ""
echo "保持这个窗口打开；关闭窗口会停止控制台。"
echo ""

python3 web_console.py

echo ""
echo "控制台已退出。按任意键关闭窗口"
read -k 1
