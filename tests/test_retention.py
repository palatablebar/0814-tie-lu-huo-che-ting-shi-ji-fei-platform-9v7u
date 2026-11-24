import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.business import DomainIssue
from app.retention.disputes import close_dispute, list_disputes, open_dispute
from app.retention.policy import PURGE, RETAIN
from app.retention.render import render
from app.retention.service import dispose, get_result
from app.retention.store import DisposalStore
from app.review.service import execute, review


def _future(run, days=2):
    created = datetime.fromisoformat(run["report"]["manifest"]["created"])
    return (created + timedelta(days=days)).isoformat()


def _approve(runs, run_id, note="源文件已复核通过可以交接"):
    return review(
        runs, run_id, dict(revision=0, status="APPROVED", note=note)
    )


# ---- 策略判定 ----
def test_unapproved_batch_is_retained_even_past_retention(store, disposal, clean):
    run = execute(store, clean)
    result = dispose(store, disposal, run["id"], 1, at=_future(run))
    assert result["disposition"] == RETAIN
    assert "BATCH_NOT_APPROVED" in result["policy"]["reasons"]
    assert all(row["note"] for row in result["voucher"])


def test_open_dispute_keeps_original_voucher_intact(store, disposal, clean):
    run = execute(store, clean)
    _approve(store, run["id"])
    dispute = open_dispute(store, disposal, run["id"], dict(note="金额争议待复核"))
    original = execute(store, clean)["voucher"]
    result = dispose(store, disposal, run["id"], 1, at=_future(run))
    assert result["disposition"] == RETAIN
    assert result["policy"] == {
        **result["policy"],
        "open_disputes": 1,
        "reasons": ["DISPUTE_OPEN"],
    }
    # 原凭据完整保留：说明列逐行一致
    assert [v["note"] for v in result["voucher"]] == [v["note"] for v in original]
    assert result["review"]["note"] == "源文件已复核通过可以交接"
    assert dispute["status"] == "OPEN"
    # 批次库中的原凭据同样未被改动
    assert store.load(run["id"])["voucher"] == original


def test_retention_not_due_blocks_purge(store, disposal, clean):
    run = execute(store, clean)
    _approve(store, run["id"])
    result = dispose(store, disposal, run["id"], 36500, at=_future(run))
    assert result["disposition"] == RETAIN
    assert result["policy"]["reasons"] == ["RETENTION_NOT_DUE"]
    assert result["policy"]["retain_until"] > result["policy"]["decided_at"]


def test_expired_without_dispute_purges_sensitive_values(store, disposal, clean):
    run = execute(store, clean)
    _approve(store, run["id"], note="复核意见含敏感措辞")
    result = dispose(store, disposal, run["id"], 1, at=_future(run))
    assert result["disposition"] == PURGE
    assert result["policy"]["reasons"] == []
    assert result["redaction"]["purged_fields"] == [
        "voucher[].note",
        "review_note",
    ]
    assert all(row["note"] is None for row in result["voucher"])
    assert result["review"]["note"] is None


def test_purged_result_cannot_reconstruct_sensitive_text(store, disposal, clean):
    run = execute(store, clean)
    sensitive = [row["note"] for row in run["voucher"]] + ["复核意见含敏感措辞"]
    _approve(store, run["id"], note=sensitive[-1])
    dispose(store, disposal, run["id"], 1, at=_future(run))
    blob = render(get_result(disposal, run["id"])).decode("utf-8")
    # 处置结果与底层库中都找不到任何敏感原文，也没有其哈希
    for text in sensitive:
        assert text not in blob
        assert __import__("hashlib").sha256(text.encode()).hexdigest() not in blob
    db_blob = json.dumps(disposal.get_disposal(run["id"]), ensure_ascii=False)
    assert all(text not in db_blob for text in sensitive)


def test_purge_keeps_keys_amounts_and_source_relations(store, disposal, clean):
    run = execute(store, clean)
    before = {v["record"]: v for v in run["voucher"]}
    _approve(store, run["id"])
    result = dispose(store, disposal, run["id"], 1, at=_future(run))
    after = {v["record"]: v for v in result["voucher"]}
    assert set(before) == set(after)  # 记录键（含前导零）不丢不改
    for key, row in before.items():
        kept = after[key]
        assert kept["case"] == row["case"]  # 来源分组关系
        assert kept["kind"] == row["kind"]
        assert kept["amount_cents"] == row["amount_cents"]  # 金额
        assert kept["start_min"] == row["start_min"]
        assert kept["end_min"] == row["end_min"]
        assert kept["free_min"] == row["free_min"]
    recon = result["reconciliation"]
    assert recon["amounts_cents"] == {"000104": 240, "000204": 0}
    assert recon["cases"] == ["0001", "0002"]
    assert recon["voucher_rows"] == 8
    # 补录记录（pause 行）仍在，仅说明列被清空
    assert "000103" in recon["record_keys"]
    assert after["000103"]["kind"] == "pause" and after["000103"]["note"] is None


# ---- 幂等 ----
def test_retry_same_task_adds_no_disposal_record(store, disposal, clean):
    run = execute(store, clean)
    _approve(store, run["id"])
    first = dispose(store, disposal, run["id"], 1, at=_future(run))
    later = (
        datetime.fromisoformat(first["policy"]["decided_at"]) + timedelta(days=9)
    ).isoformat()
    second = dispose(store, disposal, run["id"], 1, at=later)
    assert first == second
    assert len(disposal.ledger(run["id"])) == 1
    assert len(disposal.list_disposals()) == 1


def test_changed_basis_creates_new_version_but_keeps_history(store, disposal, clean):
    run = execute(store, clean)
    _approve(store, run["id"])
    first = dispose(store, disposal, run["id"], 1, at=_future(run))
    assert first["disposition"] == PURGE
    dispute = open_dispute(store, disposal, run["id"], dict(note="新争议需要复核"))
    second = dispose(store, disposal, run["id"], 1, at=_future(run, 30))
    assert second["disposition"] == RETAIN
    ledger = disposal.ledger(run["id"])
    assert [row["seq"] for row in ledger] == [1, 2]
    assert [row["disposition"] for row in ledger] == [PURGE, RETAIN]
    # 当前版本即最新，旧版本仍可在台账中审计
    current = get_result(disposal, run["id"])
    assert current["basis_hash"] == second["basis_hash"]
    close_dispute(disposal, dispute["dispute_id"])


def test_retry_after_purge_does_not_touch_records_again(store, disposal, clean):
    run = execute(store, clean)
    _approve(store, run["id"])
    dispose(store, disposal, run["id"], 1, at=_future(run))
    snapshot = store.load(run["id"])["voucher"]
    dispose(store, disposal, run["id"], 1, at=_future(run, 400))
    assert store.load(run["id"])["voucher"] == snapshot
    assert len(disposal.ledger(run["id"])) == 1


# ---- 事务失败保留旧版本 ----
class FailingStore(DisposalStore):
    def __init__(self, path, fail_on):
        super().__init__(path)
        self.fail_on = fail_on
        self.calls = 0

    def commit_disposal(self, run, result, now):
        self.calls += 1
        if self.calls >= self.fail_on:
            raise RuntimeError("注入的交接失败")
        return super().commit_disposal(run, result, now)


def test_failed_handoff_keeps_previous_version(store, clean):
    run = execute(store, clean)
    _approve(store, run["id"])
    db_path = Path(store.path)
    first_store = FailingStore(db_path, fail_on=99)
    retained = dispose(store, first_store, run["id"], 36500, at=_future(run))
    assert retained["disposition"] == RETAIN
    # 第二次处置本应 PURGE，但提交阶段失败：旧版本与原凭据必须保留
    failing = FailingStore(db_path, fail_on=1)
    with pytest.raises(RuntimeError, match="注入的交接失败"):
        dispose(store, failing, run["id"], 1, at=_future(run))
    current = get_result(first_store, run["id"])
    assert current["disposition"] == RETAIN  # 旧处置结果仍在
    assert current == retained
    assert [row["seq"] for row in first_store.ledger(run["id"])] == [1]
    # 批次库原凭据未被清空
    assert all(row["note"] for row in store.load(run["id"])["voucher"])
    assert store.load(run["id"])["note"] == "源文件已复核通过可以交接"


# ---- 争议登记规则 ----
def test_dispute_validation_and_duplicate(store, disposal, clean):
    run = execute(store, clean)
    with pytest.raises(DomainIssue, match="DISPUTE_FIELDS"):
        open_dispute(store, disposal, run["id"], dict(note="短"))
    with pytest.raises(DomainIssue, match="DISPUTE_FIELDS"):
        open_dispute(store, disposal, run["id"], "不是字典")
    dispute = open_dispute(store, disposal, run["id"], dict(note="  金额争议  "))
    assert dispute["note"] == "金额争议"
    with pytest.raises(DomainIssue, match="DISPUTE_DUPLICATE"):
        open_dispute(store, disposal, run["id"], dict(note="再次登记争议"))
    close_dispute(disposal, dispute["dispute_id"])
    # 关闭后可重新登记
    again = open_dispute(store, disposal, run["id"], dict(note="第二轮争议登记"))
    assert again["status"] == "OPEN"
    assert len(list_disputes(disposal, run["id"])) == 2


def test_close_unknown_dispute_404(store, disposal, clean):
    execute(store, clean)
    with pytest.raises(DomainIssue, match="DISPUTE_NOT_FOUND"):
        close_dispute(disposal, "missing")


def test_dispute_on_unknown_run_404(store, disposal):
    with pytest.raises(DomainIssue, match="RUN_NOT_FOUND"):
        open_dispute(store, disposal, "unknown", dict(note="争议说明文字"))


# ---- 保留期限参数 ----
@pytest.mark.parametrize("bad", [0, -1, 36501, "abc", True, 1.5])
def test_retention_days_validation(store, disposal, clean, bad):
    run = execute(store, clean)
    with pytest.raises(DomainIssue, match="RETENTION_FIELDS"):
        dispose(store, disposal, run["id"], bad, at=_future(run))


def test_disposal_without_result_404(store, disposal, clean):
    run = execute(store, clean)
    with pytest.raises(DomainIssue, match="DISPOSAL_NOT_FOUND"):
        get_result(disposal, run["id"])
