#!/usr/bin/env python3
"""
停售产品过滤测试（2026-10-27 ClawHub 加固配套）

对应整改规格 §4.2 I3 的断言：
  ① premium_calculator 默认结果不含已停售产品
  ② include_discontinued=True 时可查到已停售产品
  ③ _meta.disclaimers 里含停售排除说明

退出码：0 全部通过 / 1 至少一项失败
"""
import json
import os
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(THIS_DIR)
sys.path.insert(0, THIS_DIR)

import premium_calculator  # noqa: E402

PASS = "[PASS]"
FAIL = "[FAIL]"

results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  {PASS if ok else FAIL} {name}{(' — ' + detail) if detail else ''}")
    return ok


def test_default_excludes_discontinued():
    """① 默认结果不含已停售产品"""
    print("\nTest 1: 默认结果不含已停售/已下架产品")
    res = premium_calculator.calculate_all_premiums(35, "男", 500000)
    product_ids = [k for k in res if k != "_meta"]
    flagged = [k for k in product_ids if res[k].get("is_discontinued") is True]
    ok = not flagged
    check(f"默认结果中无停售产品（返回 {len(product_ids)} 款，命中停售 {len(flagged)} 款）", ok)

    # 交叉验证：逐条用 is_discontinued 判定
    mismatched = [k for k in product_ids if premium_calculator.is_discontinued(_lookup(k))]
    ok2 = not mismatched
    check(f"逐条 is_discontinued() 复核一致（不一致 {len(mismatched)} 条）", ok2)
    return ok and ok2


def test_include_discontinued_finds_them():
    """② include_discontinued=True 时可查到已停售产品"""
    print("\nTest 2: include_discontinued=True 时可查到已停售产品")
    res = premium_calculator.calculate_all_premiums(35, "男", 500000, include_discontinued=True)
    product_ids = [k for k in res if k != "_meta"]
    flagged = [k for k in product_ids if res[k].get("is_discontinued") is True]
    ok = len(flagged) > 0
    check(f"可查到已停售产品（返回 {len(product_ids)} 款，其中停售 {len(flagged)} 款）", ok)

    meta = res.get("_meta", {})
    ok2 = meta.get("include_discontinued") is True
    check(f"_meta.include_discontinued == True（实际 {meta.get('include_discontinued')}）", ok2)
    return ok and ok2


def test_disclaimers_mention_exclusion():
    """③ _meta.disclaimers 里含停售排除说明"""
    print("\nTest 3: _meta.disclaimers 含停售排除说明")
    res = premium_calculator.calculate_all_premiums(35, "男", 500000)
    meta = res.get("_meta", {})
    disclaimers = meta.get("disclaimers", [])
    joined = " ".join(disclaimers)
    ok = bool(disclaimers) and ("停售" in joined or "下架" in joined)
    check(f"disclaimers 含停售/下架排除说明：{disclaimers}", ok)

    ok2 = isinstance(meta.get("discontinued_excluded"), int) and meta["discontinued_excluded"] > 0
    check(f"_meta.discontinued_excluded > 0（实际 {meta.get('discontinued_excluded')}）", ok2)

    ok3 = isinstance(meta.get("total_products"), int) and meta["total_products"] > 0
    check(f"_meta.total_products 保留全部产品计数口径（实际 {meta.get('total_products')}）", ok3)

    ok4 = meta.get("eligible_products", 0) < meta.get("total_products", 0)
    check(f"可对比数 < 全部产品数（{meta.get('eligible_products')} < {meta.get('total_products')}）", ok4)
    return ok and ok2 and ok3 and ok4


def test_premium_formula_unchanged():
    """在售产品保费公式未变（与历史基线口径一致）"""
    print("\nTest 4: 在售产品保费公式未变")
    res = premium_calculator.calculate_all_premiums(35, "男", 500000)
    product_ids = [k for k in res if k != "_meta"]
    ok = True
    for pid in product_ids[:50]:
        p = _lookup(pid)
        expected = premium_calculator.calculate_premium(p, 35, "男", 500000)
        actual = res[pid].get("annual_premium")
        if actual is None:
            actual = (res[pid].get("premiums_by_term") or {}).get("20年")
        if actual is None:
            continue
        if abs(round(expected, 2) - actual) > 0.01:
            ok = False
            print(f"    mismatch {pid}: expected={expected} actual={actual}")
            break
    check("在售产品保费 = calculate_premium() 直算值（前 50 款）", ok)
    return ok


_PRODUCTS_CACHE = None


def _lookup(product_id):
    """按 id 取原始产品记录。"""
    global _PRODUCTS_CACHE
    if _PRODUCTS_CACHE is None:
        path = os.path.join(SKILL_DIR, "references", "products.json")
        with open(path, "r", encoding="utf-8") as f:
            _PRODUCTS_CACHE = {p.get("id"): p for p in json.load(f)["products"]}
    return _PRODUCTS_CACHE.get(product_id, {})


def main():
    print("=" * 60)
    print("停售产品过滤测试 (I3)")
    print("=" * 60)

    results.append(("Test 1 (默认排除停售)", test_default_excludes_discontinued()))
    results.append(("Test 2 (include_discontinued 可查)", test_include_discontinued_finds_them()))
    results.append(("Test 3 (disclaimers 说明)", test_disclaimers_mention_exclusion()))
    results.append(("Test 4 (在售保费公式未变)", test_premium_formula_unchanged()))

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
