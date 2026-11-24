import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

from app.main import create_app
from app.retention.service import dispose
from app.review.service import execute, review
from app.review.store import Store
from app.retention.store import DisposalStore


def _approved_run(client):
    run = client.post("/api/runs", data={"sample": "clean"}).json
    client.patch(
        f"/api/runs/{run['id']}",
        json=dict(revision=0, status="APPROVED", note="复核通过准备交接"),
    )
    return run


def _at(run, days=2):
    created = datetime.fromisoformat(run["report"]["manifest"]["created"])
    return (created + timedelta(days=days)).isoformat()


def test_disposal_lifecycle_over_http(client):
    run = _approved_run(client)
    rid = run["id"]
    # 保留期满、无争议 -> 清空
    response = client.post(
        f"/api/runs/{rid}/disposal?retention_days=1",
        json=dict(at=_at(run)),
    )
    assert response.status_code == 200
    assert response.mimetype == "application/json"
    result = response.json
    assert result["schema"] == "retention-disposal/1"
    assert result["disposition"] == "PURGED"
    assert all(row["note"] is None for row in result["voucher"])
    assert result["review"]["note"] is None


def test_page_and_download_read_identical_disposal_bytes(client):
    run = _approved_run(client)
    rid = run["id"]
    client.post(f"/api/runs/{rid}/disposal?retention_days=1", json=dict(at=_at(run)))
    page = client.get(f"/api/runs/{rid}/disposal")
    download = client.get(f"/api/runs/{rid}/disposal/download")
    assert page.status_code == download.status_code == 200
    assert page.data == download.data  # 同一份处置结果
    assert json.loads(page.data)["run_id"] == rid
    assert "attachment" in download.headers["Content-Disposition"]
    assert download.headers["Cache-Control"] == "no-store"
    assert "attachment" not in page.headers.get("Content-Disposition", "")


def test_disposal_retry_is_idempotent_over_http(client):
    run = _approved_run(client)
    rid = run["id"]
    first = client.post(
        f"/api/runs/{rid}/disposal?retention_days=1", json=dict(at=_at(run))
    )
    second = client.post(
        f"/api/runs/{rid}/disposal?retention_days=1",
        json=dict(at=_at(run, 400)),
    )
    assert first.data == second.data
    listing = client.get("/api/disposals").json["items"]
    assert len(listing) == 1 and listing[0]["run_id"] == rid


def test_open_dispute_forces_retention_over_http(client):
    run = _approved_run(client)
    rid = run["id"]
    dispute = client.post(
        f"/api/runs/{rid}/disputes", json=dict(note="金额争议暂停交接")
    ).json
    assert dispute["status"] == "OPEN"
    result = client.post(
        f"/api/runs/{rid}/disposal?retention_days=1", json=dict(at=_at(run))
    ).json
    assert result["disposition"] == "RETAINED"
    assert result["policy"]["reasons"] == ["DISPUTE_OPEN"]
    assert [row["note"] for row in result["voucher"] if row["note"]]
    # 关闭争议后再处置 -> 清空
    client.post(f"/api/disputes/{dispute['dispute_id']}/close")
    purged = client.post(
        f"/api/runs/{rid}/disposal?retention_days=1", json=dict(at=_at(run))
    ).json
    assert purged["disposition"] == "PURGED"
    disputes = client.get(f"/api/runs/{rid}/disputes").json["items"]
    assert len(disputes) == 1 and disputes[0]["status"] == "CLOSED"


def test_disposal_http_error_mappings(client):
    run = client.post("/api/runs", data={"sample": "clean"}).json
    rid = run["id"]
    # 尚无处置结果
    assert client.get(f"/api/runs/{rid}/disposal").status_code == 404
    # 未知批次
    assert client.post("/api/runs/missing/disposal").status_code == 404
    # 保留期非法
    bad = client.post(f"/api/runs/{rid}/disposal?retention_days=0")
    assert bad.status_code == 422 and bad.json["code"] == "RETENTION_FIELDS"
    # 争议说明非法
    bad_note = client.post(f"/api/runs/{rid}/disputes", json=dict(note="短"))
    assert bad_note.status_code == 422 and bad_note.json["code"] == "DISPUTE_FIELDS"
    # 未知争议关闭
    assert client.post("/api/disputes/nope/close").status_code == 404


def test_parallel_disposal_commits_single_record(tmp_path):
    db = tmp_path / "runs.db"
    runs, disposals = Store(db), DisposalStore(db)
    data = (tmp_path / "ready.csv")
    import shutil

    shutil.copy("/workspace/sample_data/ready.csv", data)
    run = execute(runs, data.read_bytes())
    review(runs, run["id"], dict(revision=0, status="APPROVED", note="并行交接复核"))
    at = (
        datetime.fromisoformat(run["report"]["manifest"]["created"])
        + timedelta(days=2)
    ).isoformat()
    barrier = Barrier(4)

    def attempt():
        barrier.wait(3)
        return dispose(runs, disposals, run["id"], 1, at=at)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: attempt(), range(4)))
    assert all(item == results[0] for item in results)
    assert len(disposals.ledger(run["id"])) == 1
    assert len(disposals.list_disposals()) == 1


def test_disposal_does_not_change_review_evidence_contract(client):
    run = client.post("/api/runs", data={"sample": "clean"}).json
    rid = run["id"]
    evidence_before = client.get(f"/api/runs/{rid}/evidence").json
    assert evidence_before["schema"] == "review-evidence/1"
    assert "voucher" not in evidence_before  # 凭据不混入既有证据包
