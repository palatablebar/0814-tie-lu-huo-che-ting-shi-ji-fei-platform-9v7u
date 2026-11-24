"""争议登记：争议未结的批次在月末处置中必须完整保留原凭据。"""

from hashlib import sha256

from app.business import DomainIssue
from app.retention.service import now_text


def open_dispute(runs, store, run_id, values):
    if not isinstance(values, dict):
        raise DomainIssue("DISPUTE_FIELDS")
    note = values.get("note")
    if not isinstance(note, str) or not (3 <= len(note.strip()) <= 200):
        raise DomainIssue("DISPUTE_FIELDS")
    run = runs.load(run_id)  # 批次不存在抛 RUN_NOT_FOUND
    note = note.strip()
    if store.count_open_disputes(run_id):
        raise DomainIssue("DISPUTE_DUPLICATE")
    stamp = now_text()
    dispute_id = sha256(
        f"{run_id}:{stamp}:{note}".encode()
    ).hexdigest()
    store.insert_dispute(dispute_id, run_id, note, stamp)
    return dict(
        dispute_id=dispute_id,
        run_id=run_id,
        status="OPEN",
        opened=stamp,
        closed=None,
        note=note,
    )


def close_dispute(store, dispute_id):
    stamp = now_text()
    store.close_dispute(dispute_id, stamp)
    return dict(dispute_id=dispute_id, status="CLOSED", closed=stamp)


def list_disputes(store, run_id):
    return store.list_disputes(run_id)
