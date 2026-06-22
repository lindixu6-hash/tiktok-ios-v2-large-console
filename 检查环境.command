#!/bin/zsh

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

echo "开始检查 iOS V2 运行环境..."
echo ""
python3 check_environment.py

echo ""
echo "按任意键关闭窗口"
read -k 1
