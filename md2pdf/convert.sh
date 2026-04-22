#!/usr/bin/env bash
# 将 PPT/log_llm.md 转换为 PDF
# 用法：bash md2pdf/convert.sh [input.md] [output.pdf]
#
# 依赖：md2pdf/node_modules/.bin/md-to-pdf（本地安装）
#       /usr/bin/google-chrome（系统 Chrome）

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MD_TO_PDF="$SCRIPT_DIR/node_modules/.bin/md-to-pdf"
CHROME="/usr/bin/google-chrome"

INPUT="${1:-$SCRIPT_DIR/../log_llm.md}"
OUTPUT="${2:-${INPUT%.md}.pdf}"

if [[ ! -f "$INPUT" ]]; then
  echo "❌ 文件不存在: $INPUT"
  exit 1
fi

PUPPETEER_EXECUTABLE_PATH="$CHROME" \
  node "$MD_TO_PDF" \
  --launch-options "{\"executablePath\":\"$CHROME\",\"args\":[\"--no-sandbox\",\"--disable-setuid-sandbox\"]}" \
  --pdf-options '{"format":"A4","margin":{"top":"20mm","bottom":"20mm","left":"15mm","right":"15mm"}}' \
  --stylesheet "$SCRIPT_DIR/style.css" \
  --config-file "$SCRIPT_DIR/mermaid-config.json" \
  "$INPUT" 2>&1

if [[ $? -eq 0 ]]; then
  echo "✅ PDF 已生成: $OUTPUT"
else
  echo "❌ 转换失败"
  exit 1
fi
