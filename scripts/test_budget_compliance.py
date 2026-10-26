#!/usr/bin/env python3
"""
预算口径合规测试（2026-10-27 ClawHub 加固配套）

对应整改规格 §4.2 I1 / I2 的断言：
  ① needs 的 `收入基准_年保费上限` == income * 0.15
     且 `建议保费预算` == min(income * 0.15, budget)
  ② 三套方案 `budget_planning.是否在预算内` 均为 true
  ③ `annual_premium` <= `budget_planning.年度保费上限`
  ④ 收入 20 万 / 预算 2 万时：
       - `收入基准_年保费上限` == 30000
       - `建议保费预算` == min(30000, 20000) == 20000
       - `最低保费预算` == min(20000, 20000) == 20000
       ⚠️ 说明：整改规格 §5.2 的字面表述 "建议保费预算 == 3000" 与规格 §4.2 I1
          给出的公式 min(income*0.15, budget) 自相矛盾——3000 是**旧实现**
          （budget * 0.15 = 20000 * 0.15）的结果，正是本次要修掉的错误口径。
          本测试按 §4.2 I1 的公式（权威条目）断言：百分比按**年收入**计算，
          再与年度预算取较小值 → 20000。

退出码：0 全部通过 / 1 至少一项失败
"""
import json
import os
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(THIS_DIR)
sys.path.insert(0, THIS_DIR)

import needs_analyzer  # noqa: E402
import plan_designer  # noqa: E402

PASS = "[PASS]"
FAIL = "[FAIL]"

BASE_PROFILE = {
    "age": 35,
    "gender": "男",
    "occupation": "企业主",
    "has_family": True,
    "family_members": 4,
    "has_child": True,
    "child_age": 8,
    "has_house_mortgage": True,
    "mortgage_balance": 1500000,
    "annual_income": 500000,
    "annual_expense": 200000,
    "existing_coverage": {"重疾险": 0, "医疗险": 0, "定期寿险": 0, "意外险": 0},
    "annual_budget": 500000,
}

# (年收入, 年预算) 组合：覆盖宽松、紧张、极端紧张
BUDGET_CASES = [
    (500000, 500000),
    (1000000, 30000),
    (200000, 20000),
    (300000, 10000),
    (800000, 5000),
    (150000, 5000),
]

results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  {PASS if ok else FAIL} {name}{(' — ' + detail) if detail else ''}")
    return ok


def test_needs_income_basis():
    """① needs 的收入基准与建议保费口径"""
    print("\nTest 1: needs_analyzer 收入基准 / 建议保费口径")
    ok_all = True
    for income, budget in BUDGET_CASES:
        profile = {**BASE_PROFILE, "annual_income": income, "annual_budget": budget}
        bp = needs_analyzer.analyze_needs(**profile)["budget_planning"]
        expected_ceiling = round(income * 0.15, 2)
        expected_ideal = round(min(income * 0.15, budget), 2)
        expected_essential = round(min(income * 0.10, budget), 2)
        ok = (abs(bp["收入基准_年保费上限"] - expected_ceiling) < 0.01
              and abs(bp["建议保费预算"] - expected_ideal) < 0.01
              and abs(bp["最低保费预算"] - expected_essential) < 0.01
              and bp["预算上限"] == budget)
        ok_all = ok_all and ok
        check(f"income={income} budget={budget}: 上限={bp['收入基准_年保费上限']} "
              f"建议={bp['建议保费预算']} 最低={bp['最低保费预算']} 预算上限={bp['预算上限']}",
              ok,
              f"期望 上限={expected_ceiling} 建议={expected_ideal} 最低={expected_essential}")
    return ok_all


def test_needs_low_income_case():
    """④ 收入 20 万 / 预算 2 万的具体口径"""
    print("\nTest 2: 收入 20 万 / 预算 2 万 的口径（不再被预算×15% 的旧口径压成 3000）")
    profile = {**BASE_PROFILE, "annual_income": 200000, "annual_budget": 20000}
    bp = needs_analyzer.analyze_needs(**profile)["budget_planning"]
    ok = True
    ok = check(f"收入基准_年保费上限 == 30000 (实际 {bp['收入基准_年保费上限']})",
               abs(bp["收入基准_年保费上限"] - 30000) < 0.01) and ok
    ok = check(f"建议保费预算 == min(30000, 20000) == 20000 (实际 {bp['建议保费预算']})",
               abs(bp["建议保费预算"] - 20000) < 0.01) and ok
    ok = check(f"最低保费预算 == min(20000, 20000) == 20000 (实际 {bp['最低保费预算']})",
               abs(bp["最低保费预算"] - 20000) < 0.01) and ok
    ok = check("预算上限 == 20000 (实际 {})".format(bp["预算上限"]),
               bp["预算上限"] == 20000) and ok
    ok = check("百分比未套在预算上（旧口径 20000*0.15=3000 不再出现）",
               bp["建议保费预算"] != 3000) and ok
    ok = check(f"计算口径字段存在: {bp.get('计算口径')!r}", bool(bp.get("计算口径"))) and ok
    return ok


def test_plans_within_budget():
    """②③ 三套方案均在预算内，且 annual_premium <= 年度保费上限"""
    print("\nTest 3: 三套方案的预算硬约束（是否在预算内 + 年保费 <= 上限）")
    ok_all = True
    for income, budget in BUDGET_CASES:
        plans = plan_designer.generate_all_plans(
            35, "男", income, budget,
            {"death": 2000000, "critical_illness": 1500000, "hospital": 4000000})
        for plan_name, plan in plans.items():
            bp = plan["budget_planning"]
            in_budget = bp["是否在预算内"] is True
            hard_ok = plan["annual_premium"] <= bp["年度保费上限"] + 0.01
            ok_all = ok_all and in_budget and hard_ok
            check(f"income={income} budget={budget} {plan_name}: "
                  f"年保费={plan['annual_premium']} 上限={bp['年度保费上限']} "
                  f"在预算内={bp['是否在预算内']} 占比={bp['占年收入比']}%",
                  in_budget and hard_ok)
    return ok_all


def test_budget_adjustments_recorded():
    """超预算时的调整必须写入 budget_adjustments"""
    print("\nTest 4: 超预算调整记录（budget_adjustments）")
    plans = plan_designer.generate_all_plans(
        35, "男", 200000, 20000,
        {"death": 2000000, "critical_illness": 1500000, "hospital": 4000000})
    ok_all = True
    for plan_name, plan in plans.items():
        adjustments = plan.get("budget_adjustments")
        has_key = isinstance(adjustments, list)
        ok_all = ok_all and has_key
        check(f"{plan_name}: budget_adjustments 存在且为 list", has_key)
        if has_key:
            valid = all(
                isinstance(a, dict) and a.get("type") and a.get("reason")
                for a in adjustments)
            ok_all = ok_all and valid
            check(f"{plan_name}: 每条调整含 type/reason ({len(adjustments)} 条)", valid)
    return ok_all


def main():
    print("=" * 60)
    print("预算口径合规测试 (I1 / I2)")
    print("=" * 60)

    results.append(("Test 1 (needs 收入基准口径)", test_needs_income_basis()))
    results.append(("Test 2 (20万/2万 具体口径)", test_needs_low_income_case()))
    results.append(("Test 3 (方案预算硬约束)", test_plans_within_budget()))
    results.append(("Test 4 (budget_adjustments 记录)", test_budget_adjustments_recorded()))

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
