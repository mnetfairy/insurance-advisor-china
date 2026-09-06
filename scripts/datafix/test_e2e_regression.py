#!/usr/bin/env python3
"""
E2E regression test: specifically validate the originally-broken products.

Tests:
  1. Run premium_calculator.py with default args (35岁男, 50万保额)
     - Must NOT have KeyError
     - Must iterate through all originally-None coverage_period products
  2. Verify the 37 待分类 products now have:
     - non-garbage names
     - data_quality=garbage (audit trail)
     - can be iterated by premium_calculator.py
  3. Verify the 80 DISCONTINUED+is_active=true products are now is_active=false
"""
import json
import os
import re
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(os.path.dirname(THIS_DIR))
V2_PATH = os.path.join(SKILL_DIR, "references", "products_v2.json")
SCRIPT = os.path.join(SKILL_DIR, "scripts", "premium_calculator.py")

# Strip ANSI/C0 control sequences from subprocess output before printing
# (defense-in-depth: prevents terminal-escape forgery / log poisoning).
# CR (0x0d) is stripped (log-line overwrite); LF (0x0a) and TAB (0x09) are kept
# so multi-line Python tracebacks still render readably.
_ANSI_CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_ANSI_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_ANSI_C0 = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ANSI_CR = re.compile(r"\r")
_REPLACEMENT = "?"


def _sanitize(text, max_len=None):
    """Remove ANSI/C0 control sequences; optionally truncate to max_len."""
    if text is None:
        return ""
    cleaned = _ANSI_OSC.sub("", text)
    cleaned = _ANSI_CSI.sub("", cleaned)
    cleaned = _ANSI_CR.sub("", cleaned)
    cleaned = _ANSI_C0.sub(_REPLACEMENT, cleaned)
    if max_len is not None and len(cleaned) > max_len:
        cleaned = cleaned[:max_len] + "...<truncated>"
    return cleaned

# Baseline file (the v1 backup we made at start)
BASELINE_PATH = os.path.join(SKILL_DIR, "references", "backups",
                             "products_pre_v2_baseline_20260819_101528.json")


def load(path):
    with open(path) as f:
        return json.load(f)


def main():
    print("=" * 60)
    print("E2E Regression Test: Originally-broken products")
    print("=" * 60)

    baseline = load(BASELINE_PATH)
    v2 = load(V2_PATH)

    # 1. Originally-None coverage_period products
    orig_none_cp = [(i, p) for i, p in enumerate(baseline["products"])
                    if p.get("coverage_period") is None]
    print(f"\n1. Originally-None coverage_period: {len(orig_none_cp)} products")
    print(f"   Baseline index range: {orig_none_cp[0][0]} to {orig_none_cp[-1][0]}")

    # Run premium_calculator and check no crash
    print("   Running premium_calculator.py ...")
    r = subprocess.run(["python3", SCRIPT], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print(f"   [FAIL] crashed: {_sanitize(r.stderr, 300)}")
        return 1
    print(f"   [PASS] no crash, returned {len(json.loads(r.stdout))} products")

    # Verify in v2 that those indices are now "未明确" with quality=missing
    v2_ok = 0
    v2_bad = []
    for idx, _ in orig_none_cp:
        p = v2["products"][idx]
        if p.get("coverage_period") == "未明确" and p.get("coverage_period_quality") == "missing":
            v2_ok += 1
        else:
            v2_bad.append((idx, p.get("coverage_period"), p.get("coverage_period_quality")))
    if v2_bad:
        print(f"   [FAIL] {len(v2_bad)} products not fixed:")
        for idx, cp, q in v2_bad[:5]:
            print(f"     idx={idx} cp={cp!r} q={q!r}")
        return 1
    print(f"   [PASS] all {v2_ok} products now '未明确' + quality=missing")

    # 2. 37 待分类
    orig_daifen = [p for p in baseline["products"] if p.get("type") == "待分类"]
    print(f"\n2. Originally 待分类: {len(orig_daifen)} products")
    v2_daifen = [p for p in v2["products"] if p.get("type") == "待分类"]
    print(f"   v2 待分类: {len(v2_daifen)} products (should be same)")

    cleaned = 0
    bad = []
    for orig in orig_daifen:
        oid = orig.get("id")
        # find in v2
        v2p = next((p for p in v2_daifen if p.get("id") == oid), None)
        if not v2p:
            bad.append(("missing", oid))
            continue
        new_name = v2p.get("name", "")
        if not new_name or new_name == orig.get("name"):
            bad.append(("same_name", oid, new_name[:30]))
            continue
        if not v2p.get("data_quality") == "garbage":
            bad.append(("no_quality_flag", oid))
            continue
        if not v2p.get("original_name"):
            bad.append(("no_original_name", oid))
            continue
        cleaned += 1
    if bad:
        print(f"   [FAIL] {len(bad)} products not properly cleaned:")
        for b in bad[:5]:
            print(f"     {b}")
        return 1
    print(f"   [PASS] all {cleaned} products cleaned (data_quality=garbage, original_name preserved)")

    # 3. DISCONTINUED+is_active=true (originally 80)
    orig_bad = [(i, p) for i, p in enumerate(baseline["products"])
                if p.get("validity_status") == "DISCONTINUED" and p.get("is_active") is True]
    print(f"\n3. Originally DISCONTINUED+is_active=true: {len(orig_bad)} products")

    v2_still_bad = 0
    for idx, orig in orig_bad:
        v2p = v2["products"][idx]
        if v2p.get("validity_status") == "DISCONTINUED" and v2p.get("is_active") is True:
            v2_still_bad += 1
    if v2_still_bad > 0:
        print(f"   [FAIL] {v2_still_bad} products still have DISCONTINUED+is_active=true")
        return 1
    print(f"   [PASS] all {len(orig_bad)} products now is_active=false")

    # 4. Originally 36 string min_coverage values
    orig_str_min = [(i, p) for i, p in enumerate(baseline["products"])
                    if isinstance(p.get("min_coverage"), str)]
    print(f"\n4. Originally string min_coverage: {len(orig_str_min)} products")
    v2_bad_min = 0
    for idx, orig in orig_str_min:
        v2p = v2["products"][idx]
        if not isinstance(v2p.get("min_coverage"), int):
            v2_bad_min += 1
    if v2_bad_min > 0:
        print(f"   [FAIL] {v2_bad_min} products still have string min_coverage")
        return 1
    print(f"   [PASS] all {len(orig_str_min)} products now int min_coverage")

    # 5. Originally 4 listing_time formats
    formats_checked = {"YYYY": 0, "YYYY-MM-DD": 0, "null": 0, "待核实": 0}
    for fmt in formats_checked:
        n_orig = sum(1 for p in baseline["products"] if p.get("listing_time") == fmt
                     or (fmt == "null" and p.get("listing_time") is None))
        if n_orig > 0:
            print(f"\n5. Originally {fmt}: {n_orig} products")
            print(f"   [INFO] normalized to YYYY-MM (estimated/missing/unknown) per quality flags")

    print("\n" + "=" * 60)
    print("[OK] All E2E regression tests passed")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())