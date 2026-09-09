from __future__ import annotations

import json
import mimetypes
import os
import signal
import subprocess
import sys
import tempfile
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
    read_iphone_clipboard_link,
    record_macro,
    reset_window,
    run_login_connect_macro,
    save_current_window_profile,
    stop_recording,
    swipe_to_next_video,
)
from ios_sheet_writer import (
    IOSSheetWriter,
    read_clipboard_link,
    read_clipboard_link_with_retry,
    URL_PATTERN,
    domains_config,
    current_domain_key,
    category_for_key,
    BEHAVIOR_FEED,
    BEHAVIOR_SEARCH,
)

_LARK_CLI_CANDIDATES = [
    Path.home() / ".trae-cn/plugins/trae-remote-official/lark/1.0.3/bin",
    Path.home() / ".nvm/versions/node/v24.16.0/bin",
    Path.home() / ".local/bin",
]
for _p in _LARK_CLI_CANDIDATES:
    if _p.is_dir() and str(_p) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = str(_p) + os.pathsep + os.environ.get("PATH", "")


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
        self.status = "准备就绪，点「开始」启动养号"
        self.last_result = ""
        self.updated_at = time.time()
        self.page_mode = "feed"
        self.paused = True

    def snapshot(self) -> dict:
        writer = IOSSheetWriter()
        checks = run_permission_checks()
        all_ok = all(c.get("ok") for c in checks.values())
        page = current_page_mode()
        config = load_config()
        domains = domains_config(config)
        dom_key, dom = current_domain(config)
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
                "profiles": config.get("macro_profiles", {}),
                "page_mode": page,
                "page_modes": {k: v["label"] for k, v in PAGE_MODES.items()},
                "search_term": current_search_term(config),
                "current_domain": dom_key,
                "domains": {
                    k: {"label": v.get("label", k), "categories": v.get("categories", [])}
                    for k, v in domains.items()
                },
                "categories": dom.get("categories", []),
                "console": console_config(),
                "sheet": {
                    "current_row": writer.current_row,
                    "sheet_id": writer.sheet_id,
                    "spreadsheet_token": writer.spreadsheet_token,
                    "has_policy_column": writer.has_policy_column,
                    "binary_mode": writer.binary_mode,
                },
                "permissions": {
                    "ok": all_ok,
                    "checks": checks,
                },
                "global_hotkeys": hotkey_daemon_status(),
                "paused": self.paused,
            }

    def set(self, **kwargs) -> None:
        with self.lock:
            for key, value in kwargs.items():
                setattr(self, key, value)
            self.updated_at = time.time()


STATE = ConsoleState()

HOTKEY_SCRIPT = ROOT / "global_hotkeys.py"
HOTKEY_PID_FILE = ROOT / ".hotkey.pid"
_hotkey_proc: subprocess.Popen | None = None


def _kill_orphan_hotkeys() -> None:
    """Kill any leftover global_hotkeys.py processes from previous runs."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "global_hotkeys.py"],
            capture_output=True, text=True, timeout=5,
        )
        for pid_str in result.stdout.strip().split("\n"):
            pid_str = pid_str.strip()
            if not pid_str:
                continue
            try:
                pid = int(pid_str)
                if pid == os.getpid():
                    continue
                os.kill(pid, signal.SIGTERM)
                print(f"  → 清理孤儿 hotkey 进程 PID {pid}")
            except (ProcessLookupError, ValueError, PermissionError):
                pass
        time.sleep(0.5)
        result = subprocess.run(
            ["pgrep", "-f", "global_hotkeys.py"],
            capture_output=True, text=True, timeout=5,
        )
        for pid_str in result.stdout.strip().split("\n"):
            pid_str = pid_str.strip()
            if not pid_str:
                continue
            try:
                pid = int(pid_str)
                if pid != os.getpid():
                    os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, ValueError, PermissionError):
                pass
    except Exception:
        pass


def start_hotkey_daemon() -> bool:
    global _hotkey_proc
    if _hotkey_proc is not None and _hotkey_proc.poll() is None:
        return True
    _kill_orphan_hotkeys()
    try:
        log_path = ROOT / "hotkey.log"
        log_f = open(str(log_path), "a", buffering=1)
        _hotkey_proc = subprocess.Popen(
            [sys.executable, str(HOTKEY_SCRIPT)],
            stdout=log_f,
            stderr=subprocess.STDOUT,
            cwd=str(ROOT),
        )
        HOTKEY_PID_FILE.write_text(str(_hotkey_proc.pid))
        for _ in range(20):
            time.sleep(0.15)
            if _hotkey_proc.poll() is not None:
                return False
            try:
                import urllib.request
                urllib.request.urlopen("http://127.0.0.1:8880/api/status", timeout=0.5)
                return True
            except Exception:
                continue
        return _hotkey_proc.poll() is None
    except Exception:
        return False


def stop_hotkey_daemon() -> None:
    global _hotkey_proc
    if _hotkey_proc is not None:
        try:
            _hotkey_proc.terminate()
            _hotkey_proc.wait(timeout=2)
        except Exception:
            try:
                _hotkey_proc.kill()
            except Exception:
                pass
        _hotkey_proc = None
    try:
        HOTKEY_PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    _kill_orphan_hotkeys()


def hotkey_daemon_status() -> dict:
    running = _hotkey_proc is not None and _hotkey_proc.poll() is None
    return {"running": running}


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _atomic_save_config(config: dict) -> None:
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
    all_keys = [
        ("normal_quad", "违规四连", "违规四连"),
        ("normal_safe", "不违规", "不违规"),
    ]
    for key, label, short_label in all_keys:
        storage_key = profile_macro_key(profile, key)
        actions = recorded.get(storage_key, {}).get("actions", [])
        result.append(
            {
                "key": key,
                "label": label,
                "short_label": short_label,
                "recorded": bool(actions),
                "count": len(actions),
                "active": True,
                "page": "shared",
            }
        )
    return result


PAGE_MODES = {
    "feed": {"label": "Feed"},
    "search": {"label": "搜索"},
}


def current_page_mode(config: dict | None = None) -> str:
    config = config or load_config()
    mode = str(config.get("page_mode", "feed"))
    return mode if mode in PAGE_MODES else "feed"


def set_page_mode(mode: str) -> tuple[bool, str]:
    if mode not in PAGE_MODES:
        return False, f"未知页面模式：{mode}"
    config = load_config()
    config["page_mode"] = mode
    _atomic_save_config(config)
    label = PAGE_MODES[mode]["label"]
    STATE.set(status=f"已切换到：{label}模式", page_mode=mode)
    return True, f"已切换到：{label}模式"


def current_search_term(config: dict | None = None) -> str:
    config = config or load_config()
    return str(config.get("search_term", "")).strip()


def set_search_term(term: str) -> tuple[bool, str]:
    term = term.strip()
    config = load_config()
    config["search_term"] = term
    _atomic_save_config(config)
    return True, f"搜索词已设置：{term}" if term else "搜索词已清空"


def is_binary_mode(config: dict | None = None) -> bool:
    config = config or load_config()
    return bool(config.get("sheet", {}).get("binary_mode", False))


def current_domain(config: dict | None = None) -> tuple[str, dict]:
    config = config or load_config()
    domains = domains_config(config)
    key = current_domain_key(config)
    return key, domains.get(key, {})


def set_domain(domain: str) -> tuple[bool, str]:
    config = load_config()
    domains = domains_config(config)
    if domain not in domains:
        return False, f"未知领域：{domain}"
    config["current_domain"] = domain
    _atomic_save_config(config)
    label = domains[domain].get("label", domain)
    keys = " / ".join(
        f"{c.get('key')}={c.get('label')}" for c in domains[domain].get("categories", [])
    )
    STATE.set(status=f"已切换到 {label} 领域（{keys}）")
    return True, f"已切换到 {label} 领域"


def category_macro_suffix(category_id: str) -> str:
    config = load_config()
    cat = category_for_key(config, category_id)
    if cat is None:
        return "quad"
    return "safe" if cat.get("macro") == "safe" else "quad"


# 兼容旧调用名
def page_mode_macro_suffix(category_id: str) -> str:
    return category_macro_suffix(category_id)


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
    _atomic_save_config(config)
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


def _cache_value(seconds: float):
    def decorator(func):
        _cache = {"value": None, "ts": 0.0}

        def wrapper(*args, **kwargs):
            now = time.monotonic()
            if _cache["value"] is not None and now - _cache["ts"] < seconds:
                return _cache["value"]
            result = func(*args, **kwargs)
            _cache["value"] = result
            _cache["ts"] = now
            return result

        return wrapper

    return decorator


@_cache_value(5.0)
def check_accessibility_permission() -> dict:
    try:
        from Quartz import NSWorkspace
        ws = NSWorkspace.sharedWorkspace()
        front = ws.frontmostApplication()
        if front and front.bundleIdentifier():
            return {"ok": True, "message": "辅助功能权限正常（Quartz模式）"}
    except Exception:
        pass
    test_script = '''
tell application "System Events"
    set frontApp to name of first application process whose frontmost is true
end tell
return frontApp
'''
    try:
        result = subprocess.run(
            ["osascript", "-e", test_script],
            capture_output=True, text=True, timeout=5.0,
        )
        if result.returncode == 0:
            return {"ok": True, "message": "辅助功能权限已授权"}
        err = result.stderr.lower()
        if "not authorized" in err or "-10004" in err or "privacy" in err:
            return {
                "ok": False,
                "code": "ACCESSIBILITY_DENIED",
                "message": "辅助功能权限未授权，自动点击可能失败",
                "fix_url": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
            }
        return {"ok": False, "code": "UNKNOWN", "message": f"辅助功能检测异常：{result.stderr.strip()[:200]}"}
    except FileNotFoundError:
        return {"ok": False, "code": "NO_OSASCRIPT", "message": "无法执行osascript"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": "TIMEOUT", "message": "辅助功能检测超时"}
    except Exception as exc:
        return {"ok": False, "code": "ERROR", "message": f"检测失败：{exc}"}


@_cache_value(10.0)
def check_lark_cli_auth() -> dict:
    try:
        result = subprocess.run(
            ["lark-cli", "auth", "status"],
            capture_output=True, text=True, timeout=8.0,
        )
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                identities = data.get("identities", {})
                user_id = identities.get("user", {})
                if user_id.get("status") == "ready" and user_id.get("available"):
                    name = user_id.get("userName", "")
                    return {"ok": True, "message": f"飞书CLI已登录：{name}"}
                bot_id = identities.get("bot", {})
                if bot_id.get("status") == "ready":
                    return {"ok": True, "message": "飞书CLI已登录（bot）"}
            except json.JSONDecodeError:
                if "ready" in result.stdout.lower() or "logged" in result.stdout.lower():
                    return {"ok": True, "message": "飞书CLI已登录"}
        return {
            "ok": False,
            "code": "LARK_NOT_AUTH",
            "message": "飞书CLI未授权，飞书写入将失败",
            "fix_hint": "请运行 lark-cli auth login 完成授权",
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "code": "LARK_NOT_FOUND",
            "message": "未找到lark-cli命令，请确认已安装",
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": "TIMEOUT", "message": "飞书CLI检测超时"}
    except Exception as exc:
        return {"ok": False, "code": "ERROR", "message": f"飞书CLI检测失败：{exc}"}


@_cache_value(5.0)
def check_iphone_mirroring() -> dict:
    try:
        from Quartz import NSWorkspace
        ws = NSWorkspace.sharedWorkspace()
        target_names = {"iPhone Mirroring", "iPhone 镜像", "iPhone镜像", "iPhone鏡像輸出", "iPhoneミラーリング"}
        for app in ws.runningApplications():
            name = app.localizedName()
            if name and name in target_names:
                return {"ok": True, "message": f"{name} 正在运行"}
    except Exception:
        pass
    return {
        "ok": False,
        "code": "MIRRORING_NOT_RUNNING",
        "message": "iPhone 镜像未启动，请先连接并打开iPhone Mirroring",
    }


@_cache_value(3.0)
def check_config() -> dict:
    config = load_config()
    issues = []
    sheet = config.get("sheet", {})
    if not sheet.get("spreadsheet_token"):
        issues.append("spreadsheet_token为空")
    if not sheet.get("sheet_id"):
        issues.append("sheet_id为空")
    if not config.get("recorded_macros"):
        issues.append("未配置宏坐标")
    profile = config.get("profiles", {}).get("main", {})
    if not all(k in profile for k in ("x", "y", "width", "height")):
        issues.append("主屏窗口位置未校准")
    if issues:
        return {"ok": False, "code": "CONFIG_INCOMPLETE", "message": "配置不完整：" + "；".join(issues)}
    return {"ok": True, "message": "配置完整"}


def run_permission_checks() -> dict:
    results = {
        "accessibility": check_accessibility_permission(),
        "lark_cli": check_lark_cli_auth(),
        "mirroring": check_iphone_mirroring(),
        "config": check_config(),
    }
    return results


def auto_fix_permissions(checks: dict) -> list[str]:
    fixes = []
    ax = checks.get("accessibility", {})
    if not ax.get("ok") and ax.get("fix_url"):
        try:
            subprocess.run(["open", ax["fix_url"]], capture_output=True, timeout=3.0)
            fixes.append("已自动打开「系统设置 → 隐私与安全性 → 辅助功能」，请勾选 Terminal / Python")
        except Exception:
            fixes.append("请手动打开：系统设置 → 隐私与安全性 → 辅助功能，勾选 Terminal")
    lark = checks.get("lark_cli", {})
    if not lark.get("ok") and "LARK_NOT_AUTH" in lark.get("code", ""):
        fixes.append("请在终端运行：lark-cli auth login")
    mirroring = checks.get("mirroring", {})
    if not mirroring.get("ok"):
        try:
            subprocess.run(["open", "-a", "iPhone Mirroring"], capture_output=True, timeout=3.0)
            fixes.append("已尝试自动启动 iPhone 镜像")
        except Exception:
            try:
                subprocess.run(["open", "-a", "iPhone 镜像"], capture_output=True, timeout=3.0)
                fixes.append("已尝试自动启动 iPhone 镜像")
            except Exception:
                fixes.append("请手动打开 iPhone 镜像应用")
    return fixes


def fetch_sheet_stats() -> dict:
    config = load_config()
    sheet_cfg = config.get("sheet", {})
    token = sheet_cfg.get("spreadsheet_token", "")
    sid = sheet_cfg.get("sheet_id", "")
    if not token or not sid:
        return {"ok": False, "error": "spreadsheet_token或sheet_id未配置"}

    has_policy = bool(sheet_cfg.get("has_policy_column", True))
    range_str = "B2:G2000" if has_policy else "B2:F2000"
    policy_idx = 4 if has_policy else -1
    inter_idx = 5 if has_policy else 4
    try:
        result = subprocess.run(
            ["lark-cli", "sheets", "+cells-get", "--spreadsheet-token", token,
             "--sheet-id", sid, "--range", range_str, "--as", "user"],
            capture_output=True, text=True, timeout=30.0,
        )
        if result.returncode != 0:
            return {"ok": False, "error": f"读取数据失败：{result.stderr[:300]}"}
        resp = json.loads(result.stdout)
        ranges_data = resp.get("data", {}).get("ranges", [])
        if not ranges_data:
            return {"ok": False, "error": "无数据返回"}
        cells = ranges_data[0].get("cells", [])
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "读取数据超时"}
    except Exception as e:
        return {"ok": False, "error": f"读取数据异常：{e}"}

    def cell_value(cell):
        if cell is None:
            return ""
        if isinstance(cell, dict):
            return str(cell.get("value", "")).strip()
        return str(cell).strip()

    def cell_multi(cell):
        if isinstance(cell, dict):
            mv = cell.get("multiple_values")
            if mv and isinstance(mv, list):
                return [v.get("value", "") for v in mv if isinstance(v, dict) and v.get("value")]
        txt = cell_value(cell)
        if txt:
            return [x.strip() for x in txt.split(",") if x.strip()]
        return []

    total = 0
    violation = 0
    safe = 0
    search_count = 0
    feed_count = 0
    profile_count = 0
    search_terms = {}
    policies = {}
    interactions = {}

    for row in cells:
        if not row or len(row) < 4:
            continue

        behavior = cell_value(row[0]) if len(row) > 0 else ""
        search_term = cell_value(row[1]) if len(row) > 1 else ""
        link_text = cell_value(row[2]) if len(row) > 2 else ""
        is_v_text = cell_value(row[3]) if len(row) > 3 else ""
        policy_text = cell_value(row[policy_idx]) if policy_idx >= 0 and len(row) > policy_idx else ""
        inter_cell = row[inter_idx] if len(row) > inter_idx else None

        has_data = bool(behavior) or is_v_text in ("是", "否")
        has_link = bool(link_text) and link_text not in ("链接", "link", "https://")
        if not has_link and not has_data:
            continue

        total += 1
        is_v = is_v_text == "是"
        inters = cell_multi(inter_cell)

        if behavior == "刷feed":
            feed_count += 1
        elif behavior == "搜索词":
            search_count += 1
        elif behavior == "进用户主页消费":
            profile_count += 1

        if search_term:
            search_terms[search_term] = search_terms.get(search_term, 0) + 1

        if policy_text:
            policies[policy_text] = policies.get(policy_text, 0) + 1

        if is_v:
            violation += 1
        else:
            safe += 1
        for it in inters:
            interactions[it] = interactions.get(it, 0) + 1

    violation_rate = round(violation / total * 100, 1) if total > 0 else 0
    return {
        "ok": True,
        "total": total,
        "violation": violation,
        "safe": safe,
        "violation_rate": violation_rate,
        "feed_count": feed_count,
        "search_count": search_count,
        "profile_count": profile_count,
        "search_terms": search_terms,
        "policies": policies,
        "interactions": interactions,
    }


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


def _run_reliable_pipeline(storage_key: str, previous_link: str, write_fn, use_fast_macro: bool, retry_timeout: float, allow_empty_link: bool = False) -> str:
    # #region debug-point B:pipeline-entry
    try:
        import urllib.request as _debug_urlrequest; _debug_urlrequest.urlopen(_debug_urlrequest.Request("http://127.0.0.1:7777/event", data=json.dumps({"sessionId":"sheet-write-failure","runId":"post-fix","hypothesisId":"B","location":"web_console.py:_run_reliable_pipeline","msg":"[DEBUG] pipeline entered","data":{"storage_key":storage_key,"previous_link_present":bool(previous_link),"retry_timeout":retry_timeout}}).encode(), headers={"Content-Type":"application/json"}), timeout=0.2).read()
    except Exception:
        pass
    # #endregion
    play_result = play_recorded_macro(storage_key, fast=use_fast_macro)
    if not play_result.startswith("OK:"):
        # 首次按键时镜像窗口可能尚未激活到前台（NOT_FOUND），激活后重试一次
        if "NOT_FOUND" in play_result or play_result.startswith("NO_WINDOW"):
            launch_mirroring()
            time.sleep(1.2)
            try:
                reset_window("main")
            except Exception:
                pass
            time.sleep(0.5)
            play_result = play_recorded_macro(storage_key, fast=use_fast_macro)
        if not play_result.startswith("OK:"):
            return play_result

    link = read_clipboard_link_with_retry(retry_timeout, previous_link=previous_link)
    link_is_new = bool(URL_PATTERN.fullmatch(link or "")) and link != previous_link
    if not link_is_new:
        iphone_link = read_iphone_clipboard_link()
        if iphone_link:
            link = iphone_link
            link_is_new = bool(URL_PATTERN.fullmatch(link)) and link != previous_link
    # #region debug-point B:clipboard-result
    try:
        import urllib.request as _debug_urlrequest; _debug_urlrequest.urlopen(_debug_urlrequest.Request("http://127.0.0.1:7777/event", data=json.dumps({"sessionId":"sheet-write-failure","runId":"post-fix","hypothesisId":"B","location":"web_console.py:_run_reliable_pipeline","msg":"[DEBUG] clipboard retry completed","data":{"play_ok":play_result.startswith("OK:"),"link_present":bool(link),"link_is_new":link_is_new,"link_length":len(link or "")}}).encode(), headers={"Content-Type":"application/json"}), timeout=0.2).read()
    except Exception:
        pass
    # #endregion

    if not link_is_new and not allow_empty_link:
        swipe_to_next_video()
        return f"{play_result}；剪贴板未检测到新链接（链接={link[:60] if link else '空'}）；已滑动"

    write_link = link if link_is_new else ""

    def bg_write():
        try:
            writer = IOSSheetWriter()
            # #region debug-point D:writer-target
            try:
                import urllib.request as _debug_urlrequest; _debug_urlrequest.urlopen(_debug_urlrequest.Request("http://127.0.0.1:7777/event", data=json.dumps({"sessionId":"sheet-write-failure","runId":"post-fix","hypothesisId":"D","location":"web_console.py:bg_write","msg":"[DEBUG] writer initialized","data":{"sheet_id":writer.sheet_id,"token_suffix":writer.spreadsheet_token[-6:],"current_row":writer.current_row}}).encode(), headers={"Content-Type":"application/json"}), timeout=0.2).read()
            except Exception:
                pass
            # #endregion
            write_result = write_fn(writer, write_link)
            # #region debug-point C:write-success
            try:
                import urllib.request as _debug_urlrequest; _debug_urlrequest.urlopen(_debug_urlrequest.Request("http://127.0.0.1:7777/event", data=json.dumps({"sessionId":"sheet-write-failure","runId":"post-fix","hypothesisId":"C","location":"web_console.py:bg_write","msg":"[DEBUG] background write succeeded","data":{"result":str(write_result),"next_row":writer.current_row}}).encode(), headers={"Content-Type":"application/json"}), timeout=0.2).read()
            except Exception:
                pass
            # #endregion
        except Exception as e:
            # #region debug-point C:write-error
            try:
                import urllib.request as _debug_urlrequest; _debug_urlrequest.urlopen(_debug_urlrequest.Request("http://127.0.0.1:7777/event", data=json.dumps({"sessionId":"sheet-write-failure","runId":"post-fix","hypothesisId":"C","location":"web_console.py:bg_write","msg":"[DEBUG] background write failed","data":{"error_type":type(e).__name__,"error":str(e)[:1000]}}).encode(), headers={"Content-Type":"application/json"}), timeout=0.2).read()
            except Exception:
                pass
            # #endregion
            print(f"[sheet] 写入失败: {e}", flush=True)

    threading.Thread(target=bg_write, daemon=True).start()
    swipe_result = swipe_to_next_video()

    if link_is_new:
        parts = [play_result, "链接已捕获", swipe_result, f"链接={link[:80]}", "后台写入中"]
    else:
        parts = [play_result, "链接未同步，已无链接写入", swipe_result, "后台写入中"]
    return "；".join(parts)


def play_and_write(storage_key: str, label: str) -> str:
    previous_link = read_clipboard_link()
    return _run_reliable_pipeline(
        storage_key,
        previous_link,
        lambda writer, link: writer.write_from_macro(storage_key, link),
        use_fast_macro=True,
        retry_timeout=2.5,
    )


def select_category_macro(category_id: str) -> str:
    config = load_config()
    profile = current_profile_key(config)
    suffix = page_mode_macro_suffix(category_id)
    return profile_macro_key(profile, f"normal_{suffix}")


def play_category_and_write(category_id: str) -> str:
    config = load_config()
    mode = current_page_mode(config)
    search_term = current_search_term(config) if mode == "search" else ""
    if mode == "search" and not search_term:
        return "ERROR:搜索模式必须先填写搜索词"
    behavior = BEHAVIOR_SEARCH if mode == "search" else BEHAVIOR_FEED
    previous_link = read_clipboard_link()
    storage_key = select_category_macro(category_id)
    suffix = category_macro_suffix(category_id)
    use_fast = suffix != "safe"
    return _run_reliable_pipeline(
        storage_key,
        previous_link,
        lambda writer, link: writer.write_category_review(
            link,
            category_id,
            search_term=search_term,
            behavior=behavior,
        ),
        use_fast_macro=use_fast,
        retry_timeout=8.0,
        allow_empty_link=False,
    )


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


def category_hint() -> str:
    _key, dom = current_domain()
    parts = [f"{c.get('key')}={c.get('label')}" for c in dom.get("categories", [])]
    return " / ".join(parts)


def handle_action(action: str) -> tuple[bool, str]:
    if action == "start":
        STATE.set(paused=False, status="正在启动养号...", current="启动中")
        def _start_worker():
            launch_mirroring()
            time.sleep(1.0)
            try:
                reset_window("main")
            except Exception:
                pass
            return f"养号已开始（{current_domain()[1].get('label','')} 领域），可以按 {category_hint()} 键分类视频"
        return run_background("启动养号", "working", _start_worker)

    if action == "pause":
        STATE.set(paused=True, status="已暂停，分类键不会触发操作", current="已暂停")
        return True, "已暂停养号"

    if action.startswith("profile:"):
        return set_current_profile(action.split(":", 1)[1])

    if action.startswith("domain:"):
        return set_domain(action.split(":", 1)[1])

    if action.startswith("page_mode:"):
        return set_page_mode(action.split(":", 1)[1])

    if action.startswith("search_term:"):
        return set_search_term(action.split(":", 1)[1])

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
        if STATE.paused:
            return False, "已暂停，请先点「开始」"
        key = action.split(":", 1)[1]
        storage_key = profile_macro_key(current_profile_key(), key)
        label = MACROS.get(key, key)
        return run_recording_with_countdown(storage_key, label)

    if action.startswith("play:"):
        if STATE.paused:
            return False, "已暂停，请先点「开始」"
        key = action.split(":", 1)[1]
        storage_key = profile_macro_key(current_profile_key(), key)
        label = MACROS.get(key, key)
        return run_background(f"播放并写入{label}", "playing", lambda: play_and_write(storage_key, label))

    if action.startswith("category:"):
        # #region debug-point A:category-entry
        try:
            import urllib.request as _debug_urlrequest; _debug_urlrequest.urlopen(_debug_urlrequest.Request("http://127.0.0.1:7777/event", data=json.dumps({"sessionId":"sheet-write-failure","runId":"post-fix","hypothesisId":"A","location":"web_console.py:handle_action","msg":"[DEBUG] category action received","data":{"action":action,"paused":STATE.paused,"busy":STATE.busy}}).encode(), headers={"Content-Type":"application/json"}), timeout=0.2).read()
        except Exception:
            pass
        # #endregion
        if STATE.paused:
            return False, "已暂停，请先点「开始」再按分类键"
        category_id = action.split(":", 1)[1]
        cat = category_for_key(load_config(), category_id)
        if cat is None:
            return False, f"未知分类：{category_id}（{current_domain()[1].get('label','')} 领域支持：{category_hint()}）"
        label = str(cat.get("label", category_id))
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
        if path == "/api/permissions":
            self.send_json(run_permission_checks())
            return
        if path == "/api/stats":
            self.send_json(fetch_sheet_stats())
            return
        if path == "/cat.png":
            profile = current_profile()
            cat_path = ROOT / profile["cat"]
            self.send_file(cat_path if cat_path.exists() else ROOT / "cat.png")
            return
        if path == "/":
            path = "/index.html"
        if path == "/mini":
            self.send_response(302)
            self.send_header("Location", "/mini.html")
            self.end_headers()
            return
        self.send_file(WEB_ROOT / path.lstrip("/"))

    def do_POST(self) -> None:
        if self.path == "/api/fix-permissions":
            checks = run_permission_checks()
            fixes = auto_fix_permissions(checks)
            self.send_json({"ok": True, "fixes": fixes, "checks": checks})
            return
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

    print("=" * 60)
    print("iOS Web 控制台启动中，正在检测环境...")
    checks = run_permission_checks()
    issues = [name for name, c in checks.items() if not c.get("ok")]
    if issues:
        print(f"\n⚠️  检测到 {len(issues)} 个问题：")
        for name in issues:
            c = checks[name]
            label = {"accessibility": "辅助功能权限", "lark_cli": "飞书CLI", "mirroring": "iPhone镜像", "config": "配置"}.get(name, name)
            print(f"  ✗ {label}：{c['message']}")
        fixes = auto_fix_permissions(checks)
        if fixes:
            print(f"\n🔧 已执行自动修复：")
            for f in fixes:
                print(f"  → {f}")
        print()
    else:
        print("✓ 所有检查通过：辅助功能、飞书CLI、iPhone镜像、配置均正常\n")

    port = console_config()["port"]
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)

    def shutdown_handler(signum, frame):
        print("\n正在关闭...")
        stop_hotkey_daemon()
        server.shutdown()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    print("⌨️  启动全局快捷键守护进程...")
    if start_hotkey_daemon():
        print("✓ 全局快捷键已就绪（1-7 键全局可用，浏览器前台时由网页处理）\n")
    else:
        print("⚠️  全局快捷键启动失败，将仅在浏览器焦点时响应\n")

    url = f"http://127.0.0.1:{port}/"
    print(f"iOS Web 控制台已启动：{url}")
    print("=" * 60)
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_hotkey_daemon()


if __name__ == "__main__":
    main()
