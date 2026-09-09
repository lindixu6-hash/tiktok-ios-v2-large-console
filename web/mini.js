(function () {
  const statusDot = document.getElementById("statusDot");
  const statusText = document.getElementById("statusText");
  const openMainBtn = document.getElementById("openMainBtn");
  const toast = document.getElementById("toast");
  const buttonArea = document.getElementById("buttonArea");

  let busy = false;
  let categories = [];
  let currentDomain = "";
  const colorMap = {
    blue: "blue",
    orange: "orange",
    pink: "pink",
    red: "pink",
    green: "green",
  };

  function shortLabel(label) {
    if (label.length <= 7) return label;
    if (/Credible/i.test(label)) return "Credible";
    if (/severe/i.test(label)) return "NSSI-severe";
    if (/NSSI/i.test(label)) return "NSSI";
    return label.slice(0, 6);
  }

  function buildButtons() {
    buttonArea.innerHTML = "";
    const n = Math.min(Math.max(categories.length, 1), 4);
    buttonArea.style.gridTemplateColumns = `repeat(${n}, 1fr)`;
    buttonArea.classList.toggle("binary", categories.length === 2);
    categories.forEach((cat) => {
      const btn = document.createElement("button");
      btn.className = "mini-btn mc-" + (colorMap[cat.color] || "blue");
      btn.dataset.action = "category:" + cat.key;
      btn.dataset.key = String(cat.key);
      btn.title = cat.policy ? `${cat.label}：${cat.policy}` : cat.label;
      const k = document.createElement("span");
      k.className = "key";
      k.textContent = cat.key;
      const l = document.createElement("span");
      l.className = "label";
      l.textContent = shortLabel(cat.label);
      btn.append(k, l);
      btn.addEventListener("click", function () {
        runAction(btn.dataset.action, btn);
      });
      buttonArea.appendChild(btn);
    });
  }

  function applyDomain(data) {
    const next = Array.isArray(data.categories) ? data.categories : [];
    const nextDomain = data.current_domain || "";
    const sig = nextDomain + "|" + next.map((c) => c.key + ":" + c.label).join(",");
    const prev = currentDomain + "|" + categories.map((c) => c.key + ":" + c.label).join(",");
    currentDomain = nextDomain;
    categories = next;
    if (sig !== prev) buildButtons();
  }

  function setStatus(state, text) {
    statusDot.className = "dot " + state;
    statusText.textContent = text;
  }

  function showToast(msg, type) {
    toast.textContent = msg;
    toast.className = "toast show " + (type || "");
    clearTimeout(toast._t);
    toast._t = setTimeout(function () {
      toast.className = "toast";
    }, 2000);
  }

  function summarize(s) {
    if (!s) return "";
    let m = s.match(/飞书写入成功：第\s*\d+\s*行/);
    if (m) return m[0];
    m = s.match(/ERROR:[^；]+/);
    if (m) return m[0].substring(0, 30);
    m = s.match(/剪贴板仍是上一条/);
    if (m) return "链接重复";
    return s.length > 16 ? s.substring(0, 16) + "…" : s;
  }

  async function runAction(action, btn) {
    if (busy) return;
    busy = true;
    setButtonsDisabled(true);
    setStatus("working", "执行中…");
    if (btn) {
      btn.classList.add("flash");
      setTimeout(function () { btn.classList.remove("flash"); }, 250);
    }
    try {
      const res = await fetch("/api/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: action }),
      });
      const data = await res.json();
      if (!data.ok) {
        setStatus("error", "失败");
        showToast(data.message ? data.message.substring(0, 25) : "失败", "error");
        busy = false;
        setButtonsDisabled(false);
      }
    } catch (err) {
      setStatus("error", "连接失败");
      showToast("无法连接服务器", "error");
      busy = false;
      setButtonsDisabled(false);
    }
  }

  function setButtonsDisabled(disabled) {
    document.querySelectorAll(".mini-btn").forEach(function (b) { b.disabled = disabled; });
  }

  document.addEventListener("keydown", function (e) {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
    const btn = document.querySelector('.mini-btn[data-key="' + e.key + '"]');
    if (btn && !btn.disabled) {
      e.preventDefault();
      runAction(btn.dataset.action, btn);
    }
  });

  openMainBtn.addEventListener("click", function () {
    window.open("/", "_blank");
  });

  async function refreshStatus() {
    try {
      const res = await fetch("/api/status");
      const data = await res.json();
      applyDomain(data);
      if (data.busy) {
        if (!busy) setStatus("working", "执行中…");
      } else {
        if (busy) {
          const msg = summarize(data.status);
          const isError = /ERROR|失败|重复/.test(msg);
          setStatus(isError ? "error" : "success", isError ? msg.substring(0, 10) : "完成");
          showToast(msg, isError ? "error" : "success");
          busy = false;
          setButtonsDisabled(false);
          setTimeout(function () {
            if (!busy) setStatus("idle", "空闲");
          }, 2000);
        }
      }
    } catch (_) {
      if (!busy) setStatus("error", "未连接");
    }
  }

  setStatus("idle", "空闲");
  refreshStatus();
  setInterval(refreshStatus, 700);
})();
