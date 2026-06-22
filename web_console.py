from __future__ import annotations

import json
import mimetypes
import subprocess
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from reset_iphone_mirroring import (
    calibrate_login_connect_point,
    get_window_info,
    launch_mirroring,
    play_recorded_macro,
    record_macro,
    reset_window,
    run_login_connect_macro,
    save_current_window_profile,
    stop_recording,
)
from ios_sheet_writer import IOSSheetWriter, read_clipboard_link, read_clipboard_link_with_retry


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
CONFIG_PATH = ROOT / "config.json"

MACROS = {
    "normal_triple": "违规三连",
    "normal_quad": "违规四连",
    "normal_safe": "不违规",
    "raised_triple": "推荐三连",
    "raised_quad": "推荐四连",
    "raised_safe": "推荐不违规",
}


class ConsoleState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.busy = False
        self.mode = "idle"
        self.current = "空闲"
        self.recording = "空闲。点录制按钮后，在 iPhone 镜像里操作；按 ESC 或右键结束。"
        self.status = "准备就绪"
        self.last_result = ""
        self.updated_at = time.time()

    def snapshot(self) -> dict:
        writer = IOSSheetWriter()
        with self.lock:
            return {
                "busy": self.busy,
                "mode": self.mode,
                "current": self.current,
                "recording": self.recording,
                "status": self.status,
                "last_result": self.last_result,
                "updated_at": self.updated_at,
                "macros": macro_summary(),
                "profile": current_profile(),
                "profiles": load_config().get("macro_profiles", {}),
                "console": console_config(),
                "sheet": {
                    "current_row": writer.current_row,
                    "sheet_id": writer.sheet_id,
                },
            }

    def set(self, **kwargs) -> None:
        with self.lock:
            for key, value in kwargs.items():
                setattr(self, key, value)
            self.updated_at = time.time()


STATE = ConsoleState()


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def console_config(config: dict | None = None) -> dict:
    config = config or load_config()
    console = config.get("console", {})
    return {
        "title": console.get("title", "镜像宏控制台"),
        "eyebrow": console.get("eyebrow", "iOS V2"),
        "subtitle": console.get("subtitle", "录制、复位、播放都在一个柔软的小面板里。"),
        "port": int(console.get("port", 8877)),
    }


def macro_summary() -> list[dict]:
    config = load_config()
    recorded = config.get("recorded_macros", {})
    profile = current_profile_key(config)
    result = []
    for key, label in MACROS.items():
        actions = recorded.get(profile_macro_key(profile, key), {}).get("actions", [])
        result.append(
            {
                "key": key,
                "label": label,
                "recorded": bool(actions),
                "count": len(actions),
            }
        )
    return result


def current_profile_key(config: dict | None = None) -> str:
    config = config or load_config()
    profile = str(config.get("macro_profile", "stable"))
    return profile if profile in config.get("macro_profiles", {}) else "stable"


def current_profile(config: dict | None = None) -> dict:
    config = config or load_config()
    profile_key = current_profile_key(config)
    profile = config.get("macro_profiles", {}).get(profile_key, {})
    return {
        "key": profile_key,
        "label": profile.get("label", profile_key),
        "cat": profile.get("cat", "cat.png"),
    }


def set_current_profile(profile: str) -> tuple[bool, str]:
    config = load_config()
    if profile not in config.get("macro_profiles", {}):
        return False, f"未知版本：{profile}"
    config["macro_profile"] = profile
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    STATE.set(status=f"已切换到：{current_profile(config)['label']}")
    return True, f"已切换到：{current_profile(config)['label']}"


def profile_macro_key(profile: str, macro: str) -> str:
    return f"{profile}:{macro}"


def ensure_binaries() -> None:
    for name in ("mac_click", "mac_record"):
        source = ROOT / f"{name}.swift"
        binary = ROOT / name
        if not source.exists():
            continue
        if binary.exists() and binary.stat().st_mtime >= source.stat().st_mtime:
            continue
        subprocess.run(["swiftc", str(source), "-o", str(binary)], check=False)


def run_background(label: str, mode: str, worker, on_done=None) -> tuple[bool, str]:
    with STATE.lock:
        if STATE.busy:
            return False, "上一个操作还没结束，等一下再点。"
        STATE.busy = True
        STATE.mode = mode
        STATE.current = label
        STATE.status = f"{label}中..."
        if mode == "recording":
            STATE.recording = f"录制中：{label}。操作完点「结束录制并保存」，也可按 ESC/右键。"
        STATE.updated_at = time.time()

    def run() -> None:
        try:
            result = worker()
        except Exception as exc:
            result = f"ERROR:{exc}"

        if on_done:
            status, recording = on_done(result)
        else:
            status, recording = result, None

        update = {
            "busy": False,
            "mode": "idle",
            "current": "空闲",
            "status": status,
            "last_result": result,
        }
        if recording is not None:
            update["recording"] = recording
        STATE.set(**update)

    threading.Thread(target=run, daemon=True).start()
    return True, f"{label}已开始"


def play_and_write(storage_key: str, label: str) -> str:
    previous_link = read_clipboard_link()
    play_result = play_recorded_macro(storage_key)
    if not play_result.startswith("OK:"):
        return play_result
    link = read_clipboard_link_with_retry(5.0, previous_link=previous_link)
    if link == previous_link:
        return f"{play_result}；剪贴板 5 秒内仍是上一条链接，未写入飞书，请重试；链接={link}"
    writer = IOSSheetWriter()
    sheet_result = writer.write_from_macro(storage_key, link)
    return f"{play_result}；{sheet_result}；链接={link}"


def select_category_macro(category_id: str) -> str:
    config = load_config()
    profile = current_profile_key(config)
    recorded = config.get("recorded_macros", {})
    candidates = ["normal_safe", "raised_safe"] if category_id == "0" else ["normal_triple", "raised_triple"]
    for macro_key in candidates:
        storage_key = profile_macro_key(profile, macro_key)
        if recorded.get(storage_key, {}).get("actions"):
            return storage_key
    return profile_macro_key(profile, candidates[0])


def play_category_and_write(category_id: str) -> str:
    previous_link = read_clipboard_link()
    storage_key = select_category_macro(category_id)
    play_result = play_recorded_macro(storage_key, fast=True)
    if not play_result.startswith("OK:"):
        return play_result
    link = read_clipboard_link_with_retry(5.0, previous_link=previous_link)
    if link == previous_link:
        return f"{play_result}；剪贴板 5 秒内仍是上一条链接，未写入飞书，请重试；链接={link}"
    writer = IOSSheetWriter()
    sheet_result = writer.write_category_review(link, category_id)
    return f"{play_result}；{sheet_result}；链接={link}"


def run_recording_with_countdown(key: str, label: str) -> tuple[bool, str]:
    with STATE.lock:
        if STATE.busy:
            return False, "上一个操作还没结束，等一下再点。"
        STATE.busy = True
        STATE.mode = "countdown"
        STATE.current = f"录制{label}"
        STATE.status = "录制倒计时准备中..."
        STATE.recording = f"准备录制：{label}。请把鼠标放到 iPhone 镜像起始位置。"
        STATE.updated_at = time.time()

    def run() -> None:
        for remaining in (3, 2, 1):
            STATE.set(
                status=f"{remaining} 秒后开始录制",
                recording=f"倒计时 {remaining}：准备录制 {label}，不要点击多余位置。",
            )
            time.sleep(1)

        STATE.set(
            mode="recording",
            status=f"录制{label}中...",
            recording=f"录制中：{label}。操作完点「结束录制并保存」，也可按 ESC/右键。",
        )

        try:
            result = record_macro(key, 45.0)
        except Exception as exc:
            result = f"ERROR:{exc}"

        status, recording = record_done(label)(result)
        STATE.set(
            busy=False,
            mode="idle",
            current="空闲",
            status=status,
            recording=recording,
            last_result=result,
        )

    threading.Thread(target=run, daemon=True).start()
    return True, f"录制{label}倒计时已开始"


def record_done(label: str):
    def handler(result: str) -> tuple[str, str]:
        if result.startswith("OK:"):
            count = result.split("clicks=", 1)[1].split(":", 1)[0] if "clicks=" in result else "?"
            return result, f"录制完成：{label}，录到 {count} 个点击。"
        return result, f"录制失败：{label}。"

    return handler


def handle_action(action: str) -> tuple[bool, str]:
    if action.startswith("profile:"):
        return set_current_profile(action.split(":", 1)[1])

    if action == "stop_recording":
        result = stop_recording()
        STATE.set(status=f"已请求结束录制：{result}", recording="正在结束录制并保存，请等几秒看结果。")
        return True, result

    if action.startswith("row:"):
        try:
            row = int(action.split(":", 1)[1])
            IOSSheetWriter().set_current_row(row)
        except Exception as exc:
            return False, f"设置行号失败：{exc}"
        STATE.set(status=f"已设置当前写入行：{row}")
        return True, f"已设置当前写入行：{row}"

    actions = {
        "launch": ("启动 iPhone 镜像", "working", launch_mirroring, None),
        "reset_main": ("复位到主屏", "working", lambda: reset_window("main"), None),
        "reset_external": ("复位到外接屏", "working", lambda: reset_window("external"), None),
        "save_main_window": ("保存当前为主屏位", "working", lambda: save_current_window_profile("main"), None),
        "save_external_window": ("保存当前为外接屏位", "working", lambda: save_current_window_profile("external"), None),
        "read_coords": ("读取坐标", "working", get_window_info, None),
        "test_login": ("测试登录+连接", "working", run_login_connect_macro, None),
        "play_recent": ("播放最近录制宏", "playing", play_recorded_macro, None),
        "calibrate_login": ("校准登录点", "working", lambda: calibrate_login_connect_point("login", 3.0), None),
        "calibrate_connect": ("校准连接点", "working", lambda: calibrate_login_connect_point("connect", 3.0), None),
    }

    if action.startswith("record:"):
        key = action.split(":", 1)[1]
        storage_key = profile_macro_key(current_profile_key(), key)
        label = MACROS.get(key, key)
        return run_recording_with_countdown(storage_key, label)

    if action.startswith("play:"):
        key = action.split(":", 1)[1]
        storage_key = profile_macro_key(current_profile_key(), key)
        label = MACROS.get(key, key)
        return run_background(f"播放并写入{label}", "playing", lambda: play_and_write(storage_key, label))

    if action.startswith("category:"):
        category_id = action.split(":", 1)[1]
        if category_id not in {"0", "1", "2", "3", "4", "5", "6"}:
            return False, f"未知分类：{category_id}"
        label = "不违规" if category_id == "0" else f"分类 {category_id}"
        return run_background(f"写入{label}", "playing", lambda: play_category_and_write(category_id))

    if action not in actions:
        return False, f"未知操作：{action}"

    label, mode, worker, on_done = actions[action]
    return run_background(label, mode, worker, on_done)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = unquote(self.path.split("?", 1)[0])
        if path == "/api/status":
            self.send_json(STATE.snapshot())
            return
        if path == "/cat.png":
            profile = current_profile()
            cat_path = ROOT / profile["cat"]
            self.send_file(cat_path if cat_path.exists() else ROOT / "cat.png")
            return
        if path == "/":
            path = "/index.html"
        self.send_file(WEB_ROOT / path.lstrip("/"))

    def do_POST(self) -> None:
        if self.path != "/api/action":
            self.send_json({"ok": False, "message": "not found"}, status=404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        ok, message = handle_action(str(payload.get("action", "")))
        self.send_json({"ok": ok, "message": message})

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_json({"ok": False, "message": "not found"}, status=404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    ensure_binaries()
    port = console_config()["port"]
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"iOS Web 控制台已启动：{url}")
    webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
