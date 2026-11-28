#!/usr/bin/env python3
"""
保费计算工具
输入：年龄、性别、保额、保障期限（coverage_year）、产品类型
输出：各产品年缴保费，支持不同缴费期对比

🆕 2026-11-27 保障期限（coverage_year）**真实接线**（SDI-4 残余 AE-3）
   ── 官方 finding 原文（ai v2.4.48 · Excessive Agency · MEDIUM）：
     「The documented coverage-duration input is accepted but has no effect on
       premium calculations or product selection.」
   ── 整改前：`calculate_premium(..., coverage_year=None)` 与
     `calculate_all_premiums(..., coverage_year=None)` 都**声明了不用**
     （参数被吞）→ 不同保障期限给出**完全相同**的报价，且把**不满足**客户
     要求的保障期限的产品也一并返回。
   ── 整改后（口径 · 与 SKILL 侧文档一致）：
     ① **入参校验**：coverage_year 必须是 **None** 或**正整数**（单位：年）；
        非法值（0 / 负数 / 非整数 / 布尔）→ **显式报错**（`CoverageYearError`）
        → **不再**静默忽略（官方 remediation：reject unsupported duration
        queries explicitly rather than silently ignoring them）。
     ② **产品筛选**（用产品库**已验证**的 `coverage_period_*` 字段 ·
        语义 = 保障期限 ≥ 客户要求的年限）：
        · `coverage_period_is_lifetime is True` → 满足任意年限；
        · `coverage_period_duration_unit == "year"` 且
          `coverage_period_duration_value >= coverage_year` → 满足；
        · `coverage_period_duration_unit == "to_age"`（如「至70周岁」）→
          覆盖年数 = `duration_value - age` → 同上；
        · 期限**无法验证**（`coverage_period_parse_quality` ∉
          {'parsed','parsed_long'} / 字段缺失 / 单位未知）→ **不得**声称满足
          → **排除**，排除数量在 `_meta.coverage_year_filtered_out` **披露**。
     ③ **保费口径（诚实处理）**：产品库**没有**按保障期限分档的费率表
        ⇒ **不**自造「期限加权系数」假装是保险公司定价；**期限筛选后**，
        每款产品的保费仍按**它自己**的费率数据 + 启发式系数**估算**
        （既有公式**不改**）⇒ 不同 coverage_year → 不同产品集 → 不同报价；
        该限制与「保费为非绑定启发式估算」一并写入 `_meta.disclaimers`
        **显式披露**。
     ④ **显式拒绝**：给定 coverage_year 后**筛不出任何产品** → **显式报错**
        （不得返回空列表假装成功）。
   ⚠ **本模块不做**「按保障期限加权的定价」（产品库无分档费率）——
     不得宣称「同一产品、不同保障期限 → 保费不同」。

🆕 2026-10-27 停售产品过滤（I3）
   ── references/products.json 字段取值分布探查结论（2536 款，2026-10-27 实测）──
   is_active          : True 603 / False 1933（无缺失）
   validity_status    : '已停售' 1897 / 'DISCONTINUED' 80 / '在售新品' 222
                        / '在售老品' 176 / '在售常规' 116 / 'MODIFIED' 17
                        / 'VALID' 5 / 'SKIPPED' 4 / '信息缺失' 3 / 字段缺失 16
   delisting_time     : '已停售' 1880 / '仍在售' 454 / 日期串(YYYY 或 YYYY-MM) 57
                        / '待核实' 37 / 缺失或 null 108
   data_quality       : 'garbage' 37 / 其余无此字段
   is_duplicate       : True 56 / False 68 / 字段缺失 2412

   判定口径（基于上述真实分布，不臆造字段语义）：
     已停售/已下架 = is_active is False
                     或 validity_status ∈ {'已停售', 'DISCONTINUED'}
                     或 delisting_time == '已停售'
                     或 delisting_time 为日期串（YYYY / YYYY-MM / YYYY-MM-DD）
   三条信号并集 → 排除 2017 款；剩余 519 款再剔除 data_quality=='garbage' 37 款
   与 is_duplicate==True 1 款 → 481 款进入默认产品池。
   说明：'SKIPPED' / 'MODIFIED' / '信息缺失' 未被视为停售（它们表示状态未知或条款调整），
        但 is_active / delisting_time 的日期串仍会命中停售判定。

   行为：默认（include_discontinued=False）已停售/已下架产品不进入推荐与对比列表；
        它们仍计入"全部产品"总数口径，并在 _meta.disclaimers 中说明排除数量。
        在售产品的保费计算公式未做任何改动。

🆕 2026-11-28 缴费期（payment_term）**真实生效**（SDI-4 残余 AG-4）
   ── 官方 finding 原文（china v2.4.47 · Excessive Agency · MEDIUM）：
     「A requested payment term is silently ignored when unavailable, despite
       the comment promising to return only that term.」
   ── 整改前的**两个**根因（都已被主侧实测复现）：
     ① **契约**：请求了 payment_term 但产品不支持 → `else` 分支**静默返回全部
        缴费期**（官方点名 L593–620）→ 下游把「成功返回」当成「满足了客户要求」。
     ② **字段根因**：`available_terms = product.get("payment_terms", ["年交"])`
        —— **`payment_terms` 这个 key 在产品库里根本不存在**（2592 款命中 0 款）；
        真实字段是 **`payment_choices`**（list · 2111 款命中）
        ⇒ `available_terms` **恒等于 ["年交"]** ⇒ 任何请求的缴费期都「不可用」
        ⇒ **每一款产品都落进 all-terms fallback**。
        同源 bug：`compare_payment_terms` 读的是同一个不存在的字段 → 恒空 → 空转。
   ── 整改后（口径）：
     ① **入参校验**：payment_term 必须是 **None** 或**非空字符串**；
        非法值 → **显式报错**（`PaymentTermError`）→ **不得**静默忽略。
     ② **真实字段**：`payment_choices` 为**权威**缴费期来源；
        `payment_choices` 缺失时**兼容**既有 `payment_terms` 字段；
        两者都缺失 → 沿用既有默认 `["年交"]`（**零漂移**；
        **不得**把「缺失」解释成「支持所有缴费期」）。
     ③ **筛选**（payment_term 已指定时）：
        支持 ⇔ `payment_term ∈ 可用缴费期`；
        · 支持 → **只**返回该缴费期的**单期**结果（`annual_premium` +
          `payment_term`）→ **不得**再走 all-terms 分支；
        · 不支持 → **排除该产品**，排除数量在 `_meta.payment_term_filtered_out`
          **披露**；
        · **无法验证**（缴费期字段缺失/为空）→ 按「不支持」排除
          （**无法验证 ≠ 满足**，与 AE-3 轮 `coverage_year` 同口径）。
     ④ **区分两种「拿不到价」**：
        · 不支持该缴费期 → **排除该产品**（不进结果）；
        · 支持该缴费期但**缺费率** → **保留该产品**，沿用既有 AF-5 口径
          （`premium_unavailable=True` + `premium_unavailable_reason`，
          **不输出任何数字**、**不编造**兜底价）。
     ⑤ **显式拒绝**：给定 payment_term 后**筛不出任何产品** → **显式报错**
        （`PaymentTermError`；**不得**返回空列表假装成功、
        **不得**回退到全缴费期）。
     ⑥ **零漂移**：`payment_term=None` → 行为与整改前**完全一致**
        （返回全部可用缴费期 · 不筛选 · 不报错）；
        启发式缴费期系数（趸交 0.85 / 3年 0.95 / 5年 1.0 / 10年 1.05 /
        20年 1.15 / 30年 1.25）与「医疗险 / 意外险一律按年交算」**未改动**；
        `premium_is_estimate` / `pricing_basis` / `premium_unavailable`
        字段**未删改**；既有 `CoverageYearError` 路径**未受影响**
        （`coverage_year` 与 `payment_term` 两条筛选**可叠加**）。
"""

import json
import os
import re
import sys

# 已停售判定：delisting_time 为日期串（2021-12 / 2025-02-14 / 2021 等）
_RE_DELIST_DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")

# 视为"已停售/已下架"的 validity_status 取值（实测分布见文件头注释）
_DISCONTINUED_VALIDITY = ("已停售", "DISCONTINUED")

# ══════════════════════════════════════════════════════════════════════
# 保障期限（coverage_year）· **已验证**期限信息的判定口径
#
# ⚠ 官方 SDI-4 残余 AE-3（2026-11-27 公开复扫 · ai v2.4.48）：
#   「The documented coverage-duration input is accepted but has no effect on
#    premium calculations or product selection.」
#   remediation 原文：
#   「Validate coverage_year against a documented schema, filter products using
#    verified coverage-duration information, and calculate premiums using
#    authoritative rates for the selected duration. Until duration-aware pricing
#    is implemented, reject unsupported duration queries explicitly rather than
#    silently ignoring them.」
#
# ⇒ 产品库里**没有**按保障期限分档的费率表 → **不得**自造「期限加权系数」
#   假装是保险公司定价 → 正确做法：**按已验证期限筛选产品**，每款产品的保费
#   仍按**它自己**的费率数据 + 启发式系数**估算**（既有公式**不改**）
#   → 不同 coverage_year → 不同产品集 → 不同报价。
#
# ⚠⚠ 官方 SDI-4 残余 AF-5（2026-11-28 公开复扫 · ai AF-S3 / china AF-S3'）
#   finding 原文：
#     「Documentation promises authoritative product-specific premiums, but
#       calculations use generic rates and heuristic multipliers.」
#   ⇒ 上述官方原文描述的是**目标态**；**当前实现不满足**（产品库无分档费率表）
#     → 实际输出为**非绑定启发式估算**，已在 `_meta.disclaimers` **显式披露**。
# ══════════════════════════════════════════════════════════════════════

# **已验证**的期限解析质量取值（其余一律视为「期限无法验证」→ 不得声称满足）
_COVERAGE_PERIOD_VERIFIED_QUALITIES = ("parsed", "parsed_long")
# 可换算成「年」的期限单位
_COVERAGE_PERIOD_UNIT_YEAR = "year"
_COVERAGE_PERIOD_UNIT_TO_AGE = "to_age"


class CoverageYearError(ValueError):
    """保障期限入参非法 / 按期限筛不出任何产品（**显式拒绝** · 不得静默忽略）。

    ⚠ 官方 SDI-4 残余 AE-3 remediation 原文：
      「… reject unsupported duration queries explicitly rather than silently
        ignoring them.」
    ⇒ 继承 `ValueError` → 既有 `except ValueError` 的调用方仍能捕获。
    """


def _validate_coverage_year(coverage_year):
    """coverage_year 入参校验 → 规范化后的值（None 或正整数）

    口径：**None**（不按保障期限筛选）或**正整数**（单位：年）。
    ⚠ 非法值（0 / 负数 / 非整数 / 布尔）→ **显式报错**（不静默忽略）。
    """
    if coverage_year is None:
        return None
    if isinstance(coverage_year, bool) or not isinstance(coverage_year, int):
        raise CoverageYearError(
            "coverage_year 必须是 None 或正整数（单位：年），实际收到：%r"
            % (coverage_year,))
    if coverage_year <= 0:
        raise CoverageYearError(
            "coverage_year 必须是正整数（单位：年），实际收到：%r" % (coverage_year,))
    return coverage_year


# ══════════════════════════════════════════════════════════════════════
# 缴费期（payment_term）· **真实字段**与**显式拒绝**口径
#
# ⚠ 官方 SDI-4 残余 AG-4（2026-11-28 公开复扫 · ai AG-S4 / china AG-S4'）：
#   「A requested payment term is silently ignored when unavailable, despite the
#    comment promising to return only that term.」
#   remediation 原文：
#     「Validate payment_term and, when it is specified, return only products
#       supporting that term. Explicitly report products excluded for an
#       unsupported term, distinguish unavailable rate data from unsupported
#       payment schedules, and return an error if no products can satisfy the
#       request.」
#
# ⇒ ① `payment_terms` **不是**产品库的字段（实测 2592 款命中 0 款）→ 真实字段是
#     **`payment_choices`**；② 请求的缴费期不支持时**不得**静默回退到全部缴费期。
# ══════════════════════════════════════════════════════════════════════

# 产品库中**不存在**的字段名（保留注释以说明历史根因，不再用于取值）
_LEGACY_PAYMENT_TERMS_FIELD = "payment_terms"
# 产品库中**真实存在**的缴费期字段
_PAYMENT_CHOICES_FIELD = "payment_choices"
# 缴费期字段全部缺失时的**既有默认**（零漂移 · 不解释成「支持所有缴费期」）
_DEFAULT_PAYMENT_TERMS = ("年交",)


class PaymentTermError(ValueError):
    """缴费期入参非法 / 按缴费期筛不出任何产品（**显式拒绝** · 不得静默忽略）。

    ⚠ 官方 SDI-4 残余 AG-4 remediation 原文：
      「… return an error if no products can satisfy the request.」
    ⇒ 继承 `ValueError` → 既有 `except ValueError` 的调用方仍能捕获。
    """


def _validate_payment_term(payment_term):
    """payment_term 入参校验 → 规范化后的值（None 或非空字符串）

    口径：**None**（不按缴费期筛选）或**非空字符串**（如「10年」/「趸交」）。
    ⚠ 非法值（空串 / 空白串 / 非字符串）→ **显式报错**（不静默忽略）。
    """
    if payment_term is None:
        return None
    if not isinstance(payment_term, str) or not payment_term.strip():
        raise PaymentTermError(
            "payment_term 必须是 None 或非空字符串（缴费期，如「10年」/「趸交」），"
            "实际收到：%r" % (payment_term,))
    return payment_term.strip()


def _normalize_payment_terms(raw):
    """缴费期取值列表 → 归一化列表（非空字符串 · 去空白 · 去重 · 保序）

    ⚠ **不得**把 `payment_choices` 的取值改写成「年交」等其它口径
      （真实语料取值：趸交 / 1年 / 3年 / 5年 / 10年 / 15年 / 20年 / 30年）。
    """
    if not isinstance(raw, (list, tuple)):
        return []
    out = []
    for item in raw:
        if not isinstance(item, str):
            continue
        term = item.strip()
        if term and term not in out:
            out.append(term)
    return out


def _available_payment_terms(product):
    """产品**可用**的缴费期 → list[str]

    口径（**单一事实源** · 优先级从高到低）：
      ① `payment_choices`（产品库**真实字段**）→ 归一化后即结果；
         字段存在但为空 / 格式不对 → **[]**（= 缴费期**无法验证**）。
      ② `payment_choices` 缺失 → 兼容既有 `payment_terms` 字段（历史记录）。
      ③ 两者都缺失 → 既有默认 `["年交"]`（**零漂移**；
         **不得**解释成「支持所有缴费期」）。
    """
    if not isinstance(product, dict):
        return []
    if _PAYMENT_CHOICES_FIELD in product:
        return _normalize_payment_terms(product.get(_PAYMENT_CHOICES_FIELD))
    legacy = _normalize_payment_terms(product.get(_LEGACY_PAYMENT_TERMS_FIELD))
    if legacy:
        return legacy
    return list(_DEFAULT_PAYMENT_TERMS)


def _product_supports_payment_term(product, payment_term):
    """该产品是否**支持**客户要求的缴费期 → bool

    ⚠ 缴费期**无法验证**（字段缺失且无默认 / 字段为空）→ **不得**声称满足
      → **False**（与 AE-3 轮 `coverage_year` 同口径：无法验证 ≠ 满足）。
    """
    if payment_term is None:
        return True
    terms = _available_payment_terms(product)
    if not terms:
        return False
    return payment_term in terms


def _verified_coverage_duration(product, age=None):
    """产品的**可验证**保障期限 → ("lifetime" | "years" | "unverifiable", years|None)

    口径（只认**已验证**字段；无法验证 → 不得声称满足）：
      · `coverage_period_is_lifetime is True` → 终身（满足任意年限）；
      · `coverage_period_parse_quality ∈ {'parsed','parsed_long'}` 且
        `coverage_period_duration_unit == 'year'`  → 年数 = duration_value；
      · 同上且 `coverage_period_duration_unit == 'to_age'` → 年数 =
        duration_value - age（如「至70周岁」、35 岁 → 35 年）；
      · 其余（missing / ambiguous_term / 字段缺失 / 单位未知）→ **不可验证**。
    """
    if not isinstance(product, dict):
        return ("unverifiable", None)
    if product.get("coverage_period_is_lifetime") is True:
        return ("lifetime", None)
    quality = product.get("coverage_period_parse_quality")
    if quality not in _COVERAGE_PERIOD_VERIFIED_QUALITIES:
        return ("unverifiable", None)
    unit = product.get("coverage_period_duration_unit")
    value = product.get("coverage_period_duration_value")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return ("unverifiable", None)
    if unit == _COVERAGE_PERIOD_UNIT_YEAR:
        return ("years", value)
    if unit == _COVERAGE_PERIOD_UNIT_TO_AGE:
        if isinstance(age, bool) or not isinstance(age, int) or age <= 0:
            return ("unverifiable", None)
        years = value - age
        if years <= 0:
            return ("unverifiable", None)
        return ("years", years)
    return ("unverifiable", None)


def _product_meets_coverage_year(product, coverage_year, age=None):
    """该产品的**可验证**保障期限是否满足客户要求的年限 → bool

    ⚠ 期限**无法验证** → **不得**声称满足（→ 排除）。
    """
    if coverage_year is None:
        return True
    status, years = _verified_coverage_duration(product, age)
    if status == "lifetime":
        return True
    if status == "years":
        return years >= coverage_year
    return False


def _extract_quality_hints(product):
    """🆕 2026-08-20 quality-aware：从产品提取质量提示

    基于 P0/P1 数据处理引入的字段（产品库质量治理）：
    - data_quality="garbage" → skip_for_recommendation=True （37 个产品过滤）
    - coverage_period_quality="missing" → coverage_period 替换为"未明确"（112 个产品）
    - listing_time_quality=verified/estimated/missing/unknown → 各自对应 disclaimer
      （verified=541 / estimated=80 / missing=75 / unknown=1838）

    Returns:
        dict: {
            skip_for_recommendation: bool,
            disclaimers: list[str],
            coverage_period: str | None,
            data_quality: str | None,
            coverage_period_quality: str | None,
            listing_time_quality: str | None,
        }
    """
    result = {
        "skip_for_recommendation": False,
        "disclaimers": [],
        "coverage_period": product.get("coverage_period"),
        "data_quality": product.get("data_quality"),
        "coverage_period_quality": product.get("coverage_period_quality"),
        "listing_time_quality": product.get("listing_time_quality"),
    }

    # P0-1: garbage 数据不可信，跳过推荐
    if product.get("data_quality") == "garbage":
        result["skip_for_recommendation"] = True
        result["disclaimers"].append(
            "⚠️ 此产品信息未完全核实，请联系保险公司确认详情"
        )

    # P0-2 coverage_period: missing 提示 + 默认"未明确"
    if product.get("coverage_period_quality") == "missing":
        result["coverage_period"] = "未明确"
        result["disclaimers"].append(
            "⚠️ 保险期间未明确，建议联系保险公司确认"
        )

    # P0-2 listing_time: 分级 disclaimer（verified 不加提示）
    ltq = product.get("listing_time_quality")
    if ltq == "estimated":
        result["disclaimers"].append(
            "ℹ️ 上市时间为估算值（年/月推测），仅作参考"
        )
    elif ltq == "missing":
        result["disclaimers"].append(
            "ℹ️ 上市时间不详，建议咨询保险公司最新产品"
        )
    elif ltq == "unknown":
        result["disclaimers"].append(
            "ℹ️ 上市时间无法核实，建议联系保险公司确认"
        )

    return result


def is_discontinued(product):
    """判断产品是否已停售/已下架。

    判定依据见文件头「字段取值分布探查结论」：
      - is_active is False
      - validity_status ∈ {'已停售', 'DISCONTINUED'}
      - delisting_time == '已停售' 或为日期串
    """
    if product.get("is_active") is False:
        return True
    if product.get("validity_status") in _DISCONTINUED_VALIDITY:
        return True
    delisting = str(product.get("delisting_time") or "").strip()
    if delisting == "已停售":
        return True
    if delisting and _RE_DELIST_DATE.match(delisting):
        return True
    return False


def is_eligible_for_pool(product, filter_garbage=True, include_discontinued=False):
    """产品是否可进入默认产品池（报价 / 对比 / 计数共用的**唯一**资格谓词）。

    ⚠️ 2026-11-08 整改（R7 · SDI-4）：原先 `load_products()` 与 `load_product_stats()`
    各写一套过滤条件，`load_products()` **漏了 is_duplicate 过滤**，
    导致报价池里仍混有重复记录，且 `eligible_products` != len(load_products())。
    现在两者共用本谓词，口径不会再漂移。

    过滤项：
      - data_quality == 'garbage'      → 数据不可信
      - is_duplicate is True            → 重复记录
      - 已停售/已下架（除非 include_discontinued=True）
    """
    if filter_garbage:
        if _extract_quality_hints(product)["skip_for_recommendation"] is not False:
            return False
    if product.get("is_duplicate") is True:
        return False
    if not include_discontinued and is_discontinued(product):
        return False
    return True


def load_products(filter_garbage=True, include_discontinued=False):
    """加载产品数据。

    Args:
        filter_garbage: True=跳过 data_quality=garbage 的产品（默认）。
        include_discontinued: False=跳过已停售/已下架产品（默认）；
                              True=保留它们（显式查询停售产品时使用）。

    Returns:
        list[dict]: 产品列表（已过滤 garbage、重复记录与停售产品）
    """
    product_file = os.path.join(os.path.dirname(__file__), "../references/products.json")
    with open(product_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    products = [
        p for p in data["products"]
        if is_eligible_for_pool(p, filter_garbage=filter_garbage,
                                include_discontinued=include_discontinued)
    ]
    return products


def load_product_stats(include_discontinued=False):
    """产品池计数口径（含"全部产品"总数与停售排除数）。

    Returns:
        dict: {
            total_products: int,          # 产品库总数（"全部产品"口径）
            garbage_excluded: int,
            duplicate_excluded: int,
            discontinued_excluded: int,   # 默认被排除的停售/下架数量
            eligible_products: int,       # 默认返回列表长度
            include_discontinued: bool,
        }
    """
    product_file = os.path.join(os.path.dirname(__file__), "../references/products.json")
    with open(product_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    all_products = data["products"]

    garbage = [p for p in all_products if p.get("data_quality") == "garbage"]
    duplicates = [p for p in all_products if p.get("is_duplicate") is True]
    discontinued = [p for p in all_products if is_discontinued(p)]

    # ⚠️ 2026-11-08 整改（R7 · SDI-4）：与 load_products() 共用同一资格谓词，
    #    保证 eligible_products == len(load_products())。
    eligible = [
        p for p in all_products
        if is_eligible_for_pool(p, filter_garbage=True,
                                include_discontinued=include_discontinued)
    ]
    return {
        "total_products": len(all_products),
        "garbage_excluded": len(garbage),
        "duplicate_excluded": len(duplicates),
        "discontinued_excluded": len(discontinued),
        "eligible_products": len(eligible),
        "include_discontinued": include_discontinued,
    }


def _pool_disclaimers(stats):
    """产品池口径说明（进入结果的 _meta.disclaimers）。"""
    disclaimers = []
    if stats["include_discontinued"]:
        disclaimers.append(
            f"ℹ️ 本次显式包含已停售/已下架产品（产品库共 {stats['total_products']} 款，"
            f"其中 {stats['discontinued_excluded']} 款已停售/已下架），"
            f"这些产品不可投保，仅供历史查询参考"
        )
    elif stats["discontinued_excluded"]:
        disclaimers.append(
            f"ℹ️ 已排除 {stats['discontinued_excluded']} 款已停售/已下架产品"
            f"（产品库全部 {stats['total_products']} 款，"
            f"本次可对比 {stats['eligible_products']} 款）；"
            f"如需查询停售产品请显式传 include_discontinued=true"
        )
    if stats["garbage_excluded"]:
        disclaimers.append(
            f"ℹ️ 已排除 {stats['garbage_excluded']} 款数据质量不达标（data_quality=garbage）的产品"
        )
    if stats["duplicate_excluded"]:
        disclaimers.append(
            f"ℹ️ 已排除 {stats['duplicate_excluded']} 款重复记录（is_duplicate=true）"
        )
    return disclaimers


# ⚠ 官方 SDI-4 残余 AF-5（2026-11-28 公开复扫 · ai AF-S3 / china AF-S3'）
#   remediation 原文：
#     「… Reject unsupported combinations and missing rates instead of inventing
#       fallback prices; until authoritative pricing exists, explicitly label
#       every result as a non-binding heuristic estimate, remove
#       authoritative-rate claims, and prevent estimates from being presented as
#       confirmed quotes.」
# ⇒ 产品库**没有**经核实的费率表 → 本模块所有保费均为**非绑定启发式估算**
#   （年龄 / 性别 / 缴费期系数 = 启发式乘数；医疗险 / 意外险 = 通用费率）；
#   缺费率时**不得**编造兜底价（整改前的 `coverage_amount * 0.01` 已移除）。
_PRICING_BASIS = "heuristic_estimate"
_RATE_UNAVAILABLE_REASON = "产品库缺少该产品的费率数据，未编造兜底价"


def _parse_rate_per_10k(value):
    """产品的费率数据（premium_per_10k）→ 每万元保额年缴保费 → float | None

    ⚠ **缺 / 不可解析 / 非正数 → None**（= 费率不可用）。
    ⚠ 整改前的兜底口径（`coverage_amount * 0.01`，官方点名的「arbitrary 1%
      rate」）**已移除** → 缺费率时**不输出任何数字**。
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    if isinstance(value, str):
        nums = re.findall(r"[\d.]+", value)
        if not nums:
            return None
        try:
            f = float(nums[0])
        except ValueError:
            return None
        return f if f > 0 else None
    return None


def _product_rate_available(product):
    """该产品的费率是否**可用**（医疗险 / 意外险用通用费率 → 恒可用）"""
    if not isinstance(product, dict):
        return False
    if product.get("type") in ("医疗险", "意外险"):
        return True
    return _parse_rate_per_10k(product.get("premium_per_10k")) is not None


def calculate_premium(product, age, gender, coverage_amount, payment_term=None, coverage_year=None):
    """计算单一产品保费

    Args:
        coverage_year: 客户要求的**保障年限**（单位：年 · None = 不校验）。
            ⚠ 官方 SDI-4 残余 AE-3：此参数**必须**真正生效 →
            给定后**校验该产品的已验证保障期限是否满足该年限**
            （`_product_meets_coverage_year`）→ 不满足 / 无法验证 →
            抛 `CoverageYearError`
            （**不再**留一个「声明了但完全不用」的参数）。
    """
    if coverage_year is not None:
        coverage_year = _validate_coverage_year(coverage_year)
        if not _product_meets_coverage_year(product, coverage_year, age):
            raise CoverageYearError(
                "产品「%s」的保障期限无法验证或不足 %d 年，不得用于该期限的报价"
                % (product.get("name") or product.get("id") or "?", coverage_year))
    product_type = product.get("type")

    # 基础费率调整系数
    age_factor = 1.0
    if age >= 18 and age <= 30:
        age_factor = 0.8
    elif age >= 31 and age <= 40:
        age_factor = 1.0
    elif age >= 41 and age <= 50:
        age_factor = 1.3
    elif age >= 51 and age <= 55:
        age_factor = 1.6
    elif age > 55:
        age_factor = 2.0

    gender_factor = 1.0
    if gender in ["女", "女性"]:
        gender_factor = 0.85
    elif gender in ["男", "男性"]:
        gender_factor = 1.0

    # 缴费期系数
    payment_term_factor = 1.0
    if product_type in ["重疾险", "定期寿险", "储蓄险"]:
        if payment_term == "趸交":
            payment_term_factor = 0.85
        elif payment_term == "3年":
            payment_term_factor = 0.95
        elif payment_term == "5年":
            payment_term_factor = 1.0
        elif payment_term == "10年":
            payment_term_factor = 1.05
        elif payment_term == "20年":
            payment_term_factor = 1.15
        elif payment_term == "30年":
            payment_term_factor = 1.25

    # 医疗险和意外险按固定费率（与年龄相关）
    if product_type == "医疗险":
        if age <= 30:
            annual_premium = coverage_amount * 0.0003
        elif age <= 40:
            annual_premium = coverage_amount * 0.0004
        elif age <= 50:
            annual_premium = coverage_amount * 0.0006
        elif age <= 60:
            annual_premium = coverage_amount * 0.001
        else:
            annual_premium = coverage_amount * 0.0015
        return max(annual_premium, 200)  # 最低保费200元

    if product_type == "意外险":
        annual_premium = coverage_amount * 0.001
        return max(annual_premium, 100)  # 最低保费100元

    # 重疾险、定期寿险、储蓄险（按产品**自身**的费率数据 + 启发式系数估算）
    rate = _parse_rate_per_10k(product.get("premium_per_10k"))
    if rate is None:
        # ⚠ 官方 SDI-4 残余 AF-5：缺费率 → **不编造兜底价**（不输出任何数字）
        #   （整改前的 `coverage_amount * 0.01` 已被官方点名为「编造兜底价」）
        #   → 调用方（`calculate_all_premiums`）据此标记 `premium_unavailable`
        #     并在 `_meta` 披露；**不**静默给一个看起来像价的数字。
        return None

    base_premium = (coverage_amount / 10000) * rate

    total_premium = base_premium * age_factor * gender_factor * payment_term_factor

    return round(total_premium, 2)


def calculate_all_premiums(age, gender, coverage_amount, product_types=None, payment_term=None,
                           coverage_year=None, include_discontinued=False):
    """计算所有符合条件的产品的保费（quality-aware + 停售过滤 + **保障期限筛选**）

    Args:
        coverage_year: 客户要求的**保障年限**（单位：年 · None = 不按期限筛选）。
            · 必须是 **None** 或**正整数** → 非法值**显式报错**
              （`CoverageYearError`）→ **不得**静默忽略。
            · 给定后**按产品库已验证的 `coverage_period_*` 字段筛选**产品
              （终身 / 期限 ≥ 要求年限者保留；期限**无法验证**或不足者排除，
              排除数量在 `_meta.coverage_year_filtered_out` **披露**）。
            · 给定后**筛不出任何产品** → **显式报错**（`CoverageYearError`）
              → 不得返回空列表假装成功。
            · ⚠ 保费按各产品**自身**的费率数据 + 启发式系数**估算**
              （产品库**没有**按期限分档的费率表 → **不**自造「期限加权系数」）
              → 结果为**非绑定启发式估算**，该限制在 `_meta.disclaimers`
              **显式披露**。
        include_discontinued: False=默认不返回已停售/已下架产品；
                              True=显式查询停售产品（含在结果中并标注）。
        payment_term: 客户要求的**缴费期**（如「10年」/「趸交」· None = 不按缴费期筛选）。
            · 必须是 **None** 或**非空字符串** → 非法值**显式报错**
              （`PaymentTermError`）→ **不得**静默忽略。
            · 给定后**按产品库真实字段 `payment_choices` 筛选**产品
              （支持该缴费期者保留；不支持 / 缴费期**无法验证**者排除，
              排除数量在 `_meta.payment_term_filtered_out` **披露**）。
            · 支持该缴费期的产品**只**返回该缴费期的**单期**结果
              （`annual_premium` + `payment_term`）→ **不得**走全部缴费期分支。
            · 给定后**筛不出任何产品** → **显式报错**（`PaymentTermError`）
              → 不得返回空列表假装成功、不得回退到全部缴费期。
    """
    coverage_year = _validate_coverage_year(coverage_year)
    # ⚠ 官方 SDI-4 残余 AG-4：payment_term **真实生效**（校验 + 筛选 + 单期返回）
    payment_term = _validate_payment_term(payment_term)
    products = load_products(include_discontinued=include_discontinued)
    stats = load_product_stats(include_discontinued=include_discontinued)
    pool_disclaimers = _pool_disclaimers(stats)
    # ⚠ 官方 SDI-4 残余 AE-3：coverage_year **真实生效**（产品筛选）
    coverage_filtered_out = 0
    # ⚠ 官方 SDI-4 残余 AG-4：payment_term **真实生效**（产品筛选）
    payment_term_filtered_out = 0
    # ⚠ 官方 SDI-4 残余 AF-5：缺费率的产品计数（**不编造兜底价**）
    rate_unavailable_count = 0

    results = {}
    for product in products:
        # 按类型筛选
        if product_types:
            if product.get("type") not in product_types:
                continue

        # 年龄筛选
        if age > 55 and product.get("type") in ["定期寿险", "储蓄险"]:
            continue  # 定期寿险55岁以上不推荐
        if age > 60 and product.get("type") == "意外险":
            continue

        # ⚠ 官方 SDI-4 残余 AE-3：coverage_year **真实生效**（产品筛选）
        #   （期限**无法验证** / 不足要求年限 → **不得**声称满足 → 排除）
        if coverage_year is not None and not _product_meets_coverage_year(
                product, coverage_year, age):
            coverage_filtered_out += 1
            continue

        # ⚠ 官方 SDI-4 残余 AG-4：payment_term **真实生效**（产品筛选）
        #   （不支持 / 缴费期无法验证 → **不得**声称满足 → 排除）
        if payment_term is not None and not _product_supports_payment_term(
                product, payment_term):
            payment_term_filtered_out += 1
            continue

        # 计算保费
        premiums_by_term = {}
        rate_unavailable = False
        if payment_term is not None:
            # ⚠ AG-4：指定缴费期 → **只算该期**（不得走 all-terms 分支）
            available_terms = [payment_term]
        else:
            # 未指定缴费期 → 沿用既有「全部可用缴费期」口径（**零漂移**）
            available_terms = list(_DEFAULT_PAYMENT_TERMS)

        for term in available_terms:
            if product.get("type") in ["医疗险", "意外险"]:
                term_premium = calculate_premium(product, age, gender, coverage_amount, "年交")
            else:
                term_premium = calculate_premium(product, age, gender, coverage_amount, term)

            # ⚠ 官方 SDI-4 残余 AF-5：缺费率 → **不输出任何数字**
            if term_premium is None:
                rate_unavailable = True
                continue

            # 标准化缴费期名称
            term_name = term
            premiums_by_term[term_name] = term_premium

        if rate_unavailable:
            rate_unavailable_count += 1

        # 🆕 2026-08-20 quality-aware：获取 disclaimers 和数据质量标记
        hints = _extract_quality_hints(product)
        product_disclaimers = list(hints["disclaimers"])
        if is_discontinued(product):
            product_disclaimers.append(
                "⚠️ 该产品已停售/已下架（仅在显式查询停售产品时返回），不可投保"
            )

        # 如果指定了缴费期，只返回该缴费期
        # ⚠ 官方 SDI-4 残余 AG-4：请求的缴费期**不支持**的产品已在上面被排除
        #   ⇒ 走到这里的**一定**是「支持该缴费期」的产品 → **单期**结果
        #   （缺费率时 annual_premium = None，**不编造**兜底价）
        if payment_term is not None:
            results[product.get("id")] = {
                "name": product.get("name"),
                "company": product.get("company"),
                "type": product.get("type"),
                "annual_premium": premiums_by_term.get(payment_term),
                "payment_term": payment_term,
                # ⚠ 官方 SDI-4 残余 AF-5：结果为**非绑定启发式估算**（显式标记）
                "pricing_basis": _PRICING_BASIS,
                "premium_is_estimate": True,
                "premium_unavailable": rate_unavailable,
                "premium_unavailable_reason": (_RATE_UNAVAILABLE_REASON
                                               if rate_unavailable else ""),
                "coverage_amount": coverage_amount,
                "coverage_period": hints["coverage_period"],  # 🆕 缺失时为"未明确"
                "waiting_period": product.get("waiting_period"),
                "core_coverage": ", ".join(product.get("key_benefits", [])) if isinstance(product.get("key_benefits"), list) else product.get("core_coverage", ""),
                "notes": product.get("notes", ""),
                # 🆕 质量提示（SKILL 用来给客户附 disclaimer）
                "data_quality": hints["data_quality"],
                "coverage_period_quality": hints["coverage_period_quality"],
                "listing_time_quality": hints["listing_time_quality"],
                "disclaimers": product_disclaimers,
                "is_discontinued": is_discontinued(product),
            }
        else:
            # 返回所有可用缴费期
            results[product.get("id")] = {
                "name": product.get("name"),
                "company": product.get("company"),
                "type": product.get("type"),
                "premiums_by_term": premiums_by_term,
                # ⚠ 官方 SDI-4 残余 AF-5：结果为**非绑定启发式估算**（显式标记）
                "pricing_basis": _PRICING_BASIS,
                "premium_is_estimate": True,
                "premium_unavailable": rate_unavailable,
                "premium_unavailable_reason": (_RATE_UNAVAILABLE_REASON
                                               if rate_unavailable else ""),
                "coverage_amount": coverage_amount,
                "coverage_period": hints["coverage_period"],  # 🆕 缺失时为"未明确"
                "waiting_period": product.get("waiting_period"),
                "core_coverage": ", ".join(product.get("key_benefits", [])) if isinstance(product.get("key_benefits"), list) else product.get("core_coverage", ""),
                "notes": product.get("notes", ""),
                # 🆕 质量提示（SKILL 用来给客户附 disclaimer）
                "data_quality": hints["data_quality"],
                "coverage_period_quality": hints["coverage_period_quality"],
                "listing_time_quality": hints["listing_time_quality"],
                "disclaimers": product_disclaimers,
                "is_discontinued": is_discontinued(product),
            }

    returned_count = len([k for k in results if k != "_meta"])
    # ⚠ 官方 SDI-4 残余 AE-3：给定 coverage_year 却**筛不出任何产品**
    #   → **显式报错**（不得返回空列表假装成功）
    if coverage_year is not None and returned_count == 0:
        raise CoverageYearError(
            "按保障期限 %d 年筛选后没有任何产品满足条件"
            "（产品池 %d 款，其中 %d 款因保障期限无法验证或不足被排除）"
            % (coverage_year, stats["eligible_products"], coverage_filtered_out))

    # ⚠ 官方 SDI-4 残余 AG-4：给定 payment_term 却**筛不出任何产品**
    #   → **显式报错**（不得返回空列表假装成功 · 不得回退到全部缴费期）
    if payment_term is not None and returned_count == 0:
        raise PaymentTermError(
            "按缴费期 %s 筛选后没有任何产品满足条件"
            "（产品池 %d 款，其中 %d 款因不支持该缴费期或缴费期无法验证被排除）"
            % (payment_term, stats["eligible_products"], payment_term_filtered_out))

    # ⚠ 官方 SDI-4 残余 AE-3：**如实披露**保障期限口径与保费口径
    coverage_disclaimers = []
    if coverage_year is not None:
        coverage_disclaimers.append(
            "ℹ️ 保障期限筛选依据产品库已验证的 `coverage_period_*` 字段"
            "（要求 ≥ %d 年）；已排除 %d 款保障期限无法验证或不足的产品"
            % (coverage_year, coverage_filtered_out))
        coverage_disclaimers.append(
            "ℹ️ 保费按各产品自身费率计算，未按保障期限加权"
            "（产品库无按保障期限分档的费率表）")

    # ⚠ 官方 SDI-4 残余 AG-4：**如实披露**缴费期筛选口径
    payment_term_disclaimers = []
    if payment_term is not None:
        payment_term_disclaimers.append(
            "ℹ️ 缴费期筛选依据产品库 `payment_choices` 字段（要求支持 %s）；"
            "已排除 %d 款不支持该缴费期或缴费期无法验证的产品"
            % (payment_term, payment_term_filtered_out))
        payment_term_disclaimers.append(
            "ℹ️ 仅返回支持 %s 的产品的该缴费期报价（未回退为全部缴费期）"
            % payment_term)

    # ⚠ 官方 SDI-4 残余 AF-5：**定价口径诚实化**（非绑定启发式估算）
    #   ⚠ 披露内容必须覆盖**这一层**定价限制（既有 disclaimers 只覆盖保障期限）。
    pricing_disclaimers = [
        "ℹ️ 保费为**非绑定启发式估算**：年龄 / 性别 / 缴费期系数为启发式乘数，"
        "医疗险 / 意外险使用通用费率；本结果不构成保险公司的承保报价、不具约束力，"
        "实际保费须以保险公司核保出单为准"
    ]
    if rate_unavailable_count:
        pricing_disclaimers.append(
            "ℹ️ 有 %d 款产品缺少费率数据，已标记为保费不可用（缺费率不编造兜底价）"
            % rate_unavailable_count)

    # 🆕 I3：全部产品计数口径 + 停售排除说明（不影响单产品保费公式）
    results["_meta"] = {
        "total_products": stats["total_products"],
        "eligible_products": stats["eligible_products"],
        "returned_products": returned_count,
        "discontinued_excluded": stats["discontinued_excluded"],
        "garbage_excluded": stats["garbage_excluded"],
        "duplicate_excluded": stats["duplicate_excluded"],
        "include_discontinued": include_discontinued,
        # ⚠ 官方 SDI-4 残余 AE-3：coverage_year 的**可观测**效果
        "coverage_year": coverage_year,
        "coverage_year_filtered_out": coverage_filtered_out,
        # ⚠ 官方 SDI-4 残余 AG-4：payment_term 的**可观测**效果
        "payment_term": payment_term,
        "payment_term_filtered_out": payment_term_filtered_out,
        # ⚠ 官方 SDI-4 残余 AF-5：定价口径（机器可读标记 + 缺费率计数）
        "pricing_basis": _PRICING_BASIS,
        "premium_is_estimate": True,
        "rate_unavailable_count": rate_unavailable_count,
        "disclaimers": (pool_disclaimers + coverage_disclaimers
                        + payment_term_disclaimers
                        + pricing_disclaimers),
    }

    return results


def compare_payment_terms(products_list, age, gender, coverage_amount, include_discontinued=False):
    """对比不同缴费期的保费

    ⚠ 官方 SDI-4 残余 AG-4：整改前读的是产品库里**不存在**的 `payment_terms`
      → 恒空 → 本函数**空转**（永远不产出任何缴费期报价）
      ⇒ 改读**真实字段** `payment_choices`（同 `_available_payment_terms` 口径）。
    """
    products = load_products(include_discontinued=include_discontinued)
    comparison = []

    for product in products:
        if product.get("id") not in products_list:
            continue

        row = {
            "product_id": product.get("id"),
            "name": product.get("name"),
            "company": product.get("company"),
            "type": product.get("type")
        }

        row["pricing_basis"] = _PRICING_BASIS
        row["premium_is_estimate"] = True
        # ⚠ 官方 SDI-4 残余 AG-4：真实缴费期字段（`payment_choices`）
        for term in _available_payment_terms(product):
            if product.get("type") in ["医疗险", "意外险"]:
                annual = calculate_premium(product, age, gender, coverage_amount, "年交")
            else:
                annual = calculate_premium(product, age, gender, coverage_amount, term)
            if annual is None:
                # ⚠ 官方 SDI-4 残余 AF-5：缺费率 → 不给数字（如实标记）
                row["premium_unavailable"] = True
                row["premium_unavailable_reason"] = _RATE_UNAVAILABLE_REASON
                row[term] = None
                continue
            row[term] = annual

        comparison.append(row)

    return comparison


# 示例档案（仅在 stdin 未提供输入时作为演示数据打印，并明确标注来源）
EXAMPLE_PREMIUM_INPUT = {
    "age": 35,
    "gender": "男",
    "coverage_amount": 500000,
    "product_types": None,
    "payment_term": "20年",
    "coverage_year": None
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
        sys.stderr.write(json.dumps(EXAMPLE_PREMIUM_INPUT, ensure_ascii=False, indent=2) + "\n")
        params = EXAMPLE_PREMIUM_INPUT
    else:
        try:
            params = json.loads(raw)
        except Exception as e:
            print(json.dumps({"error": str(e)}, ensure_ascii=False))
            return 0
    try:
        results = calculate_all_premiums(
            params.get("age", 35),
            params.get("gender", "男"),
            params.get("coverage_amount", 500000),
            params.get("product_types"),
            params.get("payment_term"),
            params.get("coverage_year"),
            params.get("include_discontinued", False)
        )
    except Exception as e:
        # ⚠ 官方 SDI-4 残余 AE-3：**显式拒绝**（非法 coverage_year /
        #   按期限筛不出任何产品）→ 以**非零退出码**返回
        #   （不得让「被拒绝」看起来像「成功」）。
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 1
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
