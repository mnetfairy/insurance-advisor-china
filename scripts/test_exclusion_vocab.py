#!/usr/bin/env python3
"""
除外/否定词表 · **结构性漂移守卫**（单一事实源 / 超集不变量 / 通用模式）

为什么需要这个文件（背景）
────────────────────────
本 skill 的 ClawHub 安全审计在 2026-11-24 / 11-25 / 11-26 连续三轮报出
**同一族**的 Excessive Agency 问题（SDI-4 残余 V/W/X/Y/Z/AA/AB/AC），
每一轮的点名都不同、但**根因相同**：

    否定/除外语义在代码里维护了**多份互相独立**的词表 ——
      ① 自由文本侧  _NEG_MARKERS_FORWARD / _NEG_MARKERS_BACKWARD / _NEG_MARKERS_BOTH
      ② 结构化侧    _STRUCTURED_NEGATION_TOKENS
      ③ 主体级侧    _CRX_EXCLUSION_MARKERS
      ④ 类别级侧    _CRX_CI_EXCLUSION_MARKERS

    官方每轮复扫只点出**其中一份**漏掉的短语；上一轮把短语补进了自由文本侧，
    结构化侧**照样漏** → 下一轮继续报 → 「同类问题反复出现」。

    ⇒ 真正的根因不是「又漏抄了两个词」，而是
      **词表之间没有任何一致性约束**（结构性漂移 = 必然复发）。

一次性修法（残余 AC 落地）
──────────────────────────
    A. **单一事实源**：`_EXCL_*` 语义族是唯一词表来源，全部路径由它派生；
    B. **超集不变量**：结构化侧词表 ⊇ 自由文本侧词表
       —— 这条**正面封死**官方本轮 finding 那一类（结构化 ⊉ 自由文本）漏判；
    C. **通用模式**：`_EXCL_PATTERNS` 按**构式**覆盖同族任意新表述，
       自由文本侧与结构化侧**共用同一份** → 下一轮换个词再来也能命中；
    D. 既有成员一律保留（只增不改）→ 既有口径零漂移。

本文件做什么
────────────
    把 B（超集不变量）与 A（单一事实源）从「运行时 assert + 专项断言」升级为
    **独立可运行的守卫**：任何人改动词表，只要引入漂移 → 立刻红。

⚠️ 本文件是**本地维护工具**，不随发布产物分发（`.clawhubignore` 已排除
   `scripts/test_*.py`），也不是运行时能力面的一部分。

退出码：0 全部通过 / 1 至少一项失败
"""
import json
import os
import re
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(THIS_DIR)
sys.path.insert(0, THIS_DIR)

import plan_designer as PD  # noqa: E402

PASS = "[PASS]"
FAIL = "[FAIL]"
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"  {PASS if ok else FAIL} {name}{(' — ' + detail) if detail else ''}")
    return bool(ok)


def main():
    print("=" * 60)
    print("除外词表 · 结构性漂移守卫（单一事实源 / 超集不变量 / 通用模式）")
    print("=" * 60)
    src = open(os.path.join(SKILL_DIR, "scripts", "plan_designer.py"),
               "r", encoding="utf-8").read()

    # ==================================================================
    # ① 单一事实源：语义族存在，且各条路径**引用**它（而非另抄一份）
    # ==================================================================
    print("\nTest 1: 单一事实源")
    families = ("_EXCL_SCOPE_EXTRA_LITERALS = (", "_EXCL_NONPAYMENT_LITERALS =",
                "_EXCL_CATEGORY_EXTRA_LITERALS =", "_EXCL_SUBJECT_EXTRA_LITERALS =",
                "_EXCL_GENERAL_LITERALS = (", "_EXCL_PATTERNS = (")
    check("1.1 全部语义族必须存在", all(f in src for f in families))
    check("1.2 共享「不予给付」词表仍是**唯一**定义（不得二次抄写）",
          src.count("_SHARED_NONPAYMENT_NEGATIONS = (") == 1)
    check("1.3 语义族 ② 必须**引用**共享词表（而非另抄一份）",
          "_EXCL_NONPAYMENT_LITERALS = _SHARED_NONPAYMENT_NEGATIONS" in src)
    struct_block = src.split("_STRUCTURED_NEGATION_TOKENS = (")[1].split("\n)")[0]
    check("1.4 结构化侧必须**引用**各语义族",
          all(k in struct_block for k in ("*_SHARED_EXCLUSION_VOCAB,",
                                          "*_EXCL_SCOPE_EXTRA_LITERALS,",
                                          "*_EXCL_CATEGORY_EXTRA_LITERALS,",
                                          "*_EXCL_SUBJECT_EXTRA_LITERALS,",
                                          "*_EXCL_GENERAL_LITERALS,")))
    check("1.5 自由文本侧必须**引用**共享词表",
          "*_SHARED_NONPAYMENT_NEGATIONS," in src.split("_NEG_MARKERS_BOTH = (")[1])

    # ==================================================================
    # ② 超集不变量（本轮官方 finding 的反面 · 防复发核心）
    # ==================================================================
    print("\nTest 2: 超集不变量")
    missing = sorted(set(PD._NEG_MARKERS) - set(PD._STRUCTURED_NEGATION_TOKENS))
    check("2.1 结构化侧词表 ⊇ 自由文本侧词表", not missing, f"漏词：{missing!r}")
    missing2 = sorted(set(PD._NEG_MARKERS) - set(PD._EXCL_ALL_LITERALS))
    check("2.2 单一事实源 ⊇ 自由文本侧词表", not missing2, f"漏词：{missing2!r}")
    check("2.3 模块级自检必须存在（漂移无法上线）",
          "set(_NEG_MARKERS) <= set(_STRUCTURED_NEGATION_TOKENS)" in src)
    for kw in ("不在承保范围", "不属于承保范围", "不在保障范围", "不予给付",
               "不予赔付", "不予承保", "不含", "不包含", "不包括", "除外"):
        check(f"2.4 结构化侧必须认得「{kw}」", kw in PD._STRUCTURED_NEGATION_TOKENS)

    # ==================================================================
    # ③ 通用模式：按**构式**覆盖 → 未枚举的新表述也命中（终结打补丁）
    # ==================================================================
    print("\nTest 3: 通用模式")
    check("3.1 通用模式必须存在", bool(PD._EXCL_PATTERNS))
    novel_scope = ("不在保险范围", "不属于保障范围", "不在赔付范围",
                   "不在报销范围", "不属于承保范围")
    for t in novel_scope:
        check(f"3.2 结构化侧命中未枚举表述「{t}」",
              PD._structured_text_is_negative(t) is True)
    for t in novel_scope:
        prod = {"key_benefits": [f"CAR-T治疗{t}"], "highlights": ""}
        check(f"3.3 自由文本侧命中未枚举表述「{t}」",
              not PD._medical_treatment_claims(prod))
    # 模式必须**不跨语义子句边界**
    check("3.4 模式不得跨子句边界误伤",
          PD._structured_text_is_negative("不在承保范围。含CAR-T治疗") is True
          and PD._structured_text_is_negative("含CAR-T治疗。保障范围清晰") is False)
    # 存疑表述**不得**被当成肯定授权（宁可压制、不得授权）。
    # ⚠ 注意：存疑表述被判为 negative / ambiguous **两者都压制** → 功能上等价；
    #   但绝不能让它落回 “一致 affirmative”（`payment_status` 不是决定键 →
    #   若不认作否定，该条目会被当成**干净肯定授权** → 更危险）。
    for hedge in ("不能确定是否给付", "不确定是否属于承保范围",
                  "可能无法给付，需以条款为准"):
        prod = {"name": "t",
                "treatment_coverage": {"CAR-T": {"covered": True,
                                                 "payment_status": hedge}},
                "highlights": "含CAR-T治疗"}
        check(f"3.5 存疑表述「{hedge}」不得授权 CAR-T 治疗",
              not PD._medical_treatment_claims(prod),
              f"实际 {PD._medical_treatment_claims(prod)!r}")

    # ==================================================================
    # ④ 官方 finding 原文场景（端到端 · 不得产出承保宣称）
    # ==================================================================
    print("\nTest 4: 官方残余 AC finding 原文场景")
    for ps in ("不在承保范围", "不属于承保范围"):
        prod = {"name": "测试医疗险",
                "treatment_coverage": {"CAR-T": {"covered": True,
                                                 "payment_status": ps}},
                "highlights": "含CAR-T治疗"}
        check(f"4.1 结构化 payment_status={ps!r} 必须压制",
              PD._structured_authority_denies(prod, "CAR-T") is True)
        check(f"4.2 结构化 payment_status={ps!r} 不得宣称 CAR-T",
              not PD._medical_treatment_claims(prod))
        excl = PD._record_exclusion_keywords(prod)
        check(f"4.3 结构化 payment_status={ps!r} 记录级除外须关联 CAR-T",
              any("CAR-T" in k for k in excl), f"实际 {sorted(excl)!r}")
        # 端到端：不得出现「含CAR-T治疗」
        try:
            kb = PD.derive_medical_key_benefits(prod, [])
            blob = kb if isinstance(kb, str) else str(kb)
        except Exception as e:  # noqa: BLE001
            blob = "__ERR__:%r" % (e,)
        check(f"4.4 端到端不得出现「含CAR-T治疗」（{ps}）",
              "含CAR-T治疗" not in blob, blob[:200])

    # ==================================================================
    # ⑤ 反向回归：不得过度收紧（肯定表述仍可宣称）
    # ==================================================================
    print("\nTest 5: 反向回归（不得过度收紧）")
    for ok_text in ("含CAR-T治疗费用报销", "CAR-T治疗可报销", "CAR-T治疗在承保范围"):
        prod = {"key_benefits": [ok_text], "highlights": ok_text}
        claims = PD._medical_treatment_claims(prod)
        check(f"5.1 肯定表述「{ok_text}」仍可宣称",
              any("CAR-T" in c for c in claims), f"实际 {claims!r}")
    prod = {"name": "t",
            "treatment_coverage": {"CAR-T": {"covered": True,
                                             "payment_status": "给付"}},
            "highlights": "含CAR-T治疗"}
    check("5.2 一致 affirmative 的结构化条目仍可授权",
          any("CAR-T" in c for c in PD._medical_treatment_claims(prod)))
    prod = {"name": "t",
            "treatment_coverage": {"CAR-T": {"covered": True,
                                             "payment_status": "给付"}},
            "highlights": "含CAR-T治疗"}
    check("5.3 明确 affirm 的条目不得被记为记录级除外",
          not any("CAR-T" in k for k in PD._record_exclusion_keywords(prod)),
          f"实际 {sorted(PD._record_exclusion_keywords(prod))!r}")

    # ==================================================================
    # ⑥ 真实语料回归：62 款产品的既有宣称口径不得漂移
    # ==================================================================
    print("\nTest 6: 真实语料回归")
    # ⚠ **golden 基线**：真实语料里“宣称 CAR-T / 质子重离子”的产品集合必须
    #   与整改前**完全一致** —— 既不得新增（过度宣称）也不得减少（过度收紧）。
    #   当前基线：仅「蓝医保长期医疗险（20年保证续保）」一款，
    #   其 highlights 明确写「质子重离子+CAR-T全覆盖」→ 属**真实承保**。
    _EXPECTED_CLAIMING = {"蓝医保长期医疗险（20年保证续保）"}
    try:
        products = PD.load_products()
        claiming = set()
        for p in products:
            claims = PD._medical_treatment_claims(p)
            hits = [c for c in claims if "CAR-T" in c or "质子重离子" in c]
            if not hits:
                continue
            claiming.add(p.get("name"))
            text = json.dumps(p, ensure_ascii=False)
            check(f"6.1 {p.get('name')} 宣称 {hits} 必须有**明确肯定授权证据**",
                  ("全覆盖" in text) or ("可报销" in text)
                  or ("含CAR-T治疗" in text) or ("含质子重离子治疗" in text),
                  f"实际 {hits!r}")
        check("6.2 宣称 CAR-T/质子重离真的产品集合须与基线**完全一致**"
              "（既不得新增也不得减少）",
              claiming == _EXPECTED_CLAIMING,
              f"实际 {sorted(claiming)!r} ≠ 基线 {sorted(_EXPECTED_CLAIMING)!r}")
        check("6.3 真实语料加载正常", len(products) > 0, f"{len(products)} 款")
    except Exception as e:  # noqa: BLE001
        check(f"6.1 真实语料回归：{e!r}", False)

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
