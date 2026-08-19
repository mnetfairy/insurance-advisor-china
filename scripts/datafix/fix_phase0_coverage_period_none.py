#!/usr/bin/env python3
"""
Phase 0.2: Fix products with coverage_period = None (or missing) in v2.

Per master spec: option C — both script defense (already done in fix_phase0_premium_calculator.py)
AND datafix the 112 None values to '未明确' so future tools don't need to defensively code.

Policy:
  - 112 products with None → set coverage_period = "未明确"
  - Add field coverage_period_quality = "missing" for traceability
  - Preserve the product in products[] (do NOT delete — that's P0-1's job)

Idempotent: re-running detects already-fixed products (coverage_period != None) and is no-op.
"""
import argparse
import os
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)
from lib_common import (
    load_v2, save_v2, backup_v2, write_report,
    add_dry_run_arg, die, ok, DEFAULT_NONE_FILL,
)

NONE_FILL = DEFAULT_NONE_FILL  # "未明确"


def fix_coverage_period(data, dry_run=False):
    """Set None coverage_period → '未明确'. Returns (changed_count, samples)."""
    prods = data.get("products", [])
    changed = 0
    samples = []
    for idx, p in enumerate(prods):
        if p.get("coverage_period") is None:
            old_val = "<<MISSING>>" if "coverage_period" not in p else None
            p["coverage_period"] = NONE_FILL
            p["coverage_period_quality"] = "missing"
            changed += 1
            if len(samples) < 10:
                samples.append({
                    "index": idx,
                    "id": p.get("id", "<<no-id>>"),
                    "name": (p.get("name") or "")[:50],
                    "type": p.get("type"),
                    "old_coverage_period": old_val,
                    "new_coverage_period": NONE_FILL,
                    "quality": "missing",
                })
    return changed, samples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_dry_run_arg(parser)
    args = parser.parse_args()

    print("=" * 60)
    print("Phase 0.2: datafix coverage_period=None → '未明确' (v2)")
    print("=" * 60)

    data = load_v2()
    n_before = sum(1 for p in data["products"] if p.get("coverage_period") is None)
    print(f"Before: {n_before} products with coverage_period=None")

    if n_before == 0:
        print("[INFO] Already fixed (idempotent no-op)")
        return 0

    changed, samples = fix_coverage_period(data, dry_run=args.dry_run)
    n_after = sum(1 for p in data["products"] if p.get("coverage_period") is None)

    print(f"After:  {n_after} products with coverage_period=None")
    print(f"Changed: {changed} products")

    print("\nSample changes (first 10):")
    for s in samples:
        print(f"  [{s['index']:4d}] id={s['id'][:25]:25s} type={s['type']:10s} name={s['name'][:30]}")

    report = {
        "fix": "P0-2 (coverage_period None)",
        "policy": "None → '未明确' + coverage_period_quality=missing",
        "before_none_count": n_before,
        "after_none_count": n_after,
        "changed_count": changed,
        "samples": samples,
        "dry_run": args.dry_run,
    }
    rp = write_report("P0-2_coverage_period_none_report.json", report)
    print(f"\nReport: {rp}")

    if args.dry_run:
        print("[DRY RUN] Not writing products_v2.json")
        return 0

    # Backup then save
    bk = backup_v2("pre_P0-2_coverage_period_none")
    save_v2(data)
    print(f"Backup: {bk}")
    print(f"[OK] Saved products_v2.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())