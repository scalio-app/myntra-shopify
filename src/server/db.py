from __future__ import annotations
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional


DB_PATH: Optional[Path] = None


def init_db(db_path: Path) -> None:
    global DB_PATH
    DB_PATH = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS files (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                path TEXT NOT NULL,
                size INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                params TEXT NOT NULL,
                result_path TEXT,
                error TEXT,
                counters TEXT
            )
            """
        )
        conn.commit()


def add_file(info: Dict) -> None:
    assert DB_PATH is not None
    with sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO files(id,name,path,size,created_at) VALUES(?,?,?,?,?)",
            (info["id"], info["name"], info["path"], int(info["size"]), str(info["created_at"]))
        )
        conn.commit()


def list_files() -> List[Dict]:
    assert DB_PATH is not None
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM files ORDER BY created_at DESC")
        rows = [dict(r) for r in cur.fetchall()]
    return rows


def add_job(job: Dict) -> None:
    assert DB_PATH is not None
    with sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO jobs(id,kind,status,created_at,started_at,finished_at,params,result_path,error,counters) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                job.get("id"), job.get("kind"), job.get("status"), str(job.get("created_at")),
                str(job.get("started_at") or ""), str(job.get("finished_at") or ""),
                json.dumps(job.get("params") or {}), job.get("result_path"), job.get("error"),
                json.dumps(job.get("counters") or {}),
            )
        )
        conn.commit()


def update_job(job: Dict) -> None:
    # Upsert behavior reuse add_job
    add_job(job)


def get_job(job_id: str) -> Optional[Dict]:
    assert DB_PATH is not None
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
        r = cur.fetchone()
        if not r:
            return None
        d = dict(r)
        # Parse JSON fields
        try:
            d["params"] = json.loads(d.get("params") or "{}")
        except Exception:
            d["params"] = {}
        try:
            d["counters"] = json.loads(d.get("counters") or "{}")
        except Exception:
            d["counters"] = {}
        return d


def list_jobs() -> List[Dict]:
    assert DB_PATH is not None
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM jobs ORDER BY created_at DESC")
        rows = []
        for r in cur.fetchall():
            d = dict(r)
            try:
                d["params"] = json.loads(d.get("params") or "{}")
            except Exception:
                d["params"] = {}
            try:
                d["counters"] = json.loads(d.get("counters") or "{}")
            except Exception:
                d["counters"] = {}
            rows.append(d)
    return rows

