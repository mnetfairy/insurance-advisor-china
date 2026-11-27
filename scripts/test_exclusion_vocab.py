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
import premium_calculator as PC  # noqa: E402

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
    pcsrc = open(os.path.join(SKILL_DIR, "scripts", "premium_calculator.py"),
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

    # ==================================================================
    # ⑦ 残余 AD 漂移守卫（2026-11-26 公开复扫 · ai v2.4.46 / china v2.4.43）
    #    官方 finding：类别级重疾路径未消费共享除外词表（scope 家族）
    #    官方 remediation：Derive … from one normalized vocabulary and shared
    #    semantic patterns / Require validated coverage evidence /
    #    Treat unresolved exclusions or conflicting evidence as unverified /
    #    Suppress affirmative claims on every output surface /
    #    Propagate an explicit unverified limitation to the final plan.
    # ==================================================================
    print("\nTest 7: 残余 AD 漂移守卫"
          "（CRX 路径共享词表派生 · 通用模式接入 · 三面压制 · 语料无回归）")

    # ── ⑦.1 单一事实源：两条 CRX 路径必须**引用**共享语义族 ──────────
    check("7.1 共享语义族别名必须存在（两库同口径）",
          all(k in src for k in ("_EXCL_SCOPE_LITERALS = (",
                                 "_EXCL_CATEGORY_LITERALS = (",
                                 "_EXCL_SUBJECT_LITERALS = (")))
    _subj_block = src.split("_CRX_EXCLUSION_MARKERS = (")[1].split("\n)")[0]
    _ci_block = src.split("_CRX_CI_EXCLUSION_MARKERS = (")[1].split("\n)")[0]
    check("7.1 主体级路径必须**引用**范围级语义族",
          "*_EXCL_SCOPE_LITERALS," in _subj_block, f"实际 {_subj_block[:100]!r}")
    check("7.1 类别级路径必须**引用**范围级语义族（残余 AD 核心）",
          "*_EXCL_SCOPE_LITERALS," in _ci_block, f"实际 {_ci_block[:100]!r}")
    check("7.1 两条 CRX 路径必须**引用**主体级语义族",
          "*_SHARED_EXCLUSION_SUBJECT," in _subj_block
          and "*_SHARED_EXCLUSION_SUBJECT," in _ci_block)
    check("7.1 主体级路径必须**引用**类别级语义族",
          "*_EXCL_CATEGORY_LITERALS," in _subj_block)
    check("7.1 类别级路径必须**引用**类别级共享族（残余 AB 同源）",
          "*_SHARED_EXCLUSION_CATEGORY," in _ci_block)
    check("7.1 两条 CRX 路径必须**引用**不予给付级语义族",
          "*_EXCL_NONPAYMENT_LITERALS," in _subj_block
          and "*_EXCL_NONPAYMENT_LITERALS," in _ci_block)
    # ⚠ **不得**再出现「另抄一份」的局部词表
    check("7.1 主体级路径不得**另抄**范围族（必须引用共享族）",
          '"不在承保范围"' not in _subj_block and '"不属于承保范围"' not in _subj_block)
    check("7.1 类别级路径不得**另抄**范围族（必须引用共享族）",
          '"不在承保范围"' not in _ci_block and '"不属于承保范围"' not in _ci_block)

    # ── ⑦.2 超集不变量（三条 · 双向）────────────────────────────────
    _vocab = set(PD._SHARED_EXCLUSION_VOCAB)
    check("7.2 超集不变量：单一事实源 ⊇ 自由文本侧词表",
          set(PD._NEG_MARKERS) <= set(PD._EXCL_ALL_LITERALS),
          f"漏词：{sorted(set(PD._NEG_MARKERS) - set(PD._EXCL_ALL_LITERALS))!r}")
    check("7.2 超集不变量：主体级路径 ⊇ 共享归一化除外词表",
          _vocab <= set(PD._CRX_EXCLUSION_MARKERS),
          f"漏词：{sorted(_vocab - set(PD._CRX_EXCLUSION_MARKERS))!r}")
    check("7.2 超集不变量：类别级路径 ⊇ 共享归一化除外词表",
          _vocab <= set(PD._CRX_CI_EXCLUSION_MARKERS),
          f"漏词：{sorted(_vocab - set(PD._CRX_CI_EXCLUSION_MARKERS))!r}")
    for kw in ("不在承保范围", "不属于承保范围"):
        check(f"7.2 两条 CRX 路径都必须认得「{kw}」",
              kw in PD._CRX_EXCLUSION_MARKERS
              and kw in PD._CRX_CI_EXCLUSION_MARKERS)

    # ── ⑦.3 两条 CRX 路径必须消费**同一份** `_EXCL_PATTERNS` ─────────
    check("7.3 通用模式必须存在且非空", bool(PD._EXCL_PATTERNS))
    check("7.3 源码级：CRX 路径必须消费通用模式",
          "_crx_pattern_marker_hits(" in src
          and "_EXCL_PATTERNS" in src.split("def _crx_pattern_marker_hits(")[1][:900])
    check("7.3 源码级：通用模式命中必须按**等价字面标记**参与判定",
          "_CRX_PATTERN_EQUIV_MARKER" in src)
    # 未枚举的新表述（下一轮官方换词也能命中）
    # ⚠ **主体级路径**验「轻症」主体；**类别级路径**验「重疾 / 重大疾病」类别
    #   （两条路径的**主体**不同 → 不得交叉断言）
    check("7.3 未枚举表述「轻症不在任何承保范围」须被主体级路径命中",
          PD._crx_clause_excludes_subject("轻症不在任何承保范围", "轻症") is True,
          f"实际 {PD._crx_clause_excludes_subject('轻症不在任何承保范围', '轻症')!r}")
    check("7.3 未枚举表述「重大疾病不在任何承保范围」须被类别级路径命中",
          PD._crx_clause_excludes_ci_category("重大疾病不在任何承保范围") is True,
          f"实际 {PD._crx_clause_excludes_ci_category('重大疾病不在任何承保范围')!r}")
    check("7.3 未枚举表述「轻症不得给付」须被主体级路径命中",
          PD._crx_clause_excludes_subject("轻症不得给付", "轻症") is True,
          f"实际 {PD._crx_clause_excludes_subject('轻症不得给付', '轻症')!r}")
    check("7.3 未枚举表述「重大疾病不得给付」须被类别级路径命中",
          PD._crx_clause_excludes_ci_category("重大疾病不得给付") is True,
          f"实际 {PD._crx_clause_excludes_ci_category('重大疾病不得给付')!r}")

    # ── ⑦.4 官方 finding 原文场景（记录级 + 三面压制 + 显式 limitation）─
    for _cl in ("轻症不在承保范围", "不在承保范围轻症", "轻症不属于承保范围"):
        _prod = {"name": "官方场景", "highlights": "120种重疾，含轻症保障",
                 "notes": _cl}
        _st = PD._crx_ci_claim_state(_prod)
        check(f"7.4 官方场景「{_cl}」：记录级轻症除外必须命中",
              PD._crx_record_mild_excluded(_prod) is True)
        check(f"7.4 官方场景「{_cl}」：共享状态不得 allowed=True",
              _st.get("allowed") is not True, f"实际 {_st!r}")
        check(f"7.4 官方场景「{_cl}」：必须给出非空显式 limitation",
              isinstance(_st.get("limitation"), dict) and bool(_st.get("limitation")),
              f"实际 {_st.get('limitation')!r}")
        check(f"7.4 官方场景「{_cl}」：benefits 面必须压制",
              PD._crx_key_benefits(_prod, 500000, "standard") == "")
        check(f"7.4 官方场景「{_cl}」：features 面必须压制",
              "待核实" in (PD._crx_feature(_prod) or ""))
    for _cl in ("重大疾病不在承保范围", "不在承保范围重大疾病",
                "重大疾病不属于承保范围"):
        _prod = {"name": "官方场景", "highlights": "120种重疾，含轻症保障",
                 "notes": _cl}
        _st = PD._crx_ci_claim_state(_prod)
        check(f"7.4 官方场景「{_cl}」：记录级类别级除外必须命中",
              PD._crx_record_ci_category_excluded(_prod) is True)
        check(f"7.4 官方场景「{_cl}」：共享状态不得 allowed=True",
              _st.get("allowed") is not True, f"实际 {_st!r}")
        check(f"7.4 官方场景「{_cl}」：必须给出非空显式 limitation",
              isinstance(_st.get("limitation"), dict) and bool(_st.get("limitation")),
              f"实际 {_st.get('limitation')!r}")

    # ── ⑦.5 反向回归（不得过度收紧）────────────────────────────────
    _ok = {"name": "对照", "highlights": "120种重疾，含轻症保障", "notes": ""}
    _ok_state = PD._crx_ci_claim_state(_ok)
    check("7.5 反向回归：无除外时状态必须 allowed=True",
          _ok_state.get("allowed") is True, f"实际 {_ok_state!r}")
    check("7.5 反向回归：无除外时必须保留轻症宣称",
          "120种重疾+轻症保障" in (PD._crx_key_benefits(_ok, 500000, "standard") or ""),
          f"实际 {PD._crx_key_benefits(_ok, 500000, 'standard')!r}")
    for _benign in ("轻症赔付比例25%", "40种轻症赔20%x6次",
                    "被保险人轻症/重症豁免"):
        check(f"7.5 反向回归：不得误伤「{_benign}」",
              PD._crx_clause_excludes_subject(_benign, "轻症") is False)
    check("7.5 反向回归：「续保不保证」不得被当成类别级重疾除外",
          PD._crx_clause_excludes_ci_category("续保不保证") is False)
    check("7.5 反向回归：「等待期为90天，未满期内轻重疾病不赔付」不得被当成类别级除外",
          PD._crx_clause_excludes_ci_category("等待期为90天，未满期内轻重疾病不赔付") is False)

    # ── ⑦.6 存疑表述 → ambiguous（**不是** negative）且**仍然压制** ────
    for _hedge in ("轻症可能不在承保范围", "重大疾病可能不在承保范围"):
        _prod = {"name": "存疑", "highlights": "120种重疾，含轻症保障",
                 "notes": _hedge}
        _st = PD._crx_ci_claim_state(_prod)
        check(f"7.6 存疑「{_hedge}」不得算「确定除外」（excluded=False）",
              _st.get("excluded") is False, f"实际 {_st!r}")
        check(f"7.6 存疑「{_hedge}」必须判 unverified",
              _st.get("unverified") is True, f"实际 {_st!r}")
        check(f"7.6 存疑「{_hedge}」**仍然压制**肯定宣称",
              _st.get("allowed") is False, f"实际 {_st!r}")
        check(f"7.6 存疑「{_hedge}」须产出非空限制说明",
              isinstance(_st.get("limitation"), dict) and bool(_st.get("limitation")),
              f"实际 {_st.get('limitation')!r}")
    check("7.6 源码级：存疑对冲词词表必须存在（两库同口径）",
          "_EXCL_HEDGE_PREFIXES = (" in src and "_EXCL_HEDGE_LOOKBACK =" in src)

    # ── ⑦.7 真实语料**无回归**（自洽性守卫 · 恒定有效）───────────────
    # ⚠ **绝不可**写成「宣称数 = 0」：本库**合法**存在带治疗/责任宣称的���品
    #   （例：china 库「蓝医保长期医疗险（20年保证续保）」合法宣称
    #   「质子重离子+CAR-T全覆盖」；重疾库亦有 384 款产品合法宣称
    #   「N种重疾+轻症保障」）→ 写成 0 会**误报**。
    #   ⇒ 采用**无回归**口径：① 宣称集合**不得**与改前基线不一致；
    #     ② 每一款宣称的产品**必须**有明确肯定授权证据（不得有除外证据）。
    _SNAP_DIR_MARK = "_scratch/accept"
    _snap = None
    _probe = SKILL_DIR
    for _i in range(6):
        _probe = os.path.dirname(_probe)
        _cand = os.path.join(_probe, _SNAP_DIR_MARK,
                              "_baseline_residual_ad_%s.json"
                              % ("ai" if SKILL_DIR.endswith("ai-insurance-advisor")
                                 else "china"))
        if os.path.exists(_cand):
            _snap = _cand
            break
    try:
        products = PD.load_products()
        check("7.7 真实语料加载正常", len(products) > 0, f"{len(products)} 款")
        # ⚠ 2026-11-27（残余 AE-2）：7.7 的口径由「与改前基线**完全一致**」
        #   改为**行为不变式**（任务书 §⑤·2 · §⑥.5）：
        #   ① **重疾险产品**（type==重疾险）的宣称集合与基线**完全一致**
        #      → 168 款真实重疾宣称**零丢失**（不得过度收紧）；
        #   ② **非重疾险且记录里提到重疾**的产品 → 宣称集合与基线**完全一致**
        #      → 不得过度收紧（如医疗险合法提及「重疾医疗」）；
        #   ③ **非重疾险且记录里完全不提重疾**的产品 → **不得**出现重疾宣称
        #      → 改前的**凭空宣称**必须消失（AE-2 根因被正确修复的结果）。
        #   ⚠ **绝不可**写成「宣称数 = 0」：本库**合法**存在带治疗/责任宣称的
        #     产品（例：医疗险合法宣称「质子重离子+CAR-T全覆盖」）→ 写成 0 会误报。
        #   ⇒ 断言按**产品分组**逐条比对，**不**依赖「全部一致」这一会误报的写法。
        _before = None
        if _snap:
            _before = json.load(open(_snap, encoding="utf-8"))["rows"]
        _now = {}
        _grp = {}
        for _i, _p in enumerate(products):
            # ⚠ key 与快照**同格式**（序号 + 名称 · 名称可能重复）
            _k = f"{_i:05d}|{_p.get('name') or ''}"
            _txt = "".join(PD._product_text_leaves(_p))
            if _p.get("type") == "重疾险":
                _g = "ci"                      # 重疾险 → 真实重疾宣称面
            elif "重疾" in _txt or "重大疾病" in _txt:
                _g = "nonci_wd"                # 非重疾险但记录**确实**提到重疾
            else:
                _g = "nonci_novd"              # 非重疾险且记录**完全不提**重疾
            _grp[_k] = _g
            _now[_k] = {
                "disease_claim": PD._crx_disease_claim(_p),
                "key_benefits_standard": PD._crx_key_benefits(_p, 500000, "standard"),
                "feature": PD._crx_feature(_p),
            }
        _cnt = {g: len([k for k in _grp if _grp[k] == g])
                for g in ("ci", "nonci_wd", "nonci_novd")}
        # ① / ② 与基线**完全一致**（分组逐条比对；不依赖「全部一致」写法）
        if _before is not None:
            for _g, _label in (("ci", "重疾险产品"),
                               ("nonci_wd", "非重疾险·记录提到重疾的产品")):
                _keys = [k for k in _grp if _grp[k] == _g]
                for _fld in ("disease_claim", "key_benefits_standard", "feature"):
                    _b = {k: _before.get(k, {}).get(_fld) for k in _keys}
                    _n = {k: _now[k].get(_fld) for k in _keys}
                    _diff = [k for k in _keys if _b.get(k) != _n.get(k)]
                    check(f"7.7 {_label}「{_fld}」须与基线**完全一致**"
                          "（行为不变式 · 不得写成「宣称数 = 0」）",
                          not _diff,
                          f"该组 {_cnt[_g]} 款 · 差异 {len(_diff)} 条：{_diff[:5]!r}")
        else:
            check("7.7 改前快照缺失 → 跳过逐条对照（自洽性守卫仍生效）", True,
                  f"未找到 {_SNAP_DIR_MARK}/_baseline_residual_ad_*.json")
        # ③ 非重疾险且记录**完全不提**重疾 → **不得**出现任何重疾宣称
        _bad = []
        for _k, _g in _grp.items():
            if _g != "nonci_novd":
                continue
            _p = products[int(_k.split("|", 1)[0])]
            if _now[_k].get("key_benefits_standard"):
                _bad.append((_p.get("name"), "key_benefits"))
            if _now[_k].get("disease_claim"):
                _bad.append((_p.get("name"), "disease_claim"))
            if "确诊即赔付" in (_now[_k].get("feature") or ""):
                _bad.append((_p.get("name"), "feature"))
        check("7.7 非重疾险且记录**完全不提**重疾的产品"
              "**不得**出现重疾宣称（行为不变式 · 不得写成「宣称数 = 0」）",
              not _bad,
              f"该组 {_cnt['nonci_novd']} 款 · 异常 {len(_bad)} 条：{_bad[:5]!r}")
        # ② 每一款宣称的产品**必须**有肯定授权证据（不得有除外证据）
        _bad = []
        for _p in products:
            _c = PD._crx_disease_claim(_p)
            if not _c:
                continue
            _st = PD._crx_ci_claim_state(_p)
            if not _st.get("allowed"):
                _bad.append(_p.get("name"))
            else:
                _hl = _p.get("highlights")
                _hl = _hl if isinstance(_hl, str) else ""
                if "轻症" not in _hl:
                    _bad.append(_p.get("name"))
        check("7.7 宣称轻症/重疾的产品必须**有肯定授权证据且无除外证据**"
              "（无回归口径 · 不得写成「宣称数 = 0」）",
              not _bad, f"异常产品={_bad[:8]!r}（共 {len(_bad)} 款）")
    except Exception as e:  # noqa: BLE001
        check(f"7.7 真实语料无回归：{e!r}", False)

    # ==================================================================
    # ⑧ 残余 AE 漂移守卫（2026-11-27 · 4 类根因 · 行为不变式口径）
    #
    # 官方 finding（两库均复现 · ai v2.4.48 / china v2.4.45 · SDI-4 · MEDIUM）：
    #   AE-1 结构化**嵌套**除外证据被漏扫 → 产出肯定治疗宣称
    #   AE-2 「没检测到问题」被当成「已验证承保」（absence ⇒ validated）
    #   AE-3 `coverage_year` 入参被吞 → 筛选与报价都无效果
    #   AE-4 类别级除外漏掉「不涵盖 / 不覆盖 / 不纳入」→ 仍产出肯定宣称
    #
    # ⚠ **断言口径铁律**：本节一律写成**行为不变式**
    #   （「必须判 contradictory」「不得 validated」「产品集必须单调收缩」
    #     「重疾险宣称集合与基线完全一致」…），
    #   **不得**写成「宣称数 = 0」（本库**合法**存在带治疗/责任宣称的产品
    #   —— 例：医疗险合法宣称「质子重离子+CAR-T全覆盖」）→ 写成 0 会**误报**。
    #   上一轮踩过这个坑（见任务书 §⑤·2）。
    # ==================================================================
    print("\nTest 8: 残余 AE 漂移守卫"
          "（嵌套除外下钻 · 肯定证据闸门 · coverage_year 接线 · 类别级作用域）")

    # ── ⑧.1 AE-1：嵌套结构化除外证据必须被判 contradictory + 主动压制 ──
    _AE1_NESTED = [
        ("嵌套 dict（payment.status）",
         {"treatment": "CAR-T", "covered": True,
          "payment": {"status": "不予给付"}}),
        ("list-of-dict（items[].status）",
         {"treatment": "CAR-T", "covered": True,
          "items": [{"status": "不在承保范围"}]}),
        ("嵌套 dict（coverage.status）",
         {"treatment": "CAR-T", "covered": True,
          "coverage": {"status": "不在承保范围"}}),
    ]
    for _label, _entry in _AE1_NESTED:
        _st = PD._structured_value_state(_entry)
        check(f"8.1 AE-1 {_label} 里的除外证据 → 必须判 contradictory（不得 affirmative）",
              _st == "contradictory", f"实际 {_st!r}")
        _prod = {"name": "AE1 嵌套除外测试险",
                 "treatment_coverage": {"CAR-T": _entry},
                 "key_benefits": ["含CAR-T治疗费用报销"]}
        check(f"8.1 AE-1 {_label} 里的除外证据 → 必须 denies=True（主动压制）",
              PD._structured_authority_denies(_prod, "CAR-T") is True,
              f"实际 {PD._structured_authority_denies(_prod, 'CAR-T')!r}")
        check(f"8.1 AE-1 {_label} 里的除外证据 → 不得授权该治疗手段（resolves=False）",
              PD._structured_authority_resolves(_prod, "CAR-T") is False,
              f"实际 {PD._structured_authority_resolves(_prod, 'CAR-T')!r}")
        check(f"8.1 AE-1 {_label} 里的除外证据 → 不得对外宣称该治疗手段",
              not PD._medical_treatment_claims(_prod),
              f"实际 {PD._medical_treatment_claims(_prod)!r}")
    # 反向回归（防过度收紧）：**正向**字符串不得被递归误判为否定
    _AE1_FLAT_POS = {"treatment": "CAR-T", "covered": True,
                     "payment_status": "已承保"}
    check("8.1 AE-1 反向回归 · 扁平正向「已承保」→ 必须仍判 affirmative",
          PD._structured_value_state(_AE1_FLAT_POS) == "affirmative",
          f"实际 {PD._structured_value_state(_AE1_FLAT_POS)!r}")
    _AE1_FLAT_NEG = {"treatment": "CAR-T", "covered": True,
                     "payment_status": "不在承保范围"}
    check("8.1 AE-1 反向回归 · 扁平除外「不在承保范围」→ 必须仍被压制",
          PD._structured_value_state(_AE1_FLAT_NEG) != "affirmative",
          f"实际 {PD._structured_value_state(_AE1_FLAT_NEG)!r}")

    # ── ⑧.2 AE-2：「没检测到问题」不得被当成「已验证承保」────────────
    _AE2_NEG = [
        ("空证据记录", {"name": "AE2 空证据测试险"}),
        ("「重疾保障待核实」记录",
         {"name": "AE2 待核实测试险", "highlights": "重疾保障待核实"}),
        ("「重疾保障待核实」记录（其它字段）",
         {"name": "AE2 待核实测试险2", "notes": "重疾保障待核实"}),
    ]
    for _label, _prod in _AE2_NEG:
        _st = PD._crx_ci_claim_state(_prod)
        check(f"8.2 AE-2 {_label} → 不得判 validated=True",
              _st.get("validated") is not True, f"实际 {_st!r}")
        check(f"8.2 AE-2 {_label} → 必须判 unverified=True",
              _st.get("unverified") is True, f"实际 {_st!r}")
        check(f"8.2 AE-2 {_label} → 必须产出**非空**显式 limitation",
              bool(_st.get("limitation")), f"实际 {_st.get('limitation')!r}")
        check(f"8.2 AE-2 {_label} → benefits 面不得产出肯定卖点",
              PD._crx_key_benefits(_prod, 500000, "standard") == "",
              f"实际 {PD._crx_key_benefits(_prod, 500000, 'standard')!r}")
        check(f"8.2 AE-2 {_label} → premium 面不得产出肯定卖点",
              PD._crx_key_benefits(_prod, 500000, "premium") == "",
              f"实际 {PD._crx_key_benefits(_prod, 500000, 'premium')!r}")
        check(f"8.2 AE-2 {_label} → features 面不得产出肯定宣称",
              "确诊即赔付" not in (PD._crx_feature(_prod) or ""),
              f"实际 {PD._crx_feature(_prod)!r}")
    # 反向回归（防过度收紧）：**明确肯定证据**的记录必须仍可宣称
    _AE2_OK = {"name": "AE2 明确肯定证据测试险",
               "highlights": "重疾保障，确诊即赔付",
               "coverage_items": [{"treatment": "重大疾病", "covered": True}]}
    check("8.2 AE-2 反向回归 · 明确肯定证据 → 必须仍判 validated=True",
          PD._crx_ci_claim_state(_AE2_OK).get("validated") is True,
          f"实际 {PD._crx_ci_claim_state(_AE2_OK)!r}")
    check("8.2 AE-2 反向回归 · 明确肯定证据 → 必须仍产出肯定卖点",
          bool(PD._crx_key_benefits(_AE2_OK, 500000, "standard")),
          f"实际 {PD._crx_key_benefits(_AE2_OK, 500000, 'standard')!r}")

    # ── ⑧.3 AE-3：coverage_year 必须在**筛选**与**报价**上可观测地生效 ──
    _AE3_TYPE = "定期寿险"      # 该类型有可验证的年限分档（20/25/30/35 年）
    _AE3_SETS = {}
    for _y in (None, 10, 25, 35):
        try:
            _r = PC.calculate_all_premiums(35, "男", 500000,
                                          product_types=[_AE3_TYPE],
                                          coverage_year=_y)
            _AE3_SETS[_y] = set(k for k in _r if k != "_meta")
        except Exception as e:  # noqa: BLE001
            _AE3_SETS[_y] = set()
            check(f"8.3 AE-3 coverage_year={_y!r} 报价调用异常", False,
                  f"{type(e).__name__}: {e}")
    _AE3_SIZES = "None={0} 10年={1} 25年={2} 35年={3}".format(
        len(_AE3_SETS.get(None, ())), len(_AE3_SETS.get(10, ())),
        len(_AE3_SETS.get(25, ())), len(_AE3_SETS.get(35, ())))
    check("8.3 AE-3 不同 coverage_year → 返回产品集必须**不同**（筛选可观测生效）",
          len({frozenset(s) for s in _AE3_SETS.values()}) >= 3,
          f"各期限产品集规模：{_AE3_SIZES}")
    check("8.3 AE-3 期限要求越严 → 产品集必须**单调收缩**（筛选真的在筛）",
          _AE3_SETS.get(35, set()) < _AE3_SETS.get(25, set())
          < _AE3_SETS.get(10, set()) <= _AE3_SETS.get(None, set()),
          _AE3_SIZES)
    # 报价侧可观测：_meta 必须如实披露被排除数量 + 「保费未按期限加权」口径
    try:
        _r25 = PC.calculate_all_premiums(35, "男", 500000,
                                         product_types=[_AE3_TYPE],
                                         coverage_year=25)
        _meta = _r25.get("_meta") or {}
        check("8.3 AE-3 报价 _meta 必须如实披露 coverage_year 生效结果",
              _meta.get("coverage_year") == 25
              and isinstance(_meta.get("coverage_year_filtered_out"), int)
              and _meta["coverage_year_filtered_out"] > 0,
              f"实际 coverage_year={_meta.get('coverage_year')!r} "
              f"filtered_out={_meta.get('coverage_year_filtered_out')!r}")
        check("8.3 AE-3 报价 _meta 必须如实披露「保费未按保障期限加权」的口径",
              any("未按保障期限加权" in str(d)
                  for d in (_meta.get("disclaimers") or [])),
              f"实际 disclaimers={_meta.get('disclaimers')!r}")
    except Exception as e:  # noqa: BLE001
        check("8.3 AE-3 报价 _meta 披露检查异常", False, f"{type(e).__name__}: {e}")
    # 非法 coverage_year → **显式拒绝**（不得静默忽略）
    for _bad in (0, -1, "5", 2.5, True):
        _rejected = False
        try:
            PC.calculate_all_premiums(35, "男", 500000,
                                      product_types=[_AE3_TYPE],
                                      coverage_year=_bad)
        except Exception:  # noqa: BLE001
            _rejected = True
        check(f"8.3 AE-3 非法 coverage_year={_bad!r} → 必须**显式拒绝**",
              _rejected, "未抛异常（静默忽略了非法入参）")
    # 筛不出任何产品 → **显式错误**（不得返回空列表假装成功）
    _no_match_rejected = False
    try:
        _r = PC.calculate_all_premiums(35, "男", 500000,
                                       product_types=[_AE3_TYPE],
                                       coverage_year=100)
        _no_match_rejected = False      # 返回了「成功」结构 → 假装成功
    except Exception:  # noqa: BLE001
        _no_match_rejected = True
    check("8.3 AE-3 给定期限却筛不出任何产品 → 必须**显式报错**（不得假装成功）",
          _no_match_rejected, "既未报错也未返回错误结构")
    # 单产品报价侧：coverage_year 不得再是「声明了但不用」的参数
    try:
        _short = None
        for _p in PC.load_products():
            if _p.get("type") == _AE3_TYPE and not PC._product_meets_coverage_year(
                    _p, 35, 35):
                _short = _p
                break
        if _short is not None:
            _rejected = False
            try:
                PC.calculate_premium(_short, 35, "男", 500000, "年交",
                                     coverage_year=35)
            except Exception:  # noqa: BLE001
                _rejected = True
            check("8.3 AE-3 calculate_premium 的 coverage_year 必须**真正生效**"
                  "（期限不足须拒绝）", _rejected,
                  f"产品={_short.get('name')!r}")
        else:
            check("8.3 AE-3 calculate_premium 的 coverage_year 必须**真正生效**"
                  "（期限不足须拒绝）", False, "未找到期限不足的样本产品")
    except Exception as e:  # noqa: BLE001
        check("8.3 AE-3 单产品报价检查异常", False, f"{type(e).__name__}: {e}")

    # ── ⑧.4 AE-4：类别级除外必须命中「不涵盖重大疾病保障」，且不得命中
    #         「不覆盖核爆炸导致的疾病」（主体作用域判别）────────────────
    _AE4_CAT = {"name": "AE4 类别级除外测试险",
                "highlights": "120种重疾，含轻症保障",
                "coverage_description": "不涵盖重大疾病保障"}
    _st = PD._crx_ci_claim_state(_AE4_CAT)
    check("8.4 AE-4 「不涵盖重大疾病保障」→ 必须判**类别级除外**（excluded=True）",
          _st.get("excluded") is True, f"实际 {_st!r}")
    check("8.4 AE-4 「不涵盖重大疾病保障」→ 不得 allowed=True",
          _st.get("allowed") is not True, f"实际 {_st!r}")
    check("8.4 AE-4 「不涵盖重大疾病保障」→ 必须产出**非空**显式 limitation",
          bool(_st.get("limitation")), f"实际 {_st.get('limitation')!r}")
    check("8.4 AE-4 「不涵盖重大疾病保障」→ benefits 面不得产出肯定卖点",
          PD._crx_key_benefits(_AE4_CAT, 500000, "standard") == "",
          f"实际 {PD._crx_key_benefits(_AE4_CAT, 500000, 'standard')!r}")
    check("8.4 AE-4 条款级：「不涵盖重大疾病保障」→ 必须判类别级除外",
          PD._crx_clause_excludes_ci_category("不涵盖重大疾病保障") is True)
    # 主体作用域对照：**特定病因**除外**不得**当成类别级除外
    for _other in ("本产品不覆盖核爆炸导致的疾病", "不覆盖核爆炸导致的疾病",
                   "不涵盖因酗酒导致的疾病"):
        check(f"8.4 AE-4 对照组「{_other}」→ **不得**判类别级除外",
              PD._crx_clause_excludes_ci_category(_other) is False,
              f"实际 {PD._crx_clause_excludes_ci_category(_other)!r}")
    _AE4_OTHER = {"name": "AE4 他对象除外测试险",
                   "highlights": "120种重疾，含轻症保障",
                   "coverage_description": "本产品不覆盖核爆炸导致的疾病"}
    _sto = PD._crx_ci_claim_state(_AE4_OTHER)
    check("8.4 AE-4 对照组「不覆盖核爆炸导致的疾病」→ 不得判 excluded=True",
          _sto.get("excluded") is False, f"实际 {_sto!r}")
    check("8.4 AE-4 对照组「不覆盖核爆炸导致的疾病」→ 不得**过度收紧**"
          "（allowed 须仍为 True）",
          _sto.get("allowed") is True, f"实际 {_sto!r}")
    # 既有共享族口径零漂移
    for _cl in ("不含重大疾病保障", "重大疾病不在承保范围",
                "重疾不保但含身故保障"):
        check(f"8.4 AE-4 既有共享族口径零漂移：「{_cl}」→ 必须仍判类别级除外",
              PD._crx_clause_excludes_ci_category(_cl) is True,
              f"实际 {PD._crx_clause_excludes_ci_category(_cl)!r}")

    # ── ⑧.5 源码级结构性守卫（把「类」锁死 · 防止复发）──────────────
    #   单一事实源：否定 / 存疑 / 肯定判定**必须**走既有共享 helper，
    #   **不得**新造独立词表（官方每轮复扫只点「其中一份漏掉的短语」）。
    check("8.5 源码级：AE-1 必须走**递归**共享 helper（_structured_subtree_has_text）",
          "_structured_subtree_has_text" in src
          and src.count("_structured_subtree_has_text(") >= 4)
    check("8.5 源码级：AE-2 肯定证据闸门（_crx_ci_affirmative_evidence）必须存在"
          "并被共享状态消费",
          "_crx_ci_affirmative_evidence" in src
          and "has_evidence = _crx_ci_affirmative_evidence(product)" in src)
    check("8.5 源码级：AE-2 validated 必须**依赖**肯定证据（不得再是 absence 口径）",
          "validated = bool(not excluded and not unverified and has_evidence)" in src)
    check("8.5 源码级：AE-4 主体作用域判别 helper（_crx_ci_subject_scope_ok）必须存在",
          "_crx_ci_subject_scope_ok" in src)
    check("8.5 源码级：AE-3 coverage_year 校验 helper 必须存在（_validate_coverage_year）",
          "_validate_coverage_year" in pcsrc
          and "CoverageYearError" in pcsrc)

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
