#!/usr/bin/env python3
"""
Phase 1 P1-4: Fix delisting_time vs validity_status conflicts.

Master spec:
  > P1-4：`delisting_time="仍在售"` 与 `validity_status="DISCONTINUED"` 冲突
  > 449 个"仍在售"产品里有 80 款（QA 实测）其实已停售
  > 修复策略：**以 `validity_status` 为准**
  >   若 `validity_status="DISCONTINUED"` 且 `delisting_time="仍在售"` → `delisting_time` 改为 `null` 或查 `validity_checked_at` 推断日期
  >   若是历史字段没更新，标记 `delisting_time_needs_check=true`

Per QA review (full consistency picture):
  X1: validity_status=DISCONTINUED + is_active=true → set is_active=false (80 products)
  X2: validity_status=VALID + delisting_time!='仍在售' → set delisting_time='仍在售' (5)
  X3: is_active=true + delisting_time not in ('仍在售', null) → keep but flag inconsistency (188)
  X4: delisting_time='已停售' + is_active=true → set is_active=false (0 observed)

Wait, master spec says validity_status takes priority. But QA observed:
- DISCONTINUED + is_active=true (80): validity says discontinued but is_active says active.
  → These are the master spec's "80 conflicts".
- VALID + delisting!=仍在售 (5): validity says valid but delisting is set → QA says to set delisting to '仍在售'

I'll implement master spec's primary rule (validity_status priority) AND QA's secondary rules.

Algorithm:
  X1: validity_status=DISCONTINUED + is_active=true → set is_active=false, add flag
  X2: validity_status=DISCONTINUED + delisting_time='仍在售' → set delisting_time=null (master spec)
       OR if validity_checked_at exists, use it to derive date
  X3: validity_status=VALID + delisting_time not '仍在售' → set delisting_time='仍在售' (QA rule)
  X4: delisting_time='已停售' + is_active=true → set is_active=false

Add per-product field `consistency_check_at` and `consistency_status`.

Idempotent.

================================================================================
PHASE 1 P1-4 RETRY v1 (2026-08-19 10:50): Strict criterion → 40 flagged
================================================================================

First pass used STRICT criterion (per task spec): only flag products where
delisting_time is a concrete date string (not None, not '待核实'). Result: 40
products flagged.

================================================================================
PHASE 1 P1-4 RETRY v2 (2026-08-19 10:57): WIDENED criterion → ~103 flagged
================================================================================

Master decision (2026-08-19 10:56): widen to include None and 待核实 so QA/SAs
can human-review them. Strict criterion was too narrow; missing 63 products.

After Phase 1 P1-4 fix (auto):
  - 80 DISCONTINUED → auto-fixed by X1 (is_active=false)
  - 5 VALID + delisting!=仍在售 → auto-fixed by X3 (delisting_time=仍在售)

After P1-4 inconsistency flag:
  - 40 with concrete delisting date → flagged (v1 already done)
  - 26 with delisting_time=None → flagged (v2 NEW)
  - 37 with delisting_time="待核实" → flagged (v2 NEW)
  Total: 103 products flagged with inconsistency + needs_human_review

Criterion (idempotent — skip if already flagged):
  if (
      p.get("is_active") is True
      and p.get("validity_status") != "DISCONTINUED"
      and (
          p.get("delisting_time") is None
          or p.get("delisting_time") not in ("", "仍在售")
      )
      and not p.get("inconsistency")
  ):
      p["inconsistency"] = True
      p["needs_human_review"] = True
      p["inconsistency_reason"] = "X3: is_active=true 与 delisting_time 已停售矛盾（含 None/待核实）"

Sets 3 NEW fields. Does NOT modify is_active, delisting_time, or validity_status.
"""
import argparse
import os
import re
import sys
from datetime import datetime

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)
from lib_common import load_v2, save_v2, backup_v2, write_report, add_dry_run_arg

RE_ISO_DATE = re.compile(r"^(\d{4}-\d{2})(?:-\d{2})?$")


def derive_delisting_date(p):
    """Try to derive a delisting date from validity_checked_at / policy_rate_change.detected_at / etc."""
    vc = p.get("validity_checked_at")
    if isinstance(vc, str):
        m = RE_ISO_DATE.match(vc)
        if m:
            return m.group(1)
    prc = p.get("policy_rate_change")
    if isinstance(prc, dict):
        det = prc.get("detected_at")
        if isinstance(det, str):
            m = RE_ISO_DATE.match(det)
            if m:
                return m.group(1)
    return None


def fix(data, dry_run=False):
    prods = data["products"]
    counters = {
        "X1_DISCONTINUED_active_set_inactive": 0,
        "X2_DISCONTINUED_still_listed_set_null": 0,
        "X2_DISCONTINUED_still_listed_set_date": 0,
        "X3_VALID_not_listing_set_listing": 0,
        "X4_delisted_active_set_inactive": 0,
        "untouched": 0,
    }
    diff = []

    for idx, p in enumerate(prods):
        if p.get("consistency_processed_at"):
            counters["untouched"] += 1
            continue

        vs = p.get("validity_status")
        ds = p.get("delisting_time")
        ia = p.get("is_active")
        actions = []
        record = {
            "index": idx,
            "id": p.get("id", "<<no-id>>"),
            "old_validity_status": vs,
            "old_delisting_time": ds,
            "old_is_active": ia,
            "actions": [],
        }

        # X1: DISCONTINUED + is_active=true
        if vs == "DISCONTINUED" and ia is True:
            actions.append("set_is_active_false")
            if not dry_run:
                p["is_active"] = False
            counters["X1_DISCONTINUED_active_set_inactive"] += 1

        # X2: DISCONTINUED + delisting_time='仍在售' (master spec primary)
        if vs == "DISCONTINUED" and ds == "仍在售":
            # Try to derive date from validity_checked_at
            derived = derive_delisting_date(p)
            if derived:
                actions.append(f"set_delisting_time={derived}")
                if not dry_run:
                    p["delisting_time"] = derived
                counters["X2_DISCONTINUED_still_listed_set_date"] += 1
            else:
                actions.append("set_delisting_time=null+needs_check")
                if not dry_run:
                    p["delisting_time"] = None
                    p["delisting_time_needs_check"] = True
                counters["X2_DISCONTINUED_still_listed_set_null"] += 1

        # X3: VALID + delisting_time not '仍在售'
        if vs == "VALID" and ds != "仍在售":
            actions.append("set_delisting_time=仍在售")
            if not dry_run:
                p["delisting_time"] = "仍在售"
            counters["X3_VALID_not_listing_set_listing"] += 1

        # X4: delisting_time='已停售' + is_active=true
        if ds == "已停售" and ia is True:
            actions.append("set_is_active_false")
            if not dry_run:
                p["is_active"] = False
            counters["X4_delisted_active_set_inactive"] += 1

        if not actions:
            counters["untouched"] += 1

        record["actions"] = actions
        if actions:
            record["new_is_active"] = p.get("is_active")
            record["new_delisting_time"] = p.get("delisting_time")
            diff.append(record)

        if not dry_run and actions:
            p["consistency_processed_at"] = "phase1_P1-4"
            p["consistency_status"] = "fixed"

    return diff, counters


def flag_inconsistency(data, dry_run=False):
    """
    Phase 1 P1-4 RETRY v2 (2026-08-19): Flag products needing human review.
    WIDENED criterion — includes None and 待核实 delisting_time.

    Per SA v2 §2.1 步骤 3 + QA review (NEEDS_REVISION 2026-08-19 10:30) +
    Master decision (2026-08-19 10:56 widen):

    Criterion (idempotent — skip if already flagged):
      is_active=True
      AND validity_status != DISCONTINUED
      AND (delisting_time is None OR delisting_time NOT IN ("", "仍在售"))

    Excludes: delisting_time="" (empty string — invalid sentinel) and
    delisting_time="仍在售" (consistent with is_active=true, no contradiction).

    Includes:
      - delisting_time=None (26 products)  ← newly widened
      - delisting_time="待核实" (37 products)  ← newly widened
      - delisting_time=<concrete date YYYY-MM> (40 products)  ← was v1 strict

    Expected total: 103 products flagged for human review.

    Idempotent: skip if already flagged (so rerun is safe).
    Only adds 3 new fields, never modifies is_active/delisting_time/validity_status.
    """
    prods = data["products"]
    counters = {
        "flagged_inconsistency": 0,
        "already_flagged": 0,
        "untouched": 0,
    }
    diff = []

    for idx, p in enumerate(prods):
        # Idempotent: skip products already flagged
        if p.get("inconsistency") is True:
            counters["already_flagged"] += 1
            continue

        # WIDENED criterion (Master decision 2026-08-19 10:56):
        # include None and 待核实 (not just concrete dates).
        if (
            p.get("is_active") is True
            and p.get("validity_status") != "DISCONTINUED"
            and (
                p.get("delisting_time") is None
                or p.get("delisting_time") not in ("", "仍在售")
            )
        ):
            record = {
                "index": idx,
                "id": p.get("id", "<<no-id>>"),
                "is_active": p.get("is_active"),
                "delisting_time": p.get("delisting_time"),
                "validity_status": p.get("validity_status"),
                "name": (p.get("name") or "")[:40],
            }
            if not dry_run:
                # Set 3 NEW fields only (never modify existing fields)
                p["inconsistency"] = True
                p["needs_human_review"] = True
                p["inconsistency_reason"] = (
                    "X3: is_active=true 与 delisting_time 已停售矛盾（含 None/待核实）"
                )
            counters["flagged_inconsistency"] += 1
            diff.append(record)
        else:
            counters["untouched"] += 1

    return diff, counters


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_dry_run_arg(parser)
    args = parser.parse_args()

    print("=" * 60)
    print("Phase 1 P1-4: fix delisting_time vs validity_status conflicts (v2)")
    print("=" * 60)

    data = load_v2()
    prods = data["products"]
    n_already = sum(1 for p in prods if p.get("consistency_processed_at"))
    print(f"Already processed: {n_already} products")

    # Pre-fix stats
    x1 = sum(1 for p in prods if p.get("validity_status") == "DISCONTINUED" and p.get("is_active") is True)
    x2 = sum(1 for p in prods if p.get("validity_status") == "DISCONTINUED" and p.get("delisting_time") == "仍在售")
    x3 = sum(1 for p in prods if p.get("validity_status") == "VALID" and p.get("delisting_time") != "仍在售")
    x4 = sum(1 for p in prods if p.get("delisting_time") == "已停售" and p.get("is_active") is True)
    print(f"\nBefore fix:")
    print(f"  X1 DISCONTINUED+is_active=true: {x1}")
    print(f"  X2 DISCONTINUED+delisting=仍在售: {x2}")
    print(f"  X3 VALID+delisting!=仍在售: {x3}")
    print(f"  X4 delisting=已停售+is_active=true: {x4}")

    # ------------------------------------------------------------------
    # Pass 1: original X1/X2/X3/X4 fix (idempotent: skip if already done)
    # ------------------------------------------------------------------
    diff, counters = fix(data, dry_run=args.dry_run)

    print(f"\nAfter fix counters: {counters}")

    # Post-fix stats
    x1n = sum(1 for p in prods if p.get("validity_status") == "DISCONTINUED" and p.get("is_active") is True)
    x2n = sum(1 for p in prods if p.get("validity_status") == "DISCONTINUED" and p.get("delisting_time") == "仍在售")
    x3n = sum(1 for p in prods if p.get("validity_status") == "VALID" and p.get("delisting_time") != "仍在售")
    x4n = sum(1 for p in prods if p.get("delisting_time") == "已停售" and p.get("is_active") is True)
    print(f"\nAfter fix:")
    print(f"  X1 DISCONTINUED+is_active=true: {x1n} (was {x1})")
    print(f"  X2 DISCONTINUED+delisting=仍在售: {x2n} (was {x2})")
    print(f"  X3 VALID+delisting!=仍在售: {x3n} (was {x3})")
    print(f"  X4 delisting=已停售+is_active=true: {x4n} (was {x4})")

    print(f"\nSample diff (first 15):")
    for d in diff[:15]:
        print(f"  [{d['index']:4d}] id={d['id'][:25]:25s} {d['actions']}")

    # ------------------------------------------------------------------
    # Pass 2: P1-4 RETRY v2 — flag inconsistency for products needing human
    # review (WIDENED criterion per Master 2026-08-19 10:56: includes None
    # and 待核实 delisting_time, not just concrete dates)
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("Phase 1 P1-4 RETRY v2: flag inconsistency for human review (widened)")
    print("=" * 60)

    flag_diff, flag_counters = flag_inconsistency(data, dry_run=args.dry_run)

    print(f"\nInconsistency flag counters: {flag_counters}")
    print(f"\nSample flagged (first 10):")
    for d in flag_diff[:10]:
        print(f"  [{d['index']:4d}] id={d['id'][:30]:30s} delisting={d['delisting_time']!r} validity={d['validity_status']!r}")

    report = {
        "fix": "P1-4 (validity consistency)",
        "policy": "validity_status priority: DISCONTINUED+is_active=true→is_active=false; DISCONTINUED+delisting=仍在售→null/derived; VALID+delisting!=仍在售→仍在售",
        "before": {"X1": x1, "X2": x2, "X3": x3, "X4": x4},
        "after": {"X1": x1n, "X2": x2n, "X3": x3n, "X4": x4n},
        "counters": counters,
        "total_actions": sum(c for k, c in counters.items() if k != "untouched"),
        "samples": diff[:50],
        "inconsistency_flag": {
            "policy": "is_active=true + (delisting_time is None OR delisting_time NOT IN ('', '仍在售')) + validity_status!=DISCONTINUED → flag inconsistency+needs_human_review",
            "task_criterion": "WIDENED criterion (Master 2026-08-19 10:56): includes None and 待核实 delisting_time. Expected: 103 products (40 date + 26 None + 37 待核实).",
            "counters": flag_counters,
            "samples": flag_diff[:50],
        },
        "dry_run": args.dry_run,
    }
    rp = write_report("P1-4_validity_consistency_report.json", report)
    print(f"\nReport: {rp}")

    if args.dry_run:
        print("[DRY RUN] Not writing products_v2.json")
        return 0

    # Save if anything was changed (either pass)
    x_changed = sum(c for k, c in counters.items() if k != "untouched")
    flag_changed = flag_counters["flagged_inconsistency"]
    if x_changed or flag_changed:
        bk = backup_v2("pre_P1-4_validity_consistency")
        save_v2(data)
        print(f"\nBackup: {bk}")
        print(f"[OK] Saved products_v2.json")

    return 0


if __name__ == "__main__":
    sys.exit(main())