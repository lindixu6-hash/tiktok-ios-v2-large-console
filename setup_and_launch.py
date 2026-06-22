from __future__ import annotations

import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
import json
from pathlib import Path

import setup_lark_auth


ROOT = Path(__file__).resolve().parent


def console_url() -> str:
    try:
        config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        port = int(config.get("console", {}).get("port", 8877))
    except Exception:
        port = 8877
    return f"http://127.0.0.1:{port}/"


def run(command: list[str], timeout: int | None = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, text=True, timeout=timeout)


def ask_yes(message: str, default_yes: bool = True) -> bool:
    suffix = "Y/n" if default_yes else "y/N"
    answer = input(f"{message} [{suffix}] ").strip().lower()
    if not answer:
        return default_yes
    return answer in {"y", "yes"}


def check_server_running() -> bool:
    try:
        with urllib.request.urlopen(console_url() + "api/status", timeout=1.5) as response:
            return response.status == 200
    except Exception:
        return False


def ensure_lark_cli() -> bool:
    if setup_lark_auth.find_lark_cli():
        print("[OK] lark-cli 已安装")
        return True

    print("[需要处理] 没找到 lark-cli。")
    npm = shutil.which("npm")
    if not npm:
        print("这台电脑也没找到 npm，无法自动安装 lark-cli。")
        print("先安装 Node.js，或让管理员执行：npm install -g @larksuite/cli")
        return False

    if not ask_yes("是否现在自动执行 npm install -g @larksuite/cli？"):
        return False

    result = run([npm, "install", "-g", "@larksuite/cli"], timeout=None)
    if result.returncode != 0:
        print("[失败] lark-cli 安装失败。可能是网络或 npm 权限问题。")
        return False
    print("[OK] lark-cli 安装完成")
    return setup_lark_auth.find_lark_cli() is not None


def ensure_lark_auth() -> bool:
    cli = setup_lark_auth.find_lark_cli()
    if not cli:
        return False

    ok, output = setup_lark_auth.test_sheet_access(cli)
    if ok:
        print("[OK] 飞书账号已能读取目标表格")
        return True

    print("[需要处理] 当前飞书账号还不能读取目标表格。")
    if output:
        print(output[:900])
    if not ask_yes("是否现在打开飞书授权？"):
        return False
    return setup_lark_auth.start_auth(cli) and setup_lark_auth.test_sheet_access(cli)[0]


def ensure_swift_tools() -> bool:
    swiftc = shutil.which("swiftc")
    clicker = ROOT / "mac_click"
    recorder = ROOT / "mac_record"
    if clicker.exists() and recorder.exists():
        print("[OK] 鼠标宏组件已存在")
        return True

    if not swiftc:
        print("[需要处理] 找不到 swiftc。")
        print("macOS 会打开 Xcode Command Line Tools 安装器，装完后重新双击本脚本。")
        run(["xcode-select", "--install"], timeout=10)
        return False

    ok = True
    for name in ("mac_click", "mac_record"):
        source = ROOT / f"{name}.swift"
        target = ROOT / name
        result = subprocess.run([swiftc, str(source), "-o", str(target)], check=False, text=True)
        if result.returncode != 0:
            print(f"[失败] {name} 编译失败")
            ok = False
        else:
            print(f"[OK] {name} 编译完成")
    return ok


def open_accessibility_settings() -> None:
    print("[提示] 如果复位或播放宏没反应，需要打开辅助功能权限。")
    print("路径：系统设置 -> 隐私与安全性 -> 辅助功能")
    print("允许 Terminal、Python 或这个启动器控制电脑。")
    if ask_yes("是否现在打开辅助功能设置页？", default_yes=False):
        run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"], timeout=10)


def launch_console() -> int:
    url = console_url()
    if check_server_running():
        print("[OK] Web 控制台已经在运行，直接打开浏览器。")
        webbrowser.open(url)
        return 0

    print("启动 Web 控制台...")
    print(f"浏览器地址：{url}")
    return subprocess.run([sys.executable, str(ROOT / "web_console.py")], check=False).returncode


def main() -> int:
    print("iOS 一键准备并启动")
    print(f"目录：{ROOT}")
    print("")

    if sys.version_info < (3, 9):
        print("[失败] Python 版本太低，建议 3.9 或更高。")
        return 1

    if not ensure_swift_tools():
        return 1
    if not ensure_lark_cli():
        return 1
    if not ensure_lark_auth():
        return 1

    open_accessibility_settings()
    print("")
    print("准备完成。")
    time.sleep(0.5)
    return launch_console()


if __name__ == "__main__":
    raise SystemExit(main())
