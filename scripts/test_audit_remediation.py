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


def test_task3_redline_guards():
    """任务 3 红线守卫：token 计数 / 规范三字节级一致 / products.json md5"""
    print("\nTest 任务3 红线守卫")
    text = _read_skill_md()

    n_phone = text.count("400-860-0058")
    ok = (n_phone == 6)
    check(f"400-860-0058 在 SKILL.md 出现次数 == 6（实际 {n_phone}）", ok)

    n_company = text.count("安盛天平")
    ok2 = (n_company == 8)
    check(f"安盛天平 在 SKILL.md 出现次数 == 8（实际 {n_company}）", ok2)

    n_lock = text.count("🔒")
    ok3 = (n_lock == 4)
    check(f"🔒 在 SKILL.md 出现次数 == 4（实际 {n_lock}）", ok3)

    ok4 = ("🔒 待确认后展示" not in text)
    check("「🔒 待确认后展示」不出现（保持直接展示策略）", ok4)

    # products.json md5 必须不变
    import hashlib
    prod_path = os.path.join(SKILL_DIR, "references", "products.json")
    with open(prod_path, "rb") as f:
        digest = hashlib.md5(f.read()).hexdigest()
    ok5 = (digest == PRODUCTS_MD5)
    check(f"references/products.json md5 == {PRODUCTS_MD5}（实际 {digest}）", ok5)

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

    # 「### 规范三」段落必须与 git HEAD 字节级一致
    head = _head_skill_md()
    if head is None:
        print("  [SKIP] git HEAD:SKILL.md 不可用 → 跳过「规范三」字节级比对（非失败）")
        ok7 = True
    else:
        ok7 = (_section_norm3(head) == _section_norm3(text))
        check("「### 规范三」段落与 git show HEAD:SKILL.md 字节级一致", ok7)

    # 新增整改章节标题不得含 🔒
    ok8 = ("## 🛡️ ClawHub 安全审计整改记录 · 任务 3" in text)
    check("存在「🛡️ ClawHub 安全审计整改记录 · 任务 3」章节（标题不含 🔒）", ok8)

    # frontmatter 版本号
    ok9 = ("version: 2.3.8" in text.split("---", 2)[1])
    check("frontmatter version == 2.3.8", ok9)

    return all([ok, ok2, ok3, ok4, ok5, ok6, ok7, ok8, ok9])


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
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
