#!/usr/bin/env python3
"""
随机整行打乱 - 保留/补全所有格式：
- D列: rich_text 超链接
- E列: data_validation (是/否下拉)
- F列: data_validation + multiple_values (多选)
"""
import json
import os
import random
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

_LARK_CLI_CANDIDATES = [
    Path.home() / ".trae-cn/plugins/trae-remote-official/lark/1.0.3/bin",
    Path.home() / ".nvm/versions/node/v24.16.0/bin",
    Path.home() / ".local/bin",
]
for _p in _LARK_CLI_CANDIDATES:
    if _p.is_dir() and str(_p) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = str(_p) + os.pathsep + os.environ.get("PATH", "")

SPREADSHEET_TOKEN = "ZYRTsva9DhtNZntyyu5lHhI9g4b"
SHEET_ID = "xD1mDP"
START_ROW = 21
END_ROW = 352
DATA_RANGE = f"B{START_ROW}:F{END_ROW}"

# data_validation 模板（从原始数据提取）
E_DV_TEMPLATE = {
    "enable_highlight": True,
    "highlight_colors": ["#bacefd", "#fed4a4"],
    "items": ["是", "否"],
    "type": "list"
}
F_DV_TEMPLATE = {
    "enable_highlight": True,
    "highlight_colors": ["#bacefd", "#fed4a4", "#b1e8fc", "#f8e6ab", "#a9efe6", "#fde2e2", "#ece2fe", "#d9f5d6", "#f8def8", "#eef6c6"],
    "items": ["点赞", "收藏", "转发", "多次观看", "看一遍视频", "未看完视频", "查看用户主页", "关注用户", "不感兴趣", "举报"],
    "support_multiple_values": True,
    "type": "list"
}

random.seed()


def run_lark(args, stdin_text=None, timeout=60):
    cmd = ["lark-cli"] + args + ["--as", "user"]
    result = subprocess.run(
        cmd,
        input=stdin_text,
        capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        print(f"ERROR: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"Invalid JSON: {result.stdout[:500]}", file=sys.stderr)
        sys.exit(1)


def make_link_cell(url):
    """D列：带超链接的rich_text单元格"""
    url = url.strip()
    if not url:
        return {"value": ""}
    return {
        "value": url,
        "rich_text": [{"type": "link", "text": url, "link": url}]
    }


def make_multi_cell(value_str):
    """F列：带multiple_values的多选单元格"""
    value_str = value_str.strip()
    if not value_str:
        cell = {"value": "", "data_validation": F_DV_TEMPLATE}
        return cell
    items = [v.strip() for v in value_str.split(",") if v.strip()]
    cell = {
        "value": value_str,
        "data_validation": F_DV_TEMPLATE,
    }
    if items:
        cell["multiple_values"] = [{"value": v} for v in items]
    return cell


def make_violation_cell(value_str):
    """E列：带data_validation的下拉单元格"""
    return {
        "value": value_str.strip(),
        "data_validation": E_DV_TEMPLATE,
    }


def make_b_cell(value_str):
    """B列（行为）普通文本"""
    return {"value": value_str}


def make_c_cell(value_str):
    """C列（搜索词）普通文本，可能为空"""
    return {"value": value_str}


def read_and_normalize():
    """读取所有单元格，补全缺失的格式属性"""
    print(f"读取 {DATA_RANGE} ...")
    chunk_size = 50
    all_rows = []
    
    for start in range(START_ROW, END_ROW + 1, chunk_size):
        end = min(start + chunk_size - 1, END_ROW)
        rng = f"B{start}:F{end}"
        resp = run_lark([
            "sheets", "+cells-get",
            "--spreadsheet-token", SPREADSHEET_TOKEN,
            "--sheet-id", SHEET_ID,
            "--range", rng,
            "--include", "value,rich_text,multiple_values,data_validation",
        ])
        cells = resp["data"]["ranges"][0]["cells"]
        for i, row in enumerate(cells):
            # row 是 [B, C, D, E, F]
            b_val = (row[0] or {}).get("value", "") if len(row) > 0 else ""
            c_val = (row[1] or {}).get("value", "") if len(row) > 1 else ""
            d_val = (row[2] or {}).get("value", "") if len(row) > 2 else ""
            e_val = (row[3] or {}).get("value", "") if len(row) > 3 else ""
            f_val = (row[4] or {}).get("value", "") if len(row) > 4 else ""
            
            # 检查D列是否已有rich_text，没有则补全
            d_cell = row[2] if len(row) > 2 and row[2] else {}
            if "rich_text" not in d_cell and d_val.strip().startswith("http"):
                d_cell = make_link_cell(d_val)
            elif not d_cell:
                d_cell = {"value": d_val}
            
            # E列确保有data_validation
            e_cell = row[3] if len(row) > 3 and row[3] else {}
            if "data_validation" not in e_cell:
                e_cell = make_violation_cell(e_val)
            else:
                e_cell["value"] = e_val
            
            # F列确保有data_validation和multiple_values
            f_cell = row[4] if len(row) > 4 and row[4] else {}
            if "data_validation" not in f_cell or "multiple_values" not in f_cell:
                f_cell = make_multi_cell(f_val)
            else:
                f_cell["value"] = f_val
                # 重新生成multiple_values以匹配当前值
                items = [v.strip() for v in f_val.split(",") if v.strip()]
                f_cell["multiple_values"] = [{"value": v} for v in items]
            
            b_cell = {"value": b_val}
            c_cell = {"value": c_val}
            
            normalized = [b_cell, c_cell, d_cell, e_cell, f_cell]
            all_rows.append(normalized)
        print(f"  ✓ 读取 rows {start}-{end}")
    
    print(f"  共读取 {len(all_rows)} 行")
    return all_rows


def analyze(rows, label="分布"):
    vios = []
    for cols in rows:
        val = cols[3].get("value", "") if len(cols) > 3 else ""
        vios.append(val)
    cnt = Counter(vios)
    max_s = 0
    cur_v = None
    cur_l = 0
    for v in vios:
        if v == cur_v:
            cur_l += 1
        else:
            cur_v = v
            cur_l = 1
        max_s = max(max_s, cur_l)
    d_ok = sum(1 for r in rows if "rich_text" in r[2] and r[2]["value"].startswith("http"))
    f_ok = sum(1 for r in rows if "multiple_values" in r[4])
    print(f"\n【{label}】 是:{cnt.get('是',0)} 否:{cnt.get('否',0)} 最长连续:{max_s}")
    print(f"  D列超链接: {d_ok}/{len(rows)}  F列多选: {f_ok}/{len(rows)}")
    print(f"  前30: {' '.join(vios[:30])}")


def write_cells(rows):
    print(f"\n写入 {DATA_RANGE} ...")
    chunk_size = 50
    total = len(rows)
    for chunk_start in range(0, total, chunk_size):
        chunk = rows[chunk_start:chunk_start + chunk_size]
        start_row = START_ROW + chunk_start
        end_row = start_row + len(chunk) - 1
        rng = f"B{start_row}:F{end_row}"
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, dir=tempfile.gettempdir(), encoding='utf-8') as f:
            json.dump(chunk, f, ensure_ascii=False)
            tmp = f.name
        try:
            with open(tmp, 'r', encoding='utf-8') as pf:
                resp = run_lark([
                    "sheets", "+cells-set",
                    "--spreadsheet-token", SPREADSHEET_TOKEN,
                    "--sheet-id", SHEET_ID,
                    "--range", rng,
                    "--cells", "-",
                ], stdin_text=pf.read())
            if not resp.get("ok"):
                print(f"WRITE FAIL: {resp}", file=sys.stderr)
                sys.exit(1)
            print(f"  ✓ 写入 rows {start_row}-{end_row}")
        finally:
            os.unlink(tmp)


def main():
    print("=" * 60)
    print("随机整行打乱（保留超链接、下拉多选格式）")
    print(f"范围: {DATA_RANGE}")
    print("=" * 60)

    # 1. 读取并补全格式
    print("\n[1/3] 读取并补全格式...")
    rows = read_and_normalize()
    analyze(rows, "打乱前")

    # 2. 随机打乱
    print("\n[2/3] 随机打乱...")
    random.shuffle(rows)
    analyze(rows, "打乱后")

    # 3. 写入
    print("\n[3/3] 写回表格...")
    write_cells(rows)

    print("\n" + "=" * 60)
    print("✅ 完成！D列超链接、E/F列下拉多选已保留")
    print("=" * 60)
    
    # 验证
    print("\n验证...")
    verify = read_and_normalize()
    analyze(verify, "实际结果")


if __name__ == "__main__":
    main()
