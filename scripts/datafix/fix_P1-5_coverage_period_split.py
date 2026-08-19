#!/usr/bin/env python3
"""
Phase 1 P1-5: Split coverage_period heterogeneous values into 3+ structured fields.

Master spec:
  > P1-5：`coverage_period` 异构值拆分
  > 39 种异构值
  > 修复策略：拆为 3 个字段
  >   `coverage_period_duration_value`（数值：30/70/终身/1）
  >   `coverage_period_duration_unit`（单位：年/周岁/终身）
  >   `coverage_period_guaranteed_renewable`（bool：是否保证续保）
  > **不要破坏原数据**，保留 `coverage_period` 原值，增 3 个新字段

Per QA feedback:
  - 75 unique values (more than 39 expected)
  - Must handle None / 'None' / '未明确' explicitly
  - Must handle '1年（保证续保20年）' → guaranteed_renewable=True, duration_value=1
  - Must handle dash-separated values like '综合意外险-终身' (split on - and take right side)
  - Per SA design, also add duration_unit='to_age' for 至X周岁 values

Master spec says 3 fields:
  - coverage_period_duration_value
  - coverage_period_duration_unit
  - coverage_period_guaranteed_renewable

But for '终身' we want a flag. Per SA design we add coverage_period_is_lifetime: bool.
That's 4 new fields. Master said "3 fields" but the data needs 4 for completeness.
I'll add is_lifetime and also add parse_quality for traceability.

Idempotent.
"""
import argparse
import os
import re
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)
from lib_common import load_v2, save_v2, backup_v2, write_report, add_dry_run_arg

RE_TO_AGE = re.compile(r"至\s*(\d+)\s*周岁")
RE_YEARS = re.compile(r"(\d+)\s*年")
RE_GUARANTEE = re.compile(r"(\d+)\s*年保证续保|保证续保\s*(\d+)\s*年")
RE_AGE_NUM = re.compile(r"\d+")


def parse_coverage_period(raw):
    """Parse coverage_period into structured fields.
    Returns dict with: duration_value, duration_unit, is_lifetime, guaranteed_renewable, parse_quality, parse_failed_reason.
    """
    result = {
        "coverage_period_duration_value": None,
        "coverage_period_duration_unit": None,
        "coverage_period_is_lifetime": False,
        "coverage_period_guaranteed_renewable": False,
        "coverage_period_parse_quality": "unknown",
    }

    if raw is None:
        result["coverage_period_parse_quality"] = "missing"
        return result

    if not isinstance(raw, str):
        result["coverage_period_parse_quality"] = "missing"
        return result

    s = raw.strip()

    # Filler values
    if s in ("", "None", "无", "未知", "待核实", "未明确"):
        result["coverage_period_parse_quality"] = "missing"
        return result

    if s == "按约定":
        result["coverage_period_parse_quality"] = "ambiguous_约定"
        return result

    if s == "至约定年龄" or s == "至约定年龄/满期" or s == "至约定年龄/约定期间":
        result["coverage_period_parse_quality"] = "ambiguous_约定"
        return result

    if s == "与主险同期":
        result["coverage_period_parse_quality"] = "depends_on_main"
        return result

    if s == "至妊娠结束":
        result["coverage_period_parse_quality"] = "pregnancy_end"
        return result

    if s == "积累期+领取期":
        result["coverage_period_parse_quality"] = "accumulation_then_payout"
        return result

    if s == "三年滚动持有":
        result["coverage_period_duration_value"] = 3
        result["coverage_period_duration_unit"] = "rolling_year"
        result["coverage_period_parse_quality"] = "parsed"
        return result

    # Dash split: take right side
    # "综合意外险-终身" → "终身"
    if "-" in s or "—" in s:
        parts = re.split(r"[-—]", s)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) >= 2:
            # Take last part as the period
            s_period = parts[-1]
            s_type = parts[0]  # ignored for now (type info)
            s = s_period

    # Check lifetime
    has_lifetime = "终身" in s
    # Check guaranteed renewable (e.g. "20年保证续保" or "1年（保证续保20年）")
    m = RE_GUARANTEE.search(s)
    has_guarantee = m is not None
    if has_guarantee:
        grp = m.group(1) or m.group(2)
        if grp:
            result["coverage_period_guaranteed_renewable"] = True
            result.setdefault("coverage_period_parse_notes", []).append(
                f"guaranteed_renewable_{grp}年"
            )

    # 至X周岁 (to age) — only if 周岁 is present AND not mixed with 年 in confusing way
    if "周岁" in s:
        # Extract ages (digits after 周岁 or before it if near 至)
        # Find first age before 周岁
        m = re.search(r"(\d+)\s*周岁", s)
        if m:
            age = int(m.group(1))
            result["coverage_period_duration_value"] = age
            result["coverage_period_duration_unit"] = "to_age"
            result["coverage_period_parse_quality"] = "parsed"
            # If multiple ages in 周岁 pattern
            ages_all = re.findall(r"(\d+)\s*周岁", s)
            if len(ages_all) > 1:
                result.setdefault("coverage_period_parse_notes", []).append(
                    f"multiple_ages_{ages_all}"
                )
            # Also flag lifetime if both present
            if has_lifetime:
                result["coverage_period_is_lifetime"] = True
                result.setdefault("coverage_period_parse_notes", []).append("has_lifetime_option")
            return result

    # X年 (years)
    m = RE_YEARS.search(s)
    if m:
        years = int(m.group(1))
        # First X年 is the duration
        result["coverage_period_duration_value"] = years
        result["coverage_period_duration_unit"] = "year"
        result["coverage_period_parse_quality"] = "parsed"
        # Multiple years like "10/20/30年" → take first
        ms = re.findall(r"(\d+)\s*年", s)
        if len(ms) > 1:
            result["coverage_period_duration_value"] = int(ms[0])
            result.setdefault("coverage_period_parse_notes", []).append(
                f"multiple_years_{ms}"
            )
        return result

    # Special markers like "短期", "1年可续保" → 1 year short_term
    if "1年" in s or "短期" in s or "可续保" in s:
        result["coverage_period_duration_value"] = 1
        result["coverage_period_duration_unit"] = "year_short"
        result["coverage_period_parse_quality"] = "parsed"
        return result

    if "定期" in s:
        result["coverage_period_parse_quality"] = "ambiguous_term"
        return result

    if "长期" in s:
        result["coverage_period_duration_unit"] = "long_term"
        result["coverage_period_parse_quality"] = "parsed_long"
        # Check for 保证续保
        if "保证续保" in s:
            result["coverage_period_guaranteed_renewable"] = True
            result["coverage_period_parse_quality"] = "parsed"
            result.setdefault("coverage_period_parse_notes", []).append("long_term_with_guaranteed_renewable")
        return result

    # If we got here and didn't parse, mark failed
    if has_lifetime:
        # Pure lifetime or has-lifetime marker we didn't fully parse
        result["coverage_period_is_lifetime"] = True
        result["coverage_period_duration_unit"] = "lifetime"
        result["coverage_period_parse_quality"] = "parsed"
        return result

    result["coverage_period_parse_quality"] = "parse_failed"
    result["coverage_period_parse_failed_reason"] = f"unrecognized({s[:30]})"
    return result


def fix(data, dry_run=False):
    prods = data["products"]
    diff = []
    counters = {
        "missing": 0,
        "parsed": 0,
        "ambiguous_term": 0,
        "ambiguous_约定": 0,
        "parse_failed": 0,
    }

    for idx, p in enumerate(prods):
        if p.get("coverage_period_split_at"):
            continue

        raw = p.get("coverage_period")
        result = parse_coverage_period(raw)
        counters[result["coverage_period_parse_quality"]] = counters.get(result["coverage_period_parse_quality"], 0) + 1

        record = {
            "index": idx,
            "id": p.get("id", "<<no-id>>"),
            "raw_coverage_period": raw,
            **result,
        }
        diff.append(record)

        if not dry_run:
            notes = result.pop("coverage_period_parse_notes", None)
            for k, v in result.items():
                p[k] = v
            if notes:
                p["coverage_period_parse_notes"] = notes
            p["coverage_period_split_at"] = "phase1_P1-5"

    return diff, counters


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_dry_run_arg(parser)
    args = parser.parse_args()

    print("=" * 60)
    print("Phase 1 P1-5: split coverage_period → 4 structured fields (v2)")
    print("=" * 60)

    data = load_v2()
    n_already = sum(1 for p in data["products"] if p.get("coverage_period_split_at"))
    print(f"Already processed: {n_already} products")

    diff, counters = fix(data, dry_run=args.dry_run)

    print(f"\nParse quality counters: {counters}")

    print(f"\nSample diffs (variety, first 20):")
    seen_qualities = set()
    samples = []
    for d in diff:
        q = d.get("coverage_period_parse_quality", "?")
        if q not in seen_qualities:
            seen_qualities.add(q)
            samples.append(d)
        if len(samples) >= 20:
            break
    for d in samples:
        v = d.get("coverage_period_duration_value")
        u = d.get("coverage_period_duration_unit")
        lt = d.get("coverage_period_is_lifetime")
        gr = d.get("coverage_period_guaranteed_renewable")
        notes = d.get("coverage_period_parse_notes", [])
        print(f"  [{d['index']:4d}] id={d['id'][:25]:25s}  raw={str(d['raw_coverage_period'])[:25]:25s} → "
              f"value={v} unit={u} lifetime={lt} renewable={gr} quality={d['coverage_period_parse_quality']} notes={notes}")

    report = {
        "fix": "P1-5 (coverage_period split)",
        "policy": "Add 4 fields: duration_value/unit/is_lifetime/guaranteed_renewable; preserve coverage_period",
        "counters": counters,
        "samples": samples,
        "field_names": [
            "coverage_period_duration_value",
            "coverage_period_duration_unit",
            "coverage_period_is_lifetime",
            "coverage_period_guaranteed_renewable",
            "coverage_period_parse_quality",
        ],
        "dry_run": args.dry_run,
    }
    rp = write_report("P1-5_coverage_period_split_report.json", report)
    print(f"\nReport: {rp}")

    if args.dry_run:
        print("[DRY RUN] Not writing products_v2.json")
        return 0

    if diff:
        bk = backup_v2("pre_P1-5_coverage_period_split")
        save_v2(data)
        print(f"Backup: {bk}")
        print(f"[OK] Saved products_v2.json")

    return 0


if __name__ == "__main__":
    sys.exit(main())