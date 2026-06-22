const macroLabels = {
  normal_triple: "违规三连",
  normal_quad: "违规四连",
  normal_safe: "不违规",
  raised_triple: "推荐三连",
  raised_quad: "推荐四连",
  raised_safe: "推荐不违规",
};

const categoryLabels = {
  "0": "不违规",
  "1": "BL-Lang",
  "2": "BL-Body",
  "3": "Animal",
  "4": "Sex Act",
  "5": "Nudity",
  "6": "BL-Illus",
};

const recordingEl = document.querySelector("#recording");
const statusEl = document.querySelector("#status");
const statusDetailEl = document.querySelector("#statusDetail");
const statusDetailButton = document.querySelector("#statusDetailButton");
const statusModal = document.querySelector("#statusModal");
const statusModalClose = document.querySelector("#statusModalClose");
const consoleEyebrow = document.querySelector("#consoleEyebrow");
const consoleTitle = document.querySelector("#consoleTitle");
const consoleSubtitle = document.querySelector("#consoleSubtitle");
const macroStrip = document.querySelector("#macroStrip");
const busyPill = document.querySelector("#busyPill");
const playButtons = document.querySelector("#playButtons");
const recordButtons = document.querySelector("#recordButtons");
const categoryButtons = document.querySelector("#categoryButtons");
const catImage = document.querySelector("#catImage");
const rowInput = document.querySelector("#rowInput");
const rowButton = document.querySelector("#rowButton");

function makeButton(label, action) {
  const button = document.createElement("button");
  button.textContent = label;
  button.dataset.action = action;
  button.addEventListener("click", () => runAction(action));
  return button;
}

function buildMacroButtons() {
  Object.entries(macroLabels).forEach(([key, label]) => {
    playButtons.appendChild(makeButton(`播放并写入${label}`, `play:${key}`));
    recordButtons.appendChild(makeButton(`录制${label}`, `record:${key}`));
  });
}

function buildCategoryButtons() {
  Object.entries(categoryLabels).forEach(([id, label]) => {
    const button = makeButton(id, `category:${id}`);
    button.className = `category-button category-${id}`;
    button.setAttribute("aria-label", `${id} ${label}`);
    const number = document.createElement("strong");
    number.textContent = id;
    const text = document.createElement("span");
    text.textContent = label;
    button.textContent = "";
    button.append(number, text);
    categoryButtons.appendChild(button);
  });
}

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
      statusEl.textContent = data.message || "操作失败";
    }
    await refreshStatus();
  } catch (error) {
    statusEl.textContent = `请求失败：${error}`;
  } finally {
    setButtonsDisabled(false);
  }
}

async function switchProfile(profile) {
  await runAction(`profile:${profile}`);
  catImage.src = `/cat.png?t=${Date.now()}`;
}

function setButtonsDisabled(disabled) {
  document.querySelectorAll("button").forEach((button) => {
    if (button.dataset.action !== "stop_recording") {
      button.disabled = disabled;
    }
  });
}

function renderMacros(macros) {
  macroStrip.innerHTML = "";
  macros.forEach((macro) => {
    const chip = document.createElement("span");
    chip.className = `chip ${macro.recorded ? "done" : ""}`;
    chip.textContent = macro.recorded ? `${macro.label} · ${macro.count}点` : `${macro.label} · 未录`;
    macroStrip.appendChild(chip);
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
  return withoutLink.length > 42 ? `${withoutLink.slice(0, 42)}...` : withoutLink;
}

async function refreshStatus() {
  const response = await fetch("/api/status");
  const data = await response.json();
  if (data.console) {
    consoleEyebrow.textContent = data.console.eyebrow;
    consoleTitle.textContent = data.console.title;
    consoleSubtitle.textContent = data.console.subtitle;
    document.title = `${data.console.eyebrow} ${data.console.title}`;
  }
  recordingEl.textContent = data.recording;
  statusEl.textContent = summarizeStatus(data.status);
  statusEl.title = data.status;
  statusDetailEl.textContent = data.status;
  busyPill.textContent = data.busy ? `${data.current}中` : "空闲";
  busyPill.classList.toggle("busy", data.busy);
  renderMacros(data.macros);
  if (document.activeElement !== rowInput) {
    rowInput.value = data.sheet.current_row;
  }
  document.querySelectorAll("[data-profile]").forEach((button) => {
    button.classList.toggle("active", button.dataset.profile === data.profile.key);
  });
}

document.querySelectorAll("[data-action]").forEach((button) => {
  button.addEventListener("click", () => runAction(button.dataset.action));
});

document.querySelectorAll("[data-profile]").forEach((button) => {
  button.addEventListener("click", () => switchProfile(button.dataset.profile));
});

rowButton.addEventListener("click", () => {
  const row = Number(rowInput.value);
  if (!Number.isFinite(row) || row < 1) {
    statusEl.textContent = "请输入有效行号";
    return;
  }
  runAction(`row:${Math.floor(row)}`);
});

statusDetailButton.addEventListener("click", () => {
  statusModal.classList.remove("hidden");
});

statusModalClose.addEventListener("click", () => {
  statusModal.classList.add("hidden");
});

statusModal.addEventListener("click", (event) => {
  if (event.target === statusModal) {
    statusModal.classList.add("hidden");
  }
});

buildCategoryButtons();
buildMacroButtons();
refreshStatus();
setInterval(refreshStatus, 1000);
