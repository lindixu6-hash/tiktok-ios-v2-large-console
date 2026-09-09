#!/bin/zsh

echo "=========================================="
echo "  TikTok iOS 控制台 - 辅助功能授权工具"
echo "=========================================="
echo ""

echo "📋 第一步：检测当前需要授权的应用"
echo ""

# 检测是哪个应用在运行此脚本
PARENT_APP=$(ps -p $PPID -o comm= 2>/dev/null)
echo "   当前运行环境: $PARENT_APP"
echo ""

# 检测可能需要授权的应用
APPS_TO_AUTHORIZE=()

# 检测 Trae
if [ -d "/Applications/Trae CN.app" ] || [ -d "/Applications/Trae.app" ]; then
    if [ -d "/Applications/Trae CN.app" ]; then
        APPS_TO_AUTHORIZE+=("/Applications/Trae CN.app")
        echo "   ✅ 检测到 Trae CN"
    fi
    if [ -d "/Applications/Trae.app" ]; then
        APPS_TO_AUTHORIZE+=("/Applications/Trae.app")
        echo "   ✅ 检测到 Trae"
    fi
fi

# 检测 Terminal
APPS_TO_AUTHORIZE+=("/System/Applications/Utilities/Terminal.app")
echo "   ✅ 检测到 Terminal"

echo ""
echo "📋 第二步：打开系统设置 → 隐私与安全性 → 辅助功能"
echo ""
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"

echo "⚠️  请在系统设置中操作："
echo ""
echo "   1. 在右侧列表中找到以下应用，将开关打开："
for app in "${APPS_TO_AUTHORIZE[@]}"; do
    echo "      - $(basename "$app" .app)"
done
echo ""
echo "   2. 如果列表中没有这些应用："
echo "      - 点击列表下方的 [+] 按钮"
echo "      - 在弹出窗口中按 Cmd+Shift+G"
for app in "${APPS_TO_AUTHORIZE[@]}"; do
    echo "      - 输入路径: $app"
done
echo "      - 选中后点「打开」添加"
echo ""
echo "   3. 如果开关已经是打开的，但还是报错："
echo "      - 先关闭开关（变灰），再重新打开（变蓝）"
echo "      - 这可以刷新权限缓存"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 等待用户操作
read -s "?完成授权后按 回车键 继续检测..."
echo ""
echo ""

echo "🔍 正在检测权限是否生效..."
echo ""

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 用 AppleScript 测试 System Events 权限
osascript -e 'tell application "System Events" to get name of first process whose frontmost is true' 2>/tmp/accessibility_test_error
if [ $? -eq 0 ]; then
    echo "✅ 辅助功能权限已授予！"
    echo ""
else
    ERROR_MSG=$(cat /tmp/accessibility_test_error 2>/dev/null)
    echo "❌ 辅助功能权限仍然未生效"
    echo "   错误信息: $ERROR_MSG"
    echo ""
    echo "💡 可能的原因："
    echo "   1. 开关没有正确打开（确认是蓝色状态）"
    echo "   2. 需要重启 Terminal 或 Trae 使权限生效"
    echo "   3. 如果在 Trae 中运行失败，尝试在系统 Terminal 中运行此脚本"
    echo ""
    echo "   完成后请重新运行此脚本再次检测。"
    read -s "?按回车键退出..."
    exit 1
fi

echo ""
echo "📋 第三步：检测 iPhone 镜像窗口"
echo ""

cd "$SCRIPT_DIR"
WINDOW_RESULT=$(python3 -c "
import sys
sys.path.insert(0, '.')
from reset_iphone_mirroring import get_window_info
result = get_window_info()
print(result)
")

echo "   窗口检测结果: $WINDOW_RESULT"
echo ""

if echo "$WINDOW_RESULT" | grep -q "^INFO:"; then
    echo "✅ 检测到 iPhone Mirroring 窗口！"
    echo ""
    echo "📋 第四步：是否保存当前窗口位置为主屏位？"
    echo ""
    echo "   当前窗口坐标将被保存到 config.json 的 profiles.main"
    echo ""
    read -q "?是否保存当前窗口位置？(y/n): " CONFIRM
    echo ""
    if [ "$CONFIRM" = "y" ] || [ "$CONFIRM" = "Y" ]; then
        echo ""
        echo "💾 正在保存窗口位置..."
        python3 -c "
import sys
sys.path.insert(0, '.')
from reset_iphone_mirroring import save_current_window_profile
result = save_current_window_profile('main')
print(result)
"
        echo ""
        echo "✅ 窗口坐标已保存！"
        echo ""
        echo "🎉 所有设置完成！你可以："
        echo "   1. 双击「一键准备并启动.command」启动控制台"
        echo "   2. 或在终端运行: python3 web_console.py"
        echo "   3. 控制台地址: http://127.0.0.1:8880/"
    else
        echo ""
        echo "⏭️  跳过保存。你可以稍后在控制台点击「保存当前为主屏位」按钮。"
    fi
elif echo "$WINDOW_RESULT" | grep -q "NOT_FOUND"; then
    echo "⚠️  权限OK，但没有检测到 iPhone Mirroring 窗口。"
    echo ""
    echo "   请："
    echo "   1. 打开 iPhone Mirroring（iPhone 镜像）应用"
    echo "   2. 确保已连接到 iPhone"
    echo "   3. 调整窗口到你想要的位置和大小"
    echo "   4. 重新运行此脚本保存坐标"
else
    echo "❌ 窗口检测失败：$WINDOW_RESULT"
fi

echo ""
read -s "?按回车键退出..."
