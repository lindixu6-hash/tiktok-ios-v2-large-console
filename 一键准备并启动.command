#!/bin/zsh

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

python3 setup_and_launch.py

echo ""
echo "窗口可保留；关闭窗口会停止 Web 控制台。"
echo "按任意键关闭窗口"
read -k 1
