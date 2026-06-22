#!/bin/zsh

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "没找到 python3。"
  echo "macOS 会打开 Xcode Command Line Tools 安装器。"
  echo "安装完成后，请重新双击本脚本。"
  xcode-select --install 2>/dev/null
  echo ""
  echo "按任意键关闭窗口"
  read -k 1
  exit 1
fi

python3 setup_and_launch.py

echo ""
echo "窗口可保留；关闭窗口会停止 Web 控制台。"
echo "按任意键关闭窗口"
read -k 1
