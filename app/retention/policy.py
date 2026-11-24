"""月末交接处置策略：依据批次签发、争议状态与保留期限决定每批处置结果。"""

from datetime import datetime, timedelta, timezone

from app.config import DEFAULT_RETENTION_DAYS
from app.business import DomainIssue

# 处置结论
RETAIN = "RETAINED"
PURGE = "PURGED"


def parse_retention_days(value):
    if value is None:
        return DEFAULT_RETENTION_DAYS
    if isinstance(value, bool):
        raise DomainIssue("RETENTION_FIELDS")
    if isinstance(value, int):
        days = value
    elif isinstance(value, str):
        text = value.strip()
        if not text or not text.lstrip("-").isdigit():
            raise DomainIssue("RETENTION_FIELDS")
        days = int(text)
    else:
        raise DomainIssue("RETENTION_FIELDS")
    if not 1 <= days <= 36500:
        raise DomainIssue("RETENTION_FIELDS")
    return days


def parse_moment(value):
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            raise DomainIssue("RETENTION_FIELDS")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def decide(run, open_disputes, retention_days, now):
    """返回 (disposition, reasons, expires)。理由按优先级固定顺序，便于审计。"""
    created = datetime.fromisoformat(run["report"]["manifest"]["created"])
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    expires = created + timedelta(days=retention_days)
    expired = now >= expires
    approved = run["status"] == "APPROVED"
    reasons = []
    if not approved:
        reasons.append("BATCH_NOT_APPROVED")
    if open_disputes:
        reasons.append("DISPUTE_OPEN")
    if not expired:
        reasons.append("RETENTION_NOT_DUE")
    disposition = PURGE if not reasons else RETAIN
    return disposition, reasons, expires
