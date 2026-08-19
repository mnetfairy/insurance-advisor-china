#!/usr/bin/env python3
"""
Phase 1 P0-2: Normalize listing_time to YYYY-MM.

Master spec:
  - 4 formats coexist: YYYY-MM(483) / YYYY(40) / YYYY-MM-DD(37) / null(75)
  - Unify to YYYY-MM
  - YYYY → YYYY-01 (assume January)
  - YYYY-MM-DD → YYYY-MM (take first 7 chars)
  - null → keep null (don't guess)

Add listing_time_quality enum: verified | estimated | missing | unknown
Per SA design (and QA recommend):
  - verified: was YYYY-MM already
  - estimated: was YYYY (we guessed -01) or YYYY-MM-DD (we truncated)
  - missing: was null
  - unknown: was something else (e.g. '待核实')

Idempotent.
"""
import argparse
import os
import re
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)
from lib_common import load_v2, save_v2, backup_v2, write_report, add_dry_run_arg


RE_YYYY = re.compile(r"^\d{4}$")
RE_YYYY_MM = re.compile(r"^\d{4}-\d{2}$")
RE_YYYY_MM_DD = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def classify(lt):
    """Return (quality, normalized) — normalized is the YYYY-MM form or None."""
    if lt is None:
        return "missing", None
    if not isinstance(lt, str):
        return "unknown", None
    s = lt.strip()
    if not s:
        return "missing", None
    if RE_YYYY_MM.match(s):
        return "verified", s
    if RE_YYYY.match(s):
        return "estimated", s + "-01"
    if RE_YYYY_MM_DD.match(s):
        return "estimated", s[:7]
    # Anything else (待核实, etc.) — unknown; record original raw
    return "unknown", None


def fix(data, dry_run=False):
    prods = data["products"]
    diff = []
    counters = {"verified": 0, "estimated": 0, "missing": 0, "unknown": 0}
    raw_dist = {}  # original format distribution

    for idx, p in enumerate(prods):
        # Skip if already processed
        if "listing_time_quality" in p and "listing_time_processed_at" in p:
            continue

        lt = p.get("listing_time")
        # Count raw distribution (before fix)
        if lt is None:
            raw_dist["null"] = raw_dist.get("null", 0) + 1
        elif isinstance(lt, str):
            if RE_YYYY_MM.match(lt):
                raw_dist["YYYY-MM"] = raw_dist.get("YYYY-MM", 0) + 1
            elif RE_YYYY.match(lt):
                raw_dist["YYYY"] = raw_dist.get("YYYY", 0) + 1
            elif RE_YYYY_MM_DD.match(lt):
                raw_dist["YYYY-MM-DD"] = raw_dist.get("YYYY-MM-DD", 0) + 1
            elif lt == "待核实":
                raw_dist["待核实"] = raw_dist.get("待核实", 0) + 1
            else:
                raw_dist[f"other({lt[:15]})"] = raw_dist.get(f"other({lt[:15]})", 0) + 1

        quality, normalized = classify(lt)
        counters[quality] += 1

        record = {
            "index": idx,
            "id": p.get("id", "<<no-id>>"),
            "old_listing_time": lt if lt is not None else None,
            "new_listing_time": normalized,
            "quality": quality,
        }

        if not dry_run:
            if normalized is not None:
                p["listing_time"] = normalized
            else:
                p["listing_time"] = None  # normalize None and unknown → null
            if quality == "unknown" and lt is not None:
                p["listing_time_raw"] = lt  # preserve original raw for unknown
            p["listing_time_quality"] = quality
            p["listing_time_processed_at"] = "phase1_P0-2"

        diff.append(record)

    return diff, counters, raw_dist


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_dry_run_arg(parser)
    args = parser.parse_args()

    print("=" * 60)
    print("Phase 1 P0-2: normalize listing_time → YYYY-MM (v2)")
    print("=" * 60)

    data = load_v2()
    n_already = sum(1 for p in data["products"] if "listing_time_processed_at" in p)
    print(f"Already processed: {n_already} products")

    diff, counters, raw_dist = fix(data, dry_run=args.dry_run)

    print(f"\nRaw listing_time distribution (before): {raw_dist}")
    print(f"\nQuality counter: {counters}")

    # Sample diffs (only show actual changes)
    print(f"\nSample diffs (changes only, first 10):")
    changes = [d for d in diff if d["old_listing_time"] != d["new_listing_time"]]
    for d in changes[:10]:
        print(f"  idx={d['index']:4d} id={d['id'][:25]:25s}  {str(d['old_listing_time']):20s} → {str(d['new_listing_time']):10s}  [{d['quality']}]")

    print(f"\nTotal changes: {len(changes)} of {len(diff)} products")

    report = {
        "fix": "P0-2 (listing_time normalize)",
        "policy": "YYYY→YYYY-01 (estimated) | YYYY-MM-DD→YYYY-MM (estimated) | null→null (missing) | 待核实→null (unknown, raw preserved)",
        "raw_distribution_before": raw_dist,
        "quality_counter": counters,
        "total_products": len(diff),
        "changes_count": len(changes),
        "samples": changes[:30],
        "dry_run": args.dry_run,
    }
    rp = write_report("P0-2_listing_time_report.json", report)
    print(f"\nReport: {rp}")

    if args.dry_run:
        print("[DRY RUN] Not writing products_v2.json")
        return 0

    if diff:
        bk = backup_v2("pre_P0-2_listing_time")
        save_v2(data)
        print(f"Backup: {bk}")
        print(f"[OK] Saved products_v2.json")

    return 0


if __name__ == "__main__":
    sys.exit(main())