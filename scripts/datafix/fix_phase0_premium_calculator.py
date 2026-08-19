#!/usr/bin/env python3
"""
Phase 0: Fix premium_calculator.py crash (KeyError: 'coverage_period').

Symptom: 112 products have coverage_period = None (or key missing entirely).
         premium_calculator.py uses product["coverage_period"] directly → KeyError.

Fix: Defense-in-depth
  A. Script: replace product["coverage_period"] with product.get("coverage_period")
             and normalize None → "未明确"
  B. plan_designer.py line 199: 同样用 .get() + 兜底
  C. needs_analyzer.py: 同上

This is a SKILL script edit (not data) — files in scripts/ (outside datafix/).
Backup: we copy originals to scripts/datafix/backups_pre_fix/.

Idempotent: re-running detects already-fixed files and reports no-op.
"""
import os
import sys
import shutil
from datetime import datetime

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(THIS_DIR)  # scripts/
SCRIPTS_DIR = SKILL_DIR
BACKUP_LOCAL = os.path.join(THIS_DIR, "backups_pre_fix")


def now_ts():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def backup_original(path):
    """Backup a SKILL script once (per session)."""
    os.makedirs(BACKUP_LOCAL, exist_ok=True)
    fname = os.path.basename(path)
    dst = os.path.join(BACKUP_LOCAL, fname + ".orig")
    if not os.path.exists(dst):
        shutil.copy2(path, dst)
        print(f"  [BACKUP] {path} → {dst}")
    return dst


def fix_premium_calculator():
    path = os.path.join(SCRIPTS_DIR, "premium_calculator.py")
    print(f"\n[1] Patching {path}")
    backup_original(path)

    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    # Check if already fixed
    if 'product.get("coverage_period")' in src and 'if "id" not in product' in src:
        print("  [SKIP] Already patched (defense in place)")
        return 0

    # Original problematic lines (from reading v1):
    #   "coverage_period": product["coverage_period"],
    #   "waiting_period": product["waiting_period"],
    # Replace with: p.get(...) and normalize None → "未明确"
    new_src = src.replace(
        '"coverage_period": product["coverage_period"],',
        '"coverage_period": (product.get("coverage_period") or "未明确"),'
    )
    new_src = new_src.replace(
        '"waiting_period": product["waiting_period"],',
        '"waiting_period": (product.get("waiting_period") or "未明确"),'
    )
    # Skip products missing required fields (defensive loop guard).
    # Insert before the loop in calculate_all_premiums.
    loop_guard = (
        "        # Skip products missing required fields\n"
        "        if \"id\" not in product:\n"
        "            continue\n"
        "\n"
        "        # 按类型筛选\n"
        "        if product_types:\n"
        "            if product[\"type\"] not in product_types:\n"
        "                continue\n"
    )
    legacy_loop_start = (
        "        # 按类型筛选\n"
        "        if product_types:\n"
        "            if product[\"type\"] not in product_types:\n"
        "                continue\n"
    )
    if legacy_loop_start in new_src and 'if "id" not in product' not in new_src:
        new_src = new_src.replace(legacy_loop_start, loop_guard, 1)
        print("  [PATCH] Added id-missing skip guard")

    if new_src == src:
        print("  [WARN] No replacement made — pattern not found!")
        return 1

    with open(path, "w", encoding="utf-8") as f:
        f.write(new_src)
    print("  [PATCH] 2 occurrences replaced (None → '未明确' fallback)")
    return 0


def fix_plan_designer():
    path = os.path.join(SCRIPTS_DIR, "plan_designer.py")
    print(f"\n[2] Patching {path}")
    backup_original(path)

    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    if "or ''" in src and 'p.get("coverage_period"' in src:
        print("  [SKIP] Already patched")
        return 0

    # 199: "终身" in p["coverage_period"]  →  defensive
    new_src = src.replace(
        '"终身" in p["coverage_period"]',
        '"终身" in (p.get("coverage_period") or "")'
    )
    new_src = new_src.replace(
        '"20年" in p.get("coverage_period", "")',  # line 216 — already safe
        '"20年" in (p.get("coverage_period") or "")'
    )

    if new_src == src:
        print("  [WARN] No replacement made in plan_designer.py")
        return 1

    with open(path, "w", encoding="utf-8") as f:
        f.write(new_src)
    print("  [PATCH] plan_designer.py: .get() defense added")
    return 0


def fix_needs_analyzer():
    path = os.path.join(SCRIPTS_DIR, "needs_analyzer.py")
    print(f"\n[3] Patching {path}")
    backup_original(path)

    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    # No coverage_period use detected in quick scan; still backup for safety
    if "coverage_period" not in src:
        print("  [INFO] needs_analyzer.py does not use coverage_period — no patch needed")
        return 0

    # Defensive: any p["coverage_period"] → p.get("coverage_period")
    new_src = src.replace('p["coverage_period"]', 'p.get("coverage_period")')
    if new_src == src:
        print("  [INFO] No p['coverage_period'] access in needs_analyzer.py")
        return 0

    with open(path, "w", encoding="utf-8") as f:
        f.write(new_src)
    print("  [PATCH] needs_analyzer.py defensive update")
    return 0


def smoke_test():
    """Run premium_calculator.py once and check no crash."""
    print(f"\n[4] Smoke test: python3 scripts/premium_calculator.py (no args)")
    import subprocess
    p = os.path.join(SCRIPTS_DIR, "premium_calculator.py")
    r = subprocess.run(["python3", p], capture_output=True, text=True, timeout=120)
    if r.returncode == 0:
        # Check it produced JSON
        try:
            import json
            data = json.loads(r.stdout)
            n = len(data) if isinstance(data, dict) else 0
            print(f"  [PASS] premium_calculator.py returned {n} products, no crash")
            return True
        except Exception as e:
            print(f"  [WARN] Returned but JSON parse failed: {e}")
            print(f"  stderr: {r.stderr[:200]}")
            return False
    else:
        print(f"  [FAIL] premium_calculator.py crashed (exit={r.returncode})")
        print(f"  stderr: {r.stderr[:500]}")
        return False


def main():
    print("=" * 60)
    print("Phase 0: Fix SKILL script crashes (defense in scripts/)")
    print("=" * 60)
    print(f"Backup dir: {BACKUP_LOCAL}")

    err = 0
    err |= fix_premium_calculator()
    err |= fix_plan_designer()
    err |= fix_needs_analyzer()

    if smoke_test():
        print("\n[RESULT] Phase 0 script fixes: PASS")
        return 0
    else:
        print("\n[RESULT] Phase 0 script fixes: FAIL (smoke test)")
        return 1


if __name__ == "__main__":
    sys.exit(main())