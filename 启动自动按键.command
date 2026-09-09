#!/bin/zsh

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

echo "⌨️  启动自动按键控制台..."
echo "浏览器地址：http://127.0.0.1:8866/"
echo ""

python3 auto_key_web.py

echo ""
echo "控制台已退出。按任意键关闭窗口"
read -k 1
