from __future__ import annotations

import csv
import json
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
LARK_CLI = Path("lark-cli")
URL_PATTERN = re.compile(r"https?://[^\s]+")

TRIPLE_INTERACTION = ("看一次视频", "点赞视频", "收藏视频", "转发视频")
QUAD_INTERACTION = ("看一次视频", "点赞视频", "收藏视频", "转发视频", "看视频下的一级评论")
NOT_VIOLATION_INTERACTION = ("未完整看完视频",)
CATEGORY_REVIEW_MAP: dict[str, tuple[str, str, str]] = {
    "1": (
        "Borderline",
        "Borderline - Nudity & Sexual Activity",
        "[Borderline] Contextual Behaviors & Language (Adult)",
    ),
    "2": (
        "Borderline",
        "Borderline - Nudity & Sexual Activity",
        "[Borderline] Contextual Body Exposure (Adult)",
    ),
    "3": (
        "Borderline",
        "Borderline - Nudity & Sexual Activity",
        "[Borderline] Sexualized Depictions of Animals",
    ),
    "4": (
        "Nudity & Sexual Activity",
        "Sexual Activity & Services",
        "Adult Sexual Activity",
    ),
    "5": (
        "Nudity & Sexual Activity",
        "Adult Nudity & Body Exposure",
        "Adult Nudity",
    ),
    "6": (
        "Borderline",
        "Borderline - Nudity & Sexual Activity",
        "[Borderline] Illustrations",
    ),
}


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
        sheet.setdefault("spreadsheet_token", self.spreadsheet_token)
        sheet.setdefault("sheet_id", self.sheet_id)
        sheet.setdefault("start_row", self.start_row)
        sheet.setdefault("current_row", self.current_row)
        save_config(config)

    def write_from_macro(self, macro_key: str, link: str) -> str:
        link = extract_first_url(link)
        if not URL_PATTERN.fullmatch(link):
            raise ValueError(f"剪贴板没有有效 TikTok 链接：{link[:80]}")

        interaction = macro_interaction(macro_key)
        if interaction == "safe":
            self._put_review_values(link, "否")
            self._put_multiple_values(f"J{self.current_row}", NOT_VIOLATION_INTERACTION)
        elif interaction == "triple":
            self._put_review_values(link, "是")
            self._put_multiple_values(f"J{self.current_row}", TRIPLE_INTERACTION)
        elif interaction == "quad":
            self._put_review_values(link, "是")
            self._put_multiple_values(f"J{self.current_row}", QUAD_INTERACTION)
        else:
            raise ValueError(f"未知宏类型：{macro_key}")

        written_row = self.current_row
        self.current_row += 1
        self._save_current_row()
        self._put_hyperlink_async(written_row, link)
        return f"飞书写入成功：第 {written_row} 行"

    def write_category_review(self, link: str, category_id: str) -> str:
        link = extract_first_url(link)
        if not URL_PATTERN.fullmatch(link):
            raise ValueError(f"剪贴板没有有效 TikTok 链接：{link[:80]}")

        if category_id == "0":
            self._put_review_values(link, "否")
            self._put_multiple_values(f"J{self.current_row}", NOT_VIOLATION_INTERACTION)
        else:
            category = CATEGORY_REVIEW_MAP.get(category_id)
            if category is None:
                raise ValueError(f"未知分类：{category_id}")
            self._put_review_values(link, "是")
            self._put_csv(f"G{self.current_row}", [[category[0], category[1], category[2]]])
            self._put_multiple_values(f"J{self.current_row}", TRIPLE_INTERACTION)

        written_row = self.current_row
        self.current_row += 1
        self._save_current_row()
        self._put_hyperlink_async(written_row, link)
        return f"飞书写入成功：第 {written_row} 行，分类 {category_id}"

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
        save_config(config)

    def _put_review_values(self, link: str, violation_value: str) -> None:
        self._put_csv(f"D{self.current_row}", [[link, "feed", violation_value]])

    def _put_csv(self, start_cell: str, rows: list[list[str]]) -> None:
        result = run_lark(
            [
                "sheets",
                "+csv-put",
                "--spreadsheet-token",
                self.spreadsheet_token,
                "--sheet-id",
                self.sheet_id,
                "--start-cell",
                start_cell,
                "--csv",
                to_csv(rows),
                "--as",
                "user",
            ]
        )
        ensure_ok(result)

    def _put_multiple_values(self, cell: str, values: tuple[str, ...]) -> None:
        result = run_lark(
            [
                "sheets",
                "+cells-set",
                "--spreadsheet-token",
                self.spreadsheet_token,
                "--sheet-id",
                self.sheet_id,
                "--range",
                cell,
                "--cells",
                json.dumps([[{"multiple_values": [{"value": value} for value in values]}]], ensure_ascii=False),
                "--as",
                "user",
            ]
        )
        ensure_ok(result)

    def _put_hyperlink_async(self, row: int, link: str) -> None:
        def worker() -> None:
            result = run_lark(
                [
                    "sheets",
                    "+cells-set",
                    "--spreadsheet-token",
                    self.spreadsheet_token,
                    "--sheet-id",
                    self.sheet_id,
                    "--range",
                    f"D{row}",
                    "--cells",
                    json.dumps(
                        [[{"rich_text": [{"type": "link", "text": link, "link": link}]}]],
                        ensure_ascii=False,
                    ),
                    "--as",
                    "user",
                ]
            )
            if result.returncode != 0:
                print(result.stderr or result.stdout)

        threading.Thread(target=worker, daemon=True).start()


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(config: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_lark(args: list[str]) -> subprocess.CompletedProcess[str]:
    command = [str(LARK_CLI) if LARK_CLI.exists() else "lark-cli", *args]
    return subprocess.run(command, check=False, capture_output=True, text=True, timeout=18)


def ensure_ok(result: subprocess.CompletedProcess[str]) -> None:
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or f"lark-cli exited {result.returncode}").strip())


def to_csv(rows: list[list[str]]) -> str:
    output = StringIO()
    writer = csv.writer(output, lineterminator="")
    writer.writerows(rows)
    return output.getvalue()


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
