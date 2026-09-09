const macroLabels = {
  normal_triple: "违规三连",
  normal_quad: "违规四连",
  normal_safe: "不违规",
  raised_triple: "违规三连",
  raised_quad: "违规四连",
  raised_safe: "不违规",
};

const recordFeedKeys = ["normal_triple", "normal_quad", "normal_safe"];
const recordSearchKeys = ["raised_triple", "raised_quad", "raised_safe"];

let categories = [];
let currentDomain = "";

const el = {
  recording: document.querySelector("#recording"),
  status: document.querySelector("#status"),
  statusDetail: document.querySelector("#statusDetail"),
  statusDetailBtn: document.querySelector("#statusDetailButton"),
  statusModal: document.querySelector("#statusModal"),
  statusModalClose: document.querySelector("#statusModalClose"),
  consoleTitle: document.querySelector("#consoleTitle"),
  macroStrip: document.querySelector("#macroStrip"),
  busyPill: document.querySelector("#busyPill"),
  categoryButtons: document.querySelector("#categoryButtons"),
  recordFeedGrid: document.querySelector("#recordFeedGrid"),
  recordSearchGrid: document.querySelector("#recordSearchGrid"),
  rowInput: document.querySelector("#rowInput"),
  rowButton: document.querySelector("#rowButton"),
  permBanner: document.querySelector("#permBanner"),
  permTitle: document.querySelector("#permTitle"),
  permList: document.querySelector("#permList"),
  permFixBtn: document.querySelector("#permFixBtn"),
  permCloseBtn: document.querySelector("#permCloseBtn"),
  pageModeLabel: document.querySelector("#pageModeLabel"),
  miniBtn: document.querySelector("#miniBtn"),
  toast: document.querySelector("#toast"),
  statsBtn: document.querySelector("#statsBtn"),
  statsModal: document.querySelector("#statsModal"),
  statsModalClose: document.querySelector("#statsModalClose"),
  statsContent: document.querySelector("#statsContent"),
  globalKeyBadge: document.querySelector("#globalKeyBadge"),
  startBtn: document.querySelector("#startBtn"),
  pauseBtn: document.querySelector("#pauseBtn"),
  controlStatus: document.querySelector("#controlStatus"),
  controlBar: document.querySelector("#controlBar"),
};

const permLabels = {
  accessibility: "辅助功能权限",
  lark_cli: "飞书CLI",
  mirroring: "iPhone镜像",
  config: "配置文件",
};

let permDismissed = false;

/* ─── Sound Engine (Web Audio API, zero dependencies) ─── */
let audioCtx = null;
let soundEnabled = false;

function getAudioCtx() {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  if (audioCtx.state === "suspended") {
    audioCtx.resume();
  }
  return audioCtx;
}

function playTone(freq, duration, type = "sine", volume = 0.08) {
  if (!soundEnabled) return;
  try {
    const ctx = getAudioCtx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, ctx.currentTime);
    gain.gain.setValueAtTime(0, ctx.currentTime);
    gain.gain.linearRampToValueAtTime(volume, ctx.currentTime + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(ctx.currentTime);
    osc.stop(ctx.currentTime + duration);
  } catch (_) {}
}

const sfx = {
  click: () => {
    playTone(800, 0.06, "sine", 0.06);
    setTimeout(() => playTone(1200, 0.04, "sine", 0.04), 15);
  },
  confirm: () => {
    playTone(600, 0.08, "sine", 0.07);
    setTimeout(() => playTone(900, 0.1, "sine", 0.06), 60);
  },
  error: () => {
    playTone(300, 0.15, "triangle", 0.08);
    setTimeout(() => playTone(220, 0.2, "triangle", 0.06), 80);
  },
  soft: () => {
    playTone(500, 0.05, "sine", 0.04);
  },
};

/* ─── Toast ─── */
let toastTimer = null;
function showToast(msg, ms = 1600) {
  el.toast.textContent = msg;
  el.toast.classList.remove("hidden");
  requestAnimationFrame(() => el.toast.classList.add("show"));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    el.toast.classList.remove("show");
    setTimeout(() => el.toast.classList.add("hidden"), 300);
  }, ms);
}

/* ─── Permissions ─── */
function renderPermissions(permissions) {
  if (!permissions || permissions.ok) {
    el.permBanner.classList.add("hidden");
    return;
  }
  if (permDismissed) return;
  const issues = Object.entries(permissions.checks || {}).filter(([, c]) => !c.ok);
  if (issues.length === 0) { el.permBanner.classList.add("hidden"); return; }
  el.permList.innerHTML = "";
  issues.forEach(([key, c]) => {
    const li = document.createElement("li");
    li.innerHTML = `<strong>${permLabels[key] || key}</strong>：${c.message || "检测失败"}`;
    el.permList.appendChild(li);
  });
  el.permTitle.textContent = `环境检测发现 ${issues.length} 个问题`;
  el.permBanner.classList.remove("hidden");
}

el.permFixBtn?.addEventListener("click", async () => {
  el.permFixBtn.disabled = true;
  el.permFixBtn.textContent = "修复中...";
  sfx.soft();
  try {
    const resp = await fetch("/api/fix-permissions", { method: "POST" });
    const data = await resp.json();
    if (data.fixes?.length > 0) {
      el.permTitle.textContent = "已执行修复操作，请检查：";
      el.permList.innerHTML = "";
      data.fixes.forEach((f) => {
        const li = document.createElement("li");
        li.textContent = "→ " + f;
        el.permList.appendChild(li);
      });
      sfx.confirm();
    } else {
      el.permTitle.textContent = "已尝试自动修复，部分问题需手动处理";
    }
    setTimeout(refreshStatus, 2000);
  } catch (e) {
    el.permTitle.textContent = `修复请求失败：${e}`;
    sfx.error();
  } finally {
    el.permFixBtn.disabled = false;
    el.permFixBtn.textContent = "重新检测";
  }
});

el.permCloseBtn?.addEventListener("click", () => {
  el.permBanner.classList.add("hidden");
  permDismissed = true;
  sfx.soft();
});

/* ─── Button Factory ─── */
function makeButton(label, action, onClick) {
  const button = document.createElement("button");
  button.textContent = label;
  button.dataset.action = action;
  const handler = onClick || (() => runAction(action));
  button.addEventListener("click", (e) => {
    sfx.click();
    handler(e);
  });
  return button;
}

/* ─── Build Record Buttons ─── */
function buildMacroButtons() {
  recordFeedKeys.forEach((key) => {
    const label = macroLabels[key];
    el.recordFeedGrid.appendChild(makeButton(label, `record:${key}`));
  });
  recordSearchKeys.forEach((key) => {
    const label = macroLabels[key];
    el.recordSearchGrid.appendChild(makeButton(label, `record:${key}`));
  });
}

/* ─── Build Category Buttons (domain-driven) ─── */
function buildCategoryButtons() {
  el.categoryButtons.innerHTML = "";
  el.categoryButtons.style.gridTemplateColumns = `repeat(${Math.max(categories.length, 1)}, 1fr)`;
  categories.forEach((cat) => {
    const id = String(cat.key);
    const label = cat.label;
    const button = document.createElement("button");
    button.className = `category-button cc-${cat.color || "blue"}`;
    button.dataset.key = id;
    button.dataset.action = `category:${id}`;
    button.setAttribute("aria-label", `${id} ${label}`);
    button.setAttribute("title", cat.policy ? `${label}：${cat.policy}` : `快捷键：${id}`);

    const number = document.createElement("strong");
    number.textContent = id;
    const text = document.createElement("span");
    text.textContent = label;
    button.append(number, text);

    button.addEventListener("mousedown", (e) => {
      const rect = button.getBoundingClientRect();
      button.style.setProperty("--rx", `${((e.clientX - rect.left) / rect.width) * 100}%`);
      button.style.setProperty("--ry", `${((e.clientY - rect.top) / rect.height) * 100}%`);
    });

    button.addEventListener("click", () => {
      sfx.click();
      runAction(button.dataset.action);
    });

    el.categoryButtons.appendChild(button);
  });
}

function applyDomain(data) {
  const next = Array.isArray(data.categories) ? data.categories : [];
  const nextDomain = data.current_domain || "";
  const sig = nextDomain + "|" + next.map((c) => `${c.key}:${c.label}`).join(",");
  const prevSig = currentDomain + "|" + categories.map((c) => `${c.key}:${c.label}`).join(",");
  currentDomain = nextDomain;
  categories = next;
  document.querySelectorAll("[data-domain]").forEach((btn) => {
    const isActive = btn.dataset.domain === currentDomain;
    btn.classList.toggle("active", isActive);
    btn.setAttribute("aria-selected", isActive);
  });
  if (sig !== prevSig) buildCategoryButtons();
}

/* ─── Actions ─── */
async function runAction(action) {
  setButtonsDisabled(true);
  try {
    const response = await fetch("/api/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    const data = await response.json();
    if (!data.ok) {
      el.status.textContent = data.message || "操作失败";
      sfx.error();
      showToast(data.message || "操作失败");
    } else {
      sfx.confirm();
    }
    await refreshStatus();
  } catch (error) {
    el.status.textContent = `请求失败：${error}`;
    sfx.error();
  } finally {
    setButtonsDisabled(false);
  }
}

async function switchProfile(profile) {
  await runAction(`profile:${profile}`);
}

function setButtonsDisabled(disabled) {
  document.querySelectorAll("button").forEach((button) => {
    if (button.dataset.action === "stop_recording") return;
    if (button.dataset.action === "start" || button.dataset.action === "pause") return;
    button.disabled = disabled;
  });
}

/* ─── Render Macros ─── */
function renderMacros(macros) {
  el.macroStrip.innerHTML = "";
  macros.forEach((macro) => {
    const chip = document.createElement("span");
    chip.className = `chip ${macro.recorded ? "done" : ""} ${macro.active ? "active" : ""}`;
    const prefix = macro.page === "feed" ? "📱" : "🔍";
    chip.textContent = macro.recorded
      ? `${prefix} ${macro.short_label} · ${macro.count}点`
      : `${prefix} ${macro.short_label} · 未录`;
    el.macroStrip.appendChild(chip);
  });
}

function summarizeStatus(status) {
  if (!status) return "";
  const withoutLink = status.replace(/；链接=.*/, "");
  const sheetMatch = withoutLink.match(/飞书写入成功：第\s*\d+\s*行/);
  if (sheetMatch) return sheetMatch[0];
  const staleMatch = withoutLink.match(/剪贴板仍是上一条链接，未写入飞书，请重试/);
  if (staleMatch) return staleMatch[0];
  const errorMatch = withoutLink.match(/ERROR:[^；]+/);
  if (errorMatch) return errorMatch[0];
  return withoutLink.length > 40 ? `${withoutLink.slice(0, 40)}...` : withoutLink;
}

/* ─── Refresh Status ─── */
async function refreshStatus() {
  try {
    const response = await fetch("/api/status");
    const data = await response.json();
    applyDomain(data);
    if (data.console) {
      el.consoleTitle.textContent = data.console.title;
      document.title = `${data.console.title}`;
    }
    el.recording.textContent = data.recording;
    const summarized = summarizeStatus(data.status);
    if (el.status.textContent !== summarized) {
      el.status.textContent = summarized;
      el.status.classList.add("updated");
      setTimeout(() => el.status.classList.remove("updated"), 400);
    }
    el.status.title = data.status;
    el.statusDetail.textContent = data.status;
    el.busyPill.textContent = data.busy ? `${data.current}中` : (data.paused ? "已暂停" : "养号中");
    el.busyPill.classList.toggle("busy", data.busy);
    el.busyPill.classList.toggle("paused", data.paused && !data.busy);
    el.busyPill.classList.toggle("running", !data.paused && !data.busy);
    renderMacros(data.macros);
    if (document.activeElement !== el.rowInput) {
      el.rowInput.value = data.sheet.current_row;
    }
    document.querySelectorAll("[data-profile]").forEach((button) => {
      button.classList.toggle("active", button.dataset.profile === data.profile.key);
      button.setAttribute("aria-selected", button.dataset.profile === data.profile.key);
    });
    const pageLabels = data.page_modes || {};
    if (el.pageModeLabel && data.page_mode) {
      el.pageModeLabel.textContent = pageLabels[data.page_mode]
        ? `${pageLabels[data.page_mode]} 模式`
        : data.page_mode;
    }
    document.querySelectorAll("[data-page-mode]").forEach((button) => {
      const isActive = button.dataset.pageMode === data.page_mode;
      button.classList.toggle("active", isActive);
      button.setAttribute("aria-selected", isActive);
    });
    renderPermissions(data.permissions);
    if (el.globalKeyBadge) {
      const gk = data.global_hotkeys || {};
      el.globalKeyBadge.classList.remove("on", "off");
      if (gk.running) {
        el.globalKeyBadge.classList.add("on");
        el.globalKeyBadge.title = "全局快捷键已启用：1/2/3/4 任意窗口可用";
      } else {
        el.globalKeyBadge.classList.add("off");
        el.globalKeyBadge.title = "全局快捷键未运行，仅浏览器焦点时可用";
      }
    }
    if (el.startBtn && el.pauseBtn && el.controlStatus) {
      if (data.paused) {
        el.startBtn.classList.remove("hidden");
        el.pauseBtn.classList.add("hidden");
        el.controlBar.classList.remove("running");
        el.controlBar.classList.add("paused");
        el.controlStatus.textContent = data.busy ? "启动中..." : "已暂停，点「开始养号」继续";
      } else {
        el.startBtn.classList.add("hidden");
        el.pauseBtn.classList.remove("hidden");
        el.controlBar.classList.add("running");
        el.controlBar.classList.remove("paused");
        el.controlStatus.textContent = data.busy
          ? `${data.current}中...`
          : `养号中（${(data.domains && data.domains[data.current_domain]?.label) || ""}），按 ${categories.map((c) => `${c.key}=${c.label}`).join(" / ")}`;
      }
    }
    document.querySelectorAll(".category-button").forEach((btn) => {
      btn.classList.toggle("disabled", data.paused && !data.busy);
    });
  } catch (e) {
    el.status.textContent = "连接断开，重试中...";
  }
}

/* ─── Event Delegation ─── */
document.querySelectorAll("[data-action]").forEach((button) => {
  if (!button.classList.contains("category-button")) {
    button.addEventListener("click", () => {
      sfx.click();
      runAction(button.dataset.action);
    });
  }
});

document.querySelectorAll("[data-profile]").forEach((button) => {
  button.addEventListener("click", () => {
    sfx.click();
    switchProfile(button.dataset.profile);
  });
});

document.querySelectorAll("[data-page-mode]").forEach((button) => {
  button.addEventListener("click", async () => {
    sfx.click();
    await runAction(`page_mode:${button.dataset.pageMode}`);
  });
});

document.querySelectorAll("[data-domain]").forEach((button) => {
  button.addEventListener("click", async () => {
    if (button.classList.contains("active")) return;
    sfx.confirm();
    await runAction(`domain:${button.dataset.domain}`);
    showToast(`已切换到 ${button.textContent} 领域`);
  });
});

el.miniBtn?.addEventListener("click", () => {
  sfx.soft();
  const w = 340, h = 220;
  const left = (window.screen.width - w) / 2;
  const top = (window.screen.height - h) / 2;
  window.open("/mini.html", "tiktok_mini",
    `width=${w},height=${h},left=${left},top=${top},resizable=no,scrollbars=no,toolbar=no,menubar=no,location=no,status=no,alwaysRaised=yes`);
});

el.rowButton.addEventListener("click", () => {
  const row = Number(el.rowInput.value);
  if (!Number.isFinite(row) || row < 1) {
    el.status.textContent = "请输入有效行号";
    sfx.error();
    showToast("请输入有效行号");
    return;
  }
  sfx.click();
  runAction(`row:${Math.floor(row)}`);
});

el.rowInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") el.rowButton.click();
});

el.statusDetailBtn.addEventListener("click", () => {
  sfx.soft();
  el.statusModal.classList.remove("hidden");
});

el.statusModalClose.addEventListener("click", () => {
  sfx.soft();
  el.statusModal.classList.add("hidden");
});

el.statusModal.addEventListener("click", (event) => {
  if (event.target === el.statusModal) el.statusModal.classList.add("hidden");
});

/* ─── Stats ─── */
async function loadStats() {
  el.statsContent.innerHTML = '<p class="stats-loading">正在读取飞书表格...</p>';
  el.statsModal.classList.remove("hidden");
  sfx.soft();
  try {
    const resp = await fetch("/api/stats");
    const data = await resp.json();
    if (!data.ok) {
      el.statsContent.innerHTML = `<p class="stats-error">❌ ${data.error}</p>`;
      sfx.error();
      return;
    }
    const termsStr = Object.entries(data.search_terms || {})
      .map(([k, v]) => `${k}(${v}条)`).join("、") || "无";
    const policiesStr = Object.entries(data.policies || {})
      .map(([k, v]) => `${k}: ${v}条`).join("<br>") || "无";
    const intersStr = Object.entries(data.interactions || {})
      .map(([k, v]) => `${k}×${v}`).join("、") || "无";

    el.statsContent.innerHTML = `
      <div class="stats-grid">
        <div class="stats-item big">
          <span class="stats-val">${data.total}</span>
          <span class="stats-label">总记录</span>
        </div>
        <div class="stats-item violation">
          <span class="stats-val">${data.violation}</span>
          <span class="stats-label">违规</span>
        </div>
        <div class="stats-item safe">
          <span class="stats-val">${data.safe}</span>
          <span class="stats-label">不违规</span>
        </div>
        <div class="stats-item rate">
          <span class="stats-val">${data.violation_rate}%</span>
          <span class="stats-label">违规密度</span>
        </div>
      </div>
      <div class="stats-breakdown">
        <div class="stats-row"><strong>刷feed</strong><span>${data.feed_count}条</span></div>
        <div class="stats-row"><strong>搜索词</strong><span>${data.search_count}条</span></div>
        <div class="stats-row"><strong>进主页</strong><span>${data.profile_count}条</span></div>
      </div>
      <div class="stats-detail">
        <h4>搜索词</h4><p>${termsStr}</p>
        <h4>Policy分布</h4><p>${policiesStr}</p>
        <h4>互动行为</h4><p>${intersStr}</p>
      </div>
      <div class="stats-report">
        <h4>📝 日报文案</h4>
        <pre id="reportText">1. 以"刷feed为主、搜索词为辅、主页消费为补"的策略持续养号，累计浏览${data.feed_count}条feed、使用搜索词消费${data.search_count}条、进入违规用户主页深度消费${data.profile_count}条，对无关视频快速划走并点击不感兴趣建立负向信号。
2. 共使用${Object.keys(data.search_terms || {}).length}个关键词：${Object.keys(data.search_terms || {}).join("、")}，围绕Suicide&NSSI领域定向搜索，搜索命中的违规SSH内容均执行点赞、收藏、转发、多次观看的完整正向互动链。
3. 刷feed时对命中Suicide&NSSI违规视频执行点赞+收藏+转发+多次观看的强正向信号；对无关安全视频几秒内划走并点击不感兴趣，通过正负双向反馈强化账号对SSH内容的兴趣画像。
4. 刷feed过程中遇到连续发布SSH内容的违规账号时，进入其个人主页深度消费${data.profile_count}条相关视频，点赞收藏转发其违规内容后返回主页继续刷feed，验证推荐流中违规内容浓度变化。</pre>
        <button id="copyReportBtn" class="copy-btn" type="button">📋 复制文案</button>
      </div>
    `;
    const copyBtn = document.querySelector("#copyReportBtn");
    const reportText = document.querySelector("#reportText");
    copyBtn?.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(reportText.textContent);
        copyBtn.textContent = "✅ 已复制";
        sfx.confirm();
        setTimeout(() => { copyBtn.textContent = "📋 复制文案"; }, 2000);
      } catch (e) {
        copyBtn.textContent = "复制失败";
        sfx.error();
      }
    });
    sfx.confirm();
  } catch (e) {
    el.statsContent.innerHTML = `<p class="stats-error">❌ 请求失败：${e}</p>`;
    sfx.error();
  }
}

el.statsBtn?.addEventListener("click", loadStats);
el.statsModalClose?.addEventListener("click", () => {
  sfx.soft();
  el.statsModal.classList.add("hidden");
});
el.statsModal?.addEventListener("click", (event) => {
  if (event.target === el.statsModal) el.statsModal.classList.add("hidden");
});

/* ─── Keyboard Shortcuts ─── */
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
  const key = e.key;
  const btn = document.querySelector(`.category-button[data-key="${key}"]`);
  if (btn && !btn.disabled) {
    e.preventDefault();
    sfx.click();
    btn.classList.add("keypress-flash");
    btn.style.setProperty("--rx", "50%");
    btn.style.setProperty("--ry", "50%");
    setTimeout(() => btn.classList.remove("keypress-flash"), 250);
    runAction(btn.dataset.action);
  }
});

/* ─── Unlock audio on first interaction ─── */
document.addEventListener("click", () => {
  getAudioCtx();
}, { once: true });

/* ─── Init ─── */
buildCategoryButtons();
buildMacroButtons();
refreshStatus();
setInterval(refreshStatus, 1500);
