from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
CLICKER_PATH = ROOT / "mac_click"
RECORDER_PATH = ROOT / "mac_record"
STOP_RECORDING_PATH = ROOT / ".stop-recording"


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(config: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
    return run_osascript(build_window_info_script(load_config()))


def save_current_window_profile(profile: str) -> str:
    if profile not in {"main", "external"}:
        return f"ERROR:未知窗口位置 {profile}"
    config = load_config()
    info = run_osascript(build_front_window_info_script(config))
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
    info = run_osascript(build_front_window_info_script(config))
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
    info = run_osascript(build_front_window_info_script(config))
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
        return 0.08
    if index == total - 1:
        return 0.48
    return 0.14


def play_recorded_macro(macro_name: str | None = None, fast: bool = False) -> str:
    config = load_config()
    target_macro = macro_name or config.get("last_recorded_macro")
    if not target_macro:
        return "ERROR:还没有最近录制宏"
    macro = config.get("recorded_macros", {}).get(target_macro)
    if not macro:
        return f"ERROR:没有找到录制宏 {target_macro}"

    info = run_osascript(build_front_window_info_script(config))
    parsed = parse_window_info(info)
    if parsed is None:
        return info

    app_name, left_x, top_y, width, height = parsed
    actions = macro.get("actions", [])
    if not actions:
        return f"ERROR:录制宏 {target_macro} 没有动作"

    for index, action in enumerate(actions):
        if fast:
            time.sleep(compressed_macro_delay(index, len(actions)))
        else:
            time.sleep(float(action.get("delay_seconds", 0)))
        x = int(left_x + width * float(action["x_ratio"]))
        y = int(top_y + height * float(action["y_ratio"]))
        result = run_click(x, y)
        if not result.startswith("OK:"):
            return result
    return f"OK:{app_name}:{target_macro}:played={len(actions)}"


def calibrate_login_connect_point(point_name: str, delay_seconds: float = 3.0) -> str:
    if point_name not in {"login", "connect"}:
        return f"ERROR:未知校准点 {point_name}"

    config = load_config()
    info = run_osascript(build_front_window_info_script(config))
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
