#!/bin/bash
# 同步产品数据库到 ai-insurance-advisor
SOURCE="$HOME/.openclaw/workspace/skills/insurance-advisor-china/references/products.json"
TARGET="$HOME/.openclaw/workspace/skills/ai-insurance-advisor/references/products.json"
cp "$SOURCE" "$TARGET"
echo "已同步: insurance-advisor-china -> ai-insurance-advisor ($(date))"
