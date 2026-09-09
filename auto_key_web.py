#!/usr/bin/env python3
"""
自动按键 Web 控制台 —— 模拟按键盘"1"或"2"键
- Web UI：选择按键（1/2）+ 开始/暂停/停止 + 间隔可调 + 实时计数
- 默认端口：8866
"""
import json
import os
import signal
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = 8866

try:
    from Quartz import (
        CGEventCreateKeyboardEvent,
        CGEventPost,
        kCGHIDEventTap,
    )
    QUARTZ_OK = True
except Exception:
    QUARTZ_OK = False

# Mac keyboard keycodes
KEY_CODES = {
    "1": 18,
    "2": 19,
}


def activate_iphone_mirroring():
    try:
        from Quartz import NSWorkspace
        ws = NSWorkspace.sharedWorkspace()
        target_names = {"iPhone Mirroring", "iPhone 镜像", "iPhone镜像", "iPhone鏡像輸出", "iPhoneミラーリング"}
        for app in ws.runningApplications():
            name = app.localizedName()
            if name and name in target_names:
                app.activateWithOptions_(1 << 1)
                return True
    except Exception:
        pass
    return False


def press_key(key_name: str) -> bool:
    if not QUARTZ_OK:
        return False
    keycode = KEY_CODES.get(key_name)
    if keycode is None:
        return False
    activate_iphone_mirroring()
    time.sleep(0.05)
    event_down = CGEventCreateKeyboardEvent(None, keycode, True)
    if event_down is not None:
        CGEventPost(kCGHIDEventTap, event_down)
    time.sleep(0.02)
    event_up = CGEventCreateKeyboardEvent(None, keycode, False)
    if event_up is not None:
        CGEventPost(kCGHIDEventTap, event_up)
    return True


class KeyState:
    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.paused = False
        self.interval = 3.0
        self.current_key = "2"
        self.count = 0
        self.session_count = 0
        self.started_at = None
        self.last_press_at = None
        self.error = ""

    def snapshot(self) -> dict:
        with self.lock:
            elapsed = 0.0
            if self.started_at and self.running:
                elapsed = round(time.time() - self.started_at, 1)
            return {
                "running": self.running,
                "paused": self.paused,
                "interval": self.interval,
                "current_key": self.current_key,
                "count": self.count,
                "session_count": self.session_count,
                "elapsed": elapsed,
                "last_press_at": self.last_press_at,
                "quartz_ok": QUARTZ_OK,
                "error": self.error,
            }


STATE = KeyState()


def key_loop():
    while True:
        with STATE.lock:
            if not STATE.running:
                return
            should_press = not STATE.paused
            interval = STATE.interval
            key = STATE.current_key

        if should_press:
            ok = press_key(key)
            with STATE.lock:
                if ok:
                    STATE.count += 1
                    STATE.session_count += 1
                    STATE.last_press_at = time.time()
                    STATE.error = ""
                elif QUARTZ_OK is False:
                    STATE.error = "Quartz 不可用，请 pip3 install pyobjc-framework-Quartz"

        steps = max(1, int(interval * 10))
        sleep_per_step = interval / steps
        for _ in range(steps):
            with STATE.lock:
                if not STATE.running:
                    return
            time.sleep(sleep_per_step)


_KEY_THREAD = None


def start_keys():
    global _KEY_THREAD
    with STATE.lock:
        if STATE.running:
            return False, "已经在运行中"
        STATE.running = True
        STATE.paused = False
        STATE.session_count = 0
        STATE.started_at = time.time()
        STATE.error = ""
        key = STATE.current_key
        interval = STATE.interval
    _KEY_THREAD = threading.Thread(target=key_loop, daemon=True)
    _KEY_THREAD.start()
    return True, f"已启动，每 {interval}s 按一次 {key}"


def stop_keys():
    with STATE.lock:
        STATE.running = False
        STATE.paused = False
    return True, "已停止"


def toggle_pause():
    with STATE.lock:
        if not STATE.running:
            return False, "尚未启动"
        STATE.paused = not STATE.paused
        return True, "已暂停" if STATE.paused else "已继续"


def set_interval(seconds: float):
    seconds = max(0.1, min(seconds, 3600.0))
    with STATE.lock:
        STATE.interval = seconds
    return True, f"间隔已设为 {seconds}s"


def set_key(key_name: str):
    key_name = str(key_name).strip()
    if key_name not in KEY_CODES:
        return False, f"不支持的按键: {key_name}（支持: {', '.join(KEY_CODES.keys())}）"
    with STATE.lock:
        STATE.current_key = key_name
    return True, f"当前按键设为 {key_name}"


def single_press_key(key_name: str):
    key_name = str(key_name).strip()
    if key_name not in KEY_CODES:
        return False, f"不支持的按键: {key_name}"
    with STATE.lock:
        STATE.current_key = key_name
    ok = press_key(key_name)
    with STATE.lock:
        if ok:
            STATE.count += 1
            STATE.session_count += 1
            STATE.last_press_at = time.time()
            return True, f"已按一次 {key_name}"
        return False, "按键失败：Quartz 不可用"


def single_press():
    with STATE.lock:
        key = STATE.current_key
    ok = press_key(key)
    with STATE.lock:
        if ok:
            STATE.count += 1
            STATE.session_count += 1
            STATE.last_press_at = time.time()
            return True, f"已手动按一次 {key}"
        return False, "按键失败：Quartz 不可用"


def check_permissions() -> dict:
    checks = {}
    if not QUARTZ_OK:
        checks["quartz"] = {
            "ok": False,
            "message": "未安装 Quartz，请运行：pip3 install pyobjc-framework-Quartz",
        }
    else:
        checks["quartz"] = {"ok": True, "message": "Quartz 已加载"}
    try:
        from Quartz import NSWorkspace
        ws = NSWorkspace.sharedWorkspace()
        front = ws.frontmostApplication()
        if front and front.bundleIdentifier():
            checks["accessibility"] = {"ok": True, "message": "辅助功能权限正常"}
        else:
            checks["accessibility"] = {"ok": False, "message": "无法获取前台应用，请授予辅助功能权限"}
    except Exception as e:
        checks["accessibility"] = {
            "ok": False,
            "message": f"辅助功能权限未授权：{e}",
            "fix_url": "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_Accessibility",
        }
    all_ok = all(c.get("ok") for c in checks.values())
    return {"ok": all_ok, "checks": checks}


HTML_PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>⌨️ 自动按键</title>
<style>
  :root{
    --bg:#fff8f5;--surface:#ffffff;--raised:#fffaf8;--border:#f2ebe4;--border-strong:#e8ddd2;
    --text:#3d3430;--text2:#8a7e74;--text3:#b8aaa0;
    --accent:#e8956a;--accent-h:#d98258;--accent-a:#c97048;--accent-soft:rgba(232,149,106,.12);
    --danger:#d4613a;--danger-soft:rgba(212,97,58,.08);
    --warn:#c78a2e;--ok:#5a9e6f;--ok-soft:rgba(90,158,111,.1);
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC",sans-serif;
       background:var(--bg);color:var(--text);min-height:100vh;
       display:flex;align-items:flex-start;justify-content:center;padding:20px 16px}
  .app{width:100%;max-width:380px}
  .hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}
  .hdr h1{font-size:15px;font-weight:700;display:flex;align-items:center;gap:7px}
  .hdr .logo{width:26px;height:26px;border-radius:8px;
    background:linear-gradient(135deg,var(--accent),var(--danger));
    display:flex;align-items:center;justify-content:center;font-size:13px;color:#fff}
  .pill{padding:3px 10px;border-radius:999px;font-size:11px;font-weight:600}
  .pill.idle{background:var(--border);color:var(--text2)}
  .pill.run{background:var(--ok-soft);color:var(--ok)}
  .pill.pause{background:rgba(199,138,46,.12);color:var(--warn)}

  .perm{font-size:11px;padding:7px 10px;border-radius:8px;margin-bottom:10px;
    border-left:3px solid var(--warn);background:rgba(199,138,46,.05);color:var(--text2);line-height:1.5}
  .perm.ok{border-left-color:var(--ok);background:var(--ok-soft);color:var(--ok)}
  .perm.err{border-left-color:var(--danger);background:var(--danger-soft);color:var(--danger)}
  .perm a{color:var(--accent);cursor:pointer;text-decoration:underline}

  .card{background:var(--surface);border:1px solid var(--border);border-radius:12px;
    padding:14px;margin-bottom:10px}
  .card-title{font-size:11px;color:var(--text2);font-weight:600;margin-bottom:10px;
    text-transform:uppercase;letter-spacing:.5px}

  .keys{display:flex;gap:8px}
  .key-btn{flex:1;padding:12px 0;border-radius:10px;border:2px solid var(--border);
    background:var(--raised);color:var(--text2);font-size:20px;font-weight:800;
    cursor:pointer;transition:all .12s;font-family:inherit}
  .key-btn:hover{border-color:var(--accent);color:var(--text)}
  .key-btn.active{border-color:var(--accent);background:var(--accent-soft);color:var(--accent)}
  .key-sub{display:block;font-size:9px;font-weight:500;margin-top:2px;color:var(--text3)}
  .key-btn.active .key-sub{color:var(--accent)}

  .stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
  .stat{background:var(--raised);border-radius:9px;padding:10px 6px;text-align:center}
  .stat .v{font-size:20px;font-weight:800;line-height:1.1}
  .stat .v.accent{color:var(--accent)}
  .stat .l{font-size:10px;color:var(--text2);margin-top:3px}

  .interval-row{display:flex;align-items:center;gap:8px}
  .interval-row label{font-size:12px;color:var(--text2);width:52px;flex-shrink:0}
  .interval-row input{flex:1;background:var(--raised);border:1px solid var(--border);
    color:var(--text);padding:7px 10px;border-radius:8px;font-size:13px;font-family:inherit;outline:none}
  .interval-row input:focus{border-color:var(--accent)}
  .interval-row .u{font-size:11px;color:var(--text2);width:20px}
  .chips{display:flex;gap:5px;margin-left:60px;margin-top:7px;flex-wrap:wrap}
  .chip{background:var(--raised);border:1px solid var(--border);color:var(--text2);
    padding:3px 9px;border-radius:999px;font-size:11px;cursor:pointer;transition:all .1s}
  .chip:hover{color:var(--accent);border-color:var(--accent)}

  .ctrls{display:grid;grid-template-columns:1fr 1fr;gap:7px}
  .ctrls .wide{grid-column:span 2}
  button{border:0;cursor:pointer;font-family:inherit;font-size:13px;font-weight:700;
    padding:11px;border-radius:9px;transition:transform .05s,filter .12s,opacity .12s}
  button:active{transform:scale(.97)}
  button:disabled{opacity:.35;cursor:not-allowed;transform:none}
  .btn-start{background:linear-gradient(135deg,var(--accent),var(--danger));color:#fff}
  .btn-start:hover:not(:disabled){filter:brightness(1.05)}
  .btn-pause{background:rgba(199,138,46,.12);color:var(--warn)}
  .btn-stop{background:var(--danger-soft);color:var(--danger)}
  .btn-press{background:var(--raised);color:var(--text2);border:1px solid var(--border);font-size:12px;font-weight:600}

  .hint{font-size:10px;color:var(--text3);line-height:1.6;margin-top:9px;text-align:center}
  .hint kbd{display:inline-block;padding:1px 6px;background:var(--raised);border:1px solid var(--border);
    border-radius:4px;font-family:ui-monospace,monospace;font-size:10px;color:var(--text2)}
  .toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:var(--text);
    color:#fff;padding:7px 16px;border-radius:8px;font-size:12px;opacity:0;transition:opacity .2s;
    pointer-events:none;z-index:99;white-space:nowrap}
  .toast.show{opacity:1}
</style>
</head>
<body>
<div class="app">
  <div class="hdr">
    <h1><div class="logo">⌨</div>自动按键</h1>
    <span id="pill" class="pill idle">空闲</span>
  </div>
  <div id="permWrap"></div>

  <div class="card">
    <div class="card-title">按键</div>
    <div class="keys">
      <button class="key-btn" data-key="1">1<span class="key-sub">L1 违规</span></button>
      <button class="key-btn active" data-key="2">2<span class="key-sub">L2 违规</span></button>
    </div>
  </div>

  <div class="card">
    <div class="card-title">统计</div>
    <div class="stats">
      <div class="stat"><div class="v accent" id="sCount">0</div><div class="l">本次</div></div>
      <div class="stat"><div class="v" id="tCount">0</div><div class="l">累计</div></div>
      <div class="stat"><div class="v" id="elapsed">—</div><div class="l">时长</div></div>
    </div>
  </div>

  <div class="card">
    <div class="card-title">间隔</div>
    <div class="interval-row">
      <label>每隔</label>
      <input id="interval" type="number" step="0.1" min="0.1" max="3600" value="3.0" />
      <span class="u">秒</span>
    </div>
    <div class="chips">
      <span class="chip" data-v="1">1s</span>
      <span class="chip" data-v="2">2s</span>
      <span class="chip" data-v="3">3s</span>
      <span class="chip" data-v="5">5s</span>
    </div>
  </div>

  <div class="card">
    <div class="ctrls">
      <button id="startBtn" class="btn-start wide">▶ 开始按 2</button>
      <button id="pauseBtn" class="btn-pause" disabled>⏸ 暂停</button>
      <button id="stopBtn" class="btn-stop" disabled>■ 停止</button>
      <button id="pressBtn" class="btn-press wide">👆 手动按一次 2</button>
    </div>
    <p class="hint">快捷键 <kbd>空格</kbd> 暂停/继续 · 按键前自动激活 iPhone 镜像</p>
  </div>
</div>
<div id="toast" class="toast"></div>

<script>
const $=id=>document.getElementById(id);
const pill=$('pill'),toastEl=$('toast');
let curKey='2';

function fmtTime(s){
  s=Math.floor(s);
  if(s<60)return s+'s';
  const m=Math.floor(s/60),r=s%60;
  if(m<60)return m+'m'+(r?r+'s':'');
  return Math.floor(m/60)+'h'+(m%60)+'m';
}
function toast(msg){
  toastEl.textContent=msg;toastEl.classList.add('show');
  clearTimeout(toast._t);toast._t=setTimeout(()=>toastEl.classList.remove('show'),1600);
}
async function api(path,method='GET',body){
  const opt={method};
  if(body){opt.headers={'Content-Type':'application/json'};opt.body=JSON.stringify(body)}
  const r=await fetch(path,opt);return await r.json();
}
function keyLabel(k){return k==='1'?'L1 违规':'L2 违规'}

async function render(){
  const s=await api('/api/status');
  $('sCount').textContent=s.session_count.toLocaleString();
  $('tCount').textContent=s.count.toLocaleString();
  $('elapsed').textContent=s.running?fmtTime(s.elapsed):'—';
  $('interval').value=s.interval;
  curKey=s.current_key;
  document.querySelectorAll('.key-btn').forEach(b=>b.classList.toggle('active',b.dataset.key===curKey));
  const label=keyLabel(curKey);
  $('pressBtn').textContent=`👆 手动按一次 ${curKey}`;
  if(!s.running){
    pill.className='pill idle';pill.textContent='空闲';
    $('startBtn').disabled=false;$('startBtn').textContent=`▶ 开始按 ${curKey}`;
    $('pauseBtn').disabled=true;$('stopBtn').disabled=true;
  }else if(s.paused){
    pill.className='pill pause';pill.textContent='⏸ 暂停';
    $('startBtn').disabled=true;
    $('pauseBtn').disabled=false;$('pauseBtn').textContent='▶ 继续';
    $('stopBtn').disabled=false;
  }else{
    pill.className='pill run';pill.textContent='运行中';
    $('startBtn').disabled=true;
    $('pauseBtn').disabled=false;$('pauseBtn').textContent='⏸ 暂停';
    $('stopBtn').disabled=false;
  }
  const p=await api('/api/permissions');
  const wrap=$('permWrap');wrap.innerHTML='';
  if(!p.ok){
    Object.entries(p.checks).forEach(([k,c])=>{
      if(c.ok)return;
      const el=document.createElement('div');el.className='perm err';
      el.innerHTML=`<b>${k==='quartz'?'Quartz':'辅助功能'}</b>：${c.message}`+
        (c.fix_url?` <a onclick="location.href='${c.fix_url}'">修复→</a>`:'');
      wrap.appendChild(el);
    });
  }
}

$('startBtn').onclick=async()=>{const r=await api('/api/start','POST');toast(r.message);render()};
$('pauseBtn').onclick=async()=>{const r=await api('/api/pause','POST');toast(r.message);render()};
$('stopBtn').onclick=async()=>{const r=await api('/api/stop','POST');toast(r.message);render()};
$('pressBtn').onclick=async()=>{const r=await api('/api/press','POST');toast(r.message);render()};
$('interval').addEventListener('change',async e=>{
  const v=parseFloat(e.target.value);if(isNaN(v))return;
  const r=await api('/api/interval','POST',{value:v});toast(r.message);render();
});
document.querySelectorAll('.chip').forEach(c=>c.onclick=()=>{
  $('interval').value=c.dataset.v;$('interval').dispatchEvent(new Event('change'));
});
// 选键仅切换，不立即按
document.querySelectorAll('.key-btn').forEach(b=>b.onclick=async()=>{
  const k=b.dataset.key;
  const r=await api('/api/key','POST',{key:k});
  toast(r.message);render();
});
document.addEventListener('keydown',e=>{
  if(e.code==='Space'&&e.target.tagName!=='INPUT'){e.preventDefault();$('pauseBtn').click()}
});
render();setInterval(render,1000);
</script>
</body>
</html>"""

MINI_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AutoKey</title>
  <style>
  * { margin:0; padding:0; box-sizing:border-box; -webkit-user-select:none; user-select:none; }
  html, body { width:280px; height:220px; overflow:hidden; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", sans-serif;
    background: rgba(255,250,248,0.95);
  }
  #miniWindow { width:100%; height:100%; display:flex; flex-direction:column; }
  #header {
    height:26px; flex-shrink:0; display:flex; align-items:center; padding:0 8px; gap:5px;
    background: rgba(255,255,255,0.7); border-bottom: 0.5px solid rgba(0,0,0,0.06); cursor:default;
  }
  .dot { width:6px; height:6px; border-radius:50%; flex-shrink:0; }
  .dot.idle { background:#b0b0b0; }
  .dot.run { background:#4caf50; animation: pulse 0.8s infinite; }
  .dot.pause { background:#f5a623; }
  @keyframes pulse { 0%,100%{opacity:1;} 50%{opacity:0.35;} }
  #statusText {
    flex:1; font-size:10px; font-weight:600; color:#888;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
  }
  #countText { font-size:10px; font-weight:700; color:#666; }
  #openMainBtn {
    font-size:10px; color:#aaa; background:none; border:0; cursor:pointer;
    padding:2px 4px; border-radius:3px; font-family:inherit; margin-left:4px;
  }
  #openMainBtn:hover { background:rgba(0,0,0,0.06); color:#666; }
  #buttonArea {
    flex:1; display:grid; grid-template-columns:1fr 1fr; gap:5px; padding:5px;
  }
  .mini-btn {
    display:flex; flex-direction:column; align-items:center; justify-content:center; gap:2px;
    border:0; border-radius:8px; cursor:pointer; font-family:inherit; padding:4px 2px;
    transition: transform 0.08s ease, filter 0.08s ease;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06), inset 0 0 0 0.5px rgba(255,255,255,0.7);
  }
  .mini-btn:active { transform:scale(0.93); }
  .mini-btn.flash { animation: flash 0.25s ease; }
  @keyframes flash { 0%{filter:brightness(1);} 50%{filter:brightness(1.35);} 100%{filter:brightness(1);} }
  .mini-btn .key { font-size:22px; font-weight:800; line-height:1; }
  .mini-btn .label { font-size:9px; font-weight:600; line-height:1.2; opacity:0.72; letter-spacing:0.02em; }
  .cat-key { background:linear-gradient(180deg,#eef3ff,#d4e0fd); color:#2e6be8; }
  #ctrlBar {
    flex-shrink:0; display:grid; grid-template-columns:repeat(3,1fr); gap:4px; padding:0 5px 5px 5px;
  }
  .ctrl-btn {
    border:0; border-radius:6px; cursor:pointer; font-family:inherit;
    font-size:9px; font-weight:700; padding:4px 2px;
    display:flex; align-items:center; justify-content:center; gap:2px;
    transition: transform 0.08s ease, filter 0.08s ease;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
  }
  .ctrl-btn:active { transform:scale(0.93); }
  .ctrl-btn:disabled { opacity:0.4; cursor:not-allowed; }
  .ctrl-btn.on { background:linear-gradient(180deg,#e8f5e9,#c8e6c9); color:#2e7d32; }
  .ctrl-btn.off { background:linear-gradient(180deg,#fff8e1,#ffecb3); color:#e65100; }
  .ctrl-btn.stop { background:linear-gradient(180deg,#ffebee,#ffcdd2); color:#c62828; }
  #toast {
    position:fixed; bottom:0; left:0; right:0; padding:3px 8px; font-size:10px; font-weight:600;
    text-align:center; background:rgba(0,0,0,0.75); color:#fff;
    transition:opacity 0.25s, transform 0.25s; transform:translateY(100%); pointer-events:none;
  }
  #toast.show { transform:translateY(0); }
  </style>
</head>
<body>
  <div id="miniWindow">
    <div id="header">
      <span id="statusDot" class="dot idle"></span>
      <span id="statusText">空闲</span>
      <span id="countText">0</span>
      <button id="openMainBtn" title="打开主界面">◧</button>
    </div>
    <div id="buttonArea">
      <button class="mini-btn cat-key" data-key="1" id="btn1"><span class="key">1</span><span class="label">按键</span></button>
      <button class="mini-btn cat-key" data-key="2" id="btn2"><span class="key">2</span><span class="label">按键</span></button>
    </div>
    <div id="ctrlBar">
      <button class="ctrl-btn on" id="startBtn">▶ 开始</button>
      <button class="ctrl-btn off" id="pauseBtn" disabled>⏸ 暂停</button>
      <button class="ctrl-btn stop" id="stopBtn" disabled>■ 停止</button>
    </div>
    <div id="toast"></div>
  </div>
<script>
const $ = id => document.getElementById(id);
let toastT;
function toast(msg){
  const t=$('toast'); t.textContent=msg; t.className='show';
  clearTimeout(toastT); toastT=setTimeout(()=>t.className='',1500);
}
async function api(path,method='GET',body){
  const opt={method};
  if(body){opt.headers={'Content-Type':'application/json'};opt.body=JSON.stringify(body)}
  const r=await fetch(path,opt); return await r.json();
}
async function render(){
  const s=await api('/api/status');
  $('countText').textContent=s.session_count;
  const dot=$('statusDot'), st=$('statusText');
  if(!s.running){
    dot.className='dot idle'; st.textContent='空闲';
    $('startBtn').disabled=false; $('pauseBtn').disabled=true; $('stopBtn').disabled=true;
  } else if(s.paused){
    dot.className='dot pause'; st.textContent='暂停';
    $('startBtn').disabled=true; $('pauseBtn').disabled=false; $('stopBtn').disabled=false;
    $('pauseBtn').textContent='▶ 继续';
  } else {
    dot.className='dot run'; st.textContent='按'+s.current_key+'·'+s.interval+'s';
    $('startBtn').disabled=true; $('pauseBtn').disabled=false; $('stopBtn').disabled=false;
    $('pauseBtn').textContent='⏸ 暂停';
  }
}
$('openMainBtn').onclick=()=>{ window.open('/','_blank'); };
document.querySelectorAll('.mini-btn').forEach(b=>{
  b.onclick=async()=>{
    const k=b.dataset.key;
    const r=await api('/api/press-key','POST',{key:k});
    b.classList.remove('flash'); void b.offsetWidth; b.classList.add('flash');
    toast(r.message); render();
  };
});
$('startBtn').onclick=async()=>{ const r=await api('/api/start','POST'); toast(r.message); render(); };
$('pauseBtn').onclick=async()=>{ const r=await api('/api/pause','POST'); toast(r.message); render(); };
$('stopBtn').onclick=async()=>{ const r=await api('/api/stop','POST'); toast(r.message); render(); };
document.addEventListener('keydown',e=>{
  if(e.code==='Space'){e.preventDefault(); $('pauseBtn').click();}
});
render();
setInterval(render,800);
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/status":
            self.send_json(STATE.snapshot())
            return
        if self.path == "/api/permissions":
            self.send_json(check_permissions())
            return
        if self.path in ("/", "/index.html"):
            body = HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path in ("/mini", "/mini.html"):
            body = MINI_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_json({"ok": False, "message": "not found"}, status=404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = {}
        if length:
            payload = json.loads(self.rfile.read(length) or b"{}")

        routes = {
            "/api/start": lambda: start_keys(),
            "/api/stop":  lambda: stop_keys(),
            "/api/pause": lambda: toggle_pause(),
            "/api/press": lambda: single_press(),
            "/api/press-key": lambda: single_press_key(payload.get("key", "2")),
            "/api/interval": lambda: set_interval(float(payload.get("value", 3.0))),
            "/api/key": lambda: set_key(payload.get("key", "2")),
        }
        handler = routes.get(self.path)
        if not handler:
            self.send_json({"ok": False, "message": "not found"}, status=404)
            return
        try:
            ok, message = handler()
            self.send_json({"ok": ok, "message": message})
        except Exception as e:
            self.send_json({"ok": False, "message": f"错误: {e}"}, status=500)

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


def main():
    print("=" * 56)
    print("⌨️  自动按键 Web 控制台")
    print("=" * 56)

    perm = check_permissions()
    if not perm["ok"]:
        print("\n⚠️  环境问题：")
        for name, c in perm["checks"].items():
            if not c["ok"]:
                label = "Quartz 依赖" if name == "quartz" else "辅助功能权限"
                print(f"  ✗ {label}：{c['message']}")
        if not QUARTZ_OK:
            print("\n  → 请运行：pip3 install pyobjc-framework-Quartz")
        print()
    else:
        print("✓ 环境检查通过\n")

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)

    def shutdown_handler(signum, frame):
        print("\n正在关闭...")
        with STATE.lock:
            STATE.running = False
        server.shutdown()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    url = f"http://127.0.0.1:{PORT}/"
    print(f"已启动：{url}")
    print("=" * 56)
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
