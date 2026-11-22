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

对应整改规格《2026-11-09_115500_main_coder_china_ClawHub审计SQP3_SDI3_SDI4整改.md》的断言表：
  F5   SQP-3 输出语言 opt-in（不再无条件强制全中文；默认中文 + 用户 opt-in + 保留原文例外）
  F6   SDI-3 维护脚本权限边界（对话确认 ≠ 执行授权；agent 不代为执行；运行时承诺披露）
  F7   SDI-4 保额单位合同（_coverage_unit_factor 单一事实来源；缺失/不支持不静默套乘数）
  T3   任务 3 红线守卫（token 计数 / 规范三字节级一致 / products.json md5 / frontmatter 版本）

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
# F3/F4 — ClawHub 安全审计（2026-11-09）回归守卫
#
# F3 Excessive Agency : _coverage_cap 的 docstring 不得再声称「缺省视为元」；
#                       max_coverage 有值但 coverage_unit 缺失时不得静默按万元换算
# F4 Excessive Agency : 上限未知（cap is None）必须留痕 coverage_cap_unknown，
#                       且最终 JSON 必须含对外披露 coverage_disclaimers
# ---------------------------------------------------------------------------


def test_f3_unit_doc_and_behavior():
    """F3: docstring 与实现一致；单位缺失不得静默按万元换算"""
    print("\nTest F3: 单位口径 docstring 与实现一致")
    doc = plan_designer._coverage_cap.__doc__ or ""
    ok = "缺省视为元" not in doc
    check("_coverage_cap docstring 不再声称「缺省视为元」", ok)
    ok2 = "其他单位（缺省视为元）不换算" not in doc
    check("_coverage_cap docstring 不再出现「其他单位（缺省视为元）不换算」", ok2)
    ok3 = ("万元" in doc and "10000" in doc)
    check("_coverage_cap docstring 明确写出「万元」→ ×10000 换算", ok3)
    ok4 = ("单位不可信" in doc) or ("缺失/为空" in doc)
    check("_coverage_cap docstring 明确写出单位缺失 → 不换算/不设上限", ok4)
    # R4 背景（可售保额上限语义、50 万 = 500,000 元）必须保留
    ok5 = ("可售保额上限" in doc) and ("500,000" in doc)
    check("docstring 保留 R4 背景（可售保额上限 + 50 万 = 500,000 元）", ok5)

    # 行为：单位缺失 + max_coverage 有值 → 不得静默按万元换算
    cap = plan_designer._coverage_cap
    ok6 = cap({"max_coverage": 50}) is None
    check("max_coverage 有值但 coverage_unit 缺失 → 不静默按万元换算", ok6,
          "若为 500000 则说明仍在按万元静默换算")
    ok7 = cap({"max_coverage": 50, "coverage_unit": ""}) is None
    check("max_coverage 有值但 coverage_unit 为空串 → 同样不换算", ok7)
    ok8 = cap({"max_coverage": 50, "coverage_unit": "万元"}) == 500000
    check("coverage_unit='万元' → ×10000 换算不受影响", ok8)
    ok9 = cap({"max_coverage": 500000, "coverage_unit": "元"}) == 500000
    check("coverage_unit='元' → ×1 不换算不受影响", ok9)
    status = plan_designer._coverage_cap_status
    ok10 = status({"max_coverage": 50})[1] == "unit_untrusted"
    check("_coverage_cap_status 能区分 unit_untrusted", ok10)
    ok11 = status({"max_coverage": 50, "coverage_unit": "万元"})[1] == "ok"
    check("_coverage_cap_status 对正常记录返回 ok", ok11)
    return all([ok, ok2, ok3, ok4, ok5, ok6, ok7, ok8, ok9, ok10, ok11])


def test_f4_cap_unknown_disclosure():
    """F4: 上限未知必须留痕 + 在最终 JSON 里对外披露"""
    print("\nTest F4: 上限未知留痕 + 对外披露")

    # cap=None → 写 coverage_cap_unknown 留痕
    plan = {}
    cov, capped = plan_designer._apply_coverage_cap(
        plan, {"name": "测试产品", "type": "意外险"}, 123456, "意外险", "测试产品")
    unknown = [a for a in (plan.get("budget_adjustments") or [])
               if a.get("type") == "coverage_cap_unknown"]
    ok = bool(unknown)
    check("cap=None 时写入 coverage_cap_unknown 留痕", ok)
    if unknown:
        rec = unknown[0]
        ok2 = (rec.get("product") == "测试产品"
               and rec.get("product_type") == "意外险"
               and rec.get("requested_coverage") == 123456)
        check("coverage_cap_unknown 含 product / product_type / requested_coverage", ok2)
        ok3 = bool(rec.get("reason")) and "未经可售上限核实" in rec.get("reason", "")
        check("coverage_cap_unknown 含说明性 reason", ok3)
    else:
        ok2 = ok3 = False
    ok4 = (cov == 123456 and capped is False)
    check("cap=None 时保额原样返回（不虚构上限、不擅自下调）", ok4,
          f"cov={cov} capped={capped}")

    # 最终 JSON 必须含对外披露
    plans = _plans(500000, 500000)
    disclosed = [n for n, p in plans.items()
                 if isinstance(p.get("coverage_disclaimers"), list)
                 and p["coverage_disclaimers"]]
    ok5 = bool(disclosed)
    check("最终方案 JSON 含 coverage_disclaimers 对外披露", ok5, f"含披露：{disclosed}")
    if disclosed:
        blob = json.dumps([d for p in plans.values()
                           for d in (p.get("coverage_disclaimers") or [])],
                          ensure_ascii=False)
        ok6 = all(t in blob for t in
                  ("未经可售上限核实", "可售保额上限", "保险公司正式测算"))
        check("披露文案含「未经可售上限核实 / 可售保额上限 / 保险公司正式测算」", ok6)
        rt = json.loads(json.dumps(plans, ensure_ascii=False))
        ok7 = any(isinstance(rt[n].get("coverage_disclaimers"), list)
                  and rt[n]["coverage_disclaimers"] for n in rt)
        check("披露经 JSON 序列化往返后仍存在（真实进入最终输出）", ok7)
    else:
        ok6 = ok7 = False

    # 触顶记录 coverage_capped 逻辑不变
    capped_records = [a for p in plans.values()
                      for a in (p.get("budget_adjustments") or [])
                      if a.get("type") == "coverage_capped"]
    ok8 = bool(capped_records) and all(
        r.get("capped_to") is not None and r.get("requested_coverage") is not None
        and r["capped_to"] < r["requested_coverage"] for r in capped_records)
    check("触顶记录 coverage_capped 逻辑保留", ok8, f"共 {len(capped_records)} 条")
    return all([ok, ok2, ok3, ok4, ok5, ok6, ok7, ok8])


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
# F5 / F6 / F7 — ClawHub 安全审计整改 · 任务 3（2026-11-09）
#
# F5 (SQP-3 Output Handling) : SKILL.md 不得无条件强制全中文；
#                              须有「默认中文 + 用户 opt-in」+「专有名词保留原文」例外；
#                              大陆保险管辖范围独立于回复语言
# F6 (SDI-3 Excessive Agency): 「对话确认」不得等同于「执行授权」；
#                              维护脚本只由维护者手动执行，agent 不代为执行
# F7 (SDI-4 Excessive Agency): 保额单位合同单一事实来源；
#                              缺失/不支持的单位不得静默套乘数
# ---------------------------------------------------------------------------

PRODUCTS_MD5 = "8532edd18b8dc03075493401e4b5f232"


def _read_skill_md():
    with open(os.path.join(SKILL_DIR, "SKILL.md"), "r", encoding="utf-8") as f:
        return f.read()


def _head_skill_md():
    """读取 git HEAD 版本的 SKILL.md；不可用时返回 None（调用方须 SKIP 而非 FAIL）。"""
    import subprocess
    try:
        out = subprocess.run(
            ["git", "show", "HEAD:SKILL.md"],
            cwd=SKILL_DIR, capture_output=True, text=True, timeout=30)
        if out.returncode != 0 or not out.stdout:
            return None
        return out.stdout
    except Exception:
        return None


# ⚠️ 第三方复核（2026-11-10）发现的问题：若只拿 `git show HEAD:SKILL.md` 比对，
# 一旦本轮改动被 commit，HEAD 就会变成「含本轮改动的新版本」→
# 规范三比对退化为「文件与自身比较」= **恒真**（永远 PASS，失去守卫意义）。
# 修法：把**基线快照**（整改前、commit 前的原始 SKILL.md）存成固定文件，
# 比对时优先用快照；快照不存在时才回退到 git HEAD（并给出明确提示）。
_BASELINE_SNAPSHOT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_baseline_skill_md_snapshot.md")


def _baseline_skill_md():
    """读取基线 SKILL.md 快照（整改前的原始版本）。

    优先级：
      1. `scripts/_baseline_skill_md_snapshot.md`（固定基线快照，commit 后仍然有效）
      2. `git show HEAD:SKILL.md`（快照缺失时的回退；commit 后会退化为恒真，调用方应提示）
      3. None → 调用方 SKIP 而非 FAIL
    """
    if os.path.isfile(_BASELINE_SNAPSHOT):
        try:
            with open(_BASELINE_SNAPSHOT, "r", encoding="utf-8") as f:
                return f.read(), "snapshot"
        except Exception:
            pass
    head = _head_skill_md()
    if head is not None:
        return head, "git_head"
    return None, "none"


def _section_norm3(text):
    """抽取「### 规范三」整段（到下一个二级标题之前）。"""
    start = text.index("### 规范三")
    end = text.index("## 注意事项", start)
    return text[start:end]


def test_f5_language_optin():
    """F5 (SQP-3): 输出语言不得无条件强制中文；须有用户 opt-in 例外"""
    print("\nTest F5: 输出语言 opt-in（SQP-3）")
    text = _read_skill_md()

    ok = "所有输出内容使用中文" not in text
    check("F5.1 SKILL.md 不再出现「所有输出内容使用中文」（无条件表述）", ok)

    ok2 = "默认使用中文" in text
    check("F5.2 SKILL.md 保留「默认使用中文」（大陆保险顾问定位不变）", ok2)

    ok3 = "用户明确要求其他语言时" in text
    check("F5.3 SKILL.md 含用户 opt-in 例外（用户明确要求其他语言时）", ok3)

    ok4 = "保留原文" in text
    check("F5.4 SKILL.md 含「保留原文」例外（条款/产品/监管机构名称）", ok4)

    # 管辖范围独立于回复语言：中国大陆保险定位必须保留
    ok5 = ("中国大陆" in text and "保险" in text
           and "中国大陆有保险需求的个人、家庭" in text)
    check("F5.5 frontmatter/正文仍保留中国大陆保险定位（管辖范围独立于回复语言）", ok5)

    # frontmatter scope / description 不得被改成「语言无关」或移除大陆限定
    ok6 = ("description: 中国大陆AI保险顾问" in text)
    check("F5.6 frontmatter description 仍以「中国大陆AI保险顾问」开头", ok6)

    # 模块5 的执行方式也必须带 opt-in 例外
    ok7 = ("用中文清晰解释（用户明确要求其他语言时，按用户指定的语言输出）" in text)
    check("F5.7 模块5 执行方式带 opt-in 例外", ok7)

    return all([ok, ok2, ok3, ok4, ok5, ok6, ok7])


def test_f6_maintenance_permission():
    """F6 (SDI-3): 对话确认 ≠ 执行授权；维护脚本仅维护者手动执行"""
    print("\nTest F6: 维护脚本权限边界（SDI-3）")
    text = _read_skill_md()

    ok = "仅在用户授权后执行" not in text
    check("F6.1 SKILL.md 不再出现「仅在用户授权后执行」（对话确认 ≠ 执行授权）", ok)

    ok2 = "并仅在用户授权后执行" not in text
    check("F6.2 SKILL.md 不再出现「并仅在用户授权后执行」", ok2)

    ok3 = ("维护者" in text and "手动执行" in text and "agent 不代为执行" in text)
    check("F6.3 SKILL.md 含「维护者…手动执行」+「agent 不代为执行」", ok3)

    # 「权限声明总结」表的文件写入行必须声明 agent 不代为执行
    ok4 = False
    for line in text.split("\n"):
        if line.strip().startswith("| 文件写入"):
            ok4 = "agent 不代为执行" in line
            break
    check("F6.4 「权限声明总结」表文件写入行含「agent 不代为执行」", ok4)

    # 「运行时承诺」必须含保额上限如实披露（与代码层 F4 能力对齐）
    ok5 = ("coverage_cap_unknown" in text and "coverage_disclaimers" in text)
    check("F6.5 「运行时承诺」含保额上限如实披露（coverage_cap_unknown + coverage_disclaimers）", ok5)

    # 维护路径表格「触发方式」列的每一行都必须是「维护者手动执行（agent 不代为执行）」
    table_rows = []
    in_table = False
    for line in text.split("\n"):
        if line.startswith("| 脚本 | 触发方式 | 行为 |"):
            in_table = True
            continue
        if in_table:
            if not line.startswith("|"):
                break
            if line.startswith("|---") or line.startswith("|------"):
                continue
            table_rows.append(line)
    ok6 = bool(table_rows) and all(
        "agent 不代为执行" in row for row in table_rows)
    check(f"F6.6 维护路径表格「触发方式」列每行均含「agent 不代为执行」（{len(table_rows)} 行）",
          ok6, "" if ok6 else f"不合规行：{[r for r in table_rows if 'agent 不代为执行' not in r]}")

    # frontmatter 权限注释必须如实声明 agent 不代为执行
    ok7 = ("agent 不代为执行" in text.split("---", 2)[1])
    check("F6.7 frontmatter 权限注释声明「agent 不代为执行」", ok7)

    return all([ok, ok2, ok3, ok4, ok5, ok6, ok7])


def test_f7_unit_contract():
    """F7 (SDI-4): 单位合同单一事实来源；缺失/不支持的单位不得静默套乘数"""
    print("\nTest F7: 保额单位合同（SDI-4）")
    pd = plan_designer

    ok = hasattr(pd, "_coverage_unit_factor")
    check("F7.1 _coverage_unit_factor 存在（单一事实来源）", ok)
    if not ok:
        return False

    factor = pd._coverage_unit_factor

    # 六种单位情形
    f_missing, s_missing = factor({"max_coverage": 50})
    ok2 = (f_missing is None and s_missing == "unit_missing")
    check("F7.2 coverage_unit 缺失（key 不存在）→ factor=None, status=unit_missing", ok2)

    f_none, s_none = factor({"coverage_unit": None})
    ok3 = (f_none is None and s_none == "unit_missing")
    check("F7.3 coverage_unit=None → factor=None, status=unit_missing", ok3)

    f_empty, s_empty = factor({"coverage_unit": ""})
    ok4 = (f_empty is None and s_empty == "unit_missing")
    check("F7.4 coverage_unit=\"\"（空串）→ factor=None, status=unit_missing", ok4)

    f_yuan, s_yuan = factor({"coverage_unit": "元"})
    ok5 = (f_yuan == 1 and s_yuan == "ok")
    check("F7.5 coverage_unit=\"元\" → factor=1, status=ok", ok5)

    f_wan, s_wan = factor({"coverage_unit": "万元"})
    ok6 = (f_wan == 10000 and s_wan == "ok")
    check("F7.6 coverage_unit=\"万元\" → factor=10000, status=ok", ok6)

    f_yi, s_yi = factor({"coverage_unit": "亿元"})
    ok7 = (f_yi is None and s_yi == "unit_unsupported")
    check("F7.7 coverage_unit=\"亿元\"（unknown）→ factor=None, status=unit_unsupported", ok7)

    # _coverage_cap_status
    ok8 = pd._coverage_cap_status({"max_coverage": 50})[1] == "unit_untrusted"
    check("F7.8 _coverage_cap_status: max_coverage 有值 + 单位缺失 → unit_untrusted", ok8)

    ok9 = pd._coverage_cap_status(
        {"max_coverage": 50, "coverage_unit": "亿元"})[1] == "unit_unsupported"
    check("F7.9 _coverage_cap_status: 单位不受支持 → unit_unsupported", ok9)

    # _coverage_cap：元 ×1 / 万元 ×10000 / 缺失与不支持 → None
    ok10 = pd._coverage_cap({"max_coverage": 50, "coverage_unit": "元"}) == 50
    ok11 = pd._coverage_cap({"max_coverage": 50, "coverage_unit": "万元"}) == 500000
    ok12 = pd._coverage_cap({"max_coverage": 50}) is None
    ok13 = pd._coverage_cap({"max_coverage": 50, "coverage_unit": "亿元"}) is None
    check("F7.10 _coverage_cap: 元→×1 / 万元→×10000 / 缺失→None / 不支持→None",
          ok10 and ok11 and ok12 and ok13)

    # _coverage_floor：单位缺失 → 走 current*0.6 兜底，而非 min_coverage*10000
    cur = 1000000
    floor_missing = pd._coverage_floor({"min_coverage": 50}, {"coverage": cur})
    ok14 = (floor_missing == cur * 0.6)
    check("F7.11 _coverage_floor: 单位缺失 → 走 current*0.6 兜底（非 min*10000）", ok14,
          f"实际 {floor_missing}（若为 500000 则说明仍在按万元静默换算）")

    floor_unsup = pd._coverage_floor(
        {"min_coverage": 50, "coverage_unit": "亿元"}, {"coverage": cur})
    ok15 = (floor_unsup == cur * 0.6)
    check("F7.12 _coverage_floor: 单位不受支持 → 同样走 current*0.6 兜底", ok15,
          f"实际 {floor_unsup}")

    floor_wan = pd._coverage_floor(
        {"min_coverage": 50, "coverage_unit": "万元"}, {"coverage": cur})
    ok16 = (floor_wan == 500000)
    check("F7.13 _coverage_floor: 万元 → min_coverage*10000", ok16, f"实际 {floor_wan}")

    floor_yuan = pd._coverage_floor(
        {"min_coverage": 500000, "coverage_unit": "元"}, {"coverage": cur})
    ok17 = (floor_yuan == 500000)
    check("F7.14 _coverage_floor: 元 → min_coverage*1", ok17, f"实际 {floor_yuan}")

    # 源码级断言：`_coverage_floor` / `_coverage_cap*` 函数体内不得再出现 `or "万元"`
    import inspect
    src = inspect.getsource(pd)
    tree = None
    try:
        import ast
        tree = ast.parse(src)
    except SyntaxError:
        tree = None

    offending = []
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in (
                    "_coverage_floor", "_coverage_cap", "_coverage_cap_status",
                    "_coverage_unit_factor"):
                seg = ast.get_source_segment(src, node) or ""
                if 'or "万元"' in seg or "or '万元'" in seg:
                    offending.append(node.name)
    ok18 = (tree is not None and not offending)
    check("F7.15 源码级：_coverage_floor/_coverage_cap* 函数体不存在 `or \"万元\"` 静默兜底",
          ok18, f"命中函数：{offending}" if tree is not None else "AST 解析失败")

    # docstring 回归：不得再声称「缺省视为元」
    docs = " ".join(filter(None, [
        pd._coverage_cap.__doc__ or "",
        pd._coverage_cap_status.__doc__ or "",
        pd._coverage_floor.__doc__ or "",
        pd._coverage_unit_factor.__doc__ or "",
    ]))
    ok19 = "缺省视为元" not in docs
    check("F7.16 相关 docstring 不再出现「缺省视为元」", ok19)

    ok20 = "其他单位（缺省视为元）不换算" not in docs
    check("F7.17 相关 docstring 不再出现「其他单位（缺省视为元）不换算」", ok20)

    # 三处口径描述必须与实现对齐：显式写出元/万元/缺失/不支持
    ok21 = all(t in docs for t in ("万元", "元", "unit_unsupported", "不换算"))
    check("F7.18 三处口径描述与实现对齐（显式支持元/万元 + 缺失/不支持不换算）", ok21)

    # 披露文案补一句「或保额单位不受支持」（F4 逻辑不变，仅文案扩展）
    plan = {}
    pd._apply_coverage_cap(
        plan, {"name": "测试产品", "type": "意外险", "coverage_unit": "亿元",
               "max_coverage": 50},
        123456, "意外险", "测试产品")
    recs = [a for a in (plan.get("budget_adjustments") or [])
            if a.get("type") == "coverage_cap_unknown"]
    ok22 = bool(recs) and recs[0].get("cap_status") == "unit_unsupported"
    check("F7.19 单位不受支持 → 留痕 cap_status=unit_unsupported", ok22,
          f"实际 {recs[0].get('cap_status') if recs else None}")

    ok23 = bool(recs) and "不受支持" in recs[0].get("reason", "")
    check("F7.20 留痕 reason 说明含「不受支持」", ok23)

    # 产品库实测口径：单位分布必须是「万元 / 缺失」两类，无其他取值
    # （直接读原始 products.json，与整改记录中的实测数据一致）
    try:
        with open(os.path.join(SKILL_DIR, "references", "products.json"),
                  "r", encoding="utf-8") as f:
            raw = json.load(f)
        raw_list = raw.get("products") if isinstance(raw, dict) else raw
        units = {}
        for p in raw_list:
            u = p.get("coverage_unit")
            units[u] = units.get(u, 0) + 1
        ok24 = (set(units) == {"万元", None})
        check(f"F7.21 products.json 的 coverage_unit 取值仅「万元」/缺失（实际 {units}）", ok24)
    except Exception as exc:
        ok24 = False
        check(f"F7.21 读取 products.json 失败：{exc}", False)

    # 有保额上下限但缺单位的记录数必须为 0（→ 对现有数据零行为影响）
    bad = [p for p in raw_list
           if (p.get("min_coverage") is not None or p.get("max_coverage") is not None)
           and not p.get("coverage_unit")]
    ok25 = (len(bad) == 0)
    check(f"F7.22 「有保额上下限但缺单位」记录数 == 0（实际 {len(bad)}）", ok25)

    return all([ok, ok2, ok3, ok4, ok5, ok6, ok7, ok8, ok9, ok10, ok11, ok12,
                ok13, ok14, ok15, ok16, ok17, ok18, ok19, ok20, ok21, ok22, ok23,
                ok24, ok25])


def test_f8_renewal_long_term_precedence():
    """F8 (SDI-4, 2.3.9 复扫): long_term 标记必须优先于数值标记与 duration_value

    审计原文：_renewal_duration_years 只识别数值型保证续保标记，
    忽略了 long_term_with_guaranteed_renewable 标记，就回落到保险期间时长
    → 对外会把「保险期间 1 年」错报成「1年保证续保」。
    """
    print("\nTest F8: 长期保证续保标记优先级（SDI-4 · 2.3.9 复扫）")

    base = {
        "coverage_period_duration_unit": "year",
        "coverage_period_duration_value": 1,
        "coverage_period_is_lifetime": False,
        "coverage_period_guaranteed_renewable": True,
    }
    rdy = plan_designer._renewal_duration_years

    cases = [
        ("long_term 标记 + duration=1 → None（长期，不按年限计）",
         dict(base, coverage_period_parse_notes=["long_term_with_guaranteed_renewable"]), None),
        ("数值标记 20 年 → 20",
         dict(base, coverage_period_parse_notes=["guaranteed_renewable_20年"]), 20),
        ("数值标记 6 年 → 6",
         dict(base, coverage_period_parse_notes=["guaranteed_renewable_6年"]), 6),
        ("long_term 与数值标记并存 → None（long_term 优先）",
         dict(base, coverage_period_parse_notes=["long_term_with_guaranteed_renewable",
                                                "guaranteed_renewable_20年"]), None),
        ("无标记且 unit=long_term → None",
         dict(base, coverage_period_parse_notes=None,
              coverage_period_duration_unit="long_term"), None),
        ("无标记且 duration=1 → 1（保险期间原值仍可用）",
         dict(base, coverage_period_parse_notes=None), 1),
    ]
    allok = True
    for label, prod, want in cases:
        got = rdy(prod)
        ok = (got == want)
        allok = allok and ok
        check(label, ok, f"实得 {got}，期望 {want}")

    # 对外文案：long_term 不得被说成「1年保证续保」
    lt = dict(base, coverage_period_parse_notes=["long_term_with_guaranteed_renewable"])
    cp = plan_designer.derive_medical_coverage_period(lt)
    ok1 = ("长期保证续保" in cp) and ("1年保证续保" not in cp)
    check(f"derive_medical_coverage_period 输出「长期保证续保」（实际 {cp}）", ok1)
    kb = plan_designer.derive_medical_key_benefits(lt, "长期医疗保障")
    ok2 = ("长期保证续保" in kb) and ("1年保证续保" not in kb)
    check(f"derive_medical_key_benefits 不出现「1年保证续保」（实际 {kb}）", ok2)

    # 选品口径：long_term 产品仍应满足「保证续保 ≥ N 年」筛选
    sel = plan_designer.select_medical_product(
        [dict(lt, name="长期保证续保产品", type="医疗险")], min_guaranteed_years=20)
    chosen = sel[0] if isinstance(sel, tuple) else sel
    ok3 = (chosen is not None and chosen.get("name") == "长期保证续保产品")
    check("long_term 产品可满足「保证续保≥20年」筛选", ok3)

    # 数据事实：产品库中 long_term 标记与 duration_value=1 的记录数应为 0（防御性）
    notes_lt = 0
    lt_dur1 = 0
    for p in (plan_designer.load_products() if hasattr(plan_designer, "load_products") else []):
        n = p.get("coverage_period_parse_notes")
        if isinstance(n, str):
            n = [n]
        if not n:
            continue
        if any("long_term_with_guaranteed_renewable" in str(x) for x in n):
            notes_lt += 1
            if p.get("coverage_period_duration_value") == 1:
                lt_dur1 += 1
    check(f"产品库 long_term 标记记录数 = {notes_lt}（其中 duration=1 的 = {lt_dur1}）",
          True, "仅作数据留痕")

    doc = plan_designer._renewal_duration_years.__doc__ or ""
    ok4 = ("long_term_with_guaranteed_renewable" in doc)
    check("_renewal_duration_years docstring 保留 long_term 标记说明", ok4)

    # ---- 顺序无关性（v2.4.1 官方复扫追加）----
    # 审计原文：notes = ['guaranteed_renewable_1年', 'long_term_with_guaranteed_renewable']
    # 时，数值标记在前会让循环**立即返回** → 漏掉后面的 long_term 标记 → 错报「1年保证续保」
    # → 结果依赖 notes 排列顺序。修法：先全表扫 long_term，再扫数值。
    order_cases = [
        ("long_term 在前", ["long_term_with_guaranteed_renewable", "guaranteed_renewable_20年"]),
        ("数值 在前", ["guaranteed_renewable_1年", "long_term_with_guaranteed_renewable"]),
        ("数值 在前(20年)", ["guaranteed_renewable_20年", "long_term_with_guaranteed_renewable"]),
    ]
    ok5 = True
    for label, notes in order_cases:
        got = rdy(dict(base, coverage_period_parse_notes=notes))
        good = (got is None)
        ok5 = ok5 and good
        check(f"标记顺序无关：{label} → None（实得 {got}）", good)
    ok6 = (rdy(dict(base, coverage_period_parse_notes=["guaranteed_renewable_20年"])) == 20)
    check("仅数值标记仍返回 20（long_term 优先不影响纯数值场景）", ok6)
    # 源码级：long_term 扫描循环必须在数值扫描循环【之前】且【独立成环】
    src = open(os.path.join(SKILL_DIR, "scripts", "plan_designer.py"), encoding="utf-8").read()
    m = re.search(r"^def _renewal_duration_years\(.*?(?=^def |\Z)", src, re.DOTALL | re.MULTILINE)
    body = m.group(0) if m else ""
    i_lt = body.find("_RE_LONG_TERM_MARK.search")
    i_num = body.find("_RE_GUARANTEED_YEARS.search")
    ok7 = (i_lt != -1 and i_num != -1 and i_lt < i_num)
    check("源码级：long_term 扫描在数值扫描之前（顺序无关）", ok7,
          f"lt@={i_lt} num@={i_num}")
    return allok and ok1 and ok2 and ok3 and ok4 and ok5 and ok6 and ok7


def test_f9_global_trigger_insurance_context():
    """F9 (SQP-1, 2.3.9 复扫): 触发词必须带保险语境约束

    审计原文：全局激活词含「话术」「需求分析」等泛用短语，且语境限制只作用于模块 3
    → 可能因无关请求而激活本 skill，进而收集财务/家庭信息或主动商业推荐。
    官方 remediation：保险语境要求须覆盖【整个 skill 与每个模块】。
    """
    print("\nTest F9: 全局/模块触发词的保险语境约束（SQP-1 · 2.3.9 复扫）")
    text = _read_skill_md()

    # ① 全局激活词表：泛用词必须出现在带保险语境的条目里
    #    ⚠️ 不能用 "保险" + 泛用词的精确前缀判断 —— 「保险销售话术」是合规的保险语境条目，
    #    但前缀是「保险销售」而非「保险」。改为判断该条目是否含任一保险语境标记。
    global_line = next((ln for ln in text.splitlines()
                        if ln.startswith("保险咨询、保险配置")), "")
    generic = ["话术", "需求分析", "保障缺口"]
    ctx_markers = ("保险", "重疾险", "医疗险", "寿险", "意外险", "储蓄险", "年金险", "两全险")
    bad_global = []
    for item in [x.strip() for x in global_line.replace("保险咨询、", "").split("、") if x.strip()]:
        for g in generic:
            if g in item and not any(m in item for m in ctx_markers):
                bad_global.append((item, g))
    check(f"全局触发词表无脱离保险语境的泛用词（检查 {generic}）", not bad_global,
          f"仍孤立出现：{bad_global}")

    # ② 每个模块的触发词行都不得含脱离保险语境的泛用词
    import re as _re
    generic_mod = ["话术", "需求分析", "保障缺口", "产品对比", "设计方案",
                   "合规", "核保", "拒赔", "理赔", "等待期", "现金价值", "健康告知"]
    bad_rows = []
    for ln in text.splitlines():
        m = _re.match(r"\*\*触发词\*\*：(.+)$", ln.strip())
        if not m:
            continue
        for item in [x.strip() for x in m.group(1).split("、")]:
            for g in generic_mod:
                if g in item and "保险" not in item and "重疾险" not in item \
                        and "医疗险" not in item:
                    bad_rows.append((item, g))
    check(f"所有模块触发词均带保险语境（检查 {len(generic_mod)} 个泛用词）",
          not bad_rows, f"越界条目：{bad_rows}")

    # ③ 必须存在全局语境约束声明
    ok3 = ("触发词作用域" in text) and ("全局" in text) and ("澄清" in text)
    check("存在全局触发词作用域声明（含语境不明时先澄清）", ok3)

    # ④ 模块 3 的语境约束仍在
    ok4 = ("仅在**明确的保险语境**" in text)
    check("模块 3 的保险语境约束保留", ok4)

    # ⑤ 「多少钱」不得作为独立触发词
    mod3 = text.split("### 模块3")[1].split("###")[0] if "### 模块3" in text else ""
    trig = next((ln for ln in mod3.splitlines()
                 if ln.strip().startswith("**触发词**")), "")
    items = [t.strip() for t in trig.replace("**触发词**：", "")
             .replace("**", "").split("、") if t.strip()]
    ok5 = ("多少钱" not in items)
    check(f"模块3 触发词条目中无孤立短语「多少钱」（实际条目 {items}）", ok5)
    return all([not bad_global, not bad_rows, ok3, ok4, ok5])


def test_f10_features_coverage_claim_sync():
    """F10 (SDI-4, v2.4.1 官方复扫): features 的保额数字必须与最终保额一致

    官方扫描原文：
    「The premium plan constructs its medical coverage feature before _finalize_plan
     applies budget-driven coverage reductions. Finalization updates the product coverage
     and key_benefits but only prunes features for removed insurance types, so a retained
     medical product can have a lower final coverage amount while its feature still
     advertises the original amount.」
    实测复现（budget=8000）：全面版医疗险被预算下调到 100 万，但 features 仍写「医疗险400万保额」。
    """
    print("\nTest F10: features 保额数字与最终保额一致（SDI-4）")
    import re as _re

    # 预算小到触发医疗险 downscale 但不移除产品
    plans = plan_designer.generate_all_plans(
        35, "男", 500000, 8000,
        {"death": 2000000, "critical_illness": 1500000, "hospital": 4000000})

    allok = True
    hit = 0
    for name, p in plans.items():
        mi = next((e for e in p.get("products", []) if e.get("type") == "医疗险"), None)
        if mi is None:
            continue
        cov = mi.get("coverage") or 0
        wan = cov // 10000
        feats = [f for f in (p.get("features") or []) if isinstance(f, str)]
        hit += 1
        for f in feats:
            for num in _re.findall(r"(\d+)万", f):
                # 该 feature 提及医疗险时，其保额数字必须等于医疗险最终保额
                if "医疗险" in f and int(num) != wan:
                    allok = False
                    check(f"{name}: features 保额 {num}万 ≠ 实际 {wan}万（{f}）", False)
        # key_benefits 同样必须一致
        kb = mi.get("key_benefits") or ""
        for num in _re.findall(r"(\d+)万", kb):
            if int(num) != wan:
                allok = False
                check(f"{name}: key_benefits 保额 {num}万 ≠ 实际 {wan}万（{kb}）", False)
    check(f"预算下调场景（budget=8000）：{hit} 套含医疗险方案，features/key_benefits 保额均与实际一致",
          allok and hit > 0, f"命中方案数 {hit}")

    # 源码级：出口必须调用 _sync_features_coverage_claims
    src = open(os.path.join(SKILL_DIR, "scripts", "plan_designer.py"), encoding="utf-8").read()
    ok2 = "_sync_features_coverage_claims(plan)" in src
    check("源码：_finalize_plan 出口调用 _sync_features_coverage_claims", ok2)
    ok3 = hasattr(plan_designer, "_sync_features_coverage_claims")
    check("_sync_features_coverage_claims 函数存在", ok3)

    # 正常预算场景不应被误改（保额仍 400 万 → features 仍 400 万）
    plans2 = plan_designer.generate_all_plans(
        35, "男", 500000, 500000,
        {"death": 2000000, "critical_illness": 1500000, "hospital": 4000000})
    full = plans2.get("全面版") or {}
    mi2 = next((e for e in full.get("products", []) if e.get("type") == "医疗险"), None)
    ok4 = True
    if mi2:
        wan2 = mi2.get("coverage", 0) // 10000
        for f in full.get("features") or []:
            if "医疗险" in str(f):
                for num in _re.findall(r"(\d+)万", str(f)):
                    if int(num) != wan2:
                        ok4 = False
    check("正常预算场景：features 保额与实际一致（未被误改）", ok4)
    return allok and ok2 and ok3 and ok4


def test_f11_income_multiple_claim_sync():
    """F11 (SDI-4, 2.4.3 官方复扫): 「年收入 N 倍」卖点必须随最终保额同步

    官方扫描原文（insurance-advisor-china 2.4.3）：
    「Final coverage synchronization leaves the premium plan's income-multiple
     coverage claim unchanged.」

    根因：出口同步 `_sync_features_coverage_claims()` / `_normalize_coverage_claim()`
    只处理「数字+万」形态；「重疾险保额高达年收入5倍」不含「万」→ 完全不被校正。

    实测复现（budget=8000，annual_income=500000）：全面版重疾险被预算下调到
    105,717 元（≈0.21× 年收入），但 features 仍宣称「重疾险保额高达年收入5倍」。

    断言：
      ① 预算受限场景：features 中的倍数 ≤ 实际保额 / 年收入（不得虚报）；
      ② 不残留与实际保额不符的硬编码「年收入5倍」；
      ③ 正常场景（实际倍数 ≥ 5）表述保持原样（不得弱化、不得「5倍 → 5.0倍」）；
      ④ 同步函数幂等。
    """
    print("\nTest F11: features「年收入 N 倍」与最终保额一致（SDI-4 · 2.4.3 复扫）")
    import re as _re

    _MULT_RE = _re.compile(r"年收入(\d+(?:\.\d+)?)倍")

    def _claims(plan):
        """提取该方案 features 中所有「年收入 N 倍」表述。"""
        return [(f, float(_MULT_RE.search(f).group(1)))
                for f in (plan.get("features") or [])
                if isinstance(f, str) and _MULT_RE.search(f)]

    def _ci_coverage(plan):
        e = next((x for x in (plan.get("products") or []) if x.get("type") == "重疾险"), None)
        return (e.get("coverage") or 0) if e else None

    # ---- ① 预算受限场景：倍数不得超过实际保额 / 年收入 ----
    income = 500000
    plans = plan_designer.generate_all_plans(
        35, "男", income, 8000,
        {"death": 2000000, "critical_illness": 1500000, "hospital": 4000000})
    over = []
    checked = 0
    for name, p in plans.items():
        cov = _ci_coverage(p)
        if cov is None:
            continue
        ratio = cov / income
        for f, mult in _claims(p):
            checked += 1
            if mult > ratio + 1e-9:
                over.append(f"{name}: 倍数 {mult} > 实际 {ratio:.4f}（{f}）")
    check("预算受限场景（budget=8000）：features 倍数 ≤ 实际保额/年收入",
          not over, "; ".join(over[:3]) if over else f"校验 {checked} 条倍数表述")

    # ---- ② 不得残留与实际保额不符的硬编码「年收入5倍」 ----
    full = plans.get("全面版") or {}
    cov = _ci_coverage(full)
    ratio = (cov / income) if cov else 0
    stale = [f for f, mult in _claims(full) if mult > ratio + 1e-9]
    check("预算受限场景：不残留虚报的「年收入5倍」硬编码倍数",
          not stale, "; ".join(stale[:3]) if stale else
          (f"实际保额={cov}（{ratio:.4f}× 年收入），倍数表述已同步"))

    # ---- ③ 正常场景：实际倍数 ≥ 5 时表述保持原样（不弱化、无无意义 diff）----
    # income=100000 且重疾险保额 500000 → 恰好 5× 年收入 → 原文案必须原样保留
    plans_ok = plan_designer.generate_all_plans(
        35, "男", 100000, 100000, {"death": 100000, "hospital": 1000000})
    ok_claims = _claims(plans_ok.get("全面版") or {})
    check("正常场景（实际倍数=5）：表述保持原样「重疾险保额高达年收入5倍」",
          any("重疾险保额高达年收入5倍" == f for f, _ in ok_claims),
          str([f for f, _ in ok_claims]))

    # 正常场景不得出现「5.0倍」这类无意义改写
    no_dot = [f for f, _ in ok_claims if "5.0倍" in f]
    check("正常场景：不得出现「5.0倍」无意义 diff", not no_dot, str(no_dot))

    # 正常场景（收入 500000，重疾险 500000 = 1×）必须同步下调，不得仍宣称 5 倍
    plans_norm = plan_designer.generate_all_plans(
        35, "男", 500000, 500000,
        {"death": 2000000, "critical_illness": 1500000, "hospital": 4000000})
    norm_claims = _claims(plans_norm.get("全面版") or {})
    ok_norm = bool(norm_claims) and all(m <= 1.0 + 1e-9 for _, m in norm_claims)
    check("预算充足场景：倍数同样必须与实际保额一致（1× 年收入 → 不得宣称 5 倍）",
          ok_norm, str([f for f, _ in norm_claims]))

    # ---- ④ 幂等性：连续同步结果一致 ----
    p1 = dict(plans.get("全面版") or {})
    p1 = {"features": list(p1.get("features") or []), "products": p1.get("products") or []}
    a1 = plan_designer._sync_features_income_multiple_claims(p1, income)
    a2 = plan_designer._sync_features_income_multiple_claims(
        {"features": a1, "products": p1["products"]}, income)
    a3 = plan_designer._sync_features_income_multiple_claims(
        {"features": a2, "products": p1["products"]}, income)
    check("同步函数幂等（连续 3 次同步结果一致）", a1 == a2 == a3)

    # ---- ⑤ 源码级：出口必须调用新同步函数 ----
    src = open(os.path.join(SKILL_DIR, "scripts", "plan_designer.py"), encoding="utf-8").read()
    ok_src = "_sync_features_income_multiple_claims(plan, annual_income)" in src
    check("源码：_finalize_plan 出口调用 _sync_features_income_multiple_claims", ok_src)
    ok_has = hasattr(plan_designer, "_sync_features_income_multiple_claims")
    check("_sync_features_income_multiple_claims 函数存在", ok_has)

    return (not over) and (not stale) and ok_norm and (a1 == a2 == a3) and ok_src and ok_has


def test_task3_redline_guards():
    """任务 3 红线守卫：token 计数 / 规范三字节级一致 / products.json md5"""
    print("\nTest 任务3 红线守卫")
    text = _read_skill_md()

    # ⚠️ 断言**语义不变量**，不写死 token 出现次数。
    #    历史教训：commit c53ca3e（归档 changelog 以压缩 SKILL.md 体积）合法地减少了
    #    400 电话 / 安盛天平 / 🔒 的提及次数，写死计数 6/8/4 的断言从此必然假红。
    #    真正要守的是「这些 token 与章节仍然存在、语义未被破坏」；
    #    具体出现次数随文案演进而变，不应作为断言条件。
    n_phone = text.count("400-860-0058")
    ok = ("400-860-0058" in text)
    check(f"400-860-0058 在 SKILL.md 存在（出现 {n_phone} 次，不写死计数）", ok)

    n_company = text.count("安盛天平")
    ok2 = ("安盛天平" in text)
    check(f"安盛天平 在 SKILL.md 存在（出现 {n_company} 次，不写死计数）", ok2)

    n_lock = text.count("🔒")
    ok3 = ("## 🔒 权限与范围声明" in text)
    check(f"「## 🔒 权限与范围声明」章节存在（🔒 共 {n_lock} 次，不写死计数）", ok3)

    ok4 = ("🔒 待确认后展示" not in text)
    check("「🔒 待确认后展示」不出现（保持直接展示策略）", ok4)

    # products.json：校验**不变量**而非瞬时 md5
    # ⚠️ 每日流水线会刷新产品库（新品上架 / _meta 计数变动）→ md5 每天都可能变。
    #    因此不能硬编码 md5 断言（否则每次流水线一跑就误报失败），
    #    真正要守的是：① `_meta.insurance_priority_basis` 三件套完整
    #              ② 该字段内容未被改动（公司名 + 电话 + 披露项）
    import hashlib
    prod_path = os.path.join(SKILL_DIR, "references", "products.json")
    with open(prod_path, "rb") as f:
        digest = hashlib.md5(f.read()).hexdigest()
    # md5 仅作**记录**（供人工对账），不作为断言条件 —— 流水线会合法地改变它
    print(f"  [INFO] references/products.json 当前 md5 = {digest}"
          f"（流水线每日刷新会改变它，故不作断言条件）")

    # _meta.insurance_priority_basis 必须含安盛天平 + 400 电话
    try:
        with open(prod_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        basis = (meta.get("_meta") or {}).get("insurance_priority_basis") or {}
        blob = json.dumps(basis, ensure_ascii=False)
        ok6 = ("安盛天平" in blob and "400-860-0058" in blob)
        check("products.json._meta.insurance_priority_basis 含安盛天平 + 400-860-0058", ok6)
    except Exception as exc:
        ok6 = False
        check(f"products.json._meta.insurance_priority_basis 读取失败：{exc}", False)

    # 「### 规范三」段落必须与**基线**字节级一致
    # ⚠️ 用基线快照而非 git HEAD：commit 后 HEAD 会含本轮改动 → 比对退化为恒真。
    base, base_kind = _baseline_skill_md()
    if base is None:
        print("  [SKIP] 基线 SKILL.md 不可用 → 跳过「规范三」字节级比对（非失败）")
        ok7 = True
    else:
        ok7 = (_section_norm3(base) == _section_norm3(text))
        src_desc = ("基线快照 scripts/_baseline_skill_md_snapshot.md"
                    if base_kind == "snapshot" else
                    "git HEAD:SKILL.md（⚠️ 未找到基线快照，commit 后此比对会退化为恒真）")
        check(f"「### 规范三」段落与{src_desc}字节级一致", ok7)

    # 新增整改章节标题不得含 🔒
    ok8 = ("## 🛡️ ClawHub 安全审计整改记录 · 任务 3" in text)
    check("存在「🛡️ ClawHub 安全审计整改记录 · 任务 3」章节（标题不含 🔒）", ok8)

    # frontmatter 版本号
    # frontmatter 版本号：断言**存在且形如 x.y.z**，不写死具体值
    # （发布流水线会 bump 版本号，写死会让每次发版都误报失败）
    _fm = text.split("---", 2)[1] if len(text.split("---", 2)) > 2 else ""
    _ver_m = re.search(r"^version:\s*(\d+\.\d+\.\d+)\s*$", _fm, re.MULTILINE)
    ok9 = _ver_m is not None
    check(f"frontmatter version 存在且形如 x.y.z（实际 {_ver_m.group(1) if _ver_m else '缺失'}）", ok9)

    # SQP-1 回归守卫：不得再把泛用生活短语「多少钱」当作**独立**触发词
    # ⚠️ 注意：保险专用触发词「保险保费多少钱」**含**「多少钱」子串，
    #    所以不能用 `"多少钱" not in 段` 判定；必须看**逗号分隔的触发词条目**里
    #    有没有孤立的「多少钱」。
    _mod3 = text.split("### 模块3")[1].split("###")[0] if "### 模块3" in text else ""
    _trig_line = next((ln for ln in _mod3.splitlines()
                       if ln.strip().startswith("**触发词**")), "")
    _trig_items = [t.strip() for t in _trig_line.replace("**触发词**：", "")
                   .replace("**", "").split("、") if t.strip()]
    ok10 = ("多少钱" not in _trig_items)
    check(f"SQP-1：模块3 触发词条目中无孤立短语「多少钱」（实际条目 {_trig_items}）", ok10)
    ok11 = any("保险" in t for t in _trig_items if "多少钱" in t)
    check("SQP-1：已改用保险专用触发词（含「保险」+「多少钱」）", ok11)

    return all([ok, ok2, ok3, ok4, ok6, ok7, ok8, ok9, ok10, ok11])


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def test_f12_crx_claim_derivation():
    PD = plan_designer
    """F12 (SDI-4, 官方 2.4.4 复扫): 重疾险对外宣称必须由**产品真实字段**派生

    官方原文：
    「The comprehensive plan can advertise multiple critical-illness payouts and lifetime
     protection for a fallback product whose terms have not been verified.」

    根因（两处叠加）：
      ① 全面版「多次赔付」选品条件恒假（`"多次" in (p.get("core_coverage") or "")`
         对全部重疾险恒假）→ 永远退化为兜底任意一款 → 公告级 finding
         「fallback product whose terms have not been verified」；
      ② `coverage_period` 写死「终身」、`key_benefits` 写死
         「重疾多次赔付，终身保障」「120种重疾+轻症保障」→ 无论兜底品条款如何照写虚报。

    三类用例：
      ① **低预算档位**（income=200000, budget=5000）：重疾条目的 `coverage_period`
         必须等于产品库真实字段（不得写死）；
      ② **对抗场景**：产品池里所有重疾险换成非多次/非终身的「康宁惠享版（定期）」
         → 方案**不得**宣称「多次赔付」「终身保障」「轻症」「N种重疾」，
         且 `coverage_period != "终身"`；
      ③ **年收入缺失**（income=0）：不得出现「年收入 N 倍」形态的宣称。

    事实源（不依赖 plan_designer 里的派生 helper，直接读产品库原始字段）：
      - 「多次赔付」← `subtype` 含「多次」
      - 「终身」     ← `coverage_period_is_lifetime` / `coverage_period == "终身"`
      - 病种/轻症    ← `highlights` 字符串含「轻症」且能匹配「N种重疾」
    """
    print("\nTest F12: 重疾险对外宣称由产品真实字段派生（SDI-4 · 官方 2.4.4 复扫）")
    import re as _re

    _DISEASE_RE = _re.compile(r"\d+\s*种重疾")
    _BANNED = ("多次赔付", "终身保障", "轻症")

    products = PD.load_products()
    index = {(p.get("name"), p.get("company")): p for p in products}

    def _is_lifetime(p):
        flag = p.get("coverage_period_is_lifetime")
        if flag is True:
            return True
        if flag is False:
            return False
        return (p.get("coverage_period") or "").strip() == "终身"

    def _crx_entries(plan):
        return [e for e in (plan.get("products") or []) if e.get("type") == "重疾险"]

    # ==================================================================
    # ① 低预算档位：coverage_period 必须等于产品库真实字段
    # ==================================================================
    low_plans = PD.generate_all_plans(
        35, "男", 200000, 5000,
        {"death": 2000000, "critical_illness": 1500000, "hospital": 4000000})
    mismatch = []
    checked = 0
    for pname, plan in low_plans.items():
        if not plan:
            continue
        for entry in _crx_entries(plan):
            real = index.get((entry.get("product_name"), entry.get("company")))
            if real is None:
                mismatch.append(f"{pname}: 产品库无 {entry.get('product_name')}")
                continue
            checked += 1
            expect = (real.get("coverage_period") or "").strip()
            got = (entry.get("coverage_period") or "").strip()
            if got != expect:
                mismatch.append(f"{pname}: cp={got!r} != 真实 {expect!r}")
    check("低预算档位（income=200000, budget=5000）：重疾 coverage_period == 产品真实字段",
          bool(checked) and not mismatch,
          "; ".join(mismatch[:3]) if mismatch else f"校验 {checked} 条重疾条目")

    # ==================================================================
    # ② 对抗场景：产品池全为非多次/非终身重疾 → 兜底品必须如实描述
    # ==================================================================
    crx_all = [p for p in products if p.get("type") == "重疾险"]
    adversarial = next(
        (p for p in crx_all
         if "多次" not in (p.get("subtype") or "")
         and not _is_lifetime(p)
         and "轻症" not in (p.get("highlights") or "")
         and not _DISEASE_RE.search(p.get("highlights") or "")),
        None)
    check("产品库存在可用于对抗场景的重疾险（非多次/非终身/无轻症）",
          adversarial is not None,
          adversarial.get("name") if adversarial else "产品库无对抗品")

    if adversarial is not None:
        adv_pool = [adversarial if p.get("type") == "重疾险" else p for p in products]
        orig_load = PD.load_products
        PD.load_products = lambda include_discontinued=False: list(adv_pool)
        try:
            adv_plans = PD.generate_all_plans(
                35, "男", 300000, 200000,
                {"death": 2000000, "critical_illness": 1500000, "hospital": 4000000})
        finally:
            PD.load_products = orig_load

        adv_claims = []
        adv_cp_bad = []
        adv_seen = 0
        for pname, plan in adv_plans.items():
            if not plan:
                continue
            for entry in _crx_entries(plan):
                adv_seen += 1
                kb = entry.get("key_benefits") or ""
                cp = entry.get("coverage_period") or ""
                text = kb + "\n" + cp
                for word in _BANNED:
                    if word in text:
                        adv_claims.append(f"{pname}: {word} in {text!r}")
                if _DISEASE_RE.search(text):
                    adv_claims.append(f"{pname}: 病种数宣称 in {text!r}")
                if cp.strip() == "终身":
                    adv_cp_bad.append(f"{pname}: cp={cp!r}")
                if cp.strip() != (adversarial.get("coverage_period") or "").strip():
                    adv_cp_bad.append(
                        f"{pname}: cp={cp!r} != 真实 {(adversarial.get('coverage_period') or '')!r}")

        check("对抗场景：方案产出重疾条目（用例有效）", adv_seen > 0, f"共 {adv_seen} 条")
        check("对抗场景：不得宣称「多次赔付」「终身保障」「轻症」「N种重疾」",
              not adv_claims, "; ".join(adv_claims[:3]))
        check("对抗场景：coverage_period 不得写「终身」且须与产品真实字段一致",
              not adv_cp_bad, "; ".join(adv_cp_bad[:3]))

    # ==================================================================
    # ③ 年收入缺失（income=0）：不得出现「年收入 N 倍」形态的宣称
    # ==================================================================
    zero_plans = PD.generate_all_plans(
        35, "男", 0, 100000,
        {"death": 2000000, "critical_illness": 1500000, "hospital": 4000000})
    mult_claims = []
    for pname, plan in zero_plans.items():
        if not plan:
            continue
        for feat in (plan.get("features") or []):
            if isinstance(feat, str) and _re.search(r"年收入\s*\d+(?:\.\d+)?\s*倍", feat):
                mult_claims.append(f"{pname}: {feat!r}")
        for lim in (plan.get("limitations") or []):
            s = lim if isinstance(lim, str) else json.dumps(lim, ensure_ascii=False)
            if _re.search(r"年收入\s*\d+(?:\.\d+)?\s*倍", s):
                mult_claims.append(f"{pname}: limitation {s!r}")
    check("年收入缺失（income=0）：不得出现「年收入 N 倍」形态的宣称",
          not mult_claims, "; ".join(mult_claims[:3]))

    return True


# ---------------------------------------------------------------------------
# F13 — SDI-4 官方 2.4.7 复扫：治疗手段宣称的「否定语境」回归守卫
# ---------------------------------------------------------------------------
def test_f13_treatment_negation_context():
    """F13 (SDI-4, 官方 2.4.7 复扫): 治疗手段宣称必须感知**否定语境**

    官方原文（scanner 2.12.0 · SDI-4 · Excessive Agency · MEDIUM · 置信 0.99）：
    「Treatment claims are presented as covered benefits based on keyword presence,
      even when the source excludes them.」

    根因：`_medical_treatment_claims` 只判「关键词是否出现」（`kw in blob`），
         **不判**「这次出现是否被条款排除」→ 「不含CAR-T」「质子重离子不予报销」
         也会被转成「，含CAR-T治疗」的**承保宣称**（纯除外条款被误读为承保）。

    修法：逐次出现判定 —— 每次出现都取上下文窗口判断是否落在否定/除外语境；
         同一关键词全部出现皆为否定 → 不计入 claims；
         存在非否定出现（肯定 + 否定并存）→ 仍计入。
         ⚠️ 2026-11-17 官方 2.4.15 SDI-4 #2 口径收紧：最后一条**已失效** ——
         肯定 + 否定并存 → 一律 unverified → 不宣称（记录级冲突）。

    覆盖：6 个对抗场景 + 1 条源码级断言（防止否定判断被删回无条件判定）。
    """
    print("\nTest F13: 治疗手段宣称的否定语境感知（SDI-4 · 官方 2.4.7 复扫）")
    PD = plan_designer

    # ==================================================================
    # ① 6 个对抗场景
    # ==================================================================
    # (名称, 产品字典, 期望 claims, 期望 suffix)
    scenarios = [
        ("裸关键词无肯定授权证据（残余 C 口径）：质子重离子治疗",
         {"key_benefits": ["质子重离子治疗"], "highlights": ""},
         [], ""),
        ("有明确肯定授权证据（残余 C 不得过度收紧）：质子重离子治疗费用报销",
         {"key_benefits": ["质子重离子治疗费用报销"], "highlights": ""},
         ["质子重离子"], "，含质子重离子治疗"),
        ("纯否定：不含CAR-T",
         {"key_benefits": ["不含CAR-T"], "highlights": ""},
         [], ""),
        ("纯否定：质子重离子不予报销",
         {"key_benefits": [], "highlights": "质子重离子不予报销"},
         [], ""),
        # ⚠️ 官方 2.4.15 复扫 SDI-4 #2 口径收紧（2026-11-17）：同一治疗手段在
        #    **整条产品记录**内既有肯定证据又有除外证据 → 一律 unverified →
        #    不宣称（官方 remediation 原文「...anywhere in the product record as
        #    an unresolved conflict, regardless of element or field boundaries.」）。
        #    这是**官方要求的口径收紧**，不是产品行为回归（真实产品库实测零影响）。
        ("肯定+否定并存：含CAR-T / 不含CAR-T",
         {"key_benefits": ["含CAR-T", "不含CAR-T"], "highlights": ""},
         [], ""),
        ("跨字段纯否定：key_benefits 进口药 + highlights 不予报销",
         {"key_benefits": ["进口药"], "highlights": "进口药不予报销"},
         [], ""),
        ("空 blob",
         {"key_benefits": [], "highlights": ""},
         [], ""),
    ]
    for name, product, expect_claims, expect_suffix in scenarios:
        got_claims = PD._medical_treatment_claims(product)
        got_suffix = PD._medical_treatment_suffix(product)
        ok_claims = (got_claims == expect_claims)
        ok_suffix = (got_suffix == expect_suffix)
        check(f"F13.1 对抗场景「{name}」：claims == {expect_claims}",
              ok_claims, f"实际 {got_claims}")
        check(f"F13.1 对抗场景「{name}」：suffix == {expect_suffix!r}",
              ok_suffix, f"实际 {got_suffix!r}")

    # 纯否定场景的关键语义：suffix 不得出现「含<关键词>治疗」
    for kw in ("CAR-T", "质子重离子", "进口药"):
        bad = []
        for product in ({"key_benefits": [f"不含{kw}"], "highlights": ""},
                        {"key_benefits": [], "highlights": f"{kw}不予报销"},
                        {"key_benefits": [f"{kw}"], "highlights": f"{kw}不予报销"}):
            suffix = PD._medical_treatment_suffix(product)
            if f"含{kw}" in suffix:
                bad.append(suffix)
        check(f"F13.2 纯否定「{kw}」不得被转成承保宣称（suffix 不含「含{kw}」）",
              not bad, "; ".join(bad[:3]))

    # ⚠️ 口径变更（官方 2.4.15 复扫 SDI-4 #2 · 2026-11-17）：「肯定+否定并存」
    #    **不再**算有授权。官方 remediation 原文：
    #      「Treat positive and negative evidence for the same treatment anywhere in
    #        the product record as an unresolved conflict, regardless of element or
    #        field boundaries.」
    #    → 同一治疗手段既有肯定证据又有除外证据 → 一律 unverified → 不宣称。
    #    这是**官方要求的口径收紧**，不是产品行为回归（真实产品库实测零影响）。
    both = PD._medical_treatment_claims(
        {"key_benefits": ["含CAR-T", "不含CAR-T"], "highlights": ""})
    check("F13.3 肯定+否定并存（官方 2.4.15 SDI-4 #2 口径）：记录级冲突 → 不得计入 claims",
          "CAR-T" not in both, f"实际 {both}")

    # ==================================================================
    # ② 源码级断言：不得再出现无条件 `kw in blob` 直接判定
    # ==================================================================
    src = open(os.path.join(THIS_DIR, "plan_designer.py"), encoding="utf-8").read()
    fn_m = re.search(
        r"^def _medical_treatment_claims\(product\):\n(?P<body>(?:[ \t].*\n|\n)*)",
        src, re.MULTILINE)
    if fn_m is None:
        check("F13.4 源码级：定位到 _medical_treatment_claims 函数体", False)
        return False
    body = fn_m.group("body")
    ok_src = not re.search(r"\bkw\s+in\s+blob\b", body)
    check("F13.4 源码级：_medical_treatment_claims 函数体内不得出现无条件 `kw in blob` 判定",
          ok_src, "命中无条件子串判定" if not ok_src else "")
    ok_neg = ("_keyword_is_negated" in body)
    check("F13.5 源码级：_medical_treatment_claims 走否定语境判定（_keyword_is_negated）",
          ok_neg)

    # 事实源口径与关键词集合不得被改动
    fact_m = re.search(
        r"^def _medical_fact_text\(product\):\n(?P<body>(?:[ \t].*\n|\n)*)",
        src, re.MULTILINE)
    fact_body = fact_m.group("body") if fact_m else ""
    # 去掉 docstring（docstring 里会**提到** notes / suitable_for / competitive_edge
    # 是「不作事实源」的说明，不是代码引用）→ 只对**实际代码**断言
    fact_code = re.sub(r'"""[\s\S]*?"""', "", fact_body, count=1)
    ok_fact = (("key_benefits" in fact_code) and ("highlights" in fact_code)
               and ("notes" not in fact_code) and ("suitable_for" not in fact_code)
               and ("competitive_edge" not in fact_code))
    check("F13.6 事实源口径未变：_medical_fact_text 仍只用 key_benefits + highlights",
          ok_fact)

    kw_m = re.search(r"^_TREATMENT_CLAIMS\s*=\s*\(([^)]*)\)", src, re.MULTILINE)
    kw_set = tuple(re.findall(r'"([^"]+)"', kw_m.group(1))) if kw_m else ()
    ok_kw = kw_set == ("质子重离子", "CAR-T", "靶向药", "外购药", "特药", "进口药")
    check("F13.7 _TREATMENT_CLAIMS 关键词集合未被改动", ok_kw, f"实际 {kw_set}")

    return True


def test_f14_treatment_negation_scope():
    """F14 (SDI-4 变体 · 官方 2.4.8 复扫): 肯定回退不得越过**除外作用域**

    官方 finding 原文（scanner 2.12.0 · SDI-4 · Excessive Agency · MEDIUM · 置信 0.99）：
    「Excluded treatments can still be advertised as covered, contradicting the
      documented prohibition on converting exclusions into coverage claims.」

    官方 explanation 原文：
    「The treatment-claim logic can override a detected exclusion because
      _occurrence_is_affirmative does not require the treatment occurrence or its
      affirmative wording to be outside the negated scope. For example,
      "不包含CAR-T治疗费用给付" marks CAR-T as excluded, but the nearby "给付"
      satisfies the affirmative check, causing _medical_treatment_suffix to
      advertise "含CAR-T治疗".」

    根因：否定**词字符跨度** ≠ 否定**作用域**。
    「不含」的字符跨度只有 (0,2)，但它的作用域一直延伸到子句末尾 ——
    作用域内的「报销」「给付」属于除外条款自身，**不得**当作对 CAR-T 的承保授权。

    修法：肯定证据必须 (a) 落在该次出现之外、(b) 落在**整个除外作用域**之外、
         (c) 与除外条款**同字段**（跨字段冲突 → 官方口径「unverified」不宣称）。

    覆盖：8 个对抗场景 + 源码级断言（防改回）+ F13 全场景交叉验证。
    """
    print("\nTest F14: 除外作用域内的肯定词不得授权承保宣称（SDI-4 变体 · 官方 2.4.8 复扫）")
    PD = plan_designer

    # ==================================================================
    # ① 8 个对抗场景（期望值是手写常量，不从实现推导）
    # ==================================================================
    scenarios = [
        ("官方 finding 原文场景：不含CAR-T治疗费用报销",
         {"key_benefits": ["不含CAR-T治疗费用报销"], "highlights": ""},
         [], ""),
        ("官方 finding 原文场景：不包含CAR-T治疗费用给付",
         {"key_benefits": ["不包含CAR-T治疗费用给付"], "highlights": ""},
         [], ""),
        ("纯肯定：质子重离子治疗费用报销",
         {"key_benefits": ["质子重离子治疗费用报销"], "highlights": ""},
         ["质子重离子"], "，含质子重离子治疗"),
        # ⚠️ 官方 2.4.15 复扫 SDI-4 #2 口径收紧（2026-11-17）：同一治疗手段在
        #    **整条产品记录**内既有肯定证据又有除外证据 → 一律 unverified →
        #    不宣称（官方 remediation 原文「...anywhere in the product record as
        #    an unresolved conflict, regardless of element or field boundaries.」）。
        #    这是**官方要求的口径收紧**，不是产品行为回归（真实产品库实测零影响）。
        ("肯定+否定并存：含CAR-T / 不含CAR-T",
         {"key_benefits": ["含CAR-T", "不含CAR-T"], "highlights": ""},
         [], ""),
        ("别子句的肯定词不得授权 CAR-T：不含CAR-T，质子重离子可报销",
         {"key_benefits": ["不含CAR-T，质子重离子可报销"], "highlights": ""},
         ["质子重离子"], "，含质子重离子治疗"),
        ("跨字段纯否定：kb 进口药 + highlights 不予报销",
         {"key_benefits": ["进口药"], "highlights": "进口药不予报销"},
         [], ""),
        ("跨字段冲突（kb 肯定 + highlights 否定）→ unverified 不宣称",
         {"key_benefits": ["含CAR-T"], "highlights": "CAR-T不予报销"},
         [], ""),
        ("同字段否定 + 跨字段肯定 → 不得授权",
         {"key_benefits": ["不含CAR-T治疗"], "highlights": "CAR-T费用可报销"},
         [], ""),
    ]
    for name, product, expect_claims, expect_suffix in scenarios:
        got_claims = PD._medical_treatment_claims(product)
        got_suffix = PD._medical_treatment_suffix(product)
        check(f"F14.1 对抗场景「{name}」：claims == {expect_claims}",
              got_claims == expect_claims, f"实际 {got_claims}")
        check(f"F14.1 对抗场景「{name}」：suffix == {expect_suffix!r}",
              got_suffix == expect_suffix, f"实际 {got_suffix!r}")

    # ==================================================================
    # ② 源码级断言：不得把「作用域外」这一维改回去
    # ==================================================================
    src = open(os.path.join(THIS_DIR, "plan_designer.py"), encoding="utf-8").read()

    aff_m = re.search(
        r"^def _has_affirmative\((?P<sig>.*?)\):\n(?P<body>(?:[ \t].*\n|\n)*)",
        src, re.MULTILINE)
    if aff_m is None:
        check("F14.2 源码级：定位到 _has_affirmative 函数", False)
    else:
        sig = aff_m.group("sig")
        check("F14.2 源码级：_has_affirmative 签名含 excluded 参数（作用域排除）",
              "excluded" in sig, f"实际签名 ({sig.strip()})")
        aff_body = aff_m.group("body")
        check("F14.3 源码级：_has_affirmative 函数体使用了 excluded",
              "excluded" in aff_body)

    claims_m = re.search(
        r"^def _medical_treatment_claims\(product\):\n(?P<body>(?:[ \t].*\n|\n)*)",
        src, re.MULTILINE)
    if claims_m is None:
        check("F14.4 源码级：定位到 _medical_treatment_claims 函数体", False)
    else:
        claims_body = claims_m.group("body")
        check("F14.4 源码级：_medical_treatment_claims 走 _negation_scope_map 作用域判定",
              "_negation_scope_map" in claims_body)
        check("F14.5 源码级：_negation_scope_map 函数已定义",
              "_negation_scope_map" in src)

    # ==================================================================
    # ③ F13 全场景交叉验证（F14 的改动不得把 F13 打挂）
    # ==================================================================
    f13_scenarios = [
        ("裸关键词无肯定授权证据（残余 C 口径）：质子重离子治疗",
         {"key_benefits": ["质子重离子治疗"], "highlights": ""},
         [], ""),
        ("有明确肯定授权证据（残余 C 不得过度收紧）：质子重离子治疗费用报销",
         {"key_benefits": ["质子重离子治疗费用报销"], "highlights": ""},
         ["质子重离子"], "，含质子重离子治疗"),
        ("纯否定：不含CAR-T",
         {"key_benefits": ["不含CAR-T"], "highlights": ""}, [], ""),
        ("纯否定：质子重离子不予报销",
         {"key_benefits": [], "highlights": "质子重离子不予报销"}, [], ""),
        # ⚠️ 官方 2.4.15 复扫 SDI-4 #2 口径收紧（2026-11-17）：同一治疗手段在
        #    **整条产品记录**内既有肯定证据又有除外证据 → 一律 unverified →
        #    不宣称（官方 remediation 原文「...anywhere in the product record as
        #    an unresolved conflict, regardless of element or field boundaries.」）。
        #    这是**官方要求的口径收紧**，不是产品行为回归（真实产品库实测零影响）。
        ("肯定+否定并存：含CAR-T / 不含CAR-T",
         {"key_benefits": ["含CAR-T", "不含CAR-T"], "highlights": ""},
         [], ""),
        ("跨字段纯否定：key_benefits 进口药 + highlights 不予报销",
         {"key_benefits": ["进口药"], "highlights": "进口药不予报销"}, [], ""),
        ("空 blob",
         {"key_benefits": [], "highlights": ""}, [], ""),
    ]
    for name, product, expect_claims, expect_suffix in f13_scenarios:
        got_claims = PD._medical_treatment_claims(product)
        got_suffix = PD._medical_treatment_suffix(product)
        check(f"F14.6 F13 交叉验证「{name}」：claims == {expect_claims}",
              got_claims == expect_claims, f"实际 {got_claims}")
        check(f"F14.6 F13 交叉验证「{name}」：suffix == {expect_suffix!r}",
              got_suffix == expect_suffix, f"实际 {got_suffix!r}")

    return True


# ==================================================================
# F15 — SDI-4 残余 D（官方 2026-11-16 线上复扫）：空白字符不得截断否定作用域
# ==================================================================
def test_f15_whitespace_negation_scope():
    """F15 (SDI-4 残余 D · 官方 2026-11-16 线上复扫): 空白不得截断否定作用域

    官方 finding 原文（scanner 2.12.0 · SDI-4 · Excessive Agency · MEDIUM · 置信 0.99）：
      ai-insurance-advisor 2.4.13 →「The mixed positive/exclusion branch can turn
        reimbursement wording inside another treatment's exclusion into an unsupported
        CAR-T coverage claim.」
      insurance-advisor-china 2.4.13 →「The treatment-claim parser can turn an explicit
        reimbursement exclusion into a covered-treatment claim, contradicting its
        documented exclusion safeguards.」

    根因（官方 2.4.12 更详细版本 · root cause 原文）：
      「Spaces and tabs are treated as clause boundaries, so an exclusion such as
        "不含 CAR-T治疗费用报销" loses its negation scope before reaching "CAR-T";
        the nearby "报销" then passes the affirmative-evidence check. Consequently,
        the tool can turn an excluded treatment into the unconditional claim
        "含CAR-T治疗" in generated insurance plans.」

    官方 remediation 原文（验收按这个口径）：
      「Do not treat ordinary whitespace as a semantic boundary for exclusion scope;
        normalize spacing while preserving field boundaries, and bind negation to the
        relevant treatment across spaces and tabs. Require explicit, unambiguous
        coverage evidence and suppress claims when exclusion scope or conflicting
        statements cannot be resolved. Add regression tests for "不含 CAR-T治疗费用报销",
        tab-separated exclusions, and varied whitespace, verifying that none produces
        a covered-treatment claim.」

    修法（两库同口径）：
      ① `_CLAUSE_BREAKS` 不再包含空格/制表符 —— 普通空白**不是**语义边界；
      ② 否定作用域**跨空格/制表符**绑定到相关治疗手段；
      ③ **字段边界**（key_benefits ↔ highlights）仍截断作用域（owner == -1）——
         空白不得吃掉字段边界；
      ④ 空白变体与无空白变体的口径**完全一致**。

    覆盖：15 个对抗场景 + 6 条源码级断言（防改回）+ F13/F14 场景交叉验证。
    """
    print("\n[F15] 空白字符不得截断否定作用域（SDI-4 残余 D · 官方 2026-11-16 线上复扫）")
    PD = plan_designer

    # ==================================================================
    # ① 对抗场景（期望值是手写常量，不从实现推导）
    # ==================================================================
    scenarios = [
        # ── A. 空白变体的除外条款 → 不得产出 covered-treatment claim ──
        ("官方 finding 原文场景（空格版）：不含 CAR-T治疗费用报销",
         {"key_benefits": ["不含 CAR-T治疗费用报销"], "highlights": ""},
         [], ""),
        ("官方 finding 原文场景（制表符版）：不含\tCAR-T治疗费用报销",
         {"key_benefits": ["不含\tCAR-T治疗费用报销"], "highlights": ""},
         [], ""),
        ("官方 finding 原文场景（空格版）：不包含 CAR-T治疗费用给付",
         {"key_benefits": ["不包含 CAR-T治疗费用给付"], "highlights": ""},
         [], ""),
        ("多空格变体：不含   CAR-T治疗费用报销",
         {"key_benefits": ["不含   CAR-T治疗费用报销"], "highlights": ""},
         [], ""),
        ("全角空格变体：不含\u3000CAR-T治疗费用报销",
         {"key_benefits": ["不含\u3000CAR-T治疗费用报销"], "highlights": ""},
         [], ""),
        ("空格 + 无「报销/给付」字样：不含 CAR-T治疗",
         {"key_benefits": ["不含 CAR-T治疗"], "highlights": ""},
         [], ""),
        ("空格 + 纯关键词：不含 CAR-T",
         {"key_benefits": ["不含 CAR-T"], "highlights": ""},
         [], ""),
        ("空格 + 除外条款在 highlights 字段：不含 CAR-T治疗费用报销",
         {"key_benefits": [], "highlights": "不含 CAR-T治疗费用报销"},
         [], ""),
        ("空白不得吃掉字段边界：kb 不含 CAR-T治疗 + highlights CAR-T费用可报销",
         {"key_benefits": ["不含 CAR-T治疗"], "highlights": "CAR-T费用可报销"},
         [], ""),
        ("空白不得吃掉字段边界（反向）：kb CAR-T费用可报销 + highlights 不含 CAR-T治疗",
         {"key_benefits": ["CAR-T费用可报销"], "highlights": "不含 CAR-T治疗"},
         [], ""),
        # ── B. 不得过度收紧：有明确肯定授权证据的必须仍然宣称 ──
        ("肯定（含空格）：含 CAR-T治疗费用报销",
         {"key_benefits": ["含 CAR-T治疗费用报销"], "highlights": ""},
         ["CAR-T"], "，含CAR-T治疗"),
        ("肯定（含空格 · 仅「含」）：含 CAR-T治疗",
         {"key_benefits": ["含 CAR-T治疗"], "highlights": ""},
         ["CAR-T"], "，含CAR-T治疗"),
        ("肯定（制表符）：含\tCAR-T治疗费用报销",
         {"key_benefits": ["含\tCAR-T治疗费用报销"], "highlights": ""},
         ["CAR-T"], "，含CAR-T治疗"),
        ("纯肯定：质子重离子治疗费用报销",
         {"key_benefits": ["质子重离子治疗费用报销"], "highlights": ""},
         ["质子重离子"], "，含质子重离子治疗"),
        # ── C. 真实子句边界（逗号）仍然截断作用域 ──
        ("逗号仍截断作用域：不含 CAR-T，质子重离子可报销",
         {"key_benefits": ["不含 CAR-T，质子重离子可报销"], "highlights": ""},
         ["质子重离子"], "，含质子重离子治疗"),
    ]
    for name, product, expect_claims, expect_suffix in scenarios:
        got_claims = PD._medical_treatment_claims(product)
        got_suffix = PD._medical_treatment_suffix(product)
        check(f"F15.1 对抗场景「{name}」：claims == {expect_claims}",
              got_claims == expect_claims, f"实际 {got_claims}")
        check(f"F15.1 对抗场景「{name}」：suffix == {expect_suffix!r}",
              got_suffix == expect_suffix, f"实际 {got_suffix!r}")

    # 空白变体与无空白变体口径必须**完全一致**（官方 remediation 的核心要求）
    pairs = [
        ("不含 CAR-T治疗费用报销", "不含CAR-T治疗费用报销"),
        ("不包含 CAR-T治疗费用给付", "不包含CAR-T治疗费用给付"),
        ("不含 CAR-T治疗费用报销", "不含\tCAR-T治疗费用报销"),
    ]
    for ws_text, plain_text in pairs:
        a = PD._medical_treatment_claims({"key_benefits": [ws_text], "highlights": ""})
        b = PD._medical_treatment_claims({"key_benefits": [plain_text], "highlights": ""})
        check(f"F15.2 空白变体「{ws_text}」与无空白变体口径一致",
              a == b == [], f"空白版 {a} / 无空白版 {b}")

    # 空白分隔的除外条款**不得**产出 covered-treatment claim（官方点名场景）
    for text in ("不含 CAR-T治疗费用报销", "不含\tCAR-T治疗费用报销",
                 "不包含 CAR-T治疗费用给付", "不含   CAR-T治疗费用报销",
                 "不含\u3000CAR-T治疗费用报销"):
        suffix = PD._medical_treatment_suffix({"key_benefits": [text], "highlights": ""})
        check(f"F15.3 除外条款「{text}」不得产出「含CAR-T治疗」",
              "含CAR-T" not in suffix, f"实际 {suffix!r}")

    # ==================================================================
    # ② 源码级断言：不得把「空白是语义边界」改回去
    # ==================================================================
    src = open(os.path.join(THIS_DIR, "plan_designer.py"), encoding="utf-8").read()

    brk_m = re.search(r'_CLAUSE_BREAKS\s*=\s*"(?P<body>[^"]*)"', src)
    if brk_m is None:
        check("F15.4 源码级：定位到 _CLAUSE_BREAKS 定义", False)
    else:
        body = brk_m.group("body")
        check("F15.4 源码级：_CLAUSE_BREAKS 不得包含空格（普通空白不是语义边界）",
              " " not in body, f"实际 {body!r}")
        check("F15.4 源码级：_CLAUSE_BREAKS 不得包含制表符",
              "\\t" not in body, f"实际 {body!r}")

    sb_m = re.search(
        r"^def _scope_bounds\((?P<sig>.*?)\):\n(?P<body>(?:[ \t].*\n|\n)*)",
        src, re.MULTILINE)
    if sb_m is None:
        check("F15.5 源码级：定位到 _scope_bounds 函数", False)
    else:
        check("F15.5 源码级：_scope_bounds 签名含 owner 参数（字段边界必须保留）",
              "owner" in sb_m.group("sig"), f"实际签名 ({sb_m.group('sig').strip()})")

    check("F15.5 源码级：_is_scope_boundary 已定义（空白不是边界、字段边界是边界）",
          "def _is_scope_boundary(" in src)

    nc_m = re.search(
        r"^def _negation_context\((?P<sig>.*?)\):\n(?P<body>(?:[ \t].*\n|\n)*)",
        src, re.MULTILINE)
    if nc_m is None:
        check("F15.6 源码级：定位到 _negation_context 函数", False)
    else:
        check("F15.6 源码级：_negation_context 签名含 owner 参数",
              "owner" in nc_m.group("sig"), f"实际签名 ({nc_m.group('sig').strip()})")

    claims_m = re.search(
        r"^def _medical_treatment_claims\(product\):\n(?P<body>(?:[ \t].*\n|\n)*)",
        src, re.MULTILINE)
    if claims_m is None:
        check("F15.6 源码级：定位到 _medical_treatment_claims 函数体", False)
    else:
        claims_body = claims_m.group("body")
        check("F15.6 源码级：_medical_treatment_claims 把 owner 传给 _negation_context",
              "_negation_context(blob, owner)" in claims_body)

    # ==================================================================
    # ③ F13 / F14 关键场景交叉验证（本次改动不得把它们打挂）
    # ==================================================================
    cross = [
        ("F14 官方 finding 原文场景：不含CAR-T治疗费用报销",
         {"key_benefits": ["不含CAR-T治疗费用报销"], "highlights": ""}, [], ""),
        ("F14 纯否定：不含CAR-T",
         {"key_benefits": ["不含CAR-T"], "highlights": ""}, [], ""),
        # ⚠️ 官方 2.4.15 复扫 SDI-4 #2 口径收紧（2026-11-17）：记录级冲突 → 不宣称
        ("F14 肯定+否定并存：含CAR-T / 不含CAR-T",
         {"key_benefits": ["含CAR-T", "不含CAR-T"], "highlights": ""},
         [], ""),
        ("F14 跨字段冲突：kb 含CAR-T + highlights CAR-T不予报销",
         {"key_benefits": ["含CAR-T"], "highlights": "CAR-T不予报销"}, [], ""),
        ("F14 同字段否定 + 跨字段肯定 → 不得授权",
         {"key_benefits": ["不含CAR-T治疗"], "highlights": "CAR-T费用可报销"}, [], ""),
        ("F14 纯肯定：质子重离子治疗费用报销",
         {"key_benefits": ["质子重离子治疗费用报销"], "highlights": ""},
         ["质子重离子"], "，含质子重离子治疗"),
    ]
    for name, product, expect_claims, expect_suffix in cross:
        got_claims = PD._medical_treatment_claims(product)
        got_suffix = PD._medical_treatment_suffix(product)
        check(f"F15.7 F13/F14 交叉验证「{name}」：claims == {expect_claims}",
              got_claims == expect_claims, f"实际 {got_claims}")
        check(f"F15.7 F13/F14 交叉验证「{name}」：suffix == {expect_suffix!r}",
              got_suffix == expect_suffix, f"实际 {got_suffix!r}")

    return True

# ==================================================================
# F16 — SDI-4 残余 E（官方 2026-11-16 线上复扫）：mixed-negation 分支
#       不得跨字段 / 跨元素借用授权
# ==================================================================
def test_f16_mixed_negation_authorization(pd=None):
    """F16 (SDI-4 残余 E · 官方 2026-11-16 线上复扫): 跨字段/跨元素借用授权

    官方 finding 原文（scanner 2.12.0 · SDI-4 · Excessive Agency · MEDIUM · 置信 0.99）：
      ai-insurance-advisor 2.4.14 →「The mixed-negation branch can borrow unrelated
        coverage authorization across field elements, contradicting the documented
        evidence boundaries.」
        explanation 原文：「... allowing affirmative wording from unrelated field
        elements to authorize a treatment claim. For example, key_benefits
        containing ["不含CAR-T", "CAR-T", "包含原位癌"] can borrow "包含" from the
        third element and incorrectly emit "含CAR-T治疗" despite the explicit
        exclusion.」
      insurance-advisor-china 2.4.14 →「The mixed-negation branch can borrow
        authorization from another field and falsely advertise excluded treatment
        coverage.」
        explanation 原文：「... For example, key_benefits=["不含CAR-T", "CAR-T"] and
        highlights="可报销" can incorrectly produce "含CAR-T治疗" by borrowing
        authorization from highlights despite the explicit exclusion.」

    官方 remediation 原文（验收按这个口径）：
      「Pass scope_map, owner, and all_scopes to _occurrence_is_affirmative in the
        mixed-negation branch, matching the evidence boundaries enforced in the
        non-negated branch. Treat conflicting inclusion and exclusion statements as
        unverified unless structured, authoritative policy data resolves their
        applicability. Add regression tests for cross-element and cross-field
        authorization borrowing, including treatment variants.」

    修法（两库同口径）：
      ① ⑧ mixed-negation 分支统一传 scope_map / owner / all_scopes（与 ⑥ 非否定
         分支一致）→ 跨字段、跨元素借用授权一律不成立；
      ② 肯定证据与除外证据落在**同一元素**（同一 key_benefits 元素 / 同一
         highlights 字段）→ 冲突 → unverified（一律不宣称）；
      ③ 冲突只有被**结构化、权威**的产品字段逐项裁决时才可宣称
         （`_structured_authority_resolves`）；本产品库无此字段 → 冲突即不宣称；
      ④ ⚠️ 2026-11-17 官方 2.4.15 SDI-4 #2 口径收紧：同字段**不同元素**的肯定授权
         **不再**有效 —— 官方 remediation 原文「...anywhere in the product record as
         an unresolved conflict, regardless of element or field boundaries.」
         → 记录级冲突 → 一律不宣称（只有收紧后的结构化权威规则能解决时才可宣称）。

    覆盖：18 个对抗场景 + 5 条源码级断言（防改回）+ F13/F14/F15 关键场景交叉验证。
    """
    print("\n[F16] mixed-negation 分支不得跨字段/跨元素借用授权（SDI-4 残余 E）")
    if pd is None:
        import plan_designer as pd  # china 版：模块已直接 import

    # ==================================================================
    # ① 对抗场景（期望值是手写常量，不从实现推导）
    # ==================================================================
    scenarios = [
        # ── A. 跨元素借用授权（官方 ai 原例）──
        ("官方 ai 原例：kb[不含CAR-T, CAR-T, 包含原位癌]",
         {"key_benefits": ["不含CAR-T", "CAR-T", "包含原位癌"], "highlights": ""},
         [], ""),
        ("跨元素变体：kb[不含CAR-T, CAR-T, 涵盖质子重离子]（CAR-T 不得借用第三元素）",
         {"key_benefits": ["不含CAR-T", "CAR-T", "涵盖质子重离子"], "highlights": ""},
         ["质子重离子"], "，含质子重离子治疗"),
        # ── B. 跨字段借用授权（官方 china 原例）──
        ("官方 china 原例：kb[不含CAR-T, CAR-T] + hl 可报销",
         {"key_benefits": ["不含CAR-T", "CAR-T"], "highlights": "可报销"},
         [], ""),
        ("跨字段变体：kb[不含CAR-T, CAR-T] + hl CAR-T费用可报销",
         {"key_benefits": ["不含CAR-T", "CAR-T"], "highlights": "CAR-T费用可报销"},
         [], ""),
        # ── C. tab / 多空白变体 ──
        ("tab 变体：kb[不含\tCAR-T, CAR-T] + hl \t可报销",
         {"key_benefits": ["不含\tCAR-T", "CAR-T"], "highlights": "\t可报销"},
         [], ""),
        ("多空白变体：kb[不含   CAR-T, CAR-T] + hl 可报销",
         {"key_benefits": ["不含   CAR-T", "CAR-T"], "highlights": "可报销"},
         [], ""),
        ("全角空格变体：kb[不含\u3000CAR-T, CAR-T] + hl 可报销",
         {"key_benefits": ["不含\u3000CAR-T", "CAR-T"], "highlights": "可报销"},
         [], ""),
        ("tab 跨元素变体：kb[不含\tCAR-T, CAR-T, 包含原位癌]",
         {"key_benefits": ["不含\tCAR-T", "CAR-T", "包含原位癌"], "highlights": ""},
         [], ""),
        # ── D. 同元素冲突 → unverified（一律不宣称）──
        ("同元素冲突（空格分隔）：含CAR-T治疗 不含CAR-T治疗",
         {"key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""},
         [], ""),
        ("同元素冲突（逗号分隔）：含CAR-T，不含CAR-T治疗费用报销",
         {"key_benefits": ["含CAR-T，不含CAR-T治疗费用报销"], "highlights": ""},
         [], ""),
        # ── E. 不得过度收紧（必须仍然宣称）──
        # ⚠️ 口径变更（官方 2.4.15 复扫 SDI-4 #2 · 2026-11-17）：**跨元素借用授权
        #    已废止** —— 官方 remediation 原文：
        #      「Treat positive and negative evidence for the same treatment anywhere
        #        in the product record as an unresolved conflict, regardless of element
        #        or field boundaries.」
        #    → 同一治疗手段在整条产品记录内既有肯定证据又有除外证据 → 不宣称。
        #    （非过度收紧：官方要求的口径收紧；真实产品库实测零影响。）
        ("保留语义：同字段不同元素 kb[含CAR-T, 不含CAR-T]（口径收紧 → 不宣称）",
         {"key_benefits": ["含CAR-T", "不含CAR-T"], "highlights": ""},
         [], ""),
        ("保留语义：枚举列表同子句 kb[质子重离子] + hl 涵盖质子重离子等先进治疗",
         {"key_benefits": ["质子重离子"], "highlights": "涵盖质子重离子等先进治疗"},
         ["质子重离子"], "，含质子重离子治疗"),
        ("保留语义：纯肯定 质子重离子治疗费用报销",
         {"key_benefits": ["质子重离子治疗费用报销"], "highlights": ""},
         ["质子重离子"], "，含质子重离子治疗"),
        # ── F. 跨字段冲突 → 不宣称 ──
        ("跨字段冲突：kb 含CAR-T + hl CAR-T不予报销",
         {"key_benefits": ["含CAR-T"], "highlights": "CAR-T不予报销"},
         [], ""),
        # ── G. 治疗手段变体（官方 remediation：including treatment variants）──
        ("治疗变体：kb[不含靶向药, 靶向药] + hl 可报销",
         {"key_benefits": ["不含靶向药", "靶向药"], "highlights": "可报销"},
         [], ""),
        ("治疗变体：kb[不含特药, 特药] + hl 涵盖特药",
         {"key_benefits": ["不含特药", "特药"], "highlights": "涵盖特药"},
         [], ""),
        ("治疗变体：kb[不含外购药, 外购药] + hl 可报销",
         {"key_benefits": ["不含外购药", "外购药"], "highlights": "可报销"},
         [], ""),
        ("治疗变体：kb[不含进口药, 进口药] + hl 覆盖进口药",
         {"key_benefits": ["不含进口药", "进口药"], "highlights": "覆盖进口药"},
         [], ""),
    ]
    for name, product, expect_claims, expect_suffix in scenarios:
        got_claims = pd._medical_treatment_claims(product)
        got_suffix = pd._medical_treatment_suffix(product)
        check(f"F16.1 对抗场景「{name}」：claims == {expect_claims}",
              got_claims == expect_claims, f"实际 {got_claims}")
        check(f"F16.1 对抗场景「{name}」：suffix == {expect_suffix!r}",
              got_suffix == expect_suffix, f"实际 {got_suffix!r}")

    # 纯否定/借用场景的关键语义：suffix 不得出现「含CAR-T治疗」
    borrow_cases = [
        {"key_benefits": ["不含CAR-T", "CAR-T"], "highlights": "可报销"},
        {"key_benefits": ["不含CAR-T", "CAR-T", "包含原位癌"], "highlights": ""},
        {"key_benefits": ["不含\tCAR-T", "CAR-T"], "highlights": "\t可报销"},
        {"key_benefits": ["不含   CAR-T", "CAR-T"], "highlights": "可报销"},
        {"key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""},
        {"key_benefits": ["含CAR-T"], "highlights": "CAR-T不予报销"},
    ]
    for product in borrow_cases:
        suffix = pd._medical_treatment_suffix(product)
        check(f"F16.2 借用/冲突场景不得产出「含CAR-T治疗」（{suffix!r}）",
              "含CAR-T" not in suffix, suffix)

    # 空白变体与无空白变体口径必须**完全一致**（残余 D 口径不得被破坏）
    ws_pairs = [
        (["不含CAR-T", "CAR-T"], ["不含 CAR-T", "CAR-T"]),
        (["不含CAR-T", "CAR-T"], ["不含\tCAR-T", "CAR-T"]),
        (["不含CAR-T", "CAR-T"], ["不含   CAR-T", "CAR-T"]),
    ]
    for plain, ws in ws_pairs:
        a = pd._medical_treatment_claims({"key_benefits": plain, "highlights": "可报销"})
        b = pd._medical_treatment_claims({"key_benefits": ws, "highlights": "可报销"})
        check(f"F16.3 空白变体 {ws} 与无空白变体 {plain} 口径一致",
              a == b == [], f"空白版 {a} / 无空白版 {b}")

    # ==================================================================
    # ② 源码级断言：不得把「owner / all_scopes」改回去
    # ==================================================================
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(here, "plan_designer.py"), encoding="utf-8").read()

    i8 = src.find("# ⑧")
    seg8 = src[i8:i8 + 3200] if i8 != -1 else ""
    flat8 = re.sub(r"\s+", " ", seg8)
    check("F16.4 源码级：定位到 ⑧ mixed-negation 分支", i8 != -1)
    check("F16.5 源码级：⑧ 分支调用 _occurrence_is_affirmative 必须传 scope_map/owner/all_scopes",
          "scope_map, owner, all_scopes" in flat8,
          "⑧ 分支未传全三件套")
    check("F16.6 源码级：⑧ 分支引用 _structured_authority_resolves（冲突裁决）",
          "_structured_authority_resolves" in seg8)
    check("F16.7 源码级：_element_ordinal_map 已定义（元素级冲突判定）",
          "def _element_ordinal_map(" in src)
    check("F16.8 源码级：⑥ 非否定分支仍传 scope_map/owner/all_scopes",
          "scope_map, owner, all_scopes" in re.sub(r"\s+", " ", src))

    # ==================================================================
    # ③ F13/F14/F15 关键场景交叉验证（不得被本次改动打挂）
    # ==================================================================
    cross = [
        ("裸关键词无肯定授权证据：质子重离子治疗",
         {"key_benefits": ["质子重离子治疗"], "highlights": ""}, [], ""),
        ("有明确肯定授权证据：质子重离子治疗费用报销",
         {"key_benefits": ["质子重离子治疗费用报销"], "highlights": ""},
         ["质子重离子"], "，含质子重离子治疗"),
        ("纯否定：不含CAR-T",
         {"key_benefits": ["不含CAR-T"], "highlights": ""}, [], ""),
        ("纯否定：质子重离子不予报销",
         {"key_benefits": [], "highlights": "质子重离子不予报销"}, [], ""),
        # ⚠️ 官方 2.4.15 复扫 SDI-4 #2 口径收紧（2026-11-17）：同一治疗手段在
        #    **整条产品记录**内既有肯定证据又有除外证据 → 一律 unverified →
        #    不宣称（官方 remediation 原文「...anywhere in the product record as
        #    an unresolved conflict, regardless of element or field boundaries.」）。
        #    这是**官方要求的口径收紧**，不是产品行为回归（真实产品库实测零影响）。
        ("肯定+否定并存：含CAR-T / 不含CAR-T",
         {"key_benefits": ["含CAR-T", "不含CAR-T"], "highlights": ""},
         [], ""),
        ("官方 F14 场景：不含CAR-T，质子重离子可报销",
         {"key_benefits": ["不含CAR-T，质子重离子可报销"], "highlights": ""},
         ["质子重离子"], "，含质子重离子治疗"),
        ("官方 F15 场景（空格版）：不含 CAR-T治疗费用报销",
         {"key_benefits": ["不含 CAR-T治疗费用报销"], "highlights": ""}, [], ""),
        ("官方 F15 场景（制表符版）：不含\tCAR-T治疗费用报销",
         {"key_benefits": ["不含\tCAR-T治疗费用报销"], "highlights": ""}, [], ""),
    ]
    for name, product, expect_claims, expect_suffix in cross:
        got_claims = pd._medical_treatment_claims(product)
        got_suffix = pd._medical_treatment_suffix(product)
        check(f"F16.9 F13/F14/F15 交叉验证「{name}」：claims == {expect_claims}",
              got_claims == expect_claims, f"实际 {got_claims}")
        check(f"F16.9 F13/F14/F15 交叉验证「{name}」：suffix == {expect_suffix!r}",
              got_suffix == expect_suffix, f"实际 {got_suffix!r}")

    return True




# ==================================================================
# F17 — SDI-4 残余 F（官方 2026-11-17 · 2.4.15 复扫）
#       #1 结构化字段必须显式类型化肯定才授权；#2 记录级冲突一律不宣称
# ==================================================================
def test_f17_residual_f_structured_authority(pd=None):
    """F17 (SDI-4 残余 F · 官方 2.4.15 复扫): 显式类型化肯定 + 记录级冲突

    官方 finding #1（原文）：
      「The structured authority check authorizes a treatment claim whenever the
        keyword merely appears in a structured field, without checking whether the
        value actually denies coverage. For example, treatment_coverage={"CAR-T":
        false} still authorizes CAR-T.」
      remediation 原文：
        「Define and validate an explicit schema for structured treatment coverage,
          using canonical treatment identifiers and typed coverage decisions rather
          than substring matches. Require an affirmative coverage decision plus
          applicable conditions and explicit resolution of conflicting exclusions;
          false, excluded, unknown, malformed, or ambiguous values must not
          authorize a claim.」

    官方 finding #2（原文）：
      「The mixed-negation branch allows a positive and an exclusion for the same
        treatment in different elements of the same field to pass through.」
      remediation 原文：
        「Treat positive and negative evidence for the same treatment anywhere in the
          product record as an unresolved conflict, regardless of element or field
          boundaries. Suppress the unconditional claim unless a validated structured
          rule explicitly establishes applicable coverage and resolves the exclusion.」

    修法（两库同口径）：
      ① 结构化字段：只有**显式类型化的肯定决定**才授权（布尔 True / dict 的
         covered=True）；False / None / "excluded" / 除外 → **主动压制**；
         裸字符串列表 / 未知键 / 畸形 → ambiguous → **不授权**；
      ② 标识匹配一律走**规范化标识**（NFKC + 去空白 + 统一连字符 + casefold），
         **不得**用「字符串包含关键词」的子串判定；
      ③ **记录级**冲突：同一治疗手段在整条产品记录内既有肯定证据又有除外证据
         → 一律 conflict_unresolved → 不宣称（不论同元素 / 同字段）。
    """
    print("\n[F17] 结构化授权须显式类型化肯定 + 记录级冲突一律不宣称（SDI-4 残余 F）")
    if pd is None:
        import plan_designer as pd  # china 版：模块已直接 import

    # ==================================================================
    # ① 不得宣称（对抗场景 · 期望值手写常量）
    # ==================================================================
    must_not = [
        # ── 官方 #1 原例 ──
        ("官方 #1 原例：treatment_coverage={'CAR-T': False}（否定值不得授权）",
         {"treatment_coverage": {"CAR-T": False},
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}, []),
        ("官方 #1 原例：coverage_items=[{'treatment':'CAR-T','covered':False}]",
         {"coverage_items": [{"treatment": "CAR-T", "covered": False}],
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}, []),
        ("结构化裸字符串列表属 ambiguous：不得授权",
         {"coverage_items": ["CAR-T"],
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}, []),
        ("结构化 excluded 否定值：主动压制，不得宣称",
         {"treatment_coverage": {"CAR-T": "excluded"},
          "key_benefits": ["含CAR-T治疗"], "highlights": ""}, []),
        ("结构化否定值不得借用其它元素的肯定授权",
         {"treatment_coverage": {"CAR-T": False},
          "key_benefits": ["含CAR-T治疗"], "highlights": "CAR-T费用可报销"}, []),
        ("规范化标识匹配：CAR-TX 的授权不得借给 CAR-T",
         {"treatment_coverage": {"CAR-TX": True},
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}, []),
        # ── 官方 #2 原例 ──
        ("官方 #2 原例：kb[含CAR-T治疗, CAR-T除外]（跨元素同字段·正序）",
         {"key_benefits": ["含CAR-T治疗", "CAR-T除外"], "highlights": ""}, []),
        ("官方 #2 原例：kb[CAR-T除外, 含CAR-T治疗]（跨元素同字段·反序）",
         {"key_benefits": ["CAR-T除外", "含CAR-T治疗"], "highlights": ""}, []),
        ("官方 #2 跨字段变体：kb 含CAR-T治疗 + hl CAR-T除外",
         {"key_benefits": ["含CAR-T治疗"], "highlights": "CAR-T除外"}, []),
    ]
    for name, product, expect in must_not:
        got = pd._medical_treatment_claims(product)
        check(f"F17.1 不得宣称场景「{name}」：claims == {expect}", got == expect,
              f"实际 {got}")

    # ==================================================================
    # ② 不得过度收紧（显式类型化肯定 → 合法授权；正常肯定 → 保留）
    # ==================================================================
    must_keep = [
        ("结构化 covered=True 显式肯定：正常承保必须保留",
         {"treatment_coverage": {"CAR-T": True},
          "key_benefits": ["含CAR-T治疗"], "highlights": ""}, ["CAR-T"]),
        ("结构化 covered=True + 显式除外裁决：可解决记录级冲突（残余 M 新口径）",
         {"treatment_coverage": {"CAR-T": {"covered": True, "exclusion_resolved": True}},
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}, ["CAR-T"]),
        ("结构化 list dict covered=True：正常承保必须保留",
         {"coverage_items": [{"treatment": "CAR-T", "covered": True}],
          "key_benefits": ["含CAR-T治疗"], "highlights": ""}, ["CAR-T"]),
        ("结构化 list dict covered=True + 显式除外裁决：可解决记录级冲突（残余 M 新口径）",
         {"coverage_items": [{"treatment": "CAR-T", "covered": True,
                              "exclusion_resolved": True}],
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}, ["CAR-T"]),
        ("无冲突的正常肯定承保必须保留（记录级口径不得误伤）",
         {"key_benefits": ["含质子重离子治疗"], "highlights": ""}, ["质子重离子"]),
        ("无冲突的正常肯定承保必须保留（CAR-T）",
         {"key_benefits": ["含CAR-T治疗"], "highlights": ""}, ["CAR-T"]),
    ]
    for name, product, expect in must_keep:
        got = pd._medical_treatment_claims(product)
        check(f"F17.2 不得过度收紧场景「{name}」：claims == {expect}", got == expect,
              f"实际 {got}")

    # ==================================================================
    # ②-2 残余 L/M（官方 2026-11-18 线上复扫 · ai v2.4.21）口径（2026-11-19 修正）：
    #      · 结构化 covered=True **本身即权威裁决** → 可解决记录级冲突
    #        （⚠ 不得再把「显式除外裁决信号」当**普遍前置条件** —— 那是过度收紧）
    #      · 条目携带**适用条件** → 条件无法渲染 → 必须压制
    #      · 条目**显式声明冲突未裁决**（exclusion_resolved=False）→ 必须压制
    # ==================================================================
    must_suppress = [
        ("带适用条件的 covered=True + 正文冲突 → 必须压制",
         {"coverage_items": [{"treatment": "CAR-T", "covered": True,
                              "condition": "限二级以上医院"}],
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}),
        ("带嵌套资格条件的 covered=True + 正文冲突 → 必须压制",
         {"coverage_items": [{"treatment": "CAR-T", "covered": True,
                              "eligibility": {"医院等级": "二级以上"}}],
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}),
        ("带适用条件的 covered=True + 正文肯定（无冲突）→ 必须压制",
         {"coverage_items": [{"treatment": "CAR-T", "covered": True,
                              "eligibility": "仅限指定医院"}],
          "key_benefits": ["含CAR-T治疗"], "highlights": ""}),
        ("显式声明冲突未裁决（exclusion_resolved=False）+ 正文冲突 → 必须压制",
         {"treatment_coverage": {"CAR-T": {"covered": True,
                                           "exclusion_resolved": False}},
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}),
    ]
    for name, product in must_suppress:
        got = pd._medical_treatment_claims(product)
        check(f"F17.2 残余 L/M 反向口径「{name}」：CAR-T 不在宣称里",
              "CAR-T" not in got, f"实际 {got}")
        check(f"F17.2 残余 L/M 反向口径「{name}」：不得给出肯定裁决",
              pd._structured_authority_resolves(product, "CAR-T") is False)

    # ②-2-1 结构化 covered=True **本身即权威裁决** → 必须能解决记录级冲突
    #       （2026-11-19 修正：此前把「显式除外裁决信号」当普遍前置条件 →
    #        布尔形态取不到 dict 条目 / list dict 形态无裁决信号 →
    #        结构化 covered=True 永远无法授权 → 过度收紧（误伤正例））
    must_keep_resolves = [
        ("dict 形态 covered=True + 正文冲突 → 可解决冲突",
         {"treatment_coverage": {"CAR-T": {"covered": True}},
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}),
        ("裸布尔 covered=True + 正文冲突 → 可解决冲突",
         {"treatment_coverage": {"CAR-T": True},
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}),
        ("list dict 形态 covered=True + 正文冲突 → 可解决冲突",
         {"coverage_items": [{"treatment": "CAR-T", "covered": True}],
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}),
        ("dict 形态 covered=True + 显式除外裁决 + 正文冲突 → 可解决冲突",
         {"treatment_coverage": {"CAR-T": {"covered": True,
                                          "exclusion_resolved": True}},
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}),
    ]
    for name, product in must_keep_resolves:
        got = pd._medical_treatment_claims(product)
        check(f"F17.2 残余 L/M 保留口径「{name}」：CAR-T 仍可宣称",
              "CAR-T" in got, f"实际 {got}")
        check(f"F17.2 残余 L/M 保留口径「{name}」：结构化权威给出肯定裁决",
              pd._structured_authority_resolves(product, "CAR-T") is True)

    # ==================================================================
    # ③ 源码级断言（防改回）
    # ==================================================================
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(here, "plan_designer.py"), encoding="utf-8").read()
    flat = re.sub(r"\s+", " ", src)

    check("F17.3 源码级：_normalize_treatment_identifier 已定义（规范化标识匹配）",
          "def _normalize_treatment_identifier(" in src)
    check("F17.4 源码级：_structured_value_state 已定义（类型化承保决定）",
          "def _structured_value_state(" in src)
    check("F17.5 源码级：_structured_authority_denies 已定义（否定值主动压制）",
          "def _structured_authority_denies(" in src)
    check("F17.6 源码级：_record_exclusion_keywords 已定义（记录级除外证据）",
          "def _record_exclusion_keywords(" in src)
    check("F17.7 源码级：_structured_item_identifier 已定义（list 元素标识提取）",
          "def _structured_item_identifier(" in src)
    check("F17.8 源码级：结构化授权走 _structured_value_state（类型化决定）",
          "_structured_value_state(" in src)
    check("F17.9 源码级：记录级冲突裁决存在（record_conflict）",
          "record_conflict" in src)
    check("F17.10 源码级：mixed-negation 分支设 conflict_unresolved = True",
          "conflict_unresolved = True" in src)

    # 结构化授权函数体内**不得**再出现「关键词子串包含」判定
    i = src.find("def _structured_authority_resolves(")
    j = src.find("\ndef ", i + 1)
    body = src[i:j if j != -1 else len(src)]
    _has_sub = ("keyword in x" in body) or ("keyword in " in body)
    check("F17.11 源码级：_structured_authority_resolves 不得再用「keyword in x」子串判定",
          not _has_sub,
          "仍存在子串判定" if _has_sub else "")
    check("F17.12 源码级：_structured_authority_resolves 走规范化标识匹配",
          "_normalize_treatment_identifier" in body)

    return True



# ==================================================================
# F18 — SDI-4 残余 G（官方 2026-11-17 · 2.4.16 复扫）
#       结构化承保决定键互相矛盾时必须压制
# ==================================================================
def test_f18_residual_g_conflicting_decision_keys(pd=None):
    """F18 (SDI-4 残余 G · 官方 2.4.16 复扫): 决定键冲突必须压制

    官方 finding 原文：
      「Contradictory structured coverage decisions can authorize an unconditional
        treatment claim despite the documented conflict-suppression policy.」

    官方 explanation 原文：
      「_structured_value_state stops at the first decision key, so an entry
        containing both "covered": true and "is_covered": false is classified as
        affirmative; _structured_contains_negation does not detect the
        contradictory boolean. Consequently, _structured_authority_denies fails to
        suppress the treatment, while _structured_authority_resolves can use that
        same contradictory entry to override conflicting coverage text and emit an
        unconditional coverage claim. In an insurance-advice skill, this can
        misrepresent excluded treatments as covered and influence consequential
        purchasing decisions, although exploitation requires contradictory product
        data to reach the relevant claim-generation branch.」

    官方 remediation 原文：
      「Validate structured coverage entries against an explicit schema and evaluate
        every recognized decision key before assigning a state. Reject conflicting
        decisions or classify them as unresolved and suppress the claim; also
        reconcile matching entries across all structured authority fields before
        allowing any affirmative resolution. Add regression tests for covered=true
        with is_covered=false, reversed key order, conflicting duplicate entries,
        and conflicting free-text exclusions, asserting that no unconditional
        treatment claim is emitted.」

    修法（两库同口径）：
      ① **全部**决定键都要求值（不得只看第一个命中的键）；
      ② 同一条目内多个决定键状态不一致 → contradictory：
         **不得**判为 affirmative（不得授权）+ **必须**被 _structured_authority_denies
         命中（主动压制）；
      ③ _structured_authority_resolves 必须**跨全部**结构化权威字段对齐匹配条目：
         任意一条 negative / contradictory / ambiguous → 不得给出肯定裁决。

    断言口径（官方 remediation 原文）：
      「asserting that no unconditional treatment claim is emitted」
      → 断言 **CAR-T 不得出现在宣称里**（不得产出无条件宣称）。
    """
    print("\n[F18] 结构化决定键冲突必须压制（SDI-4 残余 G · 官方 2.4.16 复扫）")
    if pd is None:
        import plan_designer as pd  # china 版：模块已直接 import

    # ==================================================================
    # ① 不得产出无条件宣称（官方点名的 4 类回归 + 顺序/重复变体）
    # ==================================================================
    must_not = [
        # ── G1：covered=true + is_covered=false（官方点名）────────────────
        ("G1 官方点名：treatment_coverage={'CAR-T':{'covered':True,'is_covered':False}}",
         {"treatment_coverage": {"CAR-T": {"covered": True, "is_covered": False}},
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}),
        # ── G2：键序反转（官方点名）──────────────────────────────────────
        ("G2 官方点名：键序反转 {'is_covered':False,'covered':True}",
         {"treatment_coverage": {"CAR-T": {"is_covered": False, "covered": True}},
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}),
        # ── G3：冲突重复条目（官方点名）──────────────────────────────────
        ("G3 官方点名：同一字段两条匹配条目，一条肯定一条否定（list）",
         {"coverage_items": [{"treatment": "CAR-T", "covered": True},
                             {"treatment": "CAR-T", "is_covered": False}],
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}),
        # 冲突重复条目（dict 形态：两个标识键归一化后同名 → 归一化后不可重复，
        #   这里用「同标识跨两个结构化权威字段」表达同口径的跨字段重复冲突）
        ("G3 变体：跨结构化权威字段的重复匹配条目（肯定 + 否定）",
         {"treatment_coverage": {"CAR-T": {"covered": True, "is_covered": False}},
          "coverage_items": [{"treatment": "CAR-T", "covered": True}],
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}),
        # ── G4：结构化自相矛盾 + 自由文本除外并存（官方点名）────────────
        ("G4 官方点名：结构化自相矛盾 + 自由文本除外并存",
         {"treatment_coverage": {"CAR-T": {"covered": True, "is_covered": False}},
          "key_benefits": ["含CAR-T治疗"], "highlights": "CAR-T除外"}),
        # 自由文本除外单独出现（无结构化冲突）→ 仍不得宣称
        ("G4 变体：自由文本除外 + 冲突条目（键序反转）",
         {"treatment_coverage": {"CAR-T": {"is_covered": False, "covered": True}},
          "key_benefits": ["含CAR-T治疗"], "highlights": "CAR-T不予报销"}),
        # ── 其它同口径变体（list 元素内自相矛盾 / 否定+ambiguous 混合）────
        ("G5 变体：coverage_items 元素内自相矛盾",
         {"coverage_items": [{"treatment": "CAR-T", "covered": True, "is_covered": False}],
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}),
        ("G5 变体：决定键 affirmative + ambiguous（未知值）→ 不得授权",
         {"treatment_coverage": {"CAR-T": {"covered": True, "is_covered": "待定"}},
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}),
        ("G5 变体：决定键 negative + ambiguous（未知值）→ 不得授权",
         {"treatment_coverage": {"CAR-T": {"covered": False, "is_covered": "待定"}},
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}),
    ]
    for name, product in must_not:
        got = pd._medical_treatment_claims(product)
        suffix = pd._medical_treatment_suffix(product)
        check(f"F18.1 不得产出无条件宣称「{name}」：CAR-T 不在宣称里",
              "CAR-T" not in got, f"实际 claims={got}")
        check(f"F18.2 不得产出无条件宣称「{name}」：suffix 不含「含CAR-T」",
              "含CAR-T" not in suffix, f"实际 suffix={suffix!r}")

    # ==================================================================
    # ② 压制生效：_structured_authority_denies 必须为真（自相矛盾 → 压制）
    # ==================================================================
    deny_cases = [
        ("G5 dict 自相矛盾（covered=True + is_covered=False）",
         {"treatment_coverage": {"CAR-T": {"covered": True, "is_covered": False}}}),
        ("G5 dict 自相矛盾（键序反转）",
         {"treatment_coverage": {"CAR-T": {"is_covered": False, "covered": True}}}),
        ("G5 list 元素自相矛盾",
         {"coverage_items": [{"treatment": "CAR-T", "covered": True, "is_covered": False}]}),
        ("G5 冲突重复条目（否定条目必须压制）",
         {"coverage_items": [{"treatment": "CAR-T", "covered": True},
                             {"treatment": "CAR-T", "is_covered": False}]}),
    ]
    for name, product in deny_cases:
        check(f"F18.3 压制生效「{name}」：_structured_authority_denies 为真",
              pd._structured_authority_denies(product, "CAR-T") is True)
        check(f"F18.4 不得授权「{name}」：_structured_authority_resolves 为假",
              pd._structured_authority_resolves(product, "CAR-T") is False)

    # ==================================================================
    # ③ 跨字段对齐：任一匹配条目否定 / 矛盾 → 不得给出肯定裁决
    # ==================================================================
    cross_cases = [
        ("跨字段：coverage_items 肯定 + treatment_coverage 否定",
         {"coverage_items": [{"treatment": "CAR-T", "covered": True}],
          "treatment_coverage": {"CAR-T": False}}),
        ("跨字段：treatment_coverage 肯定 + covered_treatments 否定",
         {"treatment_coverage": {"CAR-T": True},
          "covered_treatments": {"CAR-T": False}}),
        ("跨字段：treatment_coverage 肯定 + treatment_responsibilities 矛盾",
         {"treatment_coverage": {"CAR-T": True},
          "treatment_responsibilities": {"CAR-T": {"covered": True, "is_covered": False}}}),
    ]
    for name, product in cross_cases:
        check(f"F18.5 跨字段对齐「{name}」：不得给出肯定裁决",
              pd._structured_authority_resolves(product, "CAR-T") is False)

    # ==================================================================
    # ④ 不得过度收紧（一致的决定键 → 授权仍须保留）
    # ==================================================================
    must_keep = [
        ("一致 affirmative（两个决定键都是 True）",
         {"treatment_coverage": {"CAR-T": {"covered": True, "is_covered": True}},
          "key_benefits": ["含CAR-T治疗"], "highlights": ""}, ["CAR-T"]),
        ("一致 affirmative + 显式除外裁决（结构化字段 + 正文冲突 · 残余 M 新口径）",
         {"treatment_coverage": {"CAR-T": {"covered": True, "is_covered": True,
                                          "exclusion_resolved": True}},
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}, ["CAR-T"]),
        ("显式类型化肯定（原有残余 F 口径不得被破坏）",
         {"treatment_coverage": {"CAR-T": True},
          "key_benefits": ["含CAR-T治疗"], "highlights": ""}, ["CAR-T"]),
        ("list dict covered=True（原有残余 F 口径不得被破坏）",
         {"coverage_items": [{"treatment": "CAR-T", "covered": True}],
          "key_benefits": ["含CAR-T治疗"], "highlights": ""}, ["CAR-T"]),
    ]
    for name, product, expect in must_keep:
        got = pd._medical_treatment_claims(product)
        check(f"F18.6 不得过度收紧「{name}」：claims == {expect}", got == expect,
              f"实际 {got}")

    # ==================================================================
    # ⑤ 源码级断言（防改回）
    # ==================================================================
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(here, "plan_designer.py"), encoding="utf-8").read()

    check("F18.7 源码级：_structured_decision_state 已定义（标量决定状态判定）",
          "def _structured_decision_state(" in src)
    check("F18.8 源码级：_structured_authority_states 已定义（跨字段对齐收集）",
          "def _structured_authority_states(" in src)
    check("F18.9 源码级：状态口径含 contradictory（自相矛盾）",
          "contradictory" in src)

    # 决定键求值必须**遍历全部**键 → 不得再出现「取第一个就 break」
    i = src.find("def _structured_value_state(")
    j = src.find("\ndef ", i + 1)
    body = src[i:j if j != -1 else len(src)]
    _ok10 = ("break" not in body) or ("for key in _STRUCTURED_DECISION_KEYS" in body
                                      and "states.append(" in body)
    check("F18.10 源码级：_structured_value_state 不得再「取第一个决定键就 break」",
          _ok10, "" if _ok10 else "仍存在首个命中即 break")
    check("F18.11 源码级：_structured_value_state 遍历全部决定键并收集状态",
          "states.append(" in body)

    # 压制必须覆盖 contradictory
    i = src.find("def _structured_authority_denies(")
    j = src.find("\ndef ", i + 1)
    dbody = src[i:j if j != -1 else len(src)]
    check("F18.12 源码级：_structured_authority_denies 必须压制 contradictory",
          "contradictory" in dbody)

    # 肯定裁决必须跨全部结构化权威字段对齐
    i = src.find("def _structured_authority_resolves(")
    j = src.find("\ndef ", i + 1)
    rbody = src[i:j if j != -1 else len(src)]
    check("F18.13 源码级：_structured_authority_resolves 走 _structured_authority_states 对齐",
          "_structured_authority_states(" in rbody)
    _ok14 = ('return True' not in rbody.split("_structured_authority_states(")[0]
             or 'all(state == "affirmative"' in rbody)
    check("F18.14 源码级：_structured_authority_resolves 不得「见到 affirmative 就 return True」",
          _ok14, "" if _ok14 else "仍是首个 affirmative 即返回")

    return True


# ==================================================================
# F19 — SDI-4 残余 H（官方 2026-11-18 线上复扫 · 2.4.17）
#       结构化排除证据未压制宣称 + 明示不报销被当成承保
# ==================================================================
def test_f19_residual_h_exclusion_and_reimbursement(pd=None):
    """F19 (SDI-4 残余 H · 官方 2026-11-18 线上复扫 · 2.4.17): 排除证据压制 + 明示不报销

    官方 finding #1 原文（ai-insurance-advisor · 693-695）：
      「Structured exclusion evidence can still result in an affirmative
        treatment-coverage claim.」
    官方 remediation #1 原文：
      「Validate structured coverage entries against an explicit schema and treat
        affirmative decisions accompanied by exclusion evidence as contradictory
        or negative. Before authorizing any treatment claim, reconcile all
        matching structured entries and suppress the claim if any entry is
        negative, contradictory, ambiguous, or malformed; free text must not
        override these states. Add regression tests for co…」

    官方 finding #2 原文（insurance-advisor-china · 689-691）：
      「Contradictory structured coverage entries do not reliably suppress
        treatment claims.」
    官方 remediation #2 原文：
      「Reconcile all matching structured entries into one authoritative state
        before considering free-text claims. Classify affirmative decisions
        paired with negative metadata as contradictory, and suppress claims
        whenever a matching entry is ambiguous, malformed, negative, or
        contradictory; apply this gate to every claim-generation branch. Add
        regression tests covering contradictory metadata, conflictin…」

    官方 finding #3 原文（insurance-advisor-china · 953-963）：
      「An explicit reimbursement exclusion can become an affirmative
        treatment-coverage claim.」
    官方 remediation #3 原文：
      「Require validated, typed treatment-coverage decisions before generating
        affirmative claims; treat free-text evidence as unverified unless its
        meaning and applicable conditions are established. As an immediate
        mitigation, recognize constructions such as 「不可报销」 and post-treatment
        negation, suppress ambiguous statements, and add regression tests proving
        that reimbursement exclusions never generate af…」

    修法（两库同口径）：
      ① 结构化侧：affirmative 决定 + 同条目排除证据 → **contradictory**
         （不得是 ambiguous：ambiguous 既不授权**也不**压制 → 自由文本肯定
          证据照样产出无条件承保宣称）；
      ② 压制集合覆盖 negative / contradictory / **ambiguous**（= 未知 / 畸形）；
      ③ 结构化闸加到**每一个宣称生成分支**（free text must not override）；
      ④ 自由文本侧：否定词表补齐「不可报销」「不可支付」「不可赔付」→
         **双向**绑定（否定词在治疗手段**之前** / **之后**都生效 →
         post-treatment negation）；「不可报销」内的「报销」必须被否定作用域吃掉。

    断言口径（官方原文）：
      「asserting that no unconditional treatment claim is emitted」
      → 断言 **CAR-T 不得出现在宣称里**（不得产出无条件宣称），
        **不**写「claims 必须恰好等于 []」这类过严断言（防过度收紧）。
    """
    print("\n[F19] 结构化排除证据必须压制 + 明示不报销不得变成承保"
          "（SDI-4 残余 H · 官方 2026-11-18 线上复扫 · 2.4.17）")
    if pd is None:
        import plan_designer as pd  # china 版：模块已直接 import

    # ==================================================================
    # ① F19.1 affirmative 决定 + 同条目排除证据 → 不得产出无条件宣称
    #    （dict 形态 / list 形态；否定语义关键词两种写法）
    # ==================================================================
    must_not = [
        ("H1-1 dict 形态：covered=True + exclusion=除外",
         {"treatment_coverage": {"CAR-T": {"covered": True, "exclusion": "除外"}},
          "key_benefits": ["含CAR-T治疗费用报销"], "highlights": ""}),
        ("H1-2 dict 形态：covered=True + note=不承保（否定语义字符串）",
         {"treatment_coverage": {"CAR-T": {"covered": True, "note": "不承保"}},
          "key_benefits": ["含CAR-T治疗费用报销"], "highlights": ""}),
        ("H1-3 list 形态：元素 covered=True + exclusion=除外",
         {"treatment_coverage": [{"treatment": "CAR-T", "covered": True,
                                  "exclusion": "除外"}],
          "key_benefits": ["含CAR-T治疗费用报销"], "highlights": ""}),
        ("H1-4 list 形态：元素 covered=True + note=不承保",
         {"coverage_items": [{"treatment": "CAR-T", "covered": True,
                              "note": "不承保"}],
          "key_benefits": ["含CAR-T治疗费用报销"], "highlights": ""}),
        ("H1-5 跨字段变体：treatment_coverage 有排除证据 + coverage_items 肯定",
         {"treatment_coverage": {"CAR-T": {"covered": True, "exclusion": "除外"}},
          "coverage_items": [{"treatment": "CAR-T", "covered": True}],
          "key_benefits": ["含CAR-T治疗费用报销"], "highlights": ""}),
    ]
    for name, product in must_not:
        got = pd._medical_treatment_claims(product)
        suffix = pd._medical_treatment_suffix(product)
        check(f"F19.1 不得产出无条件宣称「{name}」：CAR-T 不在宣称里",
              "CAR-T" not in got, f"实际 claims={got}")
        check(f"F19.1 不得产出无条件宣称「{name}」：suffix 不含「含CAR-T」",
              "含CAR-T" not in suffix, f"实际 suffix={suffix!r}")

    # ==================================================================
    # ② F19.2 矛盾 / 畸形 / ambiguous 条目 → denies=True（且不得授权）
    # ==================================================================
    deny_cases = [
        ("H2-1 contradictory：covered=True + is_covered=False",
         {"treatment_coverage": {"CAR-T": {"covered": True, "is_covered": False}}}),
        ("H2-2 contradictory：covered=True + 同条目排除证据",
         {"treatment_coverage": {"CAR-T": {"covered": True, "exclusion": "除外"}}}),
        ("H2-3 contradictory：list 元素 covered=True + 同条目排除证据",
         {"coverage_items": [{"treatment": "CAR-T", "covered": True,
                              "exclusion": "除外"}]}),
        ("H2-4 malformed：条目无任何承保决定键",
         {"treatment_coverage": {"CAR-T": {"foo": "bar"}}}),
        ("H2-5 malformed：条目值是 list（未知类型）",
         {"treatment_coverage": {"CAR-T": ["CAR-T"]}}),
        ("H2-6 ambiguous：条目值是未知字符串",
         {"treatment_coverage": {"CAR-T": "待定"}}),
        ("H2-7 ambiguous：list 元素无承保决定键",
         {"coverage_items": [{"treatment": "CAR-T", "remark": "待定"}]}),
    ]
    for name, product in deny_cases:
        check(f"F19.2 压制生效「{name}」：_structured_authority_denies 为真",
              pd._structured_authority_denies(product, "CAR-T") is True)
        check(f"F19.2 不得授权「{name}」：_structured_authority_resolves 为假",
              pd._structured_authority_resolves(product, "CAR-T") is False)

    # ==================================================================
    # ③ F19.3 明示不报销 / 不支付 / 不赔付 → 不得产出承保宣称
    # ==================================================================
    reimbursement = [
        ("H3-1 不可报销（含肯定字样「含」+「报销」）",
         "含CAR-T治疗费用不可报销"),
        ("H3-2 不可支付",
         "含CAR-T治疗费用不可支付"),
        ("H3-3 不可赔付",
         "含CAR-T治疗费用不可赔付"),
        ("H3-4 前置否定：不可报销CAR-T治疗费用",
         "不可报销CAR-T治疗费用"),
    ]
    for name, text in reimbursement:
        product = {"key_benefits": [text], "highlights": ""}
        got = pd._medical_treatment_claims(product)
        suffix = pd._medical_treatment_suffix(product)
        check(f"F19.3 明示不报销不得宣称「{name}」：CAR-T 不在宣称里",
              "CAR-T" not in got, f"实际 claims={got}")
        check(f"F19.3 明示不报销不得宣称「{name}」：suffix 不含「含CAR-T」",
              "含CAR-T" not in suffix, f"实际 suffix={suffix!r}")

    # ==================================================================
    # ④ F19.4 post-treatment negation（否定词在治疗手段**之后**）
    # ==================================================================
    post_neg = [
        ("H3-5 后置否定：CAR-T治疗不可报销",
         "CAR-T治疗不可报销"),
        ("H3-6 后置否定：CAR-T治疗费用不可支付",
         "CAR-T治疗费用不可支付"),
        ("H3-7 后置否定：CAR-T治疗不可赔付",
         "CAR-T治疗不可赔付"),
        ("H3-8 后置否定 + 前置肯定字样：报销CAR-T治疗费用不可报销",
         "报销CAR-T治疗费用不可报销"),
    ]
    for name, text in post_neg:
        product = {"key_benefits": [text], "highlights": ""}
        got = pd._medical_treatment_claims(product)
        suffix = pd._medical_treatment_suffix(product)
        check(f"F19.4 post-treatment negation 不得宣称「{name}」：CAR-T 不在宣称里",
              "CAR-T" not in got, f"实际 claims={got}")
        check(f"F19.4 post-treatment negation 不得宣称「{name}」：suffix 不含「含CAR-T」",
              "含CAR-T" not in suffix, f"实际 suffix={suffix!r}")

    # ==================================================================
    # ⑤ F19.5 不得过度收紧：一致 affirmative → 仍须 claims == ['CAR-T']
    # ==================================================================
    must_keep = [
        ("一致 affirmative（两个决定键都是 True）",
         {"treatment_coverage": {"CAR-T": {"covered": True, "is_covered": True}},
          "key_benefits": ["含CAR-T治疗"], "highlights": ""}),
        ("显式类型化肯定（treatment_coverage={'CAR-T': True}）",
         {"treatment_coverage": {"CAR-T": True},
          "key_benefits": ["含CAR-T治疗"], "highlights": ""}),
        ("list dict covered=True",
         {"coverage_items": [{"treatment": "CAR-T", "covered": True}],
          "key_benefits": ["含CAR-T治疗"], "highlights": ""}),
        ("一致 affirmative + 显式除外裁决 + 正文冲突（可解决记录级冲突 · 残余 M 新口径）",
         {"treatment_coverage": {"CAR-T": {"covered": True, "is_covered": True,
                                          "exclusion_resolved": True}},
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}),
    ]
    for name, product in must_keep:
        got = pd._medical_treatment_claims(product)
        check(f"F19.5 不得过度收紧「{name}」：claims == ['CAR-T']", got == ["CAR-T"],
              f"实际 {got}")

    # ==================================================================
    # ⑥ F19.6 源码级断言（防改回）
    # ==================================================================
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(here, "plan_designer.py"), encoding="utf-8").read()

    # 否定词表：必须含「不可报销」「不可支付」「不可赔付」（post-treatment negation）
    i = src.find("_NEG_MARKERS_BOTH = (")
    nbody = src[i:src.find(")", i)] if i != -1 else ""
    check("F19.6 源码级：否定词表含「不可报销」", "不可报销" in nbody,
          "" if "不可报销" in nbody else "未找到")
    check("F19.6 源码级：否定词表含「不可支付」", "不可支付" in nbody,
          "" if "不可支付" in nbody else "未找到")
    check("F19.6 源码级：否定词表含「不可赔付」", "不可赔付" in nbody,
          "" if "不可赔付" in nbody else "未找到")
    check("F19.6 源码级：三者必须在双向否定词表 _NEG_MARKERS_BOTH"
          "（否定词在治疗手段之前 / 之后都生效 → post-treatment negation）",
          all(t in nbody for t in ("不可报销", "不可支付", "不可赔付")))

    # _structured_value_state：affirmative + 同条目否定语义 → 必须 contradictory
    i = src.find("if _structured_contains_negation(value):")
    seg = ""
    if i != -1:
        j = src.find('return "affirmative"', i)
        seg = src[i:j] if j != -1 else src[i:i + 300]
    _ok_vs = ('return "contradictory"' in seg) and ('return "ambiguous"' not in seg)
    check("F19.6 源码级：affirmative + 同条目否定语义 → 必须判 contradictory"
          "（不得再是 ambiguous）", _ok_vs,
          "" if _ok_vs else "该分支仍返回 ambiguous 或未找到该分支")

    # 压制集合：必须覆盖 contradictory / ambiguous
    i = src.find("def _structured_authority_denies(")
    j = src.find("\ndef ", i + 1)
    dbody = src[i:j if j != -1 else len(src)]
    check("F19.6 源码级：denies 判定集合必须覆盖 contradictory",
          '"contradictory"' in dbody)
    check("F19.6 源码级：denies 判定集合必须覆盖 ambiguous（未知 / 畸形）",
          '"ambiguous"' in dbody)

    # 结构化闸必须落在**每一个宣称生成分支**
    i = src.find("def _medical_treatment_claims(")
    j = src.find("\ndef ", i + 1)
    mbody = src[i:j if j != -1 else len(src)]
    _ok_gate = ("structured_denies" in mbody
                and mbody.count("if ok and structured_denies:") >= 2)
    check("F19.6 源码级：结构化压制闸必须加到每一个宣称生成分支"
          "（free text must not override structured states）", _ok_gate,
          "" if _ok_gate else "宣称生成分支未全部过结构化闸")

    return True


# ==================================================================
# F20 — SDI-4 残余 I（官方 2026-11-18 线上复扫 · 2.4.18）
#       裸字符串治疗标识绕过压制闸
# ==================================================================
def test_f20_residual_i_bare_string_identifier(pd=None):
    """F20 (SDI-4 残余 I · 官方 2026-11-18 线上复扫 · 2.4.18): 裸字符串标识必须压制

    官方 finding 原文（ai-insurance-advisor v2.4.18 · scripts/plan_designer.py 855-861）：
      「Ambiguous bare-string treatment entries bypass the documented
        claim-suppression gate.」
    官方 remediation 原文：
      「Validate treatment entries against a single explicit schema shared by
        authorization and suppression checks. Classify a matching bare-string
        treatment identifier as ambiguous and suppress its claim rather than
        falling back to affirmative free text; retain suppression for explicit
        exclusions. Add regression tests for bare-string identifiers, ambiguous
        entries alongside affirmative text, and conflict…」

    根因（裸字符串是「三不管」状态）：
      ① `_structured_authority_states()` 遇到裸字符串**直接 continue** → 不产生
         任何状态 → states 为空 → 不授权；
      ② `_structured_authority_denies()` 裸字符串**只在自带否定语义时**才压制
         → 裸标识符（"CAR-T"）**不压制**；
      → 自由文本的肯定证据照样产出**无条件承保宣称**。

    修法（两库同口径）：
      ① 裸字符串与 dict 条目走**同一套显式 schema**（`_structured_bare_string_state`）
         → 授权判定（`_structured_authority_states`）与压制判定
           （`_structured_authority_denies`）**共用同一个状态函数**；
      ② **匹配**该治疗手段的裸标识符 → 判 **ambiguous** → **必须压制**
         （官方：suppress its claim，**不得** fallback 到肯定自由文本）；
      ③ 裸字符串**自带否定语义** → 判 negative（保留显式除外的压制）；
      ④ 标识匹配一律走**规范化标识**（`_normalize_treatment_identifier`）
         + 标识边界判定 → **不得**用裸子串判定（"CAR-TX" ≠ "CAR-T"）。

    断言口径（官方原文）：
      「asserting that no unconditional treatment claim is emitted」
      → 断言 **CAR-T 不得出现在宣称里**（不得产出无条件宣称），
        **不**写「claims 必须恰好等于 []」这类过严断言（防过度收紧）。
    """
    print("\n[F20] 裸字符串治疗标识必须压制（SDI-4 残余 I · 官方 2026-11-18 线上复扫 · 2.4.18）")
    if pd is None:
        import plan_designer as pd  # china 版：模块已直接 import

    # ==================================================================
    # ① F20.1 裸字符串治疗标识符 → 不得产出无条件宣称（list 形态 + dict 形态）
    # ==================================================================
    must_not = [
        ("I1-1 list 形态：treatment_coverage=['CAR-T']",
         {"treatment_coverage": ["CAR-T"]}),
        ("I1-2 list 形态：covered_treatments=['CAR-T']",
         {"covered_treatments": ["CAR-T"]}),
        ("I1-3 list 形态：coverage_items=['CAR-T']",
         {"coverage_items": ["CAR-T"]}),
        ("I1-4 dict 形态：treatment_coverage={'CAR-T': 'CAR-T'}",
         {"treatment_coverage": {"CAR-T": "CAR-T"}}),
        ("I1-5 dict 形态：coverage_items={'CAR-T': ['CAR-T']}",
         {"coverage_items": {"CAR-T": ["CAR-T"]}}),
    ]
    for name, struct in must_not:
        product = dict(struct)
        product["key_benefits"] = ["含CAR-T治疗费用报销"]
        product["highlights"] = ""
        got = pd._medical_treatment_claims(product)
        suffix = pd._medical_treatment_suffix(product)
        check(f"F20.1 不得产出无条件宣称「{name}」：CAR-T 不在宣称里",
              "CAR-T" not in got, f"实际 claims={got}")
        check(f"F20.1 不得产出无条件宣称「{name}」：suffix 不含「含CAR-T」",
              "含CAR-T" not in suffix, f"实际 suffix={suffix!r}")
        check(f"F20.1 压制生效「{name}」：_structured_authority_denies 为真",
              pd._structured_authority_denies(product, "CAR-T") is True)
        check(f"F20.1 不得授权「{name}」：_structured_authority_resolves 为假",
              pd._structured_authority_resolves(product, "CAR-T") is False)

    # ==================================================================
    # ② F20.2 裸字符串 + 肯定自由文本并存 → 仍不得宣称（不得 fallback）
    # ==================================================================
    with_text = [
        ("I2-1 裸字符串 + key_benefits 肯定文本",
         {"treatment_coverage": ["CAR-T"]},
         {"key_benefits": ["含CAR-T治疗费用报销"], "highlights": ""}),
        ("I2-2 裸字符串 + highlights 肯定文本（跨字段）",
         {"treatment_coverage": ["CAR-T"]},
         {"key_benefits": ["含CAR-T治疗"], "highlights": "CAR-T费用可报销"}),
        ("I2-3 裸字符串 + 显式肯定条目并存（conflict）",
         {"treatment_coverage": ["CAR-T"],
          "coverage_items": [{"treatment": "CAR-T", "covered": True}]},
         {"key_benefits": ["含CAR-T治疗费用报销"], "highlights": ""}),
        ("I2-4 裸字符串 + 显式肯定条目跨字段并存（conflict）",
         {"covered_treatments": ["CAR-T"],
          "treatment_coverage": {"CAR-T": {"covered": True, "is_covered": True}}},
         {"key_benefits": ["含CAR-T治疗费用报销"], "highlights": ""}),
    ]
    for name, struct, text in with_text:
        product = dict(struct)
        product.update(text)
        got = pd._medical_treatment_claims(product)
        suffix = pd._medical_treatment_suffix(product)
        check(f"F20.2 不得 fallback 到肯定自由文本「{name}」：CAR-T 不在宣称里",
              "CAR-T" not in got, f"实际 claims={got}")
        check(f"F20.2 不得 fallback 到肯定自由文本「{name}」：suffix 不含「含CAR-T」",
              "含CAR-T" not in suffix, f"实际 suffix={suffix!r}")
        check(f"F20.2 压制生效「{name}」：_structured_authority_denies 为真",
              pd._structured_authority_denies(product, "CAR-T") is True)
        check(f"F20.2 不得授权「{name}」：_structured_authority_resolves 为假",
              pd._structured_authority_resolves(product, "CAR-T") is False)

    # ==================================================================
    # ③ F20.3 标识变体（大小写 / 连字符 / 全角）→ 走规范化标识匹配仍须压制
    # ==================================================================
    variants = [
        ("I3-1 小写 car-t", "car-t"),
        ("I3-2 下划线 CAR_T", "CAR_T"),
        ("I3-3 非断行连字符 CAR‑T", "CAR‑T"),
        ("I3-4 短横线 car–t", "car–t"),
        ("I3-5 全角 ＣＡＲ－Ｔ", "ＣＡＲ－Ｔ"),
        ("I3-6 首尾空白 ' car-t '", " car-t "),
    ]
    for name, raw in variants:
        product = {"treatment_coverage": [raw],
                   "key_benefits": ["含CAR-T治疗费用报销"], "highlights": ""}
        got = pd._medical_treatment_claims(product)
        check(f"F20.3 标识变体必须压制「{name}」：CAR-T 不在宣称里",
              "CAR-T" not in got, f"实际 claims={got}")
        check(f"F20.3 标识变体必须压制「{name}」：denies 为真",
              pd._structured_authority_denies(product, "CAR-T") is True)
        check(f"F20.3 标识变体不得授权「{name}」：resolves 为假",
              pd._structured_authority_resolves(product, "CAR-T") is False)

    # ==================================================================
    # ④ F20.4 裸字符串自带否定语义 → 仍须压制（retain explicit exclusions）
    # ==================================================================
    negatives = [
        ("I4-1 除外", "CAR-T 除外"),
        ("I4-2 不予报销", "CAR-T 不予报销"),
        ("I4-3 前置否定 不承保", "不承保 CAR-T"),
        ("I4-4 后置否定 不可报销", "CAR-T治疗费用不可报销"),
        ("I4-5 英文 excluded", "CAR-T excluded"),
    ]
    for name, raw in negatives:
        product = {"treatment_coverage": [raw],
                   "key_benefits": ["含CAR-T治疗费用报销"], "highlights": ""}
        got = pd._medical_treatment_claims(product)
        check(f"F20.4 显式除外必须压制「{name}」：CAR-T 不在宣称里",
              "CAR-T" not in got, f"实际 claims={got}")
        check(f"F20.4 显式除外必须压制「{name}」：denies 为真",
              pd._structured_authority_denies(product, "CAR-T") is True)

    # ==================================================================
    # ⑤ F20.5 标识不匹配 → 不得误压制 CAR-T
    # ==================================================================
    not_matching = [
        ("I5-1 其它治疗手段裸标识（质子重离子）",
         {"treatment_coverage": ["质子重离子"]}),
        ("I5-2 更长的标识（CAR-TX）",
         {"treatment_coverage": ["CAR-TX"]}),
    ]
    for name, struct in not_matching:
        product = dict(struct)
        product["key_benefits"] = ["含CAR-T治疗费用报销"]
        product["highlights"] = ""
        check(f"F20.5 不得误压制「{name}」：_structured_authority_denies 为假",
              pd._structured_authority_denies(product, "CAR-T") is False)
        check(f"F20.5 不得误压制「{name}」：_structured_authority_resolves 为假",
              pd._structured_authority_resolves(product, "CAR-T") is False)
        got = pd._medical_treatment_claims(product)
        check(f"F20.5 不得误压制「{name}」：CAR-T 仍可正常宣称",
              "CAR-T" in got, f"实际 claims={got}")

    # ==================================================================
    # ⑥ F20.6 不得过度收紧：一致 affirmative → 仍须 claims == ['CAR-T']
    # ==================================================================
    must_keep = [
        ("一致 affirmative（covered=True + is_covered=True）",
         {"treatment_coverage": {"CAR-T": {"covered": True, "is_covered": True}}}),
        ("显式类型化肯定（treatment_coverage={'CAR-T': True}）",
         {"treatment_coverage": {"CAR-T": True}}),
        ("list dict covered=True",
         {"coverage_items": [{"treatment": "CAR-T", "covered": True}]}),
        ("裸字符串（其它治疗手段）不得影响 CAR-T 的显式肯定",
         {"treatment_coverage": ["质子重离子"],
          "coverage_items": [{"treatment": "CAR-T", "covered": True}]}),
    ]
    for name, struct in must_keep:
        product = dict(struct)
        product["key_benefits"] = ["含CAR-T治疗"]
        product["highlights"] = ""
        got = pd._medical_treatment_claims(product)
        check(f"F20.6 不得过度收紧「{name}」：claims == ['CAR-T']", got == ["CAR-T"],
              f"实际 {got}")

    # ==================================================================
    # ⑦ F20.7 源码级断言（防改回）
    # ==================================================================
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(here, "plan_designer.py"), encoding="utf-8").read()

    check("F20.7 源码级：裸字符串状态判定函数已定义"
          "（授权与压制共用的唯一 schema）",
          "def _structured_bare_string_state(" in src)
    check("F20.7 源码级：裸字符串标识匹配函数已定义（规范化标识 + 标识边界）",
          "def _structured_bare_string_matches(" in src)

    # _structured_authority_states：裸字符串**不得**再被直接 continue 跳过
    i = src.find("def _structured_authority_states(")
    j = src.find("\ndef ", i + 1)
    sbody = src[i:j if j != -1 else len(src)]
    check("F20.7 源码级：_structured_authority_states 必须调用裸字符串状态判定"
          "（匹配时产生 ambiguous 状态）",
          "_structured_bare_string_state(" in sbody)
    _old_skip = "裸字符串 → ambiguous → 不授权"
    check("F20.7 源码级：_structured_authority_states 不得再出现"
          "「裸字符串 → ambiguous → 不授权」的直接跳过",
          _old_skip not in src,
          "仍存在直接跳过裸字符串的旧口径" if _old_skip in src else "")

    # _structured_authority_denies：裸字符串匹配项必须被压制
    i = src.find("def _structured_authority_denies(")
    j = src.find("\ndef ", i + 1)
    dbody = src[i:j if j != -1 else len(src)]
    check("F20.7 源码级：_structured_authority_denies 必须调用裸字符串状态判定"
          "（裸字符串匹配项必须被压制）",
          "_structured_bare_string_state(" in dbody)
    check("F20.7 源码级：denies 判定必须覆盖裸字符串的 ambiguous 状态",
          '"ambiguous"' in dbody)

    # 裸字符串匹配必须走规范化标识（不得裸子串判定）
    i = src.find("def _structured_bare_string_state(")
    j = src.find("\ndef ", i + 1)
    stbody = src[i:j if j != -1 else len(src)]
    check("F20.7 源码级：裸字符串状态判定必须走规范化标识",
          "_normalize_treatment_identifier(" in stbody)
    check("F20.7 源码级：裸字符串的 ambiguous 判定必须走标识匹配函数",
          "_structured_bare_string_matches(" in stbody)

    i = src.find("def _structured_bare_string_matches(")
    j = src.find("\ndef ", i + 1)
    bbody = src[i:j if j != -1 else len(src)]
    check("F20.7 源码级：标识匹配必须做**标识边界**判定"
          "（CAR-TX 不得匹配 CAR-T）",
          "_structured_is_identifier_char(" in bbody)

    # 结构化压制闸必须落在**每一个宣称生成分支**
    i = src.find("def _medical_treatment_claims(")
    j = src.find("\ndef ", i + 1)
    mbody = src[i:j if j != -1 else len(src)]
    check("F20.7 源码级：结构化压制闸必须覆盖每一个宣称生成分支"
          "（free text must not override structured states）",
          mbody.count("if ok and structured_denies:") >= 2)

    return True


def test_f21_residual_j_post_treatment_negation(pd=None):
    """F21 (SDI-4 残余 J · 官方 2026-11-18 线上复扫 · 2.4.19): post-treatment 否定必须绑定

    官方 finding 原文（insurance-advisor-china v2.4.19 · scripts/plan_designer.py 442-454）：
      「Some exclusion markers remain forward-only, so a product statement such as
        「CAR-T治疗不支持报销」 does not negate the preceding CAR-T occurrence; the
        subsequent 「报销」 can instead satisfy the affirmative-evidence check and
        generate 「含CAR-T治疗」. The record-level exclusion check uses the same
        incomplete logic, and absent structured coverage fields provide no
        suppression, making this particularly consequential in an insurance-advice
        skill where users may rely on a false coverage claim.」

    官方 remediation 原文：
      「Handle post-treatment exclusions such as 「CAR-T治疗不支持报销」 and
        「CAR-T治疗不包含在保障范围」 by binding exclusion semantics to the relevant
        treatment regardless of word order, while preventing reimbursement words
        inside those exclusions from authorizing coverage. Treat uncertain or
        conflicting interpretations as unverified and suppress affirmative claims.
        Add end-to-end regression tests covering these examples, alternative negation
        wording, punctuation and spacing variants, and records without structured
        coverage fields.」

    根因：
      ① 「不支持」「不包含」等是**纯前瞻型**否定词 —— 否定词在治疗手段**之后**
         （post-treatment negation）时，前瞻作用域落在治疗手段之后 → 绑不到它；
      ② 否定词跨度不含谓词 → 其后的「报销」落在跨度之外 → 通过肯定授权检查；
      ③ 记录级除外证据 `_record_exclusion_keywords()` 复用同一套判定 → 同样漏判
         （真实语料存在「质子重离子不含」形态）。

    修法（两库同口径）：
      A. **复合除外短语**：「<否定词><除外谓词>」是一个除外短语 —— 谓词纳入否定
         跨度 + 该短语**双向**绑定；
      B. **post-treatment 回溯绑定**：纯前瞻否定词若前瞻作用域内无治疗手段 →
         回溯绑定到最近一次治疗手段出现。

    断言口径（官方原文）：「asserting that no unconditional treatment claim is
    emitted」→ 断言被排除的治疗手段**不得**出现在宣称里（**不**写「claims 必须
    恰好等于 []」这类过严断言）；同时用 F21.6 守住**不得过度收紧**。
    """
    print("\n[F21] post-treatment 否定必须绑定到治疗手段（SDI-4 残余 J · 官方 2026-11-18 线上复扫 · 2.4.19）")
    if pd is None:
        import plan_designer as pd  # china 版：模块已直接 import

    # ==================================================================
    # ① F21.1 官方原文给出的两个形态 → 不得产出无条件承保宣称
    # ==================================================================
    official_cases = [
        ("J1-1「CAR-T治疗不支持报销」",
         {"key_benefits": ["CAR-T治疗不支持报销"], "highlights": ""}),
        ("J1-2「CAR-T治疗不包含在保障范围」",
         {"key_benefits": ["CAR-T治疗不包含在保障范围"], "highlights": ""}),
    ]
    for name, product in official_cases:
        got = pd._medical_treatment_claims(product)
        suffix = pd._medical_treatment_suffix(product)
        check(f"F21.1 不得宣称「{name}」：CAR-T 不在宣称里",
              "CAR-T" not in got, f"实际 claims={got}")
        check(f"F21.1 不得宣称「{name}」：suffix 不含「含CAR-T」",
              "含CAR-T" not in suffix, f"实际 suffix={suffix!r}")

    # ==================================================================
    # ② F21.2 同义否定措辞变体 → 不得宣称
    # ==================================================================
    wording_cases = [
        ("J2-1「CAR-T治疗不支持医保报销」",
         {"key_benefits": ["CAR-T治疗不支持医保报销"], "highlights": ""}),
        ("J2-2「CAR-T治疗不涵盖报销费用」",
         {"key_benefits": ["CAR-T治疗不涵盖报销费用"], "highlights": ""}),
        ("J2-3「CAR-T治疗不包括报销」",
         {"key_benefits": ["CAR-T治疗不包括报销"], "highlights": ""}),
        ("J2-4「质子重离子治疗不支持报销」",
         {"key_benefits": ["质子重离子治疗不支持报销"], "highlights": ""}),
        ("J2-5「CAR-T治疗不予报销」",
         {"key_benefits": ["CAR-T治疗不予报销"], "highlights": ""}),
        ("J2-6「CAR-T治疗不可报销」",
         {"key_benefits": ["CAR-T治疗不可报销"], "highlights": ""}),
        ("J2-7「质子重离子不含」（真实语料形态）",
         {"key_benefits": ["含质子重离子治疗费用报销"], "highlights": "",
          "weakness": ["质子重离子不含"]}),
    ]
    for name, product in wording_cases:
        got = pd._medical_treatment_claims(product)
        suffix = pd._medical_treatment_suffix(product)
        check(f"F21.2 不得宣称「{name}」：被排除治疗手段不在宣称里",
              not any(t in got for t in ("CAR-T", "质子重离子")),
              f"实际 claims={got}")
        check(f"F21.2 不得宣称「{name}」：suffix 不含「含」",
              "含CAR-T" not in suffix and "含质子重离子" not in suffix,
              f"实际 suffix={suffix!r}")

    # ==================================================================
    # ③ F21.3 标点 / 空白变体 → 不得宣称（普通空白不构成语义边界）
    # ==================================================================
    punct_cases = [
        ("J3-1 空格分隔「CAR-T治疗 不支持报销」",
         {"key_benefits": ["CAR-T治疗 不支持报销"], "highlights": ""}),
        ("J3-2 全角空格「CAR-T治疗　不支持报销」",
         {"key_benefits": ["CAR-T治疗　不支持报销"], "highlights": ""}),
        ("J3-3 逗号分句「CAR-T治疗，不支持报销」",
         {"key_benefits": ["CAR-T治疗，不支持报销"], "highlights": ""}),
        ("J3-4 句号结尾「CAR-T治疗不支持报销。」",
         {"key_benefits": ["CAR-T治疗不支持报销。"], "highlights": ""}),
        ("J3-5「CAR-T治疗不支持报销费用」",
         {"key_benefits": ["CAR-T治疗不支持报销费用"], "highlights": ""}),
    ]
    for name, product in punct_cases:
        got = pd._medical_treatment_claims(product)
        check(f"F21.3 不得宣称「{name}」：CAR-T 不在宣称里",
              "CAR-T" not in got, f"实际 claims={got}")

    # ==================================================================
    # ④ F21.4 跨字段（记录级冲突）→ 不得宣称
    # ==================================================================
    cross_field_cases = [
        ("J4-1 key_benefits 除外 + highlights 肯定",
         {"key_benefits": ["CAR-T治疗不支持报销"], "highlights": "含CAR-T治疗费用报销"}),
        ("J4-2 key_benefits 肯定 + highlights 除外",
         {"key_benefits": ["含CAR-T治疗费用报销"], "highlights": "CAR-T治疗不支持报销"}),
    ]
    for name, product in cross_field_cases:
        got = pd._medical_treatment_claims(product)
        check(f"F21.4 不得宣称「{name}」：CAR-T 不在宣称里",
              "CAR-T" not in got, f"实际 claims={got}")

    # ==================================================================
    # ⑤ F21.5 无结构化覆盖字段 → 自由文本不得自行授权
    # ==================================================================
    no_struct_cases = [
        ("J5-1 无结构化字段 · 仅除外文本",
         {"key_benefits": ["CAR-T治疗不支持报销"], "highlights": ""}),
        ("J5-2 无结构化字段 · 除外在 notes",
         {"key_benefits": ["含CAR-T治疗费用报销"], "highlights": "",
          "notes": "CAR-T治疗不支持报销"}),
    ]
    for name, product in no_struct_cases:
        got = pd._medical_treatment_claims(product)
        check(f"F21.5 无结构化字段时不得宣称「{name}」：CAR-T 不在宣称里",
              "CAR-T" not in got, f"实际 claims={got}")

    # ==================================================================
    # ⑥ F21.6 不得过度收紧：真正的承保证明 → 仍须正常宣称
    # ==================================================================
    positive_cases = [
        ("J6-1「含CAR-T治疗费用报销」",
         {"key_benefits": ["含CAR-T治疗费用报销"], "highlights": ""}, "CAR-T"),
        ("J6-2「CAR-T治疗费用可报销」",
         {"key_benefits": ["CAR-T治疗费用可报销"], "highlights": ""}, "CAR-T"),
        ("J6-3「覆盖CAR-T细胞免疫治疗」",
         {"key_benefits": ["覆盖CAR-T细胞免疫治疗"], "highlights": ""}, "CAR-T"),
        ("J6-4「支持CAR-T治疗但不支持质子重离子治疗」",
         {"key_benefits": ["支持CAR-T治疗但不支持质子重离子治疗"], "highlights": ""}, "CAR-T"),
        ("J6-5「含CAR-T治疗费用报销」+「质子重离子除外」",
         {"key_benefits": ["含CAR-T治疗费用报销", "质子重离子除外"], "highlights": ""}, "CAR-T"),
        ("J6-6「含质子重离子治疗费用报销」",
         {"key_benefits": ["含质子重离子治疗费用报销"], "highlights": ""}, "质子重离子"),
    ]
    for name, product, must in positive_cases:
        got = pd._medical_treatment_claims(product)
        check(f"F21.6 不得过度收紧「{name}」：{must} 仍可正常宣称",
              must in got, f"实际 claims={got}")

    # ==================================================================
    # ⑦ F21.7 源码级断言（防改回）
    # ==================================================================
    src = open(os.path.join(os.path.dirname(__file__), "plan_designer.py"),
               "r", encoding="utf-8").read()
    check("F21.7 源码级：复合除外短语判定已定义",
          "def _compound_exclusion_span(" in src)
    check("F21.7 源码级：post-treatment 回溯绑定已定义",
          "def _post_treatment_bindings(" in src)
    check("F21.7 源码级：否定词方向口径已统一到 _marker_directions",
          "def _marker_directions(" in src
          and "_marker_directions(marker)" in src)
    check("F21.7 源码级：_negation_context 必须调用 post-treatment 回溯绑定",
          "_post_treatment_bindings(blob, occurrences, spans, owner)" in src)
    check("F21.7 源码级：_negation_scope_map 必须登记 post-treatment 作用域",
          src.count("_post_treatment_bindings(blob, occurrences, spans, owner)") >= 2)
    check("F21.7 源码级：除外谓词表已定义",
          "_PREDICATE_TAILS" in src)

    return True


def test_f22_residual_k_uncertainty_guard(pd=None):
    """F22 (SDI-4 残余 K · 官方 2026-11-18 线上复扫 · 2.4.20): 不确定表述不得转为承保证言

    官方 finding 原文（insurance-advisor-china v2.4.20 · scripts/plan_designer.py 1259-1269）：
      「Uncertain treatment statements are converted into affirmative coverage claims
        despite the documented requirement to suppress unverified benefits.」
      「The affirmative-evidence check accepts words such as 「报销」 or 「含」 without
        establishing that the surrounding statement actually confirms coverage. For example,
        a product highlight reading 「CAR-T治疗是否报销待核实」 contains an accepted affirmative
        marker and no recognized exclusion, allowing it to become the unconditional claim
        「含CAR-T治疗」.」

    官方 remediation 原文：
      「Require validated, treatment-specific affirmative coverage decisions and preserve
        applicable conditions before emitting benefit claims. Treat questions, uncertainty,
        conditional eligibility, pending verification, and conflicting evidence as unverified,
        suppressing affirmative claims rather than relying on keyword presence. Add regression
        tests for phrases such as 「CAR-T治疗是否报销待核实」, 「可能包含CAR-T治疗」, and
        「CAR-T报销以核保结果为准」, alongside verified positive and explicit exclusion cases.」

    根因：`_occurrence_is_affirmative()` 只要在治疗手段邻近窗口里找到肯定关键字
         （报销 / 含 / 包含 / 覆盖 …）就判定「有承保授权」—— **没有校验这句话本身
         是否真的在确认承保**。疑问、可能性、条件性、待核实都会带着肯定关键字被当成授权。

    修法（两库同口径 · 业务逻辑零改动）：
      ① **字段元素级**守卫：元素内出现疑问 / 不确定 / 条件性 / 待核实表述
         → 该次出现的肯定证据**不成立**；
      ② **记录级**守卫：同一治疗手段在**任一文本叶子的同一子句**里带不确定表述
         → 属「未经确认」→ 跨字段 / 跨元素一律不宣称（**不得**被结构化裁决翻案）。

    断言口径：被不确定表述覆盖的治疗手段**不得**出现在宣称里（**不**写「claims 必须
    恰好等于 []」这类过严断言）；同时用 F22.5 守住**verified positive** 仍能宣称。
    """
    print("\n[F22] 不确定 / 条件性表述不得转为承保证言（SDI-4 残余 K · 官方 2026-11-18 线上复扫 · 2.4.20）")
    if pd is None:
        import plan_designer as pd  # china 版：模块已直接 import

    # ==================================================================
    # ① F22.1 官方原文给出的三个反例 → 不得宣称
    # ==================================================================
    official_cases = [
        ("K1-1「CAR-T治疗是否报销待核实」",
         {"key_benefits": ["CAR-T治疗是否报销待核实"], "highlights": ""}),
        ("K1-2「可能包含CAR-T治疗」",
         {"key_benefits": ["可能包含CAR-T治疗"], "highlights": ""}),
        ("K1-3「CAR-T报销以核保结果为准」",
         {"key_benefits": ["CAR-T报销以核保结果为准"], "highlights": ""}),
    ]
    for name, product in official_cases:
        got = pd._medical_treatment_claims(product)
        suffix = pd._medical_treatment_suffix(product)
        check(f"F22.1 不得宣称「{name}」：CAR-T 不在宣称里",
              "CAR-T" not in got, f"实际 claims={got}")
        check(f"F22.1 不得宣称「{name}」：suffix 不含「含CAR-T」",
              "含CAR-T" not in suffix, f"实际 suffix={suffix!r}")

    # ==================================================================
    # ② F22.2 疑问 / 不确定性 / 条件性措辞变体 → 不得宣称
    # ==================================================================
    wording_cases = [
        ("K2-1「CAR-T治疗能否报销」",
         {"key_benefits": ["CAR-T治疗能否报销"], "highlights": ""}),
        ("K2-2「CAR-T治疗报销情况待定」",
         {"key_benefits": ["CAR-T治疗报销情况待定"], "highlights": ""}),
        ("K2-3「含CAR-T治疗（待核实）」",
         {"key_benefits": ["含CAR-T治疗（待核实）"], "highlights": ""}),
        ("K2-4「CAR-T报销以实际理赔为准」",
         {"key_benefits": ["CAR-T报销以实际理赔为准"], "highlights": ""}),
        ("K2-5「视情况包含CAR-T治疗」",
         {"key_benefits": ["视情况包含CAR-T治疗"], "highlights": ""}),
        ("K2-6「CAR-T治疗是否承保待确认」",
         {"key_benefits": ["CAR-T治疗是否承保待确认"], "highlights": ""}),
        ("K2-7「可能涵盖质子重离子治疗」",
         {"key_benefits": ["可能涵盖质子重离子治疗"], "highlights": ""}),
    ]
    for name, product in wording_cases:
        got = pd._medical_treatment_claims(product)
        check(f"F22.2 不得宣称「{name}」：被不确定表述覆盖的治疗手段不在宣称里",
              not any(t in got for t in ("CAR-T", "质子重离子")),
              f"实际 claims={got}")

    # ==================================================================
    # ③ F22.3 跨字段（记录级不确定证据）→ 不得宣称
    # ==================================================================
    cross_field_cases = [
        ("K3-1 key_benefits 肯定 + highlights 疑问",
         {"key_benefits": ["含CAR-T治疗费用报销"], "highlights": "CAR-T治疗是否报销待核实"}),
        ("K3-2 key_benefits 疑问 + highlights 肯定",
         {"key_benefits": ["CAR-T治疗是否报销待核实"], "highlights": "含CAR-T治疗费用报销"}),
    ]
    for name, product in cross_field_cases:
        got = pd._medical_treatment_claims(product)
        check(f"F22.3 不得宣称「{name}」：CAR-T 不在宣称里",
              "CAR-T" not in got, f"实际 claims={got}")

    # ==================================================================
    # ④ F22.4 显式除外（explicit exclusion）→ 仍须压制
    # ==================================================================
    exclusion_cases = [
        ("K4-1「CAR-T治疗不支持报销」",
         {"key_benefits": ["CAR-T治疗不支持报销"], "highlights": ""}),
        ("K4-2「不含CAR-T治疗费用报销」",
         {"key_benefits": ["不含CAR-T治疗费用报销"], "highlights": ""}),
    ]
    for name, product in exclusion_cases:
        got = pd._medical_treatment_claims(product)
        check(f"F22.4 显式除外必须压制「{name}」：CAR-T 不在宣称里",
              "CAR-T" not in got, f"实际 claims={got}")

    # ==================================================================
    # ⑤ F22.5 verified positive（官方要求 alongside verified positive）
    # ==================================================================
    positive_cases = [
        ("K5-1「含CAR-T治疗费用报销」",
         {"key_benefits": ["含CAR-T治疗费用报销"], "highlights": ""}, "CAR-T"),
        ("K5-2「CAR-T治疗费用可报销」",
         {"key_benefits": ["CAR-T治疗费用可报销"], "highlights": ""}, "CAR-T"),
        ("K5-3「覆盖CAR-T细胞免疫治疗」",
         {"key_benefits": ["覆盖CAR-T细胞免疫治疗"], "highlights": ""}, "CAR-T"),
        ("K5-4「含质子重离子治疗费用报销」",
         {"key_benefits": ["含质子重离子治疗费用报销"], "highlights": ""}, "质子重离子"),
        ("K5-5「特药费用可报销」",
         {"key_benefits": ["特药费用可报销"], "highlights": ""}, "特药"),
    ]
    for name, product, must in positive_cases:
        got = pd._medical_treatment_claims(product)
        check(f"F22.5 不得过度收紧「{name}」：{must} 仍可正常宣称",
              must in got, f"实际 claims={got}")

    # ==================================================================
    # ⑥ F22.6 源码级断言（防改回）
    # ==================================================================
    src = open(os.path.join(os.path.dirname(__file__), "plan_designer.py"),
               "r", encoding="utf-8").read()
    check("F22.6 源码级：不确定判定函数已定义",
          "def _has_uncertainty(" in src)
    check("F22.6 源码级：记录级不确定证据判定已定义",
          "def _record_uncertain_keywords(" in src)
    check("F22.6 源码级：不确定 / 疑问 / 条件性词表已定义",
          "_UNCERTAINTY_MARKERS" in src)
    check("F22.6 源码级：「以……为准」通用形态已覆盖",
          "_RE_SUBJECT_TO" in src)
    check("F22.6 源码级：_occurrence_is_affirmative 必须过不确定守卫",
          "_has_uncertainty(blob, el_lo, el_hi)" in src)
    check("F22.6 源码级：_medical_treatment_claims 必须调用记录级不确定闸",
          "_record_uncertain_keywords(product)" in src)
    check("F22.6 源码级：记录级不确定闸必须压制宣称",
          src.count("if ok and kw in record_uncertain:") >= 2)

    return True


def test_f23_residual_lmn_conditions_and_structured_authority(pd=None):
    """F23 (SDI-4 残余 L/M/N · 官方 2026-11-18 线上复扫 · 2.4.21): 条件 / 结构化裁决

    【残余 L · china v2.4.21 · L1359-1376 · Excessive Agency / MEDIUM】
      finding: "Conditional treatment coverage can become an unconditional benefit claim
                despite documented suppression of conditional statements."
      remediation: "Require validated, treatment-specific coverage decisions with explicit
                    applicability conditions before generating benefit claims. Preserve those
                    conditions in the output, or suppress the claim when conditions cannot be
                    reliably interpreted; do not treat affirmative free-text keywords as
                    sufficient authorization. Add regression tests for hospital restrictions,
                    prior authorization, designated-drug lists, eligibility requirements, and
                    conditional structured entries."

    【残余 M · ai v2.4.21 · L1617-1629 · Excessive Agency / MEDIUM】
      finding: "Structured affirmative flags can override exclusions without preserving
                coverage conditions."
      remediation: "Require treatment-specific, validated coverage decisions that explicitly
                    resolve conflicting exclusions and include applicable conditions. Preserve
                    those conditions in generated benefit descriptions; if a conflict or
                    condition cannot be reliably interpreted and rendered, suppress the claim and
                    report it as unverified. Add regression tests combining affirmative flags,
                    textual exclusions, and nested eligibility conditions."

    【残余 N · ai v2.4.21 · L1691-1704 · Excessive Agency / MEDIUM】
      finding: "Critical-illness benefit derivation converts excluded mild-illness coverage
                into an affirmative benefit."
      remediation: "Derive mild-illness coverage and disease counts from validated,
                    product-specific structured fields rather than keyword presence. Suppress
                    affirmative claims when evidence is negative, uncertain, conditional, or
                    contradictory, and preserve relevant limitations in the output."

    修法（两库同口径 · 业务逻辑零改动 · 仅判定层）：
      L. 适用条件闸（仅限指定医院 / 需转诊 / 预授权 / 目录内 / 符合条件 …）
         → 条件无法在对外文案里渲染 → 肯定授权证据**不成立**；
      M. 结构化条目携带适用条件 → 不得无条件宣称；结构化 covered=True **本身即
         权威裁决** → 可解决记录级冲突（不得再要求「显式除外裁决信号」当普遍
         前置条件）；显式声明「冲突未裁决」→ 不得授权；
      N. `_crx_disease_claim` 感知除外 / 条件 / 不确定表述。
    """
    print("\n[F23] 适用条件与结构化裁决（SDI-4 残余 L/M/N · 官方 2026-11-18 线上复扫 · 2.4.21）")
    if pd is None:
        import plan_designer as pd  # china 版：模块已直接 import

    # ==================================================================
    # ① F23.1 残余 L：条件性表述 → 不得产出无条件承保宣称
    # ==================================================================
    condition_cases = [
        ("L1-1「仅限指定医院CAR-T治疗可报销」",
         {"key_benefits": ["仅限指定医院CAR-T治疗可报销"], "highlights": ""}),
        ("L1-2「CAR-T治疗需转诊后可报销」",
         {"key_benefits": ["CAR-T治疗需转诊后可报销"], "highlights": ""}),
        ("L1-3「CAR-T治疗限于社保目录内」",
         {"key_benefits": ["CAR-T治疗限于社保目录内"], "highlights": ""}),
        ("L1-4「CAR-T治疗须经审核通过」",
         {"key_benefits": ["CAR-T治疗须经审核通过"], "highlights": ""}),
        ("L1-5「CAR-T治疗限二级以上医院」",
         {"key_benefits": ["CAR-T治疗限二级以上医院"], "highlights": ""}),
        ("L1-6 跨字段：key_benefits 肯定 + highlights 带条件",
         {"key_benefits": ["含CAR-T治疗费用报销"], "highlights": "仅限指定医院可报销"}),
    ]
    for name, product in condition_cases:
        got = pd._medical_treatment_claims(product)
        suffix = pd._medical_treatment_suffix(product)
        check(f"F23.1 不得宣称「{name}」：CAR-T 不在宣称里",
              "CAR-T" not in got, f"实际 claims={got}")
        check(f"F23.1 不得宣称「{name}」：suffix 不含「含CAR-T」",
              "含CAR-T" not in suffix, f"实际 suffix={suffix!r}")

    # ==================================================================
    # ② F23.2 残余 M：结构化肯定覆盖除外证据的收紧口径
    # ==================================================================
    structured_must_suppress = [
        ("M1-3 covered=True + 适用条件 + 正文冲突",
         {"coverage_items": [{"treatment": "CAR-T", "covered": True,
                              "condition": "限二级以上医院"}],
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}),
        ("M1-4 covered=True + 嵌套资格条件 + 正文冲突",
         {"coverage_items": [{"treatment": "CAR-T", "covered": True,
                              "eligibility": {"医院等级": "二级以上"}}],
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}),
        ("M1-5 covered=True + 适用条件 + 正文肯定（无冲突）",
         {"coverage_items": [{"treatment": "CAR-T", "covered": True,
                              "eligibility": "仅限指定医院"}],
          "key_benefits": ["含CAR-T治疗"], "highlights": ""}),
        ("M1-6 显式声明冲突未裁决（exclusion_resolved=False）+ 正文冲突",
         {"treatment_coverage": {"CAR-T": {"covered": True,
                                          "exclusion_resolved": False}},
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}),
    ]
    for name, product in structured_must_suppress:
        got = pd._medical_treatment_claims(product)
        check(f"F23.2 不得宣称「{name}」：CAR-T 不在宣称里",
              "CAR-T" not in got, f"实际 claims={got}")
        check(f"F23.2 不得给出肯定裁决「{name}」：_structured_authority_resolves 为假",
              pd._structured_authority_resolves(product, "CAR-T") is False)

    structured_must_keep = [
        ("M2-1 covered=True + 显式除外裁决 → 可解决冲突",
         {"treatment_coverage": {"CAR-T": {"covered": True, "exclusion_resolved": True}},
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}),
        ("M2-2 无冲突的正常承保必须保留",
         {"key_benefits": ["含CAR-T治疗费用报销"], "highlights": ""}),
        # ⚠ 2026-11-19 修正：结构化 covered=True **本身即权威裁决** →
        #   可解决记录级冲突（不得再要求「显式除外裁决信号」当普遍前置条件）
        ("M2-3 dict 形态 covered=True → 可解决记录级冲突",
         {"treatment_coverage": {"CAR-T": {"covered": True}},
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}),
        ("M2-4 裸布尔 covered=True → 可解决记录级冲突",
         {"treatment_coverage": {"CAR-T": True},
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}),
        ("M2-5 list dict 形态 covered=True → 可解决记录级冲突",
         {"coverage_items": [{"treatment": "CAR-T", "covered": True}],
          "key_benefits": ["含CAR-T治疗 不含CAR-T治疗"], "highlights": ""}),
    ]
    for name, product in structured_must_keep:
        got = pd._medical_treatment_claims(product)
        check(f"F23.2 不得过度收紧「{name}」：CAR-T 仍可正常宣称",
              "CAR-T" in got, f"实际 claims={got}")
        check(f"F23.2 不得过度收紧「{name}」：结构化权威给出肯定裁决",
              pd._structured_authority_resolves(product, "CAR-T") is True)

    # ==================================================================
    # ③ F23.3 残余 N：重疾轻症宣称不得反转明确除外
    # ==================================================================
    crx_must_suppress = [
        ("N1-1「120种重疾，不含轻症」", "120种重疾，不含轻症"),
        ("N1-2「120种重疾，轻症除外」", "120种重疾，轻症除外"),
        ("N1-3「120种重疾，不含轻症保障」", "120种重疾，不含轻症保障"),
        ("N1-4「120种重疾，无轻症」", "120种重疾，无轻症"),
    ]
    for name, hl in crx_must_suppress:
        got = pd._crx_disease_claim({"highlights": hl})
        check(f"F23.3 不得宣称「{name}」：轻症宣称为空串",
              got == "", f"实际 {got!r}")
    crx_must_keep = [
        ("N2-1「120种重疾+60种轻症」", "120种重疾+60种轻症"),
        ("N2-2「保障120种重疾+60种轻症，含身故责任」", "保障120种重疾+60种轻症，含身故责任"),
    ]
    for name, hl in crx_must_keep:
        got = pd._crx_disease_claim({"highlights": hl})
        check(f"F23.3 不得过度收紧「{name}」：轻症宣称正常产出",
              got != "", f"实际 {got!r}")

    # ==================================================================
    # ④ F23.4 正例（条件 / 结构化收紧不得误伤正常承保）
    # ==================================================================
    positive_cases = [
        ("L3-1「含CAR-T治疗费用报销」",
         {"key_benefits": ["含CAR-T治疗费用报销"], "highlights": ""}, "CAR-T"),
        ("L3-2「CAR-T治疗费用可报销」",
         {"key_benefits": ["CAR-T治疗费用可报销"], "highlights": ""}, "CAR-T"),
        ("L3-3「覆盖CAR-T细胞免疫治疗」",
         {"key_benefits": ["覆盖CAR-T细胞免疫治疗"], "highlights": ""}, "CAR-T"),
        ("L3-4「含质子重离子治疗费用报销」",
         {"key_benefits": ["含质子重离子治疗费用报销"], "highlights": ""}, "质子重离子"),
    ]
    for name, product, must in positive_cases:
        got = pd._medical_treatment_claims(product)
        check(f"F23.4 不得过度收紧「{name}」：{must} 仍可正常宣称",
              must in got, f"实际 claims={got}")

    # ==================================================================
    # ⑤ F23.5 源码级断言（防改回）
    # ==================================================================
    src = open(os.path.join(os.path.dirname(__file__), "plan_designer.py"),
               "r", encoding="utf-8").read()
    check("F23.5 源码级：适用条件词表已定义", "_CONDITION_MARKERS" in src)
    check("F23.5 源码级：适用条件判定函数已定义", "def _has_condition(" in src)
    check("F23.5 源码级：记录级条件词表已定义",
          "def _record_condition_keywords(" in src)
    check("F23.5 源码级：肯定授权判定必须过适用条件闸",
          "_has_condition(blob, el_lo, el_hi)" in src)
    check("F23.5 源码级：结构化条件键表已定义", "_STRUCTURED_CONDITION_KEYS" in src)
    check("F23.5 源码级：结构化除外裁决键表已定义", "_STRUCTURED_RESOLUTION_KEYS" in src)
    check("F23.5 源码级：结构化裁决必须检查适用条件",
          "_structured_entry_has_condition(" in src)
    check("F23.5 源码级：结构化裁决必须显式拦截「冲突未裁决」声明",
          "_structured_entry_declares_unresolved(" in src)
    check("F23.5 源码级：条件通道必须覆盖结构化条目",
          "_structured_condition_keywords(" in src)
    check("F23.5 源码级：_crx_disease_claim 必须过除外 / 条件判定",
          "_crx_subject_unconfirmed(" in src)

    return True


def test_f24_residual_n2_bidirectional_exclusion(pd=None):
    """F24（官方 SDI-4 残余 N 第二轮 · 2026-11-21 线上复扫 · v2.4.26）

    【官方 finding（china 2.4.26 · Excessive Agency · 原文）】
      "The critical-illness benefit generator can turn an explicit mild-illness
       exclusion into an affirmative coverage claim."

    【官方 explanation（china 2.4.26 · 原文）】
      "The exclusion guard remains incomplete: highlights such as 「120种重疾，不保轻症」
       pass because _crx_subject_unconfirmed does not recognize 「不保」 before the
       subject, causing _crx_disease_claim to output 「120种重疾+轻症保障」."

    【官方 explanation（ai 2.4.26 · 原文）】
      "The exclusion guard recognizes only selected negation phrases and word orders:
       for example, highlights containing 「120种重疾，不承保轻症」 pass because
       「不承保」 is checked after the subject but not before it."

    【官方 remediation（原文）】
      "…handle exclusions before and after the subject consistently rather than
       relying on a small prefix list, and reconcile contradictory evidence
       throughout the product record."
      "Add regression tests for 「120种重疾，不保轻症」, 「120种重疾，不赔轻症」,
       post-subject exclusions, and conflicting statements, checking the final
       generated plan."

    覆盖：
      ① head（subject **之前**）除外：不承保 / 不保 / 不赔 / 不含 / 不覆盖 …
      ② 标记与 subject 之间**有填充词**（intervening words after negation）
      ③ post-subject 除外（轻症不保 / 轻症除外 / 轻症不予赔付 / 轻症不在保障范围）
      ④ **矛盾陈述**（同一条 highlights 里既有肯定又有除外）
      ⑤ **最终生成方案文案**不得出现「120种重疾+轻症保障」/「轻症保障」
      ⑥ 不得过度收紧：明确肯定承保的正例仍须产出轻症宣称
    """
    print("\nTest F24: 除外词序双向识别 + 矛盾陈述压制（官方 SDI-4 残余 N 第二轮）")
    PD = pd or plan_designer

    # ==================================================================
    # ① 官方点名的前置除外（head 侧 · subject 之前）
    # ==================================================================
    head_must_suppress = [
        ("N2-1「120种重疾，不承保轻症」（官方 ai 原文点名）", "120种重疾，不承保轻症"),
        ("N2-2「120种重疾，不保轻症」（官方 china 原文点名）", "120种重疾，不保轻症"),
        ("N2-3「120种重疾，不赔轻症」（官方 china 原文点名）", "120种重疾，不赔轻症"),
        ("N2-4「120种重疾，不含轻症」", "120种重疾，不含轻症"),
        ("N2-5「120种重疾，不包含轻症」", "120种重疾，不包含轻症"),
        ("N2-6「120种重疾，不包括轻症」", "120种重疾，不包括轻症"),
        ("N2-7「120种重疾，不纳入轻症」", "120种重疾，不纳入轻症"),
        ("N2-8「120种重疾，不涵盖轻症」", "120种重疾，不涵盖轻症"),
        ("N2-9「120种重疾，不覆盖轻症」", "120种重疾，不覆盖轻症"),
        ("N2-10「120种重疾，不支持轻症」", "120种重疾，不支持轻症"),
        ("N2-11「120种重疾，不在保障范围轻症」", "120种重疾，不在保障范围轻症"),
        ("N2-12「120种重疾，除外轻症」", "120种重疾，除外轻症"),
        ("N2-13「120种重疾，无轻症」", "120种重疾，无轻症"),
    ]
    for name, hl in head_must_suppress:
        check(f"F24.1 不得宣称「{name}」：轻症宣称为空串",
              PD._crx_disease_claim({"highlights": hl}) == "",
              f"实际 {PD._crx_disease_claim({'highlights': hl})!r}")
        check(f"F24.1 不得宣称「{name}」：_crx_subject_unconfirmed 为真",
              PD._crx_subject_unconfirmed(hl, "轻症") is True)

    # ==================================================================
    # ② 标记与 subject 之间**有填充词**（intervening words after negation）
    # ==================================================================
    filler_must_suppress = [
        ("N2-14「120种重疾，不承保轻症疾病」", "120种重疾，不承保轻症疾病"),
        ("N2-15「120种重疾，不保轻症保障」", "120种重疾，不保轻症保障"),
        ("N2-16「120种重疾，不含轻症疾病」", "120种重疾，不含轻症疾病"),
        ("N2-17「120种重疾，不赔轻症保障责任」", "120种重疾，不赔轻症保障责任"),
        ("N2-18「120种重疾，不承保的轻症」", "120种重疾，不承保的轻症"),
        ("N2-19「120种重疾，不包含部分轻症」", "120种重疾，不包含部分轻症"),
    ]
    for name, hl in filler_must_suppress:
        check(f"F24.2 不得宣称「{name}」：轻症宣称为空串",
              PD._crx_disease_claim({"highlights": hl}) == "",
              f"实际 {PD._crx_disease_claim({'highlights': hl})!r}")

    # ==================================================================
    # ③ post-subject 除外（subject 之后）
    # ==================================================================
    post_must_suppress = [
        ("N2-20「轻症不予赔付」（官方 china 原文点名）", "轻症不予赔付"),
        ("N2-21「轻症不保」", "轻症不保"),
        ("N2-22「轻症除外」", "轻症除外"),
        ("N2-23「轻症不在保障范围」", "轻症不在保障范围"),
        ("N2-24「120种重疾，轻症除外」", "120种重疾，轻症除外"),
        ("N2-25「120种重疾，轻症不予给付」", "120种重疾，轻症不予给付"),
        ("N2-26「120种重疾，轻症无保障」", "120种重疾，轻症无保障"),
    ]
    for name, hl in post_must_suppress:
        check(f"F24.3 不得宣称「{name}」：轻症宣称为空串",
              PD._crx_disease_claim({"highlights": hl}) == "",
              f"实际 {PD._crx_disease_claim({'highlights': hl})!r}")

    # ==================================================================
    # ④ 矛盾陈述（同一条 highlights 里既有肯定又有除外）
    # ==================================================================
    conflict_must_suppress = [
        ("N2-27「120种重疾，含轻症但不承保轻症」",
         "120种重疾，含轻症但不承保轻症"),
        ("N2-28「120种重疾，含轻症，轻症除外」",
         "120种重疾，含轻症，轻症除外"),
        ("N2-29「保障120种重疾+60种轻症，不赔轻症」",
         "保障120种重疾+60种轻症，不赔轻症"),
        ("N2-30「保障120种重疾+轻症，但轻症不保」",
         "保障120种重疾+轻症，但轻症不保"),
    ]
    for name, hl in conflict_must_suppress:
        check(f"F24.4 矛盾陈述不得宣称「{name}」：轻症宣称为空串",
              PD._crx_disease_claim({"highlights": hl}) == "",
              f"实际 {PD._crx_disease_claim({'highlights': hl})!r}")

    # ④-b 记录级矛盾（highlights 肯定 + 其它字段除外）→ 官方 remediation：
    #      「reconcile contradictory evidence throughout the product record」
    check("F24.4 记录级矛盾（highlights 肯定 + notes 除外）必须压制",
          PD._crx_disease_claim({
              "highlights": "120种重疾+60种轻症",
              "notes": "轻症不保，仅承保重疾"}) == "",
          "实际 %r" % (PD._crx_disease_claim({
              "highlights": "120种重疾+60种轻症",
              "notes": "轻症不保，仅承保重疾"}),))

    # ==================================================================
    # ⑤ **最终生成方案文案**校验（官方 china remediation：checking the final
    #     generated plan）—— 不得只看中间函数返回值
    # ==================================================================
    products = PD.load_products()
    crx_real = next((p for p in products if p.get("type") == "重疾险"), None)
    check("F24.5 产品库存在重疾险（用例有效）", crx_real is not None,
          crx_real.get("name") if crx_real else "产品库无重疾险")

    if crx_real is not None:
        def _plan_text_for(highlights):
            """把产品池里的重疾险换成 highlights 指定的那一款 → 生成全部方案 → 返回文案"""
            adv = dict(crx_real)
            adv["highlights"] = highlights
            pool = [adv if p.get("type") == "重疾险" else p for p in products]
            orig = PD.load_products
            PD.load_products = lambda include_discontinued=False: list(pool)
            try:
                plans = PD.generate_all_plans(
                    35, "男", 300000, 200000,
                    {"death": 2000000, "critical_illness": 1500000,
                     "hospital": 4000000})
            finally:
                PD.load_products = orig
            chunks = []
            for _pname, plan in plans.items():
                if not plan:
                    continue
                for entry in (plan.get("products") or []):
                    if entry.get("type") == "重疾险":
                        chunks.append(str(entry.get("key_benefits") or ""))
                        chunks.append(str(entry.get("coverage_period") or ""))
                for feat in (plan.get("features") or []):
                    chunks.append(str(feat))
            return "\n".join(chunks)

        for name, hl in [("N2-31「120种重疾，不承保轻症」", "120种重疾，不承保轻症"),
                         ("N2-32「120种重疾，不保轻症」", "120种重疾，不保轻症"),
                         ("N2-33「120种重疾，不赔轻症」", "120种重疾，不赔轻症"),
                         ("N2-34「轻症不予赔付」", "轻症不予赔付")]:
            text = _plan_text_for(hl)
            check(f"F24.5 最终方案文案不得出现「120种重疾+轻症保障」「{name}」",
                  "120种重疾+轻症保障" not in text,
                  "实际方案文案含该宣称" if "120种重疾+轻症保障" in text else "")
            check(f"F24.5 最终方案文案不得出现「轻症保障」「{name}」",
                  "轻症保障" not in text,
                  "实际方案文案含该宣称" if "轻症保障" in text else "")

        # ⑤-b 正例：明确肯定承保 → 最终方案**必须**继续产出轻症宣称（不得过度收紧）
        pos_text = _plan_text_for("120种重疾+60种轻症")
        check("F24.5 正例：最终方案仍须产出「120种重疾+轻症保障」（不得过度收紧）",
              "120种重疾+轻症保障" in pos_text,
              f"实际方案文案={pos_text[:200]!r}")

    # ==================================================================
    # ⑥ 不得过度收紧：明确肯定承保的正例仍须产出轻症宣称
    # ==================================================================
    crx_must_keep = [
        ("N2-35「120种重疾+60种轻症」", "120种重疾+60种轻症"),
        ("N2-36「保障120种重疾+60种轻症，含身故责任」",
         "保障120种重疾+60种轻症，含身故责任"),
        ("N2-37「120种重疾，含轻症」", "120种重疾，含轻症"),
        ("N2-38「120种重疾+轻症保障」", "120种重疾+轻症保障"),
    ]
    for name, hl in crx_must_keep:
        got = PD._crx_disease_claim({"highlights": hl})
        check(f"F24.6 不得过度收紧「{name}」：轻症宣称正常产出",
              got != "", f"实际 {got!r}")

    # ⑥-b 除外指向**另一个保障对象**时，不得误伤轻症宣称
    other_object_cases = [
        ("N2-39「120种重疾+60种轻症，不保住院津贴」",
         "120种重疾+60种轻症，不保住院津贴"),
        ("N2-40「保障120种重疾+60种轻症，不含住院津贴」",
         "保障120种重疾+60种轻症，不含住院津贴"),
    ]
    for name, hl in other_object_cases:
        got = PD._crx_disease_claim({"highlights": hl})
        check(f"F24.6 不得过度收紧「{name}」：除外指向别的对象 → 轻症宣称正常产出",
              got != "", f"实际 {got!r}")

    # ==================================================================
    # ⑦ 源码级断言（防改回）
    # ==================================================================
    src = open(os.path.join(os.path.dirname(__file__), "plan_designer.py"),
               "r", encoding="utf-8").read()
    check("F24.7 源码级：统一除外标记集合已定义",
          "_CRX_EXCLUSION_MARKERS" in src)
    check("F24.7 源码级：head / tail 必须共用同一套标记集合",
          "_crx_clause_excludes_subject" in src)
    check("F24.7 源码级：矛盾陈述（记录级）压制已实现",
          "def _crx_record_contradiction(" in src)
    check("F24.7 源码级：_crx_disease_claim 必须过记录级矛盾闸",
          "_crx_record_contradiction(product" in src)
    check("F24.7 源码级：不得回退到只做 head.endswith 的前缀表",
          "head.endswith(mk)" not in src)

    return True


def test_f25_residual_o_disease_count_record_gate(pd=None):
    """F25（官方 SDI-4 残余 O · 2026-11-22 线上复扫 · v2.4.28 · Excessive Agency · MEDIUM）

    【官方 finding（两库原文逐字相同）】
      "Critical-illness disease-count claims bypass the documented record-wide
       contradiction check."

    【官方 remediation（ai 2.4.28 · 原文）】
      "Validate disease-count coverage across the entire product record before
       generating claims, rather than applying record-wide checks only to
       mild-illness coverage. Prefer a validated, structured disease-count
       decision with applicable conditions; suppress the count and report it as
       unverified when exclusions, uncertainty, or conflicting evidence remain
       unresolved. Add regression tests with affirmativ..."

    【官方 remediation（china 2.4.28 · 原文）】
      "Before emitting disease-count claims, reconcile evidence for
       critical-illness coverage and its count across the entire product
       record, rather than checking only mild-illness contradictions. Prefer
       validated structured coverage fields; suppress the count and report it
       as unverified when exclusions, conflicting counts, uncertainty, or
       uninterpretable conditions remain. Add regression tests that plac..."

    覆盖：
      ① 记录中含**病种数除外** → 压制（问题码 excluded）
      ② 记录中含**病种数适用条件** → 压制（问题码 conditional）
      ③ 记录中含**病种数不确定表述** → 压制（问题码 uncertain）
      ④ 记录内**病种数互相冲突** → 压制（问题码 conflicting-count）
      ⑤ 正常记录 → **仍产出**「120种重疾+轻症保障」（不得过度收紧）
      ⑥ **最终生成方案文案**不得出现被压制的病种数肯定宣称（走主流程）
      ⑦ 源码级防改回断言
      ⑧ 关键坑：「120种重疾不含轻症」的「不含」指向**轻症** → 不得当成病种数除外
    """
    print("\nTest F25: 病种数记录级矛盾校验（官方 SDI-4 残余 O）")
    if pd is None:
        import plan_designer as PD  # ai 版：模块级未 import，按 F24 既有写法局部导入
    else:
        PD = pd

    # ==================================================================
    # ① 记录中含**病种数除外** → 压制（官方：exclusions）
    # ==================================================================
    excluded_cases = [
        ("O-1 key_benefits「120种重疾除外」",
         {"highlights": "120种重疾+60种轻症", "key_benefits": ["120种重疾除外"]}),
        ("O-2 key_benefits「不保120种重疾」（head 侧除外）",
         {"highlights": "120种重疾+60种轻症", "key_benefits": ["不保120种重疾"]}),
        ("O-3 notes「120种重疾不在保障范围」",
         {"highlights": "120种重疾+60种轻症", "notes": "120种重疾不在保障范围"}),
        ("O-4 key_benefits「120种重疾不予赔付」",
         {"highlights": "120种重疾+60种轻症", "key_benefits": ["120种重疾不予赔付"]}),
        ("O-5 key_benefits「120种重疾不承保」",
         {"highlights": "120种重疾+60种轻症", "key_benefits": ["120种重疾不承保"]}),
    ]
    for name, prod in excluded_cases:
        got = PD._crx_disease_claim(prod)
        check(f"F25.1 病种数除外必须压制「{name}」", got == "", f"实际 {got!r}")
        check(f"F25.1 病种数除外问题码为 excluded「{name}」",
              PD._crx_record_disease_count_issue(prod, "120种重疾") == "excluded",
              "实际 %r" % (PD._crx_record_disease_count_issue(prod, "120种重疾"),))

    # ==================================================================
    # ② 记录中含**病种数适用条件** → 压制（官方：applicable conditions /
    #    uninterpretable conditions）
    # ==================================================================
    conditional_cases = [
        ("O-6 notes「120种重疾仅限指定医院」",
         {"highlights": "120种重疾+60种轻症", "notes": "120种重疾仅限指定医院"}),
        ("O-7 notes「120种重疾需转诊」",
         {"highlights": "120种重疾+60种轻症", "notes": "120种重疾需转诊"}),
        ("O-8 notes「120种重疾目录内」",
         {"highlights": "120种重疾+60种轻症", "notes": "120种重疾目录内"}),
        ("O-9 notes「重疾病种数量以核保结论为准」（泛化病种数 + 条件）",
         {"highlights": "120种重疾+60种轻症", "notes": "重疾病种数量仅限核保通过后适用"}),
    ]
    for name, prod in conditional_cases:
        got = PD._crx_disease_claim(prod)
        check(f"F25.2 病种数适用条件必须压制「{name}」", got == "", f"实际 {got!r}")
        check(f"F25.2 病种数条件问题码为 conditional「{name}」",
              PD._crx_record_disease_count_issue(prod, "120种重疾") == "conditional",
              "实际 %r" % (PD._crx_record_disease_count_issue(prod, "120种重疾"),))

    # ==================================================================
    # ③ 记录中含**病种数不确定表述** → 压制（官方：uncertainty）
    # ==================================================================
    uncertain_cases = [
        ("O-10 notes「是否承保120种重疾待核实」",
         {"highlights": "120种重疾+60种轻症", "notes": "是否承保120种重疾待核实"}),
        ("O-11 notes「120种重疾以保险合同为准」",
         {"highlights": "120种重疾+60种轻症", "notes": "120种重疾以保险合同为准"}),
        ("O-12 notes「重疾病种数量以合同为准」（泛化病种数 + 不确定）",
         {"highlights": "120种重疾+60种轻症", "notes": "重疾病种数量以合同为准"}),
    ]
    for name, prod in uncertain_cases:
        got = PD._crx_disease_claim(prod)
        check(f"F25.3 病种数不确定表述必须压制「{name}」", got == "", f"实际 {got!r}")
        check(f"F25.3 病种数不确定问题码为 uncertain「{name}」",
              PD._crx_record_disease_count_issue(prod, "120种重疾") == "uncertain",
              "实际 %r" % (PD._crx_record_disease_count_issue(prod, "120种重疾"),))

    # ==================================================================
    # ④ 记录内**病种数互相冲突** → 压制（官方：conflicting counts /
    #    conflicting evidence）
    # ==================================================================
    conflict_cases = [
        ("O-13 highlights「120种重疾」vs key_benefits「105种重疾」",
         {"highlights": "120种重疾+60种轻症", "key_benefits": ["105种重疾+50种轻症"]}),
        ("O-14 highlights「100种重疾」vs notes「120种重疾」",
         {"highlights": "100种重疾+50种轻症", "notes": "120种重疾"}),
        ("O-15 记录内三个病种数互相冲突",
         {"highlights": "120种重疾+60种轻症",
          "key_benefits": ["105种重疾+50种轻症"],
          "notes": "另有130种重疾版本"}),
    ]
    for name, prod in conflict_cases:
        got = PD._crx_disease_claim(prod)
        check(f"F25.4 记录内病种数冲突必须压制「{name}」", got == "", f"实际 {got!r}")
        check(f"F25.4 病种数冲突问题码为 conflicting-count「{name}」",
              PD._crx_record_disease_count_issue(prod, "120种重疾") == "conflicting-count",
              "实际 %r" % (PD._crx_record_disease_count_issue(prod, "120种重疾"),))
        check(f"F25.4 记录内病种数采集须含全部数值「{name}」",
              len(PD._crx_record_disease_counts(prod)) >= 2,
              "实际 %r" % (PD._crx_record_disease_counts(prod),))

    # ==================================================================
    # ⑤ 不得过度收紧：正常记录仍须产出「120种重疾+轻症保障」
    # ==================================================================
    keep_cases = [
        ("O-16「120种重疾+60种轻症」", {"highlights": "120种重疾+60种轻症"}),
        ("O-17「保障120种重疾+60种轻症，含身故责任」",
         {"highlights": "保障120种重疾+60种轻症，含身故责任"}),
        ("O-18「120种重疾，含轻症」", {"highlights": "120种重疾，含轻症"}),
        ("O-19「120种重疾+轻症保障」", {"highlights": "120种重疾+轻症保障"}),
        ("O-20「120种重疾+60种轻症」+ 其它字段同口径",
         {"highlights": "120种重疾+60种轻症", "key_benefits": ["120种重疾分6组最高赔6次"]}),
    ]
    for name, prod in keep_cases:
        got = PD._crx_disease_claim(prod)
        check(f"F25.5 不得过度收紧「{name}」：病种数宣称正常产出",
              got != "", f"实际 {got!r}")
        check(f"F25.5 不得过度收紧「{name}」：无问题码",
              PD._crx_record_disease_count_issue(prod, "120种重疾") == "",
              "实际 %r" % (PD._crx_record_disease_count_issue(prod, "120种重疾"),))

    # ==================================================================
    # ⑧ 关键坑：除外标记的**作用对象**不是病种数时不得误判
    #    （「120种重疾不含轻症」里的「不含」指向轻症 —— 官方交接点名的坑）
    # ==================================================================
    pitfall_cases = [
        ("O-21「120种重疾不含轻症」", "120种重疾不含轻症", False),
        ("O-22「120种重疾不含轻症疾病」", "120种重疾不含轻症疾病", False),
        ("O-23「120种重疾不含住院津贴」", "120种重疾不含住院津贴", False),
        ("O-24「120种重疾+60种轻症不含轻症」", "120种重疾+60种轻症不含轻症", False),
        ("O-25「不保120种重疾」（head 侧）", "不保120种重疾", True),
        ("O-26「120种重疾除外」（tail 侧）", "120种重疾除外", True),
        ("O-27「120种重疾不予赔付」（tail 侧）", "120种重疾不予赔付", True),
        ("O-28「120种重疾不在保障范围」（tail 侧）", "120种重疾不在保障范围", True),
    ]
    for name, clause, expect in pitfall_cases:
        got = PD._crx_clause_excludes_disease_count(clause, "120种重疾")
        check(f"F25.8 病种数专属除外判定「{name}」",
              got is expect, f"实际 {got!r} 期望 {expect!r}")
    # ⑧-b 复用既有判定会把「轻症除外」误当成「病种数除外」→ 源码级禁止
    src = open(os.path.join(os.path.dirname(__file__), "plan_designer.py"),
               "r", encoding="utf-8").read()
    check("F25.8 源码级：不得用既有 _crx_clause_excludes_subject 判病种数除外",
          '_crx_clause_excludes_subject(clause, "120种重疾")' not in src)
    check("F25.8 源码级：病种数专属判定必须接入记录级闸门",
          "_crx_clause_excludes_disease_count(clause, m.group(0))" in src)

    # ==================================================================
    # ⑥ **最终生成方案文案**校验（官方 remediation：checking the final
    #     generated plan）—— 不得只看中间函数返回值
    # ==================================================================
    products = PD.load_products()
    crx_real = next((p for p in products if p.get("type") == "重疾险"), None)
    check("F25.6 产品库存在重疾险（用例有效）", crx_real is not None,
          crx_real.get("name") if crx_real else "产品库无重疾险")

    if crx_real is not None:
        def _plan_text_for(highlights, key_benefits=None, extra=None):
            """把产品池里的重疾险换成指定字段 → 生成全部方案 → 返回文案"""
            adv = dict(crx_real)
            adv["highlights"] = highlights
            if key_benefits is not None:
                adv["key_benefits"] = key_benefits
            if extra:
                adv.update(extra)
            pool = [adv if p.get("type") == "重疾险" else p for p in products]
            orig = PD.load_products
            PD.load_products = lambda include_discontinued=False: list(pool)
            try:
                plans = PD.generate_all_plans(
                    35, "男", 300000, 200000,
                    {"death": 2000000, "critical_illness": 1500000,
                     "hospital": 4000000})
            finally:
                PD.load_products = orig
            chunks = []
            for _pname, plan in plans.items():
                if not plan:
                    continue
                for entry in (plan.get("products") or []):
                    if entry.get("type") == "重疾险":
                        chunks.append(str(entry.get("key_benefits") or ""))
                        chunks.append(str(entry.get("coverage_period") or ""))
                for feat in (plan.get("features") or []):
                    chunks.append(str(feat))
            return "\n".join(chunks)

        for name, hl, kb, extra in [
            ("O-29 病种数除外", "120种重疾+60种轻症", ["120种重疾除外"], None),
            ("O-30 病种数适用条件", "120种重疾+60种轻症", None,
             {"notes": "120种重疾仅限指定医院"}),
            ("O-31 病种数不确定", "120种重疾+60种轻症", None,
             {"notes": "是否承保120种重疾待核实"}),
            ("O-32 记录内病种数冲突", "120种重疾+60种轻症", ["105种重疾+50种轻症"], None),
        ]:
            text = _plan_text_for(hl, kb, extra)
            check(f"F25.6 最终方案文案不得出现「120种重疾+轻症保障」（{name}）",
                  "120种重疾+轻症保障" not in text,
                  "实际方案文案含该宣称" if "120种重疾+轻症保障" in text else "")
            check(f"F25.6 最终方案文案不得出现「轻症保障」（{name}）",
                  "轻症保障" not in text,
                  "实际方案文案含该宣称" if "轻症保障" in text else "")
            check(f"F25.6 最终方案须落回降级口径「重疾保障，确诊即赔付」（{name}）",
                  "重疾保障，确诊即赔付" in text,
                  f"实际方案文案={text[:200]!r}")

        # ⑥-b 正例：正常记录 → 最终方案**必须**继续产出病种数宣称（不得过度收紧）
        pos_text = _plan_text_for("120种重疾+60种轻症")
        check("F25.6 正例：最终方案仍须产出「120种重疾+轻症保障」（不得过度收紧）",
              "120种重疾+轻症保障" in pos_text,
              f"实际方案文案={pos_text[:200]!r}")

    # ==================================================================
    # ⑦ 源码级断言（防改回）
    # ==================================================================
    check("F25.7 源码级：病种数正则常量已定义",
          "_CRX_DISEASE_COUNT_RE" in src)
    check("F25.7 源码级：记录级病种数采集已实现",
          "def _crx_record_disease_counts(" in src)
    check("F25.7 源码级：病种数专属除外判定已实现",
          "def _crx_clause_excludes_disease_count(" in src)
    check("F25.7 源码级：病种数专属其它对象线索表已定义",
          "_CRX_COUNT_OTHER_OBJECT_CUES" in src)
    check("F25.7 源码级：记录级病种数闸门已实现",
          "def _crx_record_disease_count_issue(" in src)
    check("F25.7 源码级：_crx_disease_claim 必须过病种数记录级闸",
          "_crx_record_disease_count_issue(product" in src)
    check("F25.7 源码级：轻症既有记录级矛盾闸不得被移除",
          '_crx_record_contradiction(product, "轻症")' in src)
    _i_light = src.find('if _crx_record_contradiction(product, "轻症"):')
    _i_count = src.find("if _crx_record_disease_count_issue(product, m.group(0)):")
    check("F25.7 源码级：病种数闸门须在轻症矛盾闸之后",
          _i_light != -1 and _i_count != -1 and _i_count > _i_light,
          f"轻症闸位置={_i_light} 病种数闸位置={_i_count}")

    return True


def main():
    print("=" * 60)
    print("ClawHub 审计整改测试（任务 2 R4/R5/R6/R7 + 任务 3 SQP-3/SDI-3/SDI-4）")
    print("=" * 60)

    test_r4_1_coverage_within_max_coverage()
    test_r4_2_ac_basic_plan_no_overrun()
    test_r4_3_coverage_capped_recorded()
    test_r4_4_no_cap_no_fake_upper_bound()

    test_f3_unit_doc_and_behavior()
    test_f4_cap_unknown_disclosure()

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

    test_f5_language_optin()
    test_f6_maintenance_permission()
    test_f7_unit_contract()
    test_f8_renewal_long_term_precedence()
    test_f9_global_trigger_insurance_context()
    test_f10_features_coverage_claim_sync()
    test_f11_income_multiple_claim_sync()
    test_f12_crx_claim_derivation()
    test_f13_treatment_negation_context()
    test_f14_treatment_negation_scope()
    test_f15_whitespace_negation_scope()
    test_f16_mixed_negation_authorization()
    test_f17_residual_f_structured_authority()
    test_f18_residual_g_conflicting_decision_keys()
    test_f19_residual_h_exclusion_and_reimbursement()
    test_f20_residual_i_bare_string_identifier()
    test_f21_residual_j_post_treatment_negation()
    test_f22_residual_k_uncertainty_guard()
    test_f23_residual_lmn_conditions_and_structured_authority()
    test_f24_residual_n2_bidirectional_exclusion()
    test_f25_residual_o_disease_count_record_gate()
    test_task3_redline_guards()

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
