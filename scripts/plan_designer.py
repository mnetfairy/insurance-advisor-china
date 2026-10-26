#!/usr/bin/env python3
"""
方案设计工具
根据需求分析结果，自动生成2-3套方案（基础版/标准版/全面版）

🆕 2026-10-27 计算口径修正（收入/预算）+ 预算硬约束
   1) I2 预算硬约束：新增 _enforce_budget(plan, budget, annual_income)。
      保费上限口径统一为 min(年度预算, 年收入 × 档位比例)：
        基础版 10% / 标准版 15% / 全面版 20%
      超预算时先按比例下调最后加入产品的保额（下限 = 产品 min_coverage，
      无 min_coverage 时用原保额 60%），用同一 calculate_product_premium 重算；
      仍超预算则按档位顺序移除可选险种（基础版 医疗险→意外险；标准/全面版 意外险→医疗险）。
      每次调整写入 plan["budget_adjustments"]。
      基础版：意外险保费校验改用 budget（不再是 budget * 1.2），
              医疗险加入前必须校验累计保费 ≤ budget。
   2) I3 产品池与 premium_calculator.py 对齐：默认不推荐已停售/已下架产品
      （探查结论见 premium_calculator.py 顶部注释）。
      china 版原已有部分过滤（is_active / is_duplicate / delisting_time == 已停售 /
      data_quality == garbage），本次统一为同一判定口径。
   3) 每个方案输出 budget_planning 块（年度保费上限 / 方案年保费 / 占年收入比 /
      是否在预算内 / 说明）。
   保费计算公式本身未改动。
"""

import json
import os
import re
import sys

# ---------------------------------------------------------------------------
# 产品有效性判定（与 premium_calculator.py 同一口径）
#
# references/products.json 字段取值分布探查结论（2536 款）：
#   is_active          : True 603 / False 1933
#   validity_status    : 已停售 1897 / DISCONTINUED 80 / 在售新品 222 / 在售老品 176
#                        / 在售常规 116 / MODIFIED 17 / VALID 5 / SKIPPED 4
#                        / 信息缺失 3 / 字段缺失 16
#   delisting_time     : "已停售" 1880 / "仍在售" 454 / 日期串(YYYY 或 YYYY-MM) 57
#                        / "待核实" 37 / 缺失或 null 108
#   data_quality       : garbage 37 / 其余无此字段
#   is_duplicate       : True 56 / False 68 / 字段缺失 2412
# 判定：is_active is False 或 validity_status ∈ {已停售, DISCONTINUED}
#       或 delisting_time == "已停售" 或 delisting_time 为日期串 → 视为已停售/已下架。
# 三条信号并集排除 2017 款；剩余 519 款再剔除 garbage 37 + duplicate 1 → 481 款进入产品池。
# ---------------------------------------------------------------------------
_RE_DELIST_DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


def _is_product_discontinued(product):
    """产品是否已停售/已下架（基于真实字段分布判定）。"""
    if product.get("is_active") is False:
        return True
    if product.get("validity_status") in ("已停售", "DISCONTINUED"):
        return True
    delisting = str(product.get("delisting_time") or "").strip()
    if delisting == "已停售":
        return True
    if delisting and _RE_DELIST_DATE.match(delisting):
        return True
    return False


def _is_product_eligible(product, include_discontinued=False):
    """产品是否可进入推荐池。"""
    if not include_discontinued and _is_product_discontinued(product):
        return False
    if product.get("data_quality") == "garbage":
        return False
    if product.get("is_duplicate") is True:
        return False
    return True


def load_products(include_discontinued=False):
    """加载产品数据（默认已应用有效性过滤，排除已停售/重复/脏数据）。"""
    product_file = os.path.join(os.path.dirname(__file__), "../references/products.json")
    with open(product_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    products = [p for p in data["products"]
                if _is_product_eligible(p, include_discontinued=include_discontinued)]
    return products


def select_products(products, product_type, criteria="recommended"):
    """按类型筛选产品"""
    filtered = [p for p in products if p["type"] == product_type]
    if not filtered:
        return []
    # 按保费排序（性价比）
    if criteria == "cheapest":
        return sorted(filtered, key=lambda x: x.get("premium_per_10k", 999))
    elif criteria == "recommended":
        # 推荐中等价位产品
        return sorted(filtered, key=lambda x: x.get("premium_per_10k", 999))
    return filtered

def design_plan(plan_type, age, gender, annual_income, annual_budget, coverage_needs):
    """设计保险方案"""
    products = load_products()

    if plan_type == "基础版":
        return design_basic_plan(age, gender, annual_income, annual_budget, coverage_needs, products)
    elif plan_type == "标准版":
        return design_standard_plan(age, gender, annual_income, annual_budget, coverage_needs, products)
    elif plan_type == "全面版":
        return design_premium_plan(age, gender, annual_income, annual_budget, coverage_needs, products)
    else:
        return None


def calculate_product_premium(product, age, gender, coverage, payment_term):
    """计算产品保费"""
    age_factor = 1.0
    if age >= 18 and age <= 30:
        age_factor = 0.8
    elif age >= 31 and age <= 40:
        age_factor = 1.0
    elif age >= 41 and age <= 50:
        age_factor = 1.3
    elif age >= 51 and age <= 55:
        age_factor = 1.6

    gender_factor = 1.0 if gender in ["男", "男性"] else 0.85

    if product["type"] == "医疗险":
        if age <= 30:
            return max(coverage * 0.0003, 200)
        elif age <= 40:
            return max(coverage * 0.0004, 200)
        elif age <= 50:
            return max(coverage * 0.0006, 200)
        else:
            return max(coverage * 0.001, 200)

    if product["type"] == "意外险":
        return max(coverage * 0.001, 100)

    payment_factor = 1.0
    if payment_term == "趸交":
        payment_factor = 0.85
    elif payment_term == "3年":
        payment_factor = 0.95
    elif payment_term == "5年":
        payment_factor = 1.0
    elif payment_term == "10年":
        payment_factor = 1.05
    elif payment_term == "20年":
        payment_factor = 1.15

    base = (coverage / 10000) * product.get("premium_per_10k", 250)
    return round(base * age_factor * gender_factor * payment_factor, 2)


# ---------------------------------------------------------------------------
# I2 预算硬约束
# ---------------------------------------------------------------------------

def _product_index(products):
    """建立 (type, product_name) → 产品记录 的索引，供保费重算使用。"""
    return {(p.get("type"), p.get("name")): p for p in products}


def _coverage_floor(product, entry):
    """保额下调下限：产品 min_coverage（单位万元→元）；无 min_coverage 时用原保额 60%。"""
    current = entry.get("coverage") or 0
    floor = None
    if product:
        raw_min = product.get("min_coverage")
        if raw_min is not None:
            unit = product.get("coverage_unit") or "万元"
            try:
                floor = float(raw_min) * (10000 if unit == "万元" else 1)
            except (TypeError, ValueError):
                floor = None
    if not floor or floor <= 0:
        return current * 0.6
    return min(floor, current)


def _refresh_coverage_text(entry, from_coverage, to_coverage):
    """保额变化后同步 key_benefits 中内嵌的保额数字。"""
    kb = entry.get("key_benefits")
    if not isinstance(kb, str):
        return
    old_wan = from_coverage // 10000
    new_wan = to_coverage // 10000
    if old_wan and f"{old_wan}万" in kb:
        entry["key_benefits"] = kb.replace(f"{old_wan}万", f"{new_wan}万")


def _enforce_budget(plan, budget, annual_income, age=None, gender=None,
                    product_index=None, removal_order=None):
    """把方案年保费压到年度保费上限以内。

    步骤：
      1. 若 annual_premium > budget，从最后加入的产品开始按比例下调 coverage
         （下限 = 产品 min_coverage，无则用原保额 60%），用同一
         calculate_product_premium 重算，直到 <= budget 或无可下调空间。
      2. 仍超预算：按 removal_order 依次移除可选险种
         （基础版 医疗险→意外险；标准/全面版 意外险→医疗险）。
      3. 每次调整写入 plan["budget_adjustments"]。

    Args:
        plan: 方案 dict（含 products / annual_premium）
        budget: 年度保费上限
        annual_income: 年收入（用于占年收入比）
        age / gender: 保费重算所需
        product_index: (type, name) → 产品记录
        removal_order: 移除可选险种的顺序（产品 type 列表）
    """
    plan.setdefault("budget_adjustments", [])
    adjustments = plan["budget_adjustments"]
    product_index = product_index or {}
    removal_order = removal_order or []

    if not budget or budget <= 0:
        return plan

    # ---- 步骤 1：按比例下调保额 ----
    # 从最后加入的产品开始；逐个下调到「该产品可承受的最大保额」或下限。
    # 即使某产品降到下限仍无法独自把总保费拉进预算，也照样降到下限，
    # 然后继续处理更早加入的产品（直到总保费 <= budget 或所有产品都无下调空间）。
    for entry in reversed(list(plan.get("products", []))):
        if plan["annual_premium"] <= budget:
            break
        product = product_index.get((entry.get("type"), entry.get("product_name")))
        if product is None or age is None or gender is None:
            continue
        current_coverage = entry.get("coverage") or 0
        floor = _coverage_floor(product, entry)
        if current_coverage <= floor:
            continue  # 已到下限，无下调空间

        payment_term = entry.get("payment_term")

        def total_at(coverage, _entry=entry, _product=product, _term=payment_term):
            """给定保额下的方案总保费。"""
            premium = calculate_product_premium(_product, age, gender, coverage, _term)
            return plan["annual_premium"] - _entry["annual_premium"] + premium

        # 保额与保费单调相关 → 二分查找可行上限（找不到则取下限）
        lo, hi = int(floor), int(current_coverage)
        best = int(floor)
        while lo <= hi:
            mid = (lo + hi) // 2
            if total_at(mid) <= budget:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1

        old_coverage = current_coverage
        old_premium = entry["annual_premium"]
        entry["coverage"] = best
        entry["annual_premium"] = calculate_product_premium(product, age, gender, best, payment_term)
        plan["annual_premium"] = plan["annual_premium"] - old_premium + entry["annual_premium"]
        _refresh_coverage_text(entry, old_coverage, best)
        adjustments.append({
            "type": "coverage_downscale",
            "product": entry.get("product_name"),
            "product_type": entry.get("type"),
            "from_coverage": old_coverage,
            "to_coverage": best,
            "premium_before": round(old_premium, 2),
            "premium_after": round(entry["annual_premium"], 2),
            "reason": "超出年度保费预算，按比例下调保额",
        })

    # ---- 步骤 2：移除可选险种 ----
    for product_type in removal_order:
        if plan["annual_premium"] <= budget:
            break
        for idx in range(len(plan.get("products", [])) - 1, -1, -1):
            entry = plan["products"][idx]
            if entry.get("type") != product_type:
                continue
            premium = entry.get("annual_premium", 0)
            plan["products"].pop(idx)
            plan["annual_premium"] -= premium
            plan["total_coverage"] -= entry.get("coverage", 0)
            adjustments.append({
                "type": "product_removed",
                "product": entry.get("product_name"),
                "product_type": product_type,
                "removed_coverage": entry.get("coverage"),
                "removed_premium": round(premium, 2),
                "reason": "超出年度保费预算且保额无可下调空间，移除该可选险种",
            })
            break

    plan["annual_premium"] = round(plan["annual_premium"], 2)
    plan["total_coverage"] = max(0, plan.get("total_coverage", 0))
    return plan


def _attach_budget_planning(plan, budget, annual_income, ratio, note=""):
    """为方案附加 budget_planning 块。"""
    plan["budget_planning"] = {
        "年度保费上限": round(budget, 2),
        "方案年保费": round(plan["annual_premium"], 2),
        "占年收入比": round(plan["annual_premium"] / annual_income * 100, 1) if annual_income else None,
        "是否在预算内": plan["annual_premium"] <= budget,
        "说明": "保费上限 = min(年度预算, 年收入×比例)；超出部分已自动下调保额或移除可选险种",
        "上限口径": f"min(年度预算 {budget}, 年收入 × {int(ratio * 100)}%)",
    }
    if note:
        plan["budget_planning"]["备注"] = note
    return plan


def design_basic_plan(age, gender, annual_income, annual_budget, coverage_needs, products):
    """基础版方案：低保费基本保障"""
    budget = min(annual_budget, annual_income * 0.10)  # 上限 = min(年度预算, 年收入 10%)
    plan = {
        "plan_name": "基础版",
        "description": "以最低成本建立基础保障，覆盖核心风险",
        "annual_premium": 0,
        "total_coverage": 0,
        "products": []
    }

    # 定期寿险 - 选择性价比高的
    tl_products = [p for p in products if p["type"] == "定期寿险"]
    if not tl_products:
        return _finalize_plan(plan, budget, annual_income, 0.10, age, gender, products)
    tl_product = min(tl_products, key=lambda x: x.get("premium_per_10k", 999))
    tl_coverage = min(coverage_needs.get("death", 500000), 1000000)
    tl_premium = calculate_product_premium(tl_product, age, gender, tl_coverage, "20年")
    if plan["annual_premium"] + tl_premium <= budget:
        plan["products"].append({
            "type": "定期寿险",
            "product_name": tl_product["name"],
            "company": tl_product["company"],
            "coverage": tl_coverage,
            "annual_premium": tl_premium,
            "payment_term": "20年",
            "coverage_period": "至60周岁",
            "key_benefits": "身故/全残保障，保护家人"
        })
        plan["annual_premium"] += tl_premium
        plan["total_coverage"] += tl_coverage

    # 意外险（保费校验使用 budget，不再使用 budget * 1.2）
    ac_products = [p for p in products if p["type"] == "意外险"]
    if ac_products:
        ac_product = min(ac_products, key=lambda x: x.get("premium_per_10k", 999))
        ac_coverage = min(annual_income * 5, 3000000)
        ac_premium = calculate_product_premium(ac_product, age, gender, ac_coverage, "年交")
        if plan["annual_premium"] + ac_premium <= budget:
            plan["products"].append({
                "type": "意外险",
                "product_name": ac_product["name"],
                "company": ac_product["company"],
                "coverage": ac_coverage,
                "annual_premium": ac_premium,
                "payment_term": "年交",
                "coverage_period": "1年",
                "key_benefits": "意外身故/伤残/医疗，100万保额仅需几百元"
            })
            plan["annual_premium"] += ac_premium
            plan["total_coverage"] += ac_coverage

    # 医疗险（加入前必须校验累计保费 ≤ budget）
    mi_products = [p for p in products if p["type"] == "医疗险" and "保证续保" in (p.get("notes") or "")]
    if not mi_products:
        mi_products = [p for p in products if p["type"] == "医疗险"]
    mi_product = mi_products[0] if mi_products else None
    if mi_product:
        mi_coverage = 2000000
        mi_premium = calculate_product_premium(mi_product, age, gender, mi_coverage, "年交")
        if plan["annual_premium"] + mi_premium <= budget:
            plan["products"].append({
                "type": "医疗险",
                "product_name": mi_product["name"],
                "company": mi_product["company"],
                "coverage": mi_coverage,
                "annual_premium": mi_premium,
                "payment_term": "年交",
                "coverage_period": "1年",
                "key_benefits": "百万医疗，不限社保，进口药/靶向药均可报销"
            })
            plan["annual_premium"] += mi_premium
            plan["total_coverage"] += mi_coverage
        else:
            plan.setdefault("budget_adjustments", []).append({
                "type": "product_skipped",
                "product": mi_product["name"],
                "product_type": "医疗险",
                "reason": "加入医疗险后累计保费将超出年度保费上限，未加入",
            })

    return _finalize_plan(plan, budget, annual_income, 0.10, age, gender, products)


def design_standard_plan(age, gender, annual_income, annual_budget, coverage_needs, products):
    """标准版方案：全面基础保障+重疾"""
    budget = min(annual_budget, annual_income * 0.15)  # 上限 = min(年度预算, 年收入 15%)
    plan = {
        "plan_name": "标准版",
        "description": "保障全面，含重疾保障，适合大多数家庭",
        "annual_premium": 0,
        "total_coverage": 0,
        "products": []
    }

    # 定期寿险 - 推荐中国人寿星Combo
    tl_products = [p for p in products if p["type"] == "定期寿险"]
    if not tl_products:
        return _finalize_plan(plan, budget, annual_income, 0.15, age, gender, products)
    tl_product = next((p for p in tl_products if "星" in p["name"]), tl_products[0])
    tl_coverage = min(coverage_needs.get("death", 1000000), 2000000)
    tl_premium = calculate_product_premium(tl_product, age, gender, tl_coverage, "20年")
    plan["products"].append({
        "type": "定期寿险",
        "product_name": tl_product["name"],
        "company": tl_product["company"],
        "coverage": tl_coverage,
        "annual_premium": tl_premium,
        "payment_term": "20年",
        "coverage_period": "至60周岁",
        "key_benefits": "身故/全残保障，保费低保障高"
    })
    plan["annual_premium"] += tl_premium
    plan["total_coverage"] += tl_coverage

    # 重疾险 - 推荐平安福或国寿福
    crx_products = [p for p in products if p["type"] == "重疾险"]
    if crx_products:
        crx_product = next((p for p in crx_products if "福" in p["name"] and "终身" in (p.get("coverage_period") or "")), crx_products[0])
        crx_coverage = min(coverage_needs.get("critical_illness", annual_income * 3), 500000)
        crx_premium = calculate_product_premium(crx_product, age, gender, crx_coverage, "20年")
        plan["products"].append({
            "type": "重疾险",
            "product_name": crx_product["name"],
            "company": crx_product["company"],
            "coverage": crx_coverage,
            "annual_premium": crx_premium,
            "payment_term": "20年",
            "coverage_period": "终身",
            "key_benefits": f"120种重疾+轻症保障，确诊即赔付{crx_coverage//10000}万"
        })
        plan["annual_premium"] += crx_premium
        plan["total_coverage"] += crx_coverage

    # 医疗险 - 选保证续保20年的
    mi_products = [p for p in products if p["type"] == "医疗险" and "20年" in (p.get("coverage_period") or "")]
    if not mi_products:
        mi_products = [p for p in products if p["type"] == "医疗险"]
    if mi_products:
        mi_product = mi_products[0]
        mi_coverage = 4000000
        mi_premium = calculate_product_premium(mi_product, age, gender, mi_coverage, "年交")
        plan["products"].append({
            "type": "医疗险",
            "product_name": mi_product["name"],
            "company": mi_product["company"],
            "coverage": mi_coverage,
            "annual_premium": mi_premium,
            "payment_term": "年交",
            "coverage_period": "保证续保20年",
            "key_benefits": "长期医疗保障，20年续保稳定"
        })
        plan["annual_premium"] += mi_premium
        plan["total_coverage"] += mi_coverage

    # 意外险
    ac_products = [p for p in products if p["type"] == "意外险"]
    if ac_products:
        ac_product = next((p for p in ac_products if "百万" in p["name"]), ac_products[0])
        ac_coverage = min(annual_income * 5, 3000000)
        ac_premium = calculate_product_premium(ac_product, age, gender, ac_coverage, "年交")
        plan["products"].append({
            "type": "意外险",
            "product_name": ac_product["name"],
            "company": ac_product["company"],
            "coverage": ac_coverage,
            "annual_premium": ac_premium,
            "payment_term": "年交",
            "coverage_period": "1年",
            "key_benefits": "含猝死保障，意外医疗不限社保"
        })
        plan["annual_premium"] += ac_premium
        plan["total_coverage"] += ac_coverage

    plan["features"] = [
        "保障全面：寿险+重疾+医疗+意外",
        "重疾险提供终身保障，确诊即赔付",
        "医疗险保证续保20年，长期稳定",
        "定期寿险覆盖家庭经济责任期",
        "年保费已按年度保费上限（min(年度预算, 年收入×15%)）校验"
    ]

    return _finalize_plan(plan, budget, annual_income, 0.15, age, gender, products,
                          removal_order=["意外险", "医疗险"])


def design_premium_plan(age, gender, annual_income, annual_budget, coverage_needs, products):
    """全面版方案：高保额全面保障+储蓄"""
    budget = min(annual_budget, annual_income * 0.20)  # 上限 = min(年度预算, 年收入 20%)
    plan = {
        "plan_name": "全面版",
        "description": "高保额全方位保障，另含养老储蓄规划",
        "annual_premium": 0,
        "total_coverage": 0,
        "products": []
    }

    # 定期寿险 - 高保额
    tl_products = [p for p in products if p["type"] == "定期寿险"]
    if not tl_products:
        return _finalize_plan(plan, budget, annual_income, 0.20, age, gender, products)
    tl_product = tl_products[0]
    tl_coverage = min(coverage_needs.get("death", 2000000), 5000000)
    tl_premium = calculate_product_premium(tl_product, age, gender, tl_coverage, "20年")
    plan["products"].append({
        "type": "定期寿险",
        "product_name": tl_product["name"],
        "company": tl_product["company"],
        "coverage": tl_coverage,
        "annual_premium": tl_premium,
        "payment_term": "20年",
        "coverage_period": "至60/65周岁",
        "key_benefits": f"高保额{tl_coverage//10000}万，覆盖所有家庭责任"
    })
    plan["annual_premium"] += tl_premium
    plan["total_coverage"] += tl_coverage

    # 重疾险 - 多次赔付型
    crx_products = [p for p in products if p["type"] == "重疾险" and "多次" in (p.get("core_coverage") or "")]
    if not crx_products:
        crx_products = [p for p in products if p["type"] == "重疾险"]
    if crx_products:
        crx_product = crx_products[0]
        crx_coverage = min(coverage_needs.get("critical_illness", annual_income * 5), 500000)
        crx_premium = calculate_product_premium(crx_product, age, gender, crx_coverage, "20年")
        plan["products"].append({
            "type": "重疾险",
            "product_name": crx_product["name"],
            "company": crx_product["company"],
            "coverage": crx_coverage,
            "annual_premium": crx_premium,
            "payment_term": "20年",
            "coverage_period": "终身",
            "key_benefits": f"重疾多次赔付，终身保障，保额{crx_coverage//10000}万"
        })
        plan["annual_premium"] += crx_premium
        plan["total_coverage"] += crx_coverage

    # 医疗险 - 600万高保额
    mi_products = [p for p in products if p["type"] == "医疗险"]
    if mi_products:
        mi_product = next((p for p in mi_products if "600" in (p.get("core_coverage") or "")), mi_products[0])
        mi_coverage = 6000000
        mi_premium = calculate_product_premium(mi_product, age, gender, mi_coverage, "年交")
        plan["products"].append({
            "type": "医疗险",
            "product_name": mi_product["name"],
            "company": mi_product["company"],
            "coverage": mi_coverage,
            "annual_premium": mi_premium,
            "payment_term": "年交",
            "coverage_period": "1年可续保",
            "key_benefits": "600万高保额，含质子重离子、CAR-T治疗"
        })
        plan["annual_premium"] += mi_premium
        plan["total_coverage"] += mi_coverage

    # 意外险 - 100万
    ac_products = [p for p in products if p["type"] == "意外险"]
    if ac_products:
        ac_product = next((p for p in ac_products if "百万" in p["name"]), ac_products[0])
        ac_coverage = 1000000
        ac_premium = calculate_product_premium(ac_product, age, gender, ac_coverage, "年交")
        plan["products"].append({
            "type": "意外险",
            "product_name": ac_product["name"],
            "company": ac_product["company"],
            "coverage": ac_coverage,
            "annual_premium": ac_premium,
            "payment_term": "年交",
            "coverage_period": "1年",
            "key_benefits": "100万意外+猝死保障，意外医疗不限社保"
        })
        plan["annual_premium"] += ac_premium
        plan["total_coverage"] += ac_coverage

    # 储蓄险 - 养老规划（可选）
    if age <= 45:
        sa_products = [p for p in products if p["type"] == "储蓄险" and "养老" in (p.get("notes") or "")]
        if not sa_products:
            sa_products = [p for p in products if p["type"] == "储蓄险"]
        if sa_products and plan["annual_premium"] + 10000 <= budget:
            sa_product = sa_products[0]
            sa_coverage = 100000
            sa_premium = calculate_product_premium(sa_product, age, gender, sa_coverage, "10年")
            plan["products"].append({
                "type": "储蓄险",
                "product_name": sa_product["name"],
                "company": sa_product["company"],
                "coverage": sa_coverage,
                "annual_premium": sa_premium,
                "payment_term": "10年",
                "coverage_period": "至60/65周岁",
                "key_benefits": "强制储蓄，养老规划，兼具保障和收益"
            })
            plan["annual_premium"] += sa_premium

    plan["features"] = [
        "全方位高保额保障：寿险+重疾+医疗+意外",
        "重疾险保额高达年收入5倍",
        "医疗险600万保额，涵盖最新治疗手段",
        "定期寿险高保额，覆盖所有家庭财务责任",
        "可选储蓄险，为养老做准备",
        "年保费已按年度保费上限（min(年度预算, 年收入×20%)）校验"
    ]

    return _finalize_plan(plan, budget, annual_income, 0.20, age, gender, products,
                          removal_order=["意外险", "医疗险", "储蓄险"])


def _finalize_plan(plan, budget, annual_income, ratio, age, gender, products,
                   removal_order=None):
    """统一收尾：执行预算硬约束 + 附加 budget_planning 块。"""
    plan.setdefault("budget_adjustments", [])
    if removal_order:
        _enforce_budget(plan, budget, annual_income, age=age, gender=gender,
                        product_index=_product_index(products),
                        removal_order=removal_order)
    else:
        # 基础版同样执行保额下调（移除顺序：医疗险 → 意外险）
        _enforce_budget(plan, budget, annual_income, age=age, gender=gender,
                        product_index=_product_index(products),
                        removal_order=removal_order or ["医疗险", "意外险"])
    _attach_budget_planning(plan, budget, annual_income, ratio)
    return plan


def generate_all_plans(age, gender, annual_income, annual_budget, coverage_needs):
    """生成三套方案"""
    plans = {
        "基础版": design_plan("基础版", age, gender, annual_income, annual_budget, coverage_needs),
        "标准版": design_plan("标准版", age, gender, annual_income, annual_budget, coverage_needs),
        "全面版": design_plan("全面版", age, gender, annual_income, annual_budget, coverage_needs)
    }

    return plans


# 示例档案（仅在 stdin 未提供输入时作为演示数据打印，并明确标注来源）
EXAMPLE_PLAN_INPUT = {
    "age": 35,
    "gender": "男",
    "annual_income": 500000,
    "annual_budget": 500000,
    "coverage_needs": {
        "death": 2000000,
        "critical_illness": 1500000,
        "hospital": 4000000
    }
}


def _read_stdin_text():
    """读取 stdin 文本；TTY（无管道输入）返回空串。"""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return ""
        return sys.stdin.read() or ""
    except Exception:
        return ""


def main():
    raw = _read_stdin_text().strip()
    if not raw:
        # 未提供输入：明确标注示例数据，不静默把示例档案当作正式结果
        sys.stderr.write("⚠️ 未提供输入，以下为示例数据（示例档案，非真实客户数据）：\n")
        sys.stderr.write(json.dumps(EXAMPLE_PLAN_INPUT, ensure_ascii=False, indent=2) + "\n")
        params = EXAMPLE_PLAN_INPUT
    else:
        try:
            params = json.loads(raw)
        except Exception as e:
            print(json.dumps({"error": str(e)}, ensure_ascii=False))
            return 0
    try:
        plans = generate_all_plans(
            params.get("age", 35),
            params.get("gender", "男"),
            params.get("annual_income", 500000),
            params.get("annual_budget", 500000),
            params.get("coverage_needs", {})
        )
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 0
    print(json.dumps(plans, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
