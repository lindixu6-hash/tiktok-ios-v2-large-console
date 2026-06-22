#!/bin/zsh

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

echo "开始检查 / 引导飞书授权..."
echo ""
python3 setup_lark_auth.py

echo ""
echo "按任意键关闭窗口"
read -k 1
