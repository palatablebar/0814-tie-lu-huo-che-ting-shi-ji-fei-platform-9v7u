from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE = 256 * 1024
MAX_ROWS = 2000
RULE_VERSION = "1.0.0"
# 月末交接凭据默认保留期限（天）：自批次执行时刻起算
DEFAULT_RETENTION_DAYS = 1825
