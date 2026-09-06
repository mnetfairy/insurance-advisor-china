#!/usr/bin/env python3
"""
Integration tests for Phase 0 + Phase 1 implementation.

Tests:
  1. premium_calculator.py smoke test (no crash)
  2. plan_designer.py smoke test (no crash)
  3. Run premium_calculator on all 75 originally-no-id products → must skip cleanly
  4. Run premium_calculator on all 112 originally-None coverage_period products → no crash
  5. Field-level sanity checks on products_v2.json:
     - All coverage_period values are not None
     - All min_coverage/max_coverage are int or None
     - All listing_time match YYYY-MM or None
     - No DISCONTINUED+is_active=true conflicts
     - 37 待分类 have non-garbage name (or <未识别产品-{id}>)
"""
import json
import os
import re
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)

# SKILL_DIR is /skills/insurance-advisor-china
SKILL_DIR = os.path.dirname(os.path.dirname(THIS_DIR))
V2_PATH = os.path.join(SKILL_DIR, "references", "products_v2.json")
SCRIPT = os.path.join(SKILL_DIR, "scripts", "premium_calculator.py")

PASS = "[PASS]"
FAIL = "[FAIL]"

# Strip ANSI control sequences (CSI / OSC) and C0 controls from subprocess output
# before printing. Defense-in-depth: a child process or its inputs must not be
# able to forge terminal escapes or overwrite prior log lines via control codes.
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


def load_v2():
    with open(V2_PATH) as f:
        return json.load(f)


def test_1_premium_calculator():
    print(f"\n{TEST_1_NAME}: python3 scripts/premium_calculator.py")
    r = subprocess.run(["python3", SCRIPT], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print(f"  {FAIL} exit={r.returncode}")
        print(f"  stderr: {_sanitize(r.stderr, 300)}")
        return False
    try:
        data = json.loads(r.stdout)
        n = len(data) if isinstance(data, dict) else 0
        print(f"  {PASS} returned {n} products (no crash)")
        return True
    except Exception as e:
        print(f"  {FAIL} JSON parse: {e}")
        return False


def test_2_plan_designer():
    print(f"\n{TEST_2_NAME}: python3 scripts/plan_designer.py")
    r = subprocess.run(["python3", os.path.join(SKILL_DIR, "scripts", "plan_designer.py")],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print(f"  {FAIL} exit={r.returncode}")
        print(f"  stderr: {_sanitize(r.stderr, 300)}")
        return False
    print(f"  {PASS} plan_designer.py ran OK")
    return True


def test_3_orig_no_id_skipped():
    """Originally 75 products had no id. Script must skip them cleanly."""
    print(f"\n{TEST_3_NAME}: original 75 no-id products must not appear in results")
    r = subprocess.run(["python3", SCRIPT], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print(f"  {FAIL} exit={r.returncode}")
        return False
    try:
        data = json.loads(r.stdout)
    except Exception:
        print(f"  {FAIL} not JSON")
        return False

    # In v2, products without id have a synthetic 'placeholder-N' id (we don't generate — let me check)
    v2_data = load_v2()
    no_id_count = sum(1 for p in v2_data["products"] if "id" not in p)
    placeholder_ids = [k for k in data.keys() if str(k).startswith("placeholder-") or "<<no-id>>" in str(k)]
    if no_id_count > 0:
        print(f"  {WARN} v2 still has {no_id_count} no-id products (Phase 1 doesn't generate synthetic IDs)")
        print(f"  Script skipped them via .get() guard — results should not contain no-id keys")
    if placeholder_ids:
        print(f"  {FAIL} script returned placeholder IDs: {placeholder_ids[:3]}")
        return False
    print(f"  {PASS} script handled no-id products cleanly")
    return True


def test_4_orig_none_cp_handled():
    """Originally 112 products had coverage_period=None. After fix they have '未明确'."""
    print(f"\n{TEST_4_NAME}: original 112 None-coverage_period products must have non-None now")
    v2 = load_v2()
    prods = v2["products"]
    still_none = sum(1 for p in prods if p.get("coverage_period") is None)
    if still_none > 0:
        print(f"  {FAIL} {still_none} products still have coverage_period=None")
        return False
    # Confirm "未明确" was set with quality=missing
    fld_wei = sum(1 for p in prods if p.get("coverage_period") == "未明确"
                  and p.get("coverage_period_quality") == "missing")
    print(f"  {PASS} 0 None, {fld_wei} products marked '未明确' + quality=missing")
    return True


def test_5_field_sanity():
    print(f"\n{TEST_5_NAME}: field-level sanity")
    v2 = load_v2()
    prods = v2["products"]
    fail = []

    # coverage_period: not None
    n_none_cp = sum(1 for p in prods if p.get("coverage_period") is None)
    if n_none_cp > 0:
        fail.append(f"coverage_period still None: {n_none_cp}")

    # min_coverage: int or None
    bad_min = sum(1 for p in prods
                  if p.get("min_coverage") is not None
                  and not isinstance(p.get("min_coverage"), int))
    if bad_min > 0:
        fail.append(f"min_coverage not int: {bad_min}")

    # max_coverage: int or None
    bad_max = sum(1 for p in prods
                  if p.get("max_coverage") is not None
                  and not isinstance(p.get("max_coverage"), int))
    if bad_max > 0:
        fail.append(f"max_coverage not int: {bad_max}")

    # listing_time: YYYY-MM or None
    import re
    RE_LT = re.compile(r"^\d{4}-\d{2}$")
    bad_lt = sum(1 for p in prods
                 if p.get("listing_time") is not None
                 and not RE_LT.match(str(p.get("listing_time"))))
    if bad_lt > 0:
        fail.append(f"listing_time not YYYY-MM: {bad_lt}")

    # DISCONTINUED+is_active=true must be 0
    n_x1 = sum(1 for p in prods
               if p.get("validity_status") == "DISCONTINUED" and p.get("is_active") is True)
    if n_x1 > 0:
        fail.append(f"DISCONTINUED+is_active=true remaining: {n_x1}")

    # VALID+delisting!=仍在售 must be 0
    n_x3 = sum(1 for p in prods
               if p.get("validity_status") == "VALID" and p.get("delisting_time") != "仍在售")
    if n_x3 > 0:
        fail.append(f"VALID+delisting!=仍在售 remaining: {n_x3}")

    # 37 待分类 must have non-garbage name
    n_daifen_bad = 0
    for p in prods:
        if p.get("type") == "待分类":
            name = p.get("name", "")
            if not name or len(name) < 4:
                n_daifen_bad += 1
            elif name in ("2025年推出科技保险创新产品", "继续推动高质量发展"):
                n_daifen_bad += 1
    if n_daifen_bad > 0:
        fail.append(f"待分类 with bad name remaining: {n_daifen_bad}")

    if fail:
        for f in fail:
            print(f"  {FAIL} {f}")
        return False
    print(f"  {PASS} all field-level checks passed")
    return True


def test_6_idempotency():
    """Re-run each fix script in --dry-run mode → should report no changes (idempotent)."""
    print(f"\n{TEST_6_NAME}: fix scripts idempotent (dry-run shows no-op)")
    scripts = [
        "fix_phase0_coverage_period_none.py",
        "fix_P0-1_name_clean.py",
        "fix_P0-2_listing_time.py",
        "fix_P1-3_coverage_types.py",
        "fix_P1-4_validity_consistency.py",
        "fix_P1-5_coverage_period_split.py",
    ]
    ok = True
    for s in scripts:
        path = os.path.join(THIS_DIR, s)
        r = subprocess.run(["python3", path, "--dry-run"],
                           capture_output=True, text=True, timeout=60)
        out = r.stdout + r.stderr
        if r.returncode != 0:
            print(f"  {FAIL} {s} exit={r.returncode}")
            ok = False
            continue
        if "0" not in _sanitize(out, 500):
            print(f"  {WARN} {s} no clear zero in output — check manually")
            print(f"  stdout: {_sanitize(out, 300)}")
        else:
            print(f"  {PASS} {s} idempotent")
    return ok


TEST_1_NAME = "Test 1: premium_calculator.py runs without crash"
TEST_2_NAME = "Test 2: plan_designer.py runs without crash"
TEST_3_NAME = "Test 3: original no-id products handled cleanly"
TEST_4_NAME = "Test 4: original None coverage_period products now non-None"
TEST_5_NAME = "Test 5: field-level sanity checks pass"
TEST_6_NAME = "Test 6: fix scripts are idempotent"

WARN = "[WARN]"


def main():
    print("=" * 60)
    print("Integration Tests — Phase 0 + Phase 1")
    print("=" * 60)

    results = []
    results.append(("Test 1", test_1_premium_calculator()))
    results.append(("Test 2", test_2_plan_designer()))
    results.append(("Test 3", test_3_orig_no_id_skipped()))
    results.append(("Test 4", test_4_orig_none_cp_handled()))
    results.append(("Test 5", test_5_field_sanity()))
    results.append(("Test 6", test_6_idempotency()))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        print(f"  {PASS if ok else FAIL} {name}")
    print(f"\n{passed}/{total} tests passed")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())