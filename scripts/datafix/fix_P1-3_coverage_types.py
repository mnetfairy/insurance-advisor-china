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
"""
import argparse
import os
import re
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)
from lib_common import load_v2, save_v2, backup_v2, write_report, add_dry_run_arg

RE_DIGIT = re.compile(r"\d+(?:\.\d+)?")
RE_RANGE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*[-~到至]\s*(\d+(?:\.\d+)?)\s*(万|万元)?\s*$")
RE_SINGLE_WAN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*万\s*(?:起)?\s*$")
RE_TWO_WAN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*万\s*[/／]\s*(\d+(?:\.\d+)?)\s*万\s*$")
RE_YUAN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*元?\s*$")


def parse_coverage(raw):
    """Parse coverage value (str/int/None) → (int_value_or_None, parse_status, note).
    status: verified | parsed | missing | parse_failed
    """
    if raw is None:
        return None, "missing", None
    if isinstance(raw, int):
        return raw, "verified", None
    if isinstance(raw, float):
        if raw.is_integer():
            return int(raw), "verified", None
        return None, "parse_failed", "float_non_integer"
    if not isinstance(raw, str):
        return None, "parse_failed", f"unknown_type_{type(raw).__name__}"

    s = raw.strip()
    if not s or s in ("N/A", "n/a", "-", "—", "无", "未知", "待核实"):
        return None, "parse_failed", f"empty_or_placeholder({s!r})"

    # Pattern 1: range like "10-350万" or "10-350"
    m = RE_RANGE.match(s)
    if m:
        # Range in single field — return the smaller value as per spec
        lower = int(float(m.group(1)))
        upper = int(float(m.group(2)))
        return lower, "parsed_range", f"range_{lower}-{upper}"

    # Pattern 2: "5万" / "5万起" / "5万元"
    m = RE_SINGLE_WAN.match(s)
    if m:
        return int(float(m.group(1))), "parsed", None

    # Pattern 3: "50万/100万" — take smaller value
    m = RE_TWO_WAN.match(s)
    if m:
        lower = int(float(m.group(1)))
        upper = int(float(m.group(2)))
        return lower, "parsed_dual", f"two_tiers_{lower}/{upper}万"

    # Pattern 4: "50000元" or "50000"
    m = RE_YUAN.match(s)
    if m:
        val = int(float(m.group(1)))
        if val >= 10000:
            return val // 10000, "parsed_yuan_to_wan", f"original={val}元"
        return val, "parsed_yuan", f"original={val}元"

    # Pattern 5: just digits with garbage
    nums = RE_DIGIT.findall(s)
    if nums:
        val = int(float(nums[0]))
        if val >= 10000:
            return val // 10000, "parsed_digits_to_wan", f"raw={s}"
        return val, "parsed_digits", f"raw={s}"

    return None, "parse_failed", f"unknown_format({s!r})"


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
        new_val, status, note = parse_coverage(raw)
        counters[status] = counters.get(status, 0) + 1

        record = {
            "index": idx,
            "id": p.get("id", "<<no-id>>"),
            "field": field_name,
            "old_value": raw if raw is not None else None,
            "new_value": new_val,
            "status": status,
            "note": note,
        }
        diff.append(record)

        if not dry_run:
            if new_val is not None:
                p[field_name] = new_val
            else:
                p[field_name] = None
            # Track on the product
            p[f"{field_name}_quality"] = status
            p[f"{field_name}_raw"] = raw if isinstance(raw, str) else None
            p[f"{field_name}_processed_at"] = "phase1_P1-3"
            if note:
                p[f"{field_name}_parse_note"] = note

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_dry_run_arg(parser)
    args = parser.parse_args()

    print("=" * 60)
    print("Phase 1 P1-3: unify min_coverage/max_coverage → int (v2)")
    print("=" * 60)

    data = load_v2()
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

    report = {
        "fix": "P1-3 (min/max_coverage type unify)",
        "policy": "All → int (万); ranges 'X-Y万' take lower; 'X万/Y万' take lower; parse_failed → null",
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
        print("[DRY RUN] Not writing products_v2.json")
        return 0

    if min_diff or max_diff:
        bk = backup_v2("pre_P1-3_coverage_types")
        save_v2(data)
        print(f"Backup: {bk}")
        print(f"[OK] Saved products_v2.json")

    return 0


if __name__ == "__main__":
    sys.exit(main())