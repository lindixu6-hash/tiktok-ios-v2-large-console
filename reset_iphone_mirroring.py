from __future__ import annotations

import json
import math
import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path

try:
    import Quartz
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID,
        NSWorkspace,
        NSApplicationActivateIgnoringOtherApps,
    )
    QUARTZ_AVAILABLE = True
except ImportError:
    QUARTZ_AVAILABLE = False

_FAST_EVENT_SOURCE = None

def _get_event_source():
    global _FAST_EVENT_SOURCE
    if _FAST_EVENT_SOURCE is None and QUARTZ_AVAILABLE:
        _FAST_EVENT_SOURCE = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    return _FAST_EVENT_SOURCE

def fast_click(x: int, y: int, move_settle_ms: int = 15, hold_ms: int = 40) -> None:
    src = _get_event_source()
    pt = Quartz.CGPoint(x, y)
    move = Quartz.CGEventCreateMouseEvent(src, Quartz.kCGEventMouseMoved, pt, 0)
    if move:
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, move)
    if move_settle_ms > 0:
        time.sleep(move_settle_ms / 1000.0)
    down = Quartz.CGEventCreateMouseEvent(src, Quartz.kCGEventLeftMouseDown, pt, 0)
    if down:
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
    if hold_ms > 0:
        time.sleep(hold_ms / 1000.0)
    up = Quartz.CGEventCreateMouseEvent(src, Quartz.kCGEventLeftMouseUp, pt, 0)
    if up:
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)

def fast_flick(delta_y: int = -600, steps: int = 10, duration_ms: int = 120) -> None:
    src = _get_event_source()
    step_us = int(duration_ms * 1000 / steps)
    for step in range(1, steps + 1):
        t = step / steps
        velocity = math.sin((1.0 - t) * math.pi / 2)
        step_delta = int((delta_y / steps) * velocity * 2.0)
        ev = Quartz.CGEventCreateScrollWheelEvent2(
            src,
            Quartz.kCGScrollEventUnitPixel,
            1,
            step_delta,
            0,
            0,
        )
        if ev:
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        if step < steps:
            time.sleep(step_us / 1_000_000.0)

def fast_swipe_next(delta_y: int = -600) -> None:
    fast_flick(delta_y, steps=10, duration_ms=120)

_TURBO_URL_RE = re.compile(r"https?://[^\s]+")

def _extract_url(text: str) -> str:
    m = _TURBO_URL_RE.search(text.strip())
    if not m:
        return ""
    link = m.group(0).rstrip("。，,)")
    # 截断查询参数：TikTok 分享长链在 video/<VID> 后带一堆追踪参数
    # （u_code/region/mid/sec_user_id/utm/...），只保留干净路径；vt 短链无 ? 不受影响
    link = link.split("?", 1)[0].rstrip("。，,)")
    return link


def read_iphone_clipboard_link() -> str:
    if not QUARTZ_AVAILABLE:
        return ""
    try:
        import Vision
        from Foundation import NSURL
    except ImportError:
        return ""

    config = load_config()
    info = get_front_window_info_quartz(config)
    if parse_window_info(info) is None:
        return ""

    source = _get_event_source()
    for key_down in (True, False):
        event = Quartz.CGEventCreateKeyboardEvent(source, 20, key_down)
        Quartz.CGEventSetFlags(event, Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
        time.sleep(0.08)
    time.sleep(0.8)

    window_id = None
    app_names = set(config.get("app_names", []))
    for window in CGWindowListCopyWindowInfo(
        kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID,
    ):
        if window.get("kCGWindowOwnerName") in app_names:
            window_id = window.get("kCGWindowNumber")
            break
    if not window_id:
        return ""

    fd, image_path = tempfile.mkstemp(prefix="iphone_clipboard_", suffix=".png")
    os.close(fd)
    try:
        capture = subprocess.run(
            ["screencapture", "-x", "-l", str(window_id), image_path],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
        if capture.returncode != 0:
            return ""

        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setRecognitionLanguages_(["en-US"])
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(
            NSURL.fileURLWithPath_(image_path),
            {},
        )
        ok, _ = handler.performRequests_error_([request], None)
        if not ok:
            return ""

        text_lines = []
        for observation in request.results() or []:
            candidates = observation.topCandidates_(1)
            if candidates:
                text_lines.append(str(candidates[0].string()))
        text = "\n".join(text_lines)
        # 优先匹配 vt.tiktok.com 短链接（干净的分享链接）
        short_match = re.search(
            r"https?://vt\.tiktok\.com/[A-Za-z0-9]+/?",
            text,
            re.IGNORECASE,
        )
        if short_match:
            return short_match.group(0)
        # 回退：匹配其他 tiktok.com 链接但截断查询参数
        match = re.search(
            r"(?:(?:https?://)?(?:www\.|vt\.)?tiktok\.com/[^\s?&]+)",
            text,
            re.IGNORECASE,
        )
        if not match:
            return ""
        link = match.group(0).rstrip("。，,)")
        return link if link.startswith(("http://", "https://")) else f"https://{link}"
    finally:
        try:
            os.unlink(image_path)
        except OSError:
            pass
        for key_down in (True, False):
            event = Quartz.CGEventCreateKeyboardEvent(source, 53, key_down)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
            time.sleep(0.05)


def is_share_transition(prev_x_ratio: float, cur_x_ratio: float, prev_y_ratio: float = 0.0, cur_y_ratio: float = 0.0) -> bool:
    if prev_x_ratio > 0.7 and cur_x_ratio < 0.5:
        return True
    if prev_x_ratio > 0.7 and cur_x_ratio > 0.7 and 0.60 < prev_y_ratio < 0.76 and cur_y_ratio > 0.73 and cur_y_ratio > prev_y_ratio:
        return True
    return False


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
CLICKER_PATH = ROOT / "mac_click"
RECORDER_PATH = ROOT / "mac_record"
STOP_RECORDING_PATH = ROOT / ".stop-recording"


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(config: dict) -> None:
    data = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_path = tempfile.mkstemp(dir=str(CONFIG_PATH.parent), prefix=".config_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(CONFIG_PATH))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def get_window_config(config: dict, profile: str) -> dict:
    if "profiles" in config:
        return config["profiles"].get(profile) or config["profiles"]["main"]
    return config["window"]


def build_applescript(config: dict, profile: str = "main") -> str:
    window = get_window_config(config, profile)
    app_names = config.get("app_names", ["iPhone Mirroring"])
    names = ", ".join(f'"{name}"' for name in app_names)
    return f"""
set targetNames to {{{names}}}
set targetX to {int(window["x"])}
set targetY to {int(window["y"])}
set targetW to {int(window["width"])}
set targetH to {int(window["height"])}

tell application "System Events"
    repeat with appName in targetNames
        if exists process appName then
            tell process appName
                set frontmost to true
                if (count of windows) is 0 then
                    return "NO_WINDOW:" & appName
                end if
                set position of window 1 to {{targetX, targetY}}
                set size of window 1 to {{targetW, targetH}}
                return "OK:" & appName & ":" & targetX & "," & targetY & "," & targetW & "," & targetH
            end tell
        end if
    end repeat
end tell

return "NOT_FOUND"
"""


def build_window_info_script(config: dict) -> str:
    app_names = config.get("app_names", ["iPhone Mirroring"])
    names = ", ".join(f'"{name}"' for name in app_names)
    return f"""
set targetNames to {{{names}}}

tell application "System Events"
    repeat with appName in targetNames
        if exists process appName then
            tell process appName
                if (count of windows) is 0 then
                    return "NO_WINDOW:" & appName
                end if
                set p to position of window 1
                set s to size of window 1
                return "INFO:" & appName & ":" & (item 1 of p) & "," & (item 2 of p) & "," & (item 1 of s) & "," & (item 2 of s)
            end tell
        end if
    end repeat
end tell

return "NOT_FOUND"
"""


def build_front_window_info_script(config: dict) -> str:
    app_names = config.get("app_names", ["iPhone Mirroring"])
    names = ", ".join(f'"{name}"' for name in app_names)
    return f"""
set targetNames to {{{names}}}

tell application "System Events"
    repeat with appName in targetNames
        if exists process appName then
            tell process appName
                set frontmost to true
                if (count of windows) is 0 then
                    return "NO_WINDOW:" & appName
                end if
                set p to position of window 1
                set s to size of window 1
                return "INFO:" & appName & ":" & (item 1 of p) & "," & (item 2 of p) & "," & (item 1 of s) & "," & (item 2 of s)
            end tell
        end if
    end repeat
end tell

return "NOT_FOUND"
"""


def run_osascript(script: str) -> str:
    completed = subprocess.run(
        ["osascript", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        return f"ERROR:{message}"
    return completed.stdout.strip()


def parse_window_info(result: str) -> tuple[str, int, int, int, int] | None:
    if not result.startswith("INFO:"):
        return None
    _, app_name, coords = result.split(":", 2)
    x, y, width, height = [int(value) for value in coords.split(",")]
    return app_name, x, y, width, height


def _find_mirror_app(config: dict):
    if not QUARTZ_AVAILABLE:
        return None
    ws = NSWorkspace.sharedWorkspace()
    app_names = config.get("app_names", ["iPhone Mirroring"])
    target_names = set(app_names)
    target_names.add("iPhone镜像")
    target_names.add("iPhone 镜像")
    for app in ws.runningApplications():
        name = app.localizedName()
        if name and name in target_names:
            return app
    return None


def get_front_window_info_quartz(config: dict, activate: bool = True) -> str:
    if not QUARTZ_AVAILABLE:
        return run_osascript(build_front_window_info_script(config) if activate else build_window_info_script(config))

    app = _find_mirror_app(config)
    if app is None:
        return "NOT_FOUND"

    app_name = app.localizedName()

    if activate:
        app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        time.sleep(0.25)

    window_list = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)
    for w in window_list:
        owner = w.get("kCGWindowOwnerName", "")
        layer = w.get("kCGWindowLayer", 0)
        if owner == app_name and layer == 0:
            bounds = w.get("kCGWindowBounds", {})
            x = int(bounds.get("X", 0))
            y = int(bounds.get("Y", 0))
            width = int(bounds.get("Width", 0))
            height = int(bounds.get("Height", 0))
            if width > 0 and height > 0:
                return f"INFO:{app_name}:{x},{y},{width},{height}"
    return f"NO_WINDOW:{app_name}"


def run_click(x: int, y: int) -> str:
    if not CLICKER_PATH.exists():
        return "ERROR:mac_click 不存在，请先编译 Swift 点击器"
    completed = subprocess.run(
        [str(CLICKER_PATH), str(x), str(y)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        return f"ERROR:{message}"
    return completed.stdout.strip()


def run_drag(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    duration_seconds: float = 0.32,
) -> str:
    if not CLICKER_PATH.exists():
        return "ERROR:mac_click 不存在，请先编译 Swift 点击器"
    completed = subprocess.run(
        [
            str(CLICKER_PATH),
            "drag",
            str(start_x),
            str(start_y),
            str(end_x),
            str(end_y),
            str(duration_seconds),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        return f"ERROR:{message}"
    return completed.stdout.strip()


def run_flick(delta_y: float, steps: int = 12, duration_ms: int = 140) -> str:
    if not CLICKER_PATH.exists():
        return "ERROR:mac_click 不存在，请先编译 Swift 点击器"
    completed = subprocess.run(
        [str(CLICKER_PATH), "flick", str(delta_y), str(steps), str(duration_ms)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        return f"ERROR:{message}"
    return completed.stdout.strip()


def run_recorder(timeout_seconds: float = 30.0) -> str:
    if not RECORDER_PATH.exists():
        return "ERROR:mac_record 不存在，请先编译 Swift 录制器"
    STOP_RECORDING_PATH.unlink(missing_ok=True)
    completed = subprocess.run(
        [str(RECORDER_PATH), str(timeout_seconds), str(STOP_RECORDING_PATH)],
        check=False,
        capture_output=True,
        text=True,
    )
    STOP_RECORDING_PATH.unlink(missing_ok=True)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        return f"ERROR:{message}"
    return completed.stdout.strip()


def stop_recording() -> str:
    STOP_RECORDING_PATH.write_text("stop", encoding="utf-8")
    return "OK:stop_requested"


def get_mouse_position() -> str:
    if not CLICKER_PATH.exists():
        return "ERROR:mac_click 不存在，请先编译 Swift 点击器"
    completed = subprocess.run(
        [str(CLICKER_PATH), "position"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        return f"ERROR:{message}"
    return completed.stdout.strip()


def parse_ok_point(result: str) -> tuple[int, int] | None:
    if not result.startswith("OK:"):
        return None
    x, y = [int(value) for value in result.split(":", 1)[1].split(",")]
    return x, y


def reset_window(profile: str = "main") -> str:
    return run_osascript(build_applescript(load_config(), profile))


def get_window_info() -> str:
    return get_front_window_info_quartz(load_config(), activate=False)


def run_scroll(delta_y: int) -> str:
    if not CLICKER_PATH.exists():
        return "ERROR:mac_click 不存在，请先编译 Swift 点击器"
    completed = subprocess.run(
        [str(CLICKER_PATH), "scroll", str(delta_y)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        return f"ERROR:{message}"
    return completed.stdout.strip()


def swipe_to_next_video() -> str:
    config = load_config()
    swipe = config.get("macros", {}).get("next_video_swipe", {})

    settle_delay = float(swipe.get("settle_delay_seconds", 0.12))
    time.sleep(settle_delay)

    delta_y = float(swipe.get("scroll_delta_y", -600))
    steps = int(swipe.get("scroll_steps", 12))
    duration_ms = int(swipe.get("scroll_duration_ms", 140))

    result = run_flick(delta_y, steps, duration_ms)
    if not result.startswith("OK:"):
        return result
    return f"OK:next_video:scroll:{int(delta_y)}"


def save_current_window_profile(profile: str) -> str:
    if profile not in {"main", "external"}:
        return f"ERROR:未知窗口位置 {profile}"
    config = load_config()
    info = get_front_window_info_quartz(config)
    parsed = parse_window_info(info)
    if parsed is None:
        return info

    app_name, x, y, width, height = parsed
    profiles = config.setdefault("profiles", {})
    profiles[profile] = {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
    }
    save_config(config)
    return f"OK:{app_name}:{profile}={x},{y},{width},{height}"


def launch_mirroring() -> str:
    config = load_config()
    app_names = config.get("app_names", ["iPhone Mirroring"])
    errors: list[str] = []
    for app_name in app_names:
        completed = subprocess.run(
            ["open", "-a", app_name],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0:
            return f"OK:{app_name}"
        message = completed.stderr.strip() or completed.stdout.strip()
        errors.append(f"{app_name}: {message}")
    return "ERROR:" + " | ".join(errors)


def run_login_connect_macro() -> str:
    config = load_config()
    macro = config["macros"]["icloud_login_connect"]
    info = get_front_window_info_quartz(config)
    parsed = parse_window_info(info)
    if parsed is None:
        return info

    app_name, left_x, top_y, width, height = parsed
    login = macro["login"]
    connect = macro["connect"]
    login_x = int(left_x + width * float(login["x_ratio"]))
    login_y = int(top_y + height * float(login["y_ratio"]))
    connect_x = int(left_x + width * float(connect["x_ratio"]))
    connect_y = int(top_y + height * float(connect["y_ratio"]))

    first = run_click(login_x, login_y)
    if not first.startswith("OK:"):
        return first
    time.sleep(float(macro.get("delay_seconds", 0.5)))
    second = run_click(connect_x, connect_y)
    if not second.startswith("OK:"):
        return second
    return f"OK:{app_name}:login={login_x},{login_y}:connect={connect_x},{connect_y}"


def parse_recording(output: str) -> list[tuple[int, int, int]]:
    clicks: list[tuple[int, int, int]] = []
    for line in output.splitlines():
        if not line.startswith("CLICK:"):
            continue
        x_text, y_text, ms_text = line.split(":", 1)[1].split(",")
        clicks.append((int(x_text), int(y_text), int(ms_text)))
    return clicks


def record_macro(macro_name: str, timeout_seconds: float = 30.0) -> str:
    config = load_config()
    info = get_front_window_info_quartz(config)
    parsed = parse_window_info(info)
    if parsed is None:
        return info

    app_name, left_x, top_y, width, height = parsed
    output = run_recorder(timeout_seconds)
    if output.startswith("ERROR:"):
        return output

    clicks = parse_recording(output)
    if not clicks:
        return "ERROR:没有录到点击。请点录制后，在镜像窗口里正常点击，最后按 ESC 或右键结束。"

    actions = []
    previous_ms = 0
    for mouse_x, mouse_y, ms in clicks:
        actions.append(
            {
                "delay_seconds": round(max(0, ms - previous_ms) / 1000, 3),
                "x_ratio": round((mouse_x - left_x) / width, 4),
                "y_ratio": round((mouse_y - top_y) / height, 4),
            }
        )
        previous_ms = ms

    recorded = config.setdefault("recorded_macros", {})
    recorded[macro_name] = {
        "profile": "main",
        "window": {
            "x": left_x,
            "y": top_y,
            "width": width,
            "height": height,
        },
        "actions": actions,
    }
    config["last_recorded_macro"] = macro_name
    save_config(config)
    return f"OK:{app_name}:{macro_name}:clicks={len(actions)}"


def compressed_macro_delay(index: int, total: int) -> float:
    if index == 0:
        return 0.03
    if index == total - 1:
        return 0.15
    return 0.05


def play_recorded_macro(macro_name: str | None = None, fast: bool = False) -> str:
    config = load_config()
    target_macro = macro_name or config.get("last_recorded_macro")
    if not target_macro:
        return "ERROR:还没有最近录制宏"
    macro = config.get("recorded_macros", {}).get(target_macro)
    if not macro:
        return f"ERROR:没有找到录制宏 {target_macro}"

    info = get_front_window_info_quartz(config)
    parsed = parse_window_info(info)
    if parsed is None:
        return info

    app_name, left_x, top_y, width, height = parsed
    actions = macro.get("actions", [])
    if not actions:
        return f"ERROR:录制宏 {target_macro} 没有动作"

    MIN_SHARE_SHEET_DELAY = 0.4

    prev_x_ratio = 1.0
    prev_y_ratio = 1.0
    for index, action in enumerate(actions):
        delay = float(action.get("delay_seconds", 0))
        cur_x_ratio = float(action["x_ratio"])
        cur_y_ratio = float(action["y_ratio"])
        if fast:
            delay = compressed_macro_delay(index, len(actions))
        if index > 0 and is_share_transition(prev_x_ratio, cur_x_ratio, prev_y_ratio, cur_y_ratio):
            delay = max(delay, MIN_SHARE_SHEET_DELAY)
        time.sleep(delay)
        x = int(left_x + width * cur_x_ratio)
        y = int(top_y + height * cur_y_ratio)
        result = run_click(x, y)
        if not result.startswith("OK:"):
            return result
        prev_x_ratio = cur_x_ratio
        prev_y_ratio = cur_y_ratio
    return f"OK:{app_name}:{target_macro}:played={len(actions)}"


def turbo_play_macro(macro_name: str) -> str:
    if not QUARTZ_AVAILABLE:
        return play_recorded_macro(macro_name, fast=True)

    config = load_config()
    target_macro = macro_name or config.get("last_recorded_macro")
    if not target_macro:
        return "ERROR:还没有最近录制宏"
    macro = config.get("recorded_macros", {}).get(target_macro)
    if not macro:
        return f"ERROR:没有找到录制宏 {target_macro}"

    info = get_front_window_info_quartz(config, activate=False)
    parsed = parse_window_info(info)
    if parsed is None:
        info2 = get_front_window_info_quartz(config, activate=True)
        parsed = parse_window_info(info2)
        if parsed is None:
            return info2

    app_name, left_x, top_y, width, height = parsed
    actions = macro.get("actions", [])
    if not actions:
        return f"ERROR:录制宏 {target_macro} 没有动作"

    INSTANT_DELAY = 0.035
    SHARE_SHEET_DELAY = 0.450

    prev_x_ratio = 1.0
    prev_y_ratio = 1.0
    for index, action in enumerate(actions):
        x_ratio = float(action["x_ratio"])
        y_ratio = float(action["y_ratio"])
        if is_share_transition(prev_x_ratio, x_ratio, prev_y_ratio, y_ratio):
            time.sleep(SHARE_SHEET_DELAY)
        elif index > 0:
            time.sleep(INSTANT_DELAY)
        x = int(left_x + width * x_ratio)
        y = int(top_y + height * y_ratio)
        fast_click(x, y, move_settle_ms=12, hold_ms=35)
        prev_x_ratio = x_ratio
        prev_y_ratio = y_ratio

    return f"OK:{app_name}:{target_macro}:turbo={len(actions)}"


def _wait_for_new_link(previous_link: str, timeout: float = 1.5) -> tuple[str, bool]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            cb = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=0.1)
            url = _extract_url(cb.stdout)
            if url and url != previous_link and len(url) > 10:
                return url, True
        except Exception:
            pass
        time.sleep(0.02)
    return "", False


def turbo_play_macro_and_get_link(macro_name: str, previous_link: str = "", swipe_delta_y: int = -600) -> dict:
    if not QUARTZ_AVAILABLE:
        return {"error": "Quartz not available"}

    config = load_config()
    target_macro = macro_name or config.get("last_recorded_macro")
    if not target_macro:
        return {"error": "还没有最近录制宏"}
    macro = config.get("recorded_macros", {}).get(target_macro)
    if not macro:
        return {"error": f"没有找到录制宏 {target_macro}"}

    info = get_front_window_info_quartz(config, activate=False)
    parsed = parse_window_info(info)
    if parsed is None:
        info = get_front_window_info_quartz(config, activate=True)
        parsed = parse_window_info(info)
        if parsed is None:
            return {"error": info}

    app_name, left_x, top_y, width, height = parsed
    actions = macro.get("actions", [])
    if not actions:
        return {"error": f"录制宏 {target_macro} 没有动作"}

    INSTANT_DELAY = 0.035
    SHARE_SHEET_DELAY = 0.450
    prev_x_ratio = 1.0
    prev_y_ratio = 1.0

    for index, action in enumerate(actions):
        x_ratio = float(action["x_ratio"])
        y_ratio = float(action["y_ratio"])
        is_last = index == len(actions) - 1
        if is_share_transition(prev_x_ratio, x_ratio, prev_y_ratio, y_ratio):
            time.sleep(SHARE_SHEET_DELAY)
        elif index > 0:
            time.sleep(INSTANT_DELAY)
        x = int(left_x + width * x_ratio)
        y = int(top_y + height * y_ratio)
        if is_last:
            fast_click(x, y, move_settle_ms=15, hold_ms=50)
            link, found = _wait_for_new_link(previous_link, timeout=1.5)
            fast_swipe_next(swipe_delta_y)
            return {
                "ok": True,
                "app_name": app_name,
                "macro": target_macro,
                "clicks": len(actions),
                "link": link,
                "link_found": found,
            }
        else:
            fast_click(x, y, move_settle_ms=12, hold_ms=35)
        prev_x_ratio = x_ratio
        prev_y_ratio = y_ratio

    return {"error": "no actions played"}


def calibrate_login_connect_point(point_name: str, delay_seconds: float = 3.0) -> str:
    if point_name not in {"login", "connect"}:
        return f"ERROR:未知校准点 {point_name}"

    config = load_config()
    info = get_front_window_info_quartz(config)
    parsed = parse_window_info(info)
    if parsed is None:
        return info

    app_name, left_x, top_y, width, height = parsed
    time.sleep(delay_seconds)
    point_result = get_mouse_position()
    point = parse_ok_point(point_result)
    if point is None:
        return point_result

    mouse_x, mouse_y = point
    x_ratio = round((mouse_x - left_x) / width, 4)
    y_ratio = round((mouse_y - top_y) / height, 4)
    macro = config.setdefault("macros", {}).setdefault("icloud_login_connect", {})
    macro.setdefault(point_name, {})
    macro[point_name]["x_ratio"] = x_ratio
    macro[point_name]["y_ratio"] = y_ratio
    save_config(config)
    return f"OK:{app_name}:{point_name}={mouse_x},{mouse_y}:ratio={x_ratio},{y_ratio}"


def main() -> None:
    result = reset_window()
    print(result)
    if result.startswith("OK:"):
        print("已复位 iPhone 镜像窗口。")
        return
    if result.startswith("NOT_FOUND"):
        print("没找到 iPhone Mirroring 窗口。请先打开 iPhone 镜像 App，并连接到 iPhone。")
        return
    if result.startswith("NO_WINDOW"):
        print("找到了 iPhone Mirroring 进程，但没有窗口。请先连接 iPhone 镜像。")
        return
    if "not allowed assistive access" in result.lower() or "accessibility" in result.lower():
        print("需要给 Terminal / Trae CN 辅助功能权限：系统设置 -> 隐私与安全性 -> 辅助功能。")
        return
    print("复位失败，请把上面的 ERROR 发给我。")


if __name__ == "__main__":
    main()
