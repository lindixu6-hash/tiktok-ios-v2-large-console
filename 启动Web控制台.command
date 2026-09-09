#!/bin/zsh

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

echo "启动 iOS V2 Web 控制台..."
PORT="$(python3 -c 'import json; print(json.load(open("config.json")).get("console", {}).get("port", 8877))' 2>/dev/null || echo 8877)"
echo "浏览器地址：http://127.0.0.1:${PORT}/"
echo ""

# 启动自动按键工具（后台）
if lsof -ti:8866 > /dev/null 2>&1; then
  echo "自动按键已在运行 (http://127.0.0.1:8866/)"
else
  echo "启动自动按键工具 (http://127.0.0.1:8866/)..."
  nohup python3 auto_key_web.py > /tmp/autokey.log 2>&1 &
fi
echo ""

python3 web_console.py

echo ""
echo "控制台已退出。按任意键关闭窗口"
read -k 1
