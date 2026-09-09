#!/usr/bin/env python3
"""
批量密度统计脚本（Minor in Feed 专项 · 0818养号表格）
- 读取12个账号sheet的E列(是否违规)是/否序列 + F列(policy: L1/L2)
- 最近100条写入 最近100条密度统计 sheet 奇数列(A/C/E/...)
- 最近300条写入 最近300条密度统计 sheet 奇数列
- 更新 时长&初步统计 E/F/G/H/I列(总违规/总消费/密度/100极值/300极值)
"""
import csv
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

for _p in [
    Path.home() / ".trae-cn/plugins/trae-remote-official/lark/1.0.3/bin",
    Path.home() / ".nvm/versions/node/v24.16.0/bin",
    Path.home() / ".local/bin",
    Path("/usr/local/bin"),
]:
    if _p.is_dir() and str(_p) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = str(_p) + os.pathsep + os.environ.get("PATH", "")

SPREADSHEET_TOKEN = "Ln4RsUu3lh8oMYteJOOm0NtgyKc"

ACCOUNTS = [
    ("8oOjek", "ID-7674830370202108936",  2,  "A", "A"),
    ("0EpigQ", "ID-7674830370202125320",  3,  "C", "C"),
    ("k5NFq6", "ID-7674830367204131858",  4,  "E", "E"),
    ("Lcm9Ha", "GB-7674830209241433121",  5,  "G", "G"),
    ("xD1mDP", "GB-7674830209241400353",  6,  "I", "I"),
    ("PlUk8W", "GB-7674830209241416737",  7,  "K", "K"),
    ("vLahNr", "FR-7674830730724099104",  8,  "M", "M"),
    ("uKaVFv", "FR-7674830818619720736",  9,  "O", "O"),
    ("ko5dcS", "FR-7674830818619737120", 10,  "Q", "Q"),
    ("cOcQ9w", "US-7674833313077920782", 11,  "S", "S"),
    ("i1yIAB", "US-7674834215967917070", 12,  "U", "U"),
    ("T6ZRRk", "US-7674834499684238350", 13,  "W", "W"),
]

SHEET_100 = "2oMtkX"
SHEET_300 = "A4XvPG"
SHEET_SUMMARY = "x8tDhT"


def run_lark(args, stdin_text=None, timeout=120):
    cmd = ["lark-cli"] + args + ["--as", "user"]
    result = subprocess.run(cmd, input=stdin_text, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        print(f"ERROR: {result.stderr[:500]}", file=sys.stderr)
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def parse_rows(csv_text, has_header=True):
    """解析annotated_csv，提取每行的 (violation, policy) ，跳过空行和表头。
    列结构: A=起始时间 B=行为 C=搜索词汇 D=链接 E=是否违规 F=policy G=互动
    """
    rows = []
    lines = csv_text.strip().split("\n")
    if has_header:
        lines = lines[1:]
    for line in lines:
        bracket_end = line.index("]")
        csv_part = line[bracket_end + 1:].lstrip()
        reader = csv.reader(io.StringIO(csv_part))
        for fields in reader:
            if len(fields) < 5:
                break
            url = fields[3].strip() if len(fields) > 3 else ""
            violation = fields[4].strip() if len(fields) > 4 else ""
            policy = fields[5].strip() if len(fields) > 5 else ""
            if not url:
                break
            if violation in ("是", "否"):
                rows.append((violation, policy))
            break
    return rows


def read_account_data(sheet_id):
    resp = run_lark([
        "sheets", "+csv-get",
        "--spreadsheet-token", SPREADSHEET_TOKEN,
        "--sheet-id", sheet_id,
        "--range", "A1:H1004",
    ])
    if not resp or not resp.get("ok"):
        print(f"  ✗ 读取失败")
        return []
    return parse_rows(resp["data"]["annotated_csv"], has_header=True)


def write_column(sheet_id, col_letter, values, start_row=2):
    if not values:
        return True
    n = len(values)
    end_row = start_row + n - 1
    rng = f"{col_letter}{start_row}:{col_letter}{end_row}"
    cells = [[{"value": v}] for v in values]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False,
                                     dir=tempfile.gettempdir(), encoding="utf-8") as f:
        json.dump(cells, f, ensure_ascii=False)
        tmp = f.name
    try:
        with open(tmp, "r", encoding="utf-8") as pf:
            resp = run_lark([
                "sheets", "+cells-set",
                "--spreadsheet-token", SPREADSHEET_TOKEN,
                "--sheet-id", sheet_id,
                "--range", rng,
                "--cells", "-",
            ], stdin_text=pf.read())
        return resp is not None and resp.get("ok", False)
    finally:
        os.unlink(tmp)


def write_summary_row(row, values_by_col):
    """一次写入汇总表一行的多列，values_by_col: {col_letter: value}"""
    for col, value in values_by_col.items():
        cell = [[{"value": value}]]
        rng = f"{col}{row}:{col}{row}"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False,
                                         dir=tempfile.gettempdir(), encoding="utf-8") as f:
            json.dump(cell, f, ensure_ascii=False)
            tmp = f.name
        try:
            with open(tmp, "r", encoding="utf-8") as pf:
                resp = run_lark([
                    "sheets", "+cells-set",
                    "--spreadsheet-token", SPREADSHEET_TOKEN,
                    "--sheet-id", SHEET_SUMMARY,
                    "--range", rng,
                    "--cells", "-",
                ], stdin_text=pf.read())
            if not resp or not resp.get("ok"):
                print(f"  ✗ 写入汇总 {col}{row} 失败")
        finally:
            os.unlink(tmp)


def calc_density(seq):
    if not seq:
        return 0.0
    return seq.count("是") / len(seq) * 100


def main():
    print("=" * 70)
    print("批量密度统计（Minor in Feed · 0818养号）")
    print(f"表格: {SPREADSHEET_TOKEN}")
    print("=" * 70)

    results = []

    for idx, (sid, name, srow, c100, c300) in enumerate(ACCOUNTS):
        print(f"\n[{idx + 1}/12] 读取 {name} ({sid})...")
        rows = read_account_data(sid)
        seq = [v for v, _ in rows]
        policies = [p for _, p in rows]
        total = len(seq)
        v_count = seq.count("是")
        s_count = seq.count("否")
        l1_count = sum(1 for p in policies if p == "L1")
        l2_count = sum(1 for p in policies if p == "L2")
        density = calc_density(seq)

        last100 = seq[-100:] if len(seq) >= 100 else seq[:]
        last300 = seq[-300:] if len(seq) >= 300 else seq[:]

        d100 = calc_density(last100)
        d300 = calc_density(last300)

        print(f"  总记录: {total}  违规: {v_count}(L1={l1_count},L2={l2_count})  安全: {s_count}")
        print(f"  整体密度: {density:.1f}%  最近100条({len(last100)}): {d100:.1f}%  最近300条({len(last300)}): {d300:.1f}%")

        results.append({
            "sid": sid, "name": name, "srow": srow,
            "c100": c100, "c300": c300,
            "seq": seq, "total": total, "v": v_count, "s": s_count,
            "l1": l1_count, "l2": l2_count,
            "last100": last100, "last300": last300,
            "d100": d100, "d300": d300, "density": density,
        })

    print("\n" + "=" * 70)
    print("写入密度数据...")
    print("=" * 70)

    for r in results:
        name = r["name"]
        if not r["last100"]:
            print(f"  跳过 {name}（无数据）")
            continue

        ok100 = write_column(SHEET_100, r["c100"], r["last100"], start_row=2)
        ok300 = write_column(SHEET_300, r["c300"], r["last300"], start_row=2)

        summary_vals = {
            "E": r["v"],
            "F": r["total"],
            "G": f"{r['density']:.1f}%" if r["total"] else "",
            "H": f"{r['d100']:.1f}%" if r["last100"] else "",
            "I": f"{r['d300']:.1f}%" if r["last300"] else "",
        }
        write_summary_row(r["srow"], summary_vals)

        status = "✓" if ok100 and ok300 else "✗"
        print(f"  {status} {name}: 总{r['total']}条 违规{r['v']}(L1={r['l1']},L2={r['l2']}) "
              f"整体{r['density']:.1f}% 近100={r['d100']:.1f}% 近300={r['d300']:.1f}%")

    print("\n" + "=" * 70)
    print("✅ 密度统计完成！")
    print("=" * 70)
    print(f"\n{'账号':35s} {'总数':>5s} {'违规':>5s} {'L1':>4s} {'L2':>4s} {'整体':>7s} {'近100':>7s} {'近300':>7s}")
    print("-" * 82)
    for r in results:
        total = r["total"]
        d_all = r["density"]
        d100 = r["d100"] if r["last100"] else 0
        d300 = r["d300"] if r["last300"] else 0
        print(f"{r['name']:35s} {total:5d} {r['v']:5d} {r['l1']:4d} {r['l2']:4d} "
              f"{d_all:6.1f}% {d100:6.1f}% {d300:6.1f}%")


if __name__ == "__main__":
    main()
