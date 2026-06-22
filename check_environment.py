from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"


def run(command: list[str], timeout: int = 8) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)


def status(ok: bool, title: str, detail: str = "") -> bool:
    mark = "OK" if ok else "需要处理"
    print(f"[{mark}] {title}")
    if detail:
        for line in detail.splitlines():
            print(f"  {line}")
    return ok


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        status(False, "读取 config.json", str(exc))
        return {}


def find_lark_cli() -> str | None:
    candidates = [
        shutil.which("lark-cli"),
        str(Path.home() / ".nvm/versions/node/v24.16.0/bin/lark-cli"),
        str(Path.home() / ".nvm/versions/node/v24.16.0/lib/node_modules/@larksuite/cli/bin/lark-cli"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def check_python() -> bool:
    version = sys.version_info
    return status(
        version >= (3, 9),
        "Python 版本",
        f"{sys.executable}\n当前 {version.major}.{version.minor}.{version.micro}，建议 3.9 或更高。",
    )


def check_macos() -> bool:
    version = platform.mac_ver()[0] or "unknown"
    major = int(version.split(".", 1)[0]) if version.split(".", 1)[0].isdigit() else 0
    return status(major >= 15, "macOS 版本", f"当前 {version}，iPhone Mirroring 建议 macOS 15+。")


def check_swift() -> bool:
    swiftc = shutil.which("swiftc")
    if not swiftc:
        return status(False, "Swift 编译器", "找不到 swiftc。请先安装 Xcode Command Line Tools。")

    ok = True
    details: list[str] = [swiftc]
    for name in ("mac_click", "mac_record"):
        source = ROOT / f"{name}.swift"
        target = ROOT / name
        if not source.exists():
            ok = False
            details.append(f"缺少 {source.name}")
            continue
        result = run([swiftc, str(source), "-o", str(target)], timeout=20)
        if result.returncode != 0:
            ok = False
            details.append(f"{name} 编译失败：{(result.stderr or result.stdout).strip()}")
        else:
            details.append(f"{name} 可编译")
    return status(ok, "Swift 鼠标宏组件", "\n".join(details))


def check_python_files() -> bool:
    result = run(
        [
            sys.executable,
            "-m",
            "py_compile",
            "web_console.py",
            "reset_iphone_mirroring.py",
            "ios_sheet_writer.py",
        ],
        timeout=12,
    )
    return status(result.returncode == 0, "Python 文件语法", (result.stderr or result.stdout).strip())


def check_lark(config: dict) -> bool:
    cli = find_lark_cli()
    if not cli:
        return status(
            False,
            "飞书 lark-cli",
            "找不到 lark-cli。先安装 lark-cli，再双击“飞书授权.command”完成同事账号授权。",
        )

    sheet = config.get("sheet", {})
    token = sheet.get("spreadsheet_token")
    sheet_id = sheet.get("sheet_id")
    if not token or not sheet_id:
        return status(False, "飞书表格配置", "config.json 里缺少 spreadsheet_token 或 sheet_id。")

    result = run(
        [
            cli,
            "sheets",
            "+csv-get",
            "--spreadsheet-token",
            token,
            "--sheet-id",
            sheet_id,
            "--range",
            "D1:J1",
            "--as",
            "user",
        ],
        timeout=18,
    )
    if result.returncode == 0:
        return status(True, "飞书读取授权", f"lark-cli 可用：{cli}")

    message = (result.stderr or result.stdout or "").strip()
    return status(
        False,
        "飞书读取授权",
        "lark-cli 已找到，但当前用户可能未授权，或没有这个表的权限。\n"
        "可以双击“飞书授权.command”按提示授权。\n"
        f"路径：{cli}\n"
        f"返回：{message[:900]}",
    )


def check_mirroring(config: dict) -> bool:
    app_names = config.get("app_names", ["iPhone Mirroring"])
    found = False
    for app_name in app_names:
        result = run(["osascript", "-e", f'tell application "System Events" to exists process "{app_name}"'])
        if result.stdout.strip().lower() == "true":
            found = True
            break

    profiles = config.get("profiles", {})
    main = profiles.get("main", {})
    expected = f'{main.get("x")},{main.get("y")},{main.get("width")},{main.get("height")}'
    if found:
        detail = f"已检测到 iPhone Mirroring 进程。\n录制主屏坐标：{expected}"
        return status(True, "iPhone Mirroring", detail)
    return status(
        False,
        "iPhone Mirroring",
        "当前没检测到镜像进程。先在控制台点“启动 iPhone 镜像”，再点“复位到主屏”。\n"
        f"录制主屏坐标：{expected}",
    )


def check_accessibility_hint() -> bool:
    print("[提示] 辅助功能权限")
    print("  第一次在新电脑播放宏时，macOS 可能会弹权限。")
    print("  如果点击/复位没反应：系统设置 -> 隐私与安全性 -> 辅助功能，允许 Terminal、Python 或启动器。")
    return True


def main() -> int:
    print("iOS V2 环境检查")
    print(f"目录：{ROOT}")
    print("")

    config = load_config()
    checks = [
        check_macos(),
        check_python(),
        check_python_files(),
        check_swift(),
        check_lark(config),
        check_mirroring(config),
        check_accessibility_hint(),
    ]

    print("")
    if all(checks):
        print("结论：环境看起来可以直接试跑。建议先用测试行跑 3-5 条。")
        return 0
    print("结论：上面标记“需要处理”的项先处理。处理完再双击本脚本复查。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
