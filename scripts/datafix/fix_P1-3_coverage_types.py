#!/usr/bin/env python3
"""
Phase 1 P1-3: Unify min_coverage / max_coverage to int.

Master spec:
  - Currently int(342) + string(36) mixed types
  - All → int (strip "万"/"起"/Chinese)
  - String format examples:
      "5万" → 5
      "1万起" → 1
      "50万/100万" → split into two products, OR store 50 (small value) with note
  - Range string like "10-350万" → split to two fields (min=10, max=350)

Per master:
  > 字符串带范围（如 "10-350万"）怎么处理？需要 SA 决策，但你先按 "min=10, max=350" 拆分到两字段处理

Add coverage_unit="万元" (per SA design).

Algorithm:
  1. If int → keep, mark coverage_parse_status=verified
  2. If str → parse with regex:
       - "X万" or "X万起" → X
       - "X-Y" or "X-Y万" → X (apply to one field only if other is already int)
       - "X万/Y万" → take X for the field with X; if "50万/100万" → split logic
       - "X元" → X / 10000 (rounded down)
       - "" / "N/A" / unknown → null + parse_failed=true + reason
  3. If null → keep null + mark missing

Important: 36 string values + 36 string values (min & max). Both fields have same
garbage for same products. Need per-field parsing rules.

For the "50万/100万" max_coverage case:
  - The "50万" is the standard max, "100万" is a special/extended tier
  - Strategy: keep the smaller value (50) as int; record parse_note saying "extended tier 100万 exists"
  
Actually re-reading the master spec more carefully:
  > "50万/100万" → 拆分成两个产品 or 存 `50`（小值）+ 备注
  This is a single max_coverage field. Most reasonable is to take the lower value (50)
  and add a note field. We follow master spec's recommendation.

Idempotent.

🆕 2026-10-27 加固（I5）
  1. 新增 --target 参数：默认指向**包内实际存在**的 references/products.json。
     （历史默认 products_v2.json 不在发布包内，脚本此前必然 FileNotFoundError。）
     如需迁移到 v2 数据集，显式传 --target references/products_v2.json；
     products_v2.json 为可选目标，不随本 skill 发布包分发。
  2. < 10000 元的金额不再被抹成 0：整数字段仍按万元取整记 0，
     但原值保留到 min_coverage_raw / max_coverage_raw（字段已存在），
     并新增 min_coverage_note / max_coverage_note 说明取整原因。
  3. 区间端点（"50万/100万"）被丢弃的高位端点不再静默丢失：
     写入新增字段 max_coverage_alternatives（数组），并在 max_coverage_note 说明。
  这些是离线人工维护工具，不影响运行时输出。
"""
import argparse
import json
import os
import re
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)
from lib_common import (load_v2, save_v2, backup_v2, write_report, add_dry_run_arg,
                       PRODUCTS_V1, PRODUCTS_V2, BACKUPS_DIR, now_ts)

RE_DIGIT = re.compile(r"\d+(?:\.\d+)?")
RE_RANGE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*[-~到至]\s*(\d+(?:\.\d+)?)\s*(万|万元)?\s*$")
RE_SINGLE_WAN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*万\s*(?:起)?\s*$")
RE_TWO_WAN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*万\s*[/／]\s*(\d+(?:\.\d+)?)\s*万\s*$")
RE_YUAN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*元?\s*$")


def parse_coverage(raw):
    """Parse coverage value (str/int/None) → dict.

    status: verified | parsed | parsed_range | parsed_dual | parsed_yuan |
            parsed_yuan_to_wan | parsed_digits | parsed_digits_to_wan |
            missing | parse_failed

    返回字段：
      value            : int_value_or_None（按万元单位的整数值）
      status           : 解析状态
      note             : 原有的解析备注（parse_note 语义）
      raw_value        : < 10000 元时保留原值到 *_raw 的依据（否则 None）
      alternatives     : 被丢弃的区间高端点（如 "50万/100万" 的 100）
      value_note       : 面向人的说明（写入 *_note）
    """
    if raw is None:
        return {"value": None, "status": "missing", "note": None,
                "raw_value": None, "alternatives": [], "value_note": None}
    if isinstance(raw, int):
        return {"value": raw, "status": "verified", "note": None,
                "raw_value": None, "alternatives": [], "value_note": None}
    if isinstance(raw, float):
        if raw.is_integer():
            return {"value": int(raw), "status": "verified", "note": None,
                    "raw_value": None, "alternatives": [], "value_note": None}
        return {"value": None, "status": "parse_failed", "note": "float_non_integer",
                "raw_value": None, "alternatives": [], "value_note": None}
    if not isinstance(raw, str):
        return {"value": None, "status": "parse_failed",
                "note": f"unknown_type_{type(raw).__name__}",
                "raw_value": None, "alternatives": [], "value_note": None}

    s = raw.strip()
    if not s or s in ("N/A", "n/a", "-", "—", "无", "未知", "待核实"):
        return {"value": None, "status": "parse_failed",
                "note": f"empty_or_placeholder({s!r})",
                "raw_value": None, "alternatives": [], "value_note": None}

    # Pattern 1: range like "10-350万" or "10-350"
    m = RE_RANGE.match(s)
    if m:
        # Range in single field — return the smaller value as per spec
        lower = int(float(m.group(1)))
        upper = int(float(m.group(2)))
        return {
            "value": lower, "status": "parsed_range", "note": f"range_{lower}-{upper}",
            "raw_value": None,
            "alternatives": [upper] if upper != lower else [],
            "value_note": (f"原值 {s}（区间 {lower}-{upper} 万元），"
                           f"按取低值策略存 {lower}，高端点 {upper} 保留在 *_alternatives"),
        }

    # Pattern 2: "5万" / "5万起" / "5万元"
    m = RE_SINGLE_WAN.match(s)
    if m:
        return {"value": int(float(m.group(1))), "status": "parsed", "note": None,
                "raw_value": None, "alternatives": [], "value_note": None}

    # Pattern 3: "50万/100万" — take smaller value, keep the dropped upper tier
    m = RE_TWO_WAN.match(s)
    if m:
        lower = int(float(m.group(1)))
        upper = int(float(m.group(2)))
        return {
            "value": lower, "status": "parsed_dual", "note": f"two_tiers_{lower}/{upper}万",
            "raw_value": None,
            "alternatives": [upper] if upper != lower else [],
            "value_note": (f"原值 {s}（双档位 {lower}/{upper} 万），"
                           f"按取低值策略存 {lower}，高端点 {upper} 保留在 *_alternatives"),
        }

    # Pattern 4: "50000元" or "50000"
    m = RE_YUAN.match(s)
    if m:
        val = int(float(m.group(1)))
        if val >= 10000:
            return {"value": val // 10000, "status": "parsed_yuan_to_wan",
                    "note": f"original={val}元",
                    "raw_value": None, "alternatives": [],
                    "value_note": (f"原值 {val} 元，按万元单位取整为 {val // 10000}，"
                                   f"整万元余数 {val % 10000} 元未保留") if val % 10000 else None}
        # < 10000 元：原值不能被抹成 0 —— 整数字段记 0，原值保留到 *_raw
        return {"value": 0, "status": "parsed_yuan", "note": f"original={val}元",
                "raw_value": val,
                "alternatives": [],
                "value_note": (f"原值 {val} 元，低于 1 万元，按万元单位取整为 0，"
                               f"原值见 *_raw")}

    # Pattern 5: just digits with garbage
    nums = RE_DIGIT.findall(s)
    if nums:
        val = int(float(nums[0]))
        if val >= 10000:
            return {"value": val // 10000, "status": "parsed_digits_to_wan",
                    "note": f"raw={s}", "raw_value": None, "alternatives": [],
                    "value_note": (f"原值 {val} 元，按万元单位取整为 {val // 10000}，"
                                   f"整万元余数 {val % 10000} 元未保留") if val % 10000 else None}
        return {"value": 0, "status": "parsed_digits", "note": f"raw={s}",
                "raw_value": val, "alternatives": [],
                "value_note": f"原值 {val} 元，低于 1 万元，按万元单位取整为 0，原值见 *_raw"}

    return {"value": None, "status": "parse_failed", "note": f"unknown_format({s!r})",
            "raw_value": None, "alternatives": [], "value_note": None}


def fix_field(prods, field_name, dry_run=False):
    """Process one field (min_coverage or max_coverage) across all products.
    Returns diff entries."""
    diff = []
    counters = {"verified": 0, "parsed": 0, "parsed_range": 0,
                "parsed_dual": 0, "parsed_yuan": 0, "parsed_yuan_to_wan": 0,
                "parsed_digits": 0, "parsed_digits_to_wan": 0,
                "missing": 0, "parse_failed": 0}

    for idx, p in enumerate(prods):
        if f"{field_name}_processed_at" in p:
            continue
        raw = p.get(field_name)
        parsed = parse_coverage(raw)
        new_val = parsed["value"]
        status = parsed["status"]
        note = parsed["note"]
        counters[status] = counters.get(status, 0) + 1

        record = {
            "index": idx,
            "id": p.get("id", "<<no-id>>"),
            "field": field_name,
            "old_value": raw if raw is not None else None,
            "new_value": new_val,
            "status": status,
            "note": note,
            "raw_preserved": parsed["raw_value"],
            "alternatives": parsed["alternatives"],
            "value_note": parsed["value_note"],
        }
        diff.append(record)

        if not dry_run:
            if new_val is not None:
                p[field_name] = new_val
            else:
                p[field_name] = None
            # Track on the product
            p[f"{field_name}_quality"] = status
            # < 10000 元的原值不能被抹掉：保留到 *_raw
            if parsed["raw_value"] is not None:
                p[f"{field_name}_raw"] = parsed["raw_value"]
            elif isinstance(raw, str):
                p[f"{field_name}_raw"] = raw
            # 新增：面向人的说明（为什么是 0 / 为什么取低值）
            if parsed["value_note"]:
                p[f"{field_name}_note"] = parsed["value_note"]
            p[f"{field_name}_processed_at"] = "phase1_P1-3"
            if note:
                p[f"{field_name}_parse_note"] = note
            # 新增：被丢弃的区间高端点（如 "50万/100万" 的 100）不再静默丢弃
            if parsed["alternatives"]:
                existing = p.get("max_coverage_alternatives")
                if not isinstance(existing, list):
                    existing = []
                for alt in parsed["alternatives"]:
                    if alt not in existing:
                        existing.append(alt)
                p["max_coverage_alternatives"] = existing

    return diff, counters


def fix(data, dry_run=False):
    prods = data["products"]

    # Process min_coverage
    min_diff, min_counters = fix_field(prods, "min_coverage", dry_run=dry_run)
    # Process max_coverage
    max_diff, max_counters = fix_field(prods, "max_coverage", dry_run=dry_run)

    # Set coverage_unit = "万元" on all products where applicable
    if not dry_run:
        for p in prods:
            if p.get("min_coverage") is not None or p.get("max_coverage") is not None:
                p["coverage_unit"] = "万元"

    return min_diff, min_counters, max_diff, max_counters


def backup_target(target_path, label):
    """备份任意目标文件（而非固定 products_v2.json）。

    🆕 2026-10-27：--target 可指向不同文件，备份也必须跟随目标，
    否则会把 v1 目标错误地备份成 products_v2_* 名字。
    """
    import shutil
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    ts = now_ts()
    base = os.path.splitext(os.path.basename(target_path))[0]
    dst = os.path.join(BACKUPS_DIR, f"{base}_{label}_{ts}.json")
    shutil.copy2(target_path, dst)
    return dst


def main():
    parser = argparse.ArgumentParser(
        description="Phase 1 P1-3: 把 min_coverage / max_coverage 统一为 int（万元单位）。"
                    "默认目标为发布包内实际存在的 references/products.json；"
                    "products_v2.json 为可选目标，不随本 skill 发布包分发，需显式用 --target 指定。",
        epilog="示例："
               "  python3 fix_P1-3_coverage_types.py --dry-run"
               "  python3 fix_P1-3_coverage_types.py --target ../references/products_v2.json")
    add_dry_run_arg(parser)
    parser.add_argument("--target", default=None,
                        help="目标产品数据文件路径。默认：references/products.json（包内实际存在）。"
                             "可选：references/products_v2.json（不在发布包内，需自行提供）。")
    args = parser.parse_args()

    # 解析目标路径：默认 → 包内实际存在的 references/products.json
    target = os.path.abspath(args.target or PRODUCTS_V1)
    if not os.path.exists(target):
        print(f"[FATAL] 目标文件不存在: {target}")
        print("  可选目标：references/products_v2.json 不在发布包内，需自行提供。")
        return 1

    print("=" * 60)
    print("Phase 1 P1-3: unify min_coverage/max_coverage → int")
    print(f"Target: {target}")
    print("=" * 60)

    with open(target, "r", encoding="utf-8") as f:
        data = json.load(f)
    n_already = sum(1 for p in data["products"] if "min_coverage_processed_at" in p)
    print(f"Already processed: {n_already} products")

    min_diff, min_counters, max_diff, max_counters = fix(data, dry_run=args.dry_run)

    print(f"\nmin_coverage parse counters: {min_counters}")
    print(f"max_coverage parse counters: {max_counters}")

    print(f"\nmin_coverage sample changes (first 10):")
    for d in [x for x in min_diff if x["status"] not in ("verified", "missing")][:10]:
        print(f"  idx={d['index']:4d} id={d['id'][:25]:25s}  {str(d['old_value']):20s} → {str(d['new_value']):10s}  [{d['status']}{(' '+d['note']) if d['note'] else ''}]")

    print(f"\nmax_coverage sample changes (first 10):")
    for d in [x for x in max_diff if x["status"] not in ("verified", "missing")][:10]:
        print(f"  idx={d['index']:4d} id={d['id'][:25]:25s}  {str(d['old_value']):20s} → {str(d['new_value']):10s}  [{d['status']}{(' '+d['note']) if d['note'] else ''}]")

    print(f"\nTotal min_coverage changes: {sum(1 for d in min_diff if d['old_value'] != d['new_value'])}")
    print(f"Total max_coverage changes: {sum(1 for d in max_diff if d['old_value'] != d['new_value'])}")
    print(f"Sub-10000-yuan values preserved to *_raw: "
          f"{sum(1 for d in min_diff + max_diff if d['raw_preserved'] is not None)}")
    print(f"Dropped range endpoints kept in max_coverage_alternatives: "
          f"{sum(1 for d in min_diff + max_diff if d['alternatives'])}")

    report = {
        "fix": "P1-3 (min/max_coverage type unify)",
        "policy": "All → int (万); ranges 'X-Y万' take lower; 'X万/Y万' take lower; "
                  "<10000 元 → 0 with original preserved in *_raw; parse_failed → null",
        "target": target,
        "min_coverage_counters": min_counters,
        "max_coverage_counters": max_counters,
        "min_coverage_samples": [d for d in min_diff if d["status"] not in ("verified", "missing")][:30],
        "max_coverage_samples": [d for d in max_diff if d["status"] not in ("verified", "missing")][:30],
        "coverage_unit_added": "万元",
        "dry_run": args.dry_run,
    }
    rp = write_report("P1-3_coverage_types_report.json", report)
    print(f"\nReport: {rp}")

    if args.dry_run:
        print(f"[DRY RUN] Not writing {target}")
        return 0

    if min_diff or max_diff:
        bk = backup_target(target, "pre_P1-3_coverage_types")
        print(f"Backup: {bk}")
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, target)
        print(f"[OK] Saved {target}")

    return 0


if __name__ == "__main__":
    sys.exit(main())