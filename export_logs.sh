#!/bin/bash
# === export_logs.sh ===
# 导出 query_logs 到 CSV 并清理90天前的旧记录

# === 可自定义部分 ===
DB_NAME="docragdb"
DB_USER="raguser"
DB_HOST="127.0.0.1"
EXPORT_DIR="$HOME/projects/log_exports"
DAYS_TO_KEEP=90

# === 准备导出目录 ===
mkdir -p "$EXPORT_DIR"

# 生成带日期的文件名
DATE_TAG=$(date +%Y%m%d_%H%M%S)
EXPORT_FILE="${EXPORT_DIR}/query_logs_${DATE_TAG}.csv"

echo "📦 Exporting query_logs to $EXPORT_FILE ..."

# === 导出CSV ===
psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -c "\COPY (
  SELECT id, created_at, bucket, query, answer
  FROM query_logs
  ORDER BY id
) TO '${EXPORT_FILE}' WITH CSV HEADER;" 

if [ $? -eq 0 ]; then
  echo "✅ Export success: $EXPORT_FILE"
else
  echo "❌ Export failed"
  exit 1
fi

# === 清理旧记录 ===
echo "🧹 Cleaning logs older than ${DAYS_TO_KEEP} days..."
psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -c "
  DELETE FROM query_logs WHERE created_at < now() - interval '${DAYS_TO_KEEP} days';
  VACUUM ANALYZE query_logs;
"

echo "✅ Cleanup done."
echo "All done! 🎉"
