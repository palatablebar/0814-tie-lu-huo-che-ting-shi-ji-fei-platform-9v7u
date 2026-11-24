"""月末交接处置编排。

处置任务以批次为单位、以"处置依据"为幂等键：同一批次在相同依据
（保留期限、未结争议数、签发状态、批次版本）下重试，只返回既有处置
结果，不新增处置记录，也不会重复清空。决策时刻仅作记录、不入键。
"""

import json
import sqlite3
from datetime import datetime, timezone
from hashlib import sha256

from app.retention.policy import PURGE, decide, parse_moment, parse_retention_days
from app.retention.redact import CLEARED, SENSITIVE_FIELDS, redact_voucher


def now_text():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _basis(run, open_disputes, retention_days, moment):
    # 决策时刻只作记录，不参与幂等键：同一处置任务跨时刻重试不新增记录
    return {
        "run_id": run["id"],
        "run_revision": run["revision"],
        "review_status": run["status"],
        "open_disputes": open_disputes,
        "retention_days": retention_days,
        "at": moment.isoformat(timespec="milliseconds"),
    }


def _idempotency_basis(basis):
    return {key: value for key, value in basis.items() if key != "at"}


def _voucher(run):
    """结构化原凭据：记录键、业务组、类型、分钟段、金额与说明列。"""
    return list(run.get("voucher", []))


def dispose(runs, store, run_id, retention_days=None, at=None):
    """对单个批次执行月末处置，返回处置结果字典。"""
    run = runs.load(run_id)
    days = parse_retention_days(retention_days)
    moment = parse_moment(at)
    open_disputes = store.count_open_disputes(run_id)
    basis = _basis(run, open_disputes, days, moment)
    basis_hash = sha256(_canonical(_idempotency_basis(basis)).encode()).hexdigest()

    # 幂等：相同处置依据直接返回当前版本，不新增处置记录
    if store.same_basis_exists(run_id, basis_hash):
        return store.get_disposal(run_id)["payload"]

    disposition, reasons, expires = decide(run, open_disputes, days, moment)
    voucher = _voucher(run)
    review_note = run["note"]
    purged_fields = []
    if disposition == PURGE:
        purged_fields = list(SENSITIVE_FIELDS)
        voucher = redact_voucher(voucher)
        review_note = CLEARED
        # 同一份脱敏结果随处置事务写回批次库凭据列
        run["voucher"] = voucher
        run["note"] = ""

    result = {
        "schema": "retention-disposal/1",
        "run_id": run_id,
        "disposition": disposition,
        "basis_hash": basis_hash,
        "basis": basis,
        "policy": {
            "retention_days": days,
            "retain_until": expires.isoformat(timespec="milliseconds"),
            "decided_at": moment.isoformat(timespec="milliseconds"),
            "reasons": reasons,
            "open_disputes": open_disputes,
        },
        "reconciliation": {
            # 记录键（含前导零）、业务分组来源关系与金额保持可核对
            "record_keys": [row["record"] for row in voucher],
            "cases": sorted({row["case"] for row in voucher}),
            "amounts_cents": {
                row["record"]: row["amount_cents"]
                for row in voucher
                if row["kind"] == "invoice"
            },
            "voucher_rows": len(voucher),
        },
        "voucher": voucher,
        "review": {
            "status": run["status"],
            "revision": run["revision"],
            "reviewed": run["reviewed"],
            "note": review_note,
        },
        "redaction": {
            "sensitive_fields": list(SENSITIVE_FIELDS),
            "purged_fields": purged_fields,
            "cleared_value": CLEARED,
        },
    }
    try:
        store.commit_disposal(run, result, now_text())
    except sqlite3.IntegrityError:
        # 并行同依据处置：另一个事务已提交，回退读取既有结果，不新增记录
        return store.get_disposal(run_id)["payload"]
    return result


def get_result(store, run_id):
    return store.get_disposal(run_id)["payload"]
