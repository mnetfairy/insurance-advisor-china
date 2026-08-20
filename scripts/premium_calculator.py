#!/usr/bin/env python3
"""
保费计算工具
输入：年龄、性别、保额、保障期限、产品类型
输出：各产品年缴保费，支持不同缴费期对比
"""

import json
import sys
import os


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


def load_products(filter_garbage=True):
    """加载产品数据。

    Args:
        filter_garbage: True=跳过 data_quality=garbage 的产品（默认）。

    Returns:
        list[dict]: 产品列表（已过滤 garbage）
    """
    product_file = os.path.join(os.path.dirname(__file__), "../references/products.json")
    with open(product_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    products = data["products"]
    if filter_garbage:
        products = [
            p for p in products
            if _extract_quality_hints(p)["skip_for_recommendation"] is False
        ]
    return products

def calculate_premium(product, age, gender, coverage_amount, payment_term=None, coverage_year=None):
    """计算单一产品保费"""
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

    # 重疾险、定期寿险、储蓄险
    premium_val = product.get("premium_per_10k")
    if premium_val is not None:
        # 处理字符串值，如 "约280" 或 "280"
        if isinstance(premium_val, str):
            import re
            nums = re.findall(r'[\d.]+', premium_val)
            premium_val = float(nums[0]) if nums else 0
        base_premium = (coverage_amount / 10000) * float(premium_val)
    else:
        base_premium = coverage_amount * 0.01

    total_premium = base_premium * age_factor * gender_factor * payment_term_factor

    return round(total_premium, 2)


def calculate_all_premiums(age, gender, coverage_amount, product_types=None, payment_term=None, coverage_year=None):
    """计算所有符合条件的产品的保费（quality-aware）"""
    products = load_products()

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

        # 计算保费
        premiums_by_term = {}
        available_terms = product.get("payment_terms", ["年交"])

        for term in available_terms:
            if product.get("type") in ["医疗险", "意外险"]:
                term_premium = calculate_premium(product, age, gender, coverage_amount, "年交")
            else:
                term_premium = calculate_premium(product, age, gender, coverage_amount, term)

            # 标准化缴费期名称
            term_name = term
            premiums_by_term[term_name] = term_premium

        # 🆕 2026-08-20 quality-aware：获取 disclaimers 和数据质量标记
        hints = _extract_quality_hints(product)

        # 如果指定了缴费期，只返回该缴费期
        if payment_term and payment_term in premiums_by_term:
            results[product.get("id")] = {
                "name": product.get("name"),
                "company": product.get("company"),
                "type": product.get("type"),
                "annual_premium": premiums_by_term[payment_term],
                "payment_term": payment_term,
                "coverage_amount": coverage_amount,
                "coverage_period": hints["coverage_period"],  # 🆕 缺失时为"未明确"
                "waiting_period": product.get("waiting_period"),
                "core_coverage": ", ".join(product.get("key_benefits", [])) if isinstance(product.get("key_benefits"), list) else product.get("core_coverage", ""),
                "notes": product.get("notes", ""),
                # 🆕 质量提示（SKILL 用来给客户附 disclaimer）
                "data_quality": hints["data_quality"],
                "coverage_period_quality": hints["coverage_period_quality"],
                "listing_time_quality": hints["listing_time_quality"],
                "disclaimers": hints["disclaimers"],
            }
        else:
            # 返回所有可用缴费期
            results[product.get("id")] = {
                "name": product.get("name"),
                "company": product.get("company"),
                "type": product.get("type"),
                "premiums_by_term": premiums_by_term,
                "coverage_amount": coverage_amount,
                "coverage_period": hints["coverage_period"],  # 🆕 缺失时为"未明确"
                "waiting_period": product.get("waiting_period"),
                "core_coverage": ", ".join(product.get("key_benefits", [])) if isinstance(product.get("key_benefits"), list) else product.get("core_coverage", ""),
                "notes": product.get("notes", ""),
                # 🆕 质量提示（SKILL 用来给客户附 disclaimer）
                "data_quality": hints["data_quality"],
                "coverage_period_quality": hints["coverage_period_quality"],
                "listing_time_quality": hints["listing_time_quality"],
                "disclaimers": hints["disclaimers"],
            }

    return results


def compare_payment_terms(products_list, age, gender, coverage_amount):
    """对比不同缴费期的保费"""
    products = load_products()
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

        for term in product.get("payment_terms", []):
            if product.get("type") in ["医疗险", "意外险"]:
                annual = calculate_premium(product, age, gender, coverage_amount, "年交")
            else:
                annual = calculate_premium(product, age, gender, coverage_amount, term)
            row[term] = annual

        comparison.append(row)

    return comparison


if __name__ == "__main__":
    if len(sys.argv) == 1:
        # 默认测试：35岁男性，50万保额
        results = calculate_all_premiums(35, "男", 500000, payment_term="20年")
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        try:
            params = json.loads(sys.stdin.read())
            results = calculate_all_premiums(
                params.get("age", 35),
                params.get("gender", "男"),
                params.get("coverage_amount", 500000),
                params.get("product_types"),
                params.get("payment_term"),
                params.get("coverage_year")
            )
            print(json.dumps(results, ensure_ascii=False, indent=2))
        except Exception as e:
            print(json.dumps({"error": str(e)}, ensure_ascii=False))
