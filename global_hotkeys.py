#!/usr/bin/env python3
"""
Global hotkey daemon for TikTok console.
Uses Quartz CGEventTap for reliable global key capture (no pynput dependency).
Listens for 1/2/3/4 keys globally and forwards to Flask backend.
When a browser is frontmost, skips (lets the web page handle it natively).
1=Credible Threat of Suicide, 2=Suicide&NSSI, 3=Suicide&NSSI-severe, 4=不违规
"""
import json
import sys
import os
import time
import threading
import signal
import urllib.request
import urllib.error
import subprocess
import ctypes

from Quartz import (
    NSWorkspace,
    CGEventTapCreate,
    CGEventTapEnable,
    kCGHIDEventTap,
    kCGHeadInsertEventTap,
    kCGEventTapOptionListenOnly,
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CFRunLoopRun,
    CFRunLoopStop,
    kCFRunLoopCommonModes,
    CGEventGetIntegerValueField,
    kCGEventKeyDown,
    kCGKeyboardEventKeycode,
    CFMachPortCreateRunLoopSource,
)
from Quartz.CoreGraphics import CGEventMaskBit

API_URL = "http://127.0.0.1:8880/api/action"
HEALTH_URL = "http://127.0.0.1:8880/api/status"
PING_INTERVAL = 3

BROWSER_BUNDLES = {
    "com.apple.Safari",
    "com.google.Chrome",
    "com.google.Chrome.canary",
    "com.brave.Browser",
    "com.microsoft.Edg",
    "org.mozilla.firefox",
    "company.thebrowser.Browser",
    "com.vivaldi.Vivaldi",
    "com.operasoftware.Opera",
    "com.apple.SafariTechnologyPreview",
}

KEY_CODE_TO_CATEGORY = {
    18: "1",
    19: "2",
    20: "3",
    21: "4",
    83: "1",
    84: "2",
    85: "3",
    86: "4",
}

_daemon_running = True
_last_action_time = 0
_cooldown = 0.3
_ping_thread = None


def frontmost_bundle_id():
    ws = NSWorkspace.sharedWorkspace()
    app = ws.frontmostApplication()
    if app:
        return app.bundleIdentifier()
    return None


def is_browser_frontmost():
    return frontmost_bundle_id() in BROWSER_BUNDLES


def play_feedback(success=True):
    pass


def send_action(category_id):
    global _last_action_time
    now = time.time()
    if now - _last_action_time < _cooldown:
        return
    _last_action_time = now
    try:
        data = json.dumps({"action": f"category:{category_id}"}).encode()
        req = urllib.request.Request(
            API_URL,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            result = json.loads(resp.read().decode())
            ok = result.get("ok", False)
            play_feedback(ok)
            if ok:
                print(f"[hotkey] {category_id} -> OK", flush=True)
            else:
                msg = result.get("message", "fail")
                print(f"[hotkey] {category_id} -> {msg}", flush=True)
                play_feedback(False)
    except urllib.error.URLError:
        print("[hotkey] backend not reachable", flush=True)
    except Exception as e:
        print(f"[hotkey] error: {e}", flush=True)


def event_callback(proxy, type_, event, refcon):
    try:
        keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
        category_id = KEY_CODE_TO_CATEGORY.get(int(keycode))
        if category_id is None:
            return event
        if is_browser_frontmost():
            return event
        send_action(category_id)
    except Exception as e:
        print(f"[hotkey] callback error: {e}", flush=True)
    return event


def health_ping_loop():
    while _daemon_running:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=2) as resp:
                pass
        except Exception:
            pass
        time.sleep(PING_INTERVAL)


def signal_handler(signum, frame):
    global _daemon_running
    print("[hotkey] signal received, stopping...", flush=True)
    _daemon_running = False
    try:
        runloop = CFRunLoopGetCurrent()
        if runloop:
            CFRunLoopStop(runloop)
    except Exception:
        pass
    sys.exit(0)


def main():
    global _ping_thread

    print("[hotkey] daemon starting (Quartz CGEventTap)...", flush=True)
    print("[hotkey] listening for keys: 1,2,3,4 (keycodes 18,19,20,21 / 83,84,85,86)", flush=True)
    print(f"[hotkey] will skip when browser is frontmost", flush=True)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    print("[hotkey] waiting for backend to be ready...", flush=True)
    backend_ready = False
    for _ in range(50):
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=1) as resp:
                backend_ready = True
                break
        except Exception:
            time.sleep(0.2)
    if not backend_ready:
        print("[hotkey] WARNING: backend not responding, starting anyway...", flush=True)
    else:
        print("[hotkey] backend ready", flush=True)

    _ping_thread = threading.Thread(target=health_ping_loop, daemon=True)
    _ping_thread.start()

    event_mask = CGEventMaskBit(kCGEventKeyDown)

    tap = CGEventTapCreate(
        kCGHIDEventTap,
        kCGHeadInsertEventTap,
        kCGEventTapOptionListenOnly,
        event_mask,
        event_callback,
        None,
    )

    if tap is None:
        print("[hotkey] ERROR: CGEventTap creation failed - need accessibility permission", flush=True)
        print("[hotkey] Go to System Settings -> Privacy & Security -> Accessibility", flush=True)
        time.sleep(5)
        return

    runloop_source = CFMachPortCreateRunLoopSource(None, tap, 0)
    runloop = CFRunLoopGetCurrent()
    CFRunLoopAddSource(runloop, runloop_source, kCFRunLoopCommonModes)
    CGEventTapEnable(tap, True)

    print("[hotkey] ready", flush=True)

    try:
        CFRunLoopRun()
    except KeyboardInterrupt:
        pass
    finally:
        _daemon_running = False
        print("[hotkey] stopped", flush=True)


if __name__ == "__main__":
    main()
