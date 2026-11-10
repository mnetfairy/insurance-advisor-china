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

# ---------------------------------------------------------------------------
# 🆕 2026-11-08 整改 R5：医疗险续保条款按**真实结构化字段**判定
#   解析器写入的权威标记（references/products.json 的 coverage_period_parse_notes）
#   与保险期间字段（duration_value/duration_unit/is_lifetime）互不等价：
#   实测有 14 款「1年（保证续保20年）」产品的 duration_value=1（保险期间 1 年），
#   只看 duration_value 会把 20 年保证续保误判成 1 年 → 必须以 parse_notes 为准。
# ---------------------------------------------------------------------------
_RE_GUARANTEED_YEARS = re.compile(r"guaranteed_renewable_(\d+)\s*年")
_RE_LONG_TERM_MARK = re.compile(r"long_term_with_guaranteed_renewable")


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


def _parse_notes_list(product):
    """返回产品库解析标记列表（统一成 list[str]）。"""
    notes = product.get("coverage_period_parse_notes")
    if notes is None:
        return []
    if isinstance(notes, str):
        return [notes]
    if isinstance(notes, (list, tuple)):
        return [str(n) for n in notes]
    return []


def _renewal_duration_years(product):
    """返回该产品保证续保的年限（年）。无法确定时返回 None。

    判定口径（**只用结构化字段**，不做子串猜测）：
      1. `coverage_period_parse_notes` 是产品库解析器写入的**权威标记**：
         - 'guaranteed_renewable_20年' → 20
         - 'guaranteed_renewable_6年'  → 6
         - 'long_term_with_guaranteed_renewable' → None（长期，不按年限计）
         ⚠️ 该标记**优先于** duration_value：实测有 14 款「1年（保证续保20年）」的
         duration_value=1（保险期间 1 年），但保证续保期是 20 年 —— 只看
         duration_value 会把 20 年保证续保误判成 1 年。
      2. 次选 `coverage_period_duration_unit == 'year'` → 取 `coverage_period_duration_value`。
      3. `coverage_period_duration_unit == 'long_term'` → None（长期）。
      4. `coverage_period_is_lifetime is True` → None（终身）。
    """
    notes = _parse_notes_list(product)
    for note in notes:
        # ⚠️ SDI-4 整改 2026-11-10：**long_term 标记必须优先于数值标记与 duration_value**。
        # 旧实现只匹配 `guaranteed_renewable_N年` 数值标记，遇到
        # 'long_term_with_guaranteed_renewable' 会**穿透**到 duration_value 分支 →
        # 把「保险期间 1 年」当成「保证续保 1 年」返回，与 docstring 声明的
        # 「长期，不按年限计 → None」**相反** → 对外文案会错报「1年保证续保」。
        # 修法：先扫 long_term 标记 → 直接返回 None（长期，不按年限计）。
        if _RE_LONG_TERM_MARK.search(note):
            return None
        m = _RE_GUARANTEED_YEARS.search(note)
        if m:
            return int(m.group(1))

    if product.get("coverage_period_is_lifetime") is True:
        return None
    unit = (product.get("coverage_period_duration_unit") or "").strip().lower()
    if unit == "long_term":
        # 单位本身就是 long_term → 长期，不按年限计
        return None
    value = product.get("coverage_period_duration_value")
    if unit == "year" and isinstance(value, (int, float)):
        return int(value)
    return None


def _is_guaranteed_renewable(product):
    """产品是否明确标注「保证续保」。"""
    return product.get("coverage_period_guaranteed_renewable") is True


def _has_long_term_renewal(product):
    """产品是否带长期保证续保（long_term 单位、解析标记或终身）。"""
    for note in _parse_notes_list(product):
        if _RE_LONG_TERM_MARK.search(note):
            return True
    if product.get("coverage_period_is_lifetime") is True:
        return True
    unit = (product.get("coverage_period_duration_unit") or "").strip().lower()
    return unit == "long_term"


def select_medical_product(products, min_guaranteed_years=None, prefer=None):
    """按真实续保字段选医疗险。

    Args:
        products: 候选产品列表。
        min_guaranteed_years: 要求的最低保证续保年限（如 20）。None = 不要求。
        prefer: 可选的选品偏好函数（如按 core_coverage 含 '600' 选 600 万产品）。

    Returns:
        tuple[dict|None, dict|None]: (选中产品, 未满足要求时的限制说明)
            第二个元素为 None 表示选品成功满足要求。
    """
    candidates = [p for p in products if p.get("type") == "医疗险"]
    if not candidates:
        return None, {
            "reason": "产品库中没有在售医疗险，无法在方案中加入医疗保障。",
            "requirement": None,
        }

    # 第 1 优先：满足「保证续保 ≥ N 年」的（结构化字段判定，非子串匹配）
    if min_guaranteed_years:
        qualified = [
            p for p in candidates
            if _is_guaranteed_renewable(p)
            and (_renewal_duration_years(p) is not None
                 and _renewal_duration_years(p) >= min_guaranteed_years
                 or _has_long_term_renewal(p))
        ]
        if qualified:
            chosen = prefer(qualified) if prefer else qualified[0]
            return chosen, None

        # 无合格产品 → 如实报告限制，**不**替换为任意产品却宣称满足
        guaranteed_any = [p for p in candidates if _is_guaranteed_renewable(p)]
        if guaranteed_any:
            best_years = max(
                (_renewal_duration_years(p) or 0) for p in guaranteed_any
            )
            limitation = {
                "reason": (
                    f"产品库中无满足「保证续保{min_guaranteed_years}年」的在售医疗险；"
                    f"现有保证续保医疗险的最高保证续保年限为 {best_years} 年。"
                ),
                "requirement": f"保证续保{min_guaranteed_years}年",
                "fallback_product": None,
            }
        else:
            limitation = {
                "reason": (
                    f"产品库中无任何标明保证续保的在售医疗险，"
                    f"无法满足「保证续保{min_guaranteed_years}年」的要求。"
                ),
                "requirement": f"保证续保{min_guaranteed_years}年",
                "fallback_product": None,
            }
        # 兜底选品：优先选**确实带保证续保（年限不足）**的产品；
        # 若连保证续保的都没有，则选续保条件最清晰的一款，并如实标注。
        fallback_pool = guaranteed_any or candidates
        fallback = prefer(fallback_pool) if prefer else fallback_pool[0]
        limitation["fallback_product"] = fallback.get("name")
        return fallback, limitation

    # 无年限要求：优先带保证续保的
    guaranteed = [p for p in candidates if _is_guaranteed_renewable(p)]
    pool = guaranteed or candidates
    chosen = prefer(pool) if prefer else pool[0]
    return chosen, None


def derive_medical_coverage_period(product):
    """从产品真实字段派生医疗险的 `coverage_period` 展示文本。"""
    if not product:
        return "未明确"
    raw = product.get("coverage_period")
    if _is_guaranteed_renewable(product):
        years = _renewal_duration_years(product)
        if years is not None:
            return f"{years}年保证续保"
        if _has_long_term_renewal(product):
            return "长期保证续保"
        return "保证续保"
    if raw:
        return raw
    return "未明确"


def derive_medical_key_benefits(product, base_benefits, coverage_period=None):
    """从产品真实字段派生医疗险的 `key_benefits` 展示文本。

    续保描述**只陈述产品自身字段所载的事实**，不套用与实际条款不符的年限。
    """
    benefits = base_benefits
    if not product:
        return benefits
    if _is_guaranteed_renewable(product):
        years = _renewal_duration_years(product)
        if years is not None:
            return f"{benefits}，{years}年保证续保"
        if _has_long_term_renewal(product):
            return f"{benefits}，长期保证续保"
        return f"{benefits}，保证续保"
    # 无保证续保：不得使用「保证续保N年」措辞；如实表述为「续保条件以产品条款为准」
    return f"{benefits}，续保条件以产品条款为准"


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

# 核心保障险种：移除顺序在可选险种之后作为兜底
# （重疾险 → 定期寿险）。min_coverage 是「可售最小保额」，不是「必须卖这么多」，
# 因此降到下限仍超预算时允许移除。
_CORE_COVERAGE_TYPES = ("重疾险", "定期寿险")


def _product_index(products):
    """建立 (type, product_name) → 产品记录 的索引，供保费重算使用。"""
    return {(p.get("type"), p.get("name")): p for p in products}


# 保额单位合同：唯一受支持的单位 → 换算为「元」的系数。
# 「元」与「万元」是产品库当前唯一支持的两种单位（实测 2542 条记录：
# 万元 2267 / 缺失 275 / 无其他取值）。**不做静默兜底**。
_COVERAGE_UNIT_FACTORS = {
    "元": 1,
    "万元": 10000,
}


def _coverage_unit_factor(product):
    """保额单位换算系数（单一事实来源）：返回 (factor, status)。

    status:
      - "ok"               —— 单位明确且受支持（"元" / "万元"），factor 为换算系数
      - "unit_missing"     —— coverage_unit 缺失 / 空串 / 非字符串
      - "unit_unsupported" —— coverage_unit 是受支持之外的值（如 "亿元" / "USD"）

    ⚠️ SDI-4 整改 2026-11-09：**不做静默兜底**。
    旧实现在单位缺失时静默套「万元」系数（×10000），而旧 docstring 却把缺省单位
    写成「元」—— 文档与实现相反，单位缺失时可售上限会被**放大 10000 倍**，
    反而放行超出真实可售上限的保额。
    现在：单位缺失 → 不猜、不换算（factor=None, status="unit_missing"）；
    单位不受支持 → 显式标记（factor=None, status="unit_unsupported"），
    两者都**不静默套任何乘数**，交由调用方如实留痕 + 对外披露。

    ⚠️ 口径选择说明（重要，勿擅自改为缺省「元」）：
    若把缺省单位改成「元」，实测产品库 2267 条「万元」记录的换算结果会**缩小
    10000 倍** → 击穿可售上限夹逼保护（上限保护失效比「文档↔实现矛盾」更严重）。
    因此本轮口径 = 显式支持「元」/「万元」；缺失与不支持一律**不换算**。
    （实测「有保额上下限但缺单位」的记录数为 0、「元/万元」之外的单位为 0 条
      → 对现有数据零行为影响。）

    Returns:
        tuple[int | None, str]: (换算系数, 状态)。factor 为 None 时**不得**套任何乘数。
    """
    if not product:
        return None, "unit_missing"
    unit = product.get("coverage_unit")
    if unit is None or not isinstance(unit, str):
        return None, "unit_missing"
    unit = unit.strip()
    if not unit:
        return None, "unit_missing"
    if unit not in _COVERAGE_UNIT_FACTORS:
        return None, "unit_unsupported"
    return _COVERAGE_UNIT_FACTORS[unit], "ok"


def _coverage_floor(product, entry):
    """保额下调下限：产品 min_coverage 按**单位合同**换算为元。

    单位口径（与 _coverage_unit_factor 严格一致）：
      - `coverage_unit == "万元"` → min_coverage × 10000
      - `coverage_unit == "元"`    → min_coverage × 1
      - 单位缺失 / 空串 / 非字符串 → **不换算**（不猜单位、不套任何乘数）
      - 单位不受支持（如 "亿元"）  → **不换算**（不静默套乘数）

    当 min_coverage 缺失、或单位不可信（无法确定可售最小保额）时，
    沿用既有兜底语义：**原保额的 60%**（`current * 0.6`）。

    ⚠️ SDI-4 整改 2026-11-09：旧实现在单位缺失时静默按「万元」换算 min_coverage，
    与旧 docstring 把缺省单位写成「元」相反 → 下限被放大 10000 倍，
    预算下调时的保额下限形同虚设。现与 _coverage_unit_factor 共用同一合同，
    **单位不可信时不套任何乘数**。
    """
    current = entry.get("coverage") or 0
    floor = None
    if product:
        raw_min = product.get("min_coverage")
        if raw_min is not None:
            factor, _unit_status = _coverage_unit_factor(product)
            if factor is not None:
                try:
                    floor = float(raw_min) * factor
                except (TypeError, ValueError):
                    floor = None
    if not floor or floor <= 0:
        return current * 0.6
    return min(floor, current)


def _coverage_cap_status(product):
    """返回 (cap, status)：可售保额上限（元）与该上限的可信度状态。

    status 取值：
      - "ok"                   —— max_coverage 与单位均可信，cap 为换算后的元值
      - "no_product"           —— 产品记录缺失
      - "max_coverage_missing" —— 产品库未提供 max_coverage
      - "max_coverage_invalid" —— max_coverage 非数值或非正数
      - "unit_untrusted"       —— max_coverage 有值但 coverage_unit 缺失/为空/非字符串
      - "unit_unsupported"     —— max_coverage 有值但 coverage_unit 是受支持之外的值

    ⚠️ SDI-4 整改 2026-11-09：**单位口径由 _coverage_unit_factor 单一来源定义**。
    旧实现在单位缺失时静默套「万元」系数（×10000），而旧 docstring 却把缺省单位
    写成「元」—— 文档与实现相反；若某条记录的真实单位是「元」，
    按万元换算会把上限**放大 10000 倍**，反而放行超出真实可售上限的保额。
    现在：
      - 单位缺失 → **不猜单位、不做换算**，返回 (None, "unit_untrusted")；
      - 单位不受支持 → **不静默套乘数**，返回 (None, "unit_unsupported")；
      两者都不设上限（不虚构上限），由调用方写入留痕 + 对外披露。

    ⚠️ 判定顺序：max_coverage 的三类状态（缺失 / 非数值 / 非正数）保持**原样不变**，
    单位合同仅在 max_coverage 存在且为正数时生效。
    """
    if not product:
        return None, "no_product"
    raw = product.get("max_coverage")
    if raw is None:
        return None, "max_coverage_missing"
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None, "max_coverage_invalid"
    if value <= 0:
        return None, "max_coverage_invalid"
    factor, unit_status = _coverage_unit_factor(product)
    if unit_status == "unit_missing":
        # 单位缺失 → 单位不可信：不换算、不设上限（交给调用方披露）
        return None, "unit_untrusted"
    if unit_status == "unit_unsupported":
        # 单位是受支持之外的值 → 显式标记：不换算、不设上限
        return None, "unit_unsupported"
    if factor is None:
        return None, "unit_untrusted"
    return int(value * factor), "ok"


def _coverage_cap(product):
    """保额上限：产品 max_coverage（可售保额上限）按 coverage_unit 换算为元；不可信时返回 None。

    ⚠️ R4 整改 2026-11-08：产品库中 max_coverage 是**可售保额上限**，
    如「安心少儿意外险」max_coverage=50（万元）= 500,000 元，
    方案原写死 2,500,000 元 → 超上限 50 倍（对外虚报可售保额）。

    ⚠️ SDI-4 整改 2026-11-09：**单位口径（与实现严格一致，来源 = _coverage_unit_factor）**
      - `coverage_unit == "万元"` → ×10000 换算为元；
      - `coverage_unit == "元"`    → ×1，不换算；
      - `coverage_unit` 缺失/为空/非字符串 且 max_coverage 有值 → **单位不可信**：
        **不**按万元、也**不**按元静默换算 → 返回 None（不设上限），
        由调用方写入留痕并对外披露（见 _apply_coverage_cap / _build_coverage_disclaimers）。
        （实测产品库中 max_coverage 有值的记录 `coverage_unit` 全部为「万元」，
          「有值但缺单位」的记录数为 0；此分支为防御性口径。）
      - `coverage_unit` 为受支持之外的值（如 "亿元" / "USD"） → **不静默套乘数**：
        返回 None（不设上限），并由调用方以 `unit_unsupported` 状态留痕 + 披露。
      - max_coverage 缺失（None / 非数值 / 非正数）→ 返回 None，**不设上限**，
        调用方须如实标注「该产品未提供可售保额上限」，不得假装有上限。

    Returns:
        int | None: 可售保额上限（元）；上限未知或不可信时为 None。
    """
    cap, _status = _coverage_cap_status(product)
    return cap


def _apply_coverage_cap(plan, product, desired_coverage, entry_type=None, entry_name=None):
    """把期望保额夹到产品 max_coverage 上限；触顶时写入 budget_adjustments。

    ⚠️ F4 整改 2026-11-09：**上限未知（cap is None）时不再静默放行**。
    旧实现原样返回期望保额且**不留任何痕迹** → 最终方案呈现一个「看起来很具体」
    却未经可售上限核实的保额，对用户构成误导。
    现在写入 `coverage_cap_unknown` 留痕（可审计），
    并由 _finalize_plan 汇总为对外披露（plan["coverage_disclaimers"]）。

    Returns:
        tuple[int, bool]: (最终保额, 是否因上限而被下调)
    """
    cap, cap_status = _coverage_cap_status(product)
    desired = int(desired_coverage or 0)
    if cap is None:
        # 上限未知/不可信 → 不设上限（不虚构上限），但必须留痕并披露
        plan.setdefault("budget_adjustments", []).append({
            "type": "coverage_cap_unknown",
            "product": entry_name,
            "product_type": entry_type,
            "requested_coverage": desired,
            "cap_status": cap_status,
            "max_coverage": (product or {}).get("max_coverage"),
            "coverage_unit": (product or {}).get("coverage_unit"),
            "reason": "该产品在产品库中未提供可核实的可售保额上限"
                      "（max_coverage 缺失/非数值/非正数，或保额单位不可信/不受支持），"
                      "此保额未经可售上限核实，请以保险公司正式测算为准",
        })
        return desired, False
    if desired <= cap:
        return desired, False
    plan.setdefault("budget_adjustments", []).append({
        "type": "coverage_capped",
        "product": entry_name,
        "product_type": entry_type,
        "requested_coverage": desired,
        "capped_to": cap,
        "max_coverage": product.get("max_coverage"),
        "coverage_unit": product.get("coverage_unit"),
        "reason": "方案保额超过该产品在产品库的可售保额上限（max_coverage），已按上限下调",
    })
    return cap, True


def _build_coverage_disclaimers(plan):
    """汇总「可售保额上限未经核实」的险种，生成对外披露文案。

    ⚠️ F4 整改 2026-11-09：审计原文指出
    「_coverage_cap 返回 None 时，_apply_coverage_cap 原样返回期望保额且不留痕迹，
      finalization 也不加对应披露 → 缺失/畸形/非正的 max_coverage 会产出
      一个看似具体、但无可核实可售上限的保险建议」。

    本函数把 budget_adjustments 中的 `coverage_cap_unknown` 记录汇总为
    顶层 `coverage_disclaimers`（list[str]），**必须真实出现在最终 JSON 输出里**。

    仅当确实存在上限未知的险种时才写入该键（无未知上限时**不新增空数组**，
    以免给所有方案引入无意义的空字段）。

    Returns:
        list[str]: 披露文案列表；无上限未知险种时返回空列表。
    """
    unknown = [a for a in (plan.get("budget_adjustments") or [])
               if isinstance(a, dict) and a.get("type") == "coverage_cap_unknown"]
    if not unknown:
        return []

    # 只披露**最终方案里实际保留**的险种：
    #   若某产品因保费超预算从未加入方案（或被 _enforce_budget 移除），
    #   它不在 plan["products"] 里 → 不该出现在本方案的保额披露中。
    final_names = {p.get("product_name") for p in (plan.get("products") or [])}
    if not final_names:
        return []
    unknown = [a for a in unknown if a.get("product") in final_names]
    if not unknown:
        return []

    # 按险种去重（同一险种可能多次留痕），保持出现顺序
    seen = []
    details = []
    for adj in unknown:
        label = adj.get("product_type") or "险种"
        name = adj.get("product")
        key = (label, name)
        if key in seen:
            continue
        seen.append(key)
        detail = f"{label}" + (f"「{name}」" if name else "")
        details.append(detail)

    n = len(details)
    plural = "、".join(details)
    return [
        f"本方案中有 {n} 个险种（{plural}）的可售保额上限未在产品库中核实："
        "产品库未提供可售保额上限，或保额单位不可信/不受支持，无法确认其可售上限。"
        "上述险种的建议保额**未经可售上限核实**，请以保险公司正式测算结果为准。",
    ]


def _refresh_coverage_text(entry, from_coverage, to_coverage):
    """保额变化后同步 key_benefits 中内嵌的保额数字。"""
    kb = entry.get("key_benefits")
    if not isinstance(kb, str):
        return
    old_wan = from_coverage // 10000
    new_wan = to_coverage // 10000
    if old_wan and f"{old_wan}万" in kb:
        entry["key_benefits"] = kb.replace(f"{old_wan}万", f"{new_wan}万")


def _coverage_claim_text(coverage):
    """由实际保额派生出对外的保额表述（万元）。"""
    wan = coverage // 10000
    if wan >= 1:
        return f"{wan}万"
    # < 1 万：如实表述为具体金额（千元级），不得谎称「百万」
    qian = round(coverage / 1000)
    return f"{qian}千" if qian else "保额较低"


def _normalize_coverage_claim(text, coverage):
    """把文本里的保额量词表述替换为由**实际保额**派生的表述。

    ⚠️ R4 整改 2026-11-08：原实现只匹配「100万保额」「600万医疗」等
    「数字+万」紧跟关键词的形态，**漏掉了**「600万高保额」「医疗险600万保额」
    这类写法 → 保额被 max_coverage 夹到 400 万后，对外仍宣称 600 万。
    这里改为：凡文本中出现「数字+万」且位于保额语境的，一律替换为实际保额表述。
    """
    if not isinstance(text, str) or not text:
        return text

    claim = _coverage_claim_text(coverage)

    def _sub_num(m):
        # 形如「100万保额」：用实际保额量词替换整个「数字+万」，保留后缀
        return claim + m.group(2)

    # ① 「数字+万」后紧跟保额类关键词（保额/意外/医疗/重疾/身故/赔付/保障/高保额…）
    out = re.sub(r"(\d+(?:\.\d+)?)万(保额|高保额|意外|医疗|重疾|身故|赔付|保障|，)",
                 _sub_num, text)
    # ② 「数字+万」后紧跟逗号 + 常见后缀（，仅需 / ，含 / ，含质子）
    out = re.sub(r"(\d+(?:\.\d+)?)万(，(?:仅需|含|含质子))",
                 _sub_num, out)
    # ③ 「医疗险600万保额」这类「险种名+数字+万+保额」已在 ① 覆盖；
    #    残留的裸「数字+万」紧跟在「医疗险/意外险/重疾险/寿险」之后也替换。
    out = re.sub(r"((?:医疗险|意外险|重疾险|寿险))(\d+(?:\.\d+)?)万",
                 lambda m: m.group(1) + claim, out)
    # ④ 「百万医疗」——实际保额 <100 万时不得再称「百万」
    if "百万医疗" in out and coverage < 1000000:
        out = out.replace("百万医疗", f"{claim}医疗")
    # ⑤ 「百万」独立出现（无「医疗」后缀）时同样按实际保额校正
    if "百万" in out and coverage < 1000000:
        out = out.replace("百万", claim)
    return out


# ---------------------------------------------------------------------------
# R6 整改 2026-11-08：方案描述与实际构成一致性
# ---------------------------------------------------------------------------
# 险种类型 → 描述中使用的名称（顺序即描述中列举的优先级）
_TYPE_LABELS = (
    ("定期寿险", "定期寿险"),
    ("重疾险", "重疾保障"),
    ("医疗险", "医疗保障"),
    ("意外险", "意外保障"),
    ("储蓄险", "养老储蓄规划"),
)

# 险种类型 → 该险种被移除后不得出现在描述/卖点中的关键词
_TYPE_BANNED_WORDS = {
    "定期寿险": ("寿险",),
    "重疾险": ("重疾",),
    "医疗险": ("医疗",),
    "意外险": ("意外",),
    "储蓄险": ("养老", "储蓄"),
}


def _build_plan_description(plan_name, products):
    """按**实际剩余险种**生成方案描述。

    ⚠️ R6 整改 2026-11-08：原先 description 写死（如「保障全面，含重疾保障」
    「高保额全方位保障，另含养老储蓄规划」），在产品被移除后不再成立 → 属于
    对外虚报。本函数以 plan["products"] 为唯一事实来源动态生成。

    Args:
        plan_name: 方案名（基础版 / 标准版 / 全面版）
        products: 方案实际保留的产品列表

    Returns:
        描述文本；产品为空时明确说明方案不覆盖任何险种。
    """
    present = {p.get("type") for p in (products or [])}
    if not present:
        return f"{plan_name}：当前预算不足以配置任何险种，方案暂不覆盖具体保障责任"

    labels = [label for ptype, label in _TYPE_LABELS if ptype in present]
    scope = "、".join(labels)

    # 全面版卖点：仅当储蓄险真实保留时才提「养老储蓄规划」
    if plan_name == "全面版":
        if "储蓄险" in present:
            others = [l for ptype, l in _TYPE_LABELS
                      if ptype in present and ptype != "储蓄险"]
            other_scope = "、".join(others)
            return (f"高保额全方位保障（{other_scope}），另含养老储蓄规划")
        return f"高保额全方位保障（{scope}）"

    # 标准版卖点：仅当重疾险真实保留时才提「含重疾保障」
    if plan_name == "标准版":
        if "重疾险" in present:
            return f"保障全面，含重疾保障（{scope}），适合大多数家庭"
        return f"保障基础，含{scope}，适合大多数家庭"

    # 基础版
    return f"以最低成本建立基础保障，覆盖核心风险（{scope}）"


def _prune_plan_features(plan, features):
    """剔除 features 中与实际保留险种不符的条目。

    被移除险种对应的卖点（如「重疾险提供终身保障」「医疗险600万保额」
    「可选储蓄险，为养老做准备」）必须同步消失。
    """
    present = {p.get("type") for p in plan.get("products", [])}
    kept = []
    for feat in features or []:
        if not isinstance(feat, str):
            continue
        drop = False
        for ptype, words in _TYPE_BANNED_WORDS.items():
            if ptype in present:
                continue
            # 只在该条目明确提到被移除险种时剔除；
            # 「医疗险20年保证续保」这类提及具体险种的条目同样处理。
            if any(w in feat for w in words):
                drop = True
                break
        if not drop:
            kept.append(feat)
    return kept


def _enforce_budget(plan, budget, annual_income, age=None, gender=None,
                    product_index=None, removal_order=None):
    """把方案年保费压到年度保费上限以内。

    步骤：
      1. 若 annual_premium > budget，从最后加入的产品开始按比例下调 coverage
         （下限 = 产品 min_coverage，无则用原保额 60%），用同一
         calculate_product_premium 重算，直到 <= budget 或无可下调空间。
      2. 仍超预算：按 removal_order 依次移除险种
         （可选险种优先；核心险种兜底：重疾险 → 定期寿险）。
      3. 兜底：removal_order 走完仍超预算时，从后往前移除剩余险种，
         直到年保费 <= 上限或产品列表为空（此时年保费 = 0）。
      4. 每次调整写入 plan["budget_adjustments"]。
      5. 产品列表为空 → budget_planning["方案可行性"] 明确说明预算不足，
         绝不允许返回「超预算却不说原因」的方案。

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

    if budget is None:
        return plan
    if budget <= 0:
        # 年度保费上限为 0（或收入为 0 导致上限为 0）：无法配置任何险种，
        # 方案置为「不可行」：年保费 0、产品列表为空，并留下审计记录。
        for entry in list(plan.get("products", [])):
            adjustments.append({
                "type": "product_removed",
                "product": entry.get("product_name"),
                "product_type": entry.get("type"),
                "removed_coverage": entry.get("coverage"),
                "removed_premium": round(entry.get("annual_premium", 0), 2),
                "reason": "年度保费上限为 0，无法配置任何险种，方案置为不可行",
            })
        plan["products"] = []
        plan["annual_premium"] = 0
        plan["total_coverage"] = 0
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
        # ⚠️ R6 整改 2026-11-08：下调保额时必须同步扣减 total_coverage，
        #    否则会出现「实际保额 5 万、对外报告 630 万」的保额虚报。
        plan["total_coverage"] = plan.get("total_coverage", 0) - (old_coverage - best)
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

    # ---- 步骤 2：移除险种（可选险种优先，核心险种兜底）----
    # removal_order 中排在后面的为核心险种（重疾险 / 定期寿险）：
    # min_coverage 是产品「可售」的最小保额，不是「必须卖这么多」，
    # 因此降到下限仍超预算时，允许移除该产品，而不是硬撑出一个超预算方案。
    def _remove_entry(idx, reason, level):
        """移除一个险种并同步 total_coverage（沿用原有增量口径）。"""
        entry = plan["products"].pop(idx)
        premium = entry.get("annual_premium", 0)
        plan["annual_premium"] -= premium
        plan["total_coverage"] -= entry.get("coverage", 0)
        adjustments.append({
            "type": "product_removed",
            "product": entry.get("product_name"),
            "product_type": entry.get("type"),
            "removed_coverage": entry.get("coverage"),
            "removed_premium": round(premium, 2),
            "reason": reason,
            "coverage_level": level,
        })

    for product_type in removal_order:
        if plan["annual_premium"] <= budget:
            break
        for idx in range(len(plan.get("products", [])) - 1, -1, -1):
            entry = plan["products"][idx]
            if entry.get("type") != product_type:
                continue
            is_core = product_type in _CORE_COVERAGE_TYPES
            _remove_entry(
                idx,
                ("超出年度保费预算且保额已降至可售最小保额仍超上限，兜底移除该核心险种"
                 if is_core else
                 "超出年度保费预算且保额无可下调空间，移除该可选险种"),
                "core" if is_core else "optional",
            )
            break

    # ---- 步骤 3：兜底移除剩余险种（removal_order 未覆盖的类型）----
    # 目的只有一个：保证返回的方案年保费恒不超过年度保费上限。
    while plan["annual_premium"] > budget and plan.get("products"):
        entry = plan["products"][-1]
        _remove_entry(
            len(plan["products"]) - 1,
            "超出年度保费上限，兜底移除该险种以保证方案不超预算",
            "core" if entry.get("type") in _CORE_COVERAGE_TYPES else "optional",
        )

    plan["annual_premium"] = max(0.0, round(plan["annual_premium"], 2))
    plan["total_coverage"] = max(0, plan.get("total_coverage", 0))
    return plan


def _attach_budget_planning(plan, budget, annual_income, ratio, note=""):
    """为方案附加 budget_planning 块。"""
    premium = round(plan["annual_premium"], 2)
    cap = round(budget, 2)
    in_budget = premium <= cap + 0.01
    plan["budget_planning"] = {
        "年度保费上限": cap,
        "方案年保费": premium,
        "占年收入比": round(premium / annual_income * 100, 1) if annual_income else None,
        "是否在预算内": in_budget,
        "说明": "保费上限 = min(年度预算, 年收入×比例)；超出部分已自动下调保额、"
                "移除可选险种，必要时兜底移除核心险种（重疾险→定期寿险）",
        "上限口径": f"min(年度预算 {budget}, 年收入 × {int(ratio * 100)}%)",
    }
    if not plan.get("products"):
        # 产品列表为空 → 方案不可行，必须说明原因，不允许静默返回一个空壳方案
        removed_core = [a for a in plan.get("budget_adjustments", [])
                        if a.get("type") == "product_removed"
                        and a.get("product_type") in _CORE_COVERAGE_TYPES]
        if removed_core:
            detail = ("核心险种（重疾险/定期寿险）已降至可售最小保额仍超上限，"
                      "兜底移除后方案为空")
        else:
            detail = "年度保费上限过低，任何一个险种（含最低保额）都无法在上限内配置"
        plan["budget_planning"]["方案可行性"] = (
            f"不可行：{detail}。当前方案年保费已置为 0，"
            "请提高年度保费预算，或仅在预算内配置基础医疗/意外保障后再行评估。"
        )
        plan["budget_planning"]["方案状态"] = "不可行"
    else:
        removed_core = [a for a in plan.get("budget_adjustments", [])
                        if a.get("type") == "product_removed"
                        and a.get("product_type") in _CORE_COVERAGE_TYPES]
        if removed_core:
            plan["budget_planning"]["方案可行性"] = (
                "可行（已按预算上限调整）：因年度保费上限偏低，"
                f"已移除核心险种 {'、'.join(a.get('product_type') for a in removed_core)}，"
                "剩余保障不足以覆盖该险种责任，请知悉保障缺口。"
            )
        else:
            plan["budget_planning"]["方案可行性"] = "可行：方案年保费在年度保费上限内"
        plan["budget_planning"]["方案状态"] = "可行"
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
    # ⚠️ R4 整改 2026-11-08：保额不得超产品可售上限（max_coverage）
    tl_coverage, _capped = _apply_coverage_cap(
        plan, tl_product, tl_coverage, "定期寿险", tl_product.get("name"))
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
        # ⚠️ R4 整改 2026-11-08：意外险保额夹到产品 max_coverage
        #    （如「安心少儿意外险」max_coverage=50 万 → 上限 500,000 元）
        ac_coverage, _capped = _apply_coverage_cap(
            plan, ac_product, ac_coverage, "意外险", ac_product.get("name"))
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
    # ⚠️ R5 整改 2026-11-08：选品改用**结构化续保字段**（原先对 notes 做子串匹配），
    #    展示字段由真实字段派生（原先无条件写死 "coverage_period": "1年"）。
    mi_product, mi_limitation = select_medical_product(products, min_guaranteed_years=None)
    if mi_product:
        mi_coverage = 2000000
        mi_coverage, _capped = _apply_coverage_cap(
            plan, mi_product, mi_coverage, "医疗险", mi_product.get("name"))
        mi_premium = calculate_product_premium(mi_product, age, gender, mi_coverage, "年交")
        if plan["annual_premium"] + mi_premium <= budget:
            mi_coverage_period = derive_medical_coverage_period(mi_product)
            plan["products"].append({
                "type": "医疗险",
                "product_name": mi_product["name"],
                "company": mi_product["company"],
                "coverage": mi_coverage,
                "annual_premium": mi_premium,
                "payment_term": "年交",
                "coverage_period": mi_coverage_period,
                "key_benefits": derive_medical_key_benefits(
                    mi_product, "百万医疗，不限社保，进口药/靶向药均可报销", mi_coverage_period)
            })
            plan["annual_premium"] += mi_premium
            plan["total_coverage"] += mi_coverage
            if mi_limitation:
                plan.setdefault("limitations", []).append({
                    "type": "coverage_limit",
                    "product_type": "医疗险",
                    "product": mi_product["name"],
                    "requirement": mi_limitation["requirement"],
                    "reason": mi_limitation["reason"],
                    "actual_coverage_period": mi_coverage_period,
                })
        else:
            plan.setdefault("budget_adjustments", []).append({
                "type": "product_skipped",
                "product": mi_product["name"],
                "product_type": "医疗险",
                "reason": "加入医疗险后累计保费将超出年度保费上限，未加入",
            })

    return _finalize_plan(plan, budget, annual_income, 0.10, age, gender, products,
                          removal_order=["医疗险", "意外险", "定期寿险"])


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
    # ⚠️ R4 整改 2026-11-08：保额不得超产品可售上限（max_coverage）
    tl_coverage, _capped = _apply_coverage_cap(
        plan, tl_product, tl_coverage, "定期寿险", tl_product.get("name"))
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
        # ⚠️ R4 整改 2026-11-08：保额不得超产品可售上限（max_coverage）
        crx_coverage, _capped = _apply_coverage_cap(
            plan, crx_product, crx_coverage, "重疾险", crx_product.get("name"))
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

    # 医疗险 - 按**真实续保字段**选保证续保20年的（R5 整改 2026-11-08）
    mi_product, mi_limitation = select_medical_product(products, min_guaranteed_years=20)
    if mi_product:
        mi_coverage = 4000000
        mi_coverage, _capped = _apply_coverage_cap(
            plan, mi_product, mi_coverage, "医疗险", mi_product.get("name"))
        mi_premium = calculate_product_premium(mi_product, age, gender, mi_coverage, "年交")
        mi_coverage_period = derive_medical_coverage_period(mi_product)
        plan["products"].append({
            "type": "医疗险",
            "product_name": mi_product["name"],
            "company": mi_product["company"],
            "coverage": mi_coverage,
            "annual_premium": mi_premium,
            "payment_term": "年交",
            "coverage_period": mi_coverage_period,
            "key_benefits": derive_medical_key_benefits(
                mi_product, "长期医疗保障", mi_coverage_period)
        })
        plan["annual_premium"] += mi_premium
        plan["total_coverage"] += mi_coverage
        if mi_limitation:
            # 无「保证续保20年」的合格产品 → 如实报告限制，不谎称已满足
            plan.setdefault("limitations", []).append({
                "type": "coverage_limit",
                "product_type": "医疗险",
                "product": mi_product["name"],
                "requirement": mi_limitation["requirement"],
                "reason": mi_limitation["reason"],
                "actual_coverage_period": mi_coverage_period,
            })

    # 意外险
    ac_products = [p for p in products if p["type"] == "意外险"]
    if ac_products:
        ac_product = next((p for p in ac_products if "百万" in p["name"]), ac_products[0])
        ac_coverage = min(annual_income * 5, 3000000)
        # ⚠️ R4 整改 2026-11-08：意外险保额夹到产品 max_coverage
        ac_coverage, _capped = _apply_coverage_cap(
            plan, ac_product, ac_coverage, "意外险", ac_product.get("name"))
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

    # features 中的医疗险描述由**真实选中产品**派生（R5 整改 2026-11-08）
    mi_entry = next((e for e in plan["products"] if e["type"] == "医疗险"), None)
    if mi_entry:
        mi_feature = f"医疗险{mi_entry['coverage_period']}，长期稳定"
    else:
        mi_feature = "本方案未包含医疗险"
    plan["features"] = [
        "保障全面：寿险+重疾+医疗+意外",
        "重疾险提供终身保障，确诊即赔付",
        mi_feature,
        "定期寿险覆盖家庭经济责任期",
        "年保费已按年度保费上限（min(年度预算, 年收入×15%））校验"
    ]

    return _finalize_plan(plan, budget, annual_income, 0.15, age, gender, products,
                          removal_order=["意外险", "医疗险", "重疾险", "定期寿险"])


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
    # ⚠️ R4 整改 2026-11-08：保额不得超产品可售上限（max_coverage）
    tl_coverage, _capped = _apply_coverage_cap(
        plan, tl_product, tl_coverage, "定期寿险", tl_product.get("name"))
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
        # ⚠️ R4 整改 2026-11-08：保额不得超产品可售上限（max_coverage）
        crx_coverage, _capped = _apply_coverage_cap(
            plan, crx_product, crx_coverage, "重疾险", crx_product.get("name"))
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
    # ⚠️ R5 整改 2026-11-08：选品规则（600 万偏好）保持原样，
    #    仅把展示字段由**真实续保字段**派生（原先无条件写死 "1年可续保"）。
    def _prefer_600w(pool):
        return next((p for p in pool if "600" in (p.get("core_coverage") or "")), pool[0])

    mi_product, mi_limitation = select_medical_product(
        products, min_guaranteed_years=None, prefer=_prefer_600w)
    if mi_product:
        mi_coverage = 6000000
        mi_coverage, _capped = _apply_coverage_cap(
            plan, mi_product, mi_coverage, "医疗险", mi_product.get("name"))
        mi_premium = calculate_product_premium(mi_product, age, gender, mi_coverage, "年交")
        mi_coverage_period = derive_medical_coverage_period(mi_product)
        plan["products"].append({
            "type": "医疗险",
            "product_name": mi_product["name"],
            "company": mi_product["company"],
            "coverage": mi_coverage,
            "annual_premium": mi_premium,
            "payment_term": "年交",
            "coverage_period": mi_coverage_period,
            "key_benefits": derive_medical_key_benefits(
                mi_product, "600万高保额，含质子重离子、CAR-T治疗", mi_coverage_period)
        })
        plan["annual_premium"] += mi_premium
        plan["total_coverage"] += mi_coverage
        if mi_limitation:
            plan.setdefault("limitations", []).append({
                "type": "coverage_limit",
                "product_type": "医疗险",
                "product": mi_product["name"],
                "requirement": mi_limitation["requirement"],
                "reason": mi_limitation["reason"],
                "actual_coverage_period": mi_coverage_period,
            })

    # 意外险 - 100万
    ac_products = [p for p in products if p["type"] == "意外险"]
    if ac_products:
        ac_product = next((p for p in ac_products if "百万" in p["name"]), ac_products[0])
        ac_coverage = 1000000
        # ⚠️ R4 整改 2026-11-08：意外险保额夹到产品 max_coverage
        ac_coverage, _capped = _apply_coverage_cap(
            plan, ac_product, ac_coverage, "意外险", ac_product.get("name"))
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
            # ⚠️ R4 整改 2026-11-08：保额不得超产品可售上限（max_coverage）
            sa_coverage, _capped = _apply_coverage_cap(
                plan, sa_product, sa_coverage, "储蓄险", sa_product.get("name"))
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

    # features 中的医疗险描述由**真实选中产品与实际保额**派生
    # （R4 整改 2026-11-08：原写死「医疗险600万保额」，保额被夹紧后即为虚报）
    mi_entry = next((e for e in plan["products"] if e["type"] == "医疗险"), None)
    if mi_entry:
        mi_feature = (f"医疗险{mi_entry['coverage'] // 10000}万保额，"
                      f"{mi_entry['coverage_period']}，涵盖最新治疗手段")
    else:
        mi_feature = "本方案未包含医疗险"
    plan["features"] = [
        "全方位高保额保障：寿险+重疾+医疗+意外",
        "重疾险保额高达年收入5倍",
        mi_feature,
        "定期寿险高保额，覆盖所有家庭财务责任",
        "可选储蓄险，为养老做准备",
        "年保费已按年度保费上限（min(年度预算, 年收入×20%））校验"
    ]

    return _finalize_plan(plan, budget, annual_income, 0.20, age, gender, products,
                          removal_order=["意外险", "医疗险", "储蓄险", "重疾险", "定期寿险"])


def _finalize_plan(plan, budget, annual_income, ratio, age, gender, products,
                   removal_order=None):
    """统一收尾：执行预算硬约束 + 附加 budget_planning 块。"""
    plan.setdefault("budget_adjustments", [])
    # 移除顺序：可选险种优先，核心险种兜底（重疾险 → 定期寿险）
    _enforce_budget(plan, budget, annual_income, age=age, gender=gender,
                    product_index=_product_index(products),
                    removal_order=removal_order or ["医疗险", "意外险", "定期寿险"])
    _attach_budget_planning(plan, budget, annual_income, ratio)
    # 🆕 2026-10-30 SDI-4：出口处最终校验 —— 单一硬上限 min(年度预算, 年收入×比例)。
    # 审计要求「validate the final total before returning the plan」。
    # _enforce_budget 已保证，但这里再兜一层：任何未来改动若引入放宽乘数
    # （如历史上的 budget * 1.2），也会在这里被拦住。
    if budget and plan["annual_premium"] > budget + 0.01:
        raise AssertionError(
            f"方案年保费 {plan['annual_premium']} 超过年度保费上限 {budget}（{plan.get('plan_name')}）"
        )
    # ⚠️ R6 整改 2026-11-08：**出口兜底重算** total_coverage。
    #    以 plan["products"] 为唯一事实来源 —— 任何新增的保额调整路径
    #    （下调保额 / 移除险种 / 未来新增逻辑）若漏了增量同步，
    #    都会在这里被重算纠正，杜绝保额虚报。
    plan["total_coverage"] = sum(p.get("coverage", 0) or 0
                                 for p in plan.get("products", []))
    # ⚠️ R6 整改 2026-11-08：描述与卖点必须与**实际保留险种**一致。
    #    _enforce_budget 可能已移除险种 → 此时重写 description / features，
    #    确保被移除险种（如重疾、养老储蓄）不再出现在对外文案中。
    plan["description"] = _build_plan_description(
        plan.get("plan_name", ""), plan.get("products", []))
    if plan.get("features"):
        plan["features"] = _prune_plan_features(plan, plan["features"])
    # ⚠️ R6 整改 2026-11-08：key_benefits 中的保额表述必须与实际保额一致。
    #    _refresh_coverage_text 只在**下调保额**时被调用 → 设计期写死的
    #    「100万保额」「百万医疗」等硬编码表述可能与实际保额不符，
    #    故在出口处对每个产品统一校正（幂等）。
    for _entry in plan.get("products", []):
        _cov = _entry.get("coverage") or 0
        _entry["key_benefits"] = _normalize_coverage_claim(
            _entry.get("key_benefits"), _cov)
    # ⚠️ F4 整改 2026-11-09：把「可售保额上限未核实」的险种汇总为**对外披露**。
    #    必须写在**出口处**（与 total_coverage 重算同一位置），
    #    否则上限未知的保额会以一种「看起来很具体」但未经核实的形式呈现给用户。
    #    无上限未知的险种时**不新增该键**（避免给所有方案引入空字段）。
    _coverage_disclaimers = _build_coverage_disclaimers(plan)
    if _coverage_disclaimers:
        plan["coverage_disclaimers"] = _coverage_disclaimers
    else:
        plan.pop("coverage_disclaimers", None)
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
