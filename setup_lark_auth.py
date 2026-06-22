from __future__ import annotations

import json
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"


def run(command: list[str], timeout: int | None = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)


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


def load_sheet_config() -> tuple[str, str]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    sheet = config.get("sheet", {})
    token = sheet.get("spreadsheet_token")
    sheet_id = sheet.get("sheet_id")
    if not token or not sheet_id:
        raise RuntimeError("config.json 缺少 sheet.spreadsheet_token 或 sheet.sheet_id")
    return token, sheet_id


def test_sheet_access(cli: str) -> tuple[bool, str]:
    token, sheet_id = load_sheet_config()
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
    output = (result.stderr or result.stdout or "").strip()
    return result.returncode == 0, output


def print_install_help() -> None:
    print("[需要处理] 这台电脑找不到 lark-cli。")
    print("")
    print("如果这台电脑有 Node/npm，可以先运行：")
    print("")
    print("  npm install -g @larksuite/cli")
    print("")
    print("安装完以后，重新双击本脚本。")
    print("")
    print("如果没有 npm，先安装 Node.js，或者让管理员帮忙安装 lark-cli。")


def start_auth(cli: str) -> bool:
    print("准备发起飞书表格授权：--domain sheets")
    print("这个授权只影响当前电脑上的当前飞书用户，不会自动沿用你电脑上的授权。")
    print("")

    result = run([cli, "auth", "login", "--domain", "sheets", "--no-wait", "--json"], timeout=20)
    if result.returncode != 0:
        print("[授权发起失败]")
        print((result.stderr or result.stdout).strip())
        return False

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        print("[授权发起失败] lark-cli 没有返回 JSON：")
        print(result.stdout or result.stderr)
        return False

    data = payload.get("data", payload)
    verification_url = (
        data.get("verification_url")
        or data.get("verification_uri_complete")
        or payload.get("verification_url")
        or payload.get("verification_uri_complete")
    )
    device_code = data.get("device_code") or payload.get("device_code")

    if not verification_url or not device_code:
        print("[授权发起失败] 没拿到 verification_url 或 device_code：")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return False

    print("请在浏览器完成飞书授权：")
    print("")
    print(verification_url)
    print("")
    webbrowser.open(verification_url)
    input("授权完成后，回到这个窗口按回车继续...")

    complete = run([cli, "auth", "login", "--device-code", device_code], timeout=None)
    if complete.returncode != 0:
        print("[授权完成失败]")
        print((complete.stderr or complete.stdout).strip())
        return False

    print("[OK] 飞书授权流程已完成。")
    return True


def main() -> int:
    print("iOS V2 飞书授权引导")
    print(f"目录：{ROOT}")
    print("")

    cli = find_lark_cli()
    if not cli:
        print_install_help()
        return 1

    print(f"检测到 lark-cli：{cli}")
    ok, output = test_sheet_access(cli)
    if ok:
        print("[OK] 当前飞书账号已经可以读取这张表。")
        print("可以直接启动 Web 控制台试跑。")
        return 0

    print("[需要授权] 当前电脑还不能读取这张表。")
    if output:
        print("lark-cli 返回：")
        print(output[:1200])
        print("")

    answer = input("是否现在打开飞书授权？输入 y 后回车：").strip().lower()
    if answer not in {"y", "yes"}:
        print("已取消。需要时重新双击本脚本。")
        return 1

    if not start_auth(cli):
        return 1

    ok, output = test_sheet_access(cli)
    if ok:
        print("[OK] 授权后已能读取表格。")
        print("下一步：双击 启动Web控制台.command。")
        return 0

    print("[仍需处理] 授权完成了，但还不能读取这张表。")
    print("通常是这个飞书账号没有表格编辑/读取权限，或者授权账号不是同事要用的账号。")
    if output:
        print(output[:1200])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
