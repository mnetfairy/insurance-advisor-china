#!/usr/bin/env python3
"""
Common utilities for datafix scripts.
- Load/save products.json (always v2)
- Backup before destructive operations
- Dry-run support
- Before/after diff logging
"""
import json
import os
import sys
import shutil
import argparse
from datetime import datetime

# Paths (relative to this file: scripts/datafix/lib_common.py)
DATA_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PRODUCTS_V2 = os.path.join(DATA_DIR, "references", "products_v2.json")
PRODUCTS_V1 = os.path.join(DATA_DIR, "references", "products.json")
BACKUPS_DIR = os.path.join(DATA_DIR, "references", "backups")
REPORTS_DIR = os.path.join(DATA_DIR, "scripts", "datafix", "reports")

DEFAULT_NONE_FILL = "未明确"


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


def write_report(name, payload):
    """Write JSON report to reports/ dir."""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    path = os.path.join(REPORTS_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def add_dry_run_arg(parser):
    parser.add_argument("--dry-run", action="store_true",
                        help="Only show what would change; do not write files.")


def die(msg, code=1):
    print(f"[FATAL] {msg}", file=sys.stderr)
    sys.exit(code)


def ok(msg):
    print(f"[OK] {msg}")