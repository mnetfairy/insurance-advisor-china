#!/usr/bin/env python3
"""
Phase 1 P0-1: Clean name for 37 '待分类' products.

Per master spec, strategy B (preferred): try to infer real product name from notes/subtype/type.
Strategy A fallback: if can't infer, set name = "<未识别产品-{id}>".

37 products all have:
  - type="待分类"
  - id prefix = "tavily-"
  - name = crawler's residual sentence (garbage)
  - subtype=None, notes='' mostly

We'll:
  1. Try to extract a real product name from the garbage name string
     (e.g. "推出了信泰如意久久守护2025重大疾病保险" → "信泰如意久久守护2025重大疾病保险")
  2. If extraction fails → name = "<未识别产品-{id}>"
  3. Mark with data_quality="garbage" + original_name + original_index
  4. **Keep in products[] but with data_quality flag** (master spec: 不删/不丢；SA's plan to move to _quarantine is Phase 2/3 work — we just flag)
  
Per master: "37 款产品的修复前后对照表" — generate diff report.

Idempotent: re-running on already-cleaned products is no-op (data_quality already set).
"""
import argparse
import os
import re
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)
from lib_common import load_v2, save_v2, backup_v2, write_report, add_dry_run_arg

GARBAGE_KW = [
    "推出了", "推出20", "在202", "2025年推出", "2025年新", "继续推动", "致力于",
    "和万能型", "和附加", "和重疾险", "总保费", "创新推出", "包括", "和养老服务",
    "为互联网专属", "2025推出了", "推出了多款", "推出科技",
]


def is_garbage(name):
    if not isinstance(name, str):
        return True
    if any(kw in name for kw in GARBAGE_KW):
        return True
    if len(name) > 25 and "保险" not in name:
        return True
    return False


# Extract real product name from a garbage sentence.
# Patterns observed:
#   "推出了信泰如意久久守护2025重大疾病保险" → "信泰如意久久守护2025重大疾病保险"
#   "推出了2025年的新产品" → 不可推断 → None
#   "和万能型终身寿险" → "万能型终身寿险"
#   "和附加定期寿险" → "附加定期寿险"
#   "推出了泰盈人生2026分红型年金保险" → "泰盈人生2026分红型年金保险"
PRODUCT_NAME_HINTS = ["保险", "寿险", "年金", "重疾", "医疗", "意外", "防癌"]


def infer_real_name(garbage):
    """Try to extract a real product name from a garbage sentence.
    Returns cleaned name, or None if cannot infer."""
    if not isinstance(garbage, str):
        return None
    s = garbage.strip()

    # Strip common sentence starters
    starters = [
        r"^推出了", r"^推出20\d{2}", r"^在20\d{2}年?", r"^2025年?",
        r"^20\d{2}年?", r"^继续推动", r"^致力于", r"^创新推出",
        r"^为互联网", r"^包括", r"^总保费", r"^和",
    ]
    for pat in starters:
        new = re.sub(pat, "", s, count=1).strip()
        if new and new != s:
            s = new

    # Remove trailing/leading filler like "（分红型）" keep parentheses content
    # Try to find a substring that looks like a real product name.
    # Heuristic: split by common delimiters and find longest segment containing "保险"/"寿险"/"年金"
    candidates = re.split(r"[、，,。；;]+", s)
    best = None
    for c in candidates:
        c = c.strip()
        # Skip candidates that are clearly residual fragments
        if c.startswith(("的", "年", "新")):
            continue
        if any(h in c for h in PRODUCT_NAME_HINTS):
            if best is None or len(c) > len(best):
                best = c

    # If no candidate with product hints, try direct regex
    if not best:
        m = re.search(r"([\u4e00-\u9fff]+(?:保险|寿险|年金|重疾|医疗|意外|防癌)[\u4e00-\u9fff（()）\d]*)", s)
        if m:
            cand = m.group(1)
            # Strip leading particles like "的", "年"
            cand = re.sub(r"^([的年新]{1,3})", "", cand)
            if cand and len(cand) >= 4:
                best = cand

    if best and len(best) >= 4 and is_garbage(best) is False and not best.startswith(("的", "年")):
        return best
    return None


def fix(data, dry_run=False):
    """Process the 37 '待分类' products. Returns diff."""
    prods = data["products"]
    diff = []
    for idx, p in enumerate(prods):
        if p.get("type") != "待分类":
            continue
        # Already cleaned?
        if p.get("data_quality") == "garbage" and p.get("name_cleaned_at"):
            continue

        old_name = p.get("name")
        old_id = p.get("id", "")
        inferred = infer_real_name(old_name)

        if inferred:
            new_name = inferred
            new_id = old_id  # keep original tavily id
            infer_status = "inferred"
        else:
            # Fallback strategy A: <未识别产品-{id}>
            new_name = f"<未识别产品-{old_id}>" if old_id else f"<未识别产品-idx{idx}>"
            new_id = old_id
            infer_status = "fallback"

        record = {
            "index": idx,
            "id": old_id,
            "old_name": old_name,
            "new_name": new_name,
            "infer_status": infer_status,
            "type": p.get("type"),
            "subtype": p.get("subtype"),
            "notes": p.get("notes", "")[:60],
            "company": p.get("company"),
            "action": "name_cleaned",
        }
        diff.append(record)

        if not dry_run:
            p["name"] = new_name
            p["data_quality"] = "garbage"
            p["original_name"] = old_name
            p["name_cleaned_at"] = "phase1_P0-1"

    return diff


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_dry_run_arg(parser)
    args = parser.parse_args()

    print("=" * 60)
    print("Phase 1 P0-1: clean name for 37 '待分类' products (v2)")
    print("=" * 60)

    data = load_v2()
    n_daifen = sum(1 for p in data["products"] if p.get("type") == "待分类")
    n_already = sum(1 for p in data["products"]
                    if p.get("type") == "待分类" and p.get("data_quality") == "garbage"
                    and p.get("name_cleaned_at"))
    print(f"Found {n_daifen} '待分类' products ({n_already} already cleaned)")

    diff = fix(data, dry_run=args.dry_run)
    print(f"\nWill process: {len(diff)} products")

    inferred = sum(1 for r in diff if r["infer_status"] == "inferred")
    fallback = sum(1 for r in diff if r["infer_status"] == "fallback")
    print(f"  Inferred (Strategy B): {inferred}")
    print(f"  Fallback (Strategy A): {fallback}")

    print(f"\nDiff (first 15):")
    print(f"{'idx':>5s}  {'id':25s}  {'status':10s}  {'old':40s} → {'new':40s}")
    print("-" * 130)
    for r in diff[:15]:
        print(f"{r['index']:5d}  {r['id']:25s}  {r['infer_status']:10s}  "
              f"{r['old_name'][:38]:40s} → {r['new_name'][:40]:40s}")

    report = {
        "fix": "P0-1 (待分类 name clean)",
        "policy": "Strategy B (infer from sentence) → Strategy A (fallback <未识别产品-{id}>)",
        "total_daifen_products": n_daifen,
        "already_cleaned": n_already,
        "processed": len(diff),
        "inferred_count": inferred,
        "fallback_count": fallback,
        "diff": diff,
        "dry_run": args.dry_run,
    }
    rp = write_report("P0-1_name_clean_report.json", report)
    print(f"\nReport: {rp}")

    if args.dry_run:
        print("[DRY RUN] Not writing products_v2.json")
        return 0

    if diff:
        bk = backup_v2("pre_P0-1_name_clean")
        save_v2(data)
        print(f"Backup: {bk}")
        print(f"[OK] Saved products_v2.json")

    return 0


if __name__ == "__main__":
    sys.exit(main())