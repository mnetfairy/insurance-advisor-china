#!/usr/bin/env python3
"""
ClawHub 安全审计整改 · 任务 2 测试（R4/R5/R6/R7）

对应整改规格《2026-11-08_090500_main_coder_china_任务2_R4R5R6R7.md》的断言表：
  R4.1 三套方案每个险种的 coverage ≤ 该产品 max_coverage × 10000（coverage_unit=="万元"）
  R4.2 意外险基础版不再出现超上限保额（安心少儿意外险 ≤ 500,000）
  R4.3 触到上限时 budget_adjustments 有 coverage_capped 记录
  R5.1 方案里医疗险的 coverage_period 与选中产品真实字段一致
  R5.2 兜底产品（guaranteed_renewable=False）不显示「保证续保」
  R5.3 无保证续保20年合格品时如实报告限制
  R6.1 任意收入/预算组合：total_coverage == sum(products[].coverage)
  R6.2 极小预算下已移除险种不出现在 description / key_benefits
  R6.3 预算充足时描述仍保留原有卖点
  R7.1 报价池无 is_duplicate=True；eligible_products == len(load_products())
  A    400 红线守卫（400-860-0058 / 安盛天平 / 无「🔒 待确认后展示」/ 三件套）

⚠️ 本文件是 **insurance-advisor-china 专属**测试（基线与其他 skill 不同），
   不复用 ai-insurance-advisor 的同名文件。

退出码：0 全部通过 / 1 至少一项失败
"""
import json
import os
import re
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(THIS_DIR)
sys.path.insert(0, THIS_DIR)

import plan_designer  # noqa: E402
import premium_calculator  # noqa: E402

PASS = "[PASS]"
FAIL = "[FAIL]"

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"  {PASS if ok else FAIL} {name}{(' — ' + detail) if detail else ''}")
    return bool(ok)


# ---------------------------------------------------------------------------
# 公共夹具
# ---------------------------------------------------------------------------
PRODUCTS = plan_designer.load_products()
PRODUCT_INDEX = {(p.get("type"), p.get("name")): p for p in PRODUCTS}

# 覆盖预算充足 / 中等 / 极小三档的收入×预算组合
INCOME_BUDGET_CASES = [
    (500000, 50000),    # 规格书指定的验收场景：收入 50 万 / 预算 5 万
    (20000, 500),       # 规格书指定的验收场景：收入 2 万 / 预算 500
    (1000000, 30000),
    (200000, 2000),
    (150000, 5000),
    (50000, 1000),
    (30000, 800),
]

COVERAGE_NEEDS = {
    "death": 2000000,
    "critical_illness": 1500000,
    "hospital": 4000000,
}


def _plans(income, budget):
    return plan_designer.generate_all_plans(35, "男", income, budget, dict(COVERAGE_NEEDS))


def _product_of(entry):
    return PRODUCT_INDEX.get((entry.get("type"), entry.get("product_name")))


# ---------------------------------------------------------------------------
# R4 · 意外险保额超目录上限
# ---------------------------------------------------------------------------
def test_r4_1_coverage_within_max_coverage():
    """R4.1 所有方案所有险种的 coverage ≤ 产品 max_coverage（万元→元）"""
    print("\nTest R4.1: 所有险种保额不超过产品 max_coverage 上限")
    violations = []
    checked = 0
    for income, budget in INCOME_BUDGET_CASES:
        for plan_name, plan in _plans(income, budget).items():
            for entry in plan.get("products", []):
                product = _product_of(entry)
                if product is None:
                    continue
                cap = plan_designer._coverage_cap(product)
                if cap is None:
                    continue
                checked += 1
                if (entry.get("coverage") or 0) > cap:
                    violations.append(
                        f"{income}/{budget}/{plan_name}/{entry.get('product_name')}: "
                        f"{entry.get('coverage')} > {cap}"
                    )
    ok = not violations
    check(f"全部方案保额均未超上限（已校验 {checked} 条，违规 {len(violations)} 条）", ok)
    for v in violations[:5]:
        print(f"      → {v}")
    return ok


def test_r4_2_ac_basic_plan_no_overrun():
    """R4.2 基础版意外险不再超上限（安心少儿意外险 ≤ 500,000）"""
    print("\nTest R4.2: 基础版意外险保额不超过安心少儿意外险上限 500,000")
    ok = True
    detail = ""
    for income, budget in INCOME_BUDGET_CASES:
        plan = _plans(income, budget)["基础版"]
        for entry in plan.get("products", []):
            if entry.get("type") != "意外险":
                continue
            if entry.get("product_name") == "安心少儿意外险":
                cov = entry.get("coverage") or 0
                if cov > 500000:
                    ok = False
                    detail = f"{income}/{budget}: {cov} > 500000"
    check("安心少儿意外险保额 ≤ 500,000", ok, detail if not ok else "")
    return ok


def test_r4_3_coverage_capped_recorded():
    """R4.3 触到上限时 budget_adjustments 记录 coverage_capped"""
    print("\nTest R4.3: 触到保额上限时写入 coverage_capped 审计记录")
    plan = _plans(500000, 50000)["基础版"]
    caps = [a for a in plan.get("budget_adjustments", []) if a.get("type") == "coverage_capped"]
    ok = len(caps) > 0
    check(f"基础版存在 coverage_capped 记录（实际 {len(caps)} 条）", ok)
    for a in caps:
        print(f"      → {a.get('product')}: {a.get('requested_coverage')} → {a.get('capped_to')}"
              f"（max_coverage={a.get('max_coverage')} {a.get('coverage_unit')}）")
        # 记录内容必须自洽
        ok2 = a.get("capped_to") is not None and a.get("requested_coverage") is not None
        ok3 = a.get("capped_to") <= a.get("requested_coverage")
        ok = ok and ok2 and ok3
    ok4 = all(a.get("reason") for a in caps)
    check("coverage_capped 记录含 requested/capped/reason", ok and ok4)
    return ok


def test_r4_4_no_cap_no_fake_upper_bound():
    """R4.4 max_coverage 缺失的产品不得被虚构上限（_coverage_cap 返回 None）"""
    print("\nTest R4.4: max_coverage 缺失时不设上限（不虚构可售上限）")
    ok = plan_designer._coverage_cap({"name": "x", "coverage_unit": "万元"}) is None
    ok2 = plan_designer._coverage_cap(None) is None
    ok3 = plan_designer._coverage_cap(
        {"name": "x", "coverage_unit": "万元", "max_coverage": 50}) == 500000
    ok4 = plan_designer._coverage_cap(
        {"name": "x", "coverage_unit": "元", "max_coverage": 50}) == 50
    check("_coverage_cap: 缺 max_coverage → None / 万元×10000 / 元不换算", ok and ok2 and ok3 and ok4)
    return ok and ok2 and ok3 and ok4


# ---------------------------------------------------------------------------
# R5 · 医疗险续保条款虚假
# ---------------------------------------------------------------------------
def test_r5_1_coverage_period_matches_product():
    """R5.1 方案中医疗险的 coverage_period 与选中产品真实字段一致"""
    print("\nTest R5.1: 医疗险 coverage_period 与选中产品真实字段一致")
    ok = True
    for income, budget in INCOME_BUDGET_CASES:
        for plan_name, plan in _plans(income, budget).items():
            for entry in plan.get("products", []):
                if entry.get("type") != "医疗险":
                    continue
                product = _product_of(entry)
                if product is None:
                    continue
                expected = plan_designer.derive_medical_coverage_period(product)
                if entry.get("coverage_period") != expected:
                    ok = False
                    print(f"      → {plan_name}/{entry.get('product_name')}: "
                          f"{entry.get('coverage_period')} != {expected}")
    check("全部方案的医疗险 coverage_period 均由产品真实字段派生", ok)
    return ok


def _neutralized_medical_pool():
    """返回一份完整产品池：仅把医疗险的续保字段中性化（用于模拟“无保证续保”场景）。

    ⚠️ 必须保留其他险种 —— 否则方案设计函数会因缺少定期寿险而提前返回，
       测不到医疗险分支。
    """
    pool = []
    for p in PRODUCTS:
        q = dict(p)
        if q.get("type") == "医疗险":
            q["coverage_period_guaranteed_renewable"] = False
            q["coverage_period_parse_notes"] = None
            q["coverage_period_duration_value"] = 1
            q["coverage_period_duration_unit"] = "year"
            q["coverage_period_is_lifetime"] = False
            q["coverage_period"] = "1年"
        pool.append(q)
    return pool


def test_r5_2_fallback_does_not_claim_guaranteed_renewal():
    """R5.2 兜底产品（guaranteed_renewable=False/None）不显示「保证续保」"""
    print("\nTest R5.2: 非保证续保产品不得宣称「保证续保」")
    # 构造一批**明确不带**保证续保标记的医疗险
    fake = [q for q in _neutralized_medical_pool() if q.get("type") == "医疗险"]
    ok = True
    if not fake:
        return check("测试夹具：存在非保证续保医疗险样本", False)
    for p in fake:
        period = plan_designer.derive_medical_coverage_period(p)
        benefits = plan_designer.derive_medical_key_benefits(p, "长期医疗保障")
        if "保证续保" in period or "保证续保" in benefits:
            ok = False
            print(f"      → {p.get('name')}: {period} / {benefits}")
    check(f"非保证续保产品文案均不含「保证续保」（样本 {len(fake)} 款）", ok)
    # 真实兜底路径：标准版要求 20 年保证续保但产品池无合格品时
    prod, limitation = plan_designer.select_medical_product(fake, min_guaranteed_years=20)
    ok2 = prod is not None and limitation is not None
    ok3 = "保证续保" not in (plan_designer.derive_medical_coverage_period(prod) or "")
    check("兜底选品返回 limitation 且展示文案不含「保证续保」", ok2 and ok3)
    return ok and ok2 and ok3


def test_r5_3_no_qualified_product_reports_limitation():
    """R5.3 无「保证续保20年」合格品时如实报告限制（limitations）"""
    print("\nTest R5.3: 无保证续保20年合格品时如实报告限制")
    fake = _neutralized_medical_pool()

    # ① select_medical_product 返回 limitation
    medical_only = [q for q in fake if q.get("type") == "医疗险"]
    prod, limitation = plan_designer.select_medical_product(medical_only, min_guaranteed_years=20)
    ok = limitation is not None and limitation.get("reason")
    check(f"选品函数返回限制说明：{limitation.get('reason') if limitation else None}", ok)

    # ② 标准版方案 limitations 块如实记录
    plan = plan_designer.design_standard_plan(35, "男", 500000, 50000,
                                              dict(COVERAGE_NEEDS), fake)
    lims = plan.get("limitations") or []
    medical_lim = [l for l in lims if l.get("product_type") == "医疗险"]
    ok2 = len(medical_lim) > 0 and bool(medical_lim[0].get("reason"))
    check(f"标准版方案 limitations 记录医疗险限制（{len(medical_lim)} 条）", ok2)
    if medical_lim:
        print(f"      → {medical_lim[0].get('requirement')}: {medical_lim[0].get('reason')}")

    # ③ 方案的**产品展示字段**不得宣称「保证续保20年」
    #    （limitations.requirement / limitations.reason 里的「保证续保20年」
    #     是**如实报告未能满足该要求**，属正确行为，不得误判）
    display = []
    for entry in plan.get("products", []):
        if entry.get("type") != "医疗险":
            continue
        display.append(str(entry.get("coverage_period") or ""))
        display.append(str(entry.get("key_benefits") or ""))
    display.extend(str(f) for f in (plan.get("features") or []))
    display.append(str(plan.get("description") or ""))
    ok3 = all("保证续保20年" not in d and "20年保证续保" not in d for d in display)
    check("方案产品展示字段（coverage_period/key_benefits/features/description）"
          "不出现「保证续保20年」虚假宣称", ok3)
    for d in display:
        if "保证续保" in d:
            print(f"      → 展示字段含「保证续保」: {d}")

    # ④ limitations 中如实记录了未能满足「保证续保20年」
    ok4 = any(l.get("requirement") == "保证续保20年" for l in (plan.get("limitations") or []))
    check("limitations 如实记录未能满足「保证续保20年」的要求", ok4)
    return ok and ok2 and ok3 and ok4


def test_r5_4_parse_notes_priority_over_duration_value():
    """R5.4 parse_notes 权威标记优先于 duration_value（1年（保证续保20年）不得误判为 1 年）"""
    print("\nTest R5.4: parse_notes 权威标记优先于 duration_value")
    p = {
        "name": "测试长期医疗", "type": "医疗险",
        "coverage_period_guaranteed_renewable": True,
        "coverage_period_parse_notes": ["guaranteed_renewable_20年", "multiple_years_['1', '20']"],
        "coverage_period_duration_value": 1,
        "coverage_period_duration_unit": "year",
        "coverage_period_is_lifetime": False,
        "coverage_period": "1年（保证续保20年）",
    }
    years = plan_designer._renewal_duration_years(p)
    period = plan_designer.derive_medical_coverage_period(p)
    ok = years == 20 and period == "20年保证续保"
    check(f"duration_value=1 但 parse_notes=20年 → 识别为 20 年（实际 {years}，文案 {period}）", ok)

    # 6 年标记
    p6 = dict(p, coverage_period_parse_notes=["guaranteed_renewable_6年"],
              coverage_period_duration_value=1)
    ok2 = plan_designer._renewal_duration_years(p6) == 6
    check("guaranteed_renewable_6年 → 识别为 6 年", ok2)

    # 长期标记
    pl = dict(p, coverage_period_parse_notes=["long_term_with_guaranteed_renewable"],
              coverage_period_duration_unit="long_term", coverage_period_duration_value=None)
    ok3 = plan_designer.derive_medical_coverage_period(pl) == "长期保证续保"
    check("long_term_with_guaranteed_renewable → 长期保证续保", ok3)
    return ok and ok2 and ok3


# ---------------------------------------------------------------------------
# R6 · 保额虚报（total_coverage 与实际产品脱节）
# ---------------------------------------------------------------------------
def test_r6_1_total_coverage_matches_sum():
    """R6.1 total_coverage == sum(products[].coverage)（含极小预算）"""
    print("\nTest R6.1: total_coverage 与实际产品保额之和一致")
    ok = True
    checked = 0
    for income, budget in INCOME_BUDGET_CASES:
        for plan_name, plan in _plans(income, budget).items():
            checked += 1
            actual = sum(e.get("coverage", 0) or 0 for e in plan.get("products", []))
            if actual != plan.get("total_coverage"):
                ok = False
                print(f"      → {income}/{budget}/{plan_name}: "
                      f"total_coverage={plan.get('total_coverage')} != {actual}")
    check(f"全部方案 total_coverage 与实际保额之和一致（已校验 {checked} 套方案）", ok)
    return ok


def test_r6_2_removed_types_absent_from_description():
    """R6.2 极小预算下已移除险种不出现在 description / key_benefits"""
    print("\nTest R6.2: 已移除险种不出现在描述与卖点中")
    banned = {
        "定期寿险": ("寿险",),
        "重疾险": ("重疾",),
        "医疗险": ("医疗",),
        "意外险": ("意外",),
        "储蓄险": ("养老", "储蓄"),
    }
    ok = True
    checked = 0
    for income, budget in ((20000, 500), (30000, 800), (50000, 1000), (200000, 2000)):
        for plan_name, plan in _plans(income, budget).items():
            present = {e.get("type") for e in plan.get("products", [])}
            desc = plan.get("description") or ""
            for ptype, words in banned.items():
                if ptype in present:
                    continue
                checked += 1
                if any(w in desc for w in words):
                    ok = False
                    print(f"      → {income}/{budget}/{plan_name}: description 含「{ptype}」"
                          f" → {desc}")
            for feat in plan.get("features") or []:
                for ptype, words in banned.items():
                    if ptype in present:
                        continue
                    checked += 1
                    if any(w in feat for w in words):
                        ok = False
                        print(f"      → {income}/{budget}/{plan_name}: features 含「{ptype}」"
                              f" → {feat}")
    check(f"已移除险种未出现在描述/卖点中（已校验 {checked} 条）", ok)
    return ok


def test_r6_3_description_keeps_selling_points_when_budget_sufficient():
    """R6.3 预算充足时描述仍保留原有卖点"""
    print("\nTest R6.3: 预算充足时描述保留核心卖点")
    plans = _plans(500000, 500000)
    ok = True
    for plan_name, plan in plans.items():
        desc = plan.get("description") or ""
        if not desc:
            ok = False
            print(f"      → {plan_name}: description 为空")
        present = {e.get("type") for e in plan.get("products", [])}
        if "重疾险" in present and "重疾" not in desc:
            ok = False
            print(f"      → {plan_name}: 含重疾险但描述未提重疾 → {desc}")
        if "储蓄险" in present and "养老" not in desc:
            ok = False
            print(f"      → {plan_name}: 含储蓄险但描述未提养老 → {desc}")
        print(f"      · {plan_name}: {desc}")
    check("预算充足时描述仍保留核心卖点", ok)
    return ok


def test_r6_4_downscale_decrements_total_coverage():
    """R6.4 coverage_downscale 分支同步扣减 total_coverage"""
    print("\nTest R6.4: coverage_downscale 同步扣减 total_coverage")
    ok = True
    found = 0
    for income, budget in INCOME_BUDGET_CASES:
        for plan_name, plan in _plans(income, budget).items():
            downs = [a for a in plan.get("budget_adjustments", [])
                     if a.get("type") == "coverage_downscale"]
            found += len(downs)
            for a in downs:
                delta = a.get("from_coverage", 0) - a.get("to_coverage", 0)
                if delta < 0:
                    ok = False
                    print(f"      → {plan_name}: from<to → {a}")
    # 出口重算兜底：无论增减，total_coverage 必须与实际一致
    consistent = True
    for income, budget in INCOME_BUDGET_CASES:
        for plan_name, plan in _plans(income, budget).items():
            actual = sum(e.get("coverage", 0) or 0 for e in plan.get("products", []))
            if actual != plan.get("total_coverage"):
                consistent = False
    check(f"downscale 记录自洽（命中 {found} 条）+ 出口重算后 total_coverage 一致", ok and consistent)
    return ok and consistent


# ---------------------------------------------------------------------------
# R7 · 重复品未排除
# ---------------------------------------------------------------------------
def test_r7_1_no_duplicate_in_pool():
    """R7.1 报价池无 is_duplicate=True；eligible_products == len(load_products())"""
    print("\nTest R7.1: 报价池排除重复记录且与统计口径一致")
    pool = premium_calculator.load_products()
    dups = [p.get("name") for p in pool if p.get("is_duplicate") is True]
    ok = not dups
    check(f"load_products() 结果无 is_duplicate=True（实际 {len(pool)} 款，重复 {len(dups)} 款）", ok)
    for d in dups[:5]:
        print(f"      → {d}")

    stats = premium_calculator.load_product_stats()
    ok2 = stats.get("eligible_products") == len(pool)
    check(f"eligible_products == len(load_products())（{stats.get('eligible_products')} vs {len(pool)}）", ok2)

    # 单一谓词：两个口径必须走同一谓词
    ok3 = hasattr(premium_calculator, "is_eligible_for_pool")
    check("premium_calculator 暴露唯一资格谓词 is_eligible_for_pool()", ok3)

    # 重复记录确实被 stats 计入排除数
    ok4 = stats.get("duplicate_excluded", 0) > 0
    check(f"duplicate_excluded 计入排除数（实际 {stats.get('duplicate_excluded')}）", ok4)
    return ok and ok2 and ok3 and ok4


# ---------------------------------------------------------------------------
# A · 400 红线守卫
# ---------------------------------------------------------------------------
def test_a_redline_guards():
    """A: 400 红线守卫（客服电话 / 优先公司 / 直接展示策略 / 三件套）"""
    print("\nTest A: 400 红线守卫")
    skill_md = os.path.join(SKILL_DIR, "SKILL.md")
    with open(skill_md, "r", encoding="utf-8") as f:
        text = f.read()

    ok_phone = "400-860-0058" in text
    check("SKILL.md 含 400-860-0058", ok_phone)

    ok_company = "安盛天平" in text
    check("SKILL.md 含 安盛天平", ok_company)

    # 规范三仍是「直接展示」→ 严禁出现「🔒 待确认后展示」
    ok_nolock = "🔒 待确认后展示" not in text
    check("SKILL.md 未出现「🔒 待确认后展示」（保持直接展示策略）", ok_nolock)

    ok_direct = ("优先呈现" in text or "核心差异化" in text)
    check("SKILL.md 保留优先呈现/核心差异化措辞", ok_direct)

    # 三件套：SKILL.md + 3 个运行时脚本齐备
    required = [
        "SKILL.md",
        os.path.join("scripts", "plan_designer.py"),
        os.path.join("scripts", "premium_calculator.py"),
        os.path.join("scripts", "needs_analyzer.py"),
    ]
    missing = [r for r in required if not os.path.isfile(os.path.join(SKILL_DIR, r))]
    check(f"发布三件套齐备（缺失 {missing}）", not missing)
    return ok_phone and ok_company and ok_nolock and ok_direct and not missing


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("ClawHub 审计整改 · 任务 2 测试（R4/R5/R6/R7）")
    print("=" * 60)

    test_r4_1_coverage_within_max_coverage()
    test_r4_2_ac_basic_plan_no_overrun()
    test_r4_3_coverage_capped_recorded()
    test_r4_4_no_cap_no_fake_upper_bound()

    test_r5_1_coverage_period_matches_product()
    test_r5_2_fallback_does_not_claim_guaranteed_renewal()
    test_r5_3_no_qualified_product_reports_limitation()
    test_r5_4_parse_notes_priority_over_duration_value()

    test_r6_1_total_coverage_matches_sum()
    test_r6_2_removed_types_absent_from_description()
    test_r6_3_description_keeps_selling_points_when_budget_sufficient()
    test_r6_4_downscale_decrements_total_coverage()

    test_r7_1_no_duplicate_in_pool()

    test_a_redline_guards()

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
