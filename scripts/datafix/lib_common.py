#!/usr/bin/env python3
"""
Common utilities for datafix scripts.
- Load/save products.json (always v2)
- Backup before destructive operations
- Dry-run support
- Before/after diff logging

🆕 2026-11-08 ClawHub 安全审计整改（SDI-3 / 越权写入）：

1. **写路径收敛**：本模块所有写操作现在只能落在**本 skill 目录内**的
   `references/products*.json`（以及 `references/backups/` 与 `scripts/datafix/reports/`
   两个配套目录）。任何指向 skill 目录之外的路径一律拒绝并返回**非 0 退出码**。
   以前 `--target` 接受任意路径 → 脚本可被用来改写任意 JSON 文件。
2. **dry-run 零写入**：`--dry-run` 现在**不写任何文件**（含 reports 目录）。
   以前 dry-run 仍会写 JSON 报告，与其 "do not write files" 的帮助文本不符。
"""
import json
import os
import sys
import shutil
import argparse
import fnmatch
from datetime import datetime

# Paths (relative to this file: scripts/datafix/lib_common.py)
DATA_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PRODUCTS_V2 = os.path.join(DATA_DIR, "references", "products_v2.json")
PRODUCTS_V1 = os.path.join(DATA_DIR, "references", "products.json")
BACKUPS_DIR = os.path.join(DATA_DIR, "references", "backups")
REPORTS_DIR = os.path.join(DATA_DIR, "scripts", "datafix", "reports")

DEFAULT_NONE_FILL = "未明确"

# ── 受管写路径白名单（ClawHub SDI-3 整改）────────────────────────────
# 只允许写本 skill 目录内、且文件名形如 references/products*.json 的产品库。
# 不含任何目录穿越（../）、符号链接逃逸（realpath 归一）。
MANAGED_REFS_DIR = os.path.join(DATA_DIR, "references")
MANAGED_TARGET_PATTERN = "products*.json"


def resolve_managed_target(target_path):
    """把写目标路径解析为**本 skill 自有**的 references/products*.json。

    ⚠️ 2026-11-08 整改（SDI-3）：--target 原先接受任意路径 → 脚本可被用来
    改写任意 JSON 文件（越权写库）。现在只接受本 skill 自己目录下的
    `references/products*.json`；其他路径一律拒绝并返回非 0 退出码。

    Returns:
        tuple[str, str | None]: (解析后的绝对路径, 错误信息)；出错时第一项为 None。
    """
    if target_path is None:
        return None, "--target 未指定"

    candidate = os.path.realpath(os.path.abspath(target_path))
    refs_real = os.path.realpath(MANAGED_REFS_DIR)

    # 必须在 references/ 目录内（realpath 已消除 ../ 与符号链接逃逸）
    parent = os.path.dirname(candidate)
    if parent != refs_real:
        return None, (
            f"拒绝操作本 skill 目录之外的路径：{candidate}\n"
            f"仅允许写入：{refs_real}/{MANAGED_TARGET_PATTERN}"
        )

    # 文件名必须形如 products*.json
    if not fnmatch.fnmatch(os.path.basename(candidate), MANAGED_TARGET_PATTERN):
        return None, (
            f"拒绝操作非受管产品库文件：{candidate}\n"
            f"仅允许写入：{refs_real}/{MANAGED_TARGET_PATTERN}"
        )

    return candidate, None


def now_ts():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def load_v2():
    """Load current v2 file (always reads from disk)."""
    with open(PRODUCTS_V2, "r", encoding="utf-8") as f:
        return json.load(f)


def save_v2(data):
    """Write v2 file (atomic: tmp + rename)."""
    tmp = PRODUCTS_V2 + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PRODUCTS_V2)


def backup_v2(label):
    """Backup current v2 file. label = e.g. 'pre_P0-1'."""
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    ts = now_ts()
    dst = os.path.join(BACKUPS_DIR, f"products_v2_{label}_{ts}.json")
    shutil.copy2(PRODUCTS_V2, dst)
    return dst


def write_report(name, payload, dry_run=False):
    """Write JSON report to reports/ dir.

    ⚠️ 2026-11-08 整改（SDI-3）：dry-run 必须**零写入**。
    以前无论是否 --dry-run 都会写 reports/ 目录，与 "do not write files" 的
    帮助文本不符。现在 dry_run=True 时只返回目标路径，不落盘。
    """
    path = os.path.join(REPORTS_DIR, name)
    if dry_run:
        return path
    os.makedirs(REPORTS_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def add_dry_run_arg(parser):
    parser.add_argument("--dry-run", action="store_true",
                        help="Only show what would change; no file is written "
                             "(including the reports/ directory).")


def die(msg, code=1):
    print(f"[FATAL] {msg}", file=sys.stderr)
    sys.exit(code)


def ok(msg):
    print(f"[OK] {msg}")