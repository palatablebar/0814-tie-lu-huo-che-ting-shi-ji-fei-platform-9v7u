import json
import sqlite3
from contextlib import closing, contextmanager
from hashlib import sha256
from pathlib import Path

from app.business import DomainIssue

SCHEMA = """
CREATE TABLE IF NOT EXISTS disposals (
    run_id TEXT PRIMARY KEY,
    seq INTEGER NOT NULL,
    disposition TEXT NOT NULL,
    basis_hash TEXT NOT NULL,
    payload TEXT NOT NULL,
    created TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_disposals_basis
    ON disposals(run_id, basis_hash);
CREATE TABLE IF NOT EXISTS disposal_ledger (
    version_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    disposition TEXT NOT NULL,
    basis_hash TEXT NOT NULL,
    payload TEXT NOT NULL,
    created TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ledger_basis
    ON disposal_ledger(run_id, basis_hash);
CREATE TABLE IF NOT EXISTS disputes (
    dispute_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    status TEXT NOT NULL,
    opened TEXT NOT NULL,
    closed TEXT,
    note TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_disputes_run ON disputes(run_id);
"""


class DisposalStore:
    """与批次库共用同一个 SQLite 文件。所有写操作在单事务内提交，
    任何一步失败整体回滚，旧版本处置结果与原凭据都不受影响。"""

    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=15)) as db, db:
            db.row_factory = sqlite3.Row
            db.executescript(SCHEMA)
            yield db

    # ---- 处置结果 ----
    def get_disposal(self, run_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM disposals WHERE run_id=?", (run_id,)
            ).fetchone()
        if row is None:
            raise DomainIssue("DISPOSAL_NOT_FOUND")
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        return result

    def same_basis_exists(self, run_id, basis_hash):
        with self.connect() as db:
            row = db.execute(
                "SELECT 1 FROM disposals WHERE run_id=? AND basis_hash=?",
                (run_id, basis_hash),
            ).fetchone()
        return row is not None

    def next_seq(self, db, run_id):
        row = db.execute(
            "SELECT seq FROM disposals WHERE run_id=?", (run_id,)
        ).fetchone()
        return 1 if row is None else row["seq"] + 1

    def commit_disposal(self, run, result, now):
        """单事务写入当前处置结果、追加版本台账；PURGED 时同步清空批次库。

        并行同依据提交触发唯一约束时抛 sqlite3.IntegrityError，由服务层
        回退读取，调用方据此走幂等路径。"""
        run_id = run["id"]
        payload = json.dumps(result, ensure_ascii=False, sort_keys=True)
        with self.connect() as db:
            seq = self.next_seq(db, run_id)
            version_id = sha256(f"{run_id}:{seq}:{now}".encode()).hexdigest()
            db.execute(
                "INSERT INTO disposal_ledger(version_id,run_id,seq,disposition,basis_hash,payload,created)"
                " VALUES (?,?,?,?,?,?,?)",
                (
                    version_id,
                    run_id,
                    seq,
                    result["disposition"],
                    result["basis_hash"],
                    payload,
                    now,
                ),
            )
            db.execute(
                "INSERT INTO disposals(run_id,seq,disposition,basis_hash,payload,created)"
                " VALUES (?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET"
                " seq=excluded.seq, disposition=excluded.disposition,"
                " basis_hash=excluded.basis_hash, payload=excluded.payload,"
                " created=excluded.created",
                (run_id, seq, result["disposition"], result["basis_hash"], payload, now),
            )
            if result["disposition"] == "PURGED":
                # 同事务清空批次库中的敏感值（凭据说明列与复核意见），
                # 任一步失败则整批回滚，旧版本处置结果与原凭据均保留
                cursor = db.execute(
                    "UPDATE runs SET voucher=?, note='' WHERE id=?",
                    (
                        json.dumps(run["voucher"], ensure_ascii=False),
                        run_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise DomainIssue("RUN_NOT_FOUND")

    def list_disposals(self):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT run_id,seq,disposition,basis_hash,created FROM disposals"
                    " ORDER BY created DESC, run_id LIMIT 50"
                )
            ]

    def ledger(self, run_id):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT version_id,seq,disposition,basis_hash,created"
                    " FROM disposal_ledger WHERE run_id=? ORDER BY seq",
                    (run_id,),
                )
            ]

    # ---- 争议登记 ----
    def count_open_disputes(self, run_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT COUNT(*) AS n FROM disputes WHERE run_id=? AND status='OPEN'",
                (run_id,),
            ).fetchone()
        return row["n"]

    def list_disputes(self, run_id):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT dispute_id,run_id,status,opened,closed,note"
                    " FROM disputes WHERE run_id=? ORDER BY opened",
                    (run_id,),
                )
            ]

    def insert_dispute(self, dispute_id, run_id, note, now):
        with self.connect() as db:
            db.execute(
                "INSERT INTO disputes(dispute_id,run_id,status,opened,closed,note)"
                " VALUES (?,?,'OPEN',?,NULL,?)",
                (dispute_id, run_id, now, note),
            )

    def close_dispute(self, dispute_id, now):
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE disputes SET status='CLOSED', closed=? WHERE dispute_id=? AND status='OPEN'",
                (now, dispute_id),
            )
            if cursor.rowcount != 1:
                raise DomainIssue("DISPUTE_NOT_FOUND")
