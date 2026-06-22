#!/bin/zsh

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

echo "启动 iOS V2 Web 控制台..."
PORT="$(python3 -c 'import json; print(json.load(open("config.json")).get("console", {}).get("port", 8877))' 2>/dev/null || echo 8877)"
echo "浏览器地址：http://127.0.0.1:${PORT}/"
echo ""

python3 web_console.py

echo ""
echo "控制台已退出。按任意键关闭窗口"
read -k 1
