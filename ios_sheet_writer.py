from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"

_LARK_BIN_CANDIDATES = [
    Path.home() / ".trae-cn/plugins/trae-remote-official/lark/1.0.3/bin/lark-cli",
    Path.home() / ".nvm/versions/node/v24.16.0/bin/lark-cli",
    Path.home() / ".local/bin/lark-cli",
]
LARK_CLI = next((p for p in _LARK_BIN_CANDIDATES if p.exists()), Path("lark-cli"))
if str(LARK_CLI.parent) not in os.environ.get("PATH", ""):
    os.environ["PATH"] = str(LARK_CLI.parent) + os.pathsep + os.environ.get("PATH", "")

URL_PATTERN = re.compile(r"https?://[^\s]+")

BEHAVIOR_FEED = "刷feed"
BEHAVIOR_SEARCH = "搜索词"

VIOLATION_YES = "是"
VIOLATION_NO = "否"

POLICY_OPTIONS = [
    "Credible Threat of Suicide",
    "Suicide&NSSI",
    "Suicide&NSSI-severe",
]

INTERACTION_LIKE = "点赞"
INTERACTION_FAVORITE = "收藏"
INTERACTION_FORWARD = "转发"
INTERACTION_REWATCH = "多次观看"
INTERACTION_WATCH_ONCE = "看一遍视频"
INTERACTION_NOT_FINISHED = "未看完视频"
INTERACTION_VIEW_PROFILE = "查看用户主页"
INTERACTION_FOLLOW = "关注用户"
INTERACTION_NOT_INTERESTED = "不感兴趣"
INTERACTION_REPORT = "举报"
ALL_INTERACTION_OPTIONS = [
    INTERACTION_LIKE,
    INTERACTION_FAVORITE,
    INTERACTION_FORWARD,
    INTERACTION_REWATCH,
    INTERACTION_WATCH_ONCE,
    INTERACTION_NOT_FINISHED,
    INTERACTION_VIEW_PROFILE,
    INTERACTION_FOLLOW,
    INTERACTION_NOT_INTERESTED,
    INTERACTION_REPORT,
]

SAFE_INTERACTIONS = [INTERACTION_NOT_FINISHED, INTERACTION_NOT_INTERESTED]
VIOLATION_INTERACTIONS = [INTERACTION_LIKE, INTERACTION_FAVORITE, INTERACTION_FORWARD, INTERACTION_REWATCH]


FALLBACK_DOMAINS: dict[str, dict] = {
    "minor": {
        "label": "Minor",
        "categories": [
            {"key": "1", "label": "L1违规", "policy": "L1", "violation": True, "macro": "quad"},
            {"key": "2", "label": "L2违规", "policy": "L2", "violation": True, "macro": "quad"},
            {"key": "3", "label": "不违规", "policy": "", "violation": False, "macro": "safe"},
        ],
    },
    "ansa": {
        "label": "ANSA",
        "categories": [
            {"key": "1", "label": "违规", "policy": "", "violation": True, "macro": "quad"},
            {"key": "2", "label": "不违规", "policy": "", "violation": False, "macro": "safe"},
        ],
    },
    "ssh": {
        "label": "SSH",
        "categories": [
            {"key": "1", "label": "Credible Threat", "policy": "Credible Threat of Suicide", "violation": True, "macro": "quad"},
            {"key": "2", "label": "Suicide&NSSI", "policy": "Suicide&NSSI", "violation": True, "macro": "quad"},
            {"key": "3", "label": "NSSI-severe", "policy": "Suicide&NSSI-severe", "violation": True, "macro": "quad"},
            {"key": "4", "label": "不违规", "policy": "", "violation": False, "macro": "safe"},
        ],
    },
    "edf": {
        "label": "EDF",
        "categories": [
            {"key": "1", "label": "Disordered Eating", "policy": "Disordered Eating", "violation": True, "macro": "quad", "color": "blue"},
            {"key": "2", "label": "Highly Harmful", "policy": "Disordered Eating - Highly Harmful", "violation": True, "macro": "quad", "color": "pink"},
            {"key": "3", "label": "General WL/MG · MFT", "policy": "General Weight Loss & Muscle Gain Products & Services - Marketing, Facilitation & Trade", "violation": True, "macro": "quad", "color": "orange"},
            {"key": "4", "label": "High Risk WL/MG · MFT", "policy": "High Risk Weight Loss & Muscle Gain Products & Services - Marketing, Facilitation & Trade", "violation": True, "macro": "quad", "color": "pink"},
            {"key": "5", "label": "High Risk WL/MG · DDP", "policy": "High Risk Weight Loss & Muscle Gain Products, Services & Behaviors - Depiction, Description & Promotion", "violation": True, "macro": "quad", "color": "orange"},
            {"key": "6", "label": "Invasive Cosmetic", "policy": "Invasive Cosmetic Procedures", "violation": True, "macro": "quad", "color": "blue"},
            {"key": "7", "label": "不违规", "policy": "", "violation": False, "macro": "safe", "color": "green"},
        ],
    },
}


def domains_config(config: dict | None = None) -> dict[str, dict]:
    config = config if config is not None else load_config()
    domains = config.get("domains")
    if isinstance(domains, dict) and domains:
        return domains
    return FALLBACK_DOMAINS


def current_domain_key(config: dict | None = None) -> str:
    config = config if config is not None else load_config()
    domains = domains_config(config)
    key = str(config.get("current_domain", "ssh"))
    return key if key in domains else next(iter(domains))


def category_for_key(config: dict, category_id: str) -> dict | None:
    domains = domains_config(config)
    domain = domains.get(current_domain_key(config), {})
    for cat in domain.get("categories", []):
        if str(cat.get("key")) == str(category_id):
            return cat
    return None


@dataclass
class IOSSheetWriter:
    spreadsheet_token: str = ""
    sheet_id: str = ""
    start_row: int = 2

    def __post_init__(self) -> None:
        config = load_config()
        sheet = config.setdefault("sheet", {})
        self.spreadsheet_token = sheet.get("spreadsheet_token", self.spreadsheet_token)
        self.sheet_id = sheet.get("sheet_id", self.sheet_id)
        self.current_row = int(sheet.get("current_row", sheet.get("start_row", self.start_row)))
        self.has_policy_column = bool(sheet.get("has_policy_column", True))
        self.binary_mode = bool(sheet.get("binary_mode", False))
        sheet.setdefault("spreadsheet_token", self.spreadsheet_token)
        sheet.setdefault("sheet_id", self.sheet_id)
        sheet.setdefault("start_row", self.start_row)
        sheet.setdefault("current_row", self.current_row)
        sheet.setdefault("has_policy_column", self.has_policy_column)
        sheet.setdefault("binary_mode", self.binary_mode)
        save_config(config)

    def write_from_macro(self, macro_key: str, link: str) -> str:
        link = extract_first_url(link)
        if not URL_PATTERN.fullmatch(link):
            raise ValueError(f"剪贴板没有有效 TikTok 链接：{link[:80]}")

        interaction_type = macro_interaction(macro_key)

        if interaction_type == "safe":
            self._write_row(
                link=link,
                behavior=BEHAVIOR_FEED,
                search_term="",
                is_violation=False,
                interactions=SAFE_INTERACTIONS,
                policy_text="",
            )
        else:
            self._write_row(
                link=link,
                behavior=BEHAVIOR_FEED,
                search_term="",
                is_violation=True,
                interactions=VIOLATION_INTERACTIONS,
                policy_text="",
            )

        written_row = self.current_row
        self.current_row += 1
        self._save_current_row()
        return f"飞书写入成功：第 {written_row} 行"

    def write_category_review(self, link: str, category_id: str, search_term: str = "") -> str:
        link = extract_first_url(link) if link else ""
        if not URL_PATTERN.fullmatch(link):
            raise ValueError(f"剪贴板没有有效 TikTok 链接：{link[:80]}")

        config = load_config()
        cat = category_for_key(config, category_id)
        domain_key = current_domain_key(config)
        domains = domains_config(config)
        if cat is None:
            valid = ", ".join(
                f"{c.get('key')}={c.get('label')}" for c in domains.get(domain_key, {}).get("categories", [])
            )
            raise ValueError(f"未知分类：{category_id}（{domains.get(domain_key, {}).get('label', domain_key)} 领域支持：{valid}）")

        is_violation = bool(cat.get("violation"))
        policy_text = str(cat.get("policy", "") or "")
        interactions = VIOLATION_INTERACTIONS if is_violation else SAFE_INTERACTIONS

        self._write_row(
            link=link,
            behavior=BEHAVIOR_FEED,
            search_term=search_term,
            is_violation=is_violation,
            interactions=interactions,
            policy_text=policy_text,
        )

        written_row = self.current_row
        self.current_row += 1
        self._save_current_row()
        if is_violation:
            label = f"违规({policy_text})" if policy_text else "违规"
        else:
            label = "不违规"
        return f"飞书写入成功：第 {written_row} 行，{label}"

    def set_current_row(self, row: int) -> None:
        if row < 1:
            raise ValueError("row must be positive")
        self.current_row = row
        self._save_current_row()

    def _save_current_row(self) -> None:
        config = load_config()
        sheet = config.setdefault("sheet", {})
        sheet["spreadsheet_token"] = self.spreadsheet_token
        sheet["sheet_id"] = self.sheet_id
        sheet["start_row"] = self.start_row
        sheet["current_row"] = self.current_row
        sheet["has_policy_column"] = self.has_policy_column
        sheet["binary_mode"] = self.binary_mode
        save_config(config)

    def _write_row(
        self,
        link: str,
        behavior: str,
        search_term: str,
        is_violation: bool,
        interactions: list[str],
        policy_text: str = "",
    ) -> None:
        violation_value = VIOLATION_YES if is_violation else VIOLATION_NO
        valid_interactions = validate_interactions(interactions)

        interaction_cell = {
            "multiple_values": [{"value": v} for v in valid_interactions]
        }

        if link:
            link_cell = {
                "rich_text": [{"type": "link", "text": link, "link": link}]
            }
        else:
            link_cell = {"value": ""}

        if self.has_policy_column:
            row = [[
                {"value": behavior},
                {"value": search_term},
                link_cell,
                {"value": violation_value},
                {"value": policy_text or ""},
                interaction_cell,
            ]]
            range_str = f"B{self.current_row}:G{self.current_row}"
        else:
            row = [[
                {"value": behavior},
                {"value": search_term},
                link_cell,
                {"value": violation_value},
                interaction_cell,
            ]]
            range_str = f"B{self.current_row}:F{self.current_row}"
        self._put_cells(range_str, row)

    def _put_cells(self, range_str: str, cells: list[list[dict]]) -> None:
        last_error = None
        cells_json = json.dumps(cells, ensure_ascii=False)
        for attempt in range(3):
            result = run_lark(
                [
                    "sheets",
                    "+cells-set",
                    "--spreadsheet-token",
                    self.spreadsheet_token,
                    "--sheet-id",
                    self.sheet_id,
                    "--range",
                    range_str,
                    "--cells",
                    cells_json,
                    "--as",
                    "user",
                ]
            )
            if result.returncode == 0:
                return
            error_text = (result.stderr or result.stdout or "").strip()
            last_error = RuntimeError(error_text or f"lark-cli exited {result.returncode}")
            if is_retryable_error(error_text) and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            break
        raise last_error


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


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


RETRYABLE_ERROR_CODES = {"1204", "601125000", "601124000"}
RETRYABLE_KEYWORDS = ("timeout", "request timeout", "connect timeout", "thrift_egress", "server_error", "connection reset", "temporarily unavailable", "503", "502", "504")


def is_retryable_error(error_text: str) -> bool:
    lower = error_text.lower()
    for code in RETRYABLE_ERROR_CODES:
        if code in lower:
            return True
    return any(kw in lower for kw in RETRYABLE_KEYWORDS)


def run_lark(args: list[str]) -> subprocess.CompletedProcess[str]:
    command = [str(LARK_CLI) if LARK_CLI.exists() else "lark-cli", *args]
    return subprocess.run(command, check=False, capture_output=True, text=True, timeout=30)


def extract_first_url(text: str) -> str:
    match = URL_PATTERN.search(text.strip())
    if not match:
        return text.strip()
    return match.group(0).rstrip("。，,)")


def read_clipboard_link() -> str:
    result = subprocess.run(["pbpaste"], check=False, capture_output=True, text=True)
    return extract_first_url(result.stdout.strip())


def read_clipboard_link_with_retry(timeout_seconds: float = 8.0, previous_link: str = "") -> str:
    start = time.time()
    deadline = time.time() + timeout_seconds
    last = ""
    previous_link = extract_first_url(previous_link)
    while time.time() < deadline:
        link = read_clipboard_link()
        last = link
        if URL_PATTERN.fullmatch(link) and link != previous_link:
            return link
        elapsed = time.time() - start
        time.sleep(0.08 if elapsed < 1.2 else 0.25)
    return last


def macro_interaction(macro_key: str) -> str:
    base = macro_key.split(":", 1)[-1]
    if base.endswith("_safe"):
        return "safe"
    if base.endswith("_triple"):
        return "triple"
    if base.endswith("_quad"):
        return "quad"
    return "unknown"


def validate_interactions(interactions: list[str]) -> list[str]:
    return [i for i in interactions if i in ALL_INTERACTION_OPTIONS]
