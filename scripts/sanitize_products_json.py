#!/usr/bin/env python3
"""
sanitize_products_json.py — 中和产品库中对 agent 的祈使指令（ClawHub AR1 / Anti-Refusal）

🆕 2026-10-30：ClawHub 安全审计 v2.0.196 的 AR1（Anti-Refusal，severity HIGH）

背景
----
`references/products.json` 的 `health_disclosure` / `renewal_terms` 是外部抓取
（Tavily + LLM 摘要）回填的自由文本，其中混入了**对 agent 的祈使句**：

    "Always answer insurance questions truthfully and accurately."
    "Health disclosure must be truthful; otherwise, coverage may be voided."
    "do not volunteer information not asked."

ClawHub 安全扫描器据此判定「Skill instructs the agent to never refuse or to always
comply」→ Anti-Refusal（AR1 × 9，severity HIGH）。这类句子**不是**产品条款本身，
而是抓取摘要时误写成了对助手的指令，会抑制 agent 拒绝不安全/越界请求的能力。

本脚本做什么
------------
把这类**祈使句式**改写为**中性陈述句**。语义信息全部保留：
- 健康告知要求（需如实填写）
- 未如实告知的后果（保单解除 / 拒赔 / 合同解除）
- 询问范围（回答被问询的问题即可，无需主动补充）

改写后仍是「英文原文 + 中文中性句」的混合文本 —— 这是**有意为之**：
只中和祈使语气，不改写整段英文，避免误伤条款语义（如 regardless of …）。

⚠️ 刻意**不动**的东西
--------------------
- 保险条款语义里的 "regardless of ..."（如 "guaranteed renewal regardless of
  health changes"）是**产品条款**，不是对 agent 的指令 → **不改**
- `coverage_period_*` 等结构化续保字段（2535 款齐全）→ 不动
- 任何其他字段（名称/保费/保额/条款…）→ 不动

用法
----
    # 中和并原地写回（自动备份到 references/backups/）
    python3 scripts/sanitize_products_json.py --db references/products.json

    # 只报告不写盘
    python3 scripts/sanitize_products_json.py --db references/products.json --dry-run

    # 校验（断言无祈使指令）→ 退出码 0/1
    python3 scripts/sanitize_products_json.py --db references/products.json --check

幂等性
------
改写规则以「句子级替换表」实现：命中即替换，不命中即原样保留。
**跑第二次结果与第一次字节级相同**（已由 test_data_hygiene.py 断言）。
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime

# ---------------------------------------------------------------------------
# 祈使指令检测（与 ClawHub 扫描器的 Anti-Refusal 口径一致）
# 注意：只匹配「对 agent 的祈使」，不匹配保险条款语义
# ---------------------------------------------------------------------------
IMPERATIVE_PATTERNS = [
    r"always\s+answer\b",
    r"always\s+be\s+truthful\b",
    r"must\s+be\s+truthful\b",
    r"do\s+not\s+volunteer\b",
    r"never\s+refuse\b",
    r"always\s+comply\b",
    r"ignore\s+(previous|prior|above)\b",
    r"system\s+prompt\b",
]
IMPERATIVE_RE = re.compile("|".join(IMPERATIVE_PATTERNS), re.IGNORECASE)

# 「保险条款语义」豁免：regardless of 在产品语境里是条款，不是指令
REGARDLESS_RE = re.compile(r"regardless of", re.IGNORECASE)

# ---------------------------------------------------------------------------
# 句子级改写表：把祈使句式换成中性陈述
# 每条 = (正则, 中性替换文本)
# 语义全部保留（健康告知要求 / 未如实告知的后果 / 询问范围）
# ---------------------------------------------------------------------------
REWRITES = [
    # ── Always answer … ──
    (r"Always answer insurance questions truthfully and accurately\.",
     "健康告知要求如实回答保险公司问询；未如实告知可能导致保单解除或拒赔。"),
    (r"Always answer insurance questions directly based on medical records\.",
     "健康告知应以病历记录为依据如实填写；未如实告知可能导致保单解除或拒赔。"),
    (r"Always answer insurance questions truthfully\.",
     "健康告知要求如实回答保险公司问询；未如实告知可能导致保单解除或拒赔。"),
    (r"Always answer asked questions, not all\.",
     "如实回答保险公司实际问询的问题即可，无需回答未被问及的事项。"),
    (r"Always answer insurer's specific questions honestly; do not volunteer information not asked\.",
     "如实回答保险公司具体问询的问题即可，无需主动补充未被问及的信息。"),
    (r"Always answer insurer's specific questions honestly\.",
     "如实回答保险公司具体问询的问题即可。"),
    (r"always answer insurance-specific questions honestly\.",
     "如实回答保险公司具体问询的问题即可。"),
    (r"always answer insurance company's specific health questions truthfully\.",
     "如实回答保险公司具体问询的健康问题即可。"),
    (r"always answer truthfully based on medical records\.",
     "健康告知应以病历记录为依据如实填写。"),
    (r"always answer honestly\.",
     "健康告知需如实填写。"),

    # ── must be truthful（含分号从句，整体替换避免残留半句）──
    (r"Health disclosure must be truthful; otherwise, coverage may be voided\.",
     "健康告知需如实填写；未如实告知可能导致保单解除。"),
    (r"Health disclosure must be truthful; omissions can void coverage\.",
     "健康告知需如实填写；遗漏告知事项可能导致保单解除。"),
    (r"Health disclosure must be truthful; if not asked, no need to disclose\.",
     "健康告知需如实填写；未被问及的事项无需填写。"),
    (r"Health disclosure must be truthful; if insurance questions are asked, answer honestly\.",
     "健康告知需如实填写；对保险公司问询的问题应如实回答。"),
    (r"Health disclosure must be truthful but not exaggerated\.",
     "健康告知需如实填写，不应夸大病情。"),
    (r"Health disclosure must be truthful for accurate insurance assessment; incomplete or false information can lead to claim denial or policy cancellation\.",
     "健康告知需如实填写，方可作出准确的核保评估；信息不完整或不真实可能导致拒赔或保单解除。"),
    (r"Health disclosure must be truthful to avoid contract termination\.",
     "健康告知需如实填写，以免保险人解除合同。"),
    (r"Health declaration(?:s)? must be truthful; false information can void coverage\.",
     "健康告知需如实填写；信息不真实可能导致保单解除。"),
    (r"Health disclosure(?:s)? must be truthful; false information can void coverage\.",
     "健康告知需如实填写；信息不真实可能导致保单解除。"),
    (r"Health declaration(?:s)? must be truthful; otherwise, the policy may be voided\.",
     "健康告知需如实填写；未如实告知可能导致保单解除。"),
    # 兜底：任何 Health disclosure(s)/Health declaration(s) must be truthful …
    (r"(Health disclosure(?:s)?|Health declaration(?:s)?) must be truthful\b",
     "健康告知需如实填写"),
    (r"health disclosure must be truthful\b",
     "健康告知需如实填写"),

    # ── 其他指令片段 ──
    (r"Always consult professionals for complex cases\.",
     "复杂情形建议咨询专业保险代理人或核保人员。"),
    (r"If insurance and smart underwriting conflict, health disclosure is primary\.",
     "智能核保结论与健康告知要求冲突时，以健康告知要求为准。"),
    (r"do not volunteer information not asked\.",
     "无需主动补充未被问及的信息。"),
]

# 排序策略：先按【具体度】—— 含标点从句的具体句式优先于泛化兜底；
# 同具体度内按模式长度降序（长句优先，避免短句先命中导致长句残留）。
# ⚠️ 泛化兜底（(Health disclosure…|Health declaration…) must be truthful）必须排在最后，
#    否则它会先命中并吃掉后面的从句，留下 "健康告知需如实填写; otherwise, coverage may be voided." 这种半句。
_GENERIC_FALLBACK = r"(Health disclosure(?:s)?|Health declaration(?:s)?) must be truthful\b"


def _sort_key(pair):
    pattern = pair[0]
    is_generic = 1 if pattern == _GENERIC_FALLBACK else 0
    return (is_generic, -len(pattern))


REWRITES.sort(key=_sort_key)


def neutralize(text):
    """把文本中的祈使指令改写为中性陈述。返回 (新文本, 命中数)。"""
    if not isinstance(text, str) or not text:
        return text, 0
    hits = 0
    out = text
    for pattern, replacement in REWRITES:
        # ⚠️ 必须 IGNORECASE：真实数据里同一句式大小写混用
        #（"Health disclosure must be truthful" vs "health disclosure must be truthful"）。
        # 若用大小写敏感匹配，长句模式会漏掉小写开头 → 只剩泛化兜底命中 →
        # 产出 "健康告知需如实填写; otherwise, coverage may be voided." 这种半句残渣。
        new_out, n = re.subn(pattern, replacement, out, flags=re.IGNORECASE)
        if n:
            out = new_out
            hits += n
    return out, hits


def sanitize_product_fields(product):
    """就地中和单个产品的两个自由文本字段。返回命中数。"""
    hits = 0
    for field in ("health_disclosure", "renewal_terms"):
        value = product.get(field)
        if not isinstance(value, str) or not value:
            continue
        new_value, n = neutralize(value)
        if n:
            product[field] = new_value
            hits += n
    return hits


def scan_file(path):
    """扫描一个 products.json，返回 (祈使命中列表, 产品总数)。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    products = data.get("products", [])
    found = []
    for p in products:
        for field in ("health_disclosure", "renewal_terms"):
            value = p.get(field)
            if isinstance(value, str) and IMPERATIVE_RE.search(value):
                # 条款语义豁免：整段只出现 regardless of 时不算指令
                if REGARDLESS_RE.search(value) and not re.search(
                    r"always\s+answer|must\s+be\s+truthful|do\s+not\s+volunteer|"
                    r"never\s+refuse|always\s+comply|system\s+prompt",
                    value,
                    re.IGNORECASE,
                ):
                    continue
                found.append((p.get("name"), field))
    return found, len(products)


def main():
    parser = argparse.ArgumentParser(description="中和中和产品库中对 agent 的祈使指令（ClawHub AR1）")
    parser.add_argument("--db", required=True, help="products.json 路径")
    parser.add_argument("--dry-run", action="store_true", help="只报告不写盘")
    parser.add_argument("--check", action="store_true", help="只校验（无祈使指令则退出码 0）")
    args = parser.parse_args()

    path = os.path.abspath(args.db)
    if not os.path.exists(path):
        print(f"❌ 找不到 {path}", file=sys.stderr)
        return 2

    if args.check:
        found, total = scan_file(path)
        if found:
            print(f"❌ 仍有 {len(found)} 处祈使指令（{path}）:")
            for name, field in found:
                print(f"   - {name} [{field}]")
            return 1
        print(f"✅ 无祈使指令（{path}，共 {total} 款产品）")
        return 0

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    products = data.get("products", [])

    hits = 0
    touched = 0
    for p in products:
        n = sanitize_product_fields(p)
        if n:
            hits += n
            touched += 1

    print(f"扫描 {len(products)} 款产品，命中祈使指令 {hits} 处，涉及 {touched} 款产品")

    if args.dry_run:
        print("（--dry-run：未写盘）")
        return 0

    if hits == 0:
        print("✅ 无需改动（已干净），未写盘")
        return 0

    # 备份（references/backups/ 已在 .gitignore 内）
    backup_dir = os.path.join(os.path.dirname(os.path.dirname(path)), "references", "backups")
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"products.json.pre_ar1_sanitize_{ts}")
    shutil.copy2(path, backup_path)
    print(f"已备份 → {backup_path}")

    # 写回：保持与原文件一致的 readable 格式（indent=2 + ensure_ascii=False）
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"已写回 → {path}")

    # 写回后自检
    found, total = scan_file(path)
    if found:
        print(f"❌ 写回后仍有 {len(found)} 处祈使指令:", file=sys.stderr)
        for name, field in found:
            print(f"   - {name} [{field}]", file=sys.stderr)
        return 1
    print(f"✅ 写回后自检通过：0 处祈使指令（共 {total} 款产品）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
